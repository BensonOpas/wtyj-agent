# OUTPUT 067 — WhatsApp Webhook Server + VPS Infrastructure

## What Was Done

### Local (Mac)
1. Created `agents/social/__init__.py` (empty package)
2. Created `agents/social/webhook_server.py` — FastAPI app with GET/POST webhook handlers + /health endpoint
3. Created `tests/social/conftest.py` — sys.path setup for social tests
4. Created `tests/social/test_067_webhook.py` — 7 tests covering verification, payload receipt, edge cases
5. Updated `briefs/infra.md` — added Social Webhook Server section

### VPS
1. Installed nginx 1.24.0, certbot 2.9.0, python3-certbot-nginx
2. Installed FastAPI 0.135.1, uvicorn 0.41.0 (system-wide pip, matching existing pattern)
3. Created nginx config at `/etc/nginx/sites-available/api-wetakeyourjob` — reverse proxy port 443 → localhost:8001
4. Opened firewall ports 80/tcp and 443/tcp (ufw) — were previously closed
5. Obtained Let's Encrypt SSL cert for `api.wetakeyourjob.com` (expires 2026-06-09, auto-renew enabled)
6. Created systemd service `bluemarlin-social` — enabled, active
7. Added 6 env vars to `/root/bluemarlin/config/bluemarlin.env` (META_APP_ID, META_APP_SECRET, WHATSAPP_VERIFY_TOKEN, WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_BUSINESS_ACCOUNT_ID)
8. Deployed code via git pull + service restart

## Test Results

### Local (7/7 pass)
```
tests/social/test_067_webhook.py::test_verify_valid_token PASSED
tests/social/test_067_webhook.py::test_verify_wrong_token PASSED
tests/social/test_067_webhook.py::test_verify_missing_mode PASSED
tests/social/test_067_webhook.py::test_verify_wrong_mode PASSED
tests/social/test_067_webhook.py::test_post_json_payload PASSED
tests/social/test_067_webhook.py::test_post_empty_body PASSED
tests/social/test_067_webhook.py::test_health_endpoint PASSED
```

### Live Verification (3/3 pass)
- `curl https://api.wetakeyourjob.com/health` → `{"status":"ok"}`
- `curl "https://api.wetakeyourjob.com/webhooks/meta/whatsapp?hub.mode=subscribe&hub.verify_token=...&hub.challenge=test123"` → `test123`
- `curl -X POST https://api.wetakeyourjob.com/webhooks/meta/whatsapp -d '{"test":true}'` → `OK`

### Log Verification
VPS logs show all 3 event types: `webhook_verify_failed` (before env vars set), `webhook_received`, `webhook_verified`

## Anything Unexpected

1. **pip3 install failed initially** — Ubuntu Noble (24.04) blocks system-wide pip installs by default. Used `--break-system-packages` flag, matching how existing packages (anthropic, etc.) were installed.
2. **Certbot failed on first attempt** — VPS firewall (ufw) only had port 22 open. Added ports 80 and 443. Certbot succeeded on retry.
3. **GET verification returned Forbidden initially** — Expected: env vars weren't set yet. After adding WHATSAPP_VERIFY_TOKEN and restarting service, verification works correctly.

## Next Steps

- **Meta webhook verification:** Go to Meta Developer Console → WhatsApp → Configuration → enter callback URL `https://api.wetakeyourjob.com/webhooks/meta/whatsapp` and verify token `bluemarlin_whatsapp_verify_2026_7fK9xP3mQ8vL2zN5rT1wB6dH4` → click Verify and Save
- **Subscribe to messages:** After verification, subscribe to the `messages` webhook field
- **Permanent access token:** Current token is temporary (~24h). Set up a System User token in Meta Business Settings for production use.
