"""Tests for Brief 227 — decision-first escalation summary."""
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

# Importing webhook_server triggers dashboard.api import, which runs
# state_registry.set_summary_dispatcher(_generate_escalation_summary).
from agents.social.webhook_server import app
from shared import state_registry

client = TestClient(app)

SAMPLE_SUMMARY = {
    "reason": ("Calvin wants to schedule an activation call. He suggested "
               "Thursday at 09:00 or Thursday at 12:00. Marina needs a "
               "human to choose one of the proposed slots."),
    "customerWants": "An activation call this week.",
    "operatorNeedsToDecide": ("Choose Thursday at 09:00, choose Thursday at "
                              "12:00, suggest another time, or ask for more "
                              "availability."),
    "recommendedOptions": [
        "Confirm Thursday at 09:00",
        "Confirm Thursday at 12:00",
        "Suggest another time",
        "Ask Marina to collect more availability",
        "Switch to human takeover",
    ],
    "extractedDetails": {
        "intent": "scheduling",
        "proposedTimes": ["Thursday at 09:00", "Thursday at 12:00"],
        "topic": "activation call",
    },
}


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _reset_escalations(prefix: str = "test227"):
    """Wipe escalation rows for our test customer_ids so each test starts
    clean. We don't truncate the whole table — other tests share it."""
    conn = state_registry._get_conn()
    conn.execute(
        "DELETE FROM pending_notifications WHERE customer_id LIKE ?",
        (f"{prefix}%",))
    conn.execute(
        "DELETE FROM conversation_status WHERE conversation_id LIKE ?",
        (f"{prefix}%",))
    conn.commit()
    conn.close()


def test_summary_persisted_on_escalation_create():
    """Brief 227: when the summary dispatcher returns a dict,
    create_pending_notification persists it on the same row as JSON."""
    _reset_escalations()
    customer_id = "test227-alice@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=SAMPLE_SUMMARY):
        row_id = state_registry.create_pending_notification(
            notification_type="escalation",
            channel="email",
            customer_id=customer_id,
            customer_name="Alice",
            subject="Re: scheduling",
            body="alert text",
        )
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT escalation_summary FROM pending_notifications WHERE id = ?",
        (row_id,)).fetchone()
    conn.close()
    assert row[0]
    parsed = json.loads(row[0])
    assert parsed["recommendedOptions"][0] == "Confirm Thursday at 09:00"
    assert parsed["extractedDetails"]["proposedTimes"] == [
        "Thursday at 09:00", "Thursday at 12:00"]


def test_summary_failure_does_not_block_escalation_create():
    """Brief 227: if the generator raises, the escalation row is still
    created with escalation_summary IS NULL."""
    _reset_escalations()
    customer_id = "test227-bob@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               side_effect=Exception("Claude exploded")):
        row_id = state_registry.create_pending_notification(
            notification_type="escalation",
            channel="email",
            customer_id=customer_id,
            customer_name="Bob",
            subject="Re: anything",
            body="alert text",
        )
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT escalation_summary FROM pending_notifications WHERE id = ?",
        (row_id,)).fetchone()
    conn.close()
    assert row[0] is None


def test_dedup_unresolved_escalation_updates_in_place():
    """Brief 227: a second escalation on the same customer_id while one is
    still pending UPDATEs the existing row instead of inserting a new one."""
    _reset_escalations()
    customer_id = "test227-carol@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=SAMPLE_SUMMARY):
        first = state_registry.create_pending_notification(
            notification_type="escalation", channel="email",
            customer_id=customer_id, customer_name="Carol",
            subject="Re: first", body="first body")
        second = state_registry.create_pending_notification(
            notification_type="escalation", channel="email",
            customer_id=customer_id, customer_name="Carol",
            subject="Re: second update", body="second body")
    assert first == second
    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT id, subject FROM pending_notifications "
        "WHERE customer_id = ? AND notification_type = 'escalation'",
        (customer_id,)).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][1] == "Re: second update"


def test_get_all_escalations_surfaces_summary_fields():
    """Brief 227: GET /escalations returns escalationSummary + lifted
    recommendedOptions + extractedDetails."""
    _reset_escalations()
    customer_id = "test227-dan@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=SAMPLE_SUMMARY):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="email",
            customer_id=customer_id, customer_name="Dan",
            subject="Re: brief 227", body="alert")
    token = _login()
    r = client.get("/dashboard/api/escalations", headers=_auth(token))
    assert r.status_code == 200
    matches = [e for e in r.json() if e.get("customer_id") == customer_id]
    assert len(matches) == 1
    e = matches[0]
    assert e["escalationSummary"]["customerWants"] == "An activation call this week."
    assert e["recommendedOptions"][:2] == [
        "Confirm Thursday at 09:00", "Confirm Thursday at 12:00"]
    assert e["extractedDetails"]["proposedTimes"] == [
        "Thursday at 09:00", "Thursday at 12:00"]


def test_conversation_detail_includes_summary():
    """Brief 227: GET /messages/conversations/{phone} surfaces the summary
    block from the most recent unresolved escalation."""
    _reset_escalations()
    customer_id = "test227-eve@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=SAMPLE_SUMMARY):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="whatsapp",
            customer_id=customer_id, customer_name="Eve",
            subject="WhatsApp escalation", body="alert")
    token = _login()
    r = client.get(f"/dashboard/api/messages/conversations/{customer_id}",
                   headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["escalationSummary"]["customerWants"] == "An activation call this week."
    assert body["recommendedOptions"][:2] == [
        "Confirm Thursday at 09:00", "Confirm Thursday at 12:00"]


def test_summary_generator_extracts_all_proposed_times():
    """Brief 227: the generator's tool schema demands `proposedTimes` be
    an array of every time mentioned. Smoke test the schema shape."""
    from dashboard.escalation_summary import SUMMARY_TOOL
    schema = SUMMARY_TOOL["input_schema"]["properties"]
    assert "proposedTimes" in schema["extractedDetails"]["properties"]
    assert "recommendedOptions" in schema
    required = set(SUMMARY_TOOL["input_schema"]["required"])
    assert {"reason", "customerWants", "operatorNeedsToDecide",
            "recommendedOptions", "extractedDetails"} <= required


def test_relay_notification_does_not_get_summary():
    """Brief 227: notification_type != 'escalation' must NOT trigger summary
    generation (relay rows are Marina asking the team — different flow)."""
    _reset_escalations()
    customer_id = "test227-frank@example.com"
    with patch("dashboard.escalation_summary.generate_summary") as mock_gen:
        state_registry.create_pending_notification(
            notification_type="relay", channel="whatsapp",
            customer_id=customer_id, customer_name="Frank",
            subject="ask the team", body="some question")
    mock_gen.assert_not_called()
