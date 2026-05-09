---
name: Session state 2026-04-14 — production infra shipped
description: End-of-session snapshot. Canary pipeline, deploy queue, and control panel Deploys tab are all live. Use this as the read-first project state file for sessions starting after 2026-04-14 (replaces project_session_state_2026_04_06.md).
type: project
originSessionId: a8da0e6a-d80e-4538-ae7c-11b06ae6beb0
---
# WTYJ Project State — 2026-04-14

End of session. Production infrastructure shipped today: Briefs 195 + 196 + follow-up.

## Test count: 904 passing / 0 failures

## Containers running (VPS 108.61.192.52)
- `wtyj-bluemarlin` (port 8001) — demo client + canary target
- `wtyj-adamus` (port 8002) — demo client (paying-client deploy stage)
- `wtyj-consultadespertares` (port 8003) — demo client (paying-client deploy stage)
- `wtyj-staging` (port 9001) — staging container, dummy keys, gets canary's image via `:latest → :staging` retag

All four healthy as of 14:59 UTC (post-Brief-196-follow-up deploy). No paying clients yet (HD Azure pending).

## Deploy pipeline — what shipped today

**Brief 195** (canary pipeline) — `.github/workflows/ci-deploy.yml` jobs: `test → deploy-canary → off-hours-decide → deploy-production`. Image tagging with commit SHA + `:previous`. Auto-rollback. Pre-deploy DB snapshot. 10-check E2E test on BlueMarlin canary using sentinel `e2etest%` data with cleanup sweep.

**Brief 196** (deploy queue + canary-always + production-only off-hours):
- Canary always runs regardless of time. Only production gates.
- Off-hours: Curaçao only (Madrid dropped). Block 05:30–20:00 AST.
- `[HOTFIX]` bypass is **subject-line only** (not body — Brief 195's accidental bypass via doc text can't happen).
- Queue at `/root/wtyj_deploy_queue.json` managed by `wtyj/shared/deploy_queue.py` with `fcntl.flock`.
- Pushes during business hours: canary deploys, commit enqueued, scheduled cron drains at off-hours.
- Control panel `Deploys` tab visualizes queued/in-progress/history.

**Brief 196 follow-up** — `Deploy queued now` button in control panel passes `-f force=true` to `gh workflow run scheduled-deploy.yml`, which sets `SKIP_OFF_HOURS_CHECK=1`. Manual UI button = emergency bypass. Cron-triggered runs still respect off-hours.

## Quick reference — deploy state file

```
/root/wtyj_deploy_queue.json  (host root — system-wide, not per-client)
└── { queued: [...], in_progress: {...} | null, history: [last 30] }
```

`fcntl.flock` on sidecar `.lock` file. `claim_for_deploy()` MOVES queued→in_progress.acknowledged_briefs and clears queued (so new pushes during deploy land in fresh queue, not absorbed). `complete_deploy()` only writes history for acknowledged briefs.

Read state via SSH:
```
ssh root@108.61.192.52 'cat /root/wtyj_deploy_queue.json'
```

## Helper scripts on VPS at /root/wtyj/scripts/

- `off_hours_check.py` — Curaçao 05:30-20:00 AST block, `[HOTFIX]` subject-line bypass
- `e2e_canary_test.sh` — 10 checks on BlueMarlin (port 8001)
- `pre_deploy_snapshot.sh` — copies state_registry.db files to `/root/backups/pre_deploy/<ts>_<sha>/`, 7-day retention
- `rollback.sh [target]` — retags `:previous → :latest + :staging`, restarts containers
- `queue_enqueue.py` — CLI wrapper for `deploy_queue.enqueue()`, takes `--subject-b64` (base64-encoded subject, survives shell quoting)
- `process_deploy_queue.sh` — claim + deploy + complete; honors `SKIP_OFF_HOURS_CHECK=1` env

## Control panel

Local at `localhost:4000` (Vite dev server, port 4000) + Express API on `localhost:3001` (proxied via Vite as `/api/*`). Started via `tools/control-panel/start.sh` which runs `npm run dev` (concurrently runs vite + node server.js).

