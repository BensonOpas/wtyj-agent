# bluemarlin/tests/social/test_077_relay_bridge.py
# Created: Brief 077
# Purpose: Tests for WhatsApp relay bridge and operator notification

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
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (phone,))
    conn.commit()
    conn.close()


def _cleanup_notification(customer_id):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (customer_id,))
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


# --- Test 1: create_pending_notification round-trip ---

def test_create_pending_notification_round_trip():
    """Create a pending notification and retrieve it."""
    customer_id = "TEST_077_NOTIF_001"
    _cleanup_notification(customer_id)
    row_id = state_registry.create_pending_notification(
        'relay', 'whatsapp', customer_id, 'Test User',
        '[RELAY-abc123def456] NO-REF - Test User', 'body text',
        relay_token='abc123def456')
    assert row_id > 0
    pending = state_registry.get_pending_notifications()
    match = [p for p in pending if p["customer_id"] == customer_id]
    assert len(match) == 1
    assert match[0]["notification_type"] == "relay"
    assert match[0]["channel"] == "whatsapp"
    assert match[0]["status"] == "pending"
    assert match[0]["relay_token"] == "abc123def456"
    _cleanup_notification(customer_id)


# --- Test 2: get_relay_by_token ---

def test_get_relay_by_token():
    """Look up relay by token, returns None for non-existent."""
    customer_id = "TEST_077_TOKEN_001"
    _cleanup_notification(customer_id)
    state_registry.create_pending_notification(
        'relay', 'whatsapp', customer_id, 'Test',
        '[RELAY-aaa111bbb222] NO-REF', 'body',
        relay_token='aaa111bbb222')
    result = state_registry.get_relay_by_token('aaa111bbb222')
    assert result is not None
    assert result["channel"] == "whatsapp"
    assert result["customer_id"] == customer_id
    # Non-existent token
    assert state_registry.get_relay_by_token('nonexistent1') is None
    _cleanup_notification(customer_id)


# --- Test 2b: get_relay_by_token filters out non-pending ---

def test_get_relay_by_token_ignores_replied():
    """get_relay_by_token returns None if notification already replied."""
    customer_id = "TEST_077_TOKEN_002"
    _cleanup_notification(customer_id)
    row_id = state_registry.create_pending_notification(
        'relay', 'whatsapp', customer_id, 'Test',
        '[RELAY-ddd444eee555] NO-REF', 'body',
        relay_token='ddd444eee555')
    # Pending → should find it
    assert state_registry.get_relay_by_token('ddd444eee555') is not None
    # Mark replied
    state_registry.update_notification_status(row_id, 'replied')
    # After replied → should NOT find it
    assert state_registry.get_relay_by_token('ddd444eee555') is None
    # 'sent' status should still be findable (operator hasn't replied yet)
    _cleanup_notification(customer_id)
    row_id2 = state_registry.create_pending_notification(
        'relay', 'whatsapp', customer_id, 'Test',
        '[RELAY-fff666ggg777] NO-REF', 'body',
        relay_token='fff666ggg777')
    state_registry.update_notification_status(row_id2, 'sent')
    assert state_registry.get_relay_by_token('fff666ggg777') is not None
    # Mark replied → NOW it should return None
    state_registry.update_notification_status(row_id2, 'replied')
    assert state_registry.get_relay_by_token('fff666ggg777') is None
    _cleanup_notification(customer_id)


# --- Test 2c: Booking decline does not re-send summary ---

