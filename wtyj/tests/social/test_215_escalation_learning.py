# test_215_escalation_learning.py
# Brief 215: operator answers in /reply and /guidance auto-create approved
# learning entries in escalation_learnings. Plus 3 endpoints (approve, save,
# repointed /learning GET) and /resolve body-param support for saveAsLearning.

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from agents.social.webhook_server import app

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_escalation(channel, customer_id, mode=None):
    from shared import state_registry
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation", channel=channel,
        customer_id=customer_id, customer_name="Test",
        subject="[ESCALATION] test215", body="test body")
    if mode:
        state_registry.set_escalation_mode(esc_id, mode)
    return esc_id


def _cleanup(esc_id, customer_id):
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM pending_notifications WHERE id = ?", (esc_id,))
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?", (customer_id,))
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (customer_id,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (customer_id,))
    conn.execute("DELETE FROM escalation_learnings WHERE conversation_id = ?", (customer_id,))
    conn.commit()
    conn.close()


# --- Test 1: save_escalation_learning round-trip
def test_save_escalation_learning_round_trip():
    from shared import state_registry
    el_id = state_registry.save_escalation_learning(
        conversation_id="215_rt_phone", channel="whatsapp",
        source_question="how much for 4 people?",
        human_answer="$300 total for 4 people on the half-day trip.")
    rows = state_registry.list_escalation_learnings()
    matched = next((r for r in rows if r["id"] == el_id), None)
    assert matched is not None
    assert matched["humanAnswer"] == "$300 total for 4 people on the half-day trip."
    assert matched["sourceQuestion"] == "how much for 4 people?"
    assert matched["status"] == "approved"
    assert matched["aiMayUseAutomatically"] is True
    state_registry.delete_escalation_learning(el_id)


# --- Test 2: invalid status update returns False
def test_update_escalation_learning_status_invalid_value_returns_false():
    from shared import state_registry
    el_id = state_registry.save_escalation_learning(
        conversation_id="215_inv_phone", channel="whatsapp",
        source_question="?", human_answer="x")
    ok = state_registry.update_escalation_learning_status(el_id, "garbage")
    assert ok is False
    rows = state_registry.list_escalation_learnings()
    matched = next(r for r in rows if r["id"] == el_id)
    assert matched["status"] == "approved"  # unchanged
    state_registry.delete_escalation_learning(el_id)


# --- Test 3: GET /learning returns escalation_learnings with status field
def test_get_learning_returns_escalation_learnings_with_status_field():
    from shared import state_registry
    el_id = state_registry.save_escalation_learning(
        conversation_id="215_get_phone", channel="whatsapp",
        source_question="?", human_answer="for the dashboard list")
    token = _login()
    r = client.get("/dashboard/api/learning", headers=_auth(token))
    assert r.status_code == 200
    payload = r.json()
    matched = next((row for row in payload if row["id"] == el_id), None)
    assert matched is not None
    assert matched["status"] == "approved"
    assert matched["humanAnswer"] == "for the dashboard list"
    state_registry.delete_escalation_learning(el_id)


