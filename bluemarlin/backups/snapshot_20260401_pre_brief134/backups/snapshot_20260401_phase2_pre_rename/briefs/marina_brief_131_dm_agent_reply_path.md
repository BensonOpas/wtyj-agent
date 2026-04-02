# BRIEF 131 — DM Agent + Reply Path
**Status:** Draft | **Files:** `agents/social/dm_agent.py` (new), `agents/marina/marina_agent.py`, `agents/social/webhook_server.py` | **Depends on:** Brief 130 | **Blocks:** Brief 132 (Dashboard multi-channel)

## Context

Brief 130 laid the plumbing: Zernio webhook receives IG/FB DMs, verifies HMAC, dedupes, and stores in SQLite. But messages are only stored — no processing, no reply. The `_process_zernio_event` function has a placeholder comment: "Brief 131 will add: dm_agent.handle_incoming_dm(msg) + send reply".

This brief closes the loop: incoming DMs are processed through Marina (Q&A only), replies are sent back via Zernio, and booking requests are redirected to WhatsApp/email.

## Why This Approach

**Considered:** Reusing `social_agent.py` for DMs. Rejected — it's 700+ lines of booking state machine (holds, calendar, payment, manifests). DMs are Q&A only with booking redirect. A separate thin agent keeps things clean and avoids accidentally entering the booking flow.

**Considered:** Adding a booking flow to DMs. Rejected — WhatsApp booking flow is battle-tested and complex. Duplicating it for IG/FB DMs adds risk with no clear benefit. Redirect to WhatsApp/email is the right call for now.

**Tradeoff:** DM agent doesn't have booking state (no holds, no confirmations). If a customer tries to book via IG DM, Marina will redirect them. This is a feature, not a limitation.

## Source Material

### Channel handling in marina_agent.py (current):
- `channel="email"` → formal writing style, email signature, full subject/body format
- `channel="whatsapp"` → casual style, no signature, short replies, conversation history section
- `_build_system_prompt()` has `if channel == "whatsapp":` block (line 118) with writing style, then `else:` block (line 180) for email
- `_build_user_prompt()` has `if channel == "whatsapp":` block (line 402) for history and `if channel == "whatsapp":` (line 416) for inbound message format
- `process_message()` accepts `channel` param, passes to both prompt builders and fallback selection
- Fallback for WhatsApp: `"Hey, give me a moment, I'll get right back to you."` (line 497)

### Contact info in client.json:
- `"whatsapp": "+599 9690 3717"` (line 6)
- `"email": "info@bluefinncharters.com"` (line 4, under `business`)
- Accessed via `config_loader.get_business()["email"]`

### Brief 130 functions available:
- `state_registry.dm_store_message(conversation_id, channel, role, text, sender_name)`
- `state_registry.dm_get_history(conversation_id, channel, limit)`
- `zernio_dm_client.send_dm_reply(conversation_id, account_id, text)`
- `zernio_dm_client.send_typing_indicator(conversation_id, account_id)`

### Webhook handler `_process_zernio_event` in webhook_server.py (from Brief 130):
- Parses webhook → dedup → stores user message → placeholder for agent call
- `msg` dict has: `conversation_id`, `platform`, `channel`, `sender_name`, `sender_id`, `text`, `message_id`, `account_id`

## Instructions

### Step 1: Create `agents/social/dm_agent.py`

New file — thin wrapper that routes DMs through Marina for Q&A.

