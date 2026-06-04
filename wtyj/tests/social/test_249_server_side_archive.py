"""Brief 249: per-conversation manual archive/unarchive endpoints
+ archived-conversations listing + WhatsApp listing filter regression
+ resolved escalations history filter."""
import json
import os
import sys
import urllib.parse
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from fastapi.testclient import TestClient
from agents.social.webhook_server import app

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _wipe_wa_phone(phone: str):
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?",
                 (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?",
                 (phone,))
    conn.commit()
    conn.close()


def test_archive_whatsapp_excludes_from_active_list_and_includes_in_archived():
    """Brief 249: POST /archive on a WhatsApp conv removes it from
    /messages/conversations and adds it to /messages/conversations/archived."""
    from shared import state_registry
    phone = "249_wa_archive_test_phone"
    _wipe_wa_phone(phone)
    state_registry.wa_store_message(phone, "user", "[QA] hello")

    token = _login()
    r = client.get("/dashboard/api/messages/conversations", headers=_auth(token))
    assert r.status_code == 200
    assert any(c["phone"] == phone for c in r.json()), \
        "expected phone in active list before archive"

    r = client.post(f"/dashboard/api/messages/conversations/{phone}/archive",
                     headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["archived"] is True
    assert body["channel"] == "whatsapp"

    r = client.get("/dashboard/api/messages/conversations", headers=_auth(token))
    assert not any(c["phone"] == phone for c in r.json()), \
        "phone must be excluded from active list after archive"

    r = client.get("/dashboard/api/messages/conversations/archived",
                    headers=_auth(token))
    assert r.status_code == 200
    assert any(c["phone"] == phone for c in r.json()), \
        "phone must appear in archived list"

    _wipe_wa_phone(phone)


def test_unarchive_whatsapp_restores_to_active_list():
    """Brief 249: POST /unarchive flips it back to active."""
    from shared import state_registry
    phone = "249_wa_unarchive_test_phone"
    _wipe_wa_phone(phone)
    state_registry.wa_store_message(phone, "user", "[QA] hello")
    state_registry.wa_set_archived(phone, True)

    token = _login()
    r = client.post(
        f"/dashboard/api/messages/conversations/{phone}/unarchive",
        headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["archived"] is False

    r = client.get("/dashboard/api/messages/conversations", headers=_auth(token))
    assert any(c["phone"] == phone for c in r.json()), \
        "phone must reappear in active list after unarchive"
    _wipe_wa_phone(phone)


def test_archive_email_thread_excludes_and_includes(monkeypatch, tmp_path):
    """Brief 249: archive on an email::thread_key conv toggles flags.deleted
    in email_thread_state.json. Uses tmp_path to isolate the test from
    real production state."""
    from shared import state_registry
    fake_state = {
        "threads": {
            "subj:bob@x.com:test 249": {
                "messages": [{"role": "customer", "ts": "2026-05-10T00:00:00+00:00",
                              "body": "[QA] test"}],
                "fields": {"customer_name": "Bob 249"},
                "flags": {},
            }
        }
    }
    state_path = tmp_path / "email_thread_state.json"
    state_path.write_text(json.dumps(fake_state))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                         lambda: str(state_path))

    token = _login()
    conv_id = "email::subj:bob@x.com:test 249"

    r = client.get("/dashboard/api/messages/conversations", headers=_auth(token))
    assert any(c["phone"] == conv_id for c in r.json()), \
        "expected email conv in active list before archive"

    r = client.post(
        f"/dashboard/api/messages/conversations/{conv_id}/archive",
        headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["channel"] == "email"

    r = client.get("/dashboard/api/messages/conversations", headers=_auth(token))
    assert not any(c["phone"] == conv_id for c in r.json())
    r = client.get("/dashboard/api/messages/conversations/archived",
                    headers=_auth(token))
    assert any(c["phone"] == conv_id for c in r.json())


def test_archive_email_accepts_double_encoded_thread_key(monkeypatch, tmp_path):
    """Email archive/unarchive tolerates a path id that arrives still
    percent-encoded after one proxy/framework decode."""
    from shared import state_registry
    fake_state = {
        "threads": {
            "subj:encoded@x.com:test 249": {
                "messages": [{"role": "customer", "ts": "2026-05-10T00:00:00+00:00",
                              "body": "[QA] encoded"}],
                "fields": {},
                "flags": {},
            }
        }
    }
    state_path = tmp_path / "email_thread_state.json"
    state_path.write_text(json.dumps(fake_state))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                         lambda: str(state_path))

    token = _login()
    conv_id = "email::subj:encoded@x.com:test 249"
    double_encoded = urllib.parse.quote(urllib.parse.quote(conv_id, safe=""),
                                        safe="")

    r = client.post(
        f"/dashboard/api/messages/conversations/{double_encoded}/archive",
        headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["conversationId"] == conv_id
    saved = json.loads(state_path.read_text())
    assert saved["threads"]["subj:encoded@x.com:test 249"]["flags"]["deleted"] is True


def test_facebookmail_system_notice_hidden_from_email_lists(monkeypatch, tmp_path):
    """Provider notifications are not customer conversations. They should
    not appear in active or archived dashboard lists for any tenant."""
    from shared import state_registry
    fake_state = {
        "threads": {
            "subj:notification@facebookmail.com:confirm your business email": {
                "messages": [{"role": "customer", "ts": "2026-05-20T00:00:00+00:00",
                              "body": "This looks like an automated notification from Facebook."}],
                "fields": {},
                "flags": {},
            },
            "subj:real@example.com:hello": {
                "messages": [{"role": "customer", "ts": "2026-05-20T00:01:00+00:00",
                              "body": "Hello"}],
                "fields": {},
                "flags": {},
            },
            "subj:notification@facebookmail.com:archived notice": {
                "messages": [{"role": "customer", "ts": "2026-05-20T00:02:00+00:00",
                              "body": "Facebook notice"}],
                "fields": {},
                "flags": {"deleted": True},
            },
        }
    }
    state_path = tmp_path / "email_thread_state.json"
    state_path.write_text(json.dumps(fake_state))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                         lambda: str(state_path))

    active = state_registry.email_list_conversations()
    archived = state_registry.email_list_archived_conversations()
    assert all("facebookmail.com" not in row["phone"] for row in active)
    assert all("facebookmail.com" not in row["phone"] for row in archived)
    assert any("real@example.com" in row["phone"] for row in active)


def test_archive_email_404_when_thread_key_missing(monkeypatch, tmp_path):
    """Brief 249: archive on a non-existent email thread_key returns 404."""
    from shared import state_registry
    state_path = tmp_path / "email_thread_state.json"
    state_path.write_text(json.dumps({"threads": {}}))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                         lambda: str(state_path))

    token = _login()
    r = client.post(
        "/dashboard/api/messages/conversations/email::nonexistent/archive",
        headers=_auth(token))
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


