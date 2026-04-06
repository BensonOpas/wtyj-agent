# OUTPUT 131 — DM Agent + Reply Path

## What was done

### Step 1: `agents/social/dm_agent.py` (new)
- `handle_incoming_dm(message)` — thin wrapper that routes IG/FB DMs through Marina for Q&A
- Fetches conversation history via `dm_get_history()`, passes to `marina_agent.process_message()` with correct channel
- Rate limiting: 30 replies/hr per conversation (counts assistant messages in last hour)
- No booking state machine — Q&A only
- Returns empty string on rate limit, empty reply, or exception (no crash)

### Step 2: `agents/marina/marina_agent.py`
- Added `elif channel in ("instagram_dm", "facebook_dm"):` block in `_build_system_prompt()` with DM-specific writing style
- Key addition: BOOKING REQUESTS section that redirects to WhatsApp (`wa.me/` link from `business.whatsapp`) and email (`business.email`) from client.json
- Instructs Claude to NOT set booking flags, NOT set requires_human for DMs
- Added DM channel handling in `_build_user_prompt()` — conversation history section and inbound message format (same as WhatsApp pattern)
- Added DM fallback reply in `process_message()` — same "give me a moment" message as WhatsApp (Rule 3 accepted exception)

### Step 3: `agents/social/webhook_server.py`
- Added imports: `send_dm_reply`, `send_typing_indicator` from zernio_dm_client, `handle_incoming_dm` from dm_agent
- Replaced Brief 130 placeholder comment in `_process_zernio_event()` with full agent call:
  1. Send typing indicator (best-effort)
  2. Call `handle_incoming_dm(msg)`
  3. If reply: send via `send_dm_reply()` and store via `dm_store_message()`

## Test results

- **Brief 131 tests: 10/10 passed**
- **Full social regression: 296/298 passed, 2 pre-existing failures** (test_070 stale date + test_073 stale date — not related to this brief)

## Unexpected

- Brief reviewer caught wrong config field: `contact_for_booking` is not in `business` section. Used `business.email` instead (same address, correct path). Fixed before execution.