```python
# bluemarlin/agents/social/dm_agent.py
# Created: Brief 131
# Purpose: DM conversation handler — routes IG/FB DMs through Marina for Q&A, redirects bookings

import time
from shared import state_registry
from shared import bm_logger
from agents.marina import marina_agent

_MAX_REPLIES_PER_HOUR = 30
_REPLY_WINDOW_SECONDS = 3600


def handle_incoming_dm(message: dict) -> str:
    """Process an incoming IG/FB DM through Marina. Q&A only, no booking flow.

    Args:
        message: normalized dict from parse_zernio_webhook with keys:
            conversation_id, platform, channel, sender_name, text, account_id

    Returns: reply text, or empty string if rate limited or error.
    """
    conversation_id = message["conversation_id"]
    channel = message["channel"]
    sender_name = message.get("sender_name", "")
    text = message["text"]

    # Rate limiting per conversation
    if _is_rate_limited(conversation_id, channel):
        bm_logger.log("dm_rate_limited", conversation_id=conversation_id[:20],
                       channel=channel)
        return ""

    # Get conversation history
    history = state_registry.dm_get_history(conversation_id, channel, limit=10)
    messages = [{"role": m["role"], "text": m["text"]} for m in history]

    try:
        result = marina_agent.process_message(
            from_email=conversation_id,
            subject="",
            body=text,
            thread_fields={"customer_name": sender_name} if sender_name else {},
            thread_flags={},
            action_context="",
            channel=channel,
            messages=messages,
        )

        reply = result.get("reply", "")
        if not reply:
            bm_logger.log("dm_empty_reply", conversation_id=conversation_id[:20],
                           channel=channel)
            return ""

        # Track reply time for rate limiting
        _record_reply_time(conversation_id, channel)

        bm_logger.log("dm_reply_generated", conversation_id=conversation_id[:20],
                       channel=channel, intents=result.get("intents", []))
        return reply

    except Exception as e:
        bm_logger.log("dm_agent_error", conversation_id=conversation_id[:20],
                       channel=channel, error=str(e)[:200])
        return ""


def _is_rate_limited(conversation_id: str, channel: str) -> bool:
    """Check if conversation has exceeded reply rate limit."""
    history = state_registry.dm_get_history(conversation_id, channel, limit=50)
    now = time.time()
    cutoff = now - _REPLY_WINDOW_SECONDS
    recent_replies = 0
    for msg in history:
        if msg["role"] == "assistant":
            try:
                from datetime import datetime, timezone
                msg_time = datetime.fromisoformat(msg["created_at"]).timestamp()
                if msg_time > cutoff:
                    recent_replies += 1
            except (ValueError, KeyError):
                pass
    return recent_replies >= _MAX_REPLIES_PER_HOUR


def _record_reply_time(conversation_id: str, channel: str):
    """No-op — reply times tracked implicitly via dm_store_message timestamps."""
    pass
```

### Step 2: Modify `agents/marina/marina_agent.py`

**2a.** In `_build_system_prompt()`, add a DM channel block. Currently line 118 has `if channel == "whatsapp":` and line 180 has `else:` (email). Change the structure to:

Replace the `if channel == "whatsapp":` / `else:` pattern with a three-way check:

After the existing WhatsApp block (which ends around line 179), and before the `else:` block (email, line 180), insert an `elif` for DM channels:

```python
    elif channel in ("instagram_dm", "facebook_dm"):
        platform_name = "Instagram" if channel == "instagram_dm" else "Facebook"
        business = config_loader.get_business()
        wa_number = business.get("whatsapp", "")
        booking_email = business.get("email", "")
        writing_style_block = (
            f"WRITING STYLE — {platform_name.upper()} DM:\n"
            "You are replying to a direct message. Sound like a real person.\n"
            "\n"
            "LENGTH:\n"
            "- Normal reply: under 60 words\n"
            "- Detailed answer: under 100 words\n"
            "\n"
            "FORMATTING:\n"
            "- Use line breaks between distinct thoughts\n"
            "- Short, natural paragraphs\n"
            "- No bullet points unless listing trip options\n"
            "\n"
            "GREETINGS:\n"
            "- Greet ONLY on the first message of a new conversation\n"
            "- Check CONVERSATION HISTORY — if you already replied, skip the greeting\n"
            "\n"
            "PRICING:\n"
            "- List trip names and short descriptions first\n"
            "- Only include prices when explicitly asked\n"
            "\n"
            "BOOKING REQUESTS:\n"
            f"When the customer wants to book a trip, do NOT collect booking fields.\n"
            f"Instead, redirect them warmly:\n"
            f"- WhatsApp: wa.me/{wa_number.replace('+', '').replace(' ', '')}\n"
            f"- Email: {booking_email}\n"
            f"Example: \"For bookings, message us on WhatsApp at wa.me/{wa_number.replace('+', '').replace(' ', '')} "
            f"or email {booking_email} — we'll get you sorted!\"\n"
            "\n"
            "RULES:\n"
            "- Answer first, then suggest next steps\n"
            "- No sign-offs, no signatures\n"
            "- Use contractions naturally\n"
            "- Match the sender's energy and length\n"
            "- NEVER return an empty reply\n"
            "- Do NOT set any booking flags (booking_confirmed, awaiting_booking_confirmation, etc.)\n"
            "- Do NOT set requires_human — DM escalations are not supported yet\n"
            "\n"
            "AVOID: em dashes, \"Shall I\", \"I'd be happy to\", \"Great choice\",\n"
            "\"Amazing\", \"Absolutely\", forced enthusiasm.\n"
            "\n"
            "Emojis: sparingly, only if the sender used them first."
        )
```

