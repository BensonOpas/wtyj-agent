# BRIEF 069 — WhatsApp Channel Support: marina_agent + State Foundation

**TL;DR:** Replace WhatsApp stub with marina_agent.py (same Claude brain as email). Add `channel="whatsapp"` for short/casual reply style + conversation history. Add booking state + history tables to state_registry. After this: WhatsApp answers real questions with business data. Booking orchestrator follows in Brief 070.

**Status:** Draft | **Files:** agents/marina/marina_agent.py, shared/state_registry.py, agents/social/social_agent.py, agents/social/webhook_server.py, tests/social/test_069_whatsapp_agent.py, tests/social/test_068_pipeline.py | **Depends on:** 068 | **Blocks:** 070

## Context

WhatsApp pipeline works end-to-end (Brief 067-068): webhook → parse → dedup → agent → send. But social_agent.py returns a hardcoded stub: "Thanks for your message! BlueMarlin test agent is online. 🚀". Customers get no real answers. The goal is WhatsApp as a full booking channel identical to email. This brief is step 1: share marina_agent.py's Claude brain with WhatsApp, add channel-specific style, and lay the state foundation for booking.

## Why This Approach

marina_agent.py is already channel-agnostic — it extracts fields, detects intents, generates replies. Only the writing style differs by channel (email = longer with signature, WhatsApp = short and casual). Adding a `channel` parameter keeps all business logic (booking rules, escalation, field extraction, trip data) in one place — no prompt duplication, no separate Claude call.

Rejected alternative: the old Brief 069 draft built a separate Claude prompt in social_agent.py with its own Q&A-only format (`reply` + `intent`). This would have meant two separate Claude prompts to maintain, no booking capability, and an eventual rewrite when booking was added. Using marina_agent.py directly avoids all of that.

State goes in SQLite (state_registry.py, consistent with existing WhatsApp dedup table). Booking state is persisted per phone number so the orchestrator (Brief 070) can pick up where the conversation left off. Conversation history gives Claude multi-turn context — essential for WhatsApp where messages are short.

Between 069 and 070: Claude answers questions, extracts booking fields, persists state — but actual booking processing (availability check, calendar hold, payment link) doesn't happen yet. Booking placeholders ([BOOKING_REF], [PAYMENT_LINK]) are stripped from replies.

## Source Material

### marina_agent.py current signatures
```python
def _build_system_prompt(thread_flags: dict) -> str:                          # line 57
def _build_user_prompt(from_email, subject, body, thread_fields,
                       thread_flags, action_context=""):                       # line 225
def _build_prompt(from_email, subject, body, thread_fields,
                  thread_flags, action_context=""):                            # line 328
def process_message(from_email, subject, body, thread_fields,
                    thread_flags, action_context=""):                          # line 344
```

### marina_agent.py writing style (lines 86-120)
Email-specific: examples, "Warm regards", agent signature. WhatsApp needs: short, casual, no signature.

### marina_agent.py fallback reply (lines 354-368)
Email-style with signature. WhatsApp should return empty string (silence > canned response).

### state_registry.py WhatsApp functions (lines 373-392)
`wa_has_been_processed`, `wa_mark_as_processed` — dedup only. No booking state or conversation history yet.

### social_agent.py current stub (line 17)
```python
return "Thanks for your message! BlueMarlin test agent is online. 🚀"
```

### webhook_server.py pipeline (lines 65-68)
```python
            reply_text = handle_incoming_whatsapp_message(msg)
            if reply_text:
                send_text_message(to=msg["from"], text=reply_text)
```

### Business values for test assertions (from client.json)
- Klein Curaçao adult: $120, Sunset: $79, 3-in-1: $110
- Email: info@bluefinncharters.com, Agent: Marina
- FAQ what_to_bring: "Towel, sunscreen, hat, sunglasses"

## Instructions

### Step 1 — marina_agent.py: add channel + messages parameters

**1a.** Add `channel: str = "email"` to `_build_system_prompt`, `_build_user_prompt`, `_build_prompt`, and `process_message`. Add `messages: list = None` to `_build_user_prompt`, `_build_prompt`, and `process_message`. All with defaults for backward compatibility — email_poller.py callers are untouched.

**1b.** In `_build_system_prompt`: before the `return f"""` statement, build `writing_style_block` conditionally.

