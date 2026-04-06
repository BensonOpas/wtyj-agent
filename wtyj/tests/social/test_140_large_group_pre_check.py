# test_140_large_group_pre_check.py — Large Group Pre-Check
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test")

from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from shared import state_registry, config_loader


def _cleanup(phone):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (phone,))
    conn.commit()
    conn.close()


def _next_fri():
    today = datetime.now(timezone.utc).date()
    d = today + timedelta(days=1)
    while d.weekday() != 4:
        d += timedelta(days=1)
    return d.isoformat()


def _setup_state(phone, guests, date=None, service_key="sunset_cruise"):
    """Set up state with awaiting_booking_confirmation=True, slot_checked=False."""
    if date is None:
        date = _next_fri()
    fields = {
        "service_key": service_key,
        "service_name": "Sunset Cruise",
        "date": date,
        "guests": str(guests),
        "slot_time": "17:30",
        "customer_name": "Test User",
    }
    flags = {"awaiting_booking_confirmation": True, "slot_checked": False}
    state_registry.wa_save_booking_state(phone, fields, flags)


def _marina_result(reply_text="Sounds great, let me check on that!"):
    return {
        "intents": ["booking"], "fields": {}, "confidence": "high",
        "reply": reply_text,
        "reply_hold_failed": "", "clarifications_needed": [],
        "requires_human": False, "flags": {},
        "internal_note": ""
    }


# --- Test 1: Large group exceeds capacity → escalation ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wa_large_group_exceeds_capacity_escalates(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "140_large_group"
    _cleanup(phone)
    _setup_state(phone, guests=200)

    mock_process.return_value = _marina_result("Sounds great, let me check on that!")

    try:
        msg = {"from": phone, "text": "Yes let's do it", "from_name": "Test User"}
        reply = handle_incoming_whatsapp_message(msg)

        # Escalation created
        escs = state_registry.get_all_escalations()
        lg_escs = [e for e in escs if e["customer_id"] == phone and "[LARGE GROUP]" in e["subject"]]
        assert len(lg_escs) >= 1, f"Expected large group escalation, got {len(lg_escs)}"
        assert "200" in lg_escs[0]["subject"]
        assert "exceeds" in lg_escs[0]["subject"]

        # Flags set correctly
        state = state_registry.wa_get_booking_state(phone)
        assert state["flags"].get("awaiting_booking_confirmation") is False
        assert state["flags"].get("slot_available") is False

        # Availability NOT checked (skipped)
        mock_cal.check_availability.assert_not_called()

        # Reply is Marina's original, not booking summary or "fully booked"
        assert "Sounds great" in reply
        assert "Unfortunately" not in reply
        assert "fully booked" not in reply.lower()
    finally:
        _cleanup(phone)


# --- Test 2: Normal group → availability checked (regression) ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wa_normal_group_checks_availability(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "140_normal"
    _cleanup(phone)
    _setup_state(phone, guests=4)

    mock_process.return_value = _marina_result()
    mock_cal.check_availability.return_value = {"available": True, "spots_remaining": 16, "capacity": 20}

    try:
        msg = {"from": phone, "text": "Sounds good", "from_name": "Test User"}
        handle_incoming_whatsapp_message(msg)

        # Availability IS checked
        mock_cal.check_availability.assert_called_once()
    finally:
        _cleanup(phone)


# --- Test 3: Group exactly at capacity → normal check ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wa_group_at_capacity_checks_normally(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "140_at_cap"
    _cleanup(phone)
    _setup_state(phone, guests=20)  # sunset_cruise capacity is 20

    mock_process.return_value = _marina_result()
    mock_cal.check_availability.return_value = {"available": True, "spots_remaining": 0, "capacity": 20}

    try:
        msg = {"from": phone, "text": "Go for it", "from_name": "Test User"}
        handle_incoming_whatsapp_message(msg)

        # At capacity (not over) → normal availability check
        mock_cal.check_availability.assert_called_once()
    finally:
        _cleanup(phone)


# --- Test 4: One over capacity → escalation ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wa_group_one_over_escalates(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "140_one_over"
    _cleanup(phone)
    _setup_state(phone, guests=21)  # sunset_cruise capacity is 20

    mock_process.return_value = _marina_result()

    try:
        msg = {"from": phone, "text": "Book it", "from_name": "Test User"}
        handle_incoming_whatsapp_message(msg)

        escs = state_registry.get_all_escalations()
        lg_escs = [e for e in escs if e["customer_id"] == phone and "[LARGE GROUP]" in e["subject"]]
        assert len(lg_escs) >= 1, f"Expected escalation for 21 guests, got {len(lg_escs)}"
        mock_cal.check_availability.assert_not_called()
    finally:
        _cleanup(phone)


# --- Test 5: Reply is Marina's original, not booking summary ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wa_large_group_reply_is_not_booking_summary(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "140_reply_check"
    _cleanup(phone)
    _setup_state(phone, guests=50)

    mock_process.return_value = _marina_result("Hey, I can help with the sunset cruise!")

    try:
        msg = {"from": phone, "text": "50 of us want sunset cruise friday", "from_name": "Test User"}
        reply = handle_incoming_whatsapp_message(msg)

        # Reply should be Marina's original conversational text
        assert "I can help" in reply, f"Expected Marina's original reply, got: {reply[:200]}"
        # NOT the post-validate booking summary
        assert "Just to confirm" not in reply
        assert "$" not in reply  # no price in original reply
    finally:
        _cleanup(phone)
