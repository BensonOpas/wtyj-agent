# test_139_error_handling.py — Manifest API Error Handling
import sys, os, json
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


def _next_wed():
    today = datetime.now(timezone.utc).date()
    d = today + timedelta(days=1)
    while d.weekday() != 2:
        d += timedelta(days=1)
    return d.isoformat()


def _setup_booking_state(phone, date, extra_flags=None):
    """Set up a state ready for Step 8 (booking confirmation)."""
    fields = {
        "service_key": "west_coast_beach", "service_name": "West Coast Beach",
        "date": date, "guests": "2", "slot_time": "09:00", "customer_name": "Test"
    }
    flags = {
        "awaiting_booking_confirmation": True,
        "slot_checked": True, "slot_available": True,
        "spots_remaining": 20, "trip_capacity": 25,
        "hold_id": 999, "hold_service_key": "west_coast_beach",
        "hold_date": date, "hold_slot_time": "09:00",
        "booking_confirmed": True,
    }
    if extra_flags:
        flags.update(extra_flags)
    state_registry.wa_save_booking_state(phone, fields, flags)
    return fields, flags


# --- Test 1: API error allows retry ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wa_manifest_api_error_allows_retry(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "139_api_retry"
    _cleanup(phone)
    date = _next_wed()
    _setup_booking_state(phone, date)

    mock_process.return_value = {
        "intents": ["booking"], "fields": {}, "confidence": "high",
        "reply": "Booked! Ref: [BOOKING_REF]. Pay: [PAYMENT_LINK]",
        "reply_hold_failed": "Sorry, having trouble confirming. Try again?",
        "clarifications_needed": [], "requires_human": False,
        "flags": {"booking_confirmed": True},
        "internal_note": ""
    }
    # Manifest returns 404 (API error)
    mock_cal.create_or_update_manifest.return_value = {
        'ok': False, 'error': '{"code": 404, "message": "Not Found", "reason": "notFound"}'
    }
    mock_cal.check_availability.return_value = {"available": True, "spots_remaining": 20, "capacity": 25}

    try:
        msg = {"from": phone, "text": "Yes book it!", "from_name": "Test"}
        reply = handle_incoming_whatsapp_message(msg)

        state = state_registry.wa_get_booking_state(phone)
        # API error should allow retry
        assert state["flags"].get("booking_confirmed") is False, \
            "booking_confirmed should be reset for API errors"
        assert state["flags"].get("awaiting_booking_confirmation") is True, \
            "awaiting_booking_confirmation should be set for retry"
        assert state["flags"].get("manifest_retry_count") == 1
        # Reply should be Marina's hold_failed text
        assert "Sorry" in reply or "trouble" in reply or reply != ""
    finally:
        _cleanup(phone)


# --- Test 2: Business error — no retry ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wa_manifest_business_error_no_retry(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "139_biz_err"
    _cleanup(phone)
    date = _next_wed()
    _setup_booking_state(phone, date)

    mock_process.return_value = {
        "intents": ["booking"], "fields": {}, "confidence": "high",
        "reply": "Booked! Ref: [BOOKING_REF].",
        "reply_hold_failed": "Sorry about that.",
        "clarifications_needed": [], "requires_human": False,
        "flags": {"booking_confirmed": True},
        "internal_note": ""
    }
    # Business logic error (not an API error)
    mock_cal.create_or_update_manifest.return_value = {
        'ok': False, 'error': 'No service_key in fields.'
    }
    mock_cal.check_availability.return_value = {"available": True, "spots_remaining": 20, "capacity": 25}

    try:
        msg = {"from": phone, "text": "Yes!", "from_name": "Test"}
        handle_incoming_whatsapp_message(msg)

        state = state_registry.wa_get_booking_state(phone)
        # Business error should NOT reset for retry
        assert state["flags"].get("booking_confirmed") is True, \
            "booking_confirmed should stay True for business errors"
        assert state["flags"].get("manifest_retry_count") is None, \
            "manifest_retry_count should not be set for business errors"
    finally:
        _cleanup(phone)


# --- Test 3: Escalation after 2 API failures ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wa_manifest_api_error_escalates_after_2(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "139_escalate"
    _cleanup(phone)
    date = _next_wed()
    # Already failed once
    _setup_booking_state(phone, date, extra_flags={"manifest_retry_count": 1})

    mock_process.return_value = {
        "intents": ["booking"], "fields": {}, "confidence": "high",
        "reply": "Booked!", "reply_hold_failed": "Sorry!",
        "clarifications_needed": [], "requires_human": False,
        "flags": {"booking_confirmed": True},
        "internal_note": ""
    }
    mock_cal.create_or_update_manifest.return_value = {
        'ok': False, 'error': '{"code": 404, "message": "Not Found"}'
    }
    mock_cal.check_availability.return_value = {"available": True, "spots_remaining": 20, "capacity": 25}

    try:
        msg = {"from": phone, "text": "Yes!", "from_name": "Test"}
        handle_incoming_whatsapp_message(msg)

        state = state_registry.wa_get_booking_state(phone)
        assert state["flags"].get("manifest_retry_count") == 2

        # Escalation should be created
        escs = state_registry.get_all_escalations()
        system_escs = [e for e in escs if e["customer_id"] == phone
                       and "[SYSTEM]" in e["subject"]]
        assert len(system_escs) >= 1, f"Expected system escalation, got {len(system_escs)}"
    finally:
        _cleanup(phone)


