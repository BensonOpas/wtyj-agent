# bluemarlin/tests/social/test_070_whatsapp_booking.py
# Created: Brief 070
# Purpose: Tests for WhatsApp booking orchestrator

import os
import re
import sys
import json
import time
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ["WHATSAPP_VERIFY_TOKEN"] = "test_token_067"
os.environ["WHATSAPP_ACCESS_TOKEN"] = "test_access_token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "990622044139349"


from datetime import datetime, timezone, timedelta
def _next_wed():
    today = datetime.now(timezone.utc).date()
    d = today + timedelta(days=1)
    while d.weekday() != 2:
        d += timedelta(days=1)
    return d.isoformat()

from agents.social.social_agent import (
    _day_matches,
    _build_action_context, _post_validate,
    _BOOKING_INTENTS, _BOOKING_FLAGS_TO_RESET, _PERSISTENT_FIELDS,
    handle_incoming_whatsapp_message,
)
from shared import config_loader
from shared import state_registry


def _next_weekday(weekday: int, days_ahead: int = 0) -> str:
    """Return the next occurrence of a weekday (0=Mon, 2=Wed, 6=Sun) as YYYY-MM-DD."""
    today = datetime.now(timezone.utc).date()
    d = today + timedelta(days=max(days_ahead, 1))
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d.isoformat()

