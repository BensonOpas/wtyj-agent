# bluemarlin/tests/social/test_069_whatsapp_agent.py
# Created: Brief 069
# Purpose: Tests for WhatsApp channel support + state foundation

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ["WHATSAPP_VERIFY_TOKEN"] = "test_token_067"
os.environ["WHATSAPP_ACCESS_TOKEN"] = "test_access_token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "990622044139349"

from agents.marina.marina_agent import _build_system_prompt, _build_user_prompt, process_message
from agents.social.social_agent import handle_incoming_whatsapp_message
from shared import state_registry


# --- Helpers ---

def _cleanup_phone(phone):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


# --- marina_agent channel tests ---

def test_system_prompt_whatsapp_style():
    """WhatsApp system prompt has WhatsApp style, no agent signature."""
    prompt = _build_system_prompt({}, channel="whatsapp")
    assert "WHATSAPP" in prompt
    assert "AGENT SIGNATURE" not in prompt
    assert "Marina" in prompt
    assert "BlueFinn" in prompt


def test_system_prompt_email_default():
    """Default (email) system prompt has agent signature, no WHATSAPP."""
    prompt = _build_system_prompt({})
    assert "AGENT SIGNATURE" in prompt
    assert "WHATSAPP" not in prompt


def test_user_prompt_whatsapp_no_subject():
    """WhatsApp user prompt has no Subject line, uses Text instead of Body."""
    prompt = _build_user_prompt("5991234567", "", "Hello", {}, {},
                                 channel="whatsapp")
    assert "Subject:" not in prompt
    assert "Text:" in prompt


def test_user_prompt_whatsapp_with_history():
    """WhatsApp user prompt includes conversation history."""
    history = [
        {"role": "user", "text": "Hi there", "created_at": "2026-03-11T10:00:00"},
        {"role": "assistant", "text": "Hello! How can I help?", "created_at": "2026-03-11T10:00:05"},
    ]
    prompt = _build_user_prompt("5991234567", "", "What trips?", {}, {},
                                 channel="whatsapp", messages=history)
    assert "Customer: Hi there" in prompt
    assert "Marina: Hello! How can I help?" in prompt


def test_user_prompt_whatsapp_empty_history():
    """WhatsApp user prompt shows '(new conversation)' when no history."""
    prompt = _build_user_prompt("5991234567", "", "Hi", {}, {},
                                 channel="whatsapp", messages=[])
    assert "(new conversation)" in prompt


def test_user_prompt_email_has_subject():
    """Default (email) user prompt includes Subject line."""
    prompt = _build_user_prompt("test@test.com", "Booking inquiry", "Hello", {}, {})
    assert "Subject:" in prompt
    assert "Booking inquiry" in prompt


@patch("agents.marina.marina_agent.anthropic.Anthropic")
def test_process_message_whatsapp_success(mock_cls):
    """process_message with channel=whatsapp returns parsed reply."""
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=json.dumps({
        "intents": ["inquiry"], "fields": {}, "confidence": "high",
        "reply": "Klein Curacao is $120 per adult!",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }))]
    mock_resp.usage = MagicMock(input_tokens=500, output_tokens=30)
    mock_cls.return_value.messages.create.return_value = mock_resp

    result = process_message("5991234567", "", "How much?", {}, {},
                              channel="whatsapp")
    assert result["reply"] == "Klein Curacao is $120 per adult!"


@patch("agents.marina.marina_agent.anthropic.Anthropic")
def test_process_message_whatsapp_failure_empty_reply(mock_cls):
    """WhatsApp API failure returns empty reply (silence > canned response)."""
    mock_cls.return_value.messages.create.side_effect = Exception("API down")
    result = process_message("5991234567", "", "Hello", {}, {},
                              channel="whatsapp")
    assert result["reply"] == ""


# --- state_registry conversation history tests ---

def test_wa_store_and_retrieve_messages():
    """Store 3 messages, retrieve in chronological order."""
    phone = "TEST_069_STORE_001"
    _cleanup_phone(phone)
    state_registry.wa_store_message(phone, "user", "Hello")
    state_registry.wa_store_message(phone, "assistant", "Hi there!")
    state_registry.wa_store_message(phone, "user", "What trips?")
    history = state_registry.wa_get_history(phone)
    assert len(history) == 3
    assert history[0]["role"] == "user"
    assert history[0]["text"] == "Hello"
    assert history[1]["role"] == "assistant"
    assert history[1]["text"] == "Hi there!"
    assert history[2]["text"] == "What trips?"
    _cleanup_phone(phone)


def test_wa_history_limit():
    """Store 15, retrieve 10 most recent."""
    phone = "TEST_069_LIMIT_001"
    _cleanup_phone(phone)
    for i in range(15):
        state_registry.wa_store_message(phone, "user", f"Message {i}")
    history = state_registry.wa_get_history(phone, limit=10)
    assert len(history) == 10
    assert history[0]["text"] == "Message 5"
    assert history[9]["text"] == "Message 14"
    _cleanup_phone(phone)


