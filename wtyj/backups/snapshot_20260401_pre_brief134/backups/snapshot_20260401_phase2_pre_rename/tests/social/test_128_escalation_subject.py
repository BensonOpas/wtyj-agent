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
    assert "complaint" in esc["subject"].lower()
    _cleanup(phone)


# --- Test 3: Prompt includes booking ref instruction ---
def test_prompt_mentions_booking_reference():
    from agents.marina.marina_agent import _build_prompt
    prompt = _build_prompt("test@test.com", "Test", "Hello",
                           {}, {}, channel="whatsapp", messages=[])
    assert "booking reference" in prompt.lower()
