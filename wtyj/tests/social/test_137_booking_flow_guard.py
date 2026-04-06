# test_137_booking_flow_guard.py
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


def _next_wed():
    today = datetime.now(timezone.utc).date()
    d = today + timedelta(days=1)
    while d.weekday() != 2:
        d += timedelta(days=1)
    return d.isoformat()


# --- Test 1: No soft hold when booking_flow OFF ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wa_no_soft_hold_when_flow_off(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "137_no_hold"
    _cleanup(phone)
    date = _next_wed()

    # Set up state that would normally trigger Step 7 (availability + hold)
    fields = {"service_key": "west_coast_beach", "service_name": "West Coast Beach",
              "date": date, "guests": "2", "slot_time": "09:00", "customer_name": "Test"}
    flags = {"awaiting_booking_confirmation": True, "slot_checked": False}
    state_registry.wa_save_booking_state(phone, fields, flags)

    mock_process.return_value = {
        "intents": ["booking"], "fields": {}, "confidence": "high",
        "reply": "I can help you book!",
        "reply_hold_failed": "", "clarifications_needed": [],
        "requires_human": False,
        "flags": {"booking_confirmed": True},
        "internal_note": "wants to book"
    }

    # Turn booking flow OFF
    raw = config_loader._cache
    original = raw.get("features", {}).get("booking_flow", True)
    raw.setdefault("features", {})["booking_flow"] = False
    try:
        msg = {"from": phone, "text": "Yes book it!", "from_name": "Test"}
        handle_incoming_whatsapp_message(msg)

        # check_availability should NOT have been called (Step 7 skipped)
        mock_cal.check_availability.assert_not_called()
        # Manifest should NOT have been called (Step 8 skipped)
        mock_cal.create_or_update_manifest.assert_not_called()
        # Escalation SHOULD have been created
        escs = state_registry.get_all_escalations()
        booking_escs = [e for e in escs if e["customer_id"] == phone and "BOOKING REQUEST" in e["subject"]]
        assert len(booking_escs) >= 1, f"Expected escalation, got {len(booking_escs)}"
    finally:
        raw["features"]["booking_flow"] = original
        _cleanup(phone)


# --- Test 2: Soft hold works when booking_flow ON (regression) ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wa_soft_hold_works_when_flow_on(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "137_hold_on"
    _cleanup(phone)
    date = _next_wed()

    fields = {"service_key": "west_coast_beach", "service_name": "West Coast Beach",
              "date": date, "guests": "2", "slot_time": "09:00", "customer_name": "Test"}
    flags = {"awaiting_booking_confirmation": True, "slot_checked": False}
    state_registry.wa_save_booking_state(phone, fields, flags)

    # Marina returns inquiry (not confirming yet) — this triggers Step 7
    mock_process.return_value = {
        "intents": ["booking"], "fields": {}, "confidence": "high",
        "reply": "Looking great, want me to book?",
        "reply_hold_failed": "", "clarifications_needed": [],
        "requires_human": False,
        "flags": {},  # No booking_confirmed — just checking availability
        "internal_note": ""
    }
    mock_cal.check_availability.return_value = {"available": True, "spots_remaining": 20, "capacity": 25}

    msg = {"from": phone, "text": "Sounds good", "from_name": "Test"}
    handle_incoming_whatsapp_message(msg)

    # check_availability SHOULD have been called (Step 7)
    mock_cal.check_availability.assert_called_once()
    _cleanup(phone)


# --- Test 3: awaiting_booking_confirmation NOT set when flow OFF ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wa_no_awaiting_flag_when_flow_off(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "137_no_await"
    _cleanup(phone)

    # Empty state — no awaiting flag
    state_registry.wa_save_booking_state(phone, {"service_name": "Test"}, {})

    mock_process.return_value = {
        "intents": ["booking"], "fields": {"service_name": "Test", "date": "2026-12-25", "guests": "2"},
        "confidence": "high",
        "reply": "Here's what I've got...",
        "reply_hold_failed": "", "clarifications_needed": [],
        "requires_human": False,
        "flags": {},
        "internal_note": ""
    }

    raw = config_loader._cache
    original = raw.get("features", {}).get("booking_flow", True)
    raw.setdefault("features", {})["booking_flow"] = False
    try:
        msg = {"from": phone, "text": "I want to book for Christmas", "from_name": "Test"}
        handle_incoming_whatsapp_message(msg)

        state = state_registry.wa_get_booking_state(phone)
        # awaiting_booking_confirmation should NOT be set
        assert not state["flags"].get("awaiting_booking_confirmation"), \
            f"awaiting_booking_confirmation should not be set when booking_flow is OFF"
    finally:
        raw["features"]["booking_flow"] = original
        _cleanup(phone)
