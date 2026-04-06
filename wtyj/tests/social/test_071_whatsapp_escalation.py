# bluemarlin/tests/social/test_071_whatsapp_escalation.py
# Created: Brief 071
# Purpose: Tests for WhatsApp escalation (semi, full, fully-escalated guard)

import os
import sys
import json
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


# --- Test 1: Fully escalated guard returns holding reply ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_fully_escalated_guard_returns_holding_reply(mock_process):
    """Fully escalated thread returns Claude's holding reply, skips booking flow."""
    phone = "TEST_071_ESC_001"
    _cleanup_phone(phone)
    state_registry.wa_save_booking_state(phone, {}, {"fully_escalated": True})
    mock_process.return_value = _base_result(
        reply="Our team is looking into this!",
    )
    msg = {"from": phone, "text": "Any update?", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == "Our team is looking into this!"
    assert mock_process.call_count == 1
    _cleanup_phone(phone)


# --- Test 2: Fully escalated guard filters relay flags ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_fully_escalated_guard_filters_relay_flags(mock_process):
    """Fully escalated guard removes relay flags before calling marina_agent."""
    phone = "TEST_071_ESC_002"
    _cleanup_phone(phone)
    state_registry.wa_save_booking_state(phone, {}, {
        "fully_escalated": True,
        "awaiting_relay": True,
        "relay_token": "abc123",
        "relay_question": "weight limit?",
    })
    mock_process.return_value = _base_result(
        reply="Still working on it!",
    )
    msg = {"from": phone, "text": "Hello?", "from_name": "Test"}
    handle_incoming_whatsapp_message(msg)
    # Check what was passed to marina_agent
    call_kwargs = mock_process.call_args
    passed_flags = call_kwargs.kwargs.get("thread_flags", {})
    assert "awaiting_relay" not in passed_flags
    assert "relay_token" not in passed_flags
    assert "relay_question" not in passed_flags
    assert passed_flags.get("fully_escalated") is True
    _cleanup_phone(phone)


# --- Test 3: Semi-escalation creates relay ---

@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_semi_escalation_sets_relay_state(mock_process, mock_sheets):
    """Semi-escalation sets relay flags and returns Claude's holding reply."""
    phone = "TEST_071_SEMI_001"
    _cleanup_phone(phone)
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="Let me check with the team on that!",
        internal_note="Weight limit question",
        semi_escalation=True,
        relay_question="What is the weight limit for jet skis?",
    )
    msg = {"from": phone, "text": "What's the weight limit for jet skis?", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == "Let me check with the team on that!"
    # Check state — relay flags set, not fully_escalated
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("awaiting_relay") is True
    assert state["flags"].get("relay_token") is not None
    assert len(state["flags"]["relay_token"]) == 12
    assert "fully_escalated" not in state["flags"]
    # Sheets logged
    assert mock_sheets.call_count == 1
    _cleanup_phone(phone)


# --- Test 4: Semi-escalation cancels soft hold ---

@patch("agents.social.social_agent.gws_calendar.remove_from_manifest")
@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_semi_escalation_cancels_soft_hold(mock_process, mock_sheets, mock_remove):
    """Semi-escalation cancels any existing soft hold and resets slot flags."""
    phone = "TEST_071_SEMI_002"
    _cleanup_phone(phone)
    # Pre-set state with active soft hold
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
    # Check state — hold cancelled, slot flags reset
    state = state_registry.wa_get_booking_state(phone)
    assert "hold_id" not in state["flags"]
    assert state["flags"].get("slot_checked") is False
    assert state["flags"].get("slot_available") is False
    assert state["flags"].get("awaiting_booking_confirmation") is False
    assert state["flags"].get("awaiting_relay") is True
    # remove_from_manifest called with correct args
    mock_remove.assert_called_once_with("west_coast_beach", "2026-03-18", "09:00")
    _cleanup_phone(phone)


# --- Test 5: Semi-escalation overrides post-validate ---

@patch("agents.social.social_agent.gws_calendar.remove_from_manifest")
@patch("agents.social.social_agent.gws_calendar.check_availability")
@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_semi_escalation_overrides_post_validate(mock_process, mock_sheets, mock_avail, mock_remove):
    """Semi-escalation with booking fields: reply is holding reply, not booking summary."""
    phone = "TEST_071_SEMI_003"
    _cleanup_phone(phone)
    mock_process.return_value = _base_result(
        intents=["booking"],
        fields={"service_key": "west_coast_beach", "service_name": "West Coast Beach Trip",
                "date": "2026-03-18", "guests": "2"},
        reply="Let me check with the team on that!",
        semi_escalation=True,
        relay_question="Also what's the weight limit?",
    )
    mock_avail.return_value = {"available": True, "spots_remaining": 23, "capacity": 25}
    msg = {"from": phone, "text": "Book West Coast Beach March 18 for 2, also what's the weight limit?",
           "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    # Reply is Claude's holding reply, NOT the booking summary
    assert reply == "Let me check with the team on that!"
    assert "$240" not in reply  # No booking summary
    # State checks
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("awaiting_booking_confirmation") is False
    assert state["flags"].get("awaiting_relay") is True
    _cleanup_phone(phone)


# --- Test 6: Full escalation sets flag and logs ---

@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_full_escalation_sets_flag_and_logs(mock_process, mock_sheets):
    """Full escalation sets fully_escalated flag and logs to Sheets."""
    phone = "TEST_071_FULL_001"
    _cleanup_phone(phone)
    mock_process.return_value = _base_result(
        intents=["complaint"],
        reply="I'm sorry about that. I've passed this to our team.",
        requires_human=True,
        internal_note="Complaint about cancelled service",
    )
    msg = {"from": phone, "text": "I want a refund!", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == "I'm sorry about that. I've passed this to our team."
    # State checks
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("fully_escalated") is True
    # Sheets logged with correct data
    assert mock_sheets.call_count == 1
    sheets_data = mock_sheets.call_args[0][0]
    assert sheets_data["intent"] == "complaint"
    assert sheets_data["email"] == phone
    _cleanup_phone(phone)


# --- Test 7: Full escalation skips booking confirmation ---

@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.gws_calendar.check_availability")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_full_escalation_skips_booking_confirmation(mock_process, mock_avail, mock_sheets):
    """Full escalation with booking fields: no booking_ref, hold cancelled."""
    phone = "TEST_071_FULL_002"
    _cleanup_phone(phone)
    mock_process.return_value = _base_result(
        intents=["booking"],
        fields={"service_key": "west_coast_beach", "service_name": "West Coast Beach Trip",
                "date": "2026-03-18", "guests": "2"},
        reply="I've passed this along to our team.",
        requires_human=True,
        internal_note="Complex booking request needing human",
    )
    mock_avail.return_value = {"available": True, "spots_remaining": 23, "capacity": 25}
    msg = {"from": phone, "text": "Book this but I have special needs", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    # No booking confirmation happened
    state = state_registry.wa_get_booking_state(phone)
    assert "booking_ref" not in state["flags"]
    assert state["flags"].get("fully_escalated") is True
    assert "hold_id" not in state["flags"]  # Hold cancelled by full escalation
    assert state["flags"].get("slot_checked") is False  # Reset by full escalation
    _cleanup_phone(phone)


# --- Test 8: Relay flags filtered for normal message ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_relay_flags_filtered_for_normal_message(mock_process):
    """Relay flags are filtered before calling marina_agent for normal messages."""
    phone = "TEST_071_FILTER_001"
    _cleanup_phone(phone)
    state_registry.wa_save_booking_state(phone, {}, {
        "awaiting_relay": True,
        "relay_token": "abc123def456",
        "relay_question": "weight limit?",
    })
    mock_process.return_value = _base_result(
        reply="Happy to help with that!",
    )
    msg = {"from": phone, "text": "What trips do you offer?", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == "Happy to help with that!"
    # Check marina_agent was called without relay flags
    call_kwargs = mock_process.call_args
    passed_flags = call_kwargs.kwargs.get("thread_flags", {})
    assert "awaiting_relay" not in passed_flags
    assert "relay_token" not in passed_flags
    assert "relay_question" not in passed_flags
    _cleanup_phone(phone)