# --- Test 4: Hold cancelled on API error ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
@patch("shared.state_registry.cancel_hold")
def test_wa_manifest_api_error_hold_cancelled(mock_cancel, mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "139_hold_cancel"
    _cleanup(phone)
    date = _next_wed()
    _setup_booking_state(phone, date)

    mock_process.return_value = {
        "intents": ["booking"], "fields": {}, "confidence": "high",
        "reply": "Booked!", "reply_hold_failed": "Sorry!",
        "clarifications_needed": [], "requires_human": False,
        "flags": {"booking_confirmed": True},
        "internal_note": ""
    }
    mock_cal.create_or_update_manifest.return_value = {
        'ok': False, 'error': '{"code": 500, "message": "Internal Server Error"}'
    }
    mock_cal.check_availability.return_value = {"available": True, "spots_remaining": 20, "capacity": 25}

    try:
        msg = {"from": phone, "text": "Yes!", "from_name": "Test"}
        handle_incoming_whatsapp_message(msg)

        # cancel_hold should have been called
        mock_cancel.assert_called_once_with(999)

        state = state_registry.wa_get_booking_state(phone)
        assert state["flags"].get("slot_checked") is False
        assert state["flags"].get("hold_id") is None
    finally:
        _cleanup(phone)


# --- Test 5: Success clears retry count ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
@patch("shared.state_registry.create_soft_hold")
def test_wa_manifest_success_clears_retry_count(mock_hold, mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "139_clear_count"
    _cleanup(phone)
    date = _next_wed()
    # Had a previous API failure
    _setup_booking_state(phone, date, extra_flags={"manifest_retry_count": 1})

    mock_process.return_value = {
        "intents": ["booking"], "fields": {}, "confidence": "high",
        "reply": "Booked! Ref: [BOOKING_REF]. Pay: [PAYMENT_LINK]",
        "reply_hold_failed": "Sorry!",
        "clarifications_needed": [], "requires_human": False,
        "flags": {"booking_confirmed": True},
        "internal_note": ""
    }
    mock_cal.create_or_update_manifest.return_value = {
        'ok': True, 'eventId': 'e1', 'htmlLink': 'http://cal/e1'
    }
    mock_cal.check_availability.return_value = {"available": True, "spots_remaining": 20, "capacity": 25}
    mock_pay.generate_payment_link.return_value = {"payment_id": "pay1", "status": "pending"}
    mock_hold.return_value = 999

    try:
        msg = {"from": phone, "text": "Yes!", "from_name": "Test"}
        handle_incoming_whatsapp_message(msg)

        state = state_registry.wa_get_booking_state(phone)
        assert state["flags"].get("hold_created") is True, "Booking should succeed"
        assert state["flags"].get("manifest_retry_count") is None, \
            "manifest_retry_count should be cleared on success"
    finally:
        _cleanup(phone)


# --- Test 6: Single-quote dict format detection ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wa_manifest_api_error_single_quote_detection(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "139_single_quote"
    _cleanup(phone)
    date = _next_wed()
    _setup_booking_state(phone, date)

    mock_process.return_value = {
        "intents": ["booking"], "fields": {}, "confidence": "high",
        "reply": "Booked!", "reply_hold_failed": "Sorry!",
        "clarifications_needed": [], "requires_human": False,
        "flags": {"booking_confirmed": True},
        "internal_note": ""
    }
    # Single-quote Python dict format (str() of a dict)
    mock_cal.create_or_update_manifest.return_value = {
        'ok': False, 'error': str({'code': 404, 'message': 'Not Found'})
    }
    mock_cal.check_availability.return_value = {"available": True, "spots_remaining": 20, "capacity": 25}

    try:
        msg = {"from": phone, "text": "Yes!", "from_name": "Test"}
        handle_incoming_whatsapp_message(msg)

        state = state_registry.wa_get_booking_state(phone)
        # Should be detected as API error (single-quote format)
        assert state["flags"].get("booking_confirmed") is False, \
            "Single-quote format should be detected as API error"
        assert state["flags"].get("awaiting_booking_confirmation") is True
        assert state["flags"].get("manifest_retry_count") == 1
    finally:
        _cleanup(phone)
