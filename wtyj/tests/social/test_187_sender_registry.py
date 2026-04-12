# test_187_sender_registry.py — Brief 187: Sender registry dispatch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test")

from unittest.mock import patch, MagicMock
from agents.social.senders import (
    Sender,
    ZernioSender,
    SENDERS,
    DEFAULT_SENDER,
    send_reply,
)
from shared import state_registry, config_loader


def _cleanup(conversation_id):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (conversation_id,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (conversation_id,))
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (conversation_id,))
    conn.execute("DELETE FROM whatsapp_processed WHERE message_id LIKE 'test_187_%'")
    conn.commit()
    conn.close()


# --- Test 1: ZernioSender.send delegates to send_dm_reply ---
@patch("agents.social.senders.zernio.send_dm_reply")
def test_zernio_sender_delegates_to_send_dm_reply(mock_dm_reply):
    mock_dm_reply.return_value = True
    result = ZernioSender.send("conv_abc", "acct_456", "hello")
    mock_dm_reply.assert_called_once_with("conv_abc", "acct_456", "hello")
    assert result is True


# --- Test 2: Registry maps the four channels to ZernioSender ---
def test_sender_registry_mapping():
    assert SENDERS["whatsapp"] is ZernioSender
    assert SENDERS["instagram_dm"] is ZernioSender
    assert SENDERS["facebook_dm"] is ZernioSender
    assert SENDERS["twitter_dm"] is ZernioSender


# --- Test 3: send_reply dispatches via the registry ---
@patch("agents.social.senders.zernio.send_dm_reply")
def test_send_reply_dispatches_via_registry(mock_dm_reply):
    mock_dm_reply.return_value = True
    result = send_reply("instagram_dm", "conv_ig", "acct_ig", "hi there")
    mock_dm_reply.assert_called_once_with("conv_ig", "acct_ig", "hi there")
    assert result is True


# --- Test 4: Unknown channel falls back to DEFAULT_SENDER ---
@patch("agents.social.senders.zernio.send_dm_reply")
def test_unknown_channel_falls_back_to_default(mock_dm_reply):
    mock_dm_reply.return_value = True
    # Lookup behavior
    assert SENDERS.get("totally_new_channel_xyz", DEFAULT_SENDER) is ZernioSender
    # Actually invoke the fallback
    result = send_reply("totally_new_channel_xyz", "conv_x", "acct_x", "fallback test")
    mock_dm_reply.assert_called_once_with("conv_x", "acct_x", "fallback test")
    assert result is True


# --- Test 5: _process_zernio_event calls send_reply for IG DMs ---
@patch("agents.social.webhook_server.send_reply")
@patch("agents.social.webhook_server.send_typing_indicator")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_process_zernio_event_calls_send_reply(mock_orch, mock_typing, mock_send):
    from agents.social.webhook_server import _process_zernio_event
    conv_id = "conv_187_ig"
    _cleanup(conv_id)

    mock_orch.return_value = "Reply from orchestrator"
    mock_send.return_value = True

    payload = {
        "event": "message.received",
        "account": {"id": "acct_187_ig"},
        "data": {
            "conversationId": conv_id,
            "id": "test_187_ig_msg_1",
            "text": "Hello from Instagram",
            "sender": {"name": "Instagram User"},
            "platform": "instagram",
        },
    }

    raw = config_loader._cache
    original = raw.get("features", {}).get("booking_flow", True)
    raw.setdefault("features", {})["booking_flow"] = True
    try:
        _process_zernio_event(payload)

        # send_reply called (not send_dm_reply directly)
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        assert args[0] == "instagram_dm", f"Expected channel 'instagram_dm', got '{args[0]}'"
        assert args[1] == conv_id, f"Expected conv_id '{conv_id}', got '{args[1]}'"
        assert args[2] == "acct_187_ig", f"Expected account_id 'acct_187_ig', got '{args[2]}'"
        assert args[3] == "Reply from orchestrator", f"Expected reply text, got '{args[3]}'"
    finally:
        raw["features"]["booking_flow"] = original
        _cleanup(conv_id)
