# test_138_dm_booking.py — DM Booking: Route DMs Through Booking Orchestrator
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test")

from unittest.mock import patch, MagicMock, call
from datetime import datetime, timezone, timedelta
from shared import state_registry, config_loader


def _cleanup(conversation_id):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (conversation_id,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (conversation_id,))
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (conversation_id,))
    # Clean dedup table too
    conn.execute("DELETE FROM whatsapp_processed WHERE message_id LIKE 'test_138_%'")
    conn.commit()
    conn.close()


def _make_zernio_payload(conversation_id, text, sender_name="Test User",
                          platform="instagram", message_id=None):
    """Build a Zernio webhook payload that parse_zernio_webhook can parse.
    Parser reads: data.conversationId, data.id (or data.messageId),
    data.text (or data.message.text), data.sender.name, data.platform.
    account.id at top level for account_id."""
    return {
        "event": "message.received",
        "account": {"id": "acc_123"},
        "data": {
            "conversationId": conversation_id,
            "id": message_id or f"test_138_{conversation_id}_{text[:10]}",
            "text": text,
            "sender": {"name": sender_name},
            "platform": platform,
        },
    }


def _next_wed():
    today = datetime.now(timezone.utc).date()
    d = today + timedelta(days=1)
    while d.weekday() != 2:
        d += timedelta(days=1)
    return d.isoformat()


# --- Test 1: DM routes to orchestrator when booking_flow ON ---
@patch("agents.social.webhook_server.send_reply")
@patch("agents.social.webhook_server.send_typing_indicator")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
@patch("agents.social.webhook_server.handle_incoming_dm")
def test_dm_routes_to_orchestrator_when_flow_on(mock_dm, mock_orchestrator,
                                                  mock_typing, mock_send):
    from agents.social.webhook_server import _process_zernio_event
    conv_id = "conv_138_orch_on"
    _cleanup(conv_id)

    mock_orchestrator.return_value = "Sure, I can help you book!"
    mock_dm.return_value = "Should not be called"

    raw = config_loader._cache
    original = raw.get("features", {}).get("booking_flow", True)
    raw.setdefault("features", {})["booking_flow"] = True
    try:
        payload = _make_zernio_payload(conv_id, "I want to book a trip")
        _process_zernio_event(payload)

        # Orchestrator called with correct shape
        mock_orchestrator.assert_called_once()
        msg_arg = mock_orchestrator.call_args[0][0]
        assert msg_arg["from"] == conv_id
        assert msg_arg["text"] == "I want to book a trip"
        assert msg_arg["from_name"] == "Test User"

        # DM agent NOT called
        mock_dm.assert_not_called()

        # Reply sent via Zernio
        mock_send.assert_called_once()
        assert mock_send.call_args[0][1] == conv_id  # conversation_id
        assert mock_send.call_args[0][3] == "Sure, I can help you book!"  # reply text
    finally:
        raw["features"]["booking_flow"] = original
        _cleanup(conv_id)


# --- Test 2: DM routes to Q&A agent when booking_flow OFF ---
@patch("agents.social.webhook_server.send_reply")
@patch("agents.social.webhook_server.send_typing_indicator")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
@patch("agents.social.webhook_server.handle_incoming_dm")
def test_dm_routes_to_qa_agent_when_flow_off(mock_dm, mock_orchestrator,
                                               mock_typing, mock_send):
    from agents.social.webhook_server import _process_zernio_event
    conv_id = "conv_138_qa_off"
    _cleanup(conv_id)

    mock_dm.return_value = "We have several properties available!"
    mock_orchestrator.return_value = "Should not be called"

    raw = config_loader._cache
    original = raw.get("features", {}).get("booking_flow", True)
    raw.setdefault("features", {})["booking_flow"] = False
    try:
        payload = _make_zernio_payload(conv_id, "What properties do you have?")
        _process_zernio_event(payload)

        # DM agent called
        mock_dm.assert_called_once()

        # Orchestrator NOT called
        mock_orchestrator.assert_not_called()

        # Reply sent via Zernio
        mock_send.assert_called_once()
    finally:
        raw["features"]["booking_flow"] = original
        _cleanup(conv_id)


