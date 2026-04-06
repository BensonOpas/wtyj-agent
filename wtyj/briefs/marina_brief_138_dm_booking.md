# BRIEF 138 — DM Booking: Route DMs Through Booking Orchestrator
**Status:** Draft | **Files:** `agents/social/webhook_server.py` | **Depends on:** Brief 137 (booking flow guard) | **Blocks:** None

## Context

Instagram and Facebook DMs currently use a separate Q&A agent (`dm_agent.py`) that redirects booking requests to WhatsApp or email. This was built in Brief 131b after Brief 131 proved Marina's booking prompt overrides "don't book" instructions when called directly.

But the real fix was never "don't let DMs book." The fix is to route DMs through the booking orchestrator (`social_agent.py`), which handles `[BOOKING_REF]` and `[PAYMENT_LINK]` replacement properly. The orchestrator is already channel-agnostic — it takes a message dict, calls Marina, runs the booking state machine, and returns a reply string. It never sends anything itself.

SR explicitly requested this: "don't cut the customer flow, let people book everywhere."

## Why This Approach

The change is entirely in `webhook_server.py`'s `_process_zernio_event`. When `booking_flow` is ON, route DMs through `handle_incoming_whatsapp_message` instead of `handle_incoming_dm`. When OFF, keep using the Q&A agent.

Why this works:
- The orchestrator uses `phone` as a generic string key. A Zernio conversation_id (`69b8689d...`) works the same as a phone number.
- `wa_get_booking_state`, `wa_save_booking_state`, `wa_store_message`, `wa_get_history` all use `phone` as a plain string — no phone format validation.
- The orchestrator never sends replies — it returns the reply text. The caller handles delivery. So DMs still send via `send_dm_reply`.
- Marina's `channel="whatsapp"` writing style (short, casual) is correct for DMs.
- The booking_flow toggle already guards WhatsApp (Brief 135) and email (Brief 137). This adds DMs as a third channel under the same toggle.

Why NOT change marina_agent.py or social_agent.py:
- Marina doesn't need to know it's a DM. The WhatsApp writing style works for DMs.
- The orchestrator doesn't need to know the channel. It takes a message, returns a reply.
- The only channel-specific logic is send/receive, which stays in webhook_server.py.

`dm_agent.py` stays as-is — it's the fallback for `booking_flow=false` clients (Q&A + redirect).

## Source Material

### Current `_process_zernio_event` (webhook_server.py lines 195-245):
```python
def _process_zernio_event(payload: dict):
    try:
        msg = parse_zernio_webhook(payload)
        if not msg:
            return
        message_id = msg["message_id"]
        if state_registry.wa_has_been_processed(message_id):
            return
        state_registry.wa_mark_as_processed(message_id)
        text = msg.get("text", "")
        if not text:
            return
        state_registry.dm_store_message(
            conversation_id=msg["conversation_id"],
            channel=msg["channel"],
            role="user", text=text,
            sender_name=msg["sender_name"],
        )
        send_typing_indicator(msg["conversation_id"], msg["account_id"])
        reply_text = handle_incoming_dm(msg)  # <-- Q&A agent
        if reply_text:
            send_dm_reply(msg["conversation_id"], msg["account_id"], reply_text)
            state_registry.dm_store_message(
                conversation_id=msg["conversation_id"],
                channel=msg["channel"],
                role="assistant", text=reply_text,
            )
    except Exception as e:
        log("webhook_process_error", source="zernio", error=str(e))
```

### `handle_incoming_whatsapp_message` expects (social_agent.py line 213):
```python
def handle_incoming_whatsapp_message(message: dict) -> str:
    phone = message.get("from", "")
    text = message.get("text", "")
    from_name = message.get("from_name", "")
```

### `dm_store_message` vs `wa_store_message` (state_registry.py):
- `wa_store_message(phone, role, text)` — stores with default `channel='whatsapp'`
- `dm_store_message(conversation_id, channel, role, text, sender_name)` — stores with explicit channel

Both write to the same `whatsapp_threads` table. The orchestrator internally calls `wa_store_message` for system notes (6 places). These will store with `channel='whatsapp'` even for DM conversations. This is a data inconsistency for system notes only — user/assistant messages are stored correctly by `_process_zernio_event` before and after the orchestrator call.

### config_loader import:
`webhook_server.py` does NOT currently import `config_loader`. Need to add it for the `booking_flow` check.

## Instructions

### Step 1: Add config_loader import to webhook_server.py

Add to imports (after line 14):
```python
from shared import config_loader
```

### Step 2: Rewrite `_process_zernio_event` with booking_flow routing

Replace the entire `_process_zernio_event` function (lines 195-245) with:

