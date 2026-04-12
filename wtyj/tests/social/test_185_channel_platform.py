# Tests for Brief 185 — Store actual platform in conversation data
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_deps():
    """Mock all external dependencies for social_agent."""
    with patch("agents.social.social_agent.marina_agent") as mock_marina, \
         patch("agents.social.social_agent.state_registry") as mock_sr, \
         patch("agents.social.social_agent.config_loader") as mock_cl, \
         patch("agents.social.social_agent.sheets_writer") as mock_sw, \
         patch("agents.social.social_agent.bm_logger") as mock_log:

        # Config: booking_flow on, minimal config
        mock_cl.get_raw.return_value = {
            "features": {"booking_flow": True},
            "business": {"name": "Test"},
            "booking_rules": {},
            "services": {},
        }

        # State registry defaults
        mock_sr.wa_get_booking_state.return_value = {
            "fields": {}, "flags": {}, "completed_bookings": []
        }
        mock_sr.wa_get_history.return_value = []
        mock_sr.customer_lookup.return_value = None

        yield {
            "marina": mock_marina,
            "sr": mock_sr,
            "cl": mock_cl,
            "sw": mock_sw,
            "log": mock_log,
        }


def _make_escalation_result():
    """Marina result that triggers a full escalation."""
    return {
        "reply": "Let me connect you with the team.",
        "intent": "complaint",
        "fields": {},
        "flags": {},
        "requires_human": True,
        "semi_escalation": False,
        "internal_note": "Customer complaint about service",
    }


def _make_relay_result():
    """Marina result that triggers a semi-escalation (relay)."""
    return {
        "reply": "Let me check with the team on that.",
        "intent": "inquiry",
        "fields": {},
        "flags": {},
        "requires_human": False,
        "semi_escalation": True,
        "relay_question": "Is wheelchair access available?",
        "internal_note": "",
    }


def test_instagram_escalation_uses_instagram_channel(mock_deps):
    """Instagram DM escalation stores instagram_dm as channel, not whatsapp."""
    mock_deps["marina"].process_message.return_value = _make_escalation_result()

    from agents.social.social_agent import handle_incoming_whatsapp_message
    msg = {"from": "ig_conv_123", "text": "This is terrible", "from_name": "Jane"}
    handle_incoming_whatsapp_message(msg, channel="instagram_dm")

    # Check notification was created with instagram_dm channel
    calls = mock_deps["sr"].create_pending_notification.call_args_list
    assert len(calls) >= 1
    notification_call = calls[0]
    assert notification_call[0][1] == "instagram_dm"  # channel argument
    # Check body contains "Instagram" not "WhatsApp"
    subject = notification_call[0][4]
    assert "Instagram" in subject
    assert "WhatsApp" not in subject


def test_facebook_relay_uses_facebook_channel(mock_deps):
    """Facebook DM relay stores facebook_dm as channel."""
    mock_deps["marina"].process_message.return_value = _make_relay_result()

    from agents.social.social_agent import handle_incoming_whatsapp_message
    msg = {"from": "fb_conv_456", "text": "Do you have wheelchair access?", "from_name": "Mark"}
    handle_incoming_whatsapp_message(msg, channel="facebook_dm")

    calls = mock_deps["sr"].create_pending_notification.call_args_list
    assert len(calls) >= 1
    assert calls[0][0][1] == "facebook_dm"
    body = calls[0][1].get("relay_token") if calls[0][1] else None
    # Check the body arg (positional arg 5) contains Facebook
    body_text = calls[0][0][5]
    assert "Facebook" in body_text


def test_default_channel_is_whatsapp(mock_deps):
    """Without channel parameter, defaults to whatsapp for backward compat."""
    mock_deps["marina"].process_message.return_value = _make_escalation_result()

    from agents.social.social_agent import handle_incoming_whatsapp_message
    msg = {"from": "wa_phone_789", "text": "I have a complaint", "from_name": "Alex"}
    handle_incoming_whatsapp_message(msg)

    calls = mock_deps["sr"].create_pending_notification.call_args_list
    assert len(calls) >= 1
    assert calls[0][0][1] == "whatsapp"
    subject = calls[0][0][4]
    assert "WhatsApp" in subject


def test_marina_receives_correct_channel(mock_deps):
    """Marina process_message is called with the actual channel, not hardcoded whatsapp."""
    mock_deps["marina"].process_message.return_value = {
        "reply": "Hello!", "intent": "greeting", "fields": {}, "flags": {},
        "requires_human": False, "semi_escalation": False,
    }

    from agents.social.social_agent import handle_incoming_whatsapp_message
    msg = {"from": "x_conv_abc", "text": "Hi there", "from_name": "Sam"}
    handle_incoming_whatsapp_message(msg, channel="twitter_dm")

    call_kwargs = mock_deps["marina"].process_message.call_args
    assert call_kwargs[1]["channel"] == "twitter_dm"
