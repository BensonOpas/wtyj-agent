# OUTPUT 146 — Adamus Second-Client Deployment

## What was done

### Code changes
- **`bluemarlin/agents/marina/email_poller.py`** — added graceful-exit guard at top of `main()`. When `EMAIL_ADDR` is empty OR `REFRESH_TOKEN_PATH` doesn't exist, logs the reason and returns without raising. BlueFinn is unaffected (both conditions false).
- **`supervisord.conf`** — `[program:email-poller]` block now has `autorestart=unexpected`, `exitcodes=0`, `startsecs=0`. The `startsecs=0` is critical — without it, supervisord treats the millisecond-fast clean exit as a startup failure and marks it FATAL, defeating the whole point. BlueFinn's poller never exits, so startsecs=0 has zero practical effect on BlueFinn. `[program:webhook-server]` block unchanged (still `startsecs=5`, `autorestart=true`).

### New files
- **`clients/adamus/config/client.json`** — full Adamus config: Sofia agent name, Restaurant Adamus business name, Jan Thiel Beach location, 4 languages (EN/NL/ES/Papiamentu), restaurant terminology (`reservation`/`diners`/`seating`), group threshold 12, payment timing `none`, lunch + dinner services with real Google Calendar IDs, full FAQ, persona text that positively establishes Sofia without mentioning Marina/charters/boats/trips.
- **`clients/adamus/config/platform.env.example`** — template with all env var names present but empty for real values. `EMAIL_ADDRESS=` is empty (the graceful-exit trigger), all WhatsApp/Zernio/Meta vars empty.
- **`clients/adamus/docker-compose.yml`** — uses pre-built `image: root-bluemarlin`, port 8002:8001, mounts client.json/calendar-key.json/data/logs from `./config/` and `./data/` etc. No azure_refresh_token mount (Adamus doesn't have one).
- **`bluemarlin/tests/marina/test_146_adamus_second_client.py`** — 14 tests.

### Config changes
- **`.gitignore`** — added `clients/*/data/` and `clients/*/logs/` patterns. Credentials (`platform.env`, `calendar-key.json`, `azure_refresh_token.txt`) were already covered by the cleanup patterns from earlier this session.

## Test results

### New tests (Brief 146)

All 14 pass:

```
test_email_poller_exits_cleanly_when_email_address_empty PASSED
test_email_poller_exits_cleanly_when_refresh_token_missing PASSED
test_email_poller_proceeds_past_guard_when_both_present PASSED
test_adamus_client_json_is_valid_json PASSED
test_adamus_client_json_has_sofia_agent PASSED
test_adamus_client_json_uses_restaurant_terminology PASSED
test_adamus_client_json_has_real_calendar_ids PASSED
test_adamus_client_json_has_real_spreadsheet_id PASSED
test_adamus_payment_timing_is_none PASSED
test_adamus_group_threshold_is_12 PASSED
test_adamus_client_json_no_bluefinn_references PASSED
test_adamus_docker_compose_uses_prebuilt_image PASSED
test_adamus_docker_compose_port_8002 PASSED
test_adamus_docker_compose_container_name PASSED

============================== 14 passed in 0.27s ==============================
```

### Full regression

Before Brief 146: **642 passed / 7 pre-existing failures** (649 total).
After Brief 146: **656 passed / 7 failures** (663 total).

The same 7 pre-existing failures remain. Zero new failures introduced. The 7 are:
- `test_047_reschedule_booking_flow` — 5 stale tests (known, documented in earlier briefs)
- `test_048_human_speech_optimization::test_reschedule_still_triggers` — stale (same cause)
- `test_social/test_068_pipeline::test_send_text_message_success` — fails in full suite only, passes in isolation (cross-test contamination, pre-existing before Brief 146, confirmed by running the suite with `--ignore=tests/marina/test_146_adamus_second_client.py` and getting the same failure).

## Deployment

### BlueFinn redeploy
- `git pull` + `docker compose down` + `docker compose build` + `docker compose up -d` ran cleanly on VPS.
- Image rebuilt and tagged as `root-bluemarlin:latest`.
- Container `bluemarlin-default` restarted, health check `{"status":"ok"}` on port 8001.
- Email poller log shows "Email poller started..." (entered normal polling loop, did not hit the graceful-exit path — BlueFinn's `EMAIL_ADDRESS` and refresh token are both present, as expected).

### Adamus container startup
- Verified image `root-bluemarlin:latest` exists (pre-check Step 12).
- `ssh root@... "cd /root/clients/adamus && docker compose up -d"` succeeded.
- Container `bluemarlin-adamus` running on port 8002, health check `{"status":"ok"}`.
- Adamus email poller log: `Email polling disabled for this client (EMAIL_ADDRESS=empty, refresh_token=present). Exiting cleanly.` — graceful-exit path fired correctly.
- Both containers confirmed running simultaneously via `docker ps`.

### Orchestrator proof (the thing we came here to prove)

Inside `bluemarlin-adamus`:
```
name: Restaurant Adamus
agent_name: Sofia
service_label: reservation
party_size_label: diners
services: ['lunch', 'dinner']
```

Inside `bluemarlin-default`:
```
name: BlueFinn Charters Curaçao
agent_name: Marina
service_label: trip
party_size_label: guests
services: ['klein_curacao', 'snorkeling_3in1', 'west_coast_beach', 'sunset_cruise', 'jet_ski']
```

**Multi-client architecture proven.** Two containers, same Docker image, completely different client.json files produce completely different business profiles, agent names, terminology, and services. No cross-contamination at the config-loading layer.

## Unexpected / problems encountered

1. **Test 3 initially hung** — my first attempt had `_SentinelException(Exception)`. The main loop's outer `except Exception` at line 1346 swallowed it, caught the exception, slept 30 seconds, and looped forever. Fix: changed the sentinel to inherit from `BaseException` so `except Exception` doesn't catch it. This is a clean, well-understood Python pattern for breaking out of catch-all loops in tests.

2. **test_066_project_structure flagged my sys.path.insert** — I'd added a defensive `sys.path.insert` at the top of the new test file out of habit. There's an existing test (`test_066`) that enforces "no sys.path.insert in test files — conftest.py handles it." Removed the sys.path.insert, kept the _BM_ROOT path constant (which is still needed for file path construction, not imports).

3. **Both above were caught by existing tests before deployment.** System working as designed.

## ⚠️ Architectural flaw discovered during deployment

While inspecting `/app/config/` inside the Adamus container, I found that it contains **BlueFinn's entire runtime config directory** — including `platform.env`, `azure_refresh_token.txt` (BlueFinn's real refresh token), `email_thread_state.json` (BlueFinn's conversation history), `archived_threads.jsonl`, and `state_registry.db`. None of these files are mounted by Adamus's docker-compose; they are **baked into the Docker image** at build time.

### Root cause

The Dockerfile does `COPY bluemarlin/ /app/`. On the VPS, `/root/bluemarlin/config/` contains live runtime files that are gitignored but present on disk. `docker build` doesn't know or care about `.gitignore` — it copies whatever exists in the build context. So every image built on the VPS bakes in BlueFinn's secrets.

### Why it didn't break Brief 146's proof

1. Adamus's docker-compose volume-mounts its own `client.json` and `calendar-key.json` over the baked-in versions, so config_loader reads Adamus's real config.
2. Docker's `env_file:` directive injects env vars at container start, which takes precedence over any baked-in `platform.env` file. So `EMAIL_ADDRESS=""` wins and the graceful-exit path fires.
3. The orchestrator proof only needed `client.json`, which IS correctly mounted.

### Why it's a blocker for real multi-client deployment

- Every client container has BlueFinn's refresh token sitting at `/app/config/azure_refresh_token.txt`. If a future client ever sets `EMAIL_ADDRESS` without explicitly mounting their own token file, they would read BlueFinn's inbox.
- Every client container has BlueFinn's `email_thread_state.json` baked in — which contains customer email threads, PII, and in-flight booking state.
- This is a data leak waiting to happen at the next client deployment.

### Fix (separate brief)

Create a `.dockerignore` that excludes `bluemarlin/config/*` from the Docker build context, with exceptions for `brand/` (fonts needed at build time) and `.gitkeep`. The image will contain an empty `/app/config/` directory, populated entirely by volume mounts at runtime. Worth its own brief (one file, clear scope, needs regression testing to confirm BlueFinn still deploys cleanly).

## Next

The orchestrator proof is done. Brief 146 is architecturally complete for its stated goal ("prove multi-client works"). The `.dockerignore` fix is Brief 147.
