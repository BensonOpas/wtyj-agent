# BRIEF 143 — Zernio WhatsApp: Route WhatsApp Through Zernio
**Status:** Draft | **Files:** `agents/social/webhook_server.py`, `agents/social/zernio_dm_client.py` | **Depends on:** Brief 142 | **Blocks:** None

## Context

WhatsApp is now connected to Zernio (Calvin's number +599 9 688 1585). Currently WhatsApp messages come through Meta Cloud API (own webhook, own send function). IG/FB DMs come through Zernio. Having two separate pipelines for messaging is unnecessary complexity.

Switch WhatsApp to Zernio: one API for all channels. Simpler onboarding for new clients (just connect WhatsApp in Zernio dashboard, no Meta Business setup). The Meta WhatsApp webhook stays in the code but becomes inactive — we'll disable the Meta webhook in the Meta dashboard, not delete our code.

## Why This Approach

The Zernio webhook already handles IG/FB DMs. WhatsApp through Zernio comes through the same webhook with `platform="whatsapp"`. The only changes needed:

1. **Channel naming** — `parse_zernio_webhook` currently sets `channel = f"{platform}_dm"` which would give `"whatsapp_dm"`. For WhatsApp, the channel should just be `"whatsapp"` to match the existing convention and Marina's channel-aware behavior.

2. **Debouncing for WhatsApp** — WhatsApp users send rapid-fire messages. The Meta flow debounces them (buffers 2-5 seconds, batches into one). The Zernio flow processes immediately. Without debouncing, 3 quick messages = 3 Claude API calls. Need to add debouncing for WhatsApp messages coming through Zernio.

3. **No code removal** — The Meta WhatsApp endpoint and `whatsapp_client.py` stay. We just stop receiving webhooks from Meta by disabling the webhook in Meta's dashboard. If Zernio has issues, we can re-enable Meta in minutes.

## Source Material

### parse_zernio_webhook channel logic (zernio_dm_client.py line 80):
```python
channel = f"{platform}_dm" if platform else "unknown_dm"
```

### Existing debounce system (webhook_server.py lines 47-174):
`_buffer_message(msg)` adds to per-phone buffer, `_flush_buffer(phone)` processes after delay. Uses `_DEBOUNCE_SECONDS = 2.0` and `_MAX_BATCH_SECONDS = 5.0`.

### _flush_buffer sends via Meta API (webhook_server.py line 170):
```python
send_text_message(to=phone, text=reply_text)
```
This needs to be Zernio's `send_dm_reply` instead for WhatsApp-via-Zernio messages.

### Current _process_zernio_event (webhook_server.py lines 196-275):
Processes each message immediately — no debouncing. Routes to orchestrator or DM agent based on booking_flow toggle.

## Instructions

### Step 1: Fix channel naming for WhatsApp (zernio_dm_client.py)

Change line 80 from:
```python
    channel = f"{platform}_dm" if platform else "unknown_dm"
```
to:
```python
    channel = "whatsapp" if platform == "whatsapp" else (f"{platform}_dm" if platform else "unknown_dm")
```

This gives WhatsApp messages `channel="whatsapp"` (matching the existing convention) while IG/FB keep their `_dm` suffix.

### Step 2: Add WhatsApp debouncing to _process_zernio_event (webhook_server.py)

In `_process_zernio_event`, after the dedup and text checks pass (after line 223 where `account_id` is set), add a WhatsApp-specific branch that routes through the debounce buffer instead of processing immediately.

After line 223 (`account_id = msg["account_id"]`), add:

```python
        # WhatsApp via Zernio: debounce like Meta WhatsApp
        if msg["platform"] == "whatsapp":
            # Store Zernio metadata for reply routing
            _wa_msg = {
                "from": conversation_id,
                "text": text,
                "from_name": msg.get("sender_name", ""),
                "message_id": msg["message_id"],
                "_zernio_conversation_id": conversation_id,
                "_zernio_account_id": account_id,
                "_zernio_channel": channel,
                "_zernio_sender_name": msg.get("sender_name", ""),
            }
            send_typing_indicator(conversation_id, account_id)
            _buffer_message(_wa_msg)
            return
```

This reuses the existing `_buffer_message` → `_flush_buffer` pipeline. The `_zernio_*` fields are metadata needed for the reply step.

### Step 3: Update _flush_buffer to handle Zernio WhatsApp replies (webhook_server.py)

In `_flush_buffer` (line 148), after the orchestrator call and message storage, the reply is sent via `send_text_message(to=phone, text=reply_text)` (line 170). This is the Meta API. For Zernio WhatsApp messages, we need to send via `send_dm_reply` instead.

Change lines 165-174 from:
```python
    try:
        reply_text = handle_incoming_whatsapp_message(final_msg)
        # Always store user message — even if reply is empty, context must be preserved
        state_registry.wa_store_message(phone, "user", combined_text)
        if reply_text:
            send_text_message(to=phone, text=reply_text)
            state_registry.wa_store_message(phone, "assistant", reply_text)
    except Exception as e:
        log("webhook_process_error", source="meta_whatsapp", error=str(e),
            phone=phone)
```

To:
```python
    try:
        # Check if this came from Zernio (has _zernio metadata)
        _zernio_conv = final_msg.get("_zernio_conversation_id")
        _zernio_acct = final_msg.get("_zernio_account_id")
        _zernio_channel = final_msg.get("_zernio_channel", "whatsapp")
        _zernio_sender = final_msg.get("_zernio_sender_name", "")
        if _zernio_conv:
            # Zernio WhatsApp — check booking_flow toggle
            _booking_flow_on = config_loader.get_raw().get("features", {}).get("booking_flow", True)
            if _booking_flow_on:
                reply_text = handle_incoming_whatsapp_message(final_msg)
                # Store user message after orchestrator (same ordering as DM path)
                state_registry.dm_store_message(
                    conversation_id=_zernio_conv,
                    channel=_zernio_channel,
                    role="user",
                    text=combined_text,
                    sender_name=_zernio_sender,
                )
            else:
                # Q&A only — use DM agent
                _dm_msg = {
                    "conversation_id": _zernio_conv,
                    "platform": "whatsapp",
                    "channel": _zernio_channel,
                    "sender_name": _zernio_sender,
                    "text": combined_text,
                    "account_id": _zernio_acct,
                    "message_id": final_msg.get("message_id", ""),
                }
                # Store user message before DM agent (same as DM path)
                state_registry.dm_store_message(
                    conversation_id=_zernio_conv,
                    channel=_zernio_channel,
                    role="user",
                    text=combined_text,
                    sender_name=_zernio_sender,
                )
                reply_text = handle_incoming_dm(_dm_msg)
            if reply_text:
                send_dm_reply(_zernio_conv, _zernio_acct, reply_text)
                state_registry.dm_store_message(
                    conversation_id=_zernio_conv,
                    channel=_zernio_channel,
                    role="assistant",
                    text=reply_text,
                )
        else:
            # Meta WhatsApp (legacy) — original path
            reply_text = handle_incoming_whatsapp_message(final_msg)
            state_registry.wa_store_message(phone, "user", combined_text)
            if reply_text:
                send_text_message(to=phone, text=reply_text)
                state_registry.wa_store_message(phone, "assistant", reply_text)
    except Exception as e:
        log("webhook_process_error",
            source="zernio_whatsapp" if final_msg.get("_zernio_conversation_id") else "meta_whatsapp",
            error=str(e), phone=phone)
```

### Step 4: No Meta code removal

Keep the Meta WhatsApp webhook endpoint (`/webhooks/meta/whatsapp`) and `whatsapp_client.py` intact. They become inactive once the Meta webhook is disabled in Meta's dashboard. This is a manual step done AFTER verifying Zernio WhatsApp works.

## Tests

File: `tests/social/test_143_zernio_whatsapp.py`

1. **test_zernio_whatsapp_channel_is_whatsapp** — Parse a Zernio webhook with `platform="whatsapp"`. Verify: `channel` is `"whatsapp"`, not `"whatsapp_dm"`.

2. **test_zernio_instagram_channel_unchanged** — Parse a Zernio webhook with `platform="instagram"`. Verify: `channel` is `"instagram_dm"` (regression — unchanged).

3. **test_zernio_whatsapp_uses_debounce** — Mock `_buffer_message`. Send a Zernio WhatsApp payload through `_process_zernio_event`. Verify: `_buffer_message` was called (not the orchestrator directly).

4. **test_zernio_whatsapp_reply_via_zernio** — Set up a buffered Zernio WhatsApp message with `_zernio_conversation_id` metadata. Mock orchestrator + `send_dm_reply`. Flush the buffer. Verify: reply sent via `send_dm_reply` (Zernio), NOT `send_text_message` (Meta).

5. **test_zernio_whatsapp_debounce_batches** — Send two messages with the same conversation_id quickly. Verify: only one orchestrator call with combined text.

6. **test_zernio_whatsapp_booking_flow_off_uses_dm_agent** — Set `booking_flow=false`. Send a Zernio WhatsApp message through the debounce + flush path. Mock `handle_incoming_dm` and `handle_incoming_whatsapp_message`. Verify: DM agent called, orchestrator NOT called.

## Success Condition

WhatsApp messages arriving through Zernio's webhook are debounced, processed through the orchestrator (or DM agent when booking_flow=false), and replied to via Zernio's API. The channel is stored as `"whatsapp"`. IG/FB DMs are unchanged. Meta WhatsApp code stays but becomes inactive. All 6 tests pass.

## Rollback

Revert `webhook_server.py` and `zernio_dm_client.py`. Re-enable Meta webhook in Meta dashboard.
