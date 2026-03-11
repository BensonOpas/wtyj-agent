# BRIEF 067 — WhatsApp Webhook Server + VPS Infrastructure
**Status:** Draft | **Files:** `agents/social/__init__.py` (new), `agents/social/webhook_server.py` (new), `tests/social/conftest.py` (new), `tests/social/test_067_webhook.py` (new), `briefs/infra.md` (update) | **Depends on:** DNS A record for `api.wetakeyourjob.com` → `108.61.192.52` (SR handling) | **Blocks:** Meta webhook verification, all Phase 1 social agent work

## Context

Marina (email agent) is complete and running in production. Phase 1 of the roadmap is the social agent — starting with WhatsApp Q&A. Meta Business setup is done (app created, WhatsApp Business Account connected, test message sent). We stopped at the webhook configuration screen because Meta needs a live HTTPS endpoint to verify.

The VPS currently runs only the Marina email poller. There is no web server, no nginx, no SSL, and no FastAPI installed. We need to stand up the full HTTPS webhook infrastructure from scratch so Meta can verify the callback URL and start sending WhatsApp events.

## Why This Approach

We need a publicly reachable HTTPS endpoint that Meta can verify. The simplest path: FastAPI (lightweight, async-native) behind nginx (handles SSL termination, reverse proxy) with Let's Encrypt (free, auto-renewable certs). This matches the architecture decided in the roadmap (Milestone A).

We're logging payloads only — no agent logic, no message processing, no HMAC signature verification yet. This is the minimum viable webhook: get verified by Meta, confirm events arrive. Agent logic comes in later briefs. HMAC hardening comes in the social hardening milestone (C).

The webhook server runs as a separate systemd service (`bluemarlin-social`) parallel to the existing `bluemarlin` service. Each service has its own process, own restart policy, and can be managed independently.

## Source Material

### Meta Webhook Verification Protocol
- Meta sends GET to callback URL with query params: `hub.mode`, `hub.verify_token`, `hub.challenge`
- If `hub.mode == "subscribe"` AND `hub.verify_token` matches our stored token, return `hub.challenge` as plain text with status 200
- Otherwise return 403
- After verification, Meta sends POST requests with JSON payloads for all subscribed events

### Env Vars (user has all values)
```
META_APP_ID=<Facebook App ID>
META_APP_SECRET=<Facebook App Secret>
WHATSAPP_VERIFY_TOKEN=bluemarlin_whatsapp_verify_2026_7fK9xP3mQ8vL2zN5rT1wB6dH4
WHATSAPP_ACCESS_TOKEN=<temporary token from Meta — expires ~24h, permanent token later>
WHATSAPP_PHONE_NUMBER_ID=990622044139349
WHATSAPP_BUSINESS_ACCOUNT_ID=967346842390828
```

### Callback URL
```
https://api.wetakeyourjob.com/webhooks/meta/whatsapp
```

### Existing systemd pattern (from bluemarlin.service)
```ini
[Unit]
Description=BlueMarlin Autonomous Booking Agent
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/bluemarlin
EnvironmentFile=-/root/bluemarlin/config/bluemarlin.env
ExecStart=/usr/bin/python3 -m agents.marina.email_poller
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=bluemarlin

[Install]
WantedBy=multi-user.target
```

## Instructions

### Step 1 — Create `agents/social/__init__.py`
Empty file. Creates the package.

### Step 2 — Create `agents/social/webhook_server.py`

```python
# bluemarlin/agents/social/webhook_server.py
# Created: Brief 067
# Last modified: Brief 067
# Purpose: FastAPI webhook receiver for Meta WhatsApp Cloud API

import os
from fastapi import FastAPI, Request, Response, Query
from fastapi.responses import PlainTextResponse

from shared.bm_logger import log

app = FastAPI(title="BlueMarlin Social Webhook", docs_url=None, redoc_url=None)

_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")


@app.get("/webhooks/meta/whatsapp")
async def verify_webhook(
    response: Response,
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification — returns challenge if token matches."""
    if hub_mode == "subscribe" and hub_verify_token == _VERIFY_TOKEN:
        log("webhook_verified", source="meta_whatsapp")
        return PlainTextResponse(content=hub_challenge, status_code=200)
    log("webhook_verify_failed", source="meta_whatsapp", mode=hub_mode)
    return PlainTextResponse(content="Forbidden", status_code=403)


@app.post("/webhooks/meta/whatsapp")
async def receive_webhook(request: Request):
    """Receive WhatsApp webhook events — log payload, return 200 immediately."""
    try:
        payload = await request.json()
    except Exception:
        payload = {"raw": (await request.body()).decode("utf-8", errors="replace")}
    log("webhook_received", source="meta_whatsapp", payload=payload)
    return PlainTextResponse(content="OK", status_code=200)


@app.get("/health")
async def health():
    """Health check for monitoring."""
    return {"status": "ok"}
```

