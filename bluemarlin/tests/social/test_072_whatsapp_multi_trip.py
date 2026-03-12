# bluemarlin/tests/social/test_072_whatsapp_multi_trip.py
# Created: Brief 072
# Purpose: Tests for WhatsApp multi-trip reset, returning customer, anti-loop

import os
import sys
import time
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ["WHATSAPP_VERIFY_TOKEN"] = "test_token_067"
os.environ["WHATSAPP_ACCESS_TOKEN"] = "test_access_token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "990622044139349"

from agents.social.social_agent import handle_incoming_whatsapp_message
from shared import state_registry


# --- Helpers ---

def _cleanup_phone(phone):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM trip_bookings WHERE customer_email = ?", (phone,))
    conn.commit()
    conn.close()


def _cleanup_booking(booking_ref):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM bookings WHERE booking_ref = ?", (booking_ref,))
    conn.commit()
    conn.close()


def _base_result(**overrides):
    """Build a base marina_agent result dict with overrides."""
    base = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": "Default reply.",
        "clarifications_needed": [],
        "requires_human": False,
        "flags": {},
        "internal_note": "",
    }
    base.update(overrides)
    return base


# --- Test 1: Multi-trip reset archives booking ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_multi_trip_reset_archives_booking(mock_process):
    """Completed booking is archived and fields/flags reset when new booking intent arrives."""
    phone = "TEST_072_MT_001"
    _cleanup_phone(phone)
    # Pre-set completed booking state
    fields = {
        "trip_key": "west_coast_beach", "experience": "West Coast Beach Trip",
        "date": "2026-03-18", "guests": "2", "departure_time": "09:00",
        "customer_name": "Test User",
    }
    flags = {
        "hold_created": True, "booking_ref": "BF-2026-99001",
        "payment_link": "https://demo.pay/test",
    }
    state_registry.wa_save_booking_state(phone, fields, flags)
    mock_process.return_value = _base_result(
        intents=["booking"],
        fields={"trip_key": "klein_curacao"},
        reply="Sure, let me help with Klein Curaçao!",
    )
    msg = {"from": phone, "text": "I want to book Klein Curacao too", "from_name": "Test User"}
    handle_incoming_whatsapp_message(msg)
    # Check persisted state
    state = state_registry.wa_get_booking_state(phone)
    cb = state["completed_bookings"]
    assert len(cb) == 1
    assert cb[0]["booking_ref"] == "BF-2026-99001"
    assert cb[0]["trip_key"] == "west_coast_beach"
    assert cb[0]["date"] == "2026-03-18"
    # Fields reset — only persistent fields survive, plus new fields from merge
    assert state["fields"].get("customer_name") == "Test User"
    assert state["fields"].get("date") is None  # cleared by reset
    assert state["fields"].get("guests") is None  # cleared by reset
    # Flags reset
    assert "hold_created" not in state["flags"]
    assert "booking_ref" not in state["flags"]
    assert "payment_link" not in state["flags"]
    _cleanup_phone(phone)


# --- Test 2: Multi-trip max bookings no reset ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_multi_trip_max_bookings_no_reset(mock_process):
    """At max_bookings_per_thread (3), no reset happens."""
    phone = "TEST_072_MT_002"
    _cleanup_phone(phone)
    completed = [
        {"booking_ref": f"BF-2026-0000{i}", "trip_key": "trip", "date": "2026-03-18",
         "guests": "2"} for i in range(3)
    ]
    fields = {"customer_name": "Test"}
    flags = {"hold_created": True}
    state_registry.wa_save_booking_state(phone, fields, flags, completed)
    mock_process.return_value = _base_result(
        intents=["booking"],
        reply="Some reply",
        fields={},
    )
    msg = {"from": phone, "text": "Book another trip", "from_name": "Test"}
    handle_incoming_whatsapp_message(msg)
    state = state_registry.wa_get_booking_state(phone)
    assert len(state["completed_bookings"]) == 3  # unchanged
    assert state["flags"].get("hold_created") is True  # not reset
    _cleanup_phone(phone)


# --- Test 3: Returning customer by booking ref ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_returning_customer_by_ref(mock_process):
    """Booking ref in message text loads past booking data."""
    phone = "TEST_072_RET_001"
    _cleanup_phone(phone)
    _cleanup_booking("BF-2026-88001")
    # Create a past booking in SQLite
    state_registry.save_booking(
        "BF-2026-88001",
        {"trip_key": "sunset_cruise", "customer_name": "Jane", "date": "2026-03-10",
         "guests": 2, "departure_time": "16:00"},
        {},
        customer_email=phone,
    )
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="Happy to help with your booking!",
    )
    msg = {"from": phone, "text": "Hi, about my booking BF-2026-88001", "from_name": "Jane"}
    handle_incoming_whatsapp_message(msg)
    # Check persisted state
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("returning_booking") == "BF-2026-88001"
    assert state["fields"].get("trip_key") == "sunset_cruise"
    assert state["fields"].get("customer_name") == "Jane"
    # Check marina_agent was called with returning_booking
    call_kwargs = mock_process.call_args
    passed_flags = call_kwargs.kwargs.get("thread_flags", {})
    assert passed_flags.get("returning_booking") == "BF-2026-88001"
    _cleanup_phone(phone)
    _cleanup_booking("BF-2026-88001")


