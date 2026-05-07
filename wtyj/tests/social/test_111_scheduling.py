# tests/social/test_111_scheduling.py
# Brief 111 — Scheduling + auto-post tests

import os
import sys
import pytest
from datetime import datetime, timezone, timedelta

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
        instagram_caption="Test caption",
        facebook_caption="Test FB",
        hashtags=["#test"],
        visual_suggestion="test",
        reasoning="test",
    )
    defaults.update(overrides)
    return state_registry.save_content_draft(**defaults)


# --- Schedule/Unschedule ---

def test_schedule_draft():
    draft_id = _make_draft()
    state_registry.update_draft_status(draft_id, "approved")
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    ok = state_registry.schedule_draft(draft_id, future)
    assert ok is True
    drafts = state_registry.get_content_drafts()
    d = next(x for x in drafts if x["id"] == draft_id)
    assert d["status"] == "scheduled"
    assert d["scheduled_at"] is not None


def test_schedule_pending_draft_fails():
    draft_id = _make_draft()  # status = pending
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    ok = state_registry.schedule_draft(draft_id, future)
    assert ok is False


def test_unschedule_draft():
    draft_id = _make_draft()
    state_registry.update_draft_status(draft_id, "approved")
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    state_registry.schedule_draft(draft_id, future)
    ok = state_registry.unschedule_draft(draft_id)
    assert ok is True
    drafts = state_registry.get_content_drafts()
    d = next(x for x in drafts if x["id"] == draft_id)
    assert d["status"] == "approved"
    assert d["scheduled_at"] is None


# --- Scheduled Due ---

def test_get_scheduled_due():
    draft_id = _make_draft()
    state_registry.update_draft_status(draft_id, "approved")
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    state_registry.schedule_draft(draft_id, past)
    # Manually set scheduled_at to past (schedule_draft requires approved status)
    due = state_registry.get_scheduled_due()
    assert len(due) == 1
    assert due[0]["id"] == draft_id


def test_future_draft_not_due():
    draft_id = _make_draft()
    state_registry.update_draft_status(draft_id, "approved")
    future = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    state_registry.schedule_draft(draft_id, future)
    due = state_registry.get_scheduled_due()
    assert len(due) == 0


# --- Schedule Slots ---

def test_schedule_slots_crud():
    slots = [
        {"day_of_week": "Tuesday", "time_utc": "16:00"},
        {"day_of_week": "Thursday", "time_utc": "18:00"},
    ]
    state_registry.save_schedule_slots(slots)
    result = state_registry.get_schedule_slots()
    assert len(result) == 2
    assert result[0]["day_of_week"] == "Tuesday"
    assert result[1]["time_utc"] == "18:00"


def test_save_slots_replaces_old():
    state_registry.save_schedule_slots([{"day_of_week": "Monday", "time_utc": "09:00"}])
    assert len(state_registry.get_schedule_slots()) == 1
    state_registry.save_schedule_slots([
        {"day_of_week": "Wednesday", "time_utc": "10:00"},
        {"day_of_week": "Friday", "time_utc": "14:00"},
    ])
    result = state_registry.get_schedule_slots()
    assert len(result) == 2
    assert result[0]["day_of_week"] == "Wednesday"


# --- API Tests ---

from fastapi.testclient import TestClient
from agents.social.webhook_server import app

_client = TestClient(app)


def _login():
    resp = _client.post("/dashboard/api/login", json={"password": "testpass"})
    return resp.json()["token"]


def test_api_schedule_draft():
    token = _login()
    draft_id = _make_draft()
    state_registry.update_draft_status(draft_id, "approved")
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    resp = _client.post(
        f"/dashboard/api/drafts/{draft_id}/schedule",
        headers={"Authorization": f"Bearer {token}"},
        json={"scheduled_at": future},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_api_unschedule_draft():
    token = _login()
    draft_id = _make_draft()
    state_registry.update_draft_status(draft_id, "approved")
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    state_registry.schedule_draft(draft_id, future)
    resp = _client.post(
        f"/dashboard/api/drafts/{draft_id}/unschedule",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


def test_api_schedule_slots():
    # Brief 212: PUT /schedule/slots now accepts the raw JSON array directly
    # (matches SR's frontend lib/api.ts:saveScheduleSlots which posts a
    # ScheduleSlot[] without a wrapper). The old {slots: [...]} body shape
    # is no longer accepted by the endpoint.
    token = _login()
    resp = _client.put(
        "/dashboard/api/schedule/slots",
        headers={"Authorization": f"Bearer {token}"},
        json=[{"day_of_week": "Saturday", "time_utc": "10:00"}],
    )
    assert resp.status_code == 200
    slots = resp.json()["slots"]
    assert len(slots) == 1
    assert slots[0]["day_of_week"] == "Saturday"
