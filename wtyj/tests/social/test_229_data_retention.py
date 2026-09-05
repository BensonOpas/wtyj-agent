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
                  "conversation_status", "operator_delivery_outbox"):
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


def _seed_operator_delivery_outbox(
    conversation_id: str,
    *,
    action_key: str,
    status: str = "confirmed",
    claim_token: str = "",
    lease_until: float = 0,
):
    from dashboard import operator_delivery

    conn = operator_delivery._connect()
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO operator_delivery_outbox "
        "(tenant_id,action_key,conversation_id,scope,request_hash,anchor,"
        "payload_json,result_json,status,claim_token,lease_until,last_error,"
        "created_at,updated_at) VALUES "
        "('mermaid',?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            action_key,
            conversation_id,
            f"email-inbox:subj:{conversation_id}:private:reply",
            "guessable-private-request-hash",
            "private-customer-anchor",
            _json.dumps({
                "to": conversation_id,
                "text": "Very private operator answer",
                "thread_key": f"subj:{conversation_id}:private",
            }),
            _json.dumps({"reply": "Very private operator answer"}),
            status,
            claim_token,
            lease_until,
            "PrivateProviderError",
            now_iso,
            now_iso,
        ),
    )
    conn.commit()
    conn.close()


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


def test_export_includes_durable_operator_delivery_outbox(tmp_path):
    _wipe_237()
    customer = "export-outbox@example.com"
    _seed_operator_delivery_outbox(customer, action_key="export-outbox")

    exported = state_registry.export_all_customer_data(str(tmp_path), "mermaid")
    payload = _json.loads(open(exported["exportPath"], encoding="utf-8").read())

    rows = payload["operator_delivery_outbox"]
    assert len(rows) == 1
    assert rows[0]["conversation_id"] == customer
    assert "Very private operator answer" in rows[0]["payload_json"]
    assert exported["recordCounts"]["operator_delivery_outbox"] == 1


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
    msg_count = conn.execute("SELECT COUNT(*) FROM whatsapp_threads").fetchone()[0]
    original_phone_count = conn.execute(
        "SELECT COUNT(*) FROM whatsapp_threads WHERE phone = ?", ("+15551111111",)
    ).fetchone()[0]
    name = conn.execute("SELECT display_name FROM customers WHERE id = ?", (cust_id,)).fetchone()[0]
    text_val = conn.execute(
        "SELECT text FROM whatsapp_threads WHERE phone LIKE '[redacted]:thread:%' LIMIT 1"
    ).fetchone()[0]
    conn.close()
    assert cust_count == 1
    assert msg_count == 3
    assert original_phone_count == 0
    assert name == "[redacted]"
    assert text_val == "[redacted message]"


def test_anonymize_customer_scrubs_escalation_summary_and_email_identity():
    _wipe_237()
    email = "private-notification@example.com"
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = state_registry._get_conn()
    customer_id = conn.execute(
        "INSERT INTO customers (display_name,first_seen,last_seen) VALUES (?,?,?)",
        ("Private Notification Guest", now_iso, now_iso),
    ).lastrowid
    conn.execute(
        "INSERT INTO customer_identifiers (customer_id,type,value,first_seen) "
        "VALUES (?,'email',?,?)",
        (customer_id, email, now_iso),
    )
    notification_id = conn.execute(
        "INSERT INTO pending_notifications "
        "(notification_type,channel,customer_id,customer_name,subject,body,"
        "status,created_at,escalation_summary,email_thread_key,email_reply_subject) "
        "VALUES ('escalation','email',?,?,?,?,'replied',?,?,?,?)",
        (
            email,
            "Private Notification Guest",
            "Private subject",
            "Private body",
            now_iso,
            _json.dumps({"latestCustomerMessage": "Private medical detail"}),
            f"subj:{email}:private-subject",
            "Re: Private subject",
        ),
    ).lastrowid
    conn.commit()
    conn.close()

    result = state_registry.delete_customer_data(
        email, "email", "anonymize", keep_approved_learnings=True
    )

    assert result["ok"] is True
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT customer_id,customer_name,subject,body,escalation_summary,"
        "email_thread_key,email_reply_subject FROM pending_notifications WHERE id=?",
        (notification_id,),
    ).fetchone()
    conn.close()
    assert row == (
        f"[redacted]:notification:{notification_id}",
        "[redacted]",
        "[redacted]",
        "[redacted]",
        None,
        "",
        "",
    )


