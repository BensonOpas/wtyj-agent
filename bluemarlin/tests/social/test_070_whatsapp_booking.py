# bluemarlin/tests/social/test_070_whatsapp_booking.py
# Created: Brief 070
# Purpose: Tests for WhatsApp booking orchestrator

import os
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

from agents.social.social_agent import (
    _day_matches, _suggest_dates, _build_booking_summary,
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


def test_suggest_dates_west_coast():
    """West Coast Beach runs Wed/Sun — Monday 2026-03-16 suggests nearby valid dates."""
    suggestions = _suggest_dates(_NEXT_MON, "Wednesdays and Sundays")
    assert "Wednesday" in suggestions  # 2026-03-18
    assert "Sunday" in suggestions  # 2026-03-22


def test_build_booking_summary_west_coast():
    """Summary contains correct price, date, guests from real service config."""
    service = config_loader.get_service("west_coast_beach")
    fields = {
        "service_key": "west_coast_beach",
        "service_name": "West Coast Beach Trip",
        "date": _NEXT_WED,  # Wednesday
        "guests": "3",
        "slot_time": "09:00",
    }
    summary = _build_booking_summary(fields, service)
    assert "$360" in summary  # 3 * $120
    assert "$120" in summary  # per person
    assert "Wednesday" in summary
    assert "09:00" in summary
    assert "Red Dragon" in summary
    assert "book this?" in summary.lower()


def test_build_booking_summary_single_departure_auto():
    """Single-departure service auto-selects departure when not specified."""
    service = config_loader.get_service("west_coast_beach")
    fields = {
        "service_key": "west_coast_beach",
        "service_name": "West Coast Beach Trip",
        "date": _NEXT_WED,  # Wednesday
        "guests": "2",
    }
    summary = _build_booking_summary(fields, service)
    assert "09:00" in summary  # auto-selected from single departure


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


def test_post_validate_day_of_week_rejection():
    """Monday booking for West Coast Beach (Wed/Sun only) is rejected."""
    service = config_loader.get_service("west_coast_beach")
    fields = {"service_name": "West Coast Beach Trip", "date": _NEXT_MON,
              "guests": "2", "service_key": "west_coast_beach"}  # Monday
    result = {"intents": ["booking"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, service)
    assert override is not None
    assert "doesn't run on Monday" in override
    assert should_set is False


def test_post_validate_past_date_rejection():
    """Past date is rejected (klein_curacao is daily, so day-of-week check passes first)."""
    service = config_loader.get_service("klein_curacao")
    fields = {"service_name": "Klein Curacao", "date": "2025-01-15",
              "guests": "2", "service_key": "klein_curacao"}
    result = {"intents": ["booking"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, service)
    assert override is not None
    assert "already passed" in override
    assert should_set is False


def test_post_validate_multi_departure_asks():
    """Multi-departure service (klein_curacao: 08:00, 08:30) without slot_time asks for selection."""
    service = config_loader.get_service("klein_curacao")
    fields = {"service_name": "Klein Curacao", "date": _FUTURE_DATE,
              "guests": "2", "service_key": "klein_curacao"}
    result = {"intents": ["booking"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, service)
    assert override is not None
    assert "departure time" in override.lower()
    assert "08:00" in override
    assert "08:30" in override
    assert should_set is False


def test_post_validate_all_pass_builds_summary():
    """All fields valid — summary built, should_set_awaiting is True."""
    service = config_loader.get_service("west_coast_beach")
    fields = {"service_name": "West Coast Beach Trip", "date": _NEXT_WED,
              "guests": "2", "service_key": "west_coast_beach",
              "slot_time": "09:00"}  # Wednesday, single departure
    result = {"intents": ["booking"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, service)
    assert override is not None
    assert "$240" in override  # 2 * $120
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
def test_orchestrator_post_validate_day_override(mock_process):
    """Booking on wrong day returns day-of-week override instead of Claude reply."""
    phone = "TEST_070_DAY_001"
    _cleanup_phone(phone)
    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {"service_key": "west_coast_beach", "service_name": "West Coast Beach",
                    "date": _NEXT_MON, "guests": "2"},  # Monday — Wed/Sun only
        "confidence": "high",
        "reply": "I'll book West Coast Beach for you!",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }
    msg = {"from": phone, "text": "Book West Coast Beach March 16 for 2", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert "doesn't run on Monday" in reply
    assert "[BOOKING_REF]" not in reply
    _cleanup_phone(phone)


@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_orchestrator_booking_summary_sent(mock_process, mock_cal, mock_pay, mock_sheets):
    """Valid booking fields trigger summary and awaiting_booking_confirmation flag."""
    phone = "TEST_070_SUMMARY_001"
    _cleanup_phone(phone)
    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {"service_key": "west_coast_beach", "service_name": "West Coast Beach",
                    "date": _NEXT_WED, "guests": "2",
                    "customer_name": "John"},  # Wednesday — single departure, auto-selects 09:00
        "confidence": "high",
        "reply": "Sounds good!",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }
    mock_cal.check_availability.return_value = {"available": True, "spots_remaining": 23, "capacity": 25}
    msg = {"from": phone, "text": "West Coast Beach March 18 for 2", "from_name": "John"}
    reply = handle_incoming_whatsapp_message(msg)
    # Should contain booking summary (from _post_validate — single departure auto-selects 09:00)
    assert "$240" in reply  # 2 * $120
    assert "book this?" in reply.lower()
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
    assert state["flags"].get("booking_ref", "").startswith("BF-")
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
