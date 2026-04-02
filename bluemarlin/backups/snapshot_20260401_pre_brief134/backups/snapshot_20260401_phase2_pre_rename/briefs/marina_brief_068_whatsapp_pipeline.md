# BRIEF 068 — WhatsApp Message Pipeline: Parse, Dedup, Reply
**Status:** Draft | **Files:** `agents/social/webhook_server.py` (modify), `agents/social/whatsapp_client.py` (new), `agents/social/social_agent.py` (new), `shared/state_registry.py` (modify), `tests/social/test_068_pipeline.py` (new) | **Depends on:** Brief 067 (webhook server live) | **Blocks:** Phase 1 social agent Q&A

## Context

Brief 067 deployed a webhook server that receives WhatsApp events and logs raw payloads. It does not parse messages, dedup, or reply. The webhook is verified and receiving real messages (Calvin Adamus sent "Test" on 2026-03-11, payload logged). The permanent System User access token is deployed.

We need to close the loop: receive a WhatsApp message → parse it → dedup → generate a reply → send it back. For now the reply is hardcoded ("Thanks for your message. BlueMarlin test agent is online."). The agent logic stub will be replaced with Claude-powered Q&A in a later brief.

## Why This Approach

SR's spec defines three phases (inbound processing, outbound reply, agent handoff prep) as a single deliverable. This is correct — they're tightly coupled and individually useless. We separate transport (parse + send) from agent logic (generate reply) in different files from the start, so wiring Claude in later is a one-file change to `social_agent.py`.

We use FastAPI BackgroundTasks so the POST handler returns 200 immediately and processing happens after. This is critical when Claude calls replace the stub — a 10-second Claude call would cause Meta to timeout and retry. BackgroundTasks is built into FastAPI and requires zero extra infrastructure.

We use SQLite for message ID dedup (not in-memory) because Meta retries webhook deliveries if the service restarts before processing completes. Matches Marina's pattern.

We use `urllib.request` (stdlib) for outbound API calls to avoid installing new dependencies on the VPS. httpx is only available on Mac (test dependency).

**Hardcoded reply stub (Rule 3 exception):** The agent stub returns a fixed test reply. This is NOT a `safe_X_reply()` routing template — it's a temporary verification fixture explicitly requested by SR to confirm the end-to-end pipeline works (token valid, API call succeeds, reply delivered). It will be replaced with Claude-powered Q&A in the next brief. This is scoped identically to marina_agent.py's accepted API-failure fallback (CLAUDE.md "Known Open Issues"). The stub is gated behind a dedicated function in `social_agent.py` so replacing it is a single-file change.

