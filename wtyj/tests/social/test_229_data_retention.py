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
    assert body["status"]["policyActive"] is False
    assert body["status"]["manualActionsAvailable"] is True
    assert body["status"]["nextCleanupAt"] is None


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




# ── Brief 237: action endpoints (replace 501 stubs) ─────────────────────


import json as _json
from datetime import datetime, timezone, timedelta


def _wipe_237():
    """Reset state for Brief 237 tests — drop everything the action
    endpoints touch."""
    conn = state_registry._get_conn()
    for table in ("data_retention_settings", "data_retention_audit_log",
                  "customers", "customer_identifiers", "customer_interactions",
                  "whatsapp_threads", "pending_notifications", "appointments",
                  "conversation_status"):
        try:
            conn.execute(f"DELETE FROM {table}")
        except Exception:
            pass
    try:
        conn.execute("DELETE FROM escalation_learnings")
    except Exception:
        pass
    conn.commit()
    conn.close()


def _set_settings(token, **overrides):
    payload = {
        "activeInboxArchiveAfterDays": 90,
        "archiveRetentionMonths": 24,
        "endOfRetentionAction": "anonymize",
        "keepApprovedLearnings": True,
        "auditLogRetentionMonths": 24,
    }
    payload.update(overrides)
    r = client.put("/dashboard/api/settings/data-retention",
                   json=payload, headers=_auth(token))
    assert r.status_code == 200


def _seed_email_thread(thread_key, last_activity_dt, **flags):
    """Write an email thread directly into the JSON state file the
    helper reads. Returns the path so a test can clean up."""
    p = state_registry._get_email_state_path()
    if os.path.exists(p):
        with open(p) as f:
            state = _json.load(f)
    else:
        state = {"threads": {}, "sender_rates": {}}
    state.setdefault("threads", {})[thread_key] = {
        "fields": {"customer_name": "Test"},
        "flags": dict(flags),
        "last_activity": last_activity_dt.isoformat(),
        "messages": [],
        "from_email": "test@example.com",
    }
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        _json.dump(state, f)
    os.replace(tmp, p)
    return p


def _clear_email_state():
    p = state_registry._get_email_state_path()
    if os.path.exists(p):
        os.remove(p)


def test_archive_now_with_null_setting_returns_400():
    """Brief 237: PUT settings with null archive-after, then archive-now
    refuses with a 400 + clear message instead of doing nothing silently."""
    _wipe_237()
    token = _login()
    _set_settings(token, activeInboxArchiveAfterDays=None)
    r = client.post("/dashboard/api/data-retention/archive-now",
                    headers=_auth(token))
    assert r.status_code == 400
    assert "null" in r.json()["detail"].lower() or "disabled" in r.json()["detail"].lower()


def test_archive_now_archives_old_email_thread_and_skips_recent():
    """Brief 237: archive-now sets flags.deleted on threads inactive
    longer than the configured day count; recent threads stay."""
    _wipe_237()
    _clear_email_state()
    token = _login()
    _set_settings(token, activeInboxArchiveAfterDays=90)

    now = datetime.now(timezone.utc)
    _seed_email_thread("subj:old@x.com:hi",
                       now - timedelta(days=120))
    _seed_email_thread("subj:fresh@x.com:hi",
                       now - timedelta(days=5))

    r = client.post("/dashboard/api/data-retention/archive-now",
                    headers=_auth(token))
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["ok"] is True
    assert body["archivedCount"] >= 1

    p = state_registry._get_email_state_path()
    with open(p) as f:
        state = _json.load(f)
    assert state["threads"]["subj:old@x.com:hi"]["flags"].get("deleted") is True
    assert not state["threads"]["subj:fresh@x.com:hi"]["flags"].get("deleted")
    _clear_email_state()


