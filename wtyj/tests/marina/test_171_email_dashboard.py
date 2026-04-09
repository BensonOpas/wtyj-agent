"""Tests for Brief 171 — email conversations in the dashboard.

Covers:
- email_list_conversations reads email_thread_state.json and returns rows
- Shape matches the wa_list_conversations contract (phone, customer_name, etc.)
- phone field has 'email::' prefix
- email_get_conversation returns normalized messages (role customer→user,
  marina→assistant; body→text; ts→created_at)
- Merged endpoint source guard in dashboard/api.py
"""
import json
import os
import tempfile

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from shared import state_registry


def test_email_list_conversations_returns_empty_when_no_file(monkeypatch, tmp_path):
    """If email_thread_state.json doesn't exist, the helper returns [] gracefully."""
    fake_path = str(tmp_path / "nonexistent.json")
    monkeypatch.setattr(state_registry, "_get_email_state_path", lambda: fake_path)
    assert state_registry.email_list_conversations() == []


def test_email_list_conversations_returns_expected_shape(monkeypatch, tmp_path):
    """Brief 171: rows must match the wa_list_conversations shape."""
    fake_state = {
        "threads": {
            "subj:alice@x.com:booking question": {
                "fields": {
                    "customer_name": "Alice",
                    "service_name": "Sunset Cruise",
                    "date": "2026-05-01",
                },
                "flags": {},
                "messages": [
                    {"role": "customer", "ts": "2026-04-09T09:00:00+00:00",
                     "body": "Hello, I want to book"},
                    {"role": "marina", "ts": "2026-04-09T09:01:00+00:00",
                     "body": "Happy to help — which date?"},
                ],
                "last_activity": 1775692099,
            },
        }
    }
    fake_path = str(tmp_path / "email_thread_state.json")
    with open(fake_path, "w") as f:
        json.dump(fake_state, f)
    monkeypatch.setattr(state_registry, "_get_email_state_path", lambda: fake_path)

    result = state_registry.email_list_conversations()
    assert len(result) == 1
    row = result[0]
    assert row["phone"] == "email::subj:alice@x.com:booking question"
    assert row["customer_name"] == "Alice"
    assert row["channel"] == "email"
    assert row["message_count"] == 2
    assert row["last_message_role"] == "assistant"  # 'marina' normalized
    assert "Happy to help" in row["last_message"]
    assert row["status"] == "active"


def test_email_list_conversations_marks_escalated(monkeypatch, tmp_path):
    """fully_escalated or awaiting_relay flags → status='escalated'."""
    fake_state = {
        "threads": {
            "subj:bob@x.com:complaint": {
                "fields": {"customer_name": "Bob"},
                "flags": {"fully_escalated": True},
                "messages": [
                    {"role": "customer", "ts": "2026-04-09T09:00:00+00:00",
                     "body": "I want a refund"},
                ],
            },
        }
    }
    fake_path = str(tmp_path / "email_thread_state.json")
    with open(fake_path, "w") as f:
        json.dump(fake_state, f)
    monkeypatch.setattr(state_registry, "_get_email_state_path", lambda: fake_path)

    result = state_registry.email_list_conversations()
    assert result[0]["status"] == "escalated"


def test_email_get_conversation_normalizes_role_and_text(monkeypatch, tmp_path):
    """Brief 171: customer → user, marina → assistant; body → text; ts → created_at."""
    fake_state = {
        "threads": {
            "subj:carol@x.com:question": {
                "fields": {"customer_name": "Carol"},
                "flags": {},
                "messages": [
                    {"role": "customer", "ts": "2026-04-09T09:00:00+00:00", "body": "hi"},
                    {"role": "marina", "ts": "2026-04-09T09:01:00+00:00", "body": "hello"},
                ],
            },
        }
    }
    fake_path = str(tmp_path / "email_thread_state.json")
    with open(fake_path, "w") as f:
        json.dump(fake_state, f)
    monkeypatch.setattr(state_registry, "_get_email_state_path", lambda: fake_path)

    result = state_registry.email_get_conversation("subj:carol@x.com:question")
    assert len(result["messages"]) == 2
    assert result["messages"][0]["role"] == "user"
    assert result["messages"][0]["text"] == "hi"
    assert result["messages"][0]["created_at"] == "2026-04-09T09:00:00+00:00"
    assert result["messages"][1]["role"] == "assistant"
    assert result["messages"][1]["text"] == "hello"


def test_dashboard_api_merges_email_conversations():
    """Source guard: api.py list_conversations calls email_list_conversations."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard", "api.py")
    src = open(path).read()
    assert "email_list_conversations" in src
    assert "email::" in src
    assert "email_get_conversation" in src
