# bluemarlin/tests/social/test_099_dashboard_api.py
# Created: Brief 099
# Purpose: Tests for dashboard API endpoints

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_token_067")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "990622044139349")
os.environ.setdefault("LATE_API_KEY", "sk_test_key_for_testing")
os.environ.setdefault("DASHBOARD_PASSWORD", "test_password_099")

from fastapi.testclient import TestClient
from agents.social.webhook_server import app
from shared import state_registry


# --- Helpers ---

client = TestClient(app)


def _cleanup_all():
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM content_drafts")
    conn.execute("DELETE FROM content_learnings")
    conn.commit()
    conn.close()


def _login():
    resp = client.post("/dashboard/api/login", json={"password": "test_password_099"})
    return resp.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# --- Tests ---

def test_login_success():
    resp = client.post("/dashboard/api/login", json={"password": "test_password_099"})
    assert resp.status_code == 200
    assert "token" in resp.json()


def test_login_wrong_password():
    resp = client.post("/dashboard/api/login", json={"password": "wrong"})
    assert resp.status_code == 401


def test_status_requires_auth():
    resp = client.get("/dashboard/api/status")
    assert resp.status_code == 401


def test_status_returns_counts():
    _cleanup_all()
    try:
        token = _login()
        state_registry.save_content_draft("A", "Draft 1", "", [], "", "")
        state_registry.save_content_draft("B", "Draft 2", "", [], "", "")
        state_registry.save_content_learning("test rule")
        resp = client.get("/dashboard/api/status", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["pending"] == 2
        assert data["learnings"] == 1
        assert "season" in data
        assert len(data["season"]) > 0
    finally:
        _cleanup_all()


def test_list_drafts():
    _cleanup_all()
    try:
        token = _login()
        state_registry.save_content_draft("A", "One", "", [], "", "")
        state_registry.save_content_draft("B", "Two", "", [], "", "")
        state_registry.save_content_draft("C", "Three", "", [], "", "")
        resp = client.get("/dashboard/api/drafts", headers=_auth(token))
        assert resp.status_code == 200
        assert len(resp.json()) == 3
    finally:
        _cleanup_all()


def test_list_drafts_filter_by_status():
    _cleanup_all()
    try:
        token = _login()
        state_registry.save_content_draft("A", "Pending 1", "", [], "", "")
        state_registry.save_content_draft("A", "Pending 2", "", [], "", "")
        d3 = state_registry.save_content_draft("B", "Approved 1", "", [], "", "")
        state_registry.update_draft_status(d3, "approved")
        resp = client.get("/dashboard/api/drafts?status=pending", headers=_auth(token))
        assert resp.status_code == 200
        assert len(resp.json()) == 2
    finally:
        _cleanup_all()


def test_approve_draft():
    _cleanup_all()
    try:
        token = _login()
        d = state_registry.save_content_draft("A", "Approve me", "", [], "", "")
        resp = client.post(f"/dashboard/api/drafts/{d}/approve", headers=_auth(token))
        assert resp.status_code == 200
        drafts = state_registry.get_content_drafts()
        match = [x for x in drafts if x["id"] == d]
        assert match[0]["status"] == "approved"
    finally:
        _cleanup_all()


def test_reject_draft():
    _cleanup_all()
    try:
        token = _login()
        d = state_registry.save_content_draft("B", "Reject me", "", [], "", "")
        resp = client.post(
            f"/dashboard/api/drafts/{d}/reject",
            headers=_auth(token),
            json={"reason": "too generic"}
        )
        assert resp.status_code == 200
        drafts = state_registry.get_content_drafts()
        match = [x for x in drafts if x["id"] == d]
        assert match[0]["status"] == "rejected"
        assert match[0]["rejection_reason"] == "too generic"
    finally:
        _cleanup_all()


def test_generate_drafts():
    _cleanup_all()
    try:
        token = _login()
        mock_drafts = [
            {"id": 1, "content_class": "A", "instagram_caption": "Mock", "status": "pending"},
            {"id": 2, "content_class": "B", "instagram_caption": "Mock 2", "status": "pending"},
        ]
        with patch("dashboard.api.content_agent.generate_drafts", return_value=mock_drafts):
            resp = client.post(
                "/dashboard/api/drafts/generate",
                headers=_auth(token),
                json={"count": 2}
            )
        assert resp.status_code == 200
        assert resp.json()["count"] == 2
    finally:
        _cleanup_all()


def test_get_learnings():
    _cleanup_all()
    try:
        token = _login()
        state_registry.save_content_learning("rule one")
        state_registry.save_content_learning("rule two")
        resp = client.get("/dashboard/api/learnings", headers=_auth(token))
        assert resp.status_code == 200
        assert len(resp.json()) == 2
    finally:
        _cleanup_all()


def test_deactivate_learning():
    _cleanup_all()
    try:
        token = _login()
        lid = state_registry.save_content_learning("remove me")
        resp = client.delete(f"/dashboard/api/learnings/{lid}", headers=_auth(token))
        assert resp.status_code == 200
        assert len(state_registry.get_active_learnings()) == 0
    finally:
        _cleanup_all()


def test_availability():
    token = _login()
    resp = client.get("/dashboard/api/availability?days=7", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0  # daily trips (Klein Curaçao, Jet Ski) guarantee results
    item = data[0]
    assert "trip_key" in item
    assert "date" in item
    assert "spots_remaining" in item
    assert "capacity" in item
    assert item["capacity"] > 0