def test_wa_list_conversations_filters_brief_237_archived_rows():
    """Brief 249 regression fix: Brief 237's bulk archive sweep marked
    WhatsApp rows with conversation_status.deleted=1 + status='archived'
    but pre-Brief-249 wa_list_conversations did NOT filter on this flag,
    so archived rows stayed in the active list. After Brief 249's LEFT
    JOIN filter, they're correctly excluded."""
    from shared import state_registry
    phone = "249_wa_brief237_filter_phone"
    _wipe_wa_phone(phone)
    state_registry.wa_store_message(phone, "user", "[QA] hi")
    state_registry.wa_set_archived(phone, True)

    token = _login()
    r = client.get("/dashboard/api/messages/conversations", headers=_auth(token))
    assert not any(c["phone"] == phone for c in r.json()), \
        "Brief 237's archived row must be excluded from wa_list_conversations"
    _wipe_wa_phone(phone)


def test_get_escalations_status_filter_returns_only_resolved():
    """Brief 249: GET /escalations?status=resolved returns only
    notification rows whose status='resolved'. Other statuses excluded."""
    from shared import state_registry
    cust_pending = "249_resolved_filter_pending@example.com"
    eid_pending = state_registry.create_pending_notification(
        notification_type="escalation", channel="email",
        customer_id=cust_pending, customer_name="Pending Test",
        subject="[ESCALATION] pending", body="body", mode="hard")
    cust_resolved = "249_resolved_filter_resolved@example.com"
    eid_resolved = state_registry.create_pending_notification(
        notification_type="escalation", channel="email",
        customer_id=cust_resolved, customer_name="Resolved Test",
        subject="[ESCALATION] resolved", body="body", mode="hard")
    state_registry.update_notification_status(eid_resolved, "resolved")

    try:
        token = _login()
        r = client.get("/dashboard/api/escalations?status=resolved",
                        headers=_auth(token))
        assert r.status_code == 200
        rows = r.json()
        ids = [r["id"] for r in rows]
        assert str(eid_resolved) in ids, \
            "resolved escalation must be in status=resolved filter"
        assert str(eid_pending) not in ids, \
            "non-resolved escalation must NOT appear when status=resolved"
    finally:
        # try/finally guarantees cleanup runs even if an assertion fails;
        # otherwise dev DB accumulates rows on every re-run.
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM pending_notifications WHERE id IN (?, ?)",
                     (eid_pending, eid_resolved))
        conn.commit()
        conn.close()


