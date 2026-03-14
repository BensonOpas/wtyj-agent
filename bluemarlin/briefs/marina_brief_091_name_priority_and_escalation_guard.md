# BRIEF 091 — Name Priority + Smarter Escalation Guard
**Status:** Approved | **Files:** `agents/social/social_agent.py`, `agents/marina/marina_agent.py` | **Depends on:** 090 | **Blocks:** —

## Context
Two UX issues from SR's live WhatsApp testing:

1. **Name confusion.** SR said "John here" but Marina later called him "Calvin" (WhatsApp profile name). The `from_id` always uses `from_name` (WhatsApp profile) even when `customer_name` has been extracted from the conversation. Claude sees both and picks inconsistently.

2. **Escalated guard blocks all questions.** After full escalation, SR asked "what time is the office open on monday" — a simple factual question. Marina gave "team will be in touch" because the prompt says "send a warm, brief holding message only." The guard is too aggressive — it should still answer factual questions from the available data. This change applies to both WhatsApp and email channels (shared `_build_system_prompt`) — the same improvement is desired on both channels.

## Why This Approach
Fix 1: Use `fields.get("customer_name")` when available, fall back to `from_name`. Once Claude extracts the customer's stated name, all subsequent messages use it. Universal — works for any client, any industry.

Fix 2: Change the escalated prompt to allow factual answers from CLIENT DATA while maintaining the escalation for the original issue. Uses "CLIENT DATA" (the dynamic section from Brief 090) instead of business-specific terms like "trips" or "FAQ" — scalable to any client.

## Source Material

### social_agent.py line 247
```python
    from_id = f"{phone} ({from_name})" if from_name else phone
```

### marina_agent.py lines 109-115
```python
    if thread_flags.get("fully_escalated"):
        fully_escalated_section = (
            "\nFULLY ESCALATED THREAD: This conversation has already been passed to the human team. "
            "Send a warm, brief holding message only. Acknowledge the customer warmly. "
            "Remind them the team will be in touch soon. Do not restart the booking process. "
            "Do not ask for information. Do not set any booking or escalation flags.\n"
        )
```

## Instructions

### Step 1 — Name priority in social_agent.py

Change line 247 from:
```python
    from_id = f"{phone} ({from_name})" if from_name else phone
```
to:
```python
    display_name = fields.get("customer_name") or from_name
    from_id = f"{phone} ({display_name})" if display_name else phone
```

### Step 2 — Smarter escalation guard in marina_agent.py

Change lines 109-115 from:
```python
    if thread_flags.get("fully_escalated"):
        fully_escalated_section = (
            "\nFULLY ESCALATED THREAD: This conversation has already been passed to the human team. "
            "Send a warm, brief holding message only. Acknowledge the customer warmly. "
            "Remind them the team will be in touch soon. Do not restart the booking process. "
            "Do not ask for information. Do not set any booking or escalation flags.\n"
        )
```
to:
```python
    if thread_flags.get("fully_escalated"):
        fully_escalated_section = (
            "\nFULLY ESCALATED THREAD: The original issue has been passed to the human team. "
            "If the customer asks a new factual question, answer it normally from the "
            "available CLIENT DATA. If they ask about the escalated issue (complaint, "
            "refund, status update), remind them the team will be in touch. "
            "Do not restart the booking process. Do not set any booking or escalation flags.\n"
        )
```

### Step 3 — Update file headers

- social_agent.py: `# Last modified: Brief 091`
- marina_agent.py: `# Last modified: Brief 091`

## Tests

Add two tests in `tests/social/test_077_relay_bridge.py` before `# --- Test 3`:

```python
# --- Test 2g: from_id uses customer_name over WhatsApp profile ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_from_id_uses_customer_name(mock_process):
    """from_id should use extracted customer_name over WhatsApp profile name."""
    phone = "TEST_091_NAME_001"
    _cleanup_phone(phone)
    # Pre-set customer_name in booking state
    state_registry.wa_save_booking_state(phone,
        {"customer_name": "John"}, {})
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="Hey John!",
    )
    msg = {"from": phone, "text": "hello", "from_name": "Calvin Profile"}
    handle_incoming_whatsapp_message(msg)
    # marina_agent should have been called with "John" in from_email, not "Calvin Profile"
    call_args = mock_process.call_args
    from_email_arg = call_args.kwargs.get("from_email", "")
    assert "John" in from_email_arg
    assert "Calvin Profile" not in from_email_arg
    _cleanup_phone(phone)


# --- Test 2h: Escalated guard prompt allows factual questions ---

def test_escalated_prompt_allows_factual():
    """Escalated prompt should mention answering factual questions from CLIENT DATA."""
    from agents.marina import marina_agent as ma
    prompt = ma._build_system_prompt({"fully_escalated": True}, channel="whatsapp")
    assert "factual question" in prompt.lower()
    assert "CLIENT DATA" in prompt
    # Should NOT say "holding message only"
    assert "holding message only" not in prompt
```

Run:
```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin && python3 -m pytest tests/social/test_077_relay_bridge.py -v && python3 -m pytest tests/social/ -q && python3 -m pytest tests/marina/test_marina_tone.py -q
```

Expected: 15/15 relay + 107/107 social + 18/18 marina.

## Success Condition
All tests pass. `test_from_id_uses_customer_name` proves extracted name takes priority. `test_escalated_prompt_allows_factual` proves the escalated prompt allows factual answers.

## Rollback
Revert one line in social_agent.py and the prompt block in marina_agent.py. Remove two tests.
