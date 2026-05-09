---
name: Session state snapshot 2026-04-06 — read this if context is fresh and you don't know what happened recently
description: End-of-session snapshot of platform state, briefs shipped, what's working, what's broken, what's next. Captures non-obvious context that's not derivable from git log alone.
type: project
---

## Platform state (2026-04-06 end-of-session)

- **738 tests passing / 0 failures.** First fully clean test suite in months.
- **Two containers running on VPS (108.61.192.52):**
  - `wtyj-bluemarlin` on port 8001 — BlueMarlin Charters demo (boat charter business)
  - `wtyj-adamus` on port 8002 — Restaurant Adamus demo (beach restaurant)
  - Both use the same Docker image `wtyj-agent:latest`
  - Built from `/root/Dockerfile`, source at `/root/wtyj/`
  - Per-client runtime: `/root/clients/bluemarlin/`, `/root/clients/adamus/`
- **WhatsApp working end-to-end for BlueMarlin** via Zernio + Twilio +1 (515) 500-5577. Verified 21:48 UTC with real test messages from Calvin Adamus.
- **Email working for BlueMarlin** (`hello@wetakeyourjob.com` polled via Microsoft OAuth, refresh token at `/root/clients/bluemarlin/config/azure_refresh_token.txt`).
- **Adamus has ZERO live customer-facing channels.** Container runs, orchestrator works via direct calls, but no real customer can reach Adamus. Email is the simplest fix — needs OAuth bootstrap for sophia@wetakeyourjob.com (the IMMEDIATE next-session item per `project_open_work.md`).

## Briefs shipped this session (146-154)

- **146** — Adamus second-client deployment (orchestrator-only proof)
- **147** — gws hardcoded calendar key fix (production was silently broken for 24h post-Brief-145)
- **148** — `.dockerignore` + directory mounts (image-layer multi-client isolation)
- **149** — Structured 10-field `agent_persona` config + `operating_mode` alias
- **150** — BlueMarlin moved to `clients/bluemarlin/` + identity rebrand (BlueFinn data scrubbed)
- **151** — Source tree `bluemarlin/` → `wtyj/`
- **152** — Docker image + container names → `wtyj-*`
- **153** — `infra.md` legacy reference sweep
- **154** — Pre-existing latent issues cleanup (7 stale tests fixed, whatsapp_client lazy env vars, template moved, 0-byte stale file deleted, two staleness investigations both came back NORMAL)

Plus session-level work: git history scrub of leaked GCP service account key, Anthropic API key removed from `.claude/settings.local.json`, security hook fixed to allowlist BensonOpas pushes (so Claude can `git push` autonomously), Docker disk cleanup on VPS (1.4 GB freed).

## Non-obvious context that future-me will need

### The two booking summary builders intentionally diverge

There are TWO `_build_booking_summary` functions in the codebase:
- `wtyj/agents/marina/email_poller.py:412` — uses old wording `"Want me to go ahead and book this?"` (the one used by the email path)
- `wtyj/agents/social/social_agent.py:86` — uses new wording `"Want me to check availability and hold a spot for you?"` (the one used by the WhatsApp/DM path, updated by Brief 141)

**Brief 141 only updated the social_agent builder, NOT the email_poller builder.** The two diverge intentionally OR Brief 141 was incomplete — that question is still open. Brief 154 explicitly leaves both alone.

**CRITICAL for future test maintenance:** if you're updating tests in `test_047_reschedule_booking_flow.py` or `test_048_human_speech_optimization.py`, the assertion strings `"Want me to go ahead and book this"` are CORRECT for the email path. Don't "fix" them. Brief 154's reviewer caught me trying to do exactly this and saved me from shipping red tests against working code. Read `project_company_naming.md` and `marina_lessons.md` for the full story.

### Day-of-week trap when picking test dates

`test_047` and `test_048` exercise the 3-in-1 Snorkeling Trip which is "Fridays only". When updating hardcoded dates in those tests, the date MUST be a Friday or the tests fail with "doesn't run on Wednesdays" instead of producing the expected booking summary. Brief 154 went from `2026-04-03` (the original stale date) to `2027-12-15` (Wednesday — failed) to `2027-12-17` (Friday — works).

When picking future dates for tests that exercise day-of-week-restricted services, check the day of the week. Use a Python REPL or `date -j -f '%Y-%m-%d' 2027-12-17 +%A` on macOS.

### Lazy env var pattern as recurring solution

Briefs 147 and 154 both fixed the same bug shape: a module loads `_VAR = os.environ.get(...)` at import time, gets cached with empty values when imported transitively before tests set the env vars, then fails silently.

**Fix pattern:**
```python
def _var() -> str:
    return os.environ.get("VAR_NAME", "")
```
Replace all module constant references with helper function calls.

**Modules already fixed:** `gws_calendar.py` (Brief 147), `whatsapp_client.py` (Brief 154).

**Not yet swept:** any other client of an external API. Future cleanup brief: grep for `_[A-Z_]+\s*=\s*os\.environ\.get` across `wtyj/agents/` and convert any survivors.

