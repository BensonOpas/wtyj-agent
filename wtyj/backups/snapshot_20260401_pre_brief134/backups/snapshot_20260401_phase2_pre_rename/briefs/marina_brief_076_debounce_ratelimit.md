# BRIEF 076 — WhatsApp Message Debouncing + Rate Limit 50
**Status:** Draft | **Files:** `agents/social/webhook_server.py`, `agents/social/social_agent.py`, `tests/social/test_076_debounce.py` (new) | **Depends on:** Briefs 068, 073, 074 | **Blocks:** nothing

## Context
When a user sends multiple WhatsApp messages in quick succession (e.g. "3-1 snorkeling" / "3perople" / "no 4" / "sorry. 5" over 4 seconds), each message triggers an independent Claude call. Each call has incomplete context and may generate a contradictory reply. Calvin Adamus hit this on 2026-03-12 — 6 messages in 3 seconds produced 6 replies, some about the wrong trip.

The rate limit is also too conservative at 25/hr. A rapid-fire conversation easily burns through this in 15 minutes.

## Why This Approach
Three options were considered:

1. **Per-phone lock + queue** — First message processes immediately, later messages queue until the lock releases. Problem: the first message still gets a premature reply with incomplete context ("Which trip?" when the next message says "snorkeling").
2. **Debounce timer** — Buffer messages for 2 seconds. If more arrive, reset the timer. When it fires, concatenate and process as one. Adds 2s latency to every message but eliminates contradictory multi-replies. This is the WhatsApp-native pattern — users expect a brief pause before "typing...".
3. **Client-side "read receipt" delay** — Send a read receipt immediately, delay processing by N seconds. Same as #2 but with an explicit read indicator. More complex, marginal UX benefit.

