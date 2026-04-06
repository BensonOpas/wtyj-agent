# bluemarlin/tests/social/test_073_whatsapp_hardening.py
# Created: Brief 073
# Purpose: Tests for stale conversation reset, data cleanup, and edge case coverage

import os
import sys
import time
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ["WHATSAPP_VERIFY_TOKEN"] = "test_token_067"
os.environ["WHATSAPP_ACCESS_TOKEN"] = "test_access_token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "990622044139349"

from agents.social.social_agent import handle_incoming_whatsapp_message
from shared import state_registry


def _next_weekday(weekday: int, days_ahead: int = 0) -> str:
    today = datetime.now(timezone.utc).date()
    d = today + timedelta(days=max(days_ahead, 1))
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d.isoformat()

_NEXT_WED = _next_weekday(2)
_FUTURE_DATE = (datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat()


# --- Helpers ---

def _cleanup_phone(phone):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM service_bookings WHERE customer_email = ?", (phone,))
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


# --- Test 1: Stale conversation resets fields ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_stale_conversation_resets_fields(mock_process):
    """Fields are reset (except persistent) after 24h inactivity gap."""
    phone = "TEST_073_STALE_001"
    _cleanup_phone(phone)
    # Pre-set state with last_activity = 48 hours ago
    fields = {"service_key": "west_coast_beach", "date": _NEXT_WED,
              "guests": "2", "customer_name": "Test User"}
    flags = {}
    state_registry.wa_save_booking_state(phone, fields, flags)
    # Manually backdate last_activity
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    conn = state_registry._get_conn()
    conn.execute("UPDATE whatsapp_booking_state SET last_activity = ? WHERE phone = ?",
                 (old_ts, phone))
    conn.commit()
    conn.close()

    mock_process.return_value = _base_result(
        intents=["inquiry"], reply="Hi!",
    )
    msg = {"from": phone, "text": "Hello", "from_name": "Test User"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == "Hi!"
    # Check persisted state — only persistent fields survive
    state = state_registry.wa_get_booking_state(phone)
    assert state["fields"].get("customer_name") == "Test User"
    assert state["fields"].get("service_key") is None
    assert state["fields"].get("date") is None
    assert state["fields"].get("guests") is None
    _cleanup_phone(phone)


# --- Test 2: Stale conversation archives booking ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_stale_conversation_archives_booking(mock_process):
    """Active booking is archived to completed_bookings on stale reset."""
    phone = "TEST_073_STALE_002"
    _cleanup_phone(phone)
    fields = {"service_key": "west_coast_beach", "service_name": "West Coast Beach",
              "date": _NEXT_WED, "guests": "2", "customer_name": "Test User"}
    flags = {"hold_created": True, "booking_ref": "BF-2026-55001",
             "payment_link": "https://demo.pay/test"}
    state_registry.wa_save_booking_state(phone, fields, flags)
    # Backdate last_activity
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    conn = state_registry._get_conn()
    conn.execute("UPDATE whatsapp_booking_state SET last_activity = ? WHERE phone = ?",
                 (old_ts, phone))
    conn.commit()
    conn.close()

    mock_process.return_value = _base_result(
        intents=["inquiry"], reply="Hello!",
    )
    msg = {"from": phone, "text": "Hi there", "from_name": "Test User"}
    handle_incoming_whatsapp_message(msg)
    state = state_registry.wa_get_booking_state(phone)
    cb = state["completed_bookings"]
    assert len(cb) == 1
    assert cb[0]["booking_ref"] == "BF-2026-55001"
    assert cb[0]["service_key"] == "west_coast_beach"
    # Flags reset
    assert "hold_created" not in state["flags"]
    assert "booking_ref" not in state["flags"]
    _cleanup_phone(phone)


# --- Test 3: Stale conversation clears escalation ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_stale_conversation_clears_escalation(mock_process):
    """Escalation flags are cleared on stale reset."""
    phone = "TEST_073_STALE_003"
    _cleanup_phone(phone)
    fields = {"customer_name": "Test"}
    flags = {"fully_escalated": True, "awaiting_relay": True, "relay_token": "abc"}
    state_registry.wa_save_booking_state(phone, fields, flags)
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    conn = state_registry._get_conn()
    conn.execute("UPDATE whatsapp_booking_state SET last_activity = ? WHERE phone = ?",
                 (old_ts, phone))
    conn.commit()
    conn.close()

    mock_process.return_value = _base_result(
        intents=["inquiry"], reply="Hi there!",
    )
    msg = {"from": phone, "text": "Hey", "from_name": "Test"}
    handle_incoming_whatsapp_message(msg)
    state = state_registry.wa_get_booking_state(phone)
    assert "fully_escalated" not in state["flags"]
    assert "awaiting_relay" not in state["flags"]
    assert "relay_token" not in state["flags"]
    _cleanup_phone(phone)


# --- Test 4: Fresh conversation no reset ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_fresh_conversation_no_reset(mock_process):
    """Fields are preserved when last_activity is < 24h ago."""
    phone = "TEST_073_FRESH_001"
    _cleanup_phone(phone)
    fields = {"service_key": "sunset_cruise", "date": _FUTURE_DATE,
              "guests": "4", "customer_name": "Test"}
    flags = {}
    state_registry.wa_save_booking_state(phone, fields, flags)
    # last_activity is set by wa_save_booking_state to now — should be < 24h

    mock_process.return_value = _base_result(
        intents=["inquiry"], reply="Sure!", fields={},
    )
    msg = {"from": phone, "text": "Hi again", "from_name": "Test"}
    handle_incoming_whatsapp_message(msg)
    state = state_registry.wa_get_booking_state(phone)
    assert state["fields"].get("service_key") == "sunset_cruise"
    assert state["fields"].get("date") == _FUTURE_DATE
    assert state["fields"].get("guests") == "4"
    _cleanup_phone(phone)


# --- Test 5: wa_get_booking_state returns last_activity ---

def test_wa_get_booking_state_returns_last_activity():
    """wa_get_booking_state includes last_activity field."""
    phone = "TEST_073_LA_001"
    _cleanup_phone(phone)
    state_registry.wa_save_booking_state(phone, {}, {})
    result = state_registry.wa_get_booking_state(phone)
    assert "last_activity" in result
    assert result["last_activity"] is not None
    # Verify it's a valid ISO timestamp
    parsed = datetime.fromisoformat(result["last_activity"])
    assert parsed.year >= 2026
    _cleanup_phone(phone)


# --- Test 6: wa_cleanup_stale_data ---

def test_wa_cleanup_stale_data():
    """Old whatsapp_threads and whatsapp_processed rows are cleaned up."""
    phone = "TEST_073_CLEANUP_001"
    _cleanup_phone(phone)
    conn = state_registry._get_conn()
    # Insert old thread row (60 days ago)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    conn.execute("INSERT INTO whatsapp_threads (phone, role, text, created_at) VALUES (?, ?, ?, ?)",
                 (phone, "user", "old message", old_ts))
    # Insert old processed row (14 days ago)
    conn.execute("INSERT OR IGNORE INTO whatsapp_processed (message_id, created_at) VALUES (?, ?)",
                 ("wamid_old_073", old_ts))
    # Insert recent thread row (1 hour ago)
    recent_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("INSERT INTO whatsapp_threads (phone, role, text, created_at) VALUES (?, ?, ?, ?)",
                 (phone, "user", "recent message", recent_ts))
    # Insert recent processed row (1 hour ago)
    conn.execute("INSERT OR IGNORE INTO whatsapp_processed (message_id, created_at) VALUES (?, ?)",
                 ("wamid_recent_073", recent_ts))
    conn.commit()
    conn.close()

    result = state_registry.wa_cleanup_stale_data()
    assert result["threads_cleaned"] >= 1
    assert result["processed_cleaned"] >= 1

    # Verify recent rows survived
    conn = state_registry._get_conn()
    row = conn.execute("SELECT COUNT(*) FROM whatsapp_threads WHERE phone = ?", (phone,)).fetchone()
    assert row[0] >= 1  # recent row survives
    row = conn.execute("SELECT COUNT(*) FROM whatsapp_processed WHERE message_id = ?",
                       ("wamid_recent_073",)).fetchone()
    assert row[0] == 1  # recent row survives
    conn.close()

    # Cleanup
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_processed WHERE message_id IN ('wamid_old_073', 'wamid_recent_073')")
    conn.commit()
    conn.close()


# --- Test 7: Change detection cancels hold ---

@patch("agents.social.social_agent.gws_calendar.remove_from_manifest")
@patch("agents.social.social_agent.gws_calendar.check_availability")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_change_detection_cancels_hold(mock_process, mock_avail, mock_remove):
    """Customer changing details mid-confirmation cancels hold and resets slot flags."""
    phone = "TEST_073_CHANGE_001"
    _cleanup_phone(phone)
    # Create real soft hold
    hold_id = state_registry.create_soft_hold("west_coast_beach", _NEXT_WED, "09:00", 2, 25,
                                               customer_name="Test", customer_email=phone)
    assert hold_id is not None
    fields = {"service_key": "west_coast_beach", "service_name": "West Coast Beach",
              "date": _NEXT_WED, "guests": "2", "slot_time": "09:00",
              "customer_name": "Test"}
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True, "hold_id": hold_id,
             "hold_service_key": "west_coast_beach", "hold_date": _NEXT_WED,
             "hold_slot_time": "09:00"}
    state_registry.wa_save_booking_state(phone, fields, flags)

    # Customer changes details — Python pops awaiting_booking_confirmation, _was_awaiting triggers change detection
    mock_process.return_value = _base_result(
        intents=["booking"],
        fields={"date": "2026-12-25"},
        reply="Sure, let me check March 25.",
        flags={"awaiting_booking_confirmation": False},
    )
    # Post-validate will re-trigger with new date — mock check_availability to prevent new hold
    mock_avail.return_value = {"available": False, "spots_remaining": 0, "capacity": 25}
    msg = {"from": phone, "text": "Actually, make it March 25", "from_name": "Test"}
    handle_incoming_whatsapp_message(msg)
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("slot_checked") is False
    assert state["flags"].get("slot_available") is False
    assert "hold_id" not in state["flags"]
    assert "hold_service_key" not in state["flags"]
    # remove_from_manifest called with correct args (from change detection)
    mock_remove.assert_called_once_with("west_coast_beach", _NEXT_WED, "09:00")
    _cleanup_phone(phone)


