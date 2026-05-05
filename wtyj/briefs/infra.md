# INFRA.md — WTYJ Agent Infrastructure Reference

**Owns:** Everything about HOW the system runs — VPS, services, credentials, URLs, ports, nginx, SSL, env vars, deploy commands.
**Related:** For what we're building and why → `master_plan.md`. For what's next → `roadmap.md`. For what each brief did → `system_state.md`.

## Project & business naming (IMPORTANT — read before using this doc)

- **WTYJ (wetakeyourjob.com)** is the project / platform. Owns all the code. All infrastructure in this file belongs to WTYJ.
- **BlueMarlin** is demo business #1, deployed on port 8001. Its `client.json` business data is mirrored from BlueFinn Charters Curaçao's public website (phone, trips, prices, FAQ) for realistic Caribbean-tourism content. The DEPLOYMENT is BlueMarlin's; the DATA inside the config happens to use BlueFinn's labels.
- **Restaurant Adamus** is demo business #2, deployed on port 8002. Fully fictional restaurant. Zero real-world analog.
- **BlueFinn Charters Curaçao** is a REAL, UNRELATED company. We have zero connection to them. Never signed, never contacted. The only link: BlueMarlin's demo client.json uses BlueFinn's public info. BlueFinn does NOT run on our platform. Do not confuse "BlueMarlin container running" with "BlueFinn running" — BlueFinn is not a client.

Legacy naming that has been cleaned up (Briefs 150-152, complete 2026-04-06):
- Source tree: `bluemarlin/` → `wtyj/` ✅
- BlueMarlin's deployment: `/root/bluemarlin/` → `/root/clients/bluemarlin/` ✅
- Docker image: `root-bluemarlin` → `wtyj-agent` ✅
- BlueMarlin container: `bluemarlin-default` → `wtyj-bluemarlin` ✅
- Adamus container: `bluemarlin-adamus` → `wtyj-adamus` ✅
- BlueMarlin's client.json business identity: `BlueFinn Charters Curaçao` → `BlueMarlin Charters` (rebrand to remove real-company impersonation) ✅

### Note for any AI / future reader ingesting briefs

The brief history (`marina_brief_001` through `marina_brief_152`), source file header comments, lessons entries, and old output docs predate the WTYJ naming sweep. They contain legacy references like:

- `# bluemarlin/agents/marina/marina_agent.py` as source file header comments
- `bluemarlin/config/client.json` paths in old briefs
- `BlueFinn Charters Curaçao` as the deployed business name
- `root-bluemarlin` as the Docker image
- `bluemarlin-default` as a container name
- `info@bluefinncharters.com` as the contact email
- `+599 9690 3717` as a phone number
- `bluefinn1` / `bluefinn2` as resource keys

**These are all historical and not authoritative.** They are preserved in the brief history because briefs are meant to be a chronological record of decisions, not a live reference. The canonical current naming is at the top of this document. When in doubt, trust this section, not the brief history.

Specifically: BlueFinn Charters Curaçao is a REAL, UNRELATED company we have zero connection to. Any brief that says "BlueFinn is client #1" or "deploying BlueFinn" is using legacy/incorrect terminology — the actual deployed demo client #1 is **BlueMarlin Charters**, which originally borrowed BlueFinn's public website data for realistic test content. The rebrand in Brief 150 stripped that borrowed data.

Don't try to "fix" header comments or old brief text. Treat them as historical artifacts. Use the canonical naming when writing new briefs or code.

---

## VPS

| Item | Value |
|------|-------|
| Host | `108.61.192.52` |
| User | `root` |
| Port | 22 |
| SSH command | `ssh root@108.61.192.52` |
| SSH key (Mac) | `~/.ssh/id_rsa` |
| OS | Ubuntu |
| Python binary | `/usr/bin/python3` (3.12.3) |

---

## Project on VPS

After Briefs 150-152, source code lives at `/root/wtyj/` and each client's runtime
state lives under `/root/clients/<client>/`. The repo root is `/root/`.

| Item | Value |
|------|-------|
| Repo root | `/root/` |
| Source tree | `/root/wtyj/` |
| Marina agent (source) | `/root/wtyj/agents/marina/` |
| Social agent (source) | `/root/wtyj/agents/social/` |
| Dashboard API (source) | `/root/wtyj/dashboard/` |
| Shared libs (source) | `/root/wtyj/shared/` |
| BlueMarlin runtime | `/root/clients/bluemarlin/` (config, data, logs, docker-compose) |
| Adamus runtime | `/root/clients/adamus/` (config, data, logs, docker-compose) |
| Inside container | `/app/` (working dir, mounts at `/app/config`, `/app/data`, `/app/logs`) |