When `channel == "whatsapp"`:
```
WRITING STYLE — WHATSAPP:
This is WhatsApp, not email. Keep replies short and natural.
- Simple question → 1-2 sentences
- Detailed question → short paragraph, no more
- No signatures, no sign-offs, no "Warm regards"
- No greeting unless the customer greeted first
- Use contractions. Be casual. Match the sender's energy.
- Emojis: sparingly, only if the sender used them first or if it genuinely fits

Mirror the sender's tone and length. Short question gets a short answer.

AVOID: em dashes, en dashes, "Shall I", "I'd be happy to", "Great choice",
"Amazing", "Absolutely", forced enthusiasm, reasoning out loud.
```

When `channel == "email"` (default): the existing WRITING STYLE text through `AGENT SIGNATURE: {signature}`, unchanged. Extract it into the else branch of the conditional.

Then replace the hardcoded writing style section in the f-string (from `WRITING STYLE:` through `AGENT SIGNATURE: {signature}`, lines 86-120) with `{writing_style_block}`.

**1c.** In `_build_user_prompt`: when `messages` is provided and `channel == "whatsapp"`, add CONVERSATION HISTORY section before INBOUND MESSAGE:
```
CONVERSATION HISTORY (recent messages):
  Customer: Hello
  Marina: Hi! How can I help?
```
When messages is empty: show `(new conversation)`. When `channel == "email"` (default), skip the section entirely.

For WhatsApp, adjust INBOUND MESSAGE format — no Subject line, use "Text" instead of "Body":
```
INBOUND MESSAGE:
  From: {from_email}
  Text: {body}
```
For email, keep existing format unchanged (From, Subject, Body).

**1d.** In `process_message`: pass `channel` and `messages` to `_build_system_prompt(thread_flags, channel)` and `_build_user_prompt(..., channel=channel, messages=messages)`. After building fallback dict, add:
```python
        if channel == "whatsapp":
            fallback["reply"] = ""
```

**1e.** In `_build_prompt` (backward-compat wrapper): pass `channel` and `messages` through to both sub-functions.

**1f.** Update header: `# Last modified: Brief 069`

### Step 2 — state_registry.py: add WhatsApp booking state + conversation history

**2a.** Add `import json` to the imports at the top of the file.

**2b.** In `_get_conn()`, after the `whatsapp_processed` table (after line 74, before the ALTER TABLE blocks), add two new tables:

```python
    conn.execute(
        "CREATE TABLE IF NOT EXISTS whatsapp_threads ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "phone TEXT NOT NULL, "
        "role TEXT NOT NULL, "
        "text TEXT NOT NULL, "
        "created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_whatsapp_threads_phone "
        "ON whatsapp_threads(phone, created_at)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS whatsapp_booking_state ("
        "phone TEXT PRIMARY KEY, "
        "fields_json TEXT DEFAULT '{}', "
        "flags_json TEXT DEFAULT '{}', "
        "completed_bookings_json TEXT DEFAULT '[]', "
        "last_activity TEXT NOT NULL, "
        "created_at TEXT NOT NULL"
        ")"
    )
```

**2c.** After `wa_mark_as_processed()` (after line 392), before the module-load init comment, add four functions:

```python
def wa_store_message(phone: str, role: str, text: str):
    """Store a WhatsApp message in conversation history."""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO whatsapp_threads (phone, role, text, created_at) VALUES (?, ?, ?, ?)",
        (phone, role, text, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()


def wa_get_history(phone: str, limit: int = 10) -> list:
    """Get recent conversation history for a phone number (last 24h, oldest first)."""
    conn = _get_conn()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    rows = conn.execute(
        "SELECT role, text, created_at FROM whatsapp_threads "
        "WHERE phone = ? AND created_at > ? "
        "ORDER BY created_at DESC LIMIT ?",
        (phone, cutoff, limit)
    ).fetchall()
    conn.close()
    return [{"role": r[0], "text": r[1], "created_at": r[2]} for r in reversed(rows)]


def wa_get_booking_state(phone: str) -> dict:
    """Get booking state for a phone number. Returns {fields, flags, completed_bookings}."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT fields_json, flags_json, completed_bookings_json "
        "FROM whatsapp_booking_state WHERE phone = ?",
        (phone,)
    ).fetchone()
    conn.close()
    if not row:
        return {"fields": {}, "flags": {}, "completed_bookings": []}
    return {
        "fields": json.loads(row[0] or "{}"),
        "flags": json.loads(row[1] or "{}"),
        "completed_bookings": json.loads(row[2] or "[]"),
    }


def wa_save_booking_state(phone: str, fields: dict, flags: dict,
                          completed_bookings: list = None):
    """Save/update booking state for a phone number."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    cb = json.dumps(completed_bookings or [], ensure_ascii=False)
    conn.execute(
        "INSERT OR REPLACE INTO whatsapp_booking_state "
        "(phone, fields_json, flags_json, completed_bookings_json, last_activity, created_at) "
        "VALUES (?, ?, ?, ?, ?, COALESCE("
        "(SELECT created_at FROM whatsapp_booking_state WHERE phone = ?), ?))",
        (phone, json.dumps(fields, ensure_ascii=False),
         json.dumps(flags, ensure_ascii=False), cb, now, phone, now)
    )
    conn.commit()
    conn.close()
```

