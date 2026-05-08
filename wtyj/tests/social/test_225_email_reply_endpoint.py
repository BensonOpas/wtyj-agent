"""Tests for Brief 225 — POST /messages/conversations/{id}/email/reply."""
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

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_email_thread(tmp_path, monkeypatch, customer_email, subject="test225 reply"):
    """Write a fake email_thread_state.json with one customer message and
    monkeypatch the state-registry path resolver. Returns the thread_key."""
    from shared import state_registry
    thread_key = f"subj:{customer_email}:{subject}"
    state = {
        "threads": {
            thread_key: {
                "messages": [{
                    "role": "customer",
                    "ts": "2026-05-08T10:00:00+00:00",
                    "body": "Hi, can you help?",
                }],
                "fields": {},
                "flags": {},
            }
        }
    }
    fake_path = tmp_path / "email_thread_state.json"
    fake_path.write_text(json.dumps(state))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                        lambda: str(fake_path))
    return thread_key, fake_path


@patch("dashboard.api.smtp_send")
def test_reply_sends_smtp_and_appends_thread(mock_smtp, tmp_path, monkeypatch):
    """Brief 225: smtp_send fires with the right address + subject; thread state
    gains an operator-role message with the operator's body."""
    customer_email = "test225-alice@example.com"
    thread_key, fake_path = _seed_email_thread(tmp_path, monkeypatch,
                                               customer_email)

    token = _login()
    r = client.post(
        f"/dashboard/api/messages/conversations/email::{thread_key}/email/reply",
        json={"body": "Thanks for reaching out — looking into it."},
        headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "channel": "email"}

    mock_smtp.assert_called_once()
    to_addr, subj, sent_body = mock_smtp.call_args.args[0:3]
    assert to_addr == customer_email
    assert subj.lower().startswith("re:")
    assert "test225 reply" in subj.lower()
    assert sent_body == "Thanks for reaching out — looking into it."

    state = json.loads(fake_path.read_text())
    msgs = state["threads"][thread_key]["messages"]
    # Brief 233: operator-typed verbatim replies persist with role="operator"
    # so the dashboard can render them distinctly from Marina-generated ones.
    assert msgs[-1]["role"] == "operator"
    assert msgs[-1]["body"] == "Thanks for reaching out — looking into it."


@patch("dashboard.api.smtp_send")
def test_reply_resolves_email_only_conversation_id(mock_smtp, tmp_path, monkeypatch):
    """When the frontend passes just the customer email (not the full
    `email::<thread_key>`), the resolver finds the matching thread."""
    customer_email = "test225-bob@example.com"
    _seed_email_thread(tmp_path, monkeypatch, customer_email,
                       subject="brief 225 inquiry")
    token = _login()
    r = client.post(
        f"/dashboard/api/messages/conversations/{customer_email}/email/reply",
        json={"body": "Will follow up shortly."},
        headers=_auth(token))
    assert r.status_code == 200, r.text
    mock_smtp.assert_called_once()
    assert mock_smtp.call_args.args[0] == customer_email


@patch("dashboard.api.smtp_send")
def test_reply_strips_email_prefix(mock_smtp, tmp_path, monkeypatch):
    customer_email = "test225-carol@example.com"
    thread_key, _ = _seed_email_thread(tmp_path, monkeypatch, customer_email,
                                       subject="menu request")
    token = _login()
    r = client.post(
        f"/dashboard/api/messages/conversations/email::{thread_key}/email/reply",
        json={"body": "Here's our menu."},
        headers=_auth(token))
    assert r.status_code == 200, r.text
    mock_smtp.assert_called_once()


def test_reply_400_on_empty_body(tmp_path, monkeypatch):
    customer_email = "test225-dan@example.com"
    thread_key, _ = _seed_email_thread(tmp_path, monkeypatch, customer_email)
    token = _login()
    r = client.post(
        f"/dashboard/api/messages/conversations/email::{thread_key}/email/reply",
        json={"body": "   "},
        headers=_auth(token))
    assert r.status_code == 400
    assert "body" in r.json()["detail"].lower()


def test_reply_404_when_thread_missing(tmp_path, monkeypatch):
    """An email-only conversation_id with no matching thread → 404."""
    from shared import state_registry
    fake_path = tmp_path / "email_thread_state.json"
    fake_path.write_text(json.dumps({"threads": {}}))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                        lambda: str(fake_path))
    token = _login()
    r = client.post(
        "/dashboard/api/messages/conversations/test225-nobody@example.com/email/reply",
        json={"body": "hello"},
        headers=_auth(token))
    assert r.status_code == 404


def test_reply_500_on_smtp_failure(tmp_path, monkeypatch):
    customer_email = "test225-eve@example.com"
    thread_key, _ = _seed_email_thread(tmp_path, monkeypatch, customer_email)
    token = _login()
    with patch("dashboard.api.smtp_send",
               side_effect=Exception("Connection refused")):
        r = client.post(
            f"/dashboard/api/messages/conversations/email::{thread_key}/email/reply",
            json={"body": "hello"},
            headers=_auth(token))
    assert r.status_code == 500
    assert "Failed to send email reply" in r.json()["detail"]
