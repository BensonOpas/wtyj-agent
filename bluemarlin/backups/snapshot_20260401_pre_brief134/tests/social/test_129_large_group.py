# test_129_large_group.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from agents.social.social_agent import handle_incoming_whatsapp_message
from shared import state_registry


def _next_wed():
    today = datetime.now(timezone.utc).date()
    d = today + timedelta(days=1)
    while d.weekday() != 2:
        d += timedelta(days=1)
    return d.isoformat()

def _cleanup(phone):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (phone,))
    conn.commit()
    conn.close()


# --- Test 1: Prompt no longer triggers requires_human for 15+ guests ---
def test_prompt_no_large_group_in_requires_human():
    from agents.marina.marina_agent import _build_prompt
    prompt = _build_prompt("test@test.com", "Test", "Hello",
                           {}, {}, channel="whatsapp", messages=[])
    for line in prompt.split("\n"):
        if "requires_human" in line and "true if" in line:
            assert "15" not in line, f"requires_human still mentions 15: {line}"
            assert "group" not in line.lower(), f"requires_human still mentions group: {line}"
            break


# --- Test 2: Prompt has large_group flag ---
def test_prompt_has_large_group_flag():
    from agents.marina.marina_agent import _build_prompt
    prompt = _build_prompt("test@test.com", "Test", "Hello",
                           {}, {}, channel="whatsapp", messages=[])
    assert "large_group" in prompt


# --- Test 3: Confirmed booking with 15+ guests creates notification ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_large_group_creates_notification(mock_process, mock_cal, mock_pay, mock_sheets):
    phone = "129_large_group"
    _cleanup(phone)
    date = _next_wed()

    fields = {"trip_key": "west_coast_beach", "experience": "West Coast Beach",
              "date": date, "guests": "20", "departure_time": "09:00",
              "customer_name": "Big Group"}
    hold_id = state_registry.create_soft_hold("west_coast_beach", date, "09:00", 20, 25,
                                               customer_name="Big Group", customer_email=phone)
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True, "hold_id": hold_id,
             "hold_trip_key": "west_coast_beach", "hold_date": date,
             "hold_departure_time": "09:00"}
    state_registry.wa_save_booking_state(phone, fields, flags)

    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {},
        "confidence": "high",
        "reply": "You're all set! Ref [BOOKING_REF]. Pay here: [PAYMENT_LINK]",
        "reply_hold_failed": "Sorry, that slot is no longer available.",
        "clarifications_needed": [], "requires_human": False,
        "flags": {"booking_confirmed": True, "awaiting_booking_confirmation": False},
        "internal_note": ""
    }
    mock_cal.create_or_update_manifest.return_value = {"ok": True, "eventId": "e1", "htmlLink": "http://cal/e1"}
    mock_pay.generate_payment_link.return_value = {"payment_id": "pay1", "status": "pending"}

    msg = {"from": phone, "text": "Yes book it!", "from_name": "Big Group"}
    reply = handle_incoming_whatsapp_message(msg)

    assert "BF-" in reply
    assert "demo.pay" in reply

    escs = state_registry.get_all_escalations()
    lg_esc = [e for e in escs if e["customer_id"] == phone and "LARGE GROUP" in e["subject"]]
    assert len(lg_esc) == 1, f"Expected 1 large group notification, got {len(lg_esc)}"
    assert "20 guests" in lg_esc[0]["subject"]
    assert "auto-confirmed" in lg_esc[0]["body"].lower()

    _cleanup(phone)


# --- Test 4: Normal booking (under 15) does NOT create notification ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_normal_booking_no_notification(mock_process, mock_cal, mock_pay, mock_sheets):
    phone = "129_normal_group"
    _cleanup(phone)
    date = _next_wed()

    fields = {"trip_key": "west_coast_beach", "experience": "West Coast Beach",
              "date": date, "guests": "4", "departure_time": "09:00",
              "customer_name": "Small Group"}
    hold_id = state_registry.create_soft_hold("west_coast_beach", date, "09:00", 4, 25,
                                               customer_name="Small Group", customer_email=phone)
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True, "hold_id": hold_id,
             "hold_trip_key": "west_coast_beach", "hold_date": date,
             "hold_departure_time": "09:00"}
    state_registry.wa_save_booking_state(phone, fields, flags)

    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {},
        "confidence": "high",
        "reply": "You're all set! Ref [BOOKING_REF]. Pay here: [PAYMENT_LINK]",
        "reply_hold_failed": "Sorry, unavailable.",
        "clarifications_needed": [], "requires_human": False,
        "flags": {"booking_confirmed": True, "awaiting_booking_confirmation": False},
        "internal_note": ""
    }
    mock_cal.create_or_update_manifest.return_value = {"ok": True, "eventId": "e2", "htmlLink": "http://cal/e2"}
    mock_pay.generate_payment_link.return_value = {"payment_id": "pay2", "status": "pending"}

    msg = {"from": phone, "text": "Yes!", "from_name": "Small Group"}
    handle_incoming_whatsapp_message(msg)

    escs = state_registry.get_all_escalations()
    lg_esc = [e for e in escs if e["customer_id"] == phone and "LARGE GROUP" in e["subject"]]
    assert len(lg_esc) == 0, f"Normal booking should not create large group notification"

    _cleanup(phone)