**2d.** Update header: `# Last modified: Brief 069`

### Step 3 — social_agent.py: replace stub with marina_agent wrapper

Replace the entire file:

```python
# bluemarlin/agents/social/social_agent.py
# Created: Brief 068
# Last modified: Brief 069
# Purpose: WhatsApp agent — calls marina_agent with channel="whatsapp"

from shared import state_registry
from shared import bm_logger
from agents.marina import marina_agent


def handle_incoming_whatsapp_message(message: dict) -> str:
    """
    Process a WhatsApp message: fetch state + history, call marina_agent,
    merge + persist state, return reply.
    Returns reply string or empty string on failure.
    """
    phone = message.get("from", "")
    text = message.get("text", "")
    from_name = message.get("from_name", "")

    # Get existing booking state
    state = state_registry.wa_get_booking_state(phone)
    fields = state.get("fields", {})
    flags = state.get("flags", {})

    # Get conversation history (last 10 messages, 24h window)
    history = state_registry.wa_get_history(phone, limit=10)

    # Build from identifier with name if available
    from_id = f"{phone} ({from_name})" if from_name else phone

    # Call marina_agent with channel="whatsapp"
    result = marina_agent.process_message(
        from_email=from_id,
        subject="",
        body=text,
        thread_fields=fields,
        thread_flags=flags,
        action_context="",
        channel="whatsapp",
        messages=history,
    )

    reply = result.get("reply", "")

    if reply:
        # Strip booking placeholders (orchestrator not active until Brief 070)
        reply = reply.replace("[BOOKING_REF]", "").replace("[PAYMENT_LINK]", "")

        # Merge fields — overwrite when Claude returns non-empty values
        new_fields = result.get("fields", {}) or {}
        for k, v in new_fields.items():
            if v is not None and v != "":
                fields[k] = v
            elif v == "" and k in fields:
                del fields[k]

        # Merge flags
        new_flags = result.get("flags", {}) or {}
        flags.update(new_flags)

        # Persist state
        state_registry.wa_save_booking_state(phone, fields, flags)

        # Log
        bm_logger.log("whatsapp_agent_reply",
            phone=phone,
            intents=result.get("intents", []),
            reply_length=len(reply))

    return reply
```

### Step 4 — webhook_server.py: store conversation history

Replace lines 65-68 (the agent call section inside `_process_whatsapp_event`):

**Old:**
```python
            # Agent generates reply
            reply_text = handle_incoming_whatsapp_message(msg)
            if reply_text:
                send_text_message(to=msg["from"], text=reply_text)
```

**New:**
```python
            # Agent generates reply (reads history + state internally)
            reply_text = handle_incoming_whatsapp_message(msg)
            if reply_text:
                state_registry.wa_store_message(msg["from"], "user", msg["text"])
                send_text_message(to=msg["from"], text=reply_text)
                state_registry.wa_store_message(msg["from"], "assistant", reply_text)
```

Update header: `# Last modified: Brief 069`

### Step 5 — Update test_068_pipeline.py

**5a.** Replace `test_agent_stub_returns_reply` (lines 144-149) with:

```python
@patch("agents.social.social_agent.marina_agent.process_message")
def test_agent_returns_reply(mock_process):
    """Agent returns Claude-generated reply (mocked marina_agent)."""
    mock_process.return_value = {
        "intents": ["greeting"], "fields": {}, "confidence": "high",
        "reply": "Hi! How can I help?",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }
    msg = {"from": "59996881585", "text": "Hello", "from_name": "Test", "channel": "whatsapp"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == "Hi! How can I help?"
```