# --- Test 4: POST /learning/:id/approve flips status
def test_post_learning_approve_flips_status():
    from shared import state_registry
    el_id = state_registry.save_escalation_learning(
        conversation_id="215_approve_phone", channel="whatsapp",
        source_question="?", human_answer="suggest", status="suggested")
    token = _login()
    r = client.post(f"/dashboard/api/learning/{el_id}/approve",
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    rows = state_registry.list_escalation_learnings()
    assert next(row for row in rows if row["id"] == el_id)["status"] == "approved"
    state_registry.delete_escalation_learning(el_id)


# --- Test 5: POST /learning/:id/save flips status
def test_post_learning_save_flips_status():
    from shared import state_registry
    el_id = state_registry.save_escalation_learning(
        conversation_id="215_save_phone", channel="whatsapp",
        source_question="?", human_answer="save")
    token = _login()
    r = client.post(f"/dashboard/api/learning/{el_id}/save",
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "saved"
    rows = state_registry.list_escalation_learnings()
    assert next(row for row in rows if row["id"] == el_id)["status"] == "saved"
    state_registry.delete_escalation_learning(el_id)


# --- Test 6: DELETE /learning/:id removes the row
def test_delete_learning_removes_row():
    from shared import state_registry
    el_id = state_registry.save_escalation_learning(
        conversation_id="215_delete_phone", channel="whatsapp",
        source_question="?", human_answer="delete me")
    token = _login()
    r = client.delete(f"/dashboard/api/learning/{el_id}", headers=_auth(token))
    assert r.status_code == 200
    rows = state_registry.list_escalation_learnings()
    assert all(row["id"] != el_id for row in rows)


# --- Test 7: /reply WhatsApp creates approved learning
@patch("dashboard.api.send_whatsapp_message", return_value=True)
@patch("dashboard.api.marina_agent")
def test_reply_whatsapp_creates_approved_learning(mock_marina, mock_wa_send):
    from shared import state_registry
    customer_id = "215_reply_wa_phone"
    esc_id = _seed_escalation("whatsapp", customer_id, mode="hard")

    mock_marina.process_message.return_value = {
        "reply": "ok", "fields": {}, "flags": {}, "intents": [],
        "confidence": "high", "requires_human": False,
    }

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/reply",
                     json={"message": "BRIEF 215 — operator answer text"},
                     headers=_auth(token))
    assert r.status_code == 200, r.text

    rows = state_registry.list_escalation_learnings()
    matched = [row for row in rows if row["conversationId"] == customer_id]
    assert len(matched) == 1, f"expected 1 learning row, got {len(matched)}"
    assert matched[0]["humanAnswer"] == "BRIEF 215 — operator answer text"
    assert matched[0]["status"] == "approved"
    assert matched[0]["channel"] == "whatsapp"

    _cleanup(esc_id, customer_id)


# --- Test 8: /guidance email creates approved learning
@patch("dashboard.api.smtp_send")
@patch("dashboard.api.state_registry.email_append_assistant_message",
       return_value="subj:215@example.com:test")
@patch("dashboard.api.marina_agent")
def test_guidance_email_creates_approved_learning(mock_marina, mock_append, mock_smtp):
    from shared import state_registry
    customer_email = "215-guidance-learn@example.com"
    esc_id = _seed_escalation("email", customer_email, mode="soft")

    mock_marina.process_message.return_value = {
        "reply": "Marina's polished version", "fields": {}, "flags": {},
        "intents": [], "confidence": "high", "requires_human": False,
    }

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/guidance",
                     json={"message": "BRIEF 215 — coach Marina text"},
                     headers=_auth(token))
    assert r.status_code == 200, r.text

    rows = state_registry.list_escalation_learnings()
    matched = [row for row in rows if row["conversationId"] == customer_email]
    assert len(matched) == 1
    # humanAnswer is the operator's coaching text, NOT Marina's reformulation
    assert matched[0]["humanAnswer"] == "BRIEF 215 — coach Marina text"
    assert matched[0]["channel"] == "email"
    assert matched[0]["status"] == "approved"

    _cleanup(esc_id, customer_email)


# --- Test 9: /resolve with saveAsLearning creates row
def test_resolve_with_save_as_learning_creates_row():
    from shared import state_registry
    customer_id = "215_resolve_save_phone"
    esc_id = _seed_escalation("whatsapp", customer_id)

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/resolve",
                     json={"resolutionNote": "set expectations clearly",
                           "saveAsLearning": True,
                           "category": "complaint",
                           "autoUseNextTime": True},
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["learningEntryId"] is not None

    rows = state_registry.list_escalation_learnings()
    matched = next((row for row in rows if row["id"] == body["learningEntryId"]), None)
    assert matched is not None
    assert matched["humanAnswer"] == "set expectations clearly"
    assert matched["category"] == "complaint"

    _cleanup(esc_id, customer_id)


# --- Test 10: /resolve without saveAsLearning creates no learning row
def test_resolve_without_save_as_learning_creates_no_row():
    from shared import state_registry
    customer_id = "215_resolve_no_save_phone"
    esc_id = _seed_escalation("whatsapp", customer_id)

    rows_before = state_registry.list_escalation_learnings()
    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/resolve",
                     json={},
                     headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["learningEntryId"] is None

    rows_after = state_registry.list_escalation_learnings()
    assert len(rows_after) == len(rows_before)

    _cleanup(esc_id, customer_id)
