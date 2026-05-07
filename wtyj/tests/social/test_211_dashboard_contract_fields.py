# test_211_dashboard_contract_fields.py
# Brief 211: GET /messages/conversations/:phone must include escalated /
# escalationResolved / escalationMode / aiMuted so SR's EscalationReply
# Composer renders. GET /escalations email rows must include a routable
# `phone` field (the email::thread_key) so clicking the row opens the
# real thread instead of falling back to esc:1 (empty).

import sys, os, json, tempfile
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

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _cleanup_phone(phone):
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?", (phone,))
    conn.commit()
    conn.close()


def _cleanup_escalation(esc_id, customer_id):
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM pending_notifications WHERE id = ?", (esc_id,))
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?", (customer_id,))
    conn.commit()
    conn.close()


# --- Test 1: escalated == True when conversation_status = "open" ---
def test_get_conversation_returns_escalated_true_when_open():
    from shared import state_registry
    phone = "211_open_phone"
    state_registry.set_conversation_status(phone, "open", "whatsapp")

    token = _login()
    r = client.get(f"/dashboard/api/messages/conversations/{phone}",
                    headers=_auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["escalated"] is True, f"expected escalated=True, got {data}"
    assert data["escalationResolved"] is False

    _cleanup_phone(phone)


# --- Test 2: escalated == False when no conversation_status row ---
def test_get_conversation_returns_escalated_false_when_no_row():
    from shared import state_registry
    phone = "211_clean_phone"
    # Pre-clean to ensure no leftover row from a previous run
    _cleanup_phone(phone)

    token = _login()
    r = client.get(f"/dashboard/api/messages/conversations/{phone}",
                    headers=_auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["escalated"] is False
    assert data["escalationResolved"] is False


# --- Test 3: escalationResolved == True when status = "resolved" ---
def test_get_conversation_returns_resolved_when_status_resolved():
    from shared import state_registry
    phone = "211_resolved_phone"
    state_registry.set_conversation_status(phone, "resolved", "whatsapp")

    token = _login()
    r = client.get(f"/dashboard/api/messages/conversations/{phone}",
                    headers=_auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["escalated"] is False
    assert data["escalationResolved"] is True

    _cleanup_phone(phone)


# --- Test 4: escalationMode is null + aiMuted is false (Tier 2 placeholders) ---
def test_get_conversation_defaults_mode_null_and_aimuted_false():
    from shared import state_registry
    phone = "211_defaults_phone"
    _cleanup_phone(phone)

    token = _login()
    r = client.get(f"/dashboard/api/messages/conversations/{phone}",
                    headers=_auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["escalationMode"] is None, f"escalationMode should be None until Tier 2"
    assert data["aiMuted"] is False, f"aiMuted should be False until Tier 2"


# --- Test 5: /escalations email row exposes routable `phone` ---
def test_list_escalations_email_row_has_routable_phone(tmp_path, monkeypatch):
    from shared import state_registry

    # Build a fake email_thread_state.json with one thread whose key contains
    # the customer email.
    customer_email = "test211-routable@example.com"
    fake_thread_key = f"subj:{customer_email}:dashboard-test"
    fake_state = {
        "threads": {
            fake_thread_key: {
                "messages": [],
                "fields": {},
                "flags": {},
            }
        }
    }
    fake_path = tmp_path / "email_thread_state.json"
    fake_path.write_text(json.dumps(fake_state))

    monkeypatch.setattr(state_registry, "_get_email_state_path",
                        lambda: str(fake_path))

    esc_id = state_registry.create_pending_notification(
        notification_type="escalation", channel="email",
        customer_id=customer_email, customer_name="Test",
        subject="[ESCALATION] routing-test", body="x",
    )

    token = _login()
    r = client.get("/dashboard/api/escalations", headers=_auth(token))
    assert r.status_code == 200, r.text
    rows = r.json()
    matched = next((row for row in rows if row["id"] == str(esc_id)), None)
    assert matched is not None, f"escalation {esc_id} not in response"
    assert matched["phone"] == f"email::{fake_thread_key}", \
        f"expected routable email::-prefixed key, got phone={matched['phone']!r}"

    _cleanup_escalation(esc_id, customer_email)