# --- Test 3: Full booking flow through DM ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
@patch("shared.state_registry.create_soft_hold")
@patch("agents.social.webhook_server.send_reply")
@patch("agents.social.webhook_server.send_typing_indicator")
def test_dm_booking_full_flow(mock_typing, mock_send, mock_create_hold, mock_process,
                               mock_cal, mock_pay, mock_sheets):
    from agents.social.webhook_server import _process_zernio_event
    conv_id = "conv_138_full_flow"
    _cleanup(conv_id)
    date = _next_wed()

    # Set up booking state — awaiting confirmation, slot not checked
    fields = {"service_key": "west_coast_beach", "service_name": "West Coast Beach",
              "date": date, "guests": "2", "slot_time": "09:00", "customer_name": "DM Booker"}
    flags = {"awaiting_booking_confirmation": True, "slot_checked": False}
    state_registry.wa_save_booking_state(conv_id, fields, flags)

    # Marina returns booking confirmed with ref placeholder
    mock_process.return_value = {
        "intents": ["booking"], "fields": {}, "confidence": "high",
        "reply": "Booked! Ref: [BOOKING_REF]. Pay here: [PAYMENT_LINK]",
        "reply_hold_failed": "Sorry, sold out.",
        "clarifications_needed": [],
        "requires_human": False,
        "flags": {"booking_confirmed": True},
        "internal_note": "confirmed booking"
    }
    mock_cal.check_availability.return_value = {"available": True, "spots_remaining": 20, "capacity": 25}
    mock_cal.create_or_update_manifest.return_value = {"ok": True, "eventId": "e1", "htmlLink": "http://cal/e1"}
    mock_pay.generate_payment_link.return_value = {"payment_id": "pay1", "status": "pending"}
    mock_create_hold.return_value = 999  # Valid hold ID

    raw = config_loader._cache
    original = raw.get("features", {}).get("booking_flow", True)
    raw.setdefault("features", {})["booking_flow"] = True
    try:
        payload = _make_zernio_payload(conv_id, "Yes, book it!", message_id="test_138_fullflow")
        _process_zernio_event(payload)

        # Reply should contain actual booking ref, not placeholder
        mock_send.assert_called_once()
        reply_text = mock_send.call_args[0][3]
        assert "[BOOKING_REF]" not in reply_text, "Booking ref placeholder not replaced"
        assert "[PAYMENT_LINK]" not in reply_text, "Payment link placeholder not replaced"
        # Reply should contain a 6-char alphanumeric ref
        import re
        ref_match = re.search(r'\b[A-Z0-9]{6}\b', reply_text)
        assert ref_match, f"No booking ref found in reply: {reply_text}"

        # Booking state should be persisted
        state = state_registry.wa_get_booking_state(conv_id)
        assert state["flags"].get("hold_created") is True
        assert len(state["flags"].get("booking_ref", "")) == 6
    finally:
        raw["features"]["booking_flow"] = original
        _cleanup(conv_id)


# --- Test 4: User message stored with correct channel ---
@patch("agents.social.webhook_server.send_reply")
@patch("agents.social.webhook_server.send_typing_indicator")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_dm_message_stored_with_correct_channel(mock_orchestrator, mock_typing, mock_send):
    from agents.social.webhook_server import _process_zernio_event
    conv_id = "conv_138_channel"
    _cleanup(conv_id)

    mock_orchestrator.return_value = "Reply from orchestrator"

    raw = config_loader._cache
    original = raw.get("features", {}).get("booking_flow", True)
    raw.setdefault("features", {})["booking_flow"] = True
    try:
        payload = _make_zernio_payload(conv_id, "Hello!", platform="instagram")
        _process_zernio_event(payload)

        # Check stored messages have correct channel
        history = state_registry.dm_get_history(conv_id, "instagram_dm", limit=10)
        user_msgs = [m for m in history if m["role"] == "user"]
        assistant_msgs = [m for m in history if m["role"] == "assistant"]
        assert len(user_msgs) >= 1, f"Expected user message, got {len(user_msgs)}"
        assert len(assistant_msgs) >= 1, f"Expected assistant message, got {len(assistant_msgs)}"
    finally:
        raw["features"]["booking_flow"] = original
        _cleanup(conv_id)