**Chosen: Option 2 (debounce).** Simplest, highest impact. 2-second window covers typical rapid-fire typing bursts (Calvin's burst was spread over 4 seconds with messages every 1-2s). A 5-second hard cap prevents infinite deferral if someone sends a message every 1.5s continuously.

## Source Material

### Current webhook_server.py flow (lines 60-87)
```python
def _process_whatsapp_event(payload: dict):
    _maybe_run_cleanup()
    try:
        messages = parse_webhook_payload(payload)
        for msg in messages:
            message_id = msg.get("message_id", "")
            if not message_id or state_registry.wa_has_been_processed(message_id):
                if message_id:
                    log("webhook_duplicate_skipped", ...)
                continue
            state_registry.wa_mark_as_processed(message_id)
            log("whatsapp_message_normalized", **msg)
            if msg.get("text") is None:
                log("whatsapp_non_text_skipped", ...)
                continue
            reply_text = handle_incoming_whatsapp_message(msg)
            if reply_text:
                state_registry.wa_store_message(msg["from"], "user", msg["text"])
                send_text_message(to=msg["from"], text=reply_text)
                state_registry.wa_store_message(msg["from"], "assistant", reply_text)
    except Exception as e:
        log("webhook_process_error", ...)
```

### Rate limit constant (social_agent.py line 32)
```python
_MAX_REPLIES_PER_HOUR = 25
```

### Debounce parameters
- `_DEBOUNCE_SECONDS = 2.0` — window resets on each new message
- `_MAX_BATCH_SECONDS = 5.0` — hard cap, process whatever we have
- Messages concatenated with `\n` separator
- Use last message's metadata (from, from_name) for the combined message
- Non-text messages filtered before buffering
- Dedup (wa_mark_as_processed) at buffer-add time, not flush time

## Instructions

### Step 1 — Update rate limit in social_agent.py
Change line 32:
```python
_MAX_REPLIES_PER_HOUR = 25
```
to:
```python
_MAX_REPLIES_PER_HOUR = 50
```

Update header to `Last modified: Brief 076`.

### Step 2 — Add debounce to webhook_server.py

Add `import threading` to the imports.

Add debounce constants and state after the `_last_cleanup_ts = 0` line:

```python
_DEBOUNCE_SECONDS = 2.0
_MAX_BATCH_SECONDS = 5.0

_message_buffers = {}   # phone -> {"messages": [...], "timer": Timer, "started": float}
_buffer_lock = threading.Lock()
```

Replace `_process_whatsapp_event` with a two-phase approach:

**Phase 1 — `_process_whatsapp_event` becomes buffer-add only:**
```python
def _process_whatsapp_event(payload: dict):
    """Background task: parse messages, dedup, buffer for debounce."""
    _maybe_run_cleanup()
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
            # Only buffer text messages
            if msg.get("text") is None:
                log("whatsapp_non_text_skipped", source="meta_whatsapp",
                    message_type=msg.get("message_type"), message_id=message_id)
                continue
            _buffer_message(msg)
    except Exception as e:
        log("webhook_process_error", source="meta_whatsapp", error=str(e))
```

**Phase 2 — Buffer + flush functions:**
```python
def _buffer_message(msg):
    """Add message to per-phone debounce buffer. Schedule flush after window."""
    phone = msg["from"]
    now = time.time()
    with _buffer_lock:
        if phone not in _message_buffers:
            _message_buffers[phone] = {
                "messages": [],
                "timer": None,
                "started": now,
            }
        buf = _message_buffers[phone]
        buf["messages"].append(msg)
        log("whatsapp_message_buffered", phone=phone,
            buffered_count=len(buf["messages"]))

        # Cancel existing timer
        if buf["timer"] is not None:
            buf["timer"].cancel()

        # Calculate delay: min of debounce window or remaining hard cap
        elapsed = now - buf["started"]
        remaining_cap = max(0.1, _MAX_BATCH_SECONDS - elapsed)
        delay = min(_DEBOUNCE_SECONDS, remaining_cap)

        buf["timer"] = threading.Timer(delay, _flush_buffer, args=[phone])
        buf["timer"].daemon = True
        buf["timer"].start()


def _flush_buffer(phone):
    """Flush buffered messages: concatenate texts, process as single message."""
    with _buffer_lock:
        buf = _message_buffers.pop(phone, None)
    if not buf or not buf["messages"]:
        return
    messages = buf["messages"]
    # Concatenate all text messages
    texts = [m["text"] for m in messages if m.get("text")]
    combined_text = "\n".join(texts)
    # Use last message's metadata
    final_msg = messages[-1].copy()
    final_msg["text"] = combined_text
    batched_count = len(messages)
    if batched_count > 1:
        log("whatsapp_batch_flushed", phone=phone, count=batched_count,
            combined_length=len(combined_text))
    try:
        reply_text = handle_incoming_whatsapp_message(final_msg)
        if reply_text:
            state_registry.wa_store_message(phone, "user", combined_text)
            send_text_message(to=phone, text=reply_text)
            state_registry.wa_store_message(phone, "assistant", reply_text)
    except Exception as e:
        log("webhook_process_error", source="meta_whatsapp", error=str(e),
            phone=phone)
```

### Step 3 — Update webhook_server.py header
```
# Last modified: Brief 076
```

### Step 4 — Create `tests/social/test_076_debounce.py`

```python
# bluemarlin/tests/social/test_076_debounce.py
# Created: Brief 076
# Purpose: Tests for WhatsApp message debouncing and rate limit at 50
```

Standard imports + path setup + env vars (same pattern as test_074).

Import debounce internals from webhook_server:
```python
from agents.social.webhook_server import (
    _buffer_message, _flush_buffer, _message_buffers, _buffer_lock,
)
```

**Cleanup fixture** — required to prevent timer thread leaks between tests:
```python
@pytest.fixture(autouse=True)
def cleanup_buffers():
    """Cancel all active timers and clear buffers before and after each test."""
    def _clear():
        with _buffer_lock:
            for phone, buf in list(_message_buffers.items()):
                if buf.get("timer") is not None:
                    buf["timer"].cancel()
            _message_buffers.clear()
    _clear()
    yield
    _clear()
```

**Test 1: Single message flushes after debounce window**
- Mock `handle_incoming_whatsapp_message` and `send_text_message` (both from `agents.social.webhook_server`)
- Call `_buffer_message({"from": phone, "text": "hello", "from_name": "Test", "message_type": "text"})`
- Assert `phone in _message_buffers` and buffer has 1 message
- Cancel timer via `_message_buffers[phone]["timer"].cancel()`, then call `_flush_buffer(phone)` directly
- Assert `handle_incoming_whatsapp_message` called once with text="hello"
- Assert `phone not in _message_buffers`

**Test 2: Rapid-fire messages batched into one**
- Mock same
- Call `_buffer_message` 3 times in quick succession for same phone:
  - `{"from": phone, "text": "book snorkeling", ...}`
  - `{"from": phone, "text": "for 4 people", ...}`
  - `{"from": phone, "text": "march 27", ...}`
- Cancel timer: `with _buffer_lock: _message_buffers[phone]["timer"].cancel()`
- Call `_flush_buffer(phone)` manually
- Assert `handle_incoming_whatsapp_message` called once
- Assert the combined text is `"book snorkeling\nfor 4 people\nmarch 27"`

**Test 3: Different phones don't batch together**
- Mock same
- Buffer message from phone_A ("hello")
- Buffer message from phone_B ("hi there")
- Cancel both timers under lock, flush phone_A, flush phone_B
- Assert `handle_incoming_whatsapp_message` called twice
- First call text = "hello", second call text = "hi there"

**Test 4: Flush with empty buffer is no-op**
- Call `_flush_buffer("NONEXISTENT_PHONE")`
- Assert `handle_incoming_whatsapp_message` not called

**Test 5: Rate limit at 50 blocks**
- Same pattern as test_074 test 5 but with `range(50)` reply_times
- Assert reply == "" and mock_process.call_count == 0

**Test 6: Rate limit at 49 allows**
- Same pattern as test_074 test 6 but with `range(49)` reply_times
- Assert reply != "" and mock_process.call_count == 1

**Test 7: Batched message stores combined text in thread history**
- Mock `handle_incoming_whatsapp_message` (from `agents.social.webhook_server`) to return "Got it!"
- Mock `send_text_message` (from `agents.social.webhook_server`)
- Mock `state_registry.wa_store_message` (from `agents.social.webhook_server`)
- Buffer 2 messages, cancel timer, flush
- Assert `wa_store_message` called with combined text "msg1\nmsg2" for user role

### Regression note: test_067 is safe
test_067's POST test sends `{"changes": []}` — `parse_webhook_payload` returns an empty list, so `_buffer_message` is never called and no timers start. No changes needed to test_067.

### Step 5 — Update test_072 anti-loop tests
Three tests use `range(25)` for reply_times. Update to `range(50)`:
- `test_anti_loop_blocks_after_limit`
- `test_anti_loop_allows_after_window`
- `test_anti_loop_blocks_fully_escalated`
Also update the comment from `# 25 timestamps` to `# 50 timestamps`.

### Step 6 — Update test_074 rate limit tests
- `test_rate_limit_25_blocks`: change `range(25)` to `range(50)`, update docstring "25 reply_times" → "50 reply_times"
- `test_rate_limit_24_allows`: change `range(24)` to `range(49)`, update docstring "24 reply_times" → "49 reply_times"

## Tests
Run:
```
cd bluemarlin && python3 -m pytest tests/social/test_076_debounce.py -v
cd bluemarlin && python3 -m pytest tests/social/ -v   # full regression
```

Expected: 7/7 new tests pass, all existing social tests pass with updated rate limit values.

## Success Condition
Rapid-fire messages from the same phone are batched into a single Claude call. Rate limit is 50/hr. All tests pass.

## Rollback
Revert webhook_server.py (remove debounce, restore `_process_whatsapp_event`). Revert social_agent.py rate limit to 25. Delete test_076. Revert test_072 and test_074 rate limit values.