### Test count history this session

| Brief | Tests passed | Pre-existing failures |
|---|---|---|
| (start) | 643 | 6 |
| 146 | 656 | 7 (test_068 added itself to the pre-existing list) |
| 147 | 665 | 7 |
| 148 | 681 | 7 |
| 149 | 700 | 7 |
| 150 | 717 | 7 |
| 151 | 723 | 7 |
| 152 | 730 | 7 |
| 153 | 730 | 7 (doc-only, no test changes) |
| **154** | **738** | **0** |

Brief 154 was the first session-end with a fully clean suite.

### File staleness on VPS is normal, not a bug

`/root/clients/bluemarlin/config/archived_threads.jsonl` (last modified Mar 10, 27 days stale) and `/root/clients/bluemarlin/config/email_thread_state.json` (last modified Apr 4, 2 days stale) are both stale because of normal quiet-inbox behavior, NOT bugs:

- `archived_threads.jsonl` only gets writes when threads age >30 days without holds. Since Mar 10, no eligible threads.
- `email_thread_state.json` only gets writes when emails are processed. Quiet inbox = no writes.

Verified during Brief 154 that the poller is alive (heartbeat 11 seconds old, log shows "Email poller started" entries from container restarts). Don't waste future-session time investigating these unless the heartbeat goes stale.

### Lost historical logs (irreversible)

During Brief 150's VPS deploy I forgot to move `/root/bluemarlin/logs/*` along with config and data. Brief 151's `rm -rf /root/bluemarlin` then deleted them. **All webhook server logs, email poller logs, and structured bluemarlin.log entries from before 21:01 UTC on 2026-04-06 are gone.** Going forward, logs persist in `/root/clients/bluemarlin/logs/` and survive container restarts.

If asked to debug "why was X failing yesterday" for anything before 2026-04-06 21:01 UTC, the answer is: we don't know, the logs don't exist anymore.

### Demo phase ethics note

BlueMarlin's `client.json` (post-Brief 150) no longer impersonates a real company. Earlier in this session it had `name: "BlueFinn Charters Curaçao"`, BlueFinn's real phone number (+599 9690 3717), and BlueFinn's real email (`info@bluefinncharters.com`) — all scrubbed in Brief 150's rebrand. New identity is `name: "BlueMarlin Charters"`, phone `+15155005577` (Twilio), email `butlerbensonagent@gmail.com`. **BlueFinn Charters Curaçao is a real, unrelated company — we have zero connection to them.** Don't refer to BlueFinn as "client #1" or anything similar. The clients are BlueMarlin and Adamus, both demos. See `project_company_naming.md` for the canonical hierarchy.

### Security hook is now BensonOpas-aware

`~/.claude/hooks/security-gate.sh` was updated this session to look up `git remote get-url origin` and check if the URL contains `github.com[:/]BensonOpas/`. If yes, push allowed. If no, push blocked. Means I can push to your repos autonomously without you needing to run `git push` manually each time. Force pushes still require explicit confirmation per your "strict" preference.

### Dashboard password is `123` ⚠️

Set as `DASHBOARD_PASSWORD=123` in `/root/clients/bluemarlin/config/platform.env`. Insecure. Anyone who knows the dashboard URL can log in. Change before any public exposure of `https://api.wetakeyourjob.com/dashboard/`. Noted in infra.md.

## What's next (priority order)

1. **Adamus email OAuth bootstrap** — IMMEDIATE next-session item. ~30 minute browser dance to get a Microsoft OAuth refresh token for sophia@wetakeyourjob.com. After this, Adamus has a real customer channel for the first time. See `project_open_work.md` IMMEDIATE section for the procedure.

2. **Resolve the booking summary wording divergence** — decide whether to unify the two builders (email + social) on the new "hold a spot" wording, or keep them divergent intentionally. Then either ship the unification or document the deferred decision in a brief.

3. **GCP project rename** (`bluemarlin-ops` → `wtyj-platform`) — deferred per Benson. Requires manual GCP console work + re-sharing all calendars. Cosmetic but visible to clients who share calendars with us.

4. **Dashboard password change** — security cleanup before any public exposure.

5. **Onboarding playbook** — write `wtyj/briefs/onboarding_checklist.md` so client #3 takes 1-2 hours, not a full day like Adamus.

## Files updated in Brief 154 to look at next session

- `wtyj/agents/social/whatsapp_client.py` — has `_access_token()` and `_phone_number_id()` helper functions now (Brief 147 pattern)
- `wtyj/templates/client.json.template` — moved from `clients/bluemarlin/config/`
- `wtyj/tests/social/test_068_pipeline.py` — has new `test_whatsapp_client_reads_env_var_lazily` test
- `wtyj/tests/marina/test_047_reschedule_booking_flow.py` and `test_048_human_speech_optimization.py` — date updated to `2027-12-17`
- `.dockerignore` — `wtyj/templates/` added
