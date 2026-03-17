# tests/social/test_102_dashboard_polish.py
# Brief 102 — Draft editing backend tests

import json
import os
import sys
import tempfile
from unittest.mock import patch
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from shared import state_registry
from fastapi.testclient import TestClient
from agents.social.webhook_server import app

_client = TestClient(app)


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(state_registry, "DB_PATH", db_path)


def _make_draft(**overrides):
    defaults = dict(
        content_class="A",
        instagram_caption="Test IG caption",
        facebook_caption="Test FB caption",
        hashtags=["#test"],
        visual_suggestion="test visual",
        reasoning="test reasoning",
    )
    defaults.update(overrides)
    return state_registry.save_content_draft(**defaults)


# --- update_draft_content tests ---

def test_update_draft_content_caption():
    draft_id = _make_draft()
    ok = state_registry.update_draft_content(draft_id, instagram_caption="New IG caption")
    assert ok is True
    drafts = state_registry.get_content_drafts()
    draft = next(d for d in drafts if d["id"] == draft_id)
    assert draft["instagram_caption"] == "New IG caption"
    assert draft["facebook_caption"] == "Test FB caption"  # unchanged


def test_update_draft_content_partial():
    draft_id = _make_draft()
    ok = state_registry.update_draft_content(draft_id, facebook_caption="New FB only")
    assert ok is True
    drafts = state_registry.get_content_drafts()
    draft = next(d for d in drafts if d["id"] == draft_id)
    assert draft["facebook_caption"] == "New FB only"
    assert draft["instagram_caption"] == "Test IG caption"  # unchanged


def test_update_draft_content_hashtags():
    draft_id = _make_draft()
    ok = state_registry.update_draft_content(draft_id, hashtags=["#new", "#tags"])
    assert ok is True
    drafts = state_registry.get_content_drafts()
    draft = next(d for d in drafts if d["id"] == draft_id)
    assert draft["hashtags"] == ["#new", "#tags"]


def test_update_draft_content_not_pending():
    draft_id = _make_draft()
    state_registry.update_draft_status(draft_id, "approved")
    ok = state_registry.update_draft_content(draft_id, instagram_caption="Should fail")
    assert ok is False
    drafts = state_registry.get_content_drafts()
    draft = next(d for d in drafts if d["id"] == draft_id)
    assert draft["instagram_caption"] == "Test IG caption"  # unchanged


def test_update_draft_content_nonexistent():
    ok = state_registry.update_draft_content(9999, instagram_caption="No such draft")
    assert ok is False


def test_update_draft_content_no_fields():
    draft_id = _make_draft()
    ok = state_registry.update_draft_content(draft_id)
    assert ok is False


def test_update_draft_content_all_fields():
    draft_id = _make_draft()
    ok = state_registry.update_draft_content(
        draft_id,
        instagram_caption="IG2",
        facebook_caption="FB2",
        hashtags=["#a", "#b"],
    )
    assert ok is True
    drafts = state_registry.get_content_drafts()
    draft = next(d for d in drafts if d["id"] == draft_id)
    assert draft["instagram_caption"] == "IG2"
    assert draft["facebook_caption"] == "FB2"
    assert draft["hashtags"] == ["#a", "#b"]


# --- API endpoint tests ---

def _login():
    resp = _client.post("/dashboard/api/login", json={"password": "testpass"})
    return resp.json()["token"]


def test_api_update_draft_endpoint():
    token = _login()
    with patch.object(state_registry, "update_draft_content", return_value=True) as mock:
        resp = _client.put(
            "/dashboard/api/drafts/1",
            json={"instagram_caption": "Edited"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock.assert_called_once_with(1, instagram_caption="Edited", facebook_caption=None, hashtags=None)


def test_api_update_draft_not_pending():
    token = _login()
    with patch.object(state_registry, "update_draft_content", return_value=False):
        resp = _client.put(
            "/dashboard/api/drafts/1",
            json={"instagram_caption": "Nope"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 400
    assert "not in pending" in resp.json()["detail"].lower()
