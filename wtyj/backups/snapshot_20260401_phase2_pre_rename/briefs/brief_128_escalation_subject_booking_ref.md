# BRIEF 128 — Better Escalation Subject + Ask for Booking Ref
**Status:** Draft | **Depends on:** Brief 126 | **Blocks:** —

**Backend files:**
- `bluemarlin/agents/marina/marina_agent.py`
- `bluemarlin/agents/social/social_agent.py`

## Context
Two issues with the full escalation flow:

1. **Escalation subject is too vague.** Currently: `[ESCALATION] NO-REF - Calvin Adamus (WhatsApp: 59996881585) - complaint`. The dashboard's `cleanSubject()` strips it to just "Complaint". The `internal_note` field from Marina's response has better context (e.g. "Customer reports rude crew, wants refund") but isn't used in the subject.

2. **Booking ref not collected.** The prompt says "Do NOT ask for booking details." Marina should ask for the booking reference on WhatsApp before escalating (same flow as email collection). If the customer doesn't have it, escalate anyway.

## Why This Approach
Both are prompt changes + one small code change in social_agent.py. No new endpoints, no frontend changes. The `cleanSubject()` function in Escalations.tsx already parses the last ` - ` segment — if we put `internal_note` there, the dashboard automatically shows it as the reason.

## Source Material

### Change 1 — marina_agent.py: Update escalation prompt (lines 259-268)

Current (lines 259-268):
```
WHATSAPP CHANNEL: Check if an email address is in the collected fields.
- IF email IS in fields: set requires_human to true. Acknowledge warmly
  and tell them the team will reach out at their email.
- IF email is NOT in fields: do NOT set requires_human yet. Instead:
  - Acknowledge warmly
  - Ask for their email so the team can follow up
  - Set needs_escalation_email to true in flags
  - Do NOT promise an email will come yet

In both cases: do NOT ask for booking details, do NOT attempt to resolve.
```

Replace with:
```
WHATSAPP CHANNEL: Check if an email address is in the collected fields.
- IF email IS in fields: set requires_human to true. Acknowledge warmly
  and tell them the team will reach out at their email. If no booking_ref
  is in fields, also ask "Could you share your booking reference if you
  have one? It helps us look into this faster." but do NOT block the
  escalation on it.
- IF email is NOT in fields: do NOT set requires_human yet. Instead:
  - Acknowledge warmly
  - Ask for their email so the team can follow up
  - Also ask for their booking reference if they have one
  - Set needs_escalation_email to true in flags
  - Do NOT promise an email will come yet

In both cases: do NOT attempt to resolve the issue yourself.
```

### Change 2 — social_agent.py: Use internal_note in escalation subject (line 597-599)

Current:
```python
        _esc_subject = (
            f"[ESCALATION] {_esc_ref} - {_cname} "
            f"(WhatsApp: {phone}) - {_esc_intents}")
```

Replace with:
```python
        _esc_note = result.get("internal_note", "").strip()
        _esc_summary = _esc_note if _esc_note else _esc_intents
        _esc_subject = (
            f"[ESCALATION] {_esc_ref} - {_cname} "
            f"(WhatsApp: {phone}) - {_esc_summary}")
```

This way `cleanSubject()` on the dashboard will show "Customer reports rude crew, wants refund" instead of just "complaint".

## Tests

**Test file:** `bluemarlin/tests/social/test_128_escalation_subject.py`

```python
# test_128_escalation_subject.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from unittest.mock import patch, MagicMock
from agents.social.social_agent import handle_incoming_whatsapp_message
from shared import state_registry


def _cleanup(phone):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (phone,))
    conn.commit()
    conn.close()


# --- Test 1: Escalation subject uses internal_note ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_escalation_subject_uses_internal_note(mock_process, mock_sheets):
    phone = "128_subject_test"
    _cleanup(phone)
    # Pre-set email so escalation fires immediately
    state_registry.wa_save_booking_state(phone,
        {"customer_name": "Test", "email": "test@test.com"}, {})

    mock_process.return_value = {
        "intents": ["complaint"],
        "fields": {},
        "confidence": "high",
        "reply": "I'm so sorry to hear that. The team will reach out.",
        "requires_human": True,
        "clarifications_needed": [],
        "flags": {},
        "internal_note": "Customer reports rude crew member during sunset cruise, wants full refund",
    }
    msg = {"from": phone, "text": "The crew was rude I want a refund", "from_name": "Test"}
    handle_incoming_whatsapp_message(msg)

    escs = state_registry.get_all_escalations()
    esc = next((e for e in escs if e["customer_id"] == phone), None)
    assert esc is not None
    # Subject should contain the internal_note, not just "complaint"
    assert "rude crew" in esc["subject"].lower()
    assert "refund" in esc["subject"].lower()
    _cleanup(phone)


# --- Test 2: Fallback to intents when internal_note is empty ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_escalation_subject_falls_back_to_intents(mock_process, mock_sheets):
    phone = "128_fallback_test"
    _cleanup(phone)
    state_registry.wa_save_booking_state(phone,
        {"customer_name": "Test", "email": "test@test.com"}, {})

    mock_process.return_value = {
        "intents": ["complaint", "refund"],
        "fields": {},
        "confidence": "high",
        "reply": "I'm sorry. The team will follow up.",
        "requires_human": True,
        "clarifications_needed": [],
        "flags": {},
        "internal_note": "",
    }
    msg = {"from": phone, "text": "This is terrible", "from_name": "Test"}
    handle_incoming_whatsapp_message(msg)

    escs = state_registry.get_all_escalations()
    esc = next((e for e in escs if e["customer_id"] == phone), None)
    assert esc is not None
    # Should fall back to intents
    assert "complaint" in esc["subject"].lower()
    _cleanup(phone)


# --- Test 3: Prompt includes booking ref instruction ---
def test_prompt_mentions_booking_reference():
    from agents.marina.marina_agent import _build_prompt
    prompt = _build_prompt("test@test.com", "Test", "Hello",
                           {}, {}, channel="whatsapp", messages=[])
    assert "booking reference" in prompt.lower()
```

## Success Condition
Escalation subject in dashboard shows Marina's internal note (descriptive context like "rude crew, wants refund") instead of just "complaint". Marina asks for booking ref during escalation collection on WhatsApp. Falls back to intents when internal_note is empty.

## Rollback
Revert marina_agent.py and social_agent.py. Delete test file.