### Step 3 — Create `tests/social/conftest.py`

```python
# bluemarlin/tests/social/conftest.py
# Created: Brief 067
# Purpose: Shared test config for social agent tests
import sys
import os
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))
```

### Step 4 — Create `tests/social/test_067_webhook.py`

```python
# bluemarlin/tests/social/test_067_webhook.py
# Created: Brief 067
# Purpose: Tests for WhatsApp webhook server

import os
import sys
import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ["WHATSAPP_VERIFY_TOKEN"] = "test_token_067"

from fastapi.testclient import TestClient
from agents.social.webhook_server import app

client = TestClient(app)


def test_verify_valid_token():
    """GET with correct token returns 200 + challenge."""
    r = client.get("/webhooks/meta/whatsapp", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "test_token_067",
        "hub.challenge": "challenge_abc123",
    })
    assert r.status_code == 200
    assert r.text == "challenge_abc123"


def test_verify_wrong_token():
    """GET with wrong token returns 403."""
    r = client.get("/webhooks/meta/whatsapp", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "wrong_token",
        "hub.challenge": "challenge_abc123",
    })
    assert r.status_code == 403


def test_verify_missing_mode():
    """GET with missing hub.mode returns 403."""
    r = client.get("/webhooks/meta/whatsapp", params={
        "hub.verify_token": "test_token_067",
        "hub.challenge": "challenge_abc123",
    })
    assert r.status_code == 403


def test_verify_wrong_mode():
    """GET with wrong hub.mode returns 403."""
    r = client.get("/webhooks/meta/whatsapp", params={
        "hub.mode": "unsubscribe",
        "hub.verify_token": "test_token_067",
        "hub.challenge": "challenge_abc123",
    })
    assert r.status_code == 403


def test_post_json_payload():
    """POST with JSON body returns 200."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "967346842390828", "changes": []}]
    }
    r = client.post("/webhooks/meta/whatsapp", json=payload)
    assert r.status_code == 200
    assert r.text == "OK"


def test_post_empty_body():
    """POST with empty body returns 200 (never reject Meta)."""
    r = client.post("/webhooks/meta/whatsapp", content=b"", headers={"content-type": "application/json"})
    assert r.status_code == 200


def test_health_endpoint():
    """GET /health returns ok."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

### Step 5 — Install VPS packages

SSH to VPS and run:
```bash
apt update && apt install -y nginx certbot python3-certbot-nginx
pip3 install fastapi uvicorn
```

### Step 6 — Create nginx config on VPS

Write to `/etc/nginx/sites-available/api-wetakeyourjob`:
```nginx
server {
    listen 80;
    server_name api.wetakeyourjob.com;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Then enable and start:
```bash
ln -sf /etc/nginx/sites-available/api-wetakeyourjob /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl enable nginx && systemctl start nginx
```

Note: certbot will modify this config to add SSL after we run it (Step 9).

### Step 7 — Create systemd service on VPS

Write to `/etc/systemd/system/bluemarlin-social.service`:
```ini
[Unit]
Description=BlueMarlin Social Webhook Server
After=network.target nginx.service
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/bluemarlin
EnvironmentFile=-/root/bluemarlin/config/bluemarlin.env
ExecStart=/usr/bin/python3 -m uvicorn agents.social.webhook_server:app --host 127.0.0.1 --port 8001
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=bluemarlin-social

[Install]
WantedBy=multi-user.target
```

Then enable and start:
```bash
systemctl daemon-reload && systemctl enable bluemarlin-social && systemctl start bluemarlin-social
```

### Step 8 — Add env vars to VPS

Append to `/root/bluemarlin/config/bluemarlin.env`:
```
# --- Social Agent (Brief 067) ---
META_APP_ID=<user provides>
META_APP_SECRET=<user provides>
WHATSAPP_VERIFY_TOKEN=bluemarlin_whatsapp_verify_2026_7fK9xP3mQ8vL2zN5rT1wB6dH4
WHATSAPP_ACCESS_TOKEN=<user provides — temporary, expires ~24h>
WHATSAPP_PHONE_NUMBER_ID=990622044139349
WHATSAPP_BUSINESS_ACCOUNT_ID=967346842390828
```

User must provide actual values for META_APP_ID, META_APP_SECRET, and WHATSAPP_ACCESS_TOKEN before this step.

### Step 9 — SSL cert via certbot (requires DNS to be live)

First verify DNS resolves:
```bash
dig +short api.wetakeyourjob.com A
```
Must return `108.61.192.52`. If not, wait for propagation.

Then run certbot:
```bash
certbot --nginx -d api.wetakeyourjob.com --non-interactive --agree-tos -m butlerbensonagent@gmail.com
```

This will auto-modify the nginx config to add SSL and redirect HTTP → HTTPS.

After certbot:
```bash
systemctl reload nginx
```

### Step 10 — Deploy webhook code to VPS

From Mac repo root:
```bash
git add agents/social/ tests/social/
git push
```

On VPS:
```bash
cd /root/bluemarlin && git pull && systemctl restart bluemarlin-social
```

### Step 11 — Update `briefs/infra.md`

Add a new section after the "Poller Process" section:

```markdown
## Social Webhook Server

The WhatsApp webhook server runs as a separate FastAPI process behind nginx.

| Item | Value |
|------|-------|
| Service name | `bluemarlin-social` |
| Status check | `systemctl status bluemarlin-social` |
| Restart | `systemctl restart bluemarlin-social` |
| Logs (tail) | `journalctl -u bluemarlin-social -n 50` |
| Internal port | `8001` (localhost only) |
| Public URL | `https://api.wetakeyourjob.com/webhooks/meta/whatsapp` |
| nginx config | `/etc/nginx/sites-available/api-wetakeyourjob` |
| SSL cert | Let's Encrypt via certbot (auto-renew) |
| Health check | `curl -s https://api.wetakeyourjob.com/health` |
```

### Step 12 — Verify

1. Health check: `curl -s https://api.wetakeyourjob.com/health` → `{"status":"ok"}`
2. GET verification test:
   ```bash
   curl -s "https://api.wetakeyourjob.com/webhooks/meta/whatsapp?hub.mode=subscribe&hub.verify_token=bluemarlin_whatsapp_verify_2026_7fK9xP3mQ8vL2zN5rT1wB6dH4&hub.challenge=test123"
   ```
   → returns `test123` with status 200
3. POST test:
   ```bash
   curl -s -X POST https://api.wetakeyourjob.com/webhooks/meta/whatsapp -H "Content-Type: application/json" -d '{"test": true}'
   ```
   → returns `OK` with status 200
4. Check log on VPS: `tail -5 /root/bluemarlin/logs/bluemarlin.log` — should show `webhook_received` event

## Tests

File: `tests/social/test_067_webhook.py` (7 tests)

1. `test_verify_valid_token` — GET with correct mode+token returns 200, body == `"challenge_abc123"`
2. `test_verify_wrong_token` — GET with wrong token returns 403
3. `test_verify_missing_mode` — GET with no hub.mode returns 403
4. `test_verify_wrong_mode` — GET with hub.mode != "subscribe" returns 403
5. `test_post_json_payload` — POST with WhatsApp-shaped JSON returns 200, body == `"OK"`
6. `test_post_empty_body` — POST with empty body returns 200 (never reject Meta)
7. `test_health_endpoint` — GET /health returns 200 with `{"status": "ok"}`

## Success Condition

`https://api.wetakeyourjob.com/webhooks/meta/whatsapp` is live, returns challenge on GET verification, logs payloads on POST, all 7 local tests pass, and the endpoint is ready for Meta webhook verification.

## Rollback

1. Stop and disable social service: `systemctl stop bluemarlin-social && systemctl disable bluemarlin-social`
2. Remove service file: `rm /etc/systemd/system/bluemarlin-social.service && systemctl daemon-reload`
3. Remove nginx config: `rm /etc/nginx/sites-enabled/api-wetakeyourjob /etc/nginx/sites-available/api-wetakeyourjob && systemctl reload nginx`
4. Remove env vars: edit `/root/bluemarlin/config/bluemarlin.env`, delete the "Social Agent (Brief 067)" block
5. Remove code: `git rm -r agents/social/ tests/social/` and commit
6. Marina email poller is completely unaffected — separate process, separate service.