def test_archive_now_skips_thread_with_active_escalation():
    """Brief 237: a 100-day-old thread with flags.fully_escalated=true
    must NOT be archived (Rule 8 — never archive active escalations)."""
    _wipe_237()
    _clear_email_state()
    token = _login()
    _set_settings(token, activeInboxArchiveAfterDays=90)

    now = datetime.now(timezone.utc)
    _seed_email_thread("subj:esc@x.com:hi",
                       now - timedelta(days=120),
                       fully_escalated=True)

    r = client.post("/dashboard/api/data-retention/archive-now",
                    headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["skippedActiveEscalation"] >= 1

    p = state_registry._get_email_state_path()
    with open(p) as f:
        state = _json.load(f)
    assert state["threads"]["subj:esc@x.com:hi"]["flags"].get("deleted") is not True
    _clear_email_state()


def test_export_writes_file_and_returns_path(tmp_path, monkeypatch):
    """Brief 237: POST /export writes a JSON file to disk and returns
    its path + record counts."""
    _wipe_237()
    token = _login()
    r = client.post("/dashboard/api/data-retention/export",
                    json={"tenant": "test237"},
                    headers=_auth(token))
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["ok"] is True
    assert "exportPath" in body
    assert os.path.exists(body["exportPath"])
    with open(body["exportPath"]) as f:
        payload = _json.load(f)
    assert payload["tenant"] == "test237"
    assert "customers" in payload
    assert "email_threads" in payload
    assert "recordCounts" in body
    os.remove(body["exportPath"])


def test_delete_customer_anonymize_preserves_row_ids():
    """Brief 237: anonymize REPLACES PII fields but keeps row count
    unchanged. display_name='[redacted]', wa text='[redacted message]'."""
    _wipe_237()
    token = _login()
    _set_settings(token, endOfRetentionAction="anonymize")

    conn = state_registry._get_conn()
    now_iso = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO customers (display_name, first_seen, last_seen) VALUES (?, ?, ?)",
        ("Alice", now_iso, now_iso))
    cust_id = cur.lastrowid
    conn.execute(
        "INSERT INTO customer_identifiers (customer_id, type, value, first_seen) "
        "VALUES (?, ?, ?, ?)",
        (cust_id, "phone", "+15551111111", datetime.now(timezone.utc).isoformat()))
    for txt in ("hi", "any time today?", "thanks"):
        conn.execute(
            "INSERT INTO whatsapp_threads (phone, role, text, created_at, channel, sender_name) "
            "VALUES (?, 'user', ?, ?, 'whatsapp', 'Alice')",
            ("+15551111111", txt, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()

    r = client.post("/dashboard/api/data-retention/delete-customer-data",
                    json={"identifierValue": "+15551111111", "identifierType": "phone"},
                    headers=_auth(token))
    assert r.status_code == 200, r.json()

    conn = state_registry._get_conn()
    cust_count = conn.execute("SELECT COUNT(*) FROM customers WHERE id = ?", (cust_id,)).fetchone()[0]
    msg_count = conn.execute("SELECT COUNT(*) FROM whatsapp_threads WHERE phone = ?", ("+15551111111",)).fetchone()[0]
    name = conn.execute("SELECT display_name FROM customers WHERE id = ?", (cust_id,)).fetchone()[0]
    text_val = conn.execute("SELECT text FROM whatsapp_threads WHERE phone = ? LIMIT 1",
                            ("+15551111111",)).fetchone()[0]
    conn.close()
    assert cust_count == 1
    assert msg_count == 3
    assert name == "[redacted]"
    assert text_val == "[redacted message]"


def test_delete_customer_delete_drops_rows():
    """Brief 237: action=delete actually removes customer + identifier +
    message rows (count=0 after)."""
    _wipe_237()
    token = _login()
    _set_settings(token, endOfRetentionAction="delete")

    conn = state_registry._get_conn()
    now_iso = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO customers (display_name, first_seen, last_seen) VALUES (?, ?, ?)",
        ("Bob", now_iso, now_iso))
    cust_id = cur.lastrowid
    conn.execute(
        "INSERT INTO customer_identifiers (customer_id, type, value, first_seen) "
        "VALUES (?, 'phone', ?, ?)",
        (cust_id, "+15552222222", datetime.now(timezone.utc).isoformat()))
    conn.execute(
        "INSERT INTO whatsapp_threads (phone, role, text, created_at, channel) "
        "VALUES (?, 'user', 'msg', ?, 'whatsapp')",
        ("+15552222222", datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()

    r = client.post("/dashboard/api/data-retention/delete-customer-data",
                    json={"identifierValue": "+15552222222", "identifierType": "phone"},
                    headers=_auth(token))
    assert r.status_code == 200

    conn = state_registry._get_conn()
    assert conn.execute("SELECT COUNT(*) FROM customers WHERE id = ?", (cust_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM whatsapp_threads WHERE phone = ?", ("+15552222222",)).fetchone()[0] == 0
    conn.close()


def test_delete_customer_blocked_by_active_escalation():
    """Brief 237: active pending_notification (status='sent', text-bound
    customer_id) blocks deletion. Returns 409, no PII touched, audit row
    still written for the blocked attempt (Rule 10)."""
    _wipe_237()
    token = _login()
    _set_settings(token, endOfRetentionAction="delete")

    conn = state_registry._get_conn()
    now_iso = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO customers (display_name, first_seen, last_seen) VALUES (?, ?, ?)",
        ("Carol", now_iso, now_iso))
    cust_id = cur.lastrowid
    conn.execute(
        "INSERT INTO customer_identifiers (customer_id, type, value, first_seen) "
        "VALUES (?, 'phone', ?, ?)",
        (cust_id, "+15553333333", datetime.now(timezone.utc).isoformat()))
    # NOTE: customer_id here is the TEXT phone value, not the integer PK,
    # matching Brief 235's production data shape.
    conn.execute(
        "INSERT INTO pending_notifications (notification_type, channel, "
        "customer_id, customer_name, subject, body, status, created_at) "
        "VALUES ('escalation', 'whatsapp', ?, 'Carol', 'subj', 'body', 'sent', ?)",
        ("+15553333333", datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()

    r = client.post("/dashboard/api/data-retention/delete-customer-data",
                    json={"identifierValue": "+15553333333", "identifierType": "phone"},
                    headers=_auth(token))
    assert r.status_code == 409
    assert "active_escalation" in r.json()["detail"]

    conn = state_registry._get_conn()
    # PII untouched
    assert conn.execute("SELECT display_name FROM customers WHERE id = ?",
                        (cust_id,)).fetchone()[0] == "Carol"
    # Audit row written for the blocked attempt
    audit_row = conn.execute(
        "SELECT action FROM data_retention_audit_log "
        "WHERE action LIKE 'delete_customer:blocked_by_%' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert audit_row is not None
    assert "blocked_by_" in audit_row[0]


def test_delete_customer_keep_learnings_skips_escalation_learnings():
    """Brief 237: with keepApprovedLearnings=true, escalation_learnings
    rows tied to the customer survive the delete sweep."""
    _wipe_237()
    token = _login()
    _set_settings(token, endOfRetentionAction="delete", keepApprovedLearnings=True)

    conn = state_registry._get_conn()
    now_iso = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO customers (display_name, first_seen, last_seen) VALUES (?, ?, ?)",
        ("Dan", now_iso, now_iso))
    cust_id = cur.lastrowid
    conn.execute(
        "INSERT INTO customer_identifiers (customer_id, type, value, first_seen) "
        "VALUES (?, 'phone', ?, ?)",
        (cust_id, "+15554444444", datetime.now(timezone.utc).isoformat()))
    # escalation_learnings keys on conversation_id (TEXT), not customer_id.
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO escalation_learnings "
        "(conversation_id, channel, source_question, human_answer, "
        "status, ai_may_use_automatically, created_at, updated_at) "
        "VALUES (?, 'whatsapp', 'Q', 'A', 'approved', 1, ?, ?)",
        ("+15554444444", now, now))
    conn.commit()
    learning_count_before = conn.execute(
        "SELECT COUNT(*) FROM escalation_learnings WHERE conversation_id = ?",
        ("+15554444444",)).fetchone()[0]
    conn.close()

    r = client.post("/dashboard/api/data-retention/delete-customer-data",
                    json={"identifierValue": "+15554444444", "identifierType": "phone"},
                    headers=_auth(token))
    assert r.status_code == 200

    conn = state_registry._get_conn()
    learning_count_after = conn.execute(
        "SELECT COUNT(*) FROM escalation_learnings WHERE conversation_id = ?",
        ("+15554444444",)).fetchone()[0]
    conn.close()
    # Learnings row survived (count unchanged)
    assert learning_count_after == learning_count_before


def test_audit_log_row_written_on_archive_now():
    """Brief 237: every archive-now call records an audit row with
    action='archive_now' and a non-empty affected_counts_json."""
    _wipe_237()
    token = _login()
    _set_settings(token, activeInboxArchiveAfterDays=90)

    r = client.post("/dashboard/api/data-retention/archive-now",
                    headers=_auth(token))
    assert r.status_code == 200

    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT action, affected_counts_json FROM data_retention_audit_log "
        "WHERE action = 'archive_now' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "archive_now"
    counts = _json.loads(row[1])
    assert "archivedCount" in counts