**Brief 067 test regression:** The modified `webhook_server.py` adds imports for `state_registry`, `whatsapp_client`, and `social_agent`. These execute at module load when Brief 067 tests import `app`. This is safe: `state_registry` creates its DB file idempotently (already happens in conftest.py sys.path setup), and the new modules have no side effects beyond reading env vars. The `Response` import removed from webhook_server.py was unused in the Brief 067 handler (only in the function signature, which now uses FastAPI's automatic response). Brief 067 tests do not reference `Response` directly.

## Source Material

### Real WhatsApp inbound payload (from VPS logs, 2026-03-11)
```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "967346842390828",
    "changes": [{
      "value": {
        "messaging_product": "whatsapp",
        "metadata": {
          "display_phone_number": "15551681192",
          "phone_number_id": "990622044139349"
        },
        "contacts": [{"profile": {"name": "Calvin Adamus"}, "wa_id": "59996881585"}],
        "messages": [{
          "from": "59996881585",
          "id": "wamid.HBgLNTk5OTY4ODE1ODUVAgASGBQyQUI2REU0RTBBQzU0QTU2NzNERAA=",
          "timestamp": "1773265596",
          "text": {"body": "Test"},
          "type": "text"
        }]
      },
      "field": "messages"
    }]
  }]
}
```

### Status update payload (Meta sends these too — must not process as messages)
```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "changes": [{
      "value": {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "15551681192", "phone_number_id": "990622044139349"},
        "statuses": [{"id": "wamid.xxx", "status": "delivered", "timestamp": "123", "recipient_id": "59996881585"}]
      },
      "field": "messages"
    }]
  }]
}
```

### Normalized message object (SR's spec)
```python
{
    "channel": "whatsapp",
    "from": "59996881585",
    "from_name": "Calvin Adamus",
    "message_id": "wamid.HBgL...",
    "text": "Test",
    "timestamp": "1773265596",
    "business_account_id": "967346842390828",
    "phone_number_id": "990622044139349"
}
```

### WhatsApp Cloud API — Send Text Message
```
POST https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages
Authorization: Bearer {ACCESS_TOKEN}
Content-Type: application/json

{
  "messaging_product": "whatsapp",
  "to": "59996881585",
  "type": "text",
  "text": {"body": "Your reply here"}
}
```

Success response: `{"messaging_product": "whatsapp", "contacts": [...], "messages": [{"id": "wamid.xxx"}]}`
Error response: `{"error": {"message": "...", "type": "...", "code": ...}}`

### Env vars (already on VPS from Brief 067)
```
WHATSAPP_ACCESS_TOKEN=<permanent System User token>
WHATSAPP_PHONE_NUMBER_ID=990622044139349
```

## Instructions

### Step 1 — Add WhatsApp dedup to `shared/state_registry.py`

Add a new table in `_get_conn()` after the `bookings` table creation:

```python
    conn.execute(
        "CREATE TABLE IF NOT EXISTS whatsapp_processed ("
        "message_id TEXT PRIMARY KEY, "
        "created_at TEXT NOT NULL"
        ")"
    )
```

Add two new functions at the end of the file (before the module-load init):

```python
def wa_has_been_processed(message_id: str) -> bool:
    """Check if a WhatsApp message ID has already been processed."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM whatsapp_processed WHERE message_id = ?",
        (message_id,)
    ).fetchone()
    conn.close()
    return row is not None


def wa_mark_as_processed(message_id: str):
    """Record a WhatsApp message ID as processed."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO whatsapp_processed (message_id, created_at) VALUES (?, ?)",
        (message_id, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()
```

Update the file header: `# Last modified: Brief 068`

### Step 2 — Create `agents/social/whatsapp_client.py`

```python
# bluemarlin/agents/social/whatsapp_client.py
# Created: Brief 068
# Last modified: Brief 068
# Purpose: Parse inbound WhatsApp payloads + send outbound replies via Cloud API

import json
import os
import urllib.request

from shared.bm_logger import log

_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
_API_VERSION = "v22.0"


def parse_webhook_payload(payload: dict) -> list:
    """
    Extract normalized message objects from a Meta webhook payload.
    Returns a list of dicts. Skips status updates and non-message events.
    Non-text messages are included with text=None.
    """
    messages = []
    try:
        for entry in payload.get("entry", []):
            business_account_id = entry.get("id", "")
            for change in entry.get("changes", []):
                value = change.get("value", {})
                # Skip status updates (delivered, read, etc.)
                if "statuses" in value and "messages" not in value:
                    log("webhook_status_update", source="meta_whatsapp",
                        statuses=value.get("statuses"))
                    continue
                metadata = value.get("metadata", {})
                phone_number_id = metadata.get("phone_number_id", "")
                contacts = {c.get("wa_id", ""): c.get("profile", {}).get("name", "")
                            for c in value.get("contacts", [])}
                for msg in value.get("messages", []):
                    sender = msg.get("from", "")
                    normalized = {
                        "channel": "whatsapp",
                        "from": sender,
                        "from_name": contacts.get(sender, ""),
                        "message_id": msg.get("id", ""),
                        "text": msg.get("text", {}).get("body") if msg.get("type") == "text" else None,
                        "message_type": msg.get("type", "unknown"),
                        "timestamp": msg.get("timestamp", ""),
                        "business_account_id": business_account_id,
                        "phone_number_id": phone_number_id,
                    }
                    messages.append(normalized)
    except Exception as e:
        log("webhook_parse_error", source="meta_whatsapp", error=str(e))
    return messages


def send_text_message(to: str, text: str) -> bool:
    """Send a text message via WhatsApp Cloud API. Returns True on success."""
    url = f"https://graph.facebook.com/{_API_VERSION}/{_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    body = json.dumps({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_body = resp.read().decode()
            log("whatsapp_send_ok", to=to, response=resp_body)
            return True
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        log("whatsapp_send_failed", to=to, status=e.code, error=error_body)
        return False
    except Exception as e:
        log("whatsapp_send_failed", to=to, error=str(e))
        return False
```

### Step 3 — Create `agents/social/social_agent.py`

```python
# bluemarlin/agents/social/social_agent.py
# Created: Brief 068
# Last modified: Brief 068
# Purpose: Social agent stub — will be replaced with Claude-powered Q&A

from shared.bm_logger import log


def handle_incoming_whatsapp_message(message: dict) -> str:
    """
    Process a normalized WhatsApp message and return a reply string.
    Stub: returns hardcoded test reply. Will be replaced with Claude Q&A.
    """
    log("agent_stub_called", channel="whatsapp",
        message_from=message.get("from", ""),
        message_text=message.get("text", ""))
    return "Thanks for your message! BlueMarlin test agent is online. 🚀"
```

### Step 4 — Modify `agents/social/webhook_server.py`

Replace the entire file with:

```python
# bluemarlin/agents/social/webhook_server.py
# Created: Brief 067
# Last modified: Brief 068
# Purpose: FastAPI webhook receiver for Meta WhatsApp Cloud API

import os
from fastapi import BackgroundTasks, FastAPI, Request, Query
from fastapi.responses import PlainTextResponse

from shared.bm_logger import log
from shared import state_registry
from agents.social.whatsapp_client import parse_webhook_payload, send_text_message
from agents.social.social_agent import handle_incoming_whatsapp_message

app = FastAPI(title="BlueMarlin Social Webhook", docs_url=None, redoc_url=None)

_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")


@app.get("/webhooks/meta/whatsapp")
async def verify_webhook(
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
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive WhatsApp webhook events — return 200 immediately, process in background."""
    try:
        payload = await request.json()
    except Exception:
        payload = {"raw": (await request.body()).decode("utf-8", errors="replace")}
    log("webhook_received", source="meta_whatsapp", payload=payload)
    background_tasks.add_task(_process_whatsapp_event, payload)
    return PlainTextResponse(content="OK", status_code=200)


def _process_whatsapp_event(payload: dict):
    """Background task: parse messages, dedup, call agent, send reply."""
    try:
        messages = parse_webhook_payload(payload)
        for msg in messages:
            message_id = msg.get("message_id", "")
            # Dedup by message ID
            if not message_id or state_registry.wa_has_been_processed(message_id):
                if message_id:
                    log("webhook_duplicate_skipped", source="meta_whatsapp",
                        message_id=message_id)
                continue
            state_registry.wa_mark_as_processed(message_id)
            log("whatsapp_message_normalized", **msg)
            # Only process text messages
            if msg.get("text") is None:
                log("whatsapp_non_text_skipped", source="meta_whatsapp",
                    message_type=msg.get("message_type"), message_id=message_id)
                continue
            # Agent generates reply
            reply_text = handle_incoming_whatsapp_message(msg)
            if reply_text:
                send_text_message(to=msg["from"], text=reply_text)
    except Exception as e:
        log("webhook_process_error", source="meta_whatsapp", error=str(e))


@app.get("/health")
async def health():
    """Health check for monitoring."""
    return {"status": "ok"}
```

### Step 5 — Create `tests/social/test_068_pipeline.py`

```python
# bluemarlin/tests/social/test_068_pipeline.py
# Created: Brief 068
# Purpose: Tests for WhatsApp message pipeline

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ["WHATSAPP_VERIFY_TOKEN"] = "test_token_067"
os.environ["WHATSAPP_ACCESS_TOKEN"] = "test_access_token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "990622044139349"

from agents.social.whatsapp_client import parse_webhook_payload, send_text_message
from agents.social.social_agent import handle_incoming_whatsapp_message
from shared import state_registry


# --- Real payload from production (2026-03-11) ---
REAL_TEXT_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "967346842390828",
        "changes": [{
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {
                    "display_phone_number": "15551681192",
                    "phone_number_id": "990622044139349"
                },
                "contacts": [{"profile": {"name": "Calvin Adamus"}, "wa_id": "59996881585"}],
                "messages": [{
                    "from": "59996881585",
                    "id": "wamid.TEST_DEDUP_001",
                    "timestamp": "1773265596",
                    "text": {"body": "Test"},
                    "type": "text"
                }]
            },
            "field": "messages"
        }]
    }]
}

STATUS_UPDATE_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "967346842390828",
        "changes": [{
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {"display_phone_number": "15551681192", "phone_number_id": "990622044139349"},
                "statuses": [{"id": "wamid.xxx", "status": "delivered", "timestamp": "123", "recipient_id": "59996881585"}]
            },
            "field": "messages"
        }]
    }]
}

IMAGE_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "967346842390828",
        "changes": [{
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {"display_phone_number": "15551681192", "phone_number_id": "990622044139349"},
                "contacts": [{"profile": {"name": "Calvin Adamus"}, "wa_id": "59996881585"}],
                "messages": [{
                    "from": "59996881585",
                    "id": "wamid.IMAGE_001",
                    "timestamp": "1773265600",
                    "image": {"mime_type": "image/jpeg", "sha256": "abc", "id": "img123"},
                    "type": "image"
                }]
            },
            "field": "messages"
        }]
    }]
}


# --- Parse tests ---

def test_parse_text_message():
    """Parse real text message payload into normalized object."""
    msgs = parse_webhook_payload(REAL_TEXT_PAYLOAD)
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg["channel"] == "whatsapp"
    assert msg["from"] == "59996881585"
    assert msg["from_name"] == "Calvin Adamus"
    assert msg["message_id"] == "wamid.TEST_DEDUP_001"
    assert msg["text"] == "Test"
    assert msg["message_type"] == "text"
    assert msg["timestamp"] == "1773265596"
    assert msg["business_account_id"] == "967346842390828"
    assert msg["phone_number_id"] == "990622044139349"


def test_parse_status_update_returns_empty():
    """Status updates (delivered, read) should not produce messages."""
    msgs = parse_webhook_payload(STATUS_UPDATE_PAYLOAD)
    assert msgs == []


def test_parse_image_message():
    """Non-text message parsed with text=None."""
    msgs = parse_webhook_payload(IMAGE_PAYLOAD)
    assert len(msgs) == 1
    assert msgs[0]["text"] is None
    assert msgs[0]["message_type"] == "image"
    assert msgs[0]["from"] == "59996881585"


def test_parse_empty_payload():
    """Empty or malformed payload returns empty list."""
    assert parse_webhook_payload({}) == []
    assert parse_webhook_payload({"entry": []}) == []
    assert parse_webhook_payload({"entry": [{"changes": []}]}) == []


# --- Dedup tests ---

def test_dedup_prevents_reprocessing():
    """Same message ID should be skipped on second processing."""
    test_id = "wamid.DEDUP_TEST_068"
    # Clean up if exists from previous test run
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_processed WHERE message_id = ?", (test_id,))
    conn.commit()
    conn.close()

    assert state_registry.wa_has_been_processed(test_id) is False
    state_registry.wa_mark_as_processed(test_id)
    assert state_registry.wa_has_been_processed(test_id) is True


# --- Agent stub tests ---

def test_agent_stub_returns_reply():
    """Stub agent returns hardcoded test reply."""
    msg = {"from": "59996881585", "text": "Hello", "channel": "whatsapp"}
    reply = handle_incoming_whatsapp_message(msg)
    assert "BlueMarlin" in reply
    assert "test agent" in reply.lower() or "online" in reply.lower()


# --- Send tests ---

@patch("agents.social.whatsapp_client.urllib.request.urlopen")
def test_send_text_message_success(mock_urlopen):
    """send_text_message calls correct URL with correct body."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"messaging_product":"whatsapp","messages":[{"id":"wamid.ok"}]}'
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    result = send_text_message("59996881585", "Hello from test")
    assert result is True

    # Verify the request
    call_args = mock_urlopen.call_args
    req = call_args[0][0]
    assert "990622044139349" in req.full_url
    assert req.get_header("Authorization") == "Bearer test_access_token"
    body = json.loads(req.data)
    assert body["messaging_product"] == "whatsapp"
    assert body["to"] == "59996881585"
    assert body["text"]["body"] == "Hello from test"


@patch("agents.social.whatsapp_client.urllib.request.urlopen")
def test_send_text_message_failure(mock_urlopen):
    """send_text_message returns False on API error."""
    mock_urlopen.side_effect = Exception("Connection refused")
    result = send_text_message("59996881585", "Hello")
    assert result is False


# --- Integration test (mocked send) ---

def test_webhook_post_triggers_pipeline():
    """POST with text message triggers parse → agent → send (mocked)."""
    from fastapi.testclient import TestClient
    from agents.social.webhook_server import app

    client = TestClient(app)

    # Use a unique message ID to avoid dedup from other tests
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "967346842390828",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "15551681192", "phone_number_id": "990622044139349"},
                    "contacts": [{"profile": {"name": "Test User"}, "wa_id": "1234567890"}],
                    "messages": [{
                        "from": "1234567890",
                        "id": "wamid.INTEGRATION_TEST_068",
                        "timestamp": "1773265700",
                        "text": {"body": "Integration test"},
                        "type": "text"
                    }]
                },
                "field": "messages"
            }]
        }]
    }

    # Clean up dedup for this test
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_processed WHERE message_id = ?", ("wamid.INTEGRATION_TEST_068",))
    conn.commit()
    conn.close()

    with patch("agents.social.webhook_server.send_text_message") as mock_send:
        mock_send.return_value = True
        r = client.post("/webhooks/meta/whatsapp", json=payload)
        assert r.status_code == 200
        assert r.text == "OK"
        # BackgroundTasks run synchronously in TestClient
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args[1]["to"] == "1234567890" or call_args[0][0] == "1234567890"


# --- Existing Brief 067 tests still pass ---

def test_health_endpoint():
    """GET /health still returns ok."""
    from fastapi.testclient import TestClient
    from agents.social.webhook_server import app
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

### Step 6 — Deploy and verify end-to-end

1. Run local tests: `python3 -m pytest tests/social/test_068_pipeline.py -v`
2. Also run Brief 067 tests to confirm no regression: `python3 -m pytest tests/social/test_067_webhook.py -v`
3. Git commit and push
4. Deploy to VPS: `cd /root/bluemarlin && git pull && systemctl restart bluemarlin-social`
5. Live verification — send a curl that simulates a WhatsApp text message to the live endpoint:
   ```bash
   curl -s -X POST https://api.wetakeyourjob.com/webhooks/meta/whatsapp \
     -H "Content-Type: application/json" \
     -d '{"object":"whatsapp_business_account","entry":[{"id":"967346842390828","changes":[{"value":{"messaging_product":"whatsapp","metadata":{"display_phone_number":"15551681192","phone_number_id":"990622044139349"},"contacts":[{"profile":{"name":"Curl Test"},"wa_id":"59996881585"}],"messages":[{"from":"59996881585","id":"wamid.CURL_LIVE_TEST","timestamp":"1773270000","text":{"body":"Live test from curl"},"type":"text"}]},"field":"messages"}]}]}'
   ```
6. Check VPS logs: `tail -10 /root/bluemarlin/logs/bluemarlin.log` — should show `webhook_received`, `whatsapp_message_normalized`, `agent_stub_called`, and either `whatsapp_send_ok` or `whatsapp_send_failed`
7. If send succeeded, ask user to check if Calvin received the reply on WhatsApp

## Tests

File: `tests/social/test_068_pipeline.py` (10 tests)

1. `test_parse_text_message` — real payload → normalized object with `from == "59996881585"`, `from_name == "Calvin Adamus"`, `text == "Test"`, `channel == "whatsapp"`
2. `test_parse_status_update_returns_empty` — status update payload → empty list
3. `test_parse_image_message` — image payload → `text is None`, `message_type == "image"`
4. `test_parse_empty_payload` — empty/malformed payloads → empty list
5. `test_dedup_prevents_reprocessing` — same message_id processed twice → second `wa_has_been_processed` returns True
6. `test_agent_stub_returns_reply` — stub returns string containing "BlueMarlin"
7. `test_send_text_message_success` — mocked urlopen → returns True, request body has correct `to` and `text`
8. `test_send_text_message_failure` — mocked exception → returns False
9. `test_webhook_post_triggers_pipeline` — full POST → parse → agent → mocked send called with correct phone number
10. `test_health_endpoint` — GET /health still returns `{"status": "ok"}`

## Success Condition

Local tests pass (10/10 + 7/7 regression), VPS logs show the full pipeline (receive → normalize → agent → send), and an outbound reply is successfully sent to a WhatsApp number via the permanent token.

## Rollback

1. Restore `webhook_server.py` to Brief 067 version: `git checkout HEAD~1 -- agents/social/webhook_server.py`
2. Remove new files: `git rm agents/social/whatsapp_client.py agents/social/social_agent.py tests/social/test_068_pipeline.py`
3. Revert state_registry.py: `git checkout HEAD~1 -- shared/state_registry.py`
4. Redeploy: `git push && ssh root@108.61.192.52 "cd /root/bluemarlin && git pull && systemctl restart bluemarlin-social"`
5. The `whatsapp_processed` table in SQLite is harmless — leave it.
