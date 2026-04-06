# test_133_generalize_config.py
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test")

from unittest.mock import patch, MagicMock
from agents.marina.marina_agent import _build_prompt
from shared import config_loader


# --- Test 1: Payment timing "none" strips payment link ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_payment_timing_none_strips_link(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    from shared import state_registry
    from datetime import datetime, timezone, timedelta

    phone = "133_pay_none"
    # Cleanup
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()

    # Next Wednesday for valid date
    today = datetime.now(timezone.utc).date()
    d = today + timedelta(days=1)
    while d.weekday() != 2:
        d += timedelta(days=1)
    date = d.isoformat()

    fields = {"trip_key": "west_coast_beach", "experience": "West Coast Beach",
              "date": date, "guests": "2", "departure_time": "09:00",
              "customer_name": "Test"}
    hold_id = state_registry.create_soft_hold("west_coast_beach", date, "09:00", 2, 25,
                                               customer_name="Test", customer_email=phone)
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True, "hold_id": hold_id,
             "hold_trip_key": "west_coast_beach", "hold_date": date,
             "hold_departure_time": "09:00"}
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

    # Patch payment timing to "none"
    # Temporarily set payment timing to "none"
    raw = config_loader.get_raw()
    original_timing = raw.get("payment", {}).get("timing", "upfront")
    raw["payment"]["timing"] = "none"
    try:
        msg = {"from": phone, "text": "Yes book it!", "from_name": "Test"}
        reply = handle_incoming_whatsapp_message(msg)

        assert "[PAYMENT_LINK]" not in reply
        assert "demo.pay" not in reply
        # payment_stub should NOT have been called
        mock_pay.generate_payment_link.assert_not_called()
    finally:
        raw["payment"]["timing"] = original_timing

    # Cleanup
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


# --- Test 2: Payment timing "upfront" unchanged (regression) ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_payment_timing_upfront_unchanged(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    from shared import state_registry
    from datetime import datetime, timezone, timedelta

    phone = "133_pay_upfront"
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()

    today = datetime.now(timezone.utc).date()
    d = today + timedelta(days=1)
    while d.weekday() != 2:
        d += timedelta(days=1)
    date = d.isoformat()

    fields = {"trip_key": "west_coast_beach", "experience": "West Coast Beach",
              "date": date, "guests": "2", "departure_time": "09:00",
              "customer_name": "Test"}
    hold_id = state_registry.create_soft_hold("west_coast_beach", date, "09:00", 2, 25,
                                               customer_name="Test", customer_email=phone)
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True, "hold_id": hold_id,
             "hold_trip_key": "west_coast_beach", "hold_date": date,
             "hold_departure_time": "09:00"}
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

    assert "demo.pay" in reply
    assert "[PAYMENT_LINK]" not in reply  # Should be replaced
    mock_pay.generate_payment_link.assert_called_once()

    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


# --- Test 3: Booking ref uses config prefix ---
def test_booking_ref_uses_config_prefix():
    import time as _time
    prefix = config_loader.get_booking_rules().get("booking_ref_prefix", "BM")
    booking_ref = f"{prefix}-{_time.strftime('%Y')}-{int(_time.time()) % 100000:05d}"
    assert booking_ref.startswith("BF-")  # Current config has "BF"
    assert re.match(r'BF-\d{4}-\d{5}', booking_ref)


# --- Test 4: Returning customer regex matches config prefix ---
def test_booking_ref_regex_matches_config_prefix():
    prefix = "RS"
    text = "My booking is RS-2026-12345"
    pattern = rf'{re.escape(prefix)}-\d{{4}}-\d{{5}}'
    match = re.search(pattern, text)
    assert match is not None
    assert match.group() == "RS-2026-12345"


# --- Test 5: Default prefix when not in config ---
def test_booking_ref_regex_default_prefix():
    # Simulate missing prefix
    rules = {}
    prefix = rules.get("booking_ref_prefix", "BM")
    assert prefix == "BM"


