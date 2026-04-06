# OUTPUT 148 — .dockerignore + Directory-Mount Refactor

## What was done

### Config changes
- **`.dockerignore`** — expanded from 10 lines to 26 lines. Added `bluemarlin/config/`, `bluemarlin/data/`, `bluemarlin/logs/`, `clients/`, `**/.DS_Store`. All Brief 142 exclusions preserved.
- **`docker-compose.yml`** — BlueMarlin's mount block replaced three per-file mounts (`client.json:ro`, `calendar-key.json:ro`, `azure_refresh_token.txt:rw`) with a single directory mount `./bluemarlin/config:/app/config:rw`. `data/`, `logs/`, `env_file:`, `environment:`, and all other settings preserved.
- **`clients/adamus/docker-compose.yml`** — same refactor. Two per-file mounts replaced with `./config:/app/config:rw`. `image: root-bluemarlin`, port `8002:8001`, container name `bluemarlin-adamus` preserved.

### New file
- **`bluemarlin/tests/marina/test_148_dockerignore_directory_mount.py`** — 16 tests covering all the above.

## Test results

### New tests (Brief 148)

All 16 pass:

```
test_dockerignore_excludes_bluemarlin_config PASSED
test_dockerignore_excludes_bluemarlin_data PASSED
test_dockerignore_excludes_bluemarlin_logs PASSED
test_dockerignore_excludes_clients_dir PASSED
test_dockerignore_excludes_ds_store PASSED
test_dockerignore_preserves_brief_142_exclusions PASSED
test_bluemarlin_docker_compose_has_config_directory_mount PASSED
test_bluemarlin_docker_compose_no_per_file_mounts PASSED
test_bluemarlin_docker_compose_preserves_data_and_logs_mounts PASSED
test_bluemarlin_docker_compose_preserves_env_file PASSED
test_bluemarlin_docker_compose_preserves_credentials_env_var PASSED
test_adamus_docker_compose_has_config_directory_mount PASSED
test_adamus_docker_compose_no_per_file_mounts PASSED
test_adamus_docker_compose_preserves_data_and_logs_mounts PASSED
test_adamus_docker_compose_preserves_image_ref PASSED
test_adamus_docker_compose_preserves_port_mapping PASSED

============================== 16 passed in 0.02s ==============================
```

### Full regression

Before Brief 148: 665 passed / 7 pre-existing failures (672 total).
After Brief 148: 681 passed / 7 failures (688 total).

Same 7 pre-existing failures unchanged. Zero new failures.

## Deployment

### BlueMarlin rebuild

```bash
ssh root@108.61.192.52 "cd /root && git pull && docker compose down && docker compose build && docker compose up -d"
```

Image rebuilt (`sha256:a1f626c29d1b...`), container `bluemarlin-default` running on port 8001, health check `{"status":"ok"}`.

### Verification: BlueMarlin's /app/config/ preserved

```
$ docker exec bluemarlin-default ls -la /app/config/

.gitkeep               0     bytes
archived_threads.jsonl 63344 bytes
azure_refresh_token.txt 1776 bytes
brand/                 (dir)
calendar-key.json      2393  bytes
client.json            16496 bytes
client.json.template   1664  bytes
email_thread_state.json 292481 bytes  ← CRITICAL: full 290 KB of thread history preserved
heartbeat.txt          10    bytes
platform.env           1252  bytes
state_registry.db      0     bytes (stale, expected)
```

All state files present via the directory mount. Nothing was baked into the image — everything comes from the host at `/root/bluemarlin/config/`.

### Verification: Brief 147 fix still works

Re-ran Brief 147's subprocess trace inside the new BlueMarlin container:

```
KEY_PATH: /app/config/calendar-key.json
env var: /app/config/calendar-key.json
SUBPROCESS env CREDENTIALS: /app/config/calendar-key.json
SUBPROCESS returncode: 0
SUBPROCESS stdout: {
  "spreadsheetId": "1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I",
  "tableRange": "'All Events'!A1:E113",
  ...
```

Row 113 written to BlueMarlin's "All Events" tab (up from row 112 in Brief 147's verification). The gws integration survives Brief 148's refactor. Env var passthrough still correct.

### Adamus restart

```bash
ssh root@108.61.192.52 "cd /root/clients/adamus && docker compose down && docker compose up -d"
```

Container `bluemarlin-adamus` running on port 8002, health check `{"status":"ok"}`.

### THE verification: Adamus's /app/config/ has ONLY Adamus files

```
$ docker exec bluemarlin-adamus ls -la /app/config/

calendar-key.json       2393 bytes
client.json             3884 bytes
platform.env            967  bytes
platform.env.example    859  bytes
```

**Four files. All Adamus's. Zero BlueMarlin contamination.**

Previously (Brief 146 state) Adamus had all of these baked in from the image:
- ❌ `azure_refresh_token.txt` (BlueMarlin's Microsoft OAuth token — GONE)
- ❌ `email_thread_state.json` (BlueMarlin's 290 KB of thread history — GONE)
- ❌ `archived_threads.jsonl` (BlueMarlin's archived conversations — GONE)
- ❌ `heartbeat.txt` (BlueMarlin's runtime artifact — GONE)
- ❌ `brand/` directory (BlueMarlin's font — GONE)
- ❌ `client.json.template` (static template — GONE)
- ❌ `state_registry.db` (stale file — GONE)
- ❌ `.gitkeep` (from image — GONE)

None of these are accessible to the Adamus container anymore. If Adamus's email_poller ever ran with a real `EMAIL_ADDRESS`, it would NOT find BlueMarlin's refresh token. It would fail with a clean "token missing" error instead of silently reading someone else's inbox.

### Verification: Adamus orchestrator still works

```
$ docker exec bluemarlin-adamus python3 -c 'config_loader.get_business()...'

name: Restaurant Adamus
agent_name: Sofia
service_label: reservation
```

Brief 146's multi-client architecture proof is intact. Sofia/Restaurant Adamus/reservation — identical to the Brief 146 state but now truly isolated from BlueMarlin.

### Final sanity check

```
$ curl -s http://localhost:8001/health && curl -s http://localhost:8002/health

{"status":"ok"}
{"status":"ok"}
```

Both containers `Up`, both healthy.

## Unexpected / problems encountered

**None.** The brief was tight, the directory-mount strategy worked exactly as described, Brief 147's fix survived the refactor, and BlueMarlin's state files persisted cleanly through the rebuild. This was a smooth brief with no surprises.

The directory mount is significantly simpler than the per-file approach in every way — fewer lines in docker-compose, no file-existence foot-guns, automatic coverage of future runtime files, and trivial mental model ("the host dir IS the container's config dir").

## Production impact

Before Brief 148: every Docker build on the VPS copied BlueMarlin's live `email_thread_state.json` (290 KB of customer conversation history), `azure_refresh_token.txt` (live Microsoft OAuth token), and `platform.env` (all secrets) into image layers. Every client container ever built from that image inherited those files on disk. Adamus was the first second-client, and we saw the contamination directly.

After Brief 148: the image's `/app/config/` is genuinely empty (just the directory the Dockerfile creates via `RUN mkdir -p`). Every client mounts their own host config dir at runtime. BlueMarlin's secrets live only on BlueMarlin's host path. Adamus's live only on Adamus's host path. No cross-tenant leakage at the image layer.

The image is also smaller — it no longer carries ~357 KB of baked-in state files that have no business in an image.

## Post-execution

- Committed as `249ee0e` on main
- Pushed to origin
- Deployed to VPS
- Both containers verified healthy and isolated
