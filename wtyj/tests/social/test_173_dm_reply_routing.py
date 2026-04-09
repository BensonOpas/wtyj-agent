"""Tests for Brief 173 — social DM reply routing fans out across platforms."""
import os
from unittest.mock import patch

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from agents.social import whatsapp_client


def _clear_cache():
    whatsapp_client._zernio_account_cache.clear()


@patch("agents.social.zernio_dm_client.send_dm_reply")
@patch("agents.social.social_publisher.get_account_id")
def test_send_succeeds_on_first_whatsapp_account(mock_get_account, mock_send):
    """Brief 173: WhatsApp-first path — if the WhatsApp account accepts, no fan-out."""
    _clear_cache()
    mock_get_account.side_effect = lambda p: {"whatsapp": "wa_acc"}.get(p, "")
    mock_send.return_value = True

    ok = whatsapp_client.send_whatsapp_message("a" * 24, "hello")
    assert ok is True
    # Should have stopped after the first successful send
    assert mock_send.call_count == 1
    assert mock_send.call_args[0][1] == "wa_acc"


@patch("agents.social.zernio_dm_client.send_dm_reply")
@patch("agents.social.social_publisher.get_account_id")
def test_send_fans_out_to_facebook_when_whatsapp_fails(mock_get_account, mock_send):
    """Brief 173: the Anne-Sophie case — Facebook conversation rejected by WhatsApp
    account, accepted by Facebook account."""
    _clear_cache()
    mock_get_account.side_effect = lambda p: {
        "whatsapp": "wa_acc",
        "facebook": "fb_acc",
        "instagram": "ig_acc",
        "twitter": "tw_acc",
    }.get(p, "")
    # First call (whatsapp) fails, second call (facebook) succeeds
    mock_send.side_effect = [False, True]

    ok = whatsapp_client.send_whatsapp_message("b" * 24, "hi from dashboard")
    assert ok is True
    assert mock_send.call_count == 2
    assert mock_send.call_args_list[0][0][1] == "wa_acc"
    assert mock_send.call_args_list[1][0][1] == "fb_acc"


@patch("agents.social.zernio_dm_client.send_dm_reply")
@patch("agents.social.social_publisher.get_account_id")
def test_send_returns_false_when_all_platforms_fail(mock_get_account, mock_send):
    _clear_cache()
    mock_get_account.side_effect = lambda p: f"{p}_acc"
    mock_send.return_value = False

    ok = whatsapp_client.send_whatsapp_message("c" * 24, "nope")
    assert ok is False
    assert mock_send.call_count == 4  # whatsapp, facebook, instagram, twitter


@patch("agents.social.zernio_dm_client.send_dm_reply")
@patch("agents.social.social_publisher.get_account_id")
def test_cache_hit_skips_fanout(mock_get_account, mock_send):
    """Brief 173: warm path — cached account is used directly, no fan-out."""
    _clear_cache()
    whatsapp_client._zernio_account_cache["d" * 24] = "fb_acc"
    mock_send.return_value = True

    ok = whatsapp_client.send_whatsapp_message("d" * 24, "warm")
    assert ok is True
    assert mock_send.call_count == 1
    assert mock_send.call_args[0][1] == "fb_acc"
    # get_account_id should not have been called at all
    assert mock_get_account.call_count == 0


@patch("agents.social.zernio_dm_client.send_dm_reply")
@patch("agents.social.social_publisher.get_account_id")
def test_cache_populated_after_fanout_success(mock_get_account, mock_send):
    _clear_cache()
    mock_get_account.side_effect = lambda p: f"{p}_acc"
    mock_send.side_effect = [False, False, True]  # instagram is the winner

    conv_id = "e" * 24
    whatsapp_client.send_whatsapp_message(conv_id, "first send")
    assert whatsapp_client._zernio_account_cache[conv_id] == "instagram_acc"
