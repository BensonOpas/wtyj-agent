# bluemarlin/tests/social/test_074_semi_ratelimit.py
# Created: Brief 074
# Purpose: Tests for semi-escalation → full escalation promotion and rate limit bump to 50

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


# --- Test 1: Semi-escalation creates relay ---

@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_semi_creates_relay(mock_process, mock_sheets):
    """Semi-escalation sets relay flags, not fully_escalated."""
    phone = "TEST_074_SEMI_001"
    _cleanup_phone(phone)
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="I'll check with the team!",
        semi_escalation=True,
        relay_question="Is 9pH water available on board?",
    )
    msg = {"from": phone, "text": "Do you have 9pH water?", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == "I'll check with the team!"
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("awaiting_relay") is True
    assert state["flags"].get("relay_token") is not None
    assert len(state["flags"]["relay_token"]) == 12
    assert "fully_escalated" not in state["flags"]
    _cleanup_phone(phone)


# --- Test 2: Semi-escalation with hold cancels hold ---

@patch("agents.social.social_agent.gws_calendar.remove_from_manifest")
@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_semi_with_hold_cancels_and_creates_relay(mock_process, mock_sheets, mock_remove):
    """Semi-escalation cancels soft hold and sets relay flags."""
    phone = "TEST_074_SEMI_002"
    _cleanup_phone(phone)
    fields = {"service_key": "west_coast_beach", "service_name": "West Coast Beach Trip",
              "date": "2026-03-18", "guests": "2", "slot_time": "09:00"}
    hold_id = state_registry.create_soft_hold("west_coast_beach", "2026-03-18", "09:00", 2, 25,
                                               customer_name="Test", customer_email=phone)
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True, "hold_id": hold_id,
             "hold_service_key": "west_coast_beach", "hold_date": "2026-03-18",
             "hold_slot_time": "09:00"}
    state_registry.wa_save_booking_state(phone, fields, flags)
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="Let me check on that!",
        semi_escalation=True,
        relay_question="Can I bring my own snorkel?",
    )
    msg = {"from": phone, "text": "Can I bring my own snorkel?", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    state = state_registry.wa_get_booking_state(phone)
    assert "hold_id" not in state["flags"]
    assert state["flags"].get("awaiting_relay") is True
    assert state["flags"].get("slot_checked") is False
    mock_remove.assert_called_once_with("west_coast_beach", "2026-03-18", "09:00")
    _cleanup_phone(phone)


# --- Test 3: Semi-escalation logs correctly to Sheets ---

@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_semi_escalation_sheets_logging(mock_process, mock_sheets):
    """Sheets intent is semi_escalation, internal_note contains relay question."""
    phone = "TEST_074_SEMI_003"
    _cleanup_phone(phone)
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="Checking with the crew!",
        semi_escalation=True,
        relay_question="Is 9pH water available?",
    )
    msg = {"from": phone, "text": "9pH water?", "from_name": "Test"}
    handle_incoming_whatsapp_message(msg)
    assert mock_sheets.call_count == 1
    sheets_data = mock_sheets.call_args[0][0]
    assert sheets_data["intent"] == "semi_escalation"
    assert "Relay question: Is 9pH water available?" in sheets_data["internal_note"]
    _cleanup_phone(phone)


# --- Test 4: Post-semi-escalation goes through fully-escalated guard ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_post_semi_goes_through_escalated_guard(mock_process):
    """After full escalation, next message hits fully-escalated guard."""
    phone = "TEST_074_POST_001"
    _cleanup_phone(phone)
    state_registry.wa_save_booking_state(phone,
        {"customer_name": "Test"},
        {"fully_escalated": True})
    mock_process.return_value = _base_result(
        reply="Our team is looking into this!",
    )
    msg = {"from": phone, "text": "Any update on my question?", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == "Our team is looking into this!"
    assert mock_process.call_count == 1
    state = state_registry.wa_get_booking_state(phone)
    assert "booking_ref" not in state["flags"]
    assert state["flags"].get("fully_escalated") is True
    _cleanup_phone(phone)


# --- Test 5: Rate limit at 50 blocks ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_rate_limit_50_blocks(mock_process):
    """50 reply_times within the hour → rate limited, empty reply."""
    phone = "TEST_074_RATE_001"
    _cleanup_phone(phone)
    now = int(time.time())
    reply_times = [now - i * 60 for i in range(50)]
    state_registry.wa_save_booking_state(phone, {}, {"reply_times": reply_times})
    msg = {"from": phone, "text": "Hello", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == ""
    assert mock_process.call_count == 0
    _cleanup_phone(phone)


# --- Test 6: Rate limit at 49 allows ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_rate_limit_49_allows(mock_process):
    """49 reply_times within the hour → still under limit, call proceeds."""
    phone = "TEST_074_RATE_002"
    _cleanup_phone(phone)
    now = int(time.time())
    reply_times = [now - i * 60 for i in range(49)]
    state_registry.wa_save_booking_state(phone, {}, {"reply_times": reply_times})
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="Happy to help!",
    )
    msg = {"from": phone, "text": "Hi there", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == "Happy to help!"
    assert mock_process.call_count == 1
    _cleanup_phone(phone)