**5b.** In `test_webhook_post_triggers_pipeline` (line 224), add a second patch. Replace:

```python
    with patch("agents.social.webhook_server.send_text_message") as mock_send:
```

With:

```python
    with patch("agents.social.webhook_server.send_text_message") as mock_send, \
         patch("agents.social.webhook_server.handle_incoming_whatsapp_message", return_value="Test reply"):
```

### Step 6 — Create test_069_whatsapp_agent.py

Create `tests/social/test_069_whatsapp_agent.py`:

```python
# bluemarlin/tests/social/test_069_whatsapp_agent.py
# Created: Brief 069
# Purpose: Tests for WhatsApp channel support + state foundation

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ["WHATSAPP_VERIFY_TOKEN"] = "test_token_067"
os.environ["WHATSAPP_ACCESS_TOKEN"] = "test_access_token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "990622044139349"

from agents.marina.marina_agent import _build_system_prompt, _build_user_prompt, process_message
from agents.social.social_agent import handle_incoming_whatsapp_message
from shared import state_registry


# --- Helpers ---

def _cleanup_phone(phone):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


# --- marina_agent channel tests ---

def test_system_prompt_whatsapp_style():
    """WhatsApp system prompt has WhatsApp style, no agent signature."""
    prompt = _build_system_prompt({}, channel="whatsapp")
    assert "WHATSAPP" in prompt
    assert "AGENT SIGNATURE" not in prompt
    assert "Marina" in prompt
    assert "BlueFinn" in prompt


def test_system_prompt_email_default():
    """Default (email) system prompt has agent signature, no WHATSAPP."""
    prompt = _build_system_prompt({})
    assert "AGENT SIGNATURE" in prompt
    assert "WHATSAPP" not in prompt


def test_user_prompt_whatsapp_no_subject():
    """WhatsApp user prompt has no Subject line, uses Text instead of Body."""
    prompt = _build_user_prompt("5991234567", "", "Hello", {}, {},
                                 channel="whatsapp")
    assert "Subject:" not in prompt
    assert "Text:" in prompt


def test_user_prompt_whatsapp_with_history():
    """WhatsApp user prompt includes conversation history."""
    history = [
        {"role": "user", "text": "Hi there", "created_at": "2026-03-11T10:00:00"},
        {"role": "assistant", "text": "Hello! How can I help?", "created_at": "2026-03-11T10:00:05"},
    ]
    prompt = _build_user_prompt("5991234567", "", "What trips?", {}, {},
                                 channel="whatsapp", messages=history)
    assert "Customer: Hi there" in prompt
    assert "Marina: Hello! How can I help?" in prompt


def test_user_prompt_whatsapp_empty_history():
    """WhatsApp user prompt shows '(new conversation)' when no history."""
    prompt = _build_user_prompt("5991234567", "", "Hi", {}, {},
                                 channel="whatsapp", messages=[])
    assert "(new conversation)" in prompt


def test_user_prompt_email_has_subject():
    """Default (email) user prompt includes Subject line."""
    prompt = _build_user_prompt("test@test.com", "Booking inquiry", "Hello", {}, {})
    assert "Subject:" in prompt
    assert "Booking inquiry" in prompt


@patch("agents.marina.marina_agent.anthropic.Anthropic")
def test_process_message_whatsapp_success(mock_cls):
    """process_message with channel=whatsapp returns parsed reply."""
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=json.dumps({
        "intents": ["inquiry"], "fields": {}, "confidence": "high",
        "reply": "Klein Curacao is $120 per adult!",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }))]
    mock_resp.usage = MagicMock(input_tokens=500, output_tokens=30)
    mock_cls.return_value.messages.create.return_value = mock_resp

    result = process_message("5991234567", "", "How much?", {}, {},
                              channel="whatsapp")
    assert result["reply"] == "Klein Curacao is $120 per adult!"


@patch("agents.marina.marina_agent.anthropic.Anthropic")
def test_process_message_whatsapp_failure_empty_reply(mock_cls):
    """WhatsApp API failure returns empty reply (silence > canned response)."""
    mock_cls.return_value.messages.create.side_effect = Exception("API down")
    result = process_message("5991234567", "", "Hello", {}, {},
                              channel="whatsapp")
    assert result["reply"] == ""


# --- state_registry conversation history tests ---

def test_wa_store_and_retrieve_messages():
    """Store 3 messages, retrieve in chronological order."""
    phone = "TEST_069_STORE_001"
    _cleanup_phone(phone)
    state_registry.wa_store_message(phone, "user", "Hello")
    state_registry.wa_store_message(phone, "assistant", "Hi there!")
    state_registry.wa_store_message(phone, "user", "What trips?")
    history = state_registry.wa_get_history(phone)
    assert len(history) == 3
    assert history[0]["role"] == "user"
    assert history[0]["text"] == "Hello"
    assert history[1]["role"] == "assistant"
    assert history[1]["text"] == "Hi there!"
    assert history[2]["text"] == "What trips?"
    _cleanup_phone(phone)


def test_wa_history_limit():
    """Store 15, retrieve 10 most recent."""
    phone = "TEST_069_LIMIT_001"
    _cleanup_phone(phone)
    for i in range(15):
        state_registry.wa_store_message(phone, "user", f"Message {i}")
    history = state_registry.wa_get_history(phone, limit=10)
    assert len(history) == 10
    assert history[0]["text"] == "Message 5"
    assert history[9]["text"] == "Message 14"
    _cleanup_phone(phone)


def test_wa_history_24h_expiry():
    """Messages older than 24h excluded."""
    phone = "TEST_069_EXPIRY_001"
    _cleanup_phone(phone)
    old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    conn = state_registry._get_conn()
    conn.execute(
        "INSERT INTO whatsapp_threads (phone, role, text, created_at) VALUES (?, ?, ?, ?)",
        (phone, "user", "Old message", old_time)
    )
    conn.commit()
    conn.close()
    state_registry.wa_store_message(phone, "user", "Recent message")
    history = state_registry.wa_get_history(phone)
    assert len(history) == 1
    assert history[0]["text"] == "Recent message"
    _cleanup_phone(phone)


# --- state_registry booking state tests ---

def test_wa_booking_state_fresh():
    """Fresh phone returns empty state."""
    phone = "TEST_069_FRESH_001"
    _cleanup_phone(phone)
    state = state_registry.wa_get_booking_state(phone)
    assert state == {"fields": {}, "flags": {}, "completed_bookings": []}


def test_wa_booking_state_round_trip():
    """Save and retrieve booking state."""
    phone = "TEST_069_STATE_001"
    _cleanup_phone(phone)
    fields = {"trip_key": "klein_curacao", "guests": "4", "date": "2026-03-15"}
    flags = {"slot_checked": True}
    state_registry.wa_save_booking_state(phone, fields, flags)
    state = state_registry.wa_get_booking_state(phone)
    assert state["fields"]["trip_key"] == "klein_curacao"
    assert state["fields"]["guests"] == "4"
    assert state["flags"]["slot_checked"] is True
    assert state["completed_bookings"] == []
    _cleanup_phone(phone)


# --- social_agent integration tests ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_social_agent_strips_placeholders(mock_process):
    """social_agent strips [BOOKING_REF] and [PAYMENT_LINK] from reply."""
    mock_process.return_value = {
        "intents": ["booking"], "fields": {}, "confidence": "high",
        "reply": "Booked! Ref [BOOKING_REF]. Pay here: [PAYMENT_LINK]",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }
    msg = {"from": "5991234567", "text": "Book it", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert "[BOOKING_REF]" not in reply
    assert "[PAYMENT_LINK]" not in reply
    assert "Booked!" in reply


@patch("agents.social.social_agent.marina_agent.process_message")
def test_social_agent_persists_state(mock_process):
    """social_agent persists extracted fields to booking state."""
    phone = "TEST_069_PERSIST_001"
    _cleanup_phone(phone)
    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {"trip_key": "sunset_cruise", "guests": "2"},
        "confidence": "high",
        "reply": "Sunset cruise for 2, got it!",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }
    msg = {"from": phone, "text": "Sunset for 2", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == "Sunset cruise for 2, got it!"
    state = state_registry.wa_get_booking_state(phone)
    assert state["fields"]["trip_key"] == "sunset_cruise"
    assert state["fields"]["guests"] == "2"
    _cleanup_phone(phone)


@patch("agents.social.social_agent.marina_agent.process_message")
def test_social_agent_api_failure_empty(mock_process):
    """social_agent returns empty string when marina_agent returns empty reply."""
    mock_process.return_value = {
        "intents": ["inquiry"], "fields": {}, "confidence": "low",
        "reply": "",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": "Fallback"
    }
    msg = {"from": "5991234567", "text": "Hello", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == ""


# --- Webhook conversation storage test ---

def test_webhook_stores_conversation():
    """Webhook pipeline stores user + assistant messages in history."""
    from fastapi.testclient import TestClient
    from agents.social.webhook_server import app

    test_phone = "TEST_069_WEBHOOK_001"
    test_msg_id = "wamid.TEST_069_WEBHOOK_STORE"
    _cleanup_phone(test_phone)

    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_processed WHERE message_id = ?", (test_msg_id,))
    conn.commit()
    conn.close()

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "967346842390828", "changes": [{"value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "15551681192", "phone_number_id": "990622044139349"},
            "contacts": [{"profile": {"name": "Test"}, "wa_id": test_phone}],
            "messages": [{"from": test_phone, "id": test_msg_id, "timestamp": "1773300000",
                          "text": {"body": "What trips?"}, "type": "text"}]
        }, "field": "messages"}]}]
    }

    client = TestClient(app)
    with patch("agents.social.webhook_server.send_text_message") as mock_send, \
         patch("agents.social.webhook_server.handle_incoming_whatsapp_message",
               return_value="We have Klein Curaçao and more!"):
        mock_send.return_value = True
        r = client.post("/webhooks/meta/whatsapp", json=payload)
        assert r.status_code == 200

    history = state_registry.wa_get_history(test_phone)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["text"] == "What trips?"
    assert history[1]["role"] == "assistant"
    assert history[1]["text"] == "We have Klein Curaçao and more!"
    _cleanup_phone(test_phone)
```

