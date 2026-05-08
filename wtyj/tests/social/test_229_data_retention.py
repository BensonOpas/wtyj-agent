"""Tests for Brief 229 — data retention settings storage + GET/PUT."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from fastapi.testclient import TestClient
from agents.social.webhook_server import app
from shared import state_registry

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _reset():
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM data_retention_settings")
    conn.commit()
    conn.close()


def test_get_returns_defaults_when_no_row_exists():
    """Brief 229: GET returns SR's DEFAULT_DATA_RETENTION shape when
    nothing has been saved yet."""
    _reset()
    token = _login()
    r = client.get("/dashboard/api/settings/data-retention",
                   headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["activeInboxArchiveAfterDays"] == 90
    assert body["archiveRetentionMonths"] == 24
    assert body["endOfRetentionAction"] == "anonymize"
    assert body["keepApprovedLearnings"] is True
    assert body["auditLogRetentionMonths"] == 24
    assert body["status"] == {"policyActive": False}


def test_put_persists_full_settings():
    """Brief 229: PUT round-trips through DB and the next GET returns
    the same values."""
    _reset()
    token = _login()
    payload = {
        "activeInboxArchiveAfterDays": 60,
        "archiveRetentionMonths": 36,
        "endOfRetentionAction": "delete",
        "keepApprovedLearnings": False,
        "auditLogRetentionMonths": 12,
    }
    r = client.put("/dashboard/api/settings/data-retention",
                   json=payload, headers=_auth(token))
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["activeInboxArchiveAfterDays"] == 60
    assert saved["archiveRetentionMonths"] == 36
    assert saved["endOfRetentionAction"] == "delete"
    assert saved["keepApprovedLearnings"] is False
    assert saved["auditLogRetentionMonths"] == 12
    r2 = client.get("/dashboard/api/settings/data-retention",
                    headers=_auth(token))
    assert r2.json()["endOfRetentionAction"] == "delete"
    assert r2.json()["keepApprovedLearnings"] is False


def test_put_accepts_null_for_inbox_and_archive():
    """Brief 229: null is the 'never archive / never delete' value for
    activeInboxArchiveAfterDays and archiveRetentionMonths."""
    _reset()
    token = _login()
    payload = {
        "activeInboxArchiveAfterDays": None,
        "archiveRetentionMonths": None,
        "endOfRetentionAction": "keep",
        "keepApprovedLearnings": True,
        "auditLogRetentionMonths": 60,
    }
    r = client.put("/dashboard/api/settings/data-retention",
                   json=payload, headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["activeInboxArchiveAfterDays"] is None
    assert body["archiveRetentionMonths"] is None
    assert body["endOfRetentionAction"] == "keep"


def test_put_422_on_invalid_inbox_value():
    """Brief 229: only {30, 60, 90, 180, null} accepted for
    activeInboxArchiveAfterDays."""
    _reset()
    token = _login()
    r = client.put(
        "/dashboard/api/settings/data-retention",
        json={
            "activeInboxArchiveAfterDays": 45,
            "archiveRetentionMonths": 24,
            "endOfRetentionAction": "anonymize",
            "keepApprovedLearnings": True,
            "auditLogRetentionMonths": 24,
        }, headers=_auth(token))
    assert r.status_code == 422


def test_put_422_on_invalid_action():
    """Brief 229: endOfRetentionAction enum validated."""
    _reset()
    token = _login()
    r = client.put(
        "/dashboard/api/settings/data-retention",
        json={
            "activeInboxArchiveAfterDays": 90,
            "archiveRetentionMonths": 24,
            "endOfRetentionAction": "purge",
            "keepApprovedLearnings": True,
            "auditLogRetentionMonths": 24,
        }, headers=_auth(token))
    assert r.status_code == 422


def test_put_422_on_invalid_audit_value():
    """Brief 229: auditLogRetentionMonths must be in {12, 24, 36, 60}."""
    _reset()
    token = _login()
    r = client.put(
        "/dashboard/api/settings/data-retention",
        json={
            "activeInboxArchiveAfterDays": 90,
            "archiveRetentionMonths": 24,
            "endOfRetentionAction": "anonymize",
            "keepApprovedLearnings": True,
            "auditLogRetentionMonths": 6,
        }, headers=_auth(token))
    assert r.status_code == 422


def test_action_endpoints_return_501():
    """Brief 229: cleanup actions are unimplemented; honest 501 per SR's
    'No fake success' rule."""
    token = _login()
    for path in ("/dashboard/api/data-retention/archive-now",
                 "/dashboard/api/data-retention/export",
                 "/dashboard/api/data-retention/delete-customer-data"):
        r = client.post(path, headers=_auth(token))
        assert r.status_code == 501, f"{path} -> {r.status_code}"
        assert "not implemented" in r.json()["detail"].lower()
