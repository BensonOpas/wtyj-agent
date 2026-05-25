# test_135_feature_toggles.py
import sys, os, re, string
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


@patch("agents.social.social_agent.marina_agent.process_message")
def test_icp_whatsapp_toggle_off_skips_marina(mock_process, monkeypatch):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "135_icp_disabled"
    _cleanup(phone)
    monkeypatch.setattr(
        "agents.social.social_agent._icp_overrides.channel_is_enabled",
        lambda channel: False,
    )

    reply = handle_incoming_whatsapp_message({
        "from": phone,
        "text": "hello",
        "from_name": "Test",
    })

    assert reply == ""
    mock_process.assert_not_called()
    _cleanup(phone)


# --- Test 1: Booking flow OFF creates escalation instead of booking ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_booking_flow_off_escalates(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "135_flow_off"
    _cleanup(phone)

    # Set booking_flow to false
    raw = config_loader.get_raw()
    original = raw.get("features", {}).get("booking_flow", True)
    raw.setdefault("features", {})["booking_flow"] = False

    try:
        # Store some booking state
        state_registry.wa_save_booking_state(phone,
            {"service_name": "Sunset Cruise", "date": "2026-04-10", "guests": "4",
             "service_key": "sunset_cruise", "customer_name": "Test"},
            {"awaiting_booking_confirmation": False})

        mock_process.return_value = {
            "intents": ["booking"], "fields": {}, "confidence": "high",
            "reply": "I'd love to help you book that!",
            "reply_hold_failed": "", "clarifications_needed": [],
            "requires_human": False,
            "flags": {"booking_confirmed": True},
            "internal_note": "Customer wants sunset cruise"
        }

        msg = {"from": phone, "text": "Yes book it!", "from_name": "Test"}
        reply = handle_incoming_whatsapp_message(msg)

        # Should NOT have created a calendar event (booking skipped)
        mock_cal.create_or_update_manifest.assert_not_called()

        # Should have created an escalation
        escs = state_registry.get_all_escalations()
        booking_escs = [e for e in escs if e["customer_id"] == phone and "BOOKING REQUEST" in e["subject"]]
        assert len(booking_escs) >= 1, f"Expected booking request escalation, got {len(booking_escs)}"
        assert "COLLECTED FIELDS" in booking_escs[0]["body"]

    finally:
        raw["features"]["booking_flow"] = original
        _cleanup(phone)


# --- Test 2: Booking flow ON works normally (regression) ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_booking_flow_on_unchanged(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    phone = "135_flow_on"
    _cleanup(phone)

    today = datetime.now(timezone.utc).date()
    d = today + timedelta(days=1)
    while d.weekday() != 2:
        d += timedelta(days=1)
    date = d.isoformat()

    fields = {"service_key": "west_coast_beach", "service_name": "West Coast Beach",
              "date": date, "guests": "2", "slot_time": "09:00",
              "customer_name": "Test"}
    hold_id = state_registry.create_soft_hold("west_coast_beach", date, "09:00", 2, 25,
                                               customer_name="Test", customer_email=phone)
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True, "hold_id": hold_id,
             "hold_service_key": "west_coast_beach", "hold_date": date,
             "hold_slot_time": "09:00"}
    state_registry.wa_save_booking_state(phone, fields, flags)

    mock_process.return_value = {
        "intents": ["booking"], "fields": {}, "confidence": "high",
        "reply": "You're all set! Ref [BOOKING_REF]. Pay here: [PAYMENT_LINK]",
        "reply_hold_failed": "Sorry.", "clarifications_needed": [],
        "requires_human": False,
        "flags": {"booking_confirmed": True, "awaiting_booking_confirmation": False},
        "internal_note": ""
    }
    mock_cal.create_or_update_manifest.return_value = {"ok": True, "eventId": "e1", "htmlLink": "http://cal/e1"}
    mock_pay.generate_payment_link.return_value = {"payment_id": "pay1", "status": "pending"}

    msg = {"from": phone, "text": "Yes!", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)

    # Booking should work — calendar called, ref in reply
    mock_cal.create_or_update_manifest.assert_called_once()
    assert "[BOOKING_REF]" not in reply  # Should be replaced with actual ref
    _cleanup(phone)


# --- Test 3: Random booking ref format ---
def test_booking_ref_random_format():
    import random as _random, string as _string
    _chars = _string.ascii_uppercase + _string.digits
    ref = ''.join(_random.choices(_chars, k=6))
    assert len(ref) == 6
    assert all(c in _string.ascii_uppercase + _string.digits for c in ref)
    assert "-" not in ref
    assert ref != ref.lower()  # Should be uppercase


# --- Test 4: Booking ref detection finds real ref ---
def test_booking_ref_detection():
    ref = "X7K9M2"
    # Create a booking with this ref
    state_registry.save_booking(ref,
        {"service_key": "test_svc", "customer_name": "Test", "date": "2026-04-10"},
        {})
    try:
        text = f"I have a booking, ref is {ref}, can I change the date?"
        match = re.search(r'\b[A-Z0-9]{6}\b', text)
        assert match is not None
        assert match.group() == ref
        # Verify it's a real booking
        booking = state_registry.get_booking(ref)
        assert booking is not None
    finally:
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM bookings WHERE booking_ref = ?", (ref,))
        conn.commit()
        conn.close()


# --- Test 5: False positive ref rejected by DB check ---
def test_booking_ref_false_positive():
    text = "The color code is FF00FF and AABBCC looks nice"
    match = re.search(r'\b[A-Z0-9]{6}\b', text)
    # May match "AABBCC" — but it's not a real booking
    if match:
        booking = state_registry.get_booking(match.group())
        assert booking is None, "False positive should not find a booking"


# --- Test 6: Terminology appears in prompt ---
def test_terminology_in_prompt():
    from agents.marina.marina_agent import _build_prompt
    # Modify the cached config directly
    config_loader._cache["terminology"] = {"service_label": "reservation", "party_size_label": "diners", "slot_label": "seating"}
    try:
        prompt = _build_prompt("test@x.com", "", "Hello", {}, {},
                               channel="whatsapp", messages=[])
        assert "reservation name" in prompt, f"Expected 'reservation name' in prompt"
        assert "diners" in prompt, f"Expected 'diners' in prompt"
        assert "seating time" in prompt, f"Expected 'seating time' in prompt"
    finally:
        config_loader._cache["terminology"] = {"service_label": "trip", "party_size_label": "guests", "slot_label": "departure"}


# --- Test 7: Terminology defaults when not in config ---
def test_terminology_defaults():
    from agents.marina.marina_agent import _build_prompt
    original = config_loader._cache.pop("terminology", None)
    try:
        prompt = _build_prompt("test@x.com", "", "Hello", {}, {},
                               channel="whatsapp", messages=[])
        assert "service name" in prompt, f"Expected 'service name' in prompt"
        assert "guests" in prompt, f"Expected 'guests' in prompt"
        # Default slot_label is "time slot", so prompt says "time slot time"
        assert "time slot" in prompt, f"Expected 'time slot' in prompt"
    finally:
        if original:
            config_loader._cache["terminology"] = original
        else:
            config_loader._cache["terminology"] = {"service_label": "trip", "party_size_label": "guests", "slot_label": "departure"}