---

## Environment Variables

Each client has its own secrets file:
- BlueMarlin: `/root/clients/bluemarlin/config/platform.env`
- Adamus: `/root/clients/adamus/config/platform.env`

Loaded by docker-compose's `env_file:` directive at container start.
**NOT in `.bashrc`, `.zshrc`, or `.profile`** — never look there.
(Brief 145 renamed the file from `bluemarlin.env` → `platform.env`. Brief 150 moved it from `/root/bluemarlin/config/` to `/root/clients/<client>/config/`.)

### Complete env var inventory

| Env Var | Service | Purpose |
|---------|---------|---------|
| `ANTHROPIC_API_KEY` | Claude API | LLM calls for Marina, DM agent, content agent, dashboard suggest-reply |
| `WHATSAPP_ACCESS_TOKEN` | Meta Cloud API | Bearer token for sending WhatsApp messages |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta Cloud API | Phone number ID (`990622044139349`) for WA send endpoint |
| `WHATSAPP_VERIFY_TOKEN` | Meta Cloud API | Token for webhook verification handshake |
| `LATE_API_KEY` | Zernio/Late SDK | Instagram/Facebook publishing + DM inbox API |
| `ZERNIO_WEBHOOK_SECRET` | Zernio | HMAC-SHA256 secret for DM webhook signature verification |
| `GOOGLE_OAUTH_CLIENT_ID` | Google OAuth2 | Dashboard Google Drive integration |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth2 | Dashboard Google Drive integration |
| `DASHBOARD_PASSWORD` | Dashboard | Operator login password (generates in-memory session token). Per-client: BlueMarlin=`123`, Adamus=`456`, Consulta Despertares=`789`. ⚠️ Change before public exposure. |
| `OPENAI_API` | OpenAI | Optional: DALL-E image generation for content pipeline |
| `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` | gws CLI | Set at runtime to path of service account key |
| `AZURE_CLIENT_ID` | Email poller | Microsoft Azure app client ID. Default in source: `28e94343-2f77-444c-ac32-58b7bed33b65` (the WTYJ Azure app, shared across all clients on the wetakeyourjob.com Microsoft 365 tenant). |
| `AZURE_TENANT_ID` | Email poller | Microsoft Azure tenant ID. Default in source: `caac06b5-1420-4223-9dcc-ba4a670ec26a`. |
| `EMAIL_ADDRESS` | Email poller | Inbox email address to poll. BlueMarlin: `hello@wetakeyourjob.com` (also the source default). Adamus: empty (triggers Brief 146 graceful exit until OAuth bootstrap is done). |

### Credential files (per-client, post-Brief-150)

| File | BlueMarlin path | Adamus path | Purpose |
|------|-----------------|-------------|---------|
| `platform.env` | `/root/clients/bluemarlin/config/platform.env` | `/root/clients/adamus/config/platform.env` | All env vars above |
| `calendar-key.json` | `/root/clients/bluemarlin/config/calendar-key.json` | `/root/clients/adamus/config/calendar-key.json` | Google service account key (currently the same physical key, copied to both during Brief 146 setup — see GCP roadmap note for the rename) |
| `azure_refresh_token.txt` | `/root/clients/bluemarlin/config/azure_refresh_token.txt` | (not yet — needs OAuth bootstrap for `sophia@wetakeyourjob.com`, see open work memory) | Microsoft OAuth2 refresh token (persisted, auto-rotated) |
| `client.json` | `/root/clients/bluemarlin/config/client.json` | `/root/clients/adamus/config/client.json` | Business config (not credentials — safe in git) |

### Email mailboxes (GoDaddy / Microsoft 365)

GoDaddy email plan currently has 2 seats total.

| Mailbox | Client | Password | Notes |
|---------|--------|----------|-------|
| `hello@wetakeyourjob.com` | BlueMarlin Charters (deployed demo) | (not recorded — uses stored OAuth refresh token) | Primary BlueMarlin inbox. Polled by email_poller via Microsoft Graph OAuth. Refresh token at `/root/clients/bluemarlin/config/azure_refresh_token.txt`. |
| `sophia@wetakeyourjob.com` | Restaurant Adamus (deployed demo) | `Cur@ao2026` | Created in GoDaddy. Needs interactive OAuth login to generate initial refresh token before email polling can start. See `memory/project_open_work.md` IMMEDIATE section. |

### Hardcoded constants in source (not env vars — Brief 145 moved to env vars)