**Tabs:** System (mindmap of architecture), Tasks (kanban SR/JR), Workspace (whiteboard + docs reader), Clients (per-client status), **Deploys** (queue + history, polls every 30s).

**Server.js does NOT auto-reload.** When changing server.js routes, kill the `node server.js` process and restart it manually, or restart the whole concurrently tree.

**Deploys tab API endpoints:**
- `GET /api/deploys/state` — SSHes to VPS, returns queue JSON
- `POST /api/deploys/trigger` — calls `gh workflow run scheduled-deploy.yml -f force=true` (emergency bypass)

## Test baselines + brief sequence

System_state.md is up-to-date through Brief 196 (entry includes the follow-up's outcome). Lessons.md has full Brief 195 + 196 entries documenting the brief-reviewer issues caught.

Recent brief sequence:
- 191 — agnostic sweep (15 hardcoded values removed from source)
- 192 — email poller escalated guard fix
- 193 — Roberto → Consulta Despertares rename
- 194 — staging environment (container + worktree + image tag)
- 195 — canary pipeline + E2E + rollback + snapshot
- 196 — deploy queue + canary-always + control panel Deploys tab
- 196 follow-up — UI button bypasses off-hours

## What's still pending from `wtyj/docs/project_live_preparations.md`

Not yet built:
- Plain-English code explainer (post-execution agent that translates each diff into a layperson-readable description for the deploy history)
- Google Drive off-site backups (rclone + OAuth via calvinadamusjr@gmail.com — needs interactive browser step from Benson)

Already shipped this session:
- Canary pipeline ✓ (Brief 195)
- System-wide E2E (10 checks) ✓ (Brief 195)
- Off-hours enforcement ✓ (Brief 195 + 196 — production-only)
- Image tagging + auto-rollback ✓ (Brief 195)
- Pre-deploy DB snapshot ✓ (Brief 195)
- Deploy status in control panel ✓ (Brief 196 — Deploys tab)
- Staging branch deletion ✓ (this session)
- Owner Email node flipped to Built on system map ✓ (this session)

## Frequently-edited file map

- `wtyj/agents/marina/marina_agent.py` — Marina prompt
- `wtyj/agents/marina/email_poller.py` — IMAP polling loop (split with `email_adapter.py` per Brief 189)
- `wtyj/agents/social/webhook_server.py` — FastAPI app (Zernio webhook + dashboard router mount)
- `wtyj/agents/social/social_agent.py` — orchestrator (`handle_incoming_whatsapp_message`)
- `wtyj/dashboard/api.py` — dashboard API endpoints (`router = APIRouter(prefix="/dashboard/api")`)
- `wtyj/shared/state_registry.py` — SQLite I/O for all client data
- `wtyj/shared/deploy_queue.py` — NEW today, deploy queue I/O
- `clients/<client>/config/client.json` — per-client business config
- `clients/<client>/config/platform.env` — credentials (chmod 600 — Brief safety fix earlier today)
- `tools/control-panel/src/pages/*.tsx` — control panel React pages

## Things that are NOT changes day-to-day but worth knowing

- Repo: `BensonOpas/wtyj-agent` (renamed from `bluemarlin-agent` earlier this session — old name redirects)
- Frontend repo: `BensonOpas/wtyj-frontend` (separate Replit deployment for `wetakeyourjob.com`)
- VPS file permissions are now strict: all `platform.env`, `calendar-key.json`, `azure_refresh_token.txt` are 600; config dirs 700
- `.gitignore` covers `wtyj/data/*`, `wtyj/backups/`, `**/state_registry.db`, `wtyj/config/*`, `tools/control-panel/{node_modules,data,package-lock.json}` (added today as part of safety hardening)
- `git history still contains older state_registry.db snapshots` from before today's gitignore fix. Decided to leave history (private repo, low risk) rather than rewrite. Stop-the-bleeding done; past exposure left as-is.
