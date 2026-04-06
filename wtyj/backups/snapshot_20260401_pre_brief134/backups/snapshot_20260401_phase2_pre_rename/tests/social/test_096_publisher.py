# bluemarlin/tests/social/test_096_publisher.py
# Created: Brief 096
# Purpose: Tests for Late publishing integration

import json
import os
import sys
import glob
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_token_067")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "990622044139349")
os.environ.setdefault("LATE_API_KEY", "sk_test_key_for_testing")

from agents.social import social_publisher
from agents.social.auto_poster import cmd_publish
from agents.social import graphics_engine
from shared import state_registry


# --- Helpers ---

def _cleanup_all():
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM content_drafts")
    conn.execute("DELETE FROM content_learnings")
    conn.commit()
    conn.close()
    gfx_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'graphics')
    if os.path.exists(gfx_dir):
        for f in glob.glob(os.path.join(gfx_dir, "draft_*.jpg")):
            os.remove(f)


def _make_temp_jpg():
    img = Image.new("RGB", (100, 100), (27, 58, 92))
    tmp = os.path.join(tempfile.gettempdir(), "late_test_upload.jpg")
    img.save(tmp, "JPEG")
    return tmp


# --- Mock helpers ---

def _mock_account(field_id="acc_test", platform="instagram", username="testuser", is_active=True):
    acc = MagicMock()
    acc.field_id = field_id
    acc.platform = platform
    acc.username = username
    acc.isActive = is_active
    return acc


def _mock_accounts_response(accounts):
    resp = MagicMock()
    resp.accounts = accounts
    return resp


def _mock_upload_response(url="https://media.getlate.dev/temp/test.jpg"):
    resp = MagicMock()
    file_obj = MagicMock()
    file_obj.url = url
    resp.files = [file_obj]
    return resp


def _mock_post_response(post_id="post_123", post_url="https://instagram.com/p/test"):
    resp = MagicMock()
    resp.post = MagicMock()
    resp.post.field_id = post_id
    platform = MagicMock()
    platform.platformPostUrl = post_url
    resp.post.platforms = [platform]
    return resp


# --- Tests ---

def test_get_instagram_account_id_found():
    mock_client = MagicMock()
    mock_client.accounts.list.return_value = _mock_accounts_response([_mock_account()])
    with patch("agents.social.social_publisher.Late", return_value=mock_client):
        result = social_publisher.get_instagram_account_id()
    assert result == "acc_test"


def test_get_instagram_account_id_no_instagram():
    mock_client = MagicMock()
    mock_client.accounts.list.return_value = _mock_accounts_response(
        [_mock_account(platform="facebook")]
    )
    with patch("agents.social.social_publisher.Late", return_value=mock_client):
        result = social_publisher.get_instagram_account_id()
    assert result == ""


def test_get_instagram_account_id_no_api_key():
    with patch.dict(os.environ, {"LATE_API_KEY": ""}):
        result = social_publisher.get_instagram_account_id()
    assert result == ""


def test_upload_media_success():
    tmp = _make_temp_jpg()
    try:
        mock_client = MagicMock()
        mock_client.media.upload.return_value = _mock_upload_response("https://cdn/test.jpg")
        with patch("agents.social.social_publisher.Late", return_value=mock_client):
            result = social_publisher.upload_media(tmp)
        assert result == "https://cdn/test.jpg"
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def test_upload_media_file_not_found():
    result = social_publisher.upload_media("/nonexistent/path.jpg")
    assert result == ""


def test_publish_to_instagram_success():
    mock_client = MagicMock()
    mock_client.posts.create.return_value = _mock_post_response()
    with patch("agents.social.social_publisher.Late", return_value=mock_client):
        result = social_publisher.publish_to_instagram(
            "Test caption.", "https://cdn/img.jpg", "acc_123", ["#test"]
        )
    assert result is not None
    assert result["post_id"] == "post_123"
    assert "instagram" in result["post_url"]


def test_publish_to_instagram_no_account():
    result = social_publisher.publish_to_instagram("caption", "url", "", [])
    assert result is None


def test_publish_to_instagram_api_error():
    mock_client = MagicMock()
    mock_client.posts.create.side_effect = Exception("API error")
    with patch("agents.social.social_publisher.Late", return_value=mock_client):
        result = social_publisher.publish_to_instagram(
            "caption", "url", "acc_1", []
        )
    assert result is None


def test_publish_caption_includes_hashtags():
    mock_client = MagicMock()
    mock_client.posts.create.return_value = _mock_post_response()
    with patch("agents.social.social_publisher.Late", return_value=mock_client):
        social_publisher.publish_to_instagram(
            "Caption.", "url", "acc_1", ["#Tag1", "#Tag2"]
        )
    call_kwargs = mock_client.posts.create.call_args.kwargs
    assert "#Tag1" in call_kwargs["content"]
    assert "#Tag2" in call_kwargs["content"]


def test_cmd_publish_full_flow(capsys):
    _cleanup_all()
    try:
        d = state_registry.save_content_draft("A", "Test post.", "Test FB.",
                                               ["#test"], "visual", "reason")
        state_registry.update_draft_status(d, "approved")
        with patch("agents.social.auto_poster.social_publisher.get_instagram_account_id", return_value="acc_test"), \
             patch("agents.social.auto_poster.social_publisher.upload_media", return_value="https://cdn/test.jpg"), \
             patch("agents.social.auto_poster.social_publisher.publish_to_instagram", return_value={"post_id": "p1", "post_url": "https://ig/p/test"}), \
             patch("agents.social.auto_poster.graphics_engine.generate_graphic", return_value="/tmp/fake.jpg"):
            cmd_publish()
        captured = capsys.readouterr()
        assert "Published" in captured.out
        drafts = state_registry.get_content_drafts()
        match = [x for x in drafts if x["id"] == d]
        assert match[0]["status"] == "published"
    finally:
        _cleanup_all()