**2b.** In `_build_user_prompt()`, add DM channel handling for history and inbound message sections.

At line 402, where `if channel == "whatsapp":` handles history, add an `elif` before the implicit `else`:

```python
    elif channel in ("instagram_dm", "facebook_dm"):
        if messages:
            history_lines = []
            for m in messages:
                role_label = "Customer" if m.get("role") == "user" else "Marina"
                history_lines.append(f"  {role_label}: {m.get('text', '')}")
            history_section = (
                "CONVERSATION HISTORY (recent messages):\n"
                + "\n".join(history_lines) + "\n\n"
            )
        else:
            history_section = "CONVERSATION HISTORY (recent messages):\n  (new conversation)\n\n"
```

At line 416, where `if channel == "whatsapp":` handles the inbound section, add an `elif`:

```python
    elif channel in ("instagram_dm", "facebook_dm"):
        inbound_section = (
            f"INBOUND MESSAGE:\n"
            f"  From: {from_email}\n"
            f"  Text: {body}"
        )
```

**2c.** In `process_message()`, add DM fallback reply. At line 493, after the WhatsApp fallback:

```python
    elif channel in ("instagram_dm", "facebook_dm"):
        # ⚠️  HARDCODED FALLBACK — Rule 3 accepted exception (API failure path only)
        fallback["reply"] = "Hey, give me a moment, I'll get right back to you."
```

**2d.** Update the file header comment: `# Last modified: Brief 131`

### Step 3: Modify `agents/social/webhook_server.py`

**3a.** Add import for dm_agent at the top (after existing imports):

```python
from agents.social.dm_agent import handle_incoming_dm
from agents.social.zernio_dm_client import send_dm_reply, send_typing_indicator
```

Note: `parse_zernio_webhook` and `verify_webhook_signature` are already imported from Brief 130. Add `send_dm_reply` and `send_typing_indicator` to the existing import, and add the new dm_agent import.

**3b.** In `_process_zernio_event()`, replace the placeholder comment with the actual agent call + reply. After the `dm_store_message()` call (line 226), replace `# Brief 131 will add...` with:

```python
        # Send typing indicator (best-effort)
        send_typing_indicator(msg["conversation_id"], msg["account_id"])

        # Process through Marina
        reply_text = handle_incoming_dm(msg)

        if reply_text:
            # Send reply via Zernio
            send_dm_reply(msg["conversation_id"], msg["account_id"], reply_text)
            # Store assistant reply
            state_registry.dm_store_message(
                conversation_id=msg["conversation_id"],
                channel=msg["channel"],
                role="assistant",
                text=reply_text,
            )
```

**3c.** Update the file header comment: `# Last modified: Brief 131`

## Tests

File: `tests/social/test_131_dm_agent.py`

1. **test_handle_dm_calls_marina** — mock `marina_agent.process_message`, verify it's called with `channel="instagram_dm"`, returns reply text
2. **test_handle_dm_facebook_channel** — same but with `channel="facebook_dm"`, verify channel passed correctly
3. **test_handle_dm_includes_history** — store 2 DM messages first, verify `process_message` receives them in `messages` param
4. **test_handle_dm_rate_limited** — store 30 assistant messages in history, verify returns empty string
5. **test_handle_dm_empty_reply** — mock marina returns `reply=""`, verify handle_incoming_dm returns empty string
6. **test_handle_dm_api_failure** — mock marina raises exception, verify returns empty string (no crash)
7. **test_prompt_has_dm_writing_style** — call `_build_prompt()` with `channel="instagram_dm"`, verify prompt contains "INSTAGRAM DM" and "BOOKING REQUESTS" and "wa.me/"
8. **test_prompt_has_booking_redirect** — verify DM prompt contains WhatsApp number and booking email from client.json
9. **test_prompt_whatsapp_unchanged** — call `_build_prompt()` with `channel="whatsapp"`, verify it does NOT contain "BOOKING REQUESTS" or "wa.me/" redirect (regression check)
10. **test_dm_fallback_reply** — verify `process_message` with DM channel returns fallback when API key is missing

## Success Condition

IG/FB DMs processed through Marina, replies sent back via Zernio. Booking requests get redirected to WhatsApp/email. Rate limiting at 30/hr per conversation. All 10 tests pass.

## Rollback

Delete `dm_agent.py`. Remove the `elif channel in ("instagram_dm", "facebook_dm")` blocks from `marina_agent.py`. Remove agent call from `_process_zernio_event()` in `webhook_server.py`. Brief 130 storage still works.