| Constant | File | Value | Purpose |
|----------|------|-------|---------|
| ~~Microsoft `CLIENT_ID`~~ | ~~email_poller.py:27~~ | Now env var `AZURE_CLIENT_ID` (default: WTYJ Azure app `28e94343-...`) | Azure app registration |
| ~~Microsoft `TENANT_ID`~~ | ~~email_poller.py:28~~ | Now env var `AZURE_TENANT_ID` (default: `caac06b5-...`) | Azure tenant |
| ~~`EMAIL_ADDR`~~ | ~~email_poller.py:29~~ | Now env var `EMAIL_ADDRESS` (default: `hello@wetakeyourjob.com` for BlueMarlin; empty for Adamus triggers graceful exit) | Inbox to poll |
| WhatsApp API version | wtyj/agents/social/whatsapp_client.py:14 | `v22.0` | Meta Cloud API version |

---

## Services (Docker — post Brief 152)

Four containers (3 production + 1 staging). Production uses `wtyj-agent:latest`, staging uses `wtyj-agent:staging` (separate image tag, never overwrites production).

| Client | Container name | Port | Compose file | Runtime dir |
|--------|----------------|------|--------------|-------------|
| BlueMarlin Charters (demo #1) | `wtyj-bluemarlin` | 8001 | `/root/clients/bluemarlin/docker-compose.yml` | `/root/clients/bluemarlin/` |
| Restaurant Adamus (demo #2) | `wtyj-adamus` | 8002 | `/root/clients/adamus/docker-compose.yml` | `/root/clients/adamus/` |
| Consulta Despertares (demo #3) | `wtyj-consultadespertares` | 8003 | `/root/clients/consultadespertares/docker-compose.yml` | `/root/clients/consultadespertares/` |
| Unboks (own product, customer-facing) | `wtyj-unboks` | 8004 | `/root/clients/unboks/docker-compose.yml` | `/root/clients/unboks/` |
| **Staging** | `wtyj-staging` | 9001 | `/root/staging/docker-compose.yml` | `/root/staging/` |

**2026-05-03 update (Brief 199):** WhatsApp/Zernio/Meta/Late credentials moved from `bluemarlin/config/platform.env` to `unboks/config/platform.env`. The number `+599 968 81585` (Calvin's WhatsApp, used for Unboks's FB-group promo) now routes to the `wtyj-unboks` tenant where the AI is configured as "Calvin" answering questions about Unboks itself. The `wtyj-bluemarlin` tenant retains zero channel credentials and runs as a code-only demo (no live channels). Webhook URL on Meta/Zernio side must be repointed from `/bluemarlin/webhook/whatsapp` → `/unboks/webhook/whatsapp` for the routing to take effect — Calvin/SR's manual operation outside this brief.

**Production** containers use `wtyj-agent:latest`. **Staging** uses `wtyj-agent:staging` (separate image tag — building staging never overwrites production). Staging has dummy API keys: only the Claude key is real; Zernio, WhatsApp, and email keys are empty or dummy, preventing staging from sending real messages. Staging dashboard password: `staging`.

**2026-04-14 update:** the `staging` branch + `/root/staging-code` worktree were deleted. Decided model per `wtyj/docs/project_live_preparations.md` is: code flows through `main` only, staging is a deploy TARGET (container at port 9001) not a branch. Canary pipeline brief (pending) will wire the staging container into the main-push flow as the first deploy stage. Until then, the staging container runs whatever image was last built and is not auto-updated.

All production containers use `image: wtyj-agent` directly — no rebuild on their deploy. Inside each: `email-poller` + `webhook-server` via supervisord. Adamus/Consulta Despertares email-pollers exit cleanly on startup (no EMAIL_ADDRESS, no refresh token). Consulta Despertares runs with `booking_flow: false` (filter/buffer mode).

Runtime isolation: Brief 148 added `.dockerignore` exclusion of `wtyj/config/`, `wtyj/data/`, `wtyj/logs/`, `clients/`, plus directory mounts in both compose files. Each container's `/app/config/` is populated entirely from its own host directory at runtime — zero cross-tenant leakage at the image layer.

### Deploy pipeline (post-Brief-196)

Deploys are driven by `.github/workflows/ci-deploy.yml` — push to main triggers the pipeline. Four jobs:

1. **test** — pytest runs all tests on Ubuntu Python 3.12 with stub env vars.
2. **deploy-canary** — ALWAYS runs (no off-hours gate). SSH to VPS. Pulls main, retags `wtyj-agent:latest` → `wtyj-agent:previous`, builds new image, archive-tags as `wtyj-agent:<short-sha>`, retags as `wtyj-agent:staging`. Deploys staging container (port 9001) with retry health check, then BlueMarlin canary (port 8001) with retry health check, then runs `wtyj/scripts/e2e_canary_test.sh` (10 system-wide checks). Any failure triggers `wtyj/scripts/rollback.sh`.
3. **off-hours-decide** — `wtyj/scripts/off_hours_check.py` (Curaçao only, no DST, 05:30-20:00 AST blocked). Bypass: `[HOTFIX]` in commit SUBJECT LINE only — body mentions don't bypass. Sets `action` output to `deploy` (off-hours or hotfix) or `queue` (business hours). When queue: SSHes to VPS and calls `wtyj/scripts/queue_enqueue.py` to append the commit to `/root/wtyj_deploy_queue.json`.
4. **deploy-production** — only runs when off-hours-decide says `deploy`. Enqueues the current commit, then runs `wtyj/scripts/process_deploy_queue.sh` which claims + deploys the latest queued SHA + writes per-brief history entries.

**Queue file:** `/root/wtyj_deploy_queue.json` on VPS (system-wide deploy state, not client-specific). Managed by `wtyj/shared/deploy_queue.py` with `fcntl.flock` sidecar lock. Schema: `{queued: [entries], in_progress: {deploy_sha, acknowledged_briefs, started_at} | null, history: [last 30 deploys]}`.

**Scheduled drain:** `.github/workflows/scheduled-deploy.yml` runs every 30 min (cron `0,30 * * * *`). Calls `process_deploy_queue.sh` — no-ops when business hours, queue empty, or another deploy is in-flight. Also triggerable via `workflow_dispatch` from the control panel's "Deploy queued now" button or `gh workflow run scheduled-deploy.yml -f force=true`. The `force` input (default false) sets `SKIP_OFF_HOURS_CHECK=1` so manual UI triggers act as emergency overrides — same semantics as `[HOTFIX]` in commit subject. Cron-triggered runs never set `force` and always respect off-hours.

**Control panel:** the `Deploys` tab (localhost:4000) polls `/api/deploys/state` every 30s, which SSHes to VPS and reads the queue JSON. Shows currently-deploying + queue + last 10 deploys in history.

**Image versioning:** every build produces `wtyj-agent:latest` + `wtyj-agent:<short-sha>` archive + saves prior `:latest` as `:previous`. Rollback (`wtyj/scripts/rollback.sh [target]`) retags `:previous` → `:latest` + `:staging` and restarts containers — seconds to recover.

**E2E sentinel data:** the canary's E2E test creates rows in 6 tables (customer_identifiers, customers, whatsapp_threads, whatsapp_booking_state, whatsapp_processed, conversation_status) with `e2etest`-prefixed keys, then sweeps via `WHERE LIKE 'e2etest%'` in the cleanup block. No persistent test data after a successful canary.

**First-run gap:** the very first deploy with this workflow has no `wtyj-agent:previous` image yet. If that canary fails, `rollback.sh` exits 1 and BlueMarlin stays on the failing image. Manual recovery: `git revert <bad-sha> && git push`. Acceptable trade-off; subsequent deploys always have `:previous` available.

```bash
# Manual emergency deploy (bypassing CI):
ssh root@108.61.192.52 "
  cd /root && git pull
  cd /root/clients/bluemarlin && docker compose down && docker compose build && docker compose up -d
  cd /root/clients/adamus && docker compose down && docker compose up -d
  cd /root/clients/consultadespertares && docker compose down && docker compose up -d
"

# Manual rollback
ssh root@108.61.192.52 "bash /root/wtyj/scripts/rollback.sh all"

# Health check all
ssh root@108.61.192.52 'for p in 8001 8002 8003 9001; do echo -n "port $p: "; curl -sf -m 3 http://localhost:$p/health; echo; done'

# Inspect running containers
ssh root@108.61.192.52 "docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'"
```

The shared image `wtyj-agent` is built when BlueMarlin's compose runs `docker compose build`. Adamus and Consulta Despertares reference `image: wtyj-agent` directly — no separate build step. Staging uses `wtyj-agent:staging` (retagged from `:latest` during canary deploy).

---

## Webhook Endpoints

| Webhook | URL | Verification | Purpose |
|---------|-----|-------------|---------|
| WhatsApp (Meta) | `https://api.wetakeyourjob.com/webhooks/meta/whatsapp` | Token match (`WHATSAPP_VERIFY_TOKEN`) | Inbound WhatsApp messages |
| Zernio DMs | `https://api.wetakeyourjob.com/webhooks/zernio` | HMAC-SHA256 (`ZERNIO_WEBHOOK_SECRET`) | Inbound Instagram/Facebook DMs |
| Zernio webhook ID | `69cd4d126860f0b4e9738a85` | — | Registered 2026-04-01, events: `message.received` |

---

## External APIs

| API | Purpose | Auth Method |
|-----|---------|-------------|
| Claude (Anthropic) | All LLM calls | `ANTHROPIC_API_KEY` |
| Meta WhatsApp Cloud API | Send/receive WhatsApp messages | `WHATSAPP_ACCESS_TOKEN` bearer |
| Zernio/Late SDK | Instagram/FB publishing + DM inbox | `LATE_API_KEY` |
| Google Calendar | Manifests, availability | Service account key |
| Google Sheets | Booking/event logging | Service account key |
| Google Drive | Dashboard photo library | OAuth2 (client ID + secret) |
| Microsoft Outlook | Email IMAP + SMTP | OAuth2 (client ID + refresh token) |
| OpenAI DALL-E | Image generation (optional) | `OPENAI_API` |
| Demo payment | Placeholder links | None (`https://demo.pay/bluemarlin/{id}`) |

---

## Nginx + SSL

| Item | Value |
|------|-------|
| nginx config (legacy) | `/etc/nginx/sites-available/api-wetakeyourjob` |
| nginx config (canonical, post Brief 200) | `/etc/nginx/sites-available/api-unboks` |
| Public domains | `api.wetakeyourjob.com` (legacy alias) + `api.unboks.org` (canonical, post-rebrand) |
| SSL cert (legacy) | Let's Encrypt via certbot (auto-renew), expires 2026-06-09 |
| SSL cert (canonical) | Pending Phase B of Brief 200 — issued by certbot once SR points `api.unboks.org` DNS at `108.61.192.52` |
| Routing (legacy) | Path-prefix: `/bluemarlin/` → 8001, `/adamus/` → 8002, `/consultadespertares/` → 8003, `/unboks/` → 8004, `/` → 8001 (backward compat) |
| Routing (canonical) | `api.unboks.org/api/{tenant}/...` — strips both `/api/` AND `/{tenant}/` prefixes via `proxy_pass` trailing-slash. Plus `/api/healthz` → BlueMarlin's `/health`. Unknown paths return 404. |
| Brief 200 status | Phase A complete — config pre-positioned, validated via `nginx -t`, dormant until DNS flips. Phase B (cert + cutover) runs via `bash wtyj/scripts/cutover_unboks_domain.sh` after SR's DNS change. |
| Health check (legacy) | `curl -s https://api.wetakeyourjob.com/bluemarlin/health` |
| Health check (canonical, post Phase B) | `curl -s https://api.unboks.org/api/healthz` |

## Monitoring + Backups

### UptimeRobot (uptime monitoring)

| Item | Value |
|------|-------|
| Service | UptimeRobot (free tier, 5-min checks) |
| Account 1 | `butlerbensonagent@gmail.com` (Mac mini / backup) |
| Account 2 | `calvinadamusjr@gmail.com` (Benson personal / primary) |
| Status page | `stats.uptimerobot.com` (public, customizable) |

| Monitor | URL |
|---|---|
| BlueMarlin Health | `https://api.wetakeyourjob.com/bluemarlin/health` |
| Adamus Health | `https://api.wetakeyourjob.com/adamus/health` |
| Consulta Despertares Health | `https://api.wetakeyourjob.com/consultadespertares/health` |

Both accounts monitor the same 3 endpoints. Alerts via email + UptimeRobot app push notifications. Health endpoints support GET and HEAD (Brief 192 session).

### Automated backups (daily cron)

**Local snapshot (stage 1 — 3:00 AM UTC):**

| Item | Value |
|------|-------|
| Script | `/root/backups/daily_backup.sh` |
| Schedule | Daily at 3:00 AM UTC via cron |
| Backup dir | `/root/backups/` |
| Retention | 30 days (auto-cleanup) |
| What's backed up | `state_registry.db` + `email_thread_state.json` for ALL clients (auto-discovers `/root/clients/*/`) |
| Log | `/root/backups/backup.log` |

**Off-site sync to Google Drive (stage 2 — 3:30 AM UTC):**

| Item | Value |
|------|-------|
| Script | `/root/backups/gdrive_sync.sh` |
| Schedule | Daily at 3:30 AM UTC (30 min after stage 1 finishes) |
| Remote | `gdrive:wtyj-backups/` (configured via `rclone config` on VPS) |
| Google account | `butlerbensonagent@gmail.com` |
| Scope | `drive` (full) — rclone writes to `My Drive/wtyj-backups/` |
| What's synced | All of `/root/backups/` EXCEPT `pre_deploy/` (too churn-heavy) and `*.log` |
| Mode | `rclone sync` (mirrors — deletes in GDrive what's deleted locally after 30-day retention) |
| Log | `/root/backups/gdrive_sync.log` |

Recovery flow: if VPS dies, spin up a new VPS, `rclone config` against the same Google account, `rclone copy gdrive:wtyj-backups/ /root/backups/`, then restore any client DB from `/root/backups/<client>_<date>.db`.

---

## Frontend (wetakeyourjob.com — merged 3 sites in one Replit project)

As of 2026-04-11 evening, SR consolidated three previously separate frontends into a single Replit project served at `wetakeyourjob.com`. One React Router app, three CSS-isolated sub-trees:

| Path | Site | Purpose |
|------|------|---------|
| `https://wetakeyourjob.com/` | Marketing site | Apple-style landing, Inter font, white/slate. Pages: Home, Services, About, Contact. |
| `https://wetakeyourjob.com/dashboard` | Operator dashboard | Login-protected (multi-tenant dropdown: BlueMarlin / Adamus / Roberto), dark navy theme, ~12 pages. Same React app as the marketing site, gated by the Login screen. |
| `https://wetakeyourjob.com/demo/bluemarlin/` | Booking demo | BlueMarlin Tours Curaçao charter booking site, teal Caribbean theme, 5 trip packages. |

| Item | Value |
|------|-------|
| Active Replit project | `wetakeyourjob.com` (under Calvin's Replit account) |
| Active GitHub repo | `BensonOpas/wtyj-frontend` (private, default branch `main`, connected 2026-04-11; renamed from `wetakeyourjob` on 2026-04-12 for symmetry with `wtyj-agent`) |
| Stack | React 19 + Vite 7 + Tailwind 4 + shadcn/ui + TanStack Query, pnpm workspace (`@replit` plugins, single React Router) |
| Workspace layout | `artifacts/wetakeyourjob/` is the React app (with `src/pages/`, `src/dashboard/`, `src/demo/` for the three sites). `artifacts/api-server/` is the Replit-side API (separate from our VPS backend). `lib/` has shared `api-client-react`, `api-spec`, `api-zod`, `db`. |
| Backend API (operator dashboard) | `https://api.wetakeyourjob.com/{tenant}/dashboard/api/` (multi-tenant path-prefix routing — see nginx section) |
| Auth | Password → session token (`wtyj_token_{tenant}`) → Bearer header. Tenant selection persists in `localStorage.wtyj_client`. |
| Default tenant passwords | BlueMarlin=`123`, Adamus=`456`, Consulta Despertares=`789`. ⚠️ Change before public launch. |

### Legacy / superseded (do not use for new work)

| Item | Status | Notes |
|------|--------|-------|
| `BensonOpas/wetakeyourjob-dashboard` (GitHub repo) | **PENDING ARCHIVE** | Old dashboard-only repo. Last commit `4023e54` (2026-04-11 18:29 UTC) was the final dashboard-only push before the merge. Archive on GitHub Settings → Danger Zone once the new merged project is fully verified. The history will remain read-only forever. |
| `~/Projects/wetakeyourjob-dashboard/` (local clone) | Outdated | Mirrors the soon-to-be-archived repo. Don't push from here. |
| `https://bluemarlindashboard.replit.app/` | Superseded | Was the old hosted URL for the dashboard-only Replit. Replaced by `wetakeyourjob.com/dashboard`. |
| `https://bmdashboard.wetakeyourjob.com/` | Leftover deployment | Served from a separate "Client Overview Dashboard" Replit project (visible in SR's project list). Still alive because it's covered by the `*.wetakeyourjob.com` CORS regex, but it's a parallel deploy to the canonical merged version. **Should be killed** by archiving the "Client Overview Dashboard" Replit project and removing the `bmdashboard` DNS record from the DNS provider. |
| ARCHIVE - WTYJ Operator Dashboard (Replit) | Archived by SR | The old operator dashboard's Replit project (was connected to `wetakeyourjob-dashboard` GitHub repo). |
| ARCHIVE - BlueMarlin Demo Site (Replit) | Archived by SR | The old standalone booking demo project. Now lives at `/demo/bluemarlin/` inside the merged project. |

### Known repo cleanup todo

- `wetakeyourjob-full-reference.zip` is committed to the new repo at the root (~46.5 MB binary). This was an export SR created on 2026-04-12 02:16 UTC ("Add a downloadable zip file containing the full project reference documentation"). It bloats every clone and lingers in git history forever. Recommendation: remove it from the latest commit (`git rm wetakeyourjob-full-reference.zip && git commit && git push`) and add `*.zip` to `.gitignore`. The matching `wetakeyourjob-full-reference.tar.gz` (6 KB) is fine to keep.

### CORS allowed origins
```
http://localhost:5173          # Vite dev
http://localhost:3000          # Dev fallback
https://api.wetakeyourjob.com  # VPS API
https://wetakeyourjob.com      # Bare apex (added 2026-04-11, commit d910d4d, after the merged Replit project went live)
https://bluemarlindashboard.replit.app
https://wtyj-dashboard.replit.app
https://*.replit.dev|app       # Regex for all Replit domains (allow_origin_regex)
https://*.wetakeyourjob.com    # All WTYJ subdomains (added Brief 184 session, allow_origin_regex)
```

**Note on the bare apex fix:** the regex `https://.*\.wetakeyourjob\.com$` requires a subdomain prefix (`.something.wetakeyourjob.com`), so it does NOT match the bare apex `https://wetakeyourjob.com`. The apex had to be added to the explicit `allow_origins` list, otherwise the merged dashboard at `wetakeyourjob.com/dashboard/login` failed CORS preflight and SR's catch handler displayed a misleading "Invalid access key" error. Source: `wtyj/agents/social/webhook_server.py:35`.

---

## Email

| Item | Value |
|------|-------|
| Marina's inbox | `hello@wetakeyourjob.com` (Microsoft Outlook, OAuth2) |
| Adamus inbox (created, not yet polled) | `sophia@wetakeyourjob.com` (Microsoft Outlook via GoDaddy — needs OAuth bootstrap) |
| IMAP host | `outlook.office365.com:993` |
| SMTP host | `smtp.office365.com:587` |
| Demo support/relay | `butlerbensonagent@gmail.com` |

### Email Authentication (DNS)

| Record | Type | Value |
|--------|------|-------|
| SPF | TXT @ | `v=spf1 include:spf.protection.outlook.com -all` |
| DKIM selector1 | CNAME | `selector1-wetakeyourjob-com._domainkey.NETORGFT20395980.p-v1.dkim.mail.microsoft` |
| DKIM selector2 | CNAME | `selector2-wetakeyourjob-com._domainkey.NETORGFT20395980.p-v1.dkim.mail.microsoft` |
| DMARC | TXT _dmarc | `v=DMARC1; p=none; rua=mailto:hello@wetakeyourjob.com; fo=1; adkim=s; aspf=s; pct=100` |

---

## WhatsApp / Messaging Channels

### BlueMarlin WhatsApp (live as of 2026-04-06)

| Item | Value |
|------|-------|
| Phone number | `+1 (515) 500-5577` (E.164: `+15155005577`) |
| Type | Twilio number connected to Zernio for WhatsApp Business |
| Display name in Meta WhatsApp Business | "BlueMarlin Tours Curaçao" (set in Zernio dashboard) ⚠️ note: client.json `business.name` is "BlueMarlin Charters" — Zernio profile name and platform business name are slightly inconsistent, customers may see both. Cosmetic, not blocking. |
| WhatsApp profile name in Meta | "Name not set" — needs to be configured in the Meta WhatsApp Business profile |
| Daily message limit | 250/day (Zernio plan tier) |
| Webhook path | Inbound: Zernio → `https://api.wetakeyourjob.com/webhooks/zernio` → BlueMarlin's container (HMAC-SHA256 signed). Brief 143 routes WhatsApp through the same Zernio webhook as IG/FB DMs. |
| Outbound | Marina sends replies via Zernio's `send_dm` API (not Meta Cloud API directly anymore, post-Brief-143) |
| Verified working | 2026-04-06 21:48 UTC — multiple test messages from Calvin Adamus processed end-to-end (received via Zernio webhook → debounced → Claude → reply sent via Zernio API). See `marina_output_154.md` open work memory for the test trace. |

### Adamus WhatsApp

Not connected. Adamus has zero live channels right now (no WhatsApp number, no email OAuth bootstrap, no IG/FB pages). Email is the simplest first channel — see `memory/project_open_work.md` IMMEDIATE section for the OAuth bootstrap procedure for sophia@wetakeyourjob.com.

### Meta WhatsApp Cloud API (legacy, ARCHIVED)

| Item | Value |
|------|-------|
| Status | ARCHIVED in Meta developer dashboard at https://developers.facebook.com/apps/3092097104309170/ |
| Why | Brief 143 migrated WhatsApp to Zernio. Meta app left in archived state as a fallback rollback path. |
| Re-enable | Unarchive the app in Meta dashboard. Webhook server still has all the env vars (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, etc.) and the `/webhooks/meta/whatsapp` endpoint is still alive. Restoration is one click in Meta. |

### Instagram + Facebook (BlueMarlin)

Connected via Zernio. See Zernio section below for IG/FB account IDs.

---

## Google Workspace CLI (gws)

| Item | Value |
|------|-------|
| Binary path | `/usr/local/bin/gws` (downloaded in Dockerfile from googleworkspace/cli releases) |
| Auth env var | `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` (set in each client's docker-compose `environment:` block) |
| Credentials file (BlueMarlin host) | `/root/clients/bluemarlin/config/calendar-key.json` |
| Credentials file (Adamus host) | `/root/clients/adamus/config/calendar-key.json` |
| Credentials file (inside container) | `/app/config/calendar-key.json` (mounted from host) |
| BlueMarlin spreadsheet ID | `1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I` |
| Adamus spreadsheet ID | `1OYtPI5Fn7btaPROsJgtpXnoWR025cbjHWudHx2a8ggc` |
| Service account | `bluemarlin-calendar@bluemarlin-ops.iam.gserviceaccount.com` (rename to wtyj-* deferred — see roadmap) |

### Adamus Google Calendars (per-service)

| Service | Calendar ID |
|---------|-------------|
| Adamus Lunch | `c3058824908775658a72e60877f8cea295b54b2b0d5c1c5a33c295e0ec2f8094@group.calendar.google.com` |
| Adamus Dinner | `5b51d6514c5576577fd39e8cb385c0fbcbfc285d283b8ca27095d322b9af50a1@group.calendar.google.com` |

Both calendars owned by `butlerbensonagent@gmail.com` (Benson's personal Google account), shared with the `bluemarlin-calendar@bluemarlin-ops.iam.gserviceaccount.com` service account with "Make changes to events" permission.

### BlueMarlin Google Calendars (per-service slot)

5 services (klein_curacao, snorkeling_3in1, west_coast_beach, sunset_cruise, jet_ski) — each slot in `clients/bluemarlin/config/client.json` has its own `calendar_id` field. See client.json for the full list. Calendars owned by `ops.bluemarlindemo@gmail.com` and shared with the same service account.

---

## Zernio (Late) Account

| Item | Value |
|------|-------|
| Login email | `calvin@gaimin.io` (SR's email — move to business email later) |
| SDK package | `late-sdk` v1.3.35 (import as `from late import Late` or `from zernio import Zernio`) |
| Plan | Build + Comments & DMs ($29/mo) |
| Billing anchor | 16th of each month |
| Profile ID | `69b868672cde65a782026248` ("Default Profile") |
| Instagram account | `bluemarlincharters` (ID: `69b8689d6cb7b8cf4c7846ff`) |
| Facebook account | BlueMarlin Tours Curacao (ID: `69bb24a66cb7b8cf4c8074aa`) |

For full Zernio feature reference → `memory/reference_late_dms.md`

---

## Console Convention

- **"Run on VPS:"** → SSH session at `root@108.61.192.52`
- **"Run on Mac:"** → Benson's local terminal

Never say "run this command" without specifying which machine.

---

## Things Claude Code Keeps Getting Wrong

1. **API key location** — in each client's `platform.env` at `/root/clients/<client>/config/platform.env`. NOT in `.bashrc` or shell profile. NOT in source code.
2. **Poller is always running** — do not start it. Just restart the container after deploys (`docker compose down && up -d`).
3. **VPS source path** — `/root/wtyj/`, NOT `/root/bluemarlin/` (legacy, removed in Brief 151).
4. **VPS client deployment paths** — `/root/clients/bluemarlin/`, `/root/clients/adamus/`. Each client has its own `docker-compose.yml`.
5. **SSH from Claude Code** — works. Key auth set up. No password needed.
6. **bm_logger.log() first arg** — the parameter is named `event`. Never pass `event=` as a kwarg.
7. **Config caching** — `config_loader.get_raw()` returns a mutable dict. Modifying it in tests leaks between tests.
8. **CLIENT_CONFIG_PATH env var** — set in conftest.py for Mac dev tests so config_loader finds the moved client.json. Inside the container, the legacy default still resolves correctly.
9. **Use `trash` not `rm`** — macOS has `/usr/bin/trash`. Always use it for file deletions.