@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_booking_decline_no_loop(mock_process, mock_sheets):
    """Customer saying 'no' to booking summary should not get summary again."""
    phone = "TEST_081_DECLINE_001"
    _cleanup_phone(phone)
    # Set up state: awaiting booking confirmation with all fields
    fields = {
        "trip_key": "sunset_cruise", "experience": "Sunset Cruise",
        "date": "2026-03-21", "guests": "4", "departure_time": "17:30",
        "customer_name": "Test Decline",
    }
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True}
    state_registry.wa_save_booking_state(phone, fields, flags)
    # Claude responds to "no" with decline — intent: inquiry, not booking
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="No problem! Would you like to look at other trips?",
        flags={"awaiting_booking_confirmation": False},
    )
    msg = {"from": phone, "text": "no thanks", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert "No problem" in reply
    assert "Just to confirm" not in reply  # Must NOT contain booking summary
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("awaiting_booking_confirmation") is not True
    _cleanup_phone(phone)


# --- Test 2e: Booking decline with booking intent still doesn't loop ---

@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_booking_decline_with_booking_intent_no_loop(mock_process, mock_sheets):
    """Even if Claude returns booking intent for a decline, guard prevents loop."""
    phone = "TEST_081_DECLINE_002"
    _cleanup_phone(phone)
    fields = {
        "trip_key": "sunset_cruise", "experience": "Sunset Cruise",
        "date": "2026-03-21", "guests": "4", "departure_time": "17:30",
        "customer_name": "Test Decline2",
    }
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True}
    state_registry.wa_save_booking_state(phone, fields, flags)
    # Claude returns booking intent but no new fields — decline scenario
    mock_process.return_value = _base_result(
        intents=["booking"],
        reply="Understood, no booking needed.",
        fields={},
        flags={"awaiting_booking_confirmation": False},
    )
    msg = {"from": phone, "text": "no", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert "Understood" in reply
    assert "Just to confirm" not in reply  # Must NOT re-send booking summary
    _cleanup_phone(phone)


# --- Test 2e: Relay notification uses WhatsApp profile name ---

@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_relay_notification_uses_profile_name(mock_process, mock_sheets):
    """When customer_name not in fields, relay notification uses WhatsApp profile name."""
    phone = "TEST_083_NAME_001"
    _cleanup_phone(phone)
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="Let me check with the team!",
        semi_escalation=True,
        relay_question="Is there shade on the boat?",
    )
    # from_name set, but no customer_name in fields
    msg = {"from": phone, "text": "Is there shade?", "from_name": "Jan de Vries"}
    handle_incoming_whatsapp_message(msg)
    pending = state_registry.get_pending_notifications()
    match = [p for p in pending if p["customer_id"] == phone]
    assert len(match) == 1
    assert "Jan de Vries" in match[0]["subject"]
    assert "Jan de Vries" in match[0]["body"]
    assert "Unknown" not in match[0]["subject"]
    _cleanup_phone(phone)


# --- Test 2f: User message stored even when reply is empty ---

def test_user_message_stored_on_empty_reply():
    """_flush_buffer stores user message even if handle returns empty reply."""
    from unittest.mock import patch as _p, MagicMock
    phone = "TEST_089_STORE_001"
    _cleanup_phone(phone)
    with _p("agents.social.webhook_server.handle_incoming_whatsapp_message", return_value="") as mock_handle, \
         _p("agents.social.webhook_server.send_text_message") as mock_send:
        from agents.social.webhook_server import _flush_buffer
        from agents.social import webhook_server
        webhook_server._message_buffers[phone] = {
            "messages": [{"from": phone, "text": "lost message", "from_name": "Test",
                          "message_id": "test_089"}],
            "timer": None,
            "started": 0,
        }
        _flush_buffer(phone)
    # Reply was empty — send should NOT be called
    mock_send.assert_not_called()
    # But user message MUST be stored in history
    history = state_registry.wa_get_history(phone, limit=10)
    user_msgs = [m for m in history if m["role"] == "user"]
    assert len(user_msgs) == 1
    assert "lost message" in user_msgs[0]["text"]
    _cleanup_phone(phone)


# --- Test 3: update_notification_status ---

def test_update_notification_status():
    """Update status from pending to sent."""
    customer_id = "TEST_077_STATUS_001"
    _cleanup_notification(customer_id)
    row_id = state_registry.create_pending_notification(
        'relay', 'whatsapp', customer_id, 'Test',
        'subject', 'body', relay_token='ccc333ddd444')
    assert state_registry.update_notification_status(row_id, 'sent') is True
    # Should not appear in pending
    pending = state_registry.get_pending_notifications('pending')
    assert not any(p["customer_id"] == customer_id for p in pending)
    # Should appear in sent
    sent = state_registry.get_pending_notifications('sent')
    assert any(p["customer_id"] == customer_id for p in sent)
    _cleanup_notification(customer_id)


# --- Test 4: Semi-escalation creates relay, not full escalation ---