```python
def _process_zernio_event(payload: dict):
    """Background task: parse Zernio webhook, dedup, route DM to booking or Q&A."""
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

        conversation_id = msg["conversation_id"]
        channel = msg["channel"]
        account_id = msg["account_id"]

        # Send typing indicator (best-effort)
        send_typing_indicator(conversation_id, account_id)

        # Route based on booking_flow toggle
        _booking_flow_on = config_loader.get_raw().get("features", {}).get("booking_flow", True)

        if _booking_flow_on:
            # Full booking flow — route through orchestrator
            # NOTE: store user message AFTER orchestrator call, not before.
            # The orchestrator reads wa_get_history(conversation_id) internally.
            # If we store before, Marina sees the message twice (once in history,
            # once as the current inbound). This matches the WhatsApp _flush_buffer
            # pattern which also stores after the call.
            orchestrator_msg = {
                "from": conversation_id,
                "text": text,
                "from_name": msg.get("sender_name", ""),
            }
            reply_text = handle_incoming_whatsapp_message(orchestrator_msg)
            # Store user message after orchestrator (same as WhatsApp path)
            state_registry.dm_store_message(
                conversation_id=conversation_id,
                channel=channel,
                role="user",
                text=text,
                sender_name=msg["sender_name"],
            )
        else:
            # Q&A only — use DM agent
            # DM agent reads dm_get_history which is separate, so store before is fine
            state_registry.dm_store_message(
                conversation_id=conversation_id,
                channel=channel,
                role="user",
                text=text,
                sender_name=msg["sender_name"],
            )
            reply_text = handle_incoming_dm(msg)

        if reply_text:
            # Send reply via Zernio
            send_dm_reply(conversation_id, account_id, reply_text)
            # Store assistant reply
            state_registry.dm_store_message(
                conversation_id=conversation_id,
                channel=channel,
                role="assistant",
                text=reply_text,
            )
    except Exception as e:
        log("webhook_process_error", source="zernio", error=str(e))
```

Key changes from original:
1. Added `_booking_flow_on` check (same pattern as social_agent.py and email_poller.py)
2. When ON: builds `orchestrator_msg` dict with `from=conversation_id`, `text`, `from_name` — the exact shape `handle_incoming_whatsapp_message` expects
3. When OFF: keeps calling `handle_incoming_dm` (Q&A agent, unchanged)
4. CRITICAL — user message storage ordering: when booking_flow is ON, user message is stored AFTER the orchestrator call. The orchestrator internally calls `wa_get_history(conversation_id)` — if the message is already in the DB, Marina sees it twice (once in history, once as current inbound). This matches the WhatsApp `_flush_buffer` pattern (webhook_server.py line 165-167) which also stores after. When booking_flow is OFF, user message is stored BEFORE the DM agent call (matching the original behavior — the DM agent uses `dm_get_history` and this ordering has always worked).
5. Note: the orchestrator's internal `wa_store_message` calls for system notes will store with `channel='whatsapp'` — this is acceptable (system notes are internal, not displayed to customers)

### Step 3: No changes needed to other files

- `social_agent.py` — no changes. The orchestrator already works with any string as `phone`.
- `marina_agent.py` — no changes. `channel="whatsapp"` gives the right writing style for DMs.
- `dm_agent.py` — no changes. Stays as fallback for `booking_flow=false`.
- `state_registry.py` — no changes. `wa_*` functions accept any string as `phone`.

## Tests

File: `tests/social/test_138_dm_booking.py`

1. **test_dm_routes_to_orchestrator_when_flow_on** — booking_flow=true, mock `handle_incoming_whatsapp_message` and `handle_incoming_dm`. Send a Zernio-style DM. Verify: orchestrator called with `from=conversation_id`, `text=message_text`, `from_name=sender_name`. DM agent NOT called. Reply sent via `send_dm_reply`.

2. **test_dm_routes_to_qa_agent_when_flow_off** — booking_flow=false. Same setup. Verify: DM agent called. Orchestrator NOT called.

3. **test_dm_booking_full_flow** — booking_flow=true, DON'T mock the orchestrator. Mock marina_agent, gws_calendar, payment_stub, sheets_writer. Set up booking state with `awaiting_booking_confirmation=true`, have Marina return `booking_confirmed=true`. Verify: booking ref generated, reply contains the booking ref (not literal `[BOOKING_REF]`), state persisted with `hold_created=true`.

4. **test_dm_message_stored_with_correct_channel** — booking_flow=true. Verify: user message stored via `dm_store_message` with correct channel (e.g., `instagram_dm`), not via `wa_store_message` with `channel='whatsapp'`. The reply is also stored with correct channel.

5. **test_dm_dedup_works** — Send the same message_id twice. Verify: only processed once (second one skipped).

6. **test_dm_reply_sent_via_zernio** — booking_flow=true. Verify: reply goes through `send_dm_reply(conversation_id, account_id, reply_text)`, NOT `send_text_message` (WhatsApp).

7. **test_dm_user_message_stored_after_orchestrator** — booking_flow=true. Mock the orchestrator. Verify: at the time `handle_incoming_whatsapp_message` is called, the user message has NOT yet been stored in the database (i.e., `dm_store_message` for `role="user"` is called AFTER the orchestrator). This prevents Marina from seeing the message twice (once in history, once as inbound).

## Success Condition

With `booking_flow: true`, an Instagram or Facebook DM enters the full booking orchestrator. Marina handles it like a WhatsApp message — collects fields, checks availability, creates holds, confirms with booking ref and payment link. The reply is delivered via Zernio DM API. With `booking_flow: false`, DMs still use the Q&A agent. All 7 tests pass.

## Rollback

Revert `webhook_server.py`. DMs go back to Q&A-only behavior.
