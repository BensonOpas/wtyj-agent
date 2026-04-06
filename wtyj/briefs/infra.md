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

All secrets live in `/root/bluemarlin/config/bluemarlin.env`.
**NOT in `.bashrc`, `.zshrc`, or `.profile`** — never look there.
The systemd units source this file at startup.

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
| `DASHBOARD_PASSWORD` | Dashboard | Operator login password (generates in-memory session token) |
| `OPENAI_API` | OpenAI | Optional: DALL-E image generation for content pipeline |
| `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` | gws CLI | Set at runtime to path of service account key |
| `AZURE_CLIENT_ID` | Email poller | Microsoft Azure app client ID. Default: BlueFinn's app. |
| `AZURE_TENANT_ID` | Email poller | Microsoft Azure tenant ID. Default: BlueFinn's tenant. |
| `EMAIL_ADDRESS` | Email poller | Inbox email address to poll. Default: hello@wetakeyourjob.com |

### Credential files

| File | VPS Path | Purpose |
|------|----------|---------|
| `platform.env` | `/root/bluemarlin/config/platform.env` | All env vars above (renamed from bluemarlin.env in Brief 145) |
| `calendar-key.json` | `/root/bluemarlin/config/calendar-key.json` | Google service account key (renamed from bluemarlin-calendar-key.json) |
| `azure_refresh_token.txt` | `/root/bluemarlin/config/azure_refresh_token.txt` | Microsoft OAuth2 refresh token (persisted, auto-rotated) |
| `client.json` | `/root/bluemarlin/config/client.json` | Business config (not credentials — safe in git) |

### Email mailboxes (GoDaddy / Microsoft 365)

GoDaddy email plan currently has 2 seats total.

| Mailbox | Client | Password | Notes |
|---------|--------|----------|-------|
| `marina@wetakeyourjob.com` | BlueFinn Charters | (not recorded — uses stored OAuth refresh token) | Primary BlueFinn inbox. Polled by email_poller via Microsoft Graph OAuth. |
| `sophia@wetakeyourjob.com` | Restaurant Adamus (demo) | `Cur@ao2026` | Repurposed from a previously unused seat. Needs interactive OAuth login to generate initial refresh token. |

### Hardcoded constants in source (not env vars — Brief 145 moved to env vars)

