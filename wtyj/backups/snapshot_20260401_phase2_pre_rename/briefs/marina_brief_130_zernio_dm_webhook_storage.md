# BRIEF 130 — Zernio DM Webhook + Storage Layer
**Status:** Draft | **Files:** `shared/state_registry.py`, `agents/social/webhook_server.py`, `agents/social/zernio_dm_client.py` (new) | **Depends on:** Late SDK v1.3.35, Zernio Build + DMs plan active | **Blocks:** Brief 131 (DM Agent), Brief 132 (Dashboard multi-channel)

## Context

Zernio account upgraded to Build + Comments & DMs ($29/mo). Inbox, webhooks, and comments APIs are all verified working. Instagram (@bluemarlincharters) and Facebook (BlueMarlin Tours Curacao) accounts connected. Currently only WhatsApp messages are received and stored. There is no way to receive IG/FB DMs.

This brief adds the plumbing: receive Zernio webhook events, verify HMAC signature, dedup, and store DM messages in the existing `whatsapp_threads` table with a new `channel` column. No agent processing or replies yet — that's Brief 131.

## Why This Approach

**Considered:** New table for DM conversations. Rejected — `whatsapp_threads` already has the right schema (contact identifier, role, text, timestamp). Adding a `channel` column and reusing the table avoids duplicating 6+ functions and all dashboard queries.

**Considered:** Reusing `whatsapp_processed` table for Zernio dedup. Accepted — Zernio message IDs (e.g. `msg_xxx`) won't collide with WhatsApp message IDs (e.g. `wamid.xxx`). Same table, no conflict.

**Considered:** Storing `account_id` in threads table. Deferred — account_id can be derived at reply time by platform (same as WhatsApp derives phone_number_id from env vars). Keeps the schema simple.

**Tradeoff:** The webhook payload structure is based on Zernio documentation. If the real payload differs, `parse_zernio_webhook` will need adjustment. Parser logs raw payload to catch this.

## Source Material

### Zernio SDK inbox methods (verified on VPS):
```python
client.inbox.list_inbox_conversations()
client.inbox.send_inbox_message(conversation_id, account_id, message)
client.messages.send_typing_indicator(conversation_id, account_id)
```

### Zernio SDK webhook methods:
```python
client.webhooks.create_webhook_settings(name, url, secret, events, is_active)
client.webhooks.get_webhook_settings()
```

### Webhook signature: HMAC-SHA256 via `X-Zernio-Signature` header, signed with shared secret.

### Expected webhook payload (message.received):
```json
{
  "event": "message.received",
  "timestamp": "2026-04-01T15:30:00Z",
  "data": {
    "id": "msg_abc123",
    "text": "How much is the sunset cruise?",
    "conversationId": "conv_456",
    "platform": "instagram",
    "sender": {
      "id": "user_789",
      "name": "John Smith"
    },
    "accountId": "69b8689d6cb7b8cf4c7846ff"
  }
}
```
Note: exact field names may vary — parser handles both `data.text` and `data.message.text` patterns, logs raw payload for debugging.

### Connected accounts (from `client.accounts.list()` on VPS, verified 2026-04-01):
- Profile ID: `69b868672cde65a782026248`
- Instagram: `69b8689d6cb7b8cf4c7846ff`
- Facebook: `69bb24a66cb7b8cf4c8074aa`

### Env var: `ZERNIO_WEBHOOK_SECRET` — to be generated and added to VPS.

## Instructions

### Step 1: Modify `shared/state_registry.py`

**1a.** In `_get_conn()`, after the existing `whatsapp_threads` CREATE TABLE and index, add schema migration:

```python
# Schema migration: add channel + sender_name columns to whatsapp_threads
try:
    conn.execute("ALTER TABLE whatsapp_threads ADD COLUMN channel TEXT DEFAULT 'whatsapp'")
except sqlite3.OperationalError:
    pass  # Column already exists
try:
    conn.execute("ALTER TABLE whatsapp_threads ADD COLUMN sender_name TEXT DEFAULT ''")
except sqlite3.OperationalError:
    pass  # Column already exists
conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_whatsapp_threads_channel "
    "ON whatsapp_threads(channel, phone, created_at)"
)
```

**1b.** Add new DM storage functions (after `wa_cleanup_stale_data`):