def test_anonymize_customer_scrubs_durable_operator_delivery_outbox(
    tmp_path, monkeypatch,
):
    _wipe_237()
    email = "private-outbox@example.com"
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = state_registry._get_conn()
    customer_id = conn.execute(
        "INSERT INTO customers (display_name,first_seen,last_seen) VALUES (?,?,?)",
        ("Private Outbox Guest", now_iso, now_iso),
    ).lastrowid
    conn.execute(
        "INSERT INTO customer_identifiers (customer_id,type,value,first_seen) "
        "VALUES (?,'email',?,?)",
        (customer_id, email, now_iso),
    )
    conn.commit()
    conn.close()
    _seed_operator_delivery_outbox(email, action_key="private-action")
    monkeypatch.setattr(
        state_registry, "_get_email_state_path",
        lambda: str(tmp_path / "email_thread_state.json"),
    )

    result = state_registry.delete_customer_data(
        email, "email", "anonymize", keep_approved_learnings=True
    )

    assert result["ok"] is True
    conn = state_registry._get_conn()
    row = conn.execute("SELECT * FROM operator_delivery_outbox").fetchone()
    columns = [item[1] for item in conn.execute(
        "PRAGMA table_info(operator_delivery_outbox)"
    ).fetchall()]
    conn.close()
    stored = dict(zip(columns, row))
    serialized = _json.dumps(stored).casefold()
    for private_value in (
        email,
        "very private operator answer",
        "private-customer-anchor",
        "privateprovidererror",
        "guessable-private-request-hash",
        "private-action",
    ):
        assert private_value.casefold() not in serialized
    assert stored["conversation_id"].startswith("[redacted]:delivery:")
    assert stored["scope"] == "[redacted]"
    assert stored["payload_json"] == "{}"
    assert stored["result_json"] == "{}"
    assert stored["status"] == "confirmed"
    assert stored["claim_token"] == ""
    assert stored["lease_until"] == 0


def test_delete_customer_removes_inactive_operator_delivery_outbox():
    _wipe_237()
    phone = "+59995550101"
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = state_registry._get_conn()
    customer_id = conn.execute(
        "INSERT INTO customers (display_name,first_seen,last_seen) VALUES (?,?,?)",
        ("Delete Outbox Guest", now_iso, now_iso),
    ).lastrowid
    conn.execute(
        "INSERT INTO customer_identifiers (customer_id,type,value,first_seen) "
        "VALUES (?,'phone',?,?)",
        (customer_id, phone, now_iso),
    )
    conn.commit()
    conn.close()
    _seed_operator_delivery_outbox(
        phone,
        action_key="released-prepared-action",
        status="prepared",
        claim_token="",
    )

    result = state_registry.delete_customer_data(
        phone, "phone", "delete", keep_approved_learnings=True
    )

    assert result["ok"] is True
    conn = state_registry._get_conn()
    assert conn.execute(
        "SELECT COUNT(*) FROM operator_delivery_outbox"
    ).fetchone()[0] == 0
    conn.close()


def test_privacy_request_waits_for_live_operator_delivery():
    _wipe_237()
    phone = "+59995550102"
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = state_registry._get_conn()
    customer_id = conn.execute(
        "INSERT INTO customers (display_name,first_seen,last_seen) VALUES (?,?,?)",
        ("Active Delivery Guest", now_iso, now_iso),
    ).lastrowid
    conn.execute(
        "INSERT INTO customer_identifiers (customer_id,type,value,first_seen) "
        "VALUES (?,'phone',?,?)",
        (customer_id, phone, now_iso),
    )
    conn.commit()
    conn.close()
    _seed_operator_delivery_outbox(
        phone,
        action_key="live-action",
        status="prepared",
        claim_token="live-worker",
        lease_until=datetime.now(timezone.utc).timestamp() + 600,
    )

    result = state_registry.delete_customer_data(
        phone, "phone", "delete", keep_approved_learnings=True
    )

    assert result == {"ok": False, "reason": "active_delivery"}
    conn = state_registry._get_conn()
    assert conn.execute(
        "SELECT value FROM customer_identifiers WHERE customer_id=?", (customer_id,)
    ).fetchone()[0] == phone
    assert conn.execute(
        "SELECT conversation_id FROM operator_delivery_outbox"
    ).fetchone()[0] == phone
    conn.close()


