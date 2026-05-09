"""Tests for Brief 163 — hold-vs-confirmed wording fix.

Covers:
- social_agent writes the correct system message text based on payment.timing
- marina_agent prompt contains the CONFIRMATION WORDING rule
- marina_agent prompt writing style examples use held language, not "All set!"
"""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from agents.marina import marina_agent
from agents.social import social_agent
from shared import state_registry


# --- Group A: prompt-level assertions (fast, no mocks) ---

def test_prompt_contains_confirmation_wording_rule_whatsapp():
    """The CONFIRMATION WORDING rule must appear in the WhatsApp-channel prompt."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "CONFIRMATION WORDING" in prompt, (
        "Brief 163: WhatsApp system prompt must contain the CONFIRMATION WORDING rule"
    )
    assert 'timing "upfront"' in prompt and 'timing "none"' in prompt, (
        "CONFIRMATION WORDING rule must reference both upfront and none timings"
    )
    assert "Forbidden words" in prompt
    assert "held-awaiting-payment" in prompt.lower() or "held" in prompt.lower()


def test_prompt_contains_confirmation_wording_rule_email():
    """The CONFIRMATION WORDING rule must appear in the email-channel prompt too."""
    prompt = marina_agent._build_system_prompt({}, channel="email")
    assert "CONFIRMATION WORDING" in prompt, (
        "Brief 163: email system prompt must contain the CONFIRMATION WORDING rule"
    )


def test_whatsapp_writing_style_no_longer_says_all_set():
    """Brief 163: the WhatsApp 'GOOD REPLIES' example must not use 'All set!' anymore."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    good_replies_idx = prompt.find("GOOD REPLIES")
    assert good_replies_idx >= 0, "Could not locate WhatsApp GOOD REPLIES block"
    bad_replies_idx = prompt.find("BAD REPLIES", good_replies_idx)
    good_block = prompt[good_replies_idx:bad_replies_idx]
    assert "All set!" not in good_block, (
        "Brief 163: WhatsApp GOOD REPLIES example must not use 'All set!' — "
        "that wording implies the booking is done when it isn't (payment pending)"
    )
    assert "held your spot" in good_block.lower() or "spot is held" in good_block.lower(), (
        "Brief 163: WhatsApp GOOD REPLIES example must use held/held-your-spot language"
    )


def test_email_writing_style_no_longer_says_youre_all_set():
    """Brief 163: the email writing style example must not use 'You're all set!'.

    Scoped to the writing style block only — the CONFIRMATION WORDING rule
    legitimately references "You're all set" as a forbidden phrase, so a
    whole-prompt search would trip on the rule itself.
    """
    prompt = marina_agent._build_system_prompt({}, channel="email")
    style_idx = prompt.find("GOOD REPLY EXAMPLES")
    assert style_idx >= 0, "Could not locate email GOOD REPLY EXAMPLES block"
    # Style block ends at AVOID: or at BOOKING BEHAVIOUR, whichever comes first
    end_idx = prompt.find("AVOID:", style_idx)
    if end_idx < 0:
        end_idx = prompt.find("BOOKING BEHAVIOUR", style_idx)
    style_block = prompt[style_idx:end_idx]
    assert "You're all set" not in style_block, (
        "Brief 163: email writing style example must not use 'You're all set'"
    )
    assert "Hold placed" in style_block or "held your spot" in style_block.lower(), (
        "Brief 163: email writing style example must use hold/held wording"
    )


# --- Group B: social_agent system message assertions (integration, mocked) ---

_NEXT_FRI = "2027-12-17"  # A Friday far enough in the future to pass date validation


def _cleanup_phone(phone):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM service_bookings WHERE customer_email = ?", (phone,))
    conn.commit()
    conn.close()


