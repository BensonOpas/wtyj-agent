"""Tests for Brief 170 — X (Twitter) DM handling.

Investigation showed Zernio webhook logs contained zero twitter/x events since
the feature started — instagram and facebook only. That's a Zernio-side
configuration issue, not a code bug. The code path for twitter_dm already
exists and routes through the same handler as IG/FB DMs.

This brief adds:
1. Platform name normalization ('x' | 'X' → 'twitter') so both Zernio
   string variants route to the same channel string.
2. Unit tests verifying twitter webhooks would be parsed correctly if they
   arrived.
"""
import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from agents.social.zernio_dm_client import parse_zernio_webhook


def _webhook(platform: str, conversation_id: str = "conv_t170", message_id: str = "msg_t170"):
    return {
        "event": "message.received",
        "data": {
            "platform": platform,
            "conversationId": conversation_id,
            "id": message_id,
            "text": "hello from twitter",
            "sender": {"name": "Twitter User", "id": "sender_1"},
            "accountId": "acc_1",
        },
    }


def test_twitter_platform_parses_to_twitter_dm_channel():
    msg = parse_zernio_webhook(_webhook("twitter"))
    assert msg is not None
    assert msg["platform"] == "twitter"
    assert msg["channel"] == "twitter_dm"


def test_x_platform_normalizes_to_twitter_dm_channel():
    """Brief 170: if Zernio sends platform='x', normalize to 'twitter' so
    both string variants route to the same channel."""
    msg = parse_zernio_webhook(_webhook("x"))
    assert msg is not None
    assert msg["platform"] == "twitter"
    assert msg["channel"] == "twitter_dm"


def test_X_platform_uppercase_normalizes_to_twitter_dm_channel():
    msg = parse_zernio_webhook(_webhook("X"))
    assert msg is not None
    assert msg["platform"] == "twitter"


def test_twitter_webhook_would_have_required_fields_for_orchestrator():
    """Brief 170: sanity check that twitter webhooks have the right shape to
    feed into handle_incoming_whatsapp_message (which is the routing target when
    booking_flow is on)."""
    msg = parse_zernio_webhook(_webhook("twitter"))
    assert msg["conversation_id"]
    assert msg["message_id"]
    assert msg["text"]
    assert msg["sender_name"]