def test_delete_customer_by_email_resolves_linked_phone_identity():
    _wipe_237()
    token = _login()
    _set_settings(token, endOfRetentionAction="anonymize")

    email = "linked@example.com"
    phone = "+15554445555"
    conn = state_registry._get_conn()
    now_iso = datetime.now(timezone.utc).isoformat()
    customer_id = conn.execute(
        "INSERT INTO customers (display_name,first_seen,last_seen) VALUES (?,?,?)",
        ("Linked Guest", now_iso, now_iso),
    ).lastrowid
    conn.executemany(
        "INSERT INTO customer_identifiers (customer_id,type,value,first_seen) "
        "VALUES (?,?,?,?)",
        [
            (customer_id, "email", email, now_iso),
            (customer_id, "phone", phone, now_iso),
        ],
    )
    conn.execute(
        "INSERT INTO whatsapp_threads "
        "(phone,role,text,created_at,channel,sender_name) "
        "VALUES (?,'user','private message',?,'whatsapp','Linked Guest')",
        (phone, now_iso),
    )
    conn.commit()
    conn.close()

    response = client.post(
        "/dashboard/api/data-retention/delete-customer-data",
        json={"identifierValue": email, "identifierType": "email"},
        headers=_auth(token),
    )

    assert response.status_code == 200, response.json()
    conn = state_registry._get_conn()
    try:
        assert conn.execute(
            "SELECT display_name FROM customers WHERE id=?", (customer_id,)
        ).fetchone()[0] == "[redacted]"
        assert conn.execute(
            "SELECT COUNT(*) FROM customer_identifiers "
            "WHERE customer_id=? AND value IN (?,?)",
            (customer_id, email, phone),
        ).fetchone()[0] == 0
        row = conn.execute(
            "SELECT phone,text,sender_name FROM whatsapp_threads"
        ).fetchone()
        assert row[0].startswith("[redacted]:thread:")
        assert row[1:] == ("[redacted message]", "[redacted]")
    finally:
        conn.close()