@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
@patch("agents.social.social_agent.config_loader.get_raw")
def test_system_message_says_hold_placed_for_upfront_timing(mock_get_raw, mock_process, mock_cal, mock_pay, mock_sheets):
    """Brief 163: when payment.timing='upfront', the system message text is 'Hold placed — awaiting payment'."""
    phone = "TEST_163_UPFRONT_001"
    _cleanup_phone(phone)

    mock_get_raw.return_value = {
        "payment": {"timing": "upfront", "hold_duration_hours": 6},
        "business": {"name": "Test Charter", "agent_name": "Marina"},
        "booking_rules": {"hold_duration_hours": 6, "max_bookings_per_thread": 5},
    }

    fields = {
        "service_key": "west_coast_beach",
        "service_name": "West Coast Beach",
        "date": _NEXT_FRI,
        "guests": "2",
        "slot_time": "09:00",
        "customer_name": "Alice",
    }
    hold_id = state_registry.create_soft_hold(
        "west_coast_beach", _NEXT_FRI, "09:00", 2, 25,
        customer_name="Alice", customer_email=phone,
    )
    flags = {
        "awaiting_booking_confirmation": True,
        "slot_checked": True,
        "slot_available": True,
        "hold_id": hold_id,
        "hold_service_key": "west_coast_beach",
        "hold_date": _NEXT_FRI,
        "hold_slot_time": "09:00",
    }
    state_registry.wa_save_booking_state(phone, fields, flags)

    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {},
        "confidence": "high",
        "reply": "Got it — I've held your spot. Ref [BOOKING_REF]. Pay here: [PAYMENT_LINK] and I'll confirm as soon as it comes through.",
        "reply_hold_failed": "Sorry, that slot is no longer available.",
        "clarifications_needed": [],
        "requires_human": False,
        "flags": {"booking_confirmed": True, "awaiting_booking_confirmation": False},
        "internal_note": "",
    }
    mock_cal.create_or_update_manifest.return_value = {"ok": True, "eventId": "e163u", "htmlLink": "http://cal/e163u"}
    mock_pay.generate_payment_link.return_value = {"payment_id": "pay163u", "status": "pending"}

    msg = {"from": phone, "text": "Yes book it!", "from_name": "Alice"}
    social_agent.handle_incoming_whatsapp_message(msg)

    history = state_registry.wa_get_full_history(phone)
    sys_msgs = [h for h in history if h["role"] == "system"]
    assert sys_msgs, "No system message written after upfront-timing booking"
    latest = sys_msgs[-1]["text"]
    assert "Hold placed" in latest, (
        f"Brief 163: upfront-timing system message must start with 'Hold placed', got: {latest!r}"
    )
    assert "Booking confirmed" not in latest, (
        f"Brief 163: upfront-timing system message must NOT say 'Booking confirmed', got: {latest!r}"
    )
    _cleanup_phone(phone)


@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
@patch("agents.social.social_agent.config_loader.get_raw")
def test_system_message_says_booking_confirmed_for_none_timing(mock_get_raw, mock_process, mock_cal, mock_pay, mock_sheets):
    """Brief 163: when payment.timing='none' (restaurant), the system message text is 'Booking confirmed'."""
    phone = "TEST_163_NONE_001"
    _cleanup_phone(phone)

    mock_get_raw.return_value = {
        "payment": {"timing": "none", "hold_duration_hours": 4},
        "business": {"name": "Test Restaurant", "agent_name": "Sofia"},
        "booking_rules": {"hold_duration_hours": 4, "max_bookings_per_thread": 5},
    }

    fields = {
        "service_key": "west_coast_beach",
        "service_name": "West Coast Beach",
        "date": _NEXT_FRI,
        "guests": "2",
        "slot_time": "09:00",
        "customer_name": "Bob",
    }
    hold_id = state_registry.create_soft_hold(
        "west_coast_beach", _NEXT_FRI, "09:00", 2, 25,
        customer_name="Bob", customer_email=phone,
    )
    flags = {
        "awaiting_booking_confirmation": True,
        "slot_checked": True,
        "slot_available": True,
        "hold_id": hold_id,
        "hold_service_key": "west_coast_beach",
        "hold_date": _NEXT_FRI,
        "hold_slot_time": "09:00",
    }
    state_registry.wa_save_booking_state(phone, fields, flags)

    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {},
        "confidence": "high",
        "reply": "All set! Your reservation is confirmed. Ref [BOOKING_REF]. See you Friday!",
        "reply_hold_failed": "Sorry, that slot is no longer available.",
        "clarifications_needed": [],
        "requires_human": False,
        "flags": {"booking_confirmed": True, "awaiting_booking_confirmation": False},
        "internal_note": "",
    }
    mock_cal.create_or_update_manifest.return_value = {"ok": True, "eventId": "e163n", "htmlLink": "http://cal/e163n"}
    mock_pay.generate_payment_link.return_value = {"payment_id": "unused", "status": "not_required"}

    msg = {"from": phone, "text": "Yes book it!", "from_name": "Bob"}
    social_agent.handle_incoming_whatsapp_message(msg)

    history = state_registry.wa_get_full_history(phone)
    sys_msgs = [h for h in history if h["role"] == "system"]
    assert sys_msgs, "No system message written after none-timing booking"
    latest = sys_msgs[-1]["text"]
    assert "Booking confirmed" in latest, (
        f"Brief 163: none-timing system message must start with 'Booking confirmed', got: {latest!r}"
    )
    assert "Hold placed" not in latest, (
        f"Brief 163: none-timing system message must NOT say 'Hold placed', got: {latest!r}"
    )
    _cleanup_phone(phone)


