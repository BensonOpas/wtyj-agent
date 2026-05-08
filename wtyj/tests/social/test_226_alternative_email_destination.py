"""Tests for Brief 226 — alternative email destination on escalation alerts."""
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


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _reset_alert_settings():
    """Wipe the singleton row + delivery audit so each test starts clean."""
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM alert_settings")
    conn.execute("DELETE FROM alert_deliveries WHERE channel = 'email'")
    conn.commit()
    conn.close()


def test_get_returns_alternative_destination_field():
    """Brief 226: GET response always includes alternativeDestination
    (empty string when not configured)."""
    _reset_alert_settings()
    token = _login()
    r = client.get("/dashboard/api/settings/escalation-alerts",
                   headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert "alternativeDestination" in body["channels"]["email"]
    assert body["channels"]["email"]["alternativeDestination"] == ""


def test_put_persists_alternative_destination():
    """Brief 226: alternativeDestination round-trips through PUT → DB → GET."""
    _reset_alert_settings()
    token = _login()
    payload = {"channels": {
        "email": {"enabled": True, "destination": "primary@example.com",
                  "alternativeDestination": "backup@example.com"},
        "whatsapp": {"enabled": False, "destination": ""},
        "telegram": {"enabled": False, "destination": ""},
        "messenger": {"enabled": False, "destination": ""},
    }}
    r = client.put("/dashboard/api/settings/escalation-alerts",
                   json=payload, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["channels"]["email"]["alternativeDestination"] == "backup@example.com"
    r2 = client.get("/dashboard/api/settings/escalation-alerts",
                    headers=_auth(token))
    assert r2.json()["channels"]["email"]["alternativeDestination"] == "backup@example.com"


def test_put_400_on_invalid_alternative_email():
    """Brief 226: invalid alternative rejected (FastAPI Pydantic = 422)."""
    _reset_alert_settings()
    token = _login()
    payload = {"channels": {
        "email": {"enabled": True, "destination": "primary@example.com",
                  "alternativeDestination": "not-an-email"},
        "whatsapp": {"enabled": False, "destination": ""},
        "telegram": {"enabled": False, "destination": ""},
        "messenger": {"enabled": False, "destination": ""},
    }}
    r = client.put("/dashboard/api/settings/escalation-alerts",
                   json=payload, headers=_auth(token))
    assert r.status_code in (400, 422)


def test_put_accepts_empty_alternative():
    """Brief 226: empty alternativeDestination is allowed."""
    _reset_alert_settings()
    token = _login()
    payload = {"channels": {
        "email": {"enabled": True, "destination": "primary@example.com",
                  "alternativeDestination": ""},
        "whatsapp": {"enabled": False, "destination": ""},
        "telegram": {"enabled": False, "destination": ""},
        "messenger": {"enabled": False, "destination": ""},
    }}
    r = client.put("/dashboard/api/settings/escalation-alerts",
                   json=payload, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["channels"]["email"]["alternativeDestination"] == ""


@patch("dashboard.api.smtp_send")
def test_alert_dispatch_sends_to_both_addresses(mock_smtp):
    """Brief 226: when alternativeDestination is configured, _fire_escalation_alerts
    sends to BOTH primary and alternative, recording one delivery row per attempt."""
    _reset_alert_settings()
    state_registry.save_alert_settings({
        "email": {"enabled": True, "destination": "primary@example.com",
                  "alternativeDestination": "backup@example.com"},
        "whatsapp": {"enabled": False, "destination": ""},
        "telegram": {"enabled": False, "destination": ""},
        "messenger": {"enabled": False, "destination": ""},
    })
    from dashboard.api import _fire_escalation_alerts
    _fire_escalation_alerts(escalation_id=99001, customer_name="Alice",
                            channel="email", summary="testing 226", mode="hard")
    sent_recipients = [c.args[0] for c in mock_smtp.call_args_list]
    assert sorted(sent_recipients) == ["backup@example.com", "primary@example.com"]
    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT destination, status FROM alert_deliveries "
        "WHERE escalation_id = 99001 AND channel = 'email' ORDER BY destination"
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert {r[0] for r in rows} == {"primary@example.com", "backup@example.com"}
    assert all(r[1] == "sent" for r in rows)


@patch("dashboard.api.smtp_send")
def test_alert_dispatch_alternative_failure_does_not_block_primary(mock_smtp):
    """Brief 226: if primary succeeds but alternative fails, the primary
    delivery row is still 'sent' and the alternative row is 'failed'."""
    _reset_alert_settings()
    state_registry.save_alert_settings({
        "email": {"enabled": True, "destination": "primary@example.com",
                  "alternativeDestination": "broken@example.com"},
        "whatsapp": {"enabled": False, "destination": ""},
        "telegram": {"enabled": False, "destination": ""},
        "messenger": {"enabled": False, "destination": ""},
    })

    def smtp_side_effect(to_addr, *args, **kwargs):
        if to_addr == "broken@example.com":
            raise Exception("alternative send failed")
        return None
    mock_smtp.side_effect = smtp_side_effect

    from dashboard.api import _fire_escalation_alerts
    _fire_escalation_alerts(escalation_id=99002, customer_name="Bob",
                            channel="email", summary="testing 226 partial fail",
                            mode="hard")
    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT destination, status, error FROM alert_deliveries "
        "WHERE escalation_id = 99002 AND channel = 'email' ORDER BY destination"
    ).fetchall()
    conn.close()
    by_dest = {r[0]: r for r in rows}
    assert by_dest["primary@example.com"][1] == "sent"
    assert by_dest["broken@example.com"][1] == "failed"
    assert "alternative send failed" in (by_dest["broken@example.com"][2] or "")


@patch("dashboard.api.smtp_send")
def test_dispatch_dedupes_when_primary_equals_alternative(mock_smtp):
    """Brief 226: if operator types the same address into both fields,
    we send once and log one delivery row — not two duplicates."""
    _reset_alert_settings()
    state_registry.save_alert_settings({
        "email": {"enabled": True, "destination": "same@example.com",
                  "alternativeDestination": "same@example.com"},
        "whatsapp": {"enabled": False, "destination": ""},
        "telegram": {"enabled": False, "destination": ""},
        "messenger": {"enabled": False, "destination": ""},
    })
    from dashboard.api import _fire_escalation_alerts
    _fire_escalation_alerts(escalation_id=99003, customer_name="Carol",
                            channel="email", summary="testing 226 dedupe",
                            mode="hard")
    assert mock_smtp.call_count == 1
    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT destination FROM alert_deliveries "
        "WHERE escalation_id = 99003 AND channel = 'email'"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