# --- Test 8: Manifest failure cancels hold ---

@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_manifest_failure_cancels_hold(mock_process, mock_cal, mock_pay, mock_sheets):
    """Manifest creation failure cancels hold, uses reply_hold_failed, logs to Sheets."""
    phone = "TEST_073_MANIFEST_001"
    _cleanup_phone(phone)
    # Pre-set: booking confirmed + hold created
    hold_id = state_registry.create_soft_hold("west_coast_beach", _NEXT_WED, "09:00", 2, 25,
                                               customer_name="Test", customer_email=phone)
    fields = {"service_key": "west_coast_beach", "service_name": "West Coast Beach",
              "date": _NEXT_WED, "guests": "2", "slot_time": "09:00",
              "customer_name": "Test"}
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True, "hold_id": hold_id,
             "hold_service_key": "west_coast_beach", "hold_date": _NEXT_WED,
             "hold_slot_time": "09:00"}
    state_registry.wa_save_booking_state(phone, fields, flags)

    mock_process.return_value = _base_result(
        intents=["booking"],
        fields={},
        reply="Congrats! Ref [BOOKING_REF]. Pay: [PAYMENT_LINK]",
        flags={"booking_confirmed": True, "awaiting_booking_confirmation": False},
    )
    mock_process.return_value["reply_hold_failed"] = "Sorry, couldn't book"
    mock_cal.create_or_update_manifest.return_value = {"ok": False, "error": "calendar API error"}
    mock_cal.remove_from_manifest = MagicMock()

    msg = {"from": phone, "text": "Yes, book it!", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert "Sorry, couldn't book" in reply
    # Hold cancelled
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("slot_checked") is False
    assert state["flags"].get("slot_available") is False
    # Sheets logging
    mock_sheets.log_hold_failed.assert_called_once()
    _cleanup_phone(phone)


# --- Test 9: Hold race condition ---

@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_hold_race_condition(mock_process, mock_cal, mock_sheets):
    """Race: availability check passes but create_soft_hold returns None — fully booked reply."""
    phone = "TEST_073_RACE_001"
    _cleanup_phone(phone)
    mock_process.return_value = _base_result(
        intents=["booking"],
        fields={"service_key": "west_coast_beach", "service_name": "West Coast Beach",
                "date": _NEXT_WED, "guests": "2", "slot_time": "09:00",
                "customer_name": "Test"},
        reply="Sounds good!",
    )
    mock_cal.check_availability.return_value = {"available": True, "spots_remaining": 10, "capacity": 25}
    # Patch create_soft_hold on the state_registry module used by social_agent
    with patch("agents.social.social_agent.state_registry.create_soft_hold", return_value=None):
        msg = {"from": phone, "text": "Book West Coast Beach March 18 for 2", "from_name": "Test"}
        reply = handle_incoming_whatsapp_message(msg)
    assert "fully booked" in reply.lower()
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("awaiting_booking_confirmation") is not True
    assert "hold_id" not in state["flags"]
    _cleanup_phone(phone)


# --- Test 10: Empty reply returns empty ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_empty_reply_returns_empty(mock_process):
    """Empty reply from marina_agent returns empty string, persisted state unchanged."""
    phone = "TEST_073_EMPTY_001"
    _cleanup_phone(phone)
    # Pre-set fields
    fields = {"service_key": "sunset_cruise", "customer_name": "Test"}
    flags = {}
    state_registry.wa_save_booking_state(phone, fields, flags)

    mock_process.return_value = _base_result(
        reply="",
    )
    msg = {"from": phone, "text": "...", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == ""
    # Persisted state unchanged — early return at line 335 skips wa_save_booking_state
    state = state_registry.wa_get_booking_state(phone)
    assert state["fields"].get("service_key") == "sunset_cruise"
    assert state["fields"].get("customer_name") == "Test"
    _cleanup_phone(phone)
