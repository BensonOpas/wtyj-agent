# test_214_guidance_endpoint.py
# Brief 214: POST /escalations/:id/guidance — soft-mode escalation flow.
# Operator coaches Marina via {message}; Marina reformulates and sends
# in her voice. Hard-mode (Brief 213) escalations return 409.

import sys, os, json
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
        subject="[ESCALATION] test214", body="test body")
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
    conn.commit()
    conn.close()


# --- Test 0 (post-fix): /guidance accepts SR's {guidance} field name
@patch("dashboard.api.send_whatsapp_message", return_value=True)
@patch("dashboard.api.marina_agent")
def test_guidance_accepts_guidance_field_name_from_frontend(mock_marina, mock_wa_send):
    """SR's frontend posts {guidance: "..."} per lib/api.ts GuidancePayload.
    Backend must accept it (alongside message/answer)."""
    from shared import state_registry
    customer_id = "214_guidance_field_phone"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation", channel="whatsapp",
        customer_id=customer_id, customer_name="Test",
        subject="[ESCALATION]", body="x")
    state_registry.set_escalation_mode(esc_id, "soft")

    mock_marina.process_message.return_value = {
        "reply": "Yes, all good.", "fields": {}, "flags": {},
        "intents": [], "confidence": "high", "requires_human": False,
    }

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/guidance",
                     json={"guidance": "Yes, everything is fine."},
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    # Marina was called with the guidance text as the third positional arg
    call = mock_marina.process_message.call_args
    assert call.args[2] == "Yes, everything is fine."

    # Cleanup
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM pending_notifications WHERE id = ?", (esc_id,))
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?", (customer_id,))
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (customer_id,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (customer_id,))
    conn.execute("DELETE FROM escalation_learnings WHERE conversation_id = ?", (customer_id,))
    conn.commit()
    conn.close()


# --- Test 1: WhatsApp soft-mode relay happy path
@patch("dashboard.api.send_whatsapp_message", return_value=True)
@patch("dashboard.api.marina_agent")
def test_guidance_whatsapp_relay_succeeds(mock_marina, mock_wa_send):
    from shared import state_registry
    customer_id = "214_wa_guidance_phone"
    esc_id = _seed_escalation("whatsapp", customer_id, mode="soft")

    mock_marina.process_message.return_value = {
        "reply": "The weight limit is 150kg per person.",
        "fields": {}, "flags": {}, "intents": [],
        "confidence": "high", "requires_human": False,
    }

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/guidance",
                     json={"message": "tell them weight limit is 150kg"},
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["channel"] == "whatsapp"
    assert "150kg" in body["reply"]

    # Marina was called with the operator text as the third arg
    call = mock_marina.process_message.call_args
    assert call.args[0] == customer_id
    assert call.args[2] == "tell them weight limit is 150kg"

    # WhatsApp send was called with Marina's reformulated reply
    mock_wa_send.assert_called_once()
    assert mock_wa_send.call_args.args[1] == "The weight limit is 150kg per person."

    # Status flipped to replied
    rows = state_registry.get_all_escalations()
    matched = next(e for e in rows if e["id"] == esc_id)
    assert matched["status"] == "replied"

    _cleanup(esc_id, customer_id)


# --- Test 2: Email soft-mode relay happy path
@patch("dashboard.api.smtp_send")
@patch("dashboard.api.state_registry.email_append_assistant_message",
       return_value="subj:test214@example.com:test")
@patch("dashboard.api.marina_agent")
def test_guidance_email_relay_succeeds(mock_marina, mock_append, mock_smtp):
    from shared import state_registry
    customer_email = "test214-guidance@example.com"
    esc_id = _seed_escalation("email", customer_email, mode="soft")

    mock_marina.process_message.return_value = {
        "reply": "Hi Calvin, Wednesday at 4pm works on our end. Calendar invite incoming.",
        "fields": {}, "flags": {}, "intents": [],
        "confidence": "high", "requires_human": False,
    }

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/guidance",
                     json={"message": "propose Wed 4pm + send invite"},
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["channel"] == "email"
    assert "Wednesday" in body["reply"]

    # Marina was called with the operator text + email signature
    call = mock_marina.process_message.call_args
    assert call.args[0] == customer_email
    assert call.args[2] == "propose Wed 4pm + send invite"

    # smtp_send called with customer email + subject + Marina's reformulated reply
    mock_smtp.assert_called_once()
    args, _ = mock_smtp.call_args
    assert args[0] == customer_email
    assert args[2] == "Hi Calvin, Wednesday at 4pm works on our end. Calendar invite incoming."

    # email_append_assistant_message was called with Marina's reply (not operator text)
    mock_append.assert_called_once()
    append_args, _ = mock_append.call_args
    assert append_args[1] == "Hi Calvin, Wednesday at 4pm works on our end. Calendar invite incoming."

    _cleanup(esc_id, customer_email)


# --- Test 3: Hard-mode escalation rejects /guidance with 409
def test_guidance_rejects_hard_mode_with_409():
    customer_id = "214_hard_phone"
    esc_id = _seed_escalation("whatsapp", customer_id, mode="hard")

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/guidance",
                     json={"message": "test"}, headers=_auth(token))
    assert r.status_code == 409, r.text
    detail = r.json()["detail"].lower()
    assert "hard" in detail
    assert "/reply" in detail or "/handback" in detail

    _cleanup(esc_id, customer_id)


# --- Test 4: Empty body returns 400
def test_guidance_empty_body_returns_400():
    customer_id = "214_empty_phone"
    esc_id = _seed_escalation("whatsapp", customer_id, mode="soft")

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/guidance",
                     json={"message": "   "}, headers=_auth(token))
    assert r.status_code == 400
    assert "guidance" in r.json()["detail"].lower() or "required" in r.json()["detail"].lower()

    _cleanup(esc_id, customer_id)


# --- Test 5: Unsupported channel returns 501
def test_guidance_unsupported_channel_returns_501():
    customer_id = "214_ig_handle"
    esc_id = _seed_escalation("instagram", customer_id, mode="soft")

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/guidance",
                     json={"message": "test"}, headers=_auth(token))
    assert r.status_code == 501
    detail = r.json()["detail"].lower()
    assert "instagram" in detail
    assert "not yet implemented" in detail

    _cleanup(esc_id, customer_id)


# --- Test 6: Marina failure returns 500, status NOT flipped
@patch("dashboard.api.send_whatsapp_message")
@patch("dashboard.api.marina_agent")
def test_guidance_marina_failure_returns_500_and_status_unchanged(mock_marina, mock_wa_send):
    from shared import state_registry
    customer_id = "214_marina_fail_phone"
    esc_id = _seed_escalation("whatsapp", customer_id, mode="soft")
    # Marina returns empty reply (one form of failure — empty content)
    mock_marina.process_message.return_value = {
        "reply": "", "fields": {}, "flags": {}, "intents": [],
        "confidence": "low", "requires_human": True,
    }

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/guidance",
                     json={"message": "test"}, headers=_auth(token))
    assert r.status_code == 500
    assert "marina returned empty reply" in r.json()["detail"].lower()

    # Whatsapp send was NOT called
    mock_wa_send.assert_not_called()

    # Status still pending — failed relay must not flip the row
    rows = state_registry.get_all_escalations()
    matched = next(e for e in rows if e["id"] == esc_id)
    assert matched["status"] == "pending"

    _cleanup(esc_id, customer_id)
