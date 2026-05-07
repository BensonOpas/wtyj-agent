# test_210_email_escalation_reply.py
# Brief 210: dashboard reply-to-escalation endpoint must handle email channel
# in addition to the existing whatsapp branch.
import sys, os
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


def _cleanup(esc_id, customer_id):
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM pending_notifications WHERE id = ?", (esc_id,))
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?", (customer_id,))
    conn.commit()
    conn.close()


# --- Test 1: Email reply happy path ---
@patch("dashboard.api.state_registry.email_append_assistant_message",
       return_value="subj:test-customer@example.com:abc")
@patch("dashboard.api.smtp_send")
def test_email_reply_sends_via_smtp_and_marks_replied(mock_smtp, mock_append):
    from shared import state_registry
    customer_email = "test210-happy@example.com"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation", channel="email",
        customer_id=customer_email, customer_name="Test Customer",
        subject="[ESCALATION] activation call", body="full chat log here",
    )

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/reply",
                     json={"answer": "Wednesday 4pm works. Calendar invite incoming."},
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["channel"] == "email"
    assert "Wednesday 4pm" in data["reply"]

    mock_smtp.assert_called_once()
    args, _ = mock_smtp.call_args
    assert args[0] == customer_email
    # subject prepended with "Re: " since the seeded subject doesn't start with re:
    assert args[1].lower().startswith("re:")
    assert args[2] == "Wednesday 4pm works. Calendar invite incoming."

    mock_append.assert_called_once_with(customer_email, "Wednesday 4pm works. Calendar invite incoming.")

    escs = state_registry.get_all_escalations()
    matched = next((e for e in escs if e["id"] == esc_id), None)
    assert matched is not None
    assert matched["status"] == "replied"

    _cleanup(esc_id, customer_email)


# --- Test 2: Invalid email address rejected ---
def test_email_reply_rejects_invalid_address():
    from shared import state_registry
    bad_id = "not-an-email"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation", channel="email",
        customer_id=bad_id, customer_name="Test",
        subject="[ESCALATION]", body="x",
    )

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/reply",
                     json={"answer": "test"},
                     headers=_auth(token))
    assert r.status_code == 400
    assert "valid email" in r.json()["detail"].lower()

    _cleanup(esc_id, bad_id)


# --- Test 3: SMTP failure surfaces as 500, status NOT flipped ---
@patch("dashboard.api.smtp_send", side_effect=RuntimeError("smtp down"))
def test_email_reply_returns_500_on_smtp_failure(mock_smtp):
    from shared import state_registry
    customer_email = "test210-smtperr@example.com"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation", channel="email",
        customer_id=customer_email, customer_name="Test",
        subject="[ESCALATION]", body="x",
    )

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/reply",
                     json={"answer": "test"},
                     headers=_auth(token))
    assert r.status_code == 500
    assert "smtp down" in r.json()["detail"].lower()

    # Status still pending — failed send must not flip the row
    escs = state_registry.get_all_escalations()
    matched = next((e for e in escs if e["id"] == esc_id), None)
    assert matched is not None
    assert matched["status"] == "pending"

    _cleanup(esc_id, customer_email)


# --- Test 4: SR's frontend field name {message} accepted ---
@patch("dashboard.api.state_registry.email_append_assistant_message",
       return_value="subj:test-sr-message@example.com:abc")
@patch("dashboard.api.smtp_send")
def test_email_reply_accepts_message_field_from_sr_frontend(mock_smtp, mock_append):
    """SR's unboks frontend posts {message: ...} not {answer: ...}.
    Backend must accept both field names so the new reply composer works."""
    from shared import state_registry
    customer_email = "test210-sr-message@example.com"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation", channel="email",
        customer_id=customer_email, customer_name="Test",
        subject="[ESCALATION]", body="x",
    )

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/reply",
                     json={"message": "Reply via SR's {message} field"},
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    args, _ = mock_smtp.call_args
    assert args[2] == "Reply via SR's {message} field"

    _cleanup(esc_id, customer_email)


# --- Test 5: Empty body returns 400 with clear error ---
def test_empty_body_returns_400():
    """Both fields missing/empty -> 400 with a message naming both fields."""
    from shared import state_registry
    customer_email = "test210-empty@example.com"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation", channel="email",
        customer_id=customer_email, customer_name="Test",
        subject="[ESCALATION]", body="x",
    )
    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/reply",
                     json={"message": "   "},
                     headers=_auth(token))
    assert r.status_code == 400
    detail = r.json()["detail"].lower()
    assert "message" in detail and "answer" in detail
    _cleanup(esc_id, customer_email)


# --- Test 6: Unknown channel still 400 (regression guard) ---
def test_unknown_channel_still_400():
    from shared import state_registry
    customer_id = "test210-ig-handle"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation", channel="instagram",
        customer_id=customer_id, customer_name="Test",
        subject="[ESCALATION]", body="x",
    )

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/reply",
                     json={"answer": "test"},
                     headers=_auth(token))
    assert r.status_code == 400
    assert "instagram" in r.json()["detail"].lower()

    _cleanup(esc_id, customer_id)
