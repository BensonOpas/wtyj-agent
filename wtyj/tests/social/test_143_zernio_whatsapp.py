# test_143_zernio_whatsapp.py — Zernio WhatsApp: Route WhatsApp Through Zernio
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test")

from unittest.mock import patch, MagicMock
from shared import state_registry, config_loader


def _cleanup(conv_id):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (conv_id,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (conv_id,))
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (conv_id,))
    conn.execute("DELETE FROM whatsapp_processed WHERE message_id LIKE 'test_143_%'")
    conn.commit()
    conn.close()


def _make_zernio_wa_payload(conversation_id, text, message_id=None):
    """Build a Zernio webhook payload for a WhatsApp message."""
    return {
        "event": "message.received",
        "account": {"id": "wa_acc_123"},
        "data": {
            "conversationId": conversation_id,
            "id": message_id or f"test_143_{conversation_id}_{text[:10]}",
            "text": text,
            "sender": {"name": "WA Tester"},
            "platform": "whatsapp",
        },
    }


# --- Test 1: WhatsApp channel is "whatsapp" not "whatsapp_dm" ---
def test_zernio_whatsapp_channel_is_whatsapp():
    from agents.social.zernio_dm_client import parse_zernio_webhook
    payload = _make_zernio_wa_payload("conv_143_channel", "hello")
    msg = parse_zernio_webhook(payload)
    assert msg is not None
    assert msg["channel"] == "whatsapp", f"Expected 'whatsapp', got '{msg['channel']}'"
    assert msg["platform"] == "whatsapp"


# --- Test 2: Instagram channel unchanged ---
def test_zernio_instagram_channel_unchanged():
    from agents.social.zernio_dm_client import parse_zernio_webhook
    payload = {
        "event": "message.received",
        "account": {"id": "ig_acc"},
        "data": {
            "conversationId": "conv_143_ig",
            "id": "test_143_ig_msg",
            "text": "hello",
            "sender": {"name": "IG User"},
            "platform": "instagram",
        },
    }
    msg = parse_zernio_webhook(payload)
    assert msg["channel"] == "instagram_dm", f"Expected 'instagram_dm', got '{msg['channel']}'"


# --- Test 3: WhatsApp via Zernio uses debounce buffer ---
@patch("agents.social.webhook_server.send_typing_indicator")
@patch("agents.social.webhook_server._buffer_message")
def test_zernio_whatsapp_uses_debounce(mock_buffer, mock_typing):
    from agents.social.webhook_server import _process_zernio_event
    conv_id = "conv_143_debounce"
    _cleanup(conv_id)

    payload = _make_zernio_wa_payload(conv_id, "I want to book")
    _process_zernio_event(payload)

    # Should go through debounce buffer, not process immediately
    mock_buffer.assert_called_once()
    msg_arg = mock_buffer.call_args[0][0]
    assert msg_arg["from"] == conv_id
    assert msg_arg["_zernio_conversation_id"] == conv_id
    assert msg_arg["_zernio_account_id"] == "wa_acc_123"
    _cleanup(conv_id)


# --- Test 4: Zernio WhatsApp reply goes via send_dm_reply ---
@patch("agents.social.webhook_server.send_dm_reply")
@patch("agents.social.webhook_server.send_text_message")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_zernio_whatsapp_reply_via_zernio(mock_orchestrator, mock_meta_send, mock_zernio_send):
    from agents.social.webhook_server import _flush_buffer, _message_buffers, _buffer_lock
    import threading

    conv_id = "conv_143_reply"
    _cleanup(conv_id)
    mock_orchestrator.return_value = "Booking confirmed!"

    # Simulate a buffered Zernio WhatsApp message
    with _buffer_lock:
        _message_buffers[conv_id] = {
            "messages": [{
                "from": conv_id,
                "text": "Book sunset cruise",
                "from_name": "WA Tester",
                "_zernio_conversation_id": conv_id,
                "_zernio_account_id": "wa_acc_123",
                "_zernio_channel": "whatsapp",
                "_zernio_sender_name": "WA Tester",
            }],
            "timer": None,
            "started": time.time(),
        }

    _flush_buffer(conv_id)

    # Reply via Zernio (not Meta)
    mock_zernio_send.assert_called_once()
    mock_meta_send.assert_not_called()
    assert mock_zernio_send.call_args[0][0] == conv_id
    assert mock_zernio_send.call_args[0][2] == "Booking confirmed!"
    _cleanup(conv_id)


# --- Test 5: Debounce batches multiple messages ---
@patch("agents.social.webhook_server.send_dm_reply")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_zernio_whatsapp_debounce_batches(mock_orchestrator, mock_send):
    from agents.social.webhook_server import _flush_buffer, _message_buffers, _buffer_lock

    conv_id = "conv_143_batch"
    _cleanup(conv_id)
    mock_orchestrator.return_value = "Got it!"

    # Simulate 2 buffered messages
    with _buffer_lock:
        _message_buffers[conv_id] = {
            "messages": [
                {
                    "from": conv_id, "text": "hey",
                    "from_name": "WA Tester",
                    "_zernio_conversation_id": conv_id,
                    "_zernio_account_id": "wa_acc_123",
                    "_zernio_channel": "whatsapp",
                    "_zernio_sender_name": "WA Tester",
                },
                {
                    "from": conv_id, "text": "I want to book sunset cruise",
                    "from_name": "WA Tester",
                    "_zernio_conversation_id": conv_id,
                    "_zernio_account_id": "wa_acc_123",
                    "_zernio_channel": "whatsapp",
                    "_zernio_sender_name": "WA Tester",
                },
            ],
            "timer": None,
            "started": time.time(),
        }

    _flush_buffer(conv_id)

    # Only one orchestrator call with combined text
    mock_orchestrator.assert_called_once()
    msg_arg = mock_orchestrator.call_args[0][0]
    assert "hey" in msg_arg["text"]
    assert "sunset cruise" in msg_arg["text"]
    _cleanup(conv_id)


# --- Test 6: booking_flow=false routes to DM agent ---
@patch("agents.social.webhook_server.send_dm_reply")
@patch("agents.social.webhook_server.handle_incoming_dm")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_zernio_whatsapp_booking_flow_off_uses_dm_agent(mock_orchestrator, mock_dm, mock_send):
    from agents.social.webhook_server import _flush_buffer, _message_buffers, _buffer_lock

    conv_id = "conv_143_flow_off"
    _cleanup(conv_id)
    mock_dm.return_value = "We have great trips!"
    mock_orchestrator.return_value = "Should not be called"

    raw = config_loader._cache
    original = raw.get("features", {}).get("booking_flow", True)
    raw.setdefault("features", {})["booking_flow"] = False
    try:
        with _buffer_lock:
            _message_buffers[conv_id] = {
                "messages": [{
                    "from": conv_id, "text": "What trips do you have?",
                    "from_name": "WA Tester",
                    "_zernio_conversation_id": conv_id,
                    "_zernio_account_id": "wa_acc_123",
                    "_zernio_channel": "whatsapp",
                    "_zernio_sender_name": "WA Tester",
                }],
                "timer": None,
                "started": time.time(),
            }

        _flush_buffer(conv_id)

        # DM agent called, orchestrator NOT called
        mock_dm.assert_called_once()
        mock_orchestrator.assert_not_called()
        # Reply via Zernio
        mock_send.assert_called_once()
    finally:
        raw["features"]["booking_flow"] = original
        _cleanup(conv_id)
