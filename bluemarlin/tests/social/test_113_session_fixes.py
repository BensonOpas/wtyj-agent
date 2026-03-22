# tests/social/test_113_session_fixes.py
# Brief 113 — Output review fixes: new endpoints, DB functions, system events

import os
import sys
import pytest

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


# --- WhatsApp conversation queries ---

def test_wa_list_conversations():
    state_registry.wa_store_message("111", "user", "hello")
    state_registry.wa_store_message("222", "user", "world")
    state_registry.wa_save_booking_state("111", {"customer_name": "Alice"}, {}, [])

    convos = state_registry.wa_list_conversations()
    assert len(convos) == 2
    assert convos[0]["phone"] == "222"  # most recent first
    assert convos[1]["phone"] == "111"
    assert convos[1]["customer_name"] == "Alice"


def test_wa_get_full_history():
    for i in range(1, 6):
        state_registry.wa_store_message("333", "user", f"msg{i}")

    history = state_registry.wa_get_full_history("333")
    assert len(history) == 5
    assert history[0]["text"] == "msg1"  # oldest first
    assert history[4]["text"] == "msg5"
    assert history[0]["role"] == "user"


# --- Escalation queries ---

def test_get_all_escalations():
    state_registry.create_pending_notification(
        "escalation", "email", "a@b.com", "Customer A", "subj A", "body A")
    state_registry.create_pending_notification(
        "escalation", "whatsapp", "555", "Customer B", "subj B", "body B")

    esc = state_registry.get_all_escalations()
    assert len(esc) == 2
    assert esc[0]["customer_name"] == "Customer B"  # newest first


def test_create_pending_notification():
    nid = state_registry.create_pending_notification(
        "escalation", "whatsapp", "555", "Test Customer", "test subject", "test body")
    assert nid > 0

    esc = state_registry.get_all_escalations()
    assert esc[0]["status"] == "pending"
    assert esc[0]["customer_name"] == "Test Customer"
    assert esc[0]["channel"] == "whatsapp"


def test_update_notification_status():
    nid = state_registry.create_pending_notification(
        "escalation", "email", "x@y.com", "Resolver", "subj", "body")
    ok = state_registry.update_notification_status(nid, "resolved")
    assert ok is True

    esc = state_registry.get_all_escalations()
    assert esc[0]["status"] == "resolved"


# --- Manual draft with platforms ---

def test_manual_draft_with_platforms():
    draft_id = _make_draft(content_class="D", instagram_caption="manual test")
    state_registry.update_draft_status(draft_id, "approved")
    state_registry.update_draft_platforms(draft_id, ["instagram", "facebook"])

    drafts = state_registry.get_content_drafts()
    d = next(x for x in drafts if x["id"] == draft_id)
    assert d["status"] == "approved"
    assert d["platforms"] == ["instagram", "facebook"]


# --- Schedule slots ---

def test_schedule_slots_roundtrip():
    state_registry.save_schedule_slots([
        {"day_of_week": "Tuesday", "time_utc": "16:00"},
        {"day_of_week": "Friday", "time_utc": "10:00"},
    ])
    slots = state_registry.get_schedule_slots()
    assert len(slots) == 2
    assert slots[0]["day_of_week"] == "Tuesday"
    assert slots[0]["time_utc"] == "16:00"
    assert slots[1]["day_of_week"] == "Friday"


# --- System events ---

def test_system_event_in_history():
    state_registry.wa_store_message("777", "system", "Booking confirmed: test")
    history = state_registry.wa_get_full_history("777")
    assert len(history) == 1
    assert history[0]["role"] == "system"
    assert history[0]["text"] == "Booking confirmed: test"