| Constant | File | Value | Purpose |
|----------|------|-------|---------|
| ~~Microsoft `CLIENT_ID`~~ | ~~email_poller.py:27~~ | Now env var `AZURE_CLIENT_ID` (default: BlueFinn's) | Azure app registration |
| ~~Microsoft `TENANT_ID`~~ | ~~email_poller.py:28~~ | Now env var `AZURE_TENANT_ID` (default: BlueFinn's) | Azure tenant |
| ~~`EMAIL_ADDR`~~ | ~~email_poller.py:29~~ | Now env var `EMAIL_ADDRESS` (default: hello@wetakeyourjob.com) | Inbox to poll |
| WhatsApp API version | whatsapp_client.py:14 | `v22.0` | Meta Cloud API version |

---

## Services (Docker — as of Brief 142)

Single Docker container running both services via supervisord.

Two containers, one shared image. Multi-client architecture proven and isolated as of Brief 152.

| Client | Container name | Port | Compose file | Runtime dir |
|--------|----------------|------|--------------|-------------|
| BlueMarlin Charters (demo #1) | `wtyj-bluemarlin` | 8001 | `/root/clients/bluemarlin/docker-compose.yml` | `/root/clients/bluemarlin/` |
| Restaurant Adamus (demo #2) | `wtyj-adamus` | 8002 | `/root/clients/adamus/docker-compose.yml` | `/root/clients/adamus/` |

Both containers use the same image `wtyj-agent:latest` (built from `Dockerfile` at `/root/Dockerfile`). Adamus uses `image: wtyj-agent` directly — no rebuild on Adamus deploy. Inside each: `email-poller` + `webhook-server` via supervisord. Adamus's email-poller exits cleanly on startup (Brief 146 graceful-exit path: no EMAIL_ADDRESS, no refresh token).

Runtime isolation: Brief 148 added `.dockerignore` exclusion of `wtyj/config/`, `wtyj/data/`, `wtyj/logs/`, `clients/`, plus directory mounts in both compose files. Each container's `/app/config/` is populated entirely from its own host directory at runtime — zero cross-tenant leakage at the image layer.

### Deploy commands (post-Brief-152)

```bash
# Standard deploy: pull, rebuild image, restart both containers
ssh root@108.61.192.52 "
  cd /root/clients/bluemarlin && docker compose down
  cd /root/clients/adamus && docker compose down
  cd /root && git pull
  cd /root/clients/bluemarlin && docker compose build && docker compose up -d
  cd /root/clients/adamus && docker compose up -d
"

# Health check both
ssh root@108.61.192.52 "curl -s http://localhost:8001/health && echo && curl -s http://localhost:8002/health"

# Inspect running containers
ssh root@108.61.192.52 "docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'"
# Expected: wtyj-bluemarlin and wtyj-adamus, both running wtyj-agent image
```

The shared image `wtyj-agent` is built when BlueMarlin's compose runs `docker compose build`. Adamus's compose references `image: wtyj-agent` directly and pulls the just-built image — no separate build step. To rebuild only (no restart), use `docker compose build` from `/root/clients/bluemarlin/` alone.

### Old services (systemd — disabled, kept for rollback)

| Service | Command to re-enable |
|---------|---------------------|
| `bluemarlin` (email poller) | `systemctl enable --now bluemarlin` |
| `bluemarlin-social` (webhook server) | `systemctl enable --now bluemarlin-social` |

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
| nginx config | `/etc/nginx/sites-available/api-wetakeyourjob` |
| Public domain | `api.wetakeyourjob.com` |
| SSL cert | Let's Encrypt via certbot (auto-renew) |
| SSL expiry | 2026-06-09 |
| Proxies to | `http://127.0.0.1:8001` |
| Health check | `curl -s https://api.wetakeyourjob.com/health` |

---

## Dashboard

| Item | Value |
|------|-------|
| Frontend repo | `BensonOpas/wetakeyourjob-dashboard` (GitHub, private) |
| Local path | `~/Projects/wetakeyourjob-dashboard/` |
| Hosted URL | `https://bluemarlindashboard.replit.app/` |
| Stack | React 19 + Vite + Tailwind + shadcn/ui + TanStack Query |
| Backend API | `https://api.wetakeyourjob.com/dashboard/api/` |
| Auth | Password → session token → Bearer header |

### CORS allowed origins
```
http://localhost:5173          # Vite dev
http://localhost:3000          # Dev fallback
https://api.wetakeyourjob.com  # VPS API
https://bluemarlindashboard.replit.app
https://wtyj-dashboard.replit.app
https://*.replit.dev|app       # Regex for all Replit domains
```

---

## Email

| Item | Value |
|------|-------|
| Marina's inbox | `hello@wetakeyourjob.com` (Microsoft Outlook, OAuth2) |
| IMAP host | `outlook.office365.com:993` |
| SMTP host | `smtp.office365.com:587` |
| Demo support/relay | `butlerbensonagent@gmail.com` |
| Production support | `info@bluefinncharters.com` (from client.json) |

### Email Authentication (DNS)

| Record | Type | Value |
|--------|------|-------|
| SPF | TXT @ | `v=spf1 include:spf.protection.outlook.com -all` |
| DKIM selector1 | CNAME | `selector1-wetakeyourjob-com._domainkey.NETORGFT20395980.p-v1.dkim.mail.microsoft` |
| DKIM selector2 | CNAME | `selector2-wetakeyourjob-com._domainkey.NETORGFT20395980.p-v1.dkim.mail.microsoft` |
| DMARC | TXT _dmarc | `v=DMARC1; p=none; rua=mailto:hello@wetakeyourjob.com; fo=1; adkim=s; aspf=s; pct=100` |

---

## Google Workspace CLI (gws)

| Item | Value |
|------|-------|
| Binary path | `/usr/bin/gws` |
| Auth env var | `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` |
| Credentials file | `/root/bluemarlin/config/bluemarlin-calendar-key.json` |
| Spreadsheet ID | `1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I` |
| Service account | `bluemarlin-calendar@bluemarlin-ops.iam.gserviceaccount.com` |

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

## Deploy Flow (Docker — as of Brief 142)

```bash
# Code-only deploy (no new packages)
ssh root@108.61.192.52 "cd /root && git pull && docker compose build && docker compose up -d"

# Full rebuild (new packages or Dockerfile changes)
ssh root@108.61.192.52 "cd /root && git pull && docker compose down && docker compose build --no-cache && docker compose up -d"

# Check status
ssh root@108.61.192.52 "docker compose ps && curl -s http://localhost:8001/health"

# View logs
ssh root@108.61.192.52 "docker compose logs --tail=50"
```

Key auth configured — no password needed.

**Rollback to systemd (if Docker fails):**
```bash
ssh root@108.61.192.52 "docker compose down && systemctl start bluemarlin && systemctl start bluemarlin-social"
```

### Old deploy flow (systemd — disabled, kept for rollback)
```bash
ssh root@108.61.192.52 "cd /root/bluemarlin && git pull && systemctl restart bluemarlin && systemctl restart bluemarlin-social"
```

---

## Console Convention

- **"Run on VPS:"** → SSH session at `root@108.61.192.52`
- **"Run on Mac:"** → Benson's local terminal

Never say "run this command" without specifying which machine.

---

## Things Claude Code Keeps Getting Wrong

1. **API key location** — in `bluemarlin.env`, NOT in `.bashrc` or shell profile.
2. **Poller is always running** — do not start it. Just restart after deploys.
3. **VPS project path** — `/root/bluemarlin/`, NOT `/root/bluemarlin-agent/` (Mac path).
4. **SSH from Claude Code** — works. Key auth set up. No password needed.
5. **bm_logger.log() first arg** — the parameter is named `event`. Never pass `event=` as a kwarg.
6. **Config caching** — `config_loader.get_raw()` returns a mutable dict. Modifying it in tests leaks between tests.
7. **Use `trash` not `rm`** — macOS has `/usr/bin/trash`. Always use it for file deletions.
