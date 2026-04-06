# tests/social/test_110_facebook_publishing.py
# Brief 110 — Facebook publishing tests

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from shared import state_registry


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(state_registry, "DB_PATH", db_path)


def _make_draft(**overrides):
    defaults = dict(
        content_class="A",
        instagram_caption="IG caption",
        facebook_caption="FB caption",
        hashtags=["#test"],
        visual_suggestion="test",
        reasoning="test",
    )
    defaults.update(overrides)
    return state_registry.save_content_draft(**defaults)


# --- state_registry tests ---

def test_platforms_json_default():
    draft_id = _make_draft()
    drafts = state_registry.get_content_drafts()
    d = next(x for x in drafts if x["id"] == draft_id)
    assert d["platforms"] == ["instagram"]


def test_update_draft_platforms():
    draft_id = _make_draft()
    ok = state_registry.update_draft_platforms(draft_id, ["instagram", "facebook"])
    assert ok is True
    drafts = state_registry.get_content_drafts()
    d = next(x for x in drafts if x["id"] == draft_id)
    assert d["platforms"] == ["instagram", "facebook"]


def test_set_draft_facebook_info():
    draft_id = _make_draft()
    state_registry.set_draft_facebook_info(draft_id, late_post_id="fb123", facebook_url="https://fb.com/post/123")
    drafts = state_registry.get_content_drafts()
    d = next(x for x in drafts if x["id"] == draft_id)
    assert d["facebook_url"] == "https://fb.com/post/123"
    assert d["late_facebook_post_id"] == "fb123"


def test_platforms_toggle_instagram_only():
    draft_id = _make_draft()
    state_registry.update_draft_platforms(draft_id, ["instagram"])
    drafts = state_registry.get_content_drafts()
    d = next(x for x in drafts if x["id"] == draft_id)
    assert "facebook" not in d["platforms"]


def test_platforms_toggle_facebook_only():
    draft_id = _make_draft()
    state_registry.update_draft_platforms(draft_id, ["facebook"])
    drafts = state_registry.get_content_drafts()
    d = next(x for x in drafts if x["id"] == draft_id)
    assert d["platforms"] == ["facebook"]
    assert "instagram" not in d["platforms"]


# --- API tests ---

from fastapi.testclient import TestClient
from agents.social.webhook_server import app

_client = TestClient(app)


def _login():
    resp = _client.post("/dashboard/api/login", json={"password": "testpass"})
    return resp.json()["token"]


def test_api_update_platforms():
    token = _login()
    draft_id = _make_draft()
    resp = _client.put(
        f"/dashboard/api/drafts/{draft_id}/platforms",
        headers={"Authorization": f"Bearer {token}"},
        json={"platforms": ["instagram", "facebook"]},
    )
    assert resp.status_code == 200
    assert resp.json()["platforms"] == ["instagram", "facebook"]


def test_api_available_platforms():
    token = _login()
    with patch.object(state_registry, "get_content_drafts", return_value=[]):
        resp = _client.get(
            "/dashboard/api/platforms/available",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    assert "platforms" in resp.json()