```python
def dm_store_message(conversation_id: str, channel: str, role: str, text: str,
                     sender_name: str = ""):
    """Store a DM message (IG/FB) in conversation history."""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO whatsapp_threads (phone, role, text, created_at, channel, sender_name) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (conversation_id, role, text, datetime.now(timezone.utc).isoformat(),
         channel, sender_name)
    )
    conn.commit()
    conn.close()


def dm_get_history(conversation_id: str, channel: str, limit: int = 10) -> list:
    """Get recent DM conversation history (last 24h, oldest first)."""
    conn = _get_conn()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    rows = conn.execute(
        "SELECT role, text, created_at FROM whatsapp_threads "
        "WHERE phone = ? AND channel = ? AND created_at > ? "
        "ORDER BY created_at DESC LIMIT ?",
        (conversation_id, channel, cutoff, limit)
    ).fetchall()
    conn.close()
    return [{"role": r[0], "text": r[1], "created_at": r[2]} for r in reversed(rows)]
```

**1c.** Existing `wa_store_message`, `wa_get_history`, `wa_get_full_history`, `wa_cleanup_stale_data` — **no changes**. They operate on the same table and work correctly because the default channel is `'whatsapp'` and they don't filter by channel. The cleanup function cleans all channels (acceptable — DMs get same 30d retention).

**Known interim side-effect:** `wa_list_conversations()` queries all rows from `whatsapp_threads` without a channel filter. After this brief, any stored DM conversations will appear in the dashboard Messages page alongside WhatsApp conversations (with conversation_ids shown as phone numbers). This is acceptable for now — Brief 132 will add channel filtering and proper display. Until then, DM conversations are visible but harmless in the list.

### Step 2: Create `agents/social/zernio_dm_client.py`

New file:

```python
# bluemarlin/agents/social/zernio_dm_client.py
# Created: Brief 130
# Purpose: Parse Zernio webhook payloads + send DM replies via Zernio Inbox API

import hashlib
import hmac
import os

from late import Late
from shared import bm_logger


def _get_client():
    """Create a Late/Zernio API client. Returns None if no API key."""
    api_key = os.environ.get("LATE_API_KEY", "")
    if not api_key:
        bm_logger.log("zernio_dm_no_api_key")
        return None
    return Late(api_key=api_key)


def verify_webhook_signature(payload_bytes: bytes, signature: str) -> bool:
    """Verify Zernio webhook HMAC-SHA256 signature. Returns True if valid."""
    secret = os.environ.get("ZERNIO_WEBHOOK_SECRET", "")
    if not secret:
        bm_logger.log("zernio_webhook_no_secret")
        return False
    expected = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_zernio_webhook(payload: dict) -> dict | None:
    """Parse a Zernio webhook payload into a normalized message dict.
    Returns None if not a message.received event or if parsing fails.

    Returns: {conversation_id, platform, sender_name, sender_id, text,
              message_id, account_id}
    """
    event = payload.get("event", "")
    if event != "message.received":
        bm_logger.log("zernio_webhook_non_message", event=event)
        return None

    # Try nested structures — Zernio may use data.message or data directly
    data = payload.get("data", {})
    if not data:
        data = payload.get("message", {})

    text = data.get("text", "")
    if not text:
        # Try nested message object
        msg_obj = data.get("message", {})
        text = msg_obj.get("text", "") if isinstance(msg_obj, dict) else ""

    conversation_id = data.get("conversationId", "") or data.get("conversation_id", "")
    message_id = data.get("id", "") or data.get("messageId", "")
    account_id = data.get("accountId", "") or data.get("account_id", "")

    sender = data.get("sender", {})
    if isinstance(sender, dict):
        sender_name = sender.get("name", "")
        sender_id = sender.get("id", "")
    else:
        sender_name = ""
        sender_id = ""

    platform = data.get("platform", "")

    if not conversation_id or not message_id:
        bm_logger.log("zernio_webhook_missing_ids", payload_keys=list(payload.keys()),
                       data_keys=list(data.keys()) if isinstance(data, dict) else [])
        return None

    channel = f"{platform}_dm" if platform else "unknown_dm"

    return {
        "conversation_id": conversation_id,
        "platform": platform,
        "channel": channel,
        "sender_name": sender_name,
        "sender_id": sender_id,
        "text": text,
        "message_id": message_id,
        "account_id": account_id,
    }


def send_dm_reply(conversation_id: str, account_id: str, text: str) -> bool:
    """Send a DM reply via Zernio Inbox API. Returns True on success."""
    client = _get_client()
    if not client:
        return False
    try:
        client.inbox.send_inbox_message(
            conversation_id=conversation_id,
            account_id=account_id,
            message=text,
        )
        bm_logger.log("zernio_dm_sent", conversation_id=conversation_id[:20])
        return True
    except Exception as e:
        bm_logger.log("zernio_dm_send_failed", conversation_id=conversation_id[:20],
                       error=str(e)[:200])
        return False


def send_typing_indicator(conversation_id: str, account_id: str):
    """Send typing indicator via Zernio. Best-effort, no error on failure."""
    client = _get_client()
    if not client:
        return
    try:
        client.messages.send_typing_indicator(
            conversation_id=conversation_id,
            account_id=account_id,
        )
    except Exception:
        pass  # Typing indicator is cosmetic — never block on failure
```