# ── Brief 253: get_all_escalations excludes rows on archived conversations ─

def test_escalations_on_archived_wa_conversation_excluded_from_get_all():
    """Brief 253: when a WhatsApp conversation is archived via Brief
    249's wa_set_archived (conversation_status.deleted=1), its
    escalation rows are excluded from get_all_escalations() — fixing
    the issue #22 stuck-row symptom where Calvin's archived
    conversation kept showing escalations in the dashboard
    Escalations tab."""
    from shared import state_registry
    phone = "253_archived_conv_phone"
    _wipe_wa_phone(phone)

    eid = state_registry.create_pending_notification(
        notification_type="escalation", channel="whatsapp",
        customer_id=phone, customer_name="Brief 253 Test",
        subject="Stuck escalation test", body="body", mode="hard")
    try:
        rows_before = state_registry.get_all_escalations()
        assert any(r["id"] == eid for r in rows_before), (
            f"escalation {eid} must be visible BEFORE archive; "
            f"got {[r['id'] for r in rows_before[:5]]}")

        state_registry.wa_set_archived(phone, True)

        rows_after = state_registry.get_all_escalations()
        assert not any(r["id"] == eid for r in rows_after), (
            f"escalation {eid} must be excluded AFTER archive; "
            f"the LEFT JOIN with conversation_status.deleted=1 should "
            f"have filtered it out")

        state_registry.wa_set_archived(phone, False)
        rows_unarchived = state_registry.get_all_escalations()
        assert any(r["id"] == eid for r in rows_unarchived), (
            f"escalation {eid} must reappear after unarchive — "
            f"Brief 253 is a view filter, not a delete")
    finally:
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM pending_notifications WHERE id = ?", (eid,))
        conn.commit()
        conn.close()
        _wipe_wa_phone(phone)


def test_escalations_on_conversation_without_status_row_still_returned():
    """Brief 253: many active WhatsApp conversations have NO
    conversation_status row at all. The LEFT JOIN must preserve these
    via `WHERE cs.deleted IS NULL OR cs.deleted = 0`.

    NOTE: create_pending_notification (state_registry.py:1656) calls
    set_conversation_status which UPSERTs a row, so the "no status row"
    scenario CANNOT be created via the helper. This test bypasses the
    helper with a direct SQL INSERT so the LEFT JOIN's NULL branch is
    genuinely exercised (round-1 reviewer caught the original test
    using the helper — the cs row was always being created, so the
    test never hit the NULL branch it claimed to cover)."""
    from shared import state_registry
    from datetime import datetime, timezone
    phone = "253_no_status_row_phone"
    _wipe_wa_phone(phone)
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?",
                 (phone,))
    conn.commit()
    conn.close()

    now = datetime.now(timezone.utc).isoformat()
    conn = state_registry._get_conn()
    cur = conn.execute(
        "INSERT INTO pending_notifications "
        "(notification_type, channel, customer_id, customer_name, "
        "subject, body, status, created_at, mode) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("escalation", "whatsapp", phone, "Brief 253 NoStatus",
         "No status row test", "body", "sent", now, "hard"))
    eid = cur.lastrowid
    conn.commit()
    conn.close()

    try:
        conn = state_registry._get_conn()
        cs_row = conn.execute(
            "SELECT 1 FROM conversation_status WHERE conversation_id = ?",
            (phone,)).fetchone()
        conn.close()
        assert cs_row is None, (
            f"test setup error: conversation_status row exists for "
            f"{phone!r}; the direct-INSERT path was supposed to bypass "
            f"set_conversation_status; defensive cleanup at start of "
            f"test must have failed")

        rows = state_registry.get_all_escalations()
        assert any(r["id"] == eid for r in rows), (
            f"escalation {eid} on conversation with NO status row must "
            f"be returned; LEFT JOIN's `cs.deleted IS NULL` branch "
            f"failed to preserve it")
    finally:
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM pending_notifications WHERE id = ?", (eid,))
        conn.commit()
        conn.close()
        _wipe_wa_phone(phone)
