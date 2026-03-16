# bluemarlin/tests/social/test_098_seasonal_and_control.py
# Created: Brief 098
# Purpose: Tests for seasonal awareness + post-publication control

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime as real_datetime, timezone, timedelta

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_token_067")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "990622044139349")
os.environ.setdefault("LATE_API_KEY", "sk_test_key_for_testing")

from agents.social.content_agent import _build_seasonal_context, _build_user_prompt
from agents.social.auto_poster import cmd_delete
from agents.social import social_publisher
from shared import state_registry, config_loader


# --- Helpers ---

def _cleanup_all():
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM content_drafts")
    conn.execute("DELETE FROM content_learnings")
    conn.commit()
    conn.close()


_CURACAO_TZ = timezone(timedelta(hours=-4))


# --- Fake datetime classes for seasonal tests ---

class FakeDatetimeDec(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return real_datetime(2026, 12, 15, 12, 0, 0, tzinfo=tz)


class FakeDatetimeJun(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return real_datetime(2026, 6, 15, 12, 0, 0, tzinfo=tz)


# --- Tests ---

def test_seasonal_calendar_in_config():
    raw = config_loader.get_raw()
    assert "seasonal_calendar" in raw
    cal = raw["seasonal_calendar"]
    assert "events" in cal
    assert len(cal["events"]) >= 5
    assert "name" in cal["events"][0]


def test_build_seasonal_context_includes_season():
    result = _build_seasonal_context()
    assert "Season:" in result


def test_build_seasonal_context_in_user_prompt():
    prompt = _build_user_prompt(3, days_ahead=7)
    assert "SEASONAL CONTEXT" in prompt


def test_set_draft_published_info():
    _cleanup_all()
    try:
        d = state_registry.save_content_draft("A", "Test IG", "Test FB", [], "", "")
        state_registry.update_draft_status(d, "published")
        state_registry.set_draft_published_info(d, "late_123", "https://ig/p/test")
        drafts = state_registry.get_content_drafts()
        match = [x for x in drafts if x["id"] == d]
        assert match[0]["late_post_id"] == "late_123"
        assert match[0]["instagram_url"] == "https://ig/p/test"
    finally:
        _cleanup_all()


def test_get_content_drafts_includes_new_fields():
    _cleanup_all()
    try:
        state_registry.save_content_draft("A", "Fields test", "", [], "", "")
        drafts = state_registry.get_content_drafts()
        assert "late_post_id" in drafts[0]
        assert "instagram_url" in drafts[0]
    finally:
        _cleanup_all()


def test_seasonal_high_season_in_december():
    with patch("agents.social.content_agent.datetime", FakeDatetimeDec):
        result = _build_seasonal_context()
    assert "High season" in result
    assert "Low season" not in result


def test_seasonal_low_season_in_june():
    with patch("agents.social.content_agent.datetime", FakeDatetimeJun):
        result = _build_seasonal_context()
    assert "Low season" in result
    assert "High season" not in result


def test_delete_post_success():
    mock_client = MagicMock()
    mock_client.posts.delete.return_value = MagicMock()
    with patch("agents.social.social_publisher.Late", return_value=mock_client):
        result = social_publisher.delete_post("lp_1")
    assert result is True


def test_delete_post_no_id():
    result = social_publisher.delete_post("")
    assert result is False


def test_cmd_delete_updates_status(capsys):
    _cleanup_all()
    try:
        d = state_registry.save_content_draft("A", "Delete me", "", [], "", "")
        state_registry.update_draft_status(d, "published")
        state_registry.set_draft_published_info(d, "lp_2", "https://ig/p/del")
        with patch("agents.social.auto_poster.social_publisher.delete_post", return_value=True):
            cmd_delete(d)
        captured = capsys.readouterr()
        assert "Deleted" in captured.out
        drafts = state_registry.get_content_drafts()
        match = [x for x in drafts if x["id"] == d]
        assert match[0]["status"] == "deleted"
    finally:
        _cleanup_all()