def test_wa_history_24h_expiry():
    """Messages older than 24h excluded."""
    phone = "TEST_069_EXPIRY_001"
    _cleanup_phone(phone)
    old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    conn = state_registry._get_conn()
    conn.execute(
        "INSERT INTO whatsapp_threads (phone, role, text, created_at) VALUES (?, ?, ?, ?)",
        (phone, "user", "Old message", old_time)
    )
    conn.commit()
    conn.close()
    state_registry.wa_store_message(phone, "user", "Recent message")
    history = state_registry.wa_get_history(phone)
    assert len(history) == 1
    assert history[0]["text"] == "Recent message"
    _cleanup_phone(phone)


# --- state_registry booking state tests ---

def test_wa_booking_state_fresh():
    """Fresh phone returns empty state."""
    phone = "TEST_069_FRESH_001"
    _cleanup_phone(phone)
    state = state_registry.wa_get_booking_state(phone)
    assert state == {"fields": {}, "flags": {}, "completed_bookings": [], "last_activity": None}


def test_wa_booking_state_round_trip():
    """Save and retrieve booking state."""
    phone = "TEST_069_STATE_001"
    _cleanup_phone(phone)
    fields = {"trip_key": "klein_curacao", "guests": "4", "date": "2026-03-15"}
    flags = {"slot_checked": True}
    state_registry.wa_save_booking_state(phone, fields, flags)
    state = state_registry.wa_get_booking_state(phone)
    assert state["fields"]["trip_key"] == "klein_curacao"
    assert state["fields"]["guests"] == "4"
    assert state["flags"]["slot_checked"] is True
    assert state["completed_bookings"] == []
    _cleanup_phone(phone)


# --- social_agent integration tests ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_social_agent_strips_placeholders(mock_process):
    """social_agent strips [BOOKING_REF] and [PAYMENT_LINK] from reply."""
    mock_process.return_value = {
        "intents": ["booking"], "fields": {}, "confidence": "high",
        "reply": "Booked! Ref [BOOKING_REF]. Pay here: [PAYMENT_LINK]",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }
    msg = {"from": "5991234567", "text": "Book it", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert "[BOOKING_REF]" not in reply
    assert "[PAYMENT_LINK]" not in reply
    assert "Booked!" in reply


@patch("agents.social.social_agent.marina_agent.process_message")
def test_social_agent_persists_state(mock_process):
    """social_agent persists extracted fields to booking state."""
    phone = "TEST_069_PERSIST_001"
    _cleanup_phone(phone)
    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {"trip_key": "sunset_cruise", "guests": "2"},
        "confidence": "high",
        "reply": "Sunset cruise for 2, got it!",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }
    msg = {"from": phone, "text": "Sunset for 2", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == "Sunset cruise for 2, got it!"
    state = state_registry.wa_get_booking_state(phone)
    assert state["fields"]["trip_key"] == "sunset_cruise"
    assert state["fields"]["guests"] == "2"
    _cleanup_phone(phone)


@patch("agents.social.social_agent.marina_agent.process_message")
def test_social_agent_api_failure_empty(mock_process):
    """social_agent returns empty string when marina_agent returns empty reply."""
    mock_process.return_value = {
        "intents": ["inquiry"], "fields": {}, "confidence": "low",
        "reply": "",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": "Fallback"
    }
    msg = {"from": "5991234567", "text": "Hello", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == ""


# --- Webhook conversation storage test ---

def test_webhook_stores_conversation():
    """Webhook pipeline stores user + assistant messages in history."""
    from fastapi.testclient import TestClient
    from agents.social.webhook_server import app

    test_phone = "TEST_069_WEBHOOK_001"
    test_msg_id = "wamid.TEST_069_WEBHOOK_STORE"
    _cleanup_phone(test_phone)

    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_processed WHERE message_id = ?", (test_msg_id,))
    conn.commit()
    conn.close()

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "967346842390828", "changes": [{"value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "15551681192", "phone_number_id": "990622044139349"},
            "contacts": [{"profile": {"name": "Test"}, "wa_id": test_phone}],
            "messages": [{"from": test_phone, "id": test_msg_id, "timestamp": "1773300000",
                          "text": {"body": "What trips?"}, "type": "text"}]
        }, "field": "messages"}]}]
    }

    client = TestClient(app)
    with patch("agents.social.webhook_server.send_text_message") as mock_send, \
         patch("agents.social.webhook_server.handle_incoming_whatsapp_message",
               return_value="We have Klein Curaçao and more!"):
        mock_send.return_value = True
        r = client.post("/webhooks/meta/whatsapp", json=payload)
        assert r.status_code == 200

    history = state_registry.wa_get_history(test_phone)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["text"] == "What trips?"
    assert history[1]["role"] == "assistant"
    assert history[1]["text"] == "We have Klein Curaçao and more!"
    _cleanup_phone(test_phone)