# --- Test 5: Dedup works ---
@patch("agents.social.webhook_server.send_reply")
@patch("agents.social.webhook_server.send_typing_indicator")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_dm_dedup_works(mock_orchestrator, mock_typing, mock_send):
    from agents.social.webhook_server import _process_zernio_event
    conv_id = "conv_138_dedup"
    _cleanup(conv_id)

    mock_orchestrator.return_value = "Reply"

    raw = config_loader._cache
    original = raw.get("features", {}).get("booking_flow", True)
    raw.setdefault("features", {})["booking_flow"] = True
    try:
        payload = _make_zernio_payload(conv_id, "Hello!", message_id="test_138_dedup_same")
        _process_zernio_event(payload)
        _process_zernio_event(payload)  # Same message_id

        # Orchestrator called only once
        assert mock_orchestrator.call_count == 1, \
            f"Expected 1 call, got {mock_orchestrator.call_count}"
    finally:
        raw["features"]["booking_flow"] = original
        _cleanup(conv_id)


# --- Test 6: Reply sent via Zernio, not WhatsApp ---
@patch("agents.social.webhook_server.send_reply")
@patch("agents.social.webhook_server.send_typing_indicator")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_dm_reply_sent_via_zernio(mock_orchestrator, mock_typing, mock_send):
    from agents.social.webhook_server import _process_zernio_event
    conv_id = "conv_138_zernio_send"
    _cleanup(conv_id)

    mock_orchestrator.return_value = "Booking reply"

    raw = config_loader._cache
    original = raw.get("features", {}).get("booking_flow", True)
    raw.setdefault("features", {})["booking_flow"] = True
    try:
        payload = _make_zernio_payload(conv_id, "Book me in")
        _process_zernio_event(payload)

        # send_reply called (Zernio, via sender registry)
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        assert args[0] == "instagram_dm"  # channel (Brief 187 — send_reply first arg)
        assert args[1] == conv_id  # conversation_id
        assert args[2] == "acc_123"  # account_id
        assert args[3] == "Booking reply"  # reply text
    finally:
        raw["features"]["booking_flow"] = original
        _cleanup(conv_id)


# --- Test 7: User message stored AFTER orchestrator call (not before) ---
@patch("agents.social.webhook_server.send_reply")
@patch("agents.social.webhook_server.send_typing_indicator")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_dm_user_message_stored_after_orchestrator(mock_orchestrator, mock_typing, mock_send):
    from agents.social.webhook_server import _process_zernio_event
    conv_id = "conv_138_ordering"
    _cleanup(conv_id)

    # Track whether dm_store_message was called before the orchestrator
    store_calls_at_orchestrator_time = []

    def _orchestrator_side_effect(msg, **kwargs):
        # At the time the orchestrator is called, check if the user message
        # is already in the database
        history = state_registry.dm_get_history(conv_id, "instagram_dm", limit=50)
        user_msgs = [m for m in history if m["role"] == "user"
                     and "Order test message" in m.get("text", "")]
        store_calls_at_orchestrator_time.append(len(user_msgs))
        return "Reply"

    mock_orchestrator.side_effect = _orchestrator_side_effect

    raw = config_loader._cache
    original = raw.get("features", {}).get("booking_flow", True)
    raw.setdefault("features", {})["booking_flow"] = True
    try:
        payload = _make_zernio_payload(conv_id, "Order test message")
        _process_zernio_event(payload)

        # At the time the orchestrator was called, user message should NOT
        # have been in the database yet
        assert len(store_calls_at_orchestrator_time) == 1
        assert store_calls_at_orchestrator_time[0] == 0, \
            "User message was stored BEFORE orchestrator call — Marina would see it twice"

        # After the function completes, the message SHOULD be stored
        history = state_registry.dm_get_history(conv_id, "instagram_dm", limit=50)
        user_msgs = [m for m in history if m["role"] == "user"
                     and "Order test message" in m.get("text", "")]
        assert len(user_msgs) == 1, f"Expected 1 user message after, got {len(user_msgs)}"
    finally:
        raw["features"]["booking_flow"] = original
        _cleanup(conv_id)