# --- Test 4: Returning customer unknown ref ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_returning_customer_unknown_ref(mock_process):
    """Unknown booking ref sets unknown_ref flag, cleared after call."""
    phone = "TEST_072_RET_002"
    _cleanup_phone(phone)
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="Let me check.",
    )
    msg = {"from": phone, "text": "About booking BF-2026-00000", "from_name": "Test"}
    handle_incoming_whatsapp_message(msg)
    # marina_agent was called with unknown_ref
    call_kwargs = mock_process.call_args
    passed_flags = call_kwargs.kwargs.get("thread_flags", {})
    assert passed_flags.get("unknown_ref") == "BF-2026-00000"
    # But it's cleared after the call (one-shot)
    state = state_registry.wa_get_booking_state(phone)
    assert "unknown_ref" not in state["flags"]
    _cleanup_phone(phone)


# --- Test 5: Returning customer by phone ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_returning_customer_by_phone(mock_process):
    """Phone-based lookup finds past bookings and injects summary into agent_flags."""
    phone = "TEST_072_RET_003"
    _cleanup_phone(phone)
    _cleanup_booking("BF-2026-88005")
    # Create a past booking with this phone as customer_email
    state_registry.save_booking(
        "BF-2026-88005",
        {"trip_key": "jet_ski", "customer_name": "Mike", "guests": 1},
        {},
        customer_email=phone,
    )
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="Welcome back!",
    )
    msg = {"from": phone, "text": "What trips do you have?", "from_name": "Mike"}
    handle_incoming_whatsapp_message(msg)
    # Check marina_agent was called with _past_customer_bookings
    call_kwargs = mock_process.call_args
    passed_flags = call_kwargs.kwargs.get("thread_flags", {})
    past_bookings = passed_flags.get("_past_customer_bookings", "")
    assert "jet_ski" in past_bookings
    assert "BF-2026-88005" in past_bookings
    _cleanup_phone(phone)
    _cleanup_booking("BF-2026-88005")


# --- Test 6: Anti-loop blocks after limit ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_anti_loop_blocks_after_limit(mock_process):
    """Rate limited phone gets empty reply, marina_agent not called."""
    phone = "TEST_072_LOOP_001"
    _cleanup_phone(phone)
    now = int(time.time())
    # 25 timestamps within the last hour
    reply_times = [now - i * 60 for i in range(25)]
    state_registry.wa_save_booking_state(phone, {}, {"reply_times": reply_times})
    msg = {"from": phone, "text": "Hello", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == ""
    assert mock_process.call_count == 0
    _cleanup_phone(phone)


# --- Test 7: Anti-loop allows after window ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_anti_loop_allows_after_window(mock_process):
    """Old timestamps outside 1hr window are pruned, call proceeds."""
    phone = "TEST_072_LOOP_002"
    _cleanup_phone(phone)
    old = int(time.time()) - 7200  # 2 hours ago
    reply_times = [old - i * 60 for i in range(25)]
    state_registry.wa_save_booking_state(phone, {}, {"reply_times": reply_times})
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="Here to help!",
    )
    msg = {"from": phone, "text": "Hi there", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == "Here to help!"
    assert mock_process.call_count == 1
    _cleanup_phone(phone)


# --- Test 8: Reply times recorded ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_reply_times_recorded(mock_process):
    """Reply timestamp is recorded in persisted state."""
    phone = "TEST_072_RT_001"
    _cleanup_phone(phone)
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="Hello!",
    )
    msg = {"from": phone, "text": "Hi", "from_name": "Test"}
    before = int(time.time())
    handle_incoming_whatsapp_message(msg)
    state = state_registry.wa_get_booking_state(phone)
    rt = state["flags"].get("reply_times", [])
    assert len(rt) == 1
    assert rt[0] >= before
    assert rt[0] <= before + 5
    _cleanup_phone(phone)


# --- Test 9: Reply times not in agent flags ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_reply_times_not_in_agent_flags(mock_process):
    """reply_times is filtered from flags passed to marina_agent."""
    phone = "TEST_072_RT_002"
    _cleanup_phone(phone)
    now = int(time.time())
    state_registry.wa_save_booking_state(phone, {}, {"reply_times": [now]})
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="Sure!",
    )
    msg = {"from": phone, "text": "Question", "from_name": "Test"}
    handle_incoming_whatsapp_message(msg)
    call_kwargs = mock_process.call_args
    passed_flags = call_kwargs.kwargs.get("thread_flags", {})
    assert "reply_times" not in passed_flags
    _cleanup_phone(phone)


# --- Test 10: Completed bookings summary in agent flags ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_completed_bookings_summary_in_agent_flags(mock_process):
    """Completed bookings are injected as summary into agent_flags."""
    phone = "TEST_072_CB_001"
    _cleanup_phone(phone)
    completed = [{
        "booking_ref": "BF-2026-77001", "trip_key": "klein_curacao",
        "experience": "Klein Curaçao", "date": "2026-03-15", "guests": "4",
    }]
    state_registry.wa_save_booking_state(phone, {}, {}, completed)
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="What can I help with?",
    )
    msg = {"from": phone, "text": "I want another trip", "from_name": "Test"}
    handle_incoming_whatsapp_message(msg)
    call_kwargs = mock_process.call_args
    passed_flags = call_kwargs.kwargs.get("thread_flags", {})
    summary = passed_flags.get("_completed_bookings_summary", "")
    assert "BF-2026-77001" in summary
    assert "Klein Cura" in summary  # experience takes priority over trip_key in summary
    _cleanup_phone(phone)


# --- Test 11: Anti-loop blocks fully escalated ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_anti_loop_blocks_fully_escalated(mock_process):
    """Anti-loop fires before fully-escalated guard."""
    phone = "TEST_072_LOOP_003"
    _cleanup_phone(phone)
    now = int(time.time())
    reply_times = [now - i * 60 for i in range(25)]
    state_registry.wa_save_booking_state(
        phone, {}, {"fully_escalated": True, "reply_times": reply_times})
    msg = {"from": phone, "text": "Any update?", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == ""
    assert mock_process.call_count == 0
    _cleanup_phone(phone)
