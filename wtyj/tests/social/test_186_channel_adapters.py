# test_186_channel_adapters.py — Brief 186: Channel adapter refactor (parsing layer)
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test")

from unittest.mock import patch
from agents.social.channels import (
    Channel,
    WhatsAppZernioChannel,
    ZernioDMChannel,
    ZERNIO_CHANNELS,
    DEFAULT_ZERNIO_CHANNEL,
)
from shared import state_registry, config_loader


def _cleanup(conversation_id):
    """Mirror of test_138 cleanup pattern — wipe rows we created."""
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (conversation_id,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (conversation_id,))
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (conversation_id,))
    conn.execute("DELETE FROM whatsapp_processed WHERE message_id LIKE 'test_186_%'")
    conn.commit()
    conn.close()


# --- Test 1: WhatsApp via Zernio adapter produces full _zernio_* metadata ---
def test_whatsapp_zernio_adapter_includes_metadata():
    zernio_msg = {
        "conversation_id": "conv_abc",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "sender_name": "Test User",
        "sender_id": "sender_xyz",
        "text": "hello",
        "message_id": "msg_123",
        "account_id": "acct_456",
    }
    result = WhatsAppZernioChannel.from_zernio(zernio_msg)
    assert result["from"] == "conv_abc"
    assert result["text"] == "hello"
    assert result["from_name"] == "Test User"
    assert result["message_id"] == "msg_123"
    assert result["channel"] == "whatsapp"
    assert result["_zernio_conversation_id"] == "conv_abc"
    assert result["_zernio_account_id"] == "acct_456"
    assert result["_zernio_channel"] == "whatsapp"
    assert result["_zernio_sender_name"] == "Test User"


# --- Test 2: Generic DM adapter produces minimal dict (no _zernio_* keys) ---
def test_zernio_dm_adapter_no_metadata():
    zernio_msg = {
        "conversation_id": "conv_ig",
        "platform": "instagram",
        "channel": "instagram_dm",
        "sender_name": "IG User",
        "sender_id": "ig_sender_1",
        "text": "hi there",
        "message_id": "msg_ig_1",
        "account_id": "acct_ig",
    }
    result = ZernioDMChannel.from_zernio(zernio_msg)
    assert result["from"] == "conv_ig"
    assert result["text"] == "hi there"
    assert result["from_name"] == "IG User"
    assert result["channel"] == "instagram_dm"
    assert result["message_id"] == "msg_ig_1"
    # Critical: DM adapter must NOT add buffer-round-trip metadata
    assert not any(k.startswith("_zernio_") for k in result), \
        f"ZernioDMChannel should not produce _zernio_* keys, got: {list(result.keys())}"


# --- Test 3: Registry maps the four channels to the correct adapter classes ---
def test_zernio_channels_registry_mapping():
    assert ZERNIO_CHANNELS["whatsapp"] is WhatsAppZernioChannel
    assert ZERNIO_CHANNELS["instagram_dm"] is ZernioDMChannel
    assert ZERNIO_CHANNELS["facebook_dm"] is ZernioDMChannel
    assert ZERNIO_CHANNELS["twitter_dm"] is ZernioDMChannel


# --- Test 4: Unknown channel falls back to DEFAULT_ZERNIO_CHANNEL ---
def test_unknown_channel_falls_back_to_default():
    # Lookup behavior — unknown key returns the default
    adapter_cls = ZERNIO_CHANNELS.get("totally_new_dm", DEFAULT_ZERNIO_CHANNEL)
    assert adapter_cls is ZernioDMChannel
    # The default adapter actually works on an unknown-platform Zernio dict
    fake_unknown = {
        "conversation_id": "conv_unknown",
        "platform": "newplatform",
        "channel": "newplatform_dm",
        "sender_name": "Unknown User",
        "sender_id": "u_1",
        "text": "msg from unknown",
        "message_id": "msg_unknown_1",
        "account_id": "acct_u",
    }
    result = adapter_cls.from_zernio(fake_unknown)
    assert result["from"] == "conv_unknown"
    assert result["text"] == "msg from unknown"
    assert result["from_name"] == "Unknown User"
    assert result["channel"] == "newplatform_dm"
    assert result["message_id"] == "msg_unknown_1"
    assert not any(k.startswith("_zernio_") for k in result)


# --- Test 5: _process_zernio_event dispatches via the registry end-to-end ---
@patch("agents.social.webhook_server.send_reply")
@patch("agents.social.webhook_server.send_typing_indicator")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_process_zernio_event_dispatches_via_registry(mock_orch, mock_typing, mock_send):
    from agents.social.webhook_server import _process_zernio_event
    conv_id = "conv_186_ig"
    _cleanup(conv_id)

    mock_orch.return_value = "Reply from orchestrator"

    payload = {
        "event": "message.received",
        "account": {"id": "acct_ig"},
        "data": {
            "conversationId": conv_id,
            "id": "test_186_ig_msg_1",
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

        # Orchestrator was called once, with the adapter-produced dict
        mock_orch.assert_called_once()
        call_args = mock_orch.call_args
        msg_arg = call_args[0][0]
        assert msg_arg["from"] == conv_id
        assert msg_arg["text"] == "Hello from Instagram"
        assert msg_arg["from_name"] == "Instagram User"
        assert msg_arg["channel"] == "instagram_dm"
        assert msg_arg["message_id"] == "test_186_ig_msg_1"
        # DM adapter must not add buffer metadata
        assert "_zernio_conversation_id" not in msg_arg

        # channel kwarg passed correctly
        assert call_args[1].get("channel") == "instagram_dm"
    finally:
        raw["features"]["booking_flow"] = original
        _cleanup(conv_id)
