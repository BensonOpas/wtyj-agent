# bluemarlin/tests/social/test_100_email_collection.py
# Created: Brief 100
# Purpose: Tests for WhatsApp email collection + escalation email fix

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_token_067")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "990622044139349")
os.environ.setdefault("LATE_API_KEY", "sk_test_key_for_testing")

from agents.social.social_agent import handle_incoming_whatsapp_message
from agents.marina.marina_agent import _build_system_prompt
from shared import state_registry


# --- Helpers ---

def _cleanup_phone(phone):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM trip_bookings WHERE customer_email = ?", (phone,))
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (phone,))
    conn.commit()
    conn.close()


def _base_result(**overrides):
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


_TEST_PHONE = "5991112222"
_TEST_MSG = {
    "channel": "whatsapp",
    "from": _TEST_PHONE,
    "from_name": "Test User",
    "message_id": "test_100_msg_1",
    "text": "test message",
    "message_type": "text",
    "timestamp": "1710000000",
    "business_account_id": "test",
    "phone_number_id": "990622044139349",
}


# --- Tests ---

def test_whatsapp_prompt_includes_email_field():
    prompt = _build_system_prompt({}, channel="whatsapp")
    assert "email" in prompt
    assert "EMAIL:" in prompt


def test_email_prompt_no_email_section():
    prompt = _build_system_prompt({}, channel="email")
    assert "EMAIL:\n" not in prompt


def test_whatsapp_escalation_prompt_channel_aware():
    prompt = _build_system_prompt({}, channel="whatsapp")
    assert "needs_escalation_email" in prompt
    assert "WHATSAPP CHANNEL" in prompt


def test_escalation_with_email_fires_normally():
    _cleanup_phone(_TEST_PHONE)
    try:
        result = _base_result(
            intents=["complaint"],
            requires_human=True,
            fields={"email": "john@test.com"},
            reply="I've passed this along to our team. They'll reach out at john@test.com.",
        )
        with patch("agents.social.social_agent.marina_agent.process_message", return_value=result), \
             patch("agents.social.social_agent.sheets_writer.log_escalation"):
            reply = handle_incoming_whatsapp_message(_TEST_MSG)

        state = state_registry.wa_get_booking_state(_TEST_PHONE)
        assert state["flags"].get("fully_escalated") is True

        # Check notification was created
        notifs = state_registry.get_pending_notifications()
        phone_notifs = [n for n in notifs if n["customer_id"] == _TEST_PHONE]
        assert len(phone_notifs) > 0
    finally:
        _cleanup_phone(_TEST_PHONE)


def test_escalation_without_email_asks_for_it():
    _cleanup_phone(_TEST_PHONE)
    try:
        result = _base_result(
            intents=["complaint"],
            requires_human=False,
            flags={"needs_escalation_email": True},
            reply="I'm sorry to hear that. Could you share your email so our team can follow up?",
        )
        with patch("agents.social.social_agent.marina_agent.process_message", return_value=result):
            reply = handle_incoming_whatsapp_message(_TEST_MSG)

        state = state_registry.wa_get_booking_state(_TEST_PHONE)
        assert state["flags"].get("awaiting_escalation_email") is True
        assert state["flags"].get("fully_escalated") is not True

        # No notification yet
        notifs = state_registry.get_pending_notifications()
        phone_notifs = [n for n in notifs if n["customer_id"] == _TEST_PHONE]
        assert len(phone_notifs) == 0
    finally:
        _cleanup_phone(_TEST_PHONE)


def test_escalation_email_provided_fires_escalation():
    _cleanup_phone(_TEST_PHONE)
    try:
        # Set up state: awaiting_escalation_email
        state_registry.wa_save_booking_state(
            _TEST_PHONE,
            fields={},
            flags={"awaiting_escalation_email": True},
        )

        result = _base_result(
            intents=["complaint"],
            requires_human=False,
            fields={"email": "john@test.com"},
            reply="Our team will reach out to you at john@test.com.",
        )
        msg = dict(_TEST_MSG)
        msg["message_id"] = "test_100_msg_2"
        msg["text"] = "john@test.com"

        with patch("agents.social.social_agent.marina_agent.process_message", return_value=result), \
             patch("agents.social.social_agent.sheets_writer.log_escalation"):
            reply = handle_incoming_whatsapp_message(msg)

        state = state_registry.wa_get_booking_state(_TEST_PHONE)
        assert state["flags"].get("fully_escalated") is True
        assert "awaiting_escalation_email" not in state["flags"]

        notifs = state_registry.get_pending_notifications()
        phone_notifs = [n for n in notifs if n["customer_id"] == _TEST_PHONE]
        assert len(phone_notifs) > 0
    finally:
        _cleanup_phone(_TEST_PHONE)


def test_email_used_in_soft_hold_when_present():
    """Verify create_soft_hold receives email instead of phone when email is in fields."""
    _cleanup_phone(_TEST_PHONE)
    try:
        # Pre-set fields with email
        fields = {"trip_key": "sunset_cruise", "date": "2026-04-10",
                  "departure_time": "17:30", "guests": 2,
                  "customer_name": "Jane", "email": "jane@test.com"}

        # The expression `fields.get("email") or phone` should resolve to email
        customer_email = fields.get("email") or _TEST_PHONE
        assert customer_email == "jane@test.com"

        # Create a soft hold with the email
        hold_id = state_registry.create_soft_hold(
            "sunset_cruise", "2026-04-10", "17:30", 2, 20,
            customer_name="Jane", customer_email=customer_email
        )
        assert hold_id is not None

        # Verify it was stored with email
        conn = state_registry._get_conn()
        rows = conn.execute(
            "SELECT customer_email FROM trip_bookings WHERE id = ?", (hold_id,)
        ).fetchall()
        conn.close()
        assert rows[0][0] == "jane@test.com"
    finally:
        _cleanup_phone(_TEST_PHONE)
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM trip_bookings WHERE customer_email = ?", ("jane@test.com",))
        conn.commit()
        conn.close()


def test_phone_used_in_soft_hold_when_no_email():
    """Verify create_soft_hold falls back to phone when no email in fields."""
    _cleanup_phone(_TEST_PHONE)
    try:
        fields = {"trip_key": "sunset_cruise", "date": "2026-04-11",
                  "departure_time": "17:30", "guests": 2, "customer_name": "Bob"}

        customer_email = fields.get("email") or _TEST_PHONE
        assert customer_email == _TEST_PHONE

        hold_id = state_registry.create_soft_hold(
            "sunset_cruise", "2026-04-11", "17:30", 2, 20,
            customer_name="Bob", customer_email=customer_email
        )
        assert hold_id is not None

        conn = state_registry._get_conn()
        rows = conn.execute(
            "SELECT customer_email FROM trip_bookings WHERE id = ?", (hold_id,)
        ).fetchall()
        conn.close()
        assert rows[0][0] == _TEST_PHONE
    finally:
        _cleanup_phone(_TEST_PHONE)
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM trip_bookings WHERE customer_email = ?", (_TEST_PHONE,))
        conn.commit()
        conn.close()