### Step 7 — Run tests

Brief 069 tests:
```
cd ~/Projects/bluemarlin-agent && python -m pytest bluemarlin/tests/social/test_069_whatsapp_agent.py -v
```

Brief 068 regression:
```
python -m pytest bluemarlin/tests/social/test_068_pipeline.py -v
```

Brief 067 regression:
```
python -m pytest bluemarlin/tests/social/test_067_webhook.py -v
```

### Step 8 — Write output file

Write `briefs/marina_output_069.md` with: what was done, all test results, anything unexpected.

## Tests

18 tests in test_069, asserting specific known values:

**marina_agent channel (8 tests):**
- System prompt WhatsApp: contains "WHATSAPP", NOT "AGENT SIGNATURE"
- System prompt email default: contains "AGENT SIGNATURE", NOT "WHATSAPP"
- User prompt WhatsApp: no "Subject:", has "Text:"
- User prompt WhatsApp + history: "Customer: Hi there", "Marina: Hello!"
- User prompt WhatsApp empty history: "(new conversation)"
- User prompt email: contains "Subject:", "Booking inquiry"
- process_message WhatsApp success: reply == "Klein Curacao is $120 per adult!"
- process_message WhatsApp failure: reply == ""

**state_registry (5 tests):**
- Conversation store: 3 messages, chronological order, exact text
- History limit: 15 stored → 10 returned, messages 5-14
- History 24h expiry: old excluded, recent included
- Booking state fresh: empty dict
- Booking state round trip: trip_key == "klein_curacao", slot_checked == True

**social_agent (3 tests):**
- Strips [BOOKING_REF] and [PAYMENT_LINK] from reply
- Persists extracted fields: trip_key == "sunset_cruise" in wa_get_booking_state
- Empty reply on API failure: reply == ""

**Webhook integration (1 test):**
- Stores conversation: 2 messages in history, correct roles and text

Plus 1 updated test in test_068 (stub → mocked marina_agent).

## Success Condition

WhatsApp messages get real Claude-powered replies from marina_agent.py with WhatsApp-appropriate short/casual style. Conversation history persists in SQLite. Booking fields extracted and stored for future orchestrator. All 18 Brief 069 tests pass. Brief 067 (7 tests) and 068 (10 tests) regression pass.

## Rollback

```
git checkout HEAD -- agents/marina/marina_agent.py shared/state_registry.py agents/social/social_agent.py agents/social/webhook_server.py tests/social/test_068_pipeline.py
rm tests/social/test_069_whatsapp_agent.py
```
