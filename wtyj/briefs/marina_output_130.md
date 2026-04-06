# OUTPUT 130 — Zernio DM Webhook + Storage Layer

## What was done

### Step 1: `shared/state_registry.py`
- Added schema migration in `_get_conn()`: `ALTER TABLE whatsapp_threads ADD COLUMN channel TEXT DEFAULT 'whatsapp'` and `ADD COLUMN sender_name TEXT DEFAULT ''` (with try/except for idempotency)
- Added new index: `idx_whatsapp_threads_channel` on `(channel, phone, created_at)`
- Added `dm_store_message()` — stores DM messages with conversation_id, channel, role, text, sender_name
- Added `dm_get_history()` — retrieves DM history filtered by conversation_id + channel (last 24h, oldest first)
- Existing `wa_*` functions unchanged and verified working

### Step 2: `agents/social/zernio_dm_client.py` (new)
- `verify_webhook_signature()` — HMAC-SHA256 verification of `X-Zernio-Signature` header
- `parse_zernio_webhook()` — normalizes Zernio webhook payload to `{conversation_id, platform, channel, sender_name, sender_id, text, message_id, account_id}`. Returns None for non-message events or missing IDs. Handles multiple payload structures (data.text, data.message.text).
- `send_dm_reply()` — sends DM via Zernio Inbox API (used by Brief 131)
- `send_typing_indicator()` — best-effort typing indicator (used by Brief 131)
- Uses same `_get_client()` pattern as social_publisher.py

### Step 3: `agents/social/webhook_server.py`
- Added `import json as _json` and import of `parse_zernio_webhook`, `verify_webhook_signature`
- New `POST /webhooks/zernio` endpoint: reads body once for HMAC verification, parses JSON from bytes (avoids double stream consumption), returns 200 immediately
- New `_process_zernio_event()` background handler: parses webhook, dedup via `wa_has_been_processed`, skips non-text messages, stores via `dm_store_message()`
- Placeholder comment for Brief 131 (dm_agent + reply)

## Test results

- **Brief 130 tests: 12/12 passed**
- **Full social regression: 288/288 passed, 0 failed**

## Unexpected

- `bm_logger.log()` uses `event` as its first positional parameter. Passing `event=` as a kwarg caused `TypeError: log() got multiple values for argument 'event'`. Fixed by renaming to `webhook_event=` in both `zernio_dm_client.py` and `webhook_server.py`. Output reviewer caught the second instance.

## Known interim side-effect

`wa_list_conversations()` doesn't filter by channel. Any DM conversations stored will appear in the dashboard Messages page alongside WhatsApp conversations. This is intentional — Brief 132 adds channel filtering.

## VPS env var needed

`ZERNIO_WEBHOOK_SECRET` must be added to `/root/bluemarlin/config/bluemarlin.env` before deploying. Webhook registration via SDK is a manual step during Brief 131 or deployment.
