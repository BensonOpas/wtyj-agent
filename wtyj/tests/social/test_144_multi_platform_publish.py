# test_144_multi_platform_publish.py — Multi-Platform Publishing
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


def _mock_accounts(*platforms):
    """Create mock Zernio accounts for given platforms."""
    accounts = []
    for i, plat in enumerate(platforms):
        acc = MagicMock()
        acc.platform = plat
        acc.isActive = True
        acc.field_id = f"acc_{plat}_{i}"
        accounts.append(acc)
    resp = MagicMock()
    resp.accounts = accounts
    return resp


# --- Test 1: get_available_platforms filters excluded platforms (Brief 155 + 156) ---
@patch("agents.social.social_publisher._get_client")
def test_get_available_platforms_filters_excluded(mock_client):
    """Brief 156 — get_available_platforms must exclude DM-only and discontinued
    platforms (whatsapp from Brief 155, linkedin from Brief 156)."""
    from agents.social.social_publisher import get_available_platforms
    client = MagicMock()
    client.accounts.list.return_value = _mock_accounts(
        "instagram", "facebook", "whatsapp", "linkedin", "twitter"
    )
    mock_client.return_value = client

    platforms = get_available_platforms()
    assert "instagram" in platforms
    assert "facebook" in platforms
    assert "twitter" in platforms
    assert "whatsapp" not in platforms, "whatsapp must be filtered (DM-only)"
    assert "linkedin" not in platforms, "linkedin must be filtered (discontinued)"
    assert len(platforms) == 3


# --- Test 2: get_account_id finds correct platform ---
@patch("agents.social.social_publisher._get_client")
def test_get_account_id_finds_platform(mock_client):
    from agents.social.social_publisher import get_account_id
    client = MagicMock()
    client.accounts.list.return_value = _mock_accounts("instagram", "linkedin", "twitter")
    mock_client.return_value = client

    assert get_account_id("linkedin") == "acc_linkedin_1"
    assert get_account_id("twitter") == "acc_twitter_2"
    assert get_account_id("tiktok") == ""  # Not connected


# --- Test 3: publish_to_platform passes correct platform ---
@patch("agents.social.social_publisher._get_client")
def test_publish_to_platform_generic(mock_client):
    from agents.social.social_publisher import publish_to_platform
    client = MagicMock()
    mock_post = MagicMock()
    mock_post.field_id = "post_123"
    mock_post.platforms = []
    mock_result = MagicMock()
    mock_result.post = mock_post
    client.posts.create.return_value = mock_result
    mock_client.return_value = client

    result = publish_to_platform("linkedin", "Test post", "http://img.jpg", "acc_li")
    assert result is not None
    assert result["post_id"] == "post_123"

    # Verify the platform passed to Zernio
    call_kwargs = client.posts.create.call_args
    platforms_arg = call_kwargs.kwargs.get("platforms") or call_kwargs[1].get("platforms")
    assert platforms_arg[0]["platform"] == "linkedin"


# --- Test 4: execute_publish handles multi-platform ---
@patch("agents.social.social_publisher.get_account_id")
@patch("agents.social.social_publisher.publish_to_platform")
@patch("agents.social.social_publisher.publish_to_instagram")
@patch("agents.social.social_publisher.get_instagram_account_id")
@patch("agents.social.social_publisher.upload_media")
@patch("agents.social.scheduler._resolve_image")
@patch("shared.state_registry.is_dry_run")
@patch("shared.state_registry.update_draft_status")
def test_execute_publish_multi_platform(mock_status, mock_dry, mock_resolve,
                                         mock_upload, mock_ig_acct, mock_ig_pub,
                                         mock_generic_pub, mock_get_acct):
    from agents.social.scheduler import execute_publish

    mock_dry.return_value = False
    mock_resolve.return_value = "/tmp/test.jpg"
    mock_upload.return_value = "http://media.url/test.jpg"
    mock_ig_acct.return_value = "ig_acc"
    mock_ig_pub.return_value = {"post_id": "ig_post", "post_url": "http://ig/post"}
    mock_get_acct.return_value = "li_acc"
    mock_generic_pub.return_value = {"post_id": "li_post", "post_url": "http://li/post"}

    draft = {
        "id": 999,
        "instagram_caption": "Test caption",
        "platforms": ["instagram", "linkedin"],
        "image_path": "/tmp/test.jpg",
        "hashtags": ["#test"],
    }

    result = execute_publish(draft)
    assert result["ok"] is True
    assert "instagram" in result["platforms"]
    assert "linkedin" in result["platforms"]

    # Instagram published via dedicated function
    mock_ig_pub.assert_called_once()
    # LinkedIn published via generic function
    mock_generic_pub.assert_called_once()
    assert mock_generic_pub.call_args[1]["platform"] == "linkedin" or mock_generic_pub.call_args[0][0] == "linkedin"
