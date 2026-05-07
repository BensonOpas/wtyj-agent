# test_218_email_actions.py
# Brief 218: POST /messages/conversations/:id/email/forward + /delete

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


def _seed_email_thread(tmp_path, monkeypatch, customer_email, with_messages=True,
                       extra_flags=None):
    """Write a fake email_thread_state.json with one customer message."""
    from shared import state_registry
    thread_key = f"subj:{customer_email}:test218"
    messages = []
    if with_messages:
        messages.append({
            "role": "customer",
            "ts": "2026-05-07T00:00:00+00:00",
            "body": "Original customer body for forward test",
        })
    state = {
        "threads": {
            thread_key: {
                "messages": messages,
                "fields": {},
                "flags": dict(extra_flags or {}),
            }
        }
    }
    fake_path = tmp_path / "email_thread_state.json"
    fake_path.write_text(json.dumps(state))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                        lambda: str(fake_path))
    return thread_key, fake_path


# --- Test 1: Forward calls smtp_send per recipient + body contains note + original
@patch("dashboard.api.smtp_send")
def test_forward_calls_smtp_send_for_each_recipient(mock_smtp, tmp_path, monkeypatch):
    customer_email = "test218-fwd@example.com"
    thread_key, _ = _seed_email_thread(tmp_path, monkeypatch, customer_email)

    token = _login()
    r = client.post(
        f"/dashboard/api/messages/conversations/email::{thread_key}/email/forward",
        json={"to": ["a@x.com", "b@x.com"], "note": "FYI from operator"},
        headers=_auth(token))
    assert r.status_code == 200, r.text
    assert mock_smtp.call_count == 2
    sent_recipients = [call.args[0] for call in mock_smtp.call_args_list]
    assert sorted(sent_recipients) == ["a@x.com", "b@x.com"]
    sent_body = mock_smtp.call_args_list[0].args[2]
    assert "FYI from operator" in sent_body
    assert "Original customer body for forward test" in sent_body
    assert r.json()["forwarded_to"] == sent_recipients


# --- Test 2: Forward 400 on empty recipients
def test_forward_400_on_empty_recipients(tmp_path, monkeypatch):
    customer_email = "test218-empty@example.com"
    thread_key, _ = _seed_email_thread(tmp_path, monkeypatch, customer_email)

    token = _login()
    r = client.post(
        f"/dashboard/api/messages/conversations/email::{thread_key}/email/forward",
        json={"to": []},
        headers=_auth(token))
    assert r.status_code == 400
    detail = r.json()["detail"].lower()
    assert "to" in detail or "recipient" in detail


# --- Test 3: Forward 404 when thread has no customer message
def test_forward_404_when_no_customer_message(tmp_path, monkeypatch):
    customer_email = "test218-empty-thread@example.com"
    thread_key, _ = _seed_email_thread(tmp_path, monkeypatch, customer_email,
                                         with_messages=False)

    token = _login()
    r = client.post(
        f"/dashboard/api/messages/conversations/email::{thread_key}/email/forward",
        json={"to": ["a@x.com"]},
        headers=_auth(token))
    assert r.status_code == 404


# --- Test 4: Forward response acknowledges attachments NOT forwarded
@patch("dashboard.api.smtp_send")
def test_forward_response_acknowledges_attachments_skipped(mock_smtp, tmp_path, monkeypatch):
    customer_email = "test218-att@example.com"
    thread_key, _ = _seed_email_thread(tmp_path, monkeypatch, customer_email)

    token = _login()
    r = client.post(
        f"/dashboard/api/messages/conversations/email::{thread_key}/email/forward",
        json={"to": ["x@y.com"], "includeAttachments": True},
        headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["attachments_included"] is False
    # The original body still went through despite the ignored flag
    sent_body = mock_smtp.call_args.args[2]
    assert "Original customer body for forward test" in sent_body


# --- Test 5: Delete marks thread deleted + filters from list
def test_delete_marks_thread_deleted_and_filters_from_list(tmp_path, monkeypatch):
    from shared import state_registry
    customer_email = "test218-del@example.com"
    thread_key, _ = _seed_email_thread(tmp_path, monkeypatch, customer_email)

    # Pre: thread shows up in list
    pre_list = state_registry.email_list_conversations()
    assert any(row["phone"] == f"email::{thread_key}" for row in pre_list)

    token = _login()
    r = client.post(
        f"/dashboard/api/messages/conversations/email::{thread_key}/email/delete",
        json={"deleteMode": "trash"},
        headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["deleteMode"] == "trash"

    # Post: thread filtered from list
    post_list = state_registry.email_list_conversations()
    assert not any(row["phone"] == f"email::{thread_key}" for row in post_list)


# --- Test 6: Delete 400 on invalid mode
def test_delete_400_on_invalid_mode(tmp_path, monkeypatch):
    customer_email = "test218-mode@example.com"
    thread_key, _ = _seed_email_thread(tmp_path, monkeypatch, customer_email)

    token = _login()
    r = client.post(
        f"/dashboard/api/messages/conversations/email::{thread_key}/email/delete",
        json={"deleteMode": "permanent"},
        headers=_auth(token))
    assert r.status_code == 400
    detail = r.json()["detail"].lower()
    assert "trash" in detail and "only" in detail