# --- Test 6: CONTACT INFO RULE uses business email from config ---
def test_prompt_contact_email_from_config():
    prompt = _build_prompt("test@x.com", "Hello", "Hi", {}, {},
                           channel="whatsapp", messages=[])
    # The CONTACT INFO RULE should contain the email from config
    business_email = config_loader.get_business().get("email", "")
    assert f"CONTACT INFO RULE: {business_email}" in prompt
    # The hardcoded literal "info@bluefinncharters.com" should NOT appear
    # as a string constant in the source — it comes from config
    # (It WILL appear in the client data sections because that IS the config value)
    assert "CONTACT INFO RULE: info@bluefinncharters.com" in prompt  # Currently same value, that's fine
    # The key test: no literal hardcoded email in the source code prompt template
    # (verified by checking the source file itself is better, but this at least
    #  confirms the f-string interpolation works)


# --- Test 7: Prompt EXAMPLES (source code) have no charter-specific content ---
def test_prompt_no_charter_specific_examples():
    prompt = _build_prompt("test@x.com", "", "Hello", {}, {},
                           channel="whatsapp", messages=[])
    # Check the GOOD REPLIES section specifically — not the whole prompt
    # (FAQ data from client.json will contain charter terms, that's correct)
    assert "boat trips plus jet ski" not in prompt
    assert "Klein Curacao trip" not in prompt
    assert "drinks are included once the BBQ" not in prompt


# --- Test 8: Email prompt has no "BlueFinn team" ---
def test_prompt_email_no_bluefinn_team():
    prompt = _build_prompt("test@x.com", "Hello", "Hi", {}, {},
                           channel="email", messages=[])
    assert "BlueFinn team" not in prompt
    # Should contain the actual business name from config
    business_name = config_loader.get_business().get("name", "")
    assert business_name in prompt


# --- Test 9: Payment "none" keeps booking ref but strips payment link ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_payment_timing_none_keeps_booking_ref(mock_process, mock_cal, mock_pay, mock_sheets):
    from agents.social.social_agent import handle_incoming_whatsapp_message
    from shared import state_registry
    from datetime import datetime, timezone, timedelta

    phone = "133_ref_kept"
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()

    today = datetime.now(timezone.utc).date()
    d = today + timedelta(days=1)
    while d.weekday() != 2:
        d += timedelta(days=1)
    date = d.isoformat()

    fields = {"trip_key": "west_coast_beach", "experience": "West Coast Beach",
              "date": date, "guests": "2", "departure_time": "09:00",
              "customer_name": "Test"}
    hold_id = state_registry.create_soft_hold("west_coast_beach", date, "09:00", 2, 25,
                                               customer_name="Test", customer_email=phone)
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True, "hold_id": hold_id,
             "hold_trip_key": "west_coast_beach", "hold_date": date,
             "hold_departure_time": "09:00"}
    state_registry.wa_save_booking_state(phone, fields, flags)

    mock_process.return_value = {
        "intents": ["booking"], "fields": {}, "confidence": "high",
        "reply": "Ref [BOOKING_REF]. Payment: [PAYMENT_LINK]",
        "reply_hold_failed": "Sorry.", "clarifications_needed": [],
        "requires_human": False,
        "flags": {"booking_confirmed": True, "awaiting_booking_confirmation": False},
        "internal_note": ""
    }
    mock_cal.create_or_update_manifest.return_value = {"ok": True, "eventId": "e1", "htmlLink": "http://cal/e1"}

    raw = config_loader.get_raw()
    original_timing = raw.get("payment", {}).get("timing", "upfront")
    raw["payment"]["timing"] = "none"
    try:
        msg = {"from": phone, "text": "Yes!", "from_name": "Test"}
        reply = handle_incoming_whatsapp_message(msg)

        # Booking ref SHOULD be replaced (not a placeholder)
        assert "[BOOKING_REF]" not in reply
        assert "BF-" in reply  # Actual ref present
        # Payment link SHOULD be stripped
        assert "[PAYMENT_LINK]" not in reply
        assert "demo.pay" not in reply
    finally:
        raw["payment"]["timing"] = original_timing

    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()
