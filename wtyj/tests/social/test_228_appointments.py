"""Tests for Brief 228 — appointments backend."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from unittest.mock import patch
from fastapi.testclient import TestClient
from agents.social.webhook_server import app
from shared import state_registry

client = TestClient(app)

SCHEDULING_SUMMARY = {
    "reason": "Calvin wants to schedule.",
    "customerWants": "An activation call.",
    "operatorNeedsToDecide": "Pick a time.",
    "recommendedOptions": ["Confirm Thursday at 09:00", "Suggest another time"],
    "extractedDetails": {
        "intent": "scheduling",
        "proposedTimes": ["Thursday at 09:00", "Thursday at 12:00"],
        "topic": "activation call",
    },
}

NON_SCHEDULING_SUMMARY = {
    "reason": "Customer complaint.",
    "customerWants": "A refund.",
    "operatorNeedsToDecide": "Approve refund or deny.",
    "recommendedOptions": ["Approve refund", "Deny refund"],
    "extractedDetails": {
        "intent": "refund",
        "proposedTimes": [],
        "topic": "refund request",
    },
}

VAGUE_SCHEDULING_SUMMARY = {
    "reason": "Customer wants to chat sometime.",
    "customerWants": "A meeting.",
    "operatorNeedsToDecide": "Propose a time.",
    "recommendedOptions": ["Propose a time", "Ask for availability"],
    "extractedDetails": {
        "intent": "scheduling",
        "proposedTimes": [],
        "topic": "general meeting",
    },
}


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _reset(prefix: str = "test228"):
    conn = state_registry._get_conn()
    conn.execute(
        "DELETE FROM pending_notifications WHERE customer_id LIKE ?",
        (f"{prefix}%",))
    conn.execute(
        "DELETE FROM conversation_status WHERE conversation_id LIKE ?",
        (f"{prefix}%",))
    conn.execute(
        "DELETE FROM appointments WHERE conversation_id LIKE ?",
        (f"%{prefix}%",))
    conn.commit()
    conn.close()


def test_scheduling_escalation_creates_appointment_row():
    """Brief 228: when summary intent=='scheduling' and proposedTimes is
    non-empty, an appointments row lands with status pending_team_confirmation."""
    _reset()
    customer_id = "test228-alice@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=SCHEDULING_SUMMARY):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="email",
            customer_id=customer_id, customer_name="Alice",
            subject="Re: scheduling", body="alert")
    appts = state_registry.appointments_list()
    matches = [a for a in appts if customer_id in a["conversationId"]]
    assert len(matches) == 1
    a = matches[0]
    assert a["status"] == "pending_team_confirmation"
    assert a["dateTimeLabel"] == "Thursday at 09:00"
    assert a["proposedTimes"] == ["Thursday at 09:00", "Thursday at 12:00"]
    assert a["title"] == "activation call"
    assert a["channel"] == "email"
    assert a["customerName"] == "Alice"


def test_vague_scheduling_creates_detected_appointment():
    """Brief 228: scheduling intent without proposedTimes still creates a
    row, but with status='detected' (not pending_team_confirmation)."""
    _reset()
    customer_id = "test228-bob@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=VAGUE_SCHEDULING_SUMMARY):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="whatsapp",
            customer_id=customer_id, customer_name="Bob",
            subject="WhatsApp", body="alert")
    appts = state_registry.appointments_list()
    matches = [a for a in appts if a["conversationId"] == customer_id]
    assert len(matches) == 1
    assert matches[0]["status"] == "detected"
    assert matches[0]["dateTimeLabel"] == ""


def test_non_scheduling_summary_creates_no_appointment():
    """Brief 228: refund / complaint / etc intents don't write an
    appointment row."""
    _reset()
    customer_id = "test228-carol@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=NON_SCHEDULING_SUMMARY):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="whatsapp",
            customer_id=customer_id, customer_name="Carol",
            subject="WhatsApp", body="alert")
    appts = state_registry.appointments_list()
    assert not [a for a in appts if a["conversationId"] == customer_id]


def test_second_scheduling_escalation_updates_existing_appointment():
    """Brief 228: a second scheduling escalation on the same conversation
    UPDATEs the appointment row instead of inserting a duplicate."""
    _reset()
    customer_id = "test228-dan@example.com"
    second_summary = {
        **SCHEDULING_SUMMARY,
        "extractedDetails": {
            "intent": "scheduling",
            "proposedTimes": ["Friday at 14:00"],
            "topic": "follow-up call",
        },
    }
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=SCHEDULING_SUMMARY):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="whatsapp",
            customer_id=customer_id, customer_name="Dan",
            subject="WhatsApp", body="alert")
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=second_summary):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="whatsapp",
            customer_id=customer_id, customer_name="Dan",
            subject="WhatsApp", body="alert")
    appts = state_registry.appointments_list()
    matches = [a for a in appts if a["conversationId"] == customer_id]
    assert len(matches) == 1
    assert matches[0]["dateTimeLabel"] == "Friday at 14:00"
    assert matches[0]["title"] == "follow-up call"


def test_get_appointments_endpoint_returns_items():
    """Brief 228: GET /appointments returns the list under both `items`
    and `appointments` keys."""
    _reset()
    customer_id = "test228-eve@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=SCHEDULING_SUMMARY):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="whatsapp",
            customer_id=customer_id, customer_name="Eve",
            subject="WhatsApp", body="alert")
    token = _login()
    r = client.get("/dashboard/api/appointments", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body
    assert "appointments" in body
    assert body["items"] == body["appointments"]
    matches = [a for a in body["items"] if a["conversationId"] == customer_id]
    assert len(matches) == 1
    assert matches[0]["dateTimeLabel"] == "Thursday at 09:00"


def test_email_appointment_uses_email_routing_key(tmp_path, monkeypatch):
    """Brief 228: for email escalations the conversationId is prefixed
    `email::<thread_key>` so the frontend's /messages/conversations/:phone
    routing works (matches what the escalations list returns)."""
    _reset()
    customer_email = "test228-frank@example.com"
    thread_key = f"subj:{customer_email}:test228 inquiry"
    fake_path = tmp_path / "email_thread_state.json"
    fake_path.write_text(json.dumps(
        {"threads": {thread_key: {"messages": [], "fields": {}, "flags": {}}}}
    ))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                        lambda: str(fake_path))
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=SCHEDULING_SUMMARY):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="email",
            customer_id=customer_email, customer_name="Frank",
            subject="Re: scheduling", body="alert")
    appts = state_registry.appointments_list()
    matches = [a for a in appts if customer_email in a["conversationId"]]
    assert len(matches) == 1
    assert matches[0]["conversationId"] == f"email::{thread_key}"
