# BRIEF 089 — Store User Message Before Processing
**Status:** Approved | **Files:** `agents/social/webhook_server.py` | **Depends on:** 088 | **Blocks:** —

## Context
In webhook_server.py, the user's message is only stored in conversation history if Marina replies. When Marina returns empty (dropped messages), the customer's message is never recorded. Next Claude call sees conversation history with missing messages — context is lost. This explains why after a dropped message, Marina sometimes responds as if the customer never said anything.

## Why This Approach
Move `wa_store_message(phone, "user", combined_text)` out of the `if reply_text:` block to run unconditionally AFTER processing. It must stay AFTER `handle_incoming_whatsapp_message` — not before — because `social_agent.py` reads conversation history via `wa_get_history()` during processing. Storing before would duplicate the current message in Claude's prompt (once in CONVERSATION HISTORY, once in INBOUND MESSAGE). The assistant reply stays inside the conditional — we only store replies that are actually sent.

## Source Material

### webhook_server.py lines 139-147 (current)
```python
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

## Instructions

### Step 1 — Store user message unconditionally after processing

Replace lines 139-147:
```python
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
with:
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

### Step 2 — Update file header

Change line 3:
```python
# Last modified: Brief 076
```
to:
```python
# Last modified: Brief 089
```

## Tests

Run unit regression:
```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin && python3 -m pytest tests/social/ -q
```

Expected: 104/104 pass.

Add a test in `tests/social/test_077_relay_bridge.py` before the `# --- Test 3` line:

```python
# --- Test 2f: User message stored even when reply is empty ---

def test_user_message_stored_on_empty_reply():
    """_flush_buffer stores user message even if handle returns empty reply."""
    from unittest.mock import patch as _p, MagicMock
    phone = "TEST_089_STORE_001"
    _cleanup_phone(phone)
    with _p("agents.social.webhook_server.handle_incoming_whatsapp_message", return_value="") as mock_handle, \
         _p("agents.social.webhook_server.send_text_message") as mock_send:
        from agents.social.webhook_server import _flush_buffer
        # Simulate a buffer with one message
        from agents.social import webhook_server
        webhook_server._message_buffers[phone] = {
            "messages": [{"from": phone, "text": "lost message", "from_name": "Test",
                          "message_id": "test_089"}],
            "timer": None,
            "started": 0,
        }
        _flush_buffer(phone)
    # Reply was empty — send should NOT be called
    mock_send.assert_not_called()
    # But user message MUST be stored in history
    history = state_registry.wa_get_history(phone, limit=10)
    user_msgs = [m for m in history if m["role"] == "user"]
    assert len(user_msgs) == 1
    assert "lost message" in user_msgs[0]["text"]
    _cleanup_phone(phone)
```

Run:
```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin && python3 -m pytest tests/social/test_077_relay_bridge.py -v
```

Expected: 13/13 pass (12 existing + 1 new).

Full regression:
```bash
python3 -m pytest tests/social/ -q
```

Expected: 105/105 pass.

## Success Condition
All 105 tests pass. `test_user_message_stored_on_empty_reply` proves that a message getting an empty reply is still stored in conversation history.

## Rollback
Move `wa_store_message` back inside the `if reply_text:` block.