@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_semi_creates_relay_not_full(mock_process, mock_sheets):
    """Semi-escalation sets awaiting_relay, not fully_escalated."""
    phone = "TEST_077_SEMI_001"
    _cleanup_phone(phone)
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="I'll check with the team!",
        semi_escalation=True,
        relay_question="Is 9pH water available?",
    )
    msg = {"from": phone, "text": "Do you have 9pH water?", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == "I'll check with the team!"
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("awaiting_relay") is True
    assert state["flags"].get("relay_token") is not None
    assert len(state["flags"]["relay_token"]) == 12
    assert state["flags"].get("relay_question") == "Is 9pH water available?"
    assert "fully_escalated" not in state["flags"]
    _cleanup_phone(phone)


# --- Test 5: Semi-escalation inserts pending notification ---

@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_semi_inserts_pending_notification(mock_process, mock_sheets):
    """Semi-escalation creates a relay notification in pending_notifications."""
    phone = "TEST_077_SEMI_002"
    _cleanup_phone(phone)
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="Let me check!",
        semi_escalation=True,
        relay_question="What if it rains?",
    )
    msg = {"from": phone, "text": "What if it rains?", "from_name": "Test"}
    handle_incoming_whatsapp_message(msg)
    pending = state_registry.get_pending_notifications()
    match = [p for p in pending if p["customer_id"] == phone]
    assert len(match) == 1
    assert match[0]["notification_type"] == "relay"
    assert match[0]["channel"] == "whatsapp"
    assert "[RELAY-" in match[0]["subject"]
    # Token consistency — notification token matches state token
    state = state_registry.wa_get_booking_state(phone)
    assert match[0]["relay_token"] == state["flags"]["relay_token"]
    _cleanup_phone(phone)


# --- Test 6: Full escalation inserts pending notification ---

@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_full_escalation_inserts_notification(mock_process, mock_sheets):
    """Full escalation creates an escalation notification in pending_notifications."""
    phone = "TEST_077_FULL_001"
    _cleanup_phone(phone)
    mock_process.return_value = _base_result(
        intents=["complaint"],
        reply="Let me get someone to help!",
        requires_human=True,
        internal_note="Customer unhappy about service",
    )
    msg = {"from": phone, "text": "I want to speak to a manager", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == "Let me get someone to help!"
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("fully_escalated") is True
    pending = state_registry.get_pending_notifications()
    match = [p for p in pending if p["customer_id"] == phone]
    assert len(match) == 1
    assert match[0]["notification_type"] == "escalation"
    assert "[ESCALATION]" in match[0]["subject"]
    assert match[0]["relay_token"] is None
    _cleanup_phone(phone)


# --- Test 7: Semi-escalation cancels soft hold ---

@patch("agents.social.social_agent.gws_calendar.remove_from_manifest")
@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_semi_cancels_soft_hold(mock_process, mock_sheets, mock_remove):
    """Semi-escalation cancels soft hold and sets relay flags."""
    phone = "TEST_077_HOLD_001"
    _cleanup_phone(phone)
    hold_id = state_registry.create_soft_hold("west_coast_beach", "2026-03-18", "09:00", 2, 25,
                                               customer_name="Test", customer_email=phone)
    fields = {"trip_key": "west_coast_beach", "experience": "West Coast Beach Trip",
              "date": "2026-03-18", "guests": "2", "departure_time": "09:00"}
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True, "hold_id": hold_id,
             "hold_trip_key": "west_coast_beach", "hold_date": "2026-03-18",
             "hold_departure_time": "09:00"}
    state_registry.wa_save_booking_state(phone, fields, flags)
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="Let me check on that!",
        semi_escalation=True,
        relay_question="Can I bring my own snorkel?",
    )
    msg = {"from": phone, "text": "Can I bring my own snorkel?", "from_name": "Test"}
    handle_incoming_whatsapp_message(msg)
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("awaiting_relay") is True
    assert "hold_id" not in state["flags"]
    assert state["flags"].get("slot_checked") is False
    mock_remove.assert_called_once_with("west_coast_beach", "2026-03-18", "09:00")
    _cleanup_phone(phone)


# --- Test 8: Escalation alert body contains chat log ---

@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_escalation_alert_contains_chat_log(mock_process, mock_sheets):
    """Full escalation notification body includes chat log and structured sections."""
    phone = "TEST_077_CHATLOG_001"
    _cleanup_phone(phone)
    # Pre-populate WhatsApp history
    state_registry.wa_store_message(phone, "user", "I have a complaint")
    mock_process.return_value = _base_result(
        intents=["complaint"],
        reply="I'm sorry to hear that!",
        requires_human=True,
        internal_note="Angry customer",
    )
    msg = {"from": phone, "text": "This is unacceptable", "from_name": "Test"}
    handle_incoming_whatsapp_message(msg)
    pending = state_registry.get_pending_notifications()
    match = [p for p in pending if p["customer_id"] == phone]
    assert len(match) == 1
    body = match[0]["body"]
    assert "I have a complaint" in body
    assert "=== CUSTOMER ===" in body
    assert "=== CHAT LOG ===" in body
    assert "=== BOOKING FIELDS ===" in body
    assert "=== MARINA'S INTERNAL NOTE ===" in body
    _cleanup_phone(phone)
