# BRIEF 083 — Use WhatsApp Profile Name in Escalation Notifications
**Status:** Approved | **Files:** `agents/social/social_agent.py` | **Depends on:** 082 | **Blocks:** —

## Context
Relay and escalation emails show `Customer: Unknown` even when Marina greets the customer by name in the same conversation. Marina knows the name from the WhatsApp profile metadata (`from_name`), but the notification uses `fields.get("customer_name", "Unknown")` — the booking state field. For FAQ questions with no booking flow, `customer_name` is never extracted into fields, so it defaults to "Unknown".

## Why This Approach
The `from_name` variable is already in scope (line 219 of social_agent.py). Using it as a fallback when `customer_name` isn't in the booking fields is a one-line change per handler. No new data flow needed.

## Source Material

### Semi-escalation handler — line 500
```python
        _cname = fields.get("customer_name", "Unknown")
```

### Full escalation handler — line 545
```python
        _cname = fields.get("customer_name", "Unknown")
```

### `from_name` definition — line 219
```python
    from_name = message.get("from_name", "")
```

## Instructions

### Step 1 — Fix semi-escalation handler (line 500)

Change:
```python
        _cname = fields.get("customer_name", "Unknown")
```
to:
```python
        _cname = fields.get("customer_name") or from_name or "Unknown"
```

### Step 2 — Fix full escalation handler (line 545)

Same change:
```python
        _cname = fields.get("customer_name", "Unknown")
```
to:
```python
        _cname = fields.get("customer_name") or from_name or "Unknown"
```

## Tests

Add one new test in `tests/social/test_077_relay_bridge.py` after `test_booking_decline_with_booking_intent_no_loop`:

```python
# --- Test 2e: Relay notification uses WhatsApp profile name ---

@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_relay_notification_uses_profile_name(mock_process, mock_sheets):
    """When customer_name not in fields, relay notification uses WhatsApp profile name."""
    phone = "TEST_083_NAME_001"
    _cleanup_phone(phone)
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="Let me check with the team!",
        semi_escalation=True,
        relay_question="Is there shade on the boat?",
    )
    # from_name set, but no customer_name in fields
    msg = {"from": phone, "text": "Is there shade?", "from_name": "Jan de Vries"}
    handle_incoming_whatsapp_message(msg)
    pending = state_registry.get_pending_notifications()
    match = [p for p in pending if p["customer_id"] == phone]
    assert len(match) == 1
    assert "Jan de Vries" in match[0]["subject"]
    assert "Jan de Vries" in match[0]["body"]
    assert "Unknown" not in match[0]["subject"]
    _cleanup_phone(phone)
```

Run:
```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin && python3 -m pytest tests/social/test_077_relay_bridge.py -v
```

Expected: 12/12 pass (11 existing + 1 new).

Full regression:
```bash
python3 -m pytest tests/social/ -q
```

Expected: 104/104 pass.

## Success Condition
All 104 tests pass. `test_relay_notification_uses_profile_name` confirms relay email shows "Jan de Vries" instead of "Unknown" when `customer_name` is not in booking fields.

## Rollback
Revert two lines in social_agent.py.