def test_anonymize_customer_scrubs_complete_email_sidecar(tmp_path, monkeypatch):
    _wipe_237()
    token = _login()
    _set_settings(token, endOfRetentionAction="anonymize")

    email = "private@example.com"
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = state_registry._get_conn()
    customer_id = conn.execute(
        "INSERT INTO customers (display_name,first_seen,last_seen) VALUES (?,?,?)",
        ("Secret Guest", now_iso, now_iso),
    ).lastrowid
    conn.execute(
        "INSERT INTO customer_identifiers (customer_id,type,value,first_seen) "
        "VALUES (?,'email',?,?)",
        (customer_id, email, now_iso),
    )
    conn.commit()
    conn.close()

    email_path = tmp_path / "email_thread_state.json"
    email_path.write_text(
        _json.dumps(
            {
                "threads": {
                    f"subj:{email}:Secret Excursion": {
                        "from_email": email,
                        "subject": "Secret Excursion",
                        "fields": {
                            "customer_name": "Secret Guest",
                            "phone": "+59991234567",
                        },
                        "flags": {"private_marker": "Secret Flag"},
                        "completed_bookings": [
                            {"customer_name": "Secret Guest", "trip": "Hidden"}
                        ],
                        "last_activity": now_iso,
                        "messages": [
                            {
                                "role": "customer",
                                "ts": now_iso,
                                "text": "Secret text",
                                "body": "Secret body",
                                "from_email": email,
                                "subject": "Secret subject",
                                "attachment_name": "Secret passport.pdf",
                            }
                        ],
                        "private_top_level": "Secret trace",
                    }
                },
                "sender_rates": {email: {"count": 4}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        state_registry, "_get_email_state_path", lambda: str(email_path)
    )

    response = client.post(
        "/dashboard/api/data-retention/delete-customer-data",
        json={"identifierValue": email, "identifierType": "email"},
        headers=_auth(token),
    )

    assert response.status_code == 200, response.json()
    email_state = _json.loads(email_path.read_text(encoding="utf-8"))
    serialized = _json.dumps(email_state).casefold()
    for private_value in (
        email,
        "secret guest",
        "secret excursion",
        "secret text",
        "secret body",
        "secret subject",
        "secret passport.pdf",
        "secret trace",
        "+59991234567",
    ):
        assert private_value.casefold() not in serialized
    assert email_state["sender_rates"] == {}
    assert len(email_state["threads"]) == 1
    redacted_key, redacted_thread = next(iter(email_state["threads"].items()))
    assert redacted_key.startswith("[redacted]:email-thread:")
    assert redacted_thread["fields"] == {}
    assert redacted_thread["flags"] == {}
    assert redacted_thread["completed_bookings"] == []
    assert redacted_thread["messages"][0] == {
        "role": "customer",
        "ts": now_iso,
        "text": "[redacted]",
        "body": "[redacted]",
        "from_email": "[redacted]",
        "subject": "[redacted]",
    }


def test_email_retention_matches_exact_address_without_substring_collateral(
    tmp_path, monkeypatch,
):
    _wipe_237()
    email = "ann@example.com"
    collateral = "joann@example.com"
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = state_registry._get_conn()
    customer_id = conn.execute(
        "INSERT INTO customers (display_name,first_seen,last_seen) VALUES (?,?,?)",
        ("Ann", now_iso, now_iso),
    ).lastrowid
    conn.execute(
        "INSERT INTO customer_identifiers (customer_id,type,value,first_seen) "
        "VALUES (?,'email',?,?)",
        (customer_id, email, now_iso),
    )
    conn.commit()
    conn.close()
    path = tmp_path / "email_thread_state.json"
    path.write_text(_json.dumps({
        "threads": {
            f"subj:{email}:private": {
                "from_email": email,
                "messages": [{"role": "customer", "body": "Ann private"}],
            },
            f"subj:{collateral}:keep": {
                "from_email": collateral,
                "messages": [{"role": "customer", "body": "Joann must remain"}],
            },
        }
    }))
    monkeypatch.setattr(state_registry, "_get_email_state_path", lambda: str(path))

    result = state_registry.delete_customer_data(
        email, "email", "delete", keep_approved_learnings=True
    )
    assert result["ok"] is True
    threads = _json.loads(path.read_text())["threads"]
    assert f"subj:{email}:private" not in threads
    assert threads[f"subj:{collateral}:keep"]["messages"][0]["body"] == "Joann must remain"


def test_legacy_raw_email_archive_migrates_into_governed_export(
    tmp_path, monkeypatch,
):
    _wipe_237()
    email = "legacy@example.com"
    thread_key = f"subj:{email}:old"
    state_path = tmp_path / "email_thread_state.json"
    state_path.write_text(_json.dumps({"threads": {}, "message_id_index": {}}))
    legacy_path = tmp_path / "archived_threads.jsonl"
    legacy_path.write_text(_json.dumps({
        "archived_at": 1,
        "thread_key": thread_key,
        "data": {
            "fields": {"customer_name": "Legacy Guest"},
            "flags": {},
            "messages": [{"role": "customer", "body": "Old question"}],
        },
    }) + "\n")
    monkeypatch.setattr(
        state_registry, "_get_email_state_path", lambda: str(state_path)
    )

    exported = state_registry.export_all_customer_data(str(tmp_path), "mermaid")
    payload = _json.loads(
        open(exported["exportPath"], encoding="utf-8").read()
    )
    assert legacy_path.exists() is False
    migrated = payload["email_threads"]["threads"][thread_key]
    assert migrated["flags"]["deleted"] is True
    assert migrated["messages"][0]["body"] == "Old question"


def test_legacy_only_raw_email_archive_migrates_into_governed_export(
    tmp_path, monkeypatch,
):
    _wipe_237()
    email = "legacy-only@example.com"
    thread_key = f"subj:{email}:old"
    state_path = tmp_path / "email_thread_state.json"
    legacy_path = tmp_path / "archived_threads.jsonl"
    legacy_path.write_text(_json.dumps({
        "archived_at": 1,
        "thread_key": thread_key,
        "data": {
            "fields": {"customer_name": "Legacy Only Guest"},
            "flags": {},
            "messages": [{"role": "customer", "body": "Only raw copy"}],
        },
    }) + "\n")
    monkeypatch.setattr(
        state_registry, "_get_email_state_path", lambda: str(state_path)
    )

    exported = state_registry.export_all_customer_data(str(tmp_path), "mermaid")
    payload = _json.loads(
        open(exported["exportPath"], encoding="utf-8").read()
    )
    assert state_path.exists() is True
    assert legacy_path.exists() is False
    migrated = payload["email_threads"]["threads"][thread_key]
    assert migrated["flags"]["deleted"] is True
    assert migrated["messages"][0]["body"] == "Only raw copy"


def test_legacy_archive_merge_preserves_history_without_rehiding_live_thread(
    tmp_path, monkeypatch,
):
    _wipe_237()
    email = "returned@example.com"
    thread_key = f"subj:{email}:same-subject"
    state_path = tmp_path / "email_thread_state.json"
    state_path.write_text(_json.dumps({
        "threads": {
            thread_key: {
                "fields": {"phone": "+59990000000"},
                "flags": {"awaiting_details": True},
                "messages": [{"role": "customer", "body": "New question"}],
                "completed_bookings": [{"booking_ref": "NEW-2"}],
                "last_activity": 2,
            },
        },
        "message_id_index": {},
    }))
    legacy_path = tmp_path / "archived_threads.jsonl"
    legacy_path.write_text(_json.dumps({
        "archived_at": 1,
        "thread_key": thread_key,
        "data": {
            "fields": {"customer_name": "Returning Guest", "date": "old-date"},
            "flags": {"hold_created": True},
            "messages": [{"role": "customer", "body": "Old question"}],
            "completed_bookings": [{"booking_ref": "OLD-1"}],
            "last_activity": 1,
        },
    }) + "\n")
    monkeypatch.setattr(
        state_registry, "_get_email_state_path", lambda: str(state_path)
    )

    state = state_registry.email_state_read(str(state_path), {})
    merged = state["threads"][thread_key]

    assert legacy_path.exists() is False
    assert merged["flags"] == {"hold_created": True, "awaiting_details": True}
    assert merged["fields"] == {
        "customer_name": "Returning Guest",
        "date": "old-date",
        "phone": "+59990000000",
    }
    assert [message["body"] for message in merged["messages"]] == [
        "Old question", "New question",
    ]
    assert [item["booking_ref"] for item in merged["completed_bookings"]] == [
        "OLD-1", "NEW-2",
    ]
    assert merged["last_activity"] == 2


def test_delete_customer_data_removes_legacy_only_raw_email_archive(
    tmp_path, monkeypatch,
):
    _wipe_237()
    email = "legacy-delete@example.com"
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = state_registry._get_conn()
    customer_id = conn.execute(
        "INSERT INTO customers (display_name,first_seen,last_seen) VALUES (?,?,?)",
        ("Legacy Delete Guest", now_iso, now_iso),
    ).lastrowid
    conn.execute(
        "INSERT INTO customer_identifiers (customer_id,type,value,first_seen) "
        "VALUES (?,'email',?,?)",
        (customer_id, email, now_iso),
    )
    conn.commit()
    conn.close()

    thread_key = f"subj:{email}:private"
    state_path = tmp_path / "email_thread_state.json"
    legacy_path = tmp_path / "archived_threads.jsonl"
    legacy_path.write_text(_json.dumps({
        "archived_at": 1,
        "thread_key": thread_key,
        "data": {
            "fields": {"customer_name": "Legacy Delete Guest"},
            "flags": {},
            "messages": [{"role": "customer", "body": "Delete me"}],
        },
    }) + "\n")
    monkeypatch.setattr(
        state_registry, "_get_email_state_path", lambda: str(state_path)
    )

    result = state_registry.delete_customer_data(
        email, "email", "delete", keep_approved_learnings=True
    )

    assert result["ok"] is True
    assert legacy_path.exists() is False
    assert _json.loads(state_path.read_text())["threads"] == {}
    conn = state_registry._get_conn()
    assert conn.execute(
        "SELECT 1 FROM customer_identifiers WHERE value=?", (email,)
    ).fetchone() is None
    conn.close()


def test_email_sidecar_write_failure_rolls_back_customer_anonymization(
    tmp_path, monkeypatch
):
    _wipe_237()
    email = "retry@example.com"
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = state_registry._get_conn()
    customer_id = conn.execute(
        "INSERT INTO customers (display_name,first_seen,last_seen) VALUES (?,?,?)",
        ("Retry Guest", now_iso, now_iso),
    ).lastrowid
    conn.execute(
        "INSERT INTO customer_identifiers (customer_id,type,value,first_seen) "
        "VALUES (?,'email',?,?)",
        (customer_id, email, now_iso),
    )
    conn.commit()
    conn.close()

    email_path = tmp_path / "email_thread_state.json"
    original_state = {
        "threads": {
            f"subj:{email}:retry": {
                "from_email": email,
                "messages": [{"role": "customer", "body": "Keep until retry"}],
            }
        },
        "sender_rates": {email: {"count": 1}},
    }
    email_path.write_text(_json.dumps(original_state), encoding="utf-8")
    monkeypatch.setattr(
        state_registry, "_get_email_state_path", lambda: str(email_path)
    )

    def fail_replace(_source, _destination):
        raise OSError("read-only sidecar")

    monkeypatch.setattr(state_registry.os, "replace", fail_replace)
    result = state_registry.delete_customer_data(
        email, "email", "anonymize", keep_approved_learnings=True
    )

    assert result["ok"] is False
    assert result["reason"] == "email_state_write_failed"
    conn = state_registry._get_conn()
    try:
        assert conn.execute(
            "SELECT display_name FROM customers WHERE id=?", (customer_id,)
        ).fetchone()[0] == "Retry Guest"
        assert conn.execute(
            "SELECT value FROM customer_identifiers WHERE customer_id=?",
            (customer_id,),
        ).fetchone()[0] == email
    finally:
        conn.close()
    assert _json.loads(email_path.read_text(encoding="utf-8")) == original_state


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
