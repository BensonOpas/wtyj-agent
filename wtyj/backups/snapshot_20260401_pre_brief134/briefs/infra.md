# INFRA.md — BlueMarlin Infrastructure Reference

**Owns:** Everything about HOW the system runs — VPS, services, credentials, URLs, ports, nginx, SSL, env vars, deploy commands.
**Related:** For what we're building and why → `master_plan.md`. For what's next → `roadmap.md`. For what each brief did → `system_state.md`.

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

| Item | Value |
|------|-------|
| Project root | `/root/bluemarlin/` |
| Marina agent | `/root/bluemarlin/agents/marina/` |
| Social agent | `/root/bluemarlin/agents/social/` |
| Dashboard API | `/root/bluemarlin/dashboard/` |
| Shared libs | `/root/bluemarlin/shared/` |
| Runtime data | `/root/bluemarlin/data/` (SQLite DB, graphics, photos) |
| Config files | `/root/bluemarlin/config/` |
| Log directory | `/root/bluemarlin/logs/` |
| Log file | `bluemarlin.log` (JSONL via bm_logger) |

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

### Credential files

| File | VPS Path | Purpose |
|------|----------|---------|
| `bluemarlin.env` | `/root/bluemarlin/config/bluemarlin.env` | All env vars above |
| `bluemarlin-calendar-key.json` | `/root/bluemarlin/config/bluemarlin-calendar-key.json` | Google service account key (Calendar + Sheets) |
| `azure_refresh_token.txt` | `/root/bluemarlin/config/azure_refresh_token.txt` | Microsoft OAuth2 refresh token (persisted, auto-rotated) |
| `client.json` | `/root/bluemarlin/config/client.json` | Business config (not credentials — safe in git) |

### Hardcoded constants in source (not env vars)

| Constant | File | Value | Purpose |
|----------|------|-------|---------|
| Microsoft `CLIENT_ID` | email_poller.py:27 | `28e94343-2f77-444c-ac32-58b7bed33b65` | Azure app registration |
| Microsoft `TENANT_ID` | email_poller.py:28 | `caac06b5-1420-4223-9dcc-ba4a670ec26a` | Azure tenant |
| `EMAIL_ADDR` | email_poller.py:29 | `hello@wetakeyourjob.com` | Marina's inbox |
| WhatsApp API version | whatsapp_client.py:14 | `v22.0` | Meta Cloud API version |

---

## Services (systemd)

### Email Poller

| Item | Value |
|------|-------|
| Service name | `bluemarlin` |
| What it does | IMAP polling → Marina agent → booking flow → SMTP reply |
| Status | `systemctl is-active bluemarlin` |
| Restart | `systemctl restart bluemarlin` |
| Logs | `journalctl -u bluemarlin -n 50` |

### Social Webhook Server

| Item | Value |
|------|-------|
| Service name | `bluemarlin-social` |
| What it does | FastAPI: WhatsApp webhook + Zernio DM webhook + dashboard API + scheduler |
| Internal port | `8001` (localhost only) |
| Status | `systemctl is-active bluemarlin-social` |
| Restart | `systemctl restart bluemarlin-social` |
| Logs | `journalctl -u bluemarlin-social -n 50` |

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

## Deploy Flow

```bash
# Full deploy (both services)
ssh root@108.61.192.52 "cd /root/bluemarlin && git pull && systemctl restart bluemarlin && systemctl restart bluemarlin-social"

# Social only (faster, no email restart)
ssh root@108.61.192.52 "cd /root/bluemarlin && git pull && systemctl restart bluemarlin-social"
```

Key auth configured — no password needed.

After adding new pip packages: `ssh root@108.61.192.52 "pip3 install <package> --break-system-packages"`

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