# Dynamic future dates for booking tests
_NEXT_WED = _next_weekday(2)      # Next Wednesday (West Coast Beach runs Wed/Sun)
_NEXT_MON = _next_weekday(0)      # Next Monday (invalid for West Coast Beach)
_FUTURE_DATE = (datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat()


# --- Helpers ---

def _cleanup_phone(phone):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM service_bookings WHERE customer_email = ?", (phone,))
    conn.commit()
    conn.close()


# --- Helper function unit tests (pure functions, real config_loader) ---

def test_day_matches_daily():
    """Daily trips match any day."""
    assert _day_matches("Monday", "Daily") is True
    assert _day_matches("Sunday", "daily") is True


def test_day_matches_specific_days():
    """Specific days match correctly."""
    assert _day_matches("Wednesday", "Wednesdays and Sundays") is True
    assert _day_matches("Sunday", "Wednesdays and Sundays") is True
    assert _day_matches("Monday", "Wednesdays and Sundays") is False
    assert _day_matches("Friday", "Tuesday, Thursday, Friday, Saturday") is True


def test_build_action_context_awaiting():
    """Action context generated when awaiting_booking_confirmation is True."""
    ctx = _build_action_context({"awaiting_booking_confirmation": True})
    assert "booking summary was sent" in ctx
    assert "[PAYMENT_LINK]" in ctx
    assert "reply_hold_failed" in ctx


def test_build_action_context_not_awaiting():
    """No action context when not awaiting confirmation."""
    ctx = _build_action_context({})
    assert ctx == ""


def test_post_validate_day_of_week_does_not_advance():
    """Brief 161: wrong day returns (None, False) — Marina handles the rejection reply."""
    service = config_loader.get_service("west_coast_beach")
    fields = {"service_name": "West Coast Beach Trip", "date": _NEXT_MON,
              "guests": "2", "service_key": "west_coast_beach"}  # Monday — Wed/Sun only
    result = {"intents": ["booking"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, service)
    assert override is None
    assert should_set is False


def test_post_validate_past_date_does_not_advance():
    """Brief 161: past date returns (None, False)."""
    service = config_loader.get_service("klein_curacao")
    fields = {"service_name": "Klein Curacao", "date": "2025-01-15",
              "guests": "2", "service_key": "klein_curacao"}
    result = {"intents": ["booking"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, service)
    assert override is None
    assert should_set is False


def test_post_validate_multi_departure_does_not_advance():
    """Brief 161: multi-departure without slot_time returns (None, False)."""
    service = config_loader.get_service("klein_curacao")
    fields = {"service_name": "Klein Curacao", "date": _FUTURE_DATE,
              "guests": "2", "service_key": "klein_curacao"}
    result = {"intents": ["booking"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, service)
    assert override is None
    assert should_set is False


def test_post_validate_all_pass_advances_state():
    """Brief 161: all valid returns (None, True) — no reply override, just state."""
    service = config_loader.get_service("west_coast_beach")
    fields = {"service_name": "West Coast Beach Trip", "date": _NEXT_WED,
              "guests": "2", "service_key": "west_coast_beach",
              "slot_time": "09:00"}  # Wednesday, single departure
    result = {"intents": ["booking"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, service)
    assert override is None
    assert should_set is True


def test_post_validate_skips_non_booking_intent():
    """Non-booking intent skips validation entirely."""
    service = config_loader.get_service("klein_curacao")
    fields = {"service_name": "Klein Curacao", "date": _FUTURE_DATE,
              "guests": "2", "service_key": "klein_curacao"}
    result = {"intents": ["inquiry"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, service)
    assert override is None
    assert should_set is False


# --- Orchestrator integration tests (mocked externals) ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_orchestrator_wrong_day_keeps_marinas_reply(mock_process):
    """Brief 161: Marina's own wrong-day reply is preserved; state does not advance."""
    phone = "TEST_070_DAY_001"
    _cleanup_phone(phone)
    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {"service_key": "west_coast_beach", "service_name": "West Coast Beach",
                    "date": _NEXT_MON, "guests": "2"},  # Monday — Wed/Sun only
        "confidence": "high",
        "reply": "The West Coast Beach Trip only runs Wednesdays and Sundays. Would Wednesday work?",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }
    msg = {"from": phone, "text": "Book West Coast Beach Monday for 2", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    # Marina's own reply is preserved — no Python override
    assert "Wednesday" in reply
    assert "[BOOKING_REF]" not in reply
    # State must NOT have advanced
    state = state_registry.wa_get_booking_state(phone)
    assert not state["flags"].get("awaiting_booking_confirmation")
    _cleanup_phone(phone)


@patch("agents.social.social_agent.state_registry.create_soft_hold")
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_orchestrator_all_valid_advances_state_keeps_marinas_summary(mock_process, mock_cal, mock_pay, mock_sheets, mock_hold):
    """Brief 161: valid booking — Marina's own summary kept, awaiting flag set, hold placed.
    NOTE: patch agents.social.social_agent.state_registry (local import), not shared.state_registry,
    because social_agent.py imports state_registry at the top."""
    phone = "TEST_070_SUMMARY_001"
    _cleanup_phone(phone)
    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {"service_key": "west_coast_beach", "service_name": "West Coast Beach",
                    "date": _NEXT_WED, "guests": "2",
                    "slot_time": "09:00",
                    "customer_name": "John"},
        "confidence": "high",
        "reply": "Just to confirm: West Coast Beach Trip on Wednesday, 2 guests, $240 total. Want me to check availability and hold a spot?",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }
    mock_cal.check_availability.return_value = {"available": True, "spots_remaining": 23, "capacity": 25}
    mock_hold.return_value = 888
    msg = {"from": phone, "text": "West Coast Beach Wed for 2", "from_name": "John"}
    reply = handle_incoming_whatsapp_message(msg)
    # Marina's own summary is preserved exactly (no Python override)
    assert "$240" in reply
    assert "check availability" in reply.lower()
    # Check awaiting flag was set
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("awaiting_booking_confirmation") is True
    assert state["flags"].get("slot_checked") is True
    _cleanup_phone(phone)


@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_orchestrator_booking_confirmed(mock_process, mock_cal, mock_pay, mock_sheets):
    """Customer confirms booking — booking_ref and payment_link replaced in reply."""
    phone = "TEST_070_CONFIRM_001"
    _cleanup_phone(phone)
    # Pre-set state: awaiting confirmation with soft hold
    fields = {"service_key": "west_coast_beach", "service_name": "West Coast Beach",
              "date": _NEXT_WED, "guests": "2",
              "slot_time": "09:00", "customer_name": "John"}
    hold_id = state_registry.create_soft_hold("west_coast_beach", _NEXT_WED, "09:00", 2, 25,
                                               customer_name="John", customer_email=phone)
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True, "hold_id": hold_id,
             "hold_service_key": "west_coast_beach", "hold_date": _NEXT_WED,
             "hold_slot_time": "09:00"}
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
    mock_cal.create_or_update_manifest.return_value = {"ok": True, "eventId": "e2", "htmlLink": "http://cal/e2"}
    mock_pay.generate_payment_link.return_value = {"payment_id": "pay123", "status": "pending"}

    msg = {"from": phone, "text": "Yes book it!", "from_name": "John"}
    reply = handle_incoming_whatsapp_message(msg)
    assert "[BOOKING_REF]" not in reply
    assert "[PAYMENT_LINK]" not in reply
    assert re.search(r"[A-Z0-9]{6}", reply)  # real booking ref
    assert "demo.pay" in reply  # real payment link
    # Verify state
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("hold_created") is True
    assert len(state["flags"].get("booking_ref", "")) == 6  # random alphanumeric ref
    assert "demo.pay" in state["flags"].get("payment_link", "")
    # Cleanup
    _cleanup_phone(phone)


@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_orchestrator_slot_unavailable(mock_process, mock_cal):
    """Slot unavailable returns friendly message, does not set awaiting."""
    phone = "TEST_070_UNAVAIL_001"
    _cleanup_phone(phone)
    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {"service_key": "west_coast_beach", "service_name": "West Coast Beach",
                    "date": _NEXT_WED, "guests": "2",
                    "slot_time": "09:00", "customer_name": "Jane"},
        "confidence": "high",
        "reply": "Sounds good!",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }
    mock_cal.check_availability.return_value = {"available": False, "spots_remaining": 0, "capacity": 25}
    msg = {"from": phone, "text": "Book it for March 18", "from_name": "Jane"}
    reply = handle_incoming_whatsapp_message(msg)
    assert "fully booked" in reply.lower()
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("awaiting_booking_confirmation") is not True
    _cleanup_phone(phone)