### Step 3: Modify `agents/social/webhook_server.py`

**3a.** Add imports at the top (after existing imports):

```python
import json as _json
from agents.social.zernio_dm_client import parse_zernio_webhook, verify_webhook_signature
```

**3b.** Add Zernio webhook endpoint + background processor before the `/health` endpoint.

Note: `request.body()` must be called before `request.json()` — FastAPI consumes the stream. Read body once, parse JSON from bytes.

```python
@app.post("/webhooks/zernio")
async def receive_zernio_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive Zernio webhook events (DMs from IG/FB). Return 200 immediately."""
    body = await request.body()
    signature = request.headers.get("X-Zernio-Signature", "")

    if not verify_webhook_signature(body, signature):
        log("zernio_webhook_signature_invalid")
        return PlainTextResponse(content="Forbidden", status_code=403)

    try:
        payload = _json.loads(body)
    except Exception:
        payload = {"raw": body.decode("utf-8", errors="replace")}
    log("webhook_received", source="zernio", event=payload.get("event", "unknown"))
    background_tasks.add_task(_process_zernio_event, payload)
    return PlainTextResponse(content="OK", status_code=200)


def _process_zernio_event(payload: dict):
    """Background task: parse Zernio webhook, dedup, store DM message."""
    try:
        msg = parse_zernio_webhook(payload)
        if not msg:
            return  # Not a message event or unparseable

        message_id = msg["message_id"]
        # Reuse whatsapp_processed table for dedup
        if state_registry.wa_has_been_processed(message_id):
            log("webhook_duplicate_skipped", source="zernio", message_id=message_id)
            return
        state_registry.wa_mark_as_processed(message_id)

        text = msg.get("text", "")
        if not text:
            log("zernio_dm_non_text_skipped", message_id=message_id,
                platform=msg.get("platform"))
            return

        log("zernio_dm_received",
            conversation_id=msg["conversation_id"][:20],
            platform=msg["platform"],
            sender=msg["sender_name"][:30])

        # Store the incoming message
        state_registry.dm_store_message(
            conversation_id=msg["conversation_id"],
            channel=msg["channel"],
            role="user",
            text=text,
            sender_name=msg["sender_name"],
        )
        # Brief 131 will add: dm_agent.handle_incoming_dm(msg) + send reply
    except Exception as e:
        log("webhook_process_error", source="zernio", error=str(e))
```

### Step 4: Add env var to VPS (manual step during execution)

Generate a random webhook secret and add to `/root/bluemarlin/config/bluemarlin.env`:
```
ZERNIO_WEBHOOK_SECRET=<generated-32-char-hex>
```

Also add `ZERNIO_WEBHOOK_SECRET=test-secret` to test env defaults.

## Tests

File: `tests/social/test_130_zernio_dm_webhook.py`

1. **test_verify_signature_valid** — verify_webhook_signature returns True with correct HMAC
2. **test_verify_signature_invalid** — returns False with wrong signature
3. **test_verify_signature_missing_secret** — returns False when env var missing
4. **test_parse_webhook_message_received** — parse_zernio_webhook returns correct dict for IG message
5. **test_parse_webhook_facebook_message** — same for FB platform
6. **test_parse_webhook_non_message_event** — returns None for post.published etc
7. **test_parse_webhook_missing_ids** — returns None when conversationId missing
8. **test_parse_webhook_no_text** — parser returns dict with `text=""` (parser doesn't reject empty text — the empty-text skip happens in `_process_zernio_event`)
9. **test_dm_store_and_get_history** — dm_store_message stores with correct channel, dm_get_history retrieves only that channel
10. **test_dm_history_does_not_leak_whatsapp** — store WA message + DM message on same "phone", dm_get_history only returns DM
11. **test_existing_wa_functions_still_work** — wa_store_message + wa_get_history still work after schema migration
12. **test_dedup_zernio_message** — same message_id processed twice, second time skipped

## Success Condition

Zernio webhook payload is received at `/webhooks/zernio`, HMAC-verified, deduped, and stored in `whatsapp_threads` with `channel='instagram_dm'` or `channel='facebook_dm'`. Existing WhatsApp storage and booking functions unchanged. Dashboard will show DM conversations in the WhatsApp list as an accepted interim side-effect (fixed in Brief 132). All 12 tests pass.

## Rollback

Remove the new functions from state_registry.py, remove the Zernio endpoint from webhook_server.py, delete zernio_dm_client.py. The `channel` and `sender_name` columns are harmless if left in the table (default values preserve existing behavior).
