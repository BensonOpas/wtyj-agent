# test_119_suggest_reply.py
# Tests for Brief 119 — Suggest email reply endpoint

import sys, os
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


# --- Test 1: Missing phone returns 400 ---
def test_missing_phone():
    token = _login()
    r = client.post("/dashboard/api/messages/suggest-reply",
                     json={"phone": ""},
                     headers=_auth(token))
    assert r.status_code == 400


# --- Test 2: Unknown phone returns 404 ---
def test_unknown_phone():
    token = _login()
    r = client.post("/dashboard/api/messages/suggest-reply",
                     json={"phone": "0000000000"},
                     headers=_auth(token))
    assert r.status_code == 404


# --- Test 3: No auth returns 401 ---
def test_no_auth():
    r = client.post("/dashboard/api/messages/suggest-reply",
                     json={"phone": "1234567890"})
    assert r.status_code == 401


# --- Test 4: Successful suggestion with mocked Claude ---
@patch("dashboard.api.anthropic")
def test_suggest_reply_success(mock_anthropic_module):
    from shared import state_registry
    phone = "119_test_phone"

    # Seed conversation
    state_registry.wa_store_message(phone, "user", "Hi, I want to book the sunset cruise for 2 people")
    state_registry.wa_store_message(phone, "assistant", "The Sunset Cruise runs daily at 17:30. Price is $65/person. Which date works?")
    state_registry.wa_store_message(phone, "user", "This Friday please")

    # Mock Claude response
    mock_client = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"subject": "Sunset Cruise \u2014 Friday Booking", "body": "Hi there,\\n\\nGreat choice! I\'ve got you down for the Sunset Cruise this Friday at 17:30 for 2 guests.\\n\\nMarina\\nBlueFinn Charters Cura\u00e7ao"}')]
    mock_client.messages.create.return_value = mock_response

    token = _login()
    r = client.post("/dashboard/api/messages/suggest-reply",
                     json={"phone": phone},
                     headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data["subject"] == "Sunset Cruise \u2014 Friday Booking"
    assert "Marina" in data["body"]
    assert "BlueFinn" in data["body"]

    # Verify Claude was called with conversation context
    call_args = mock_client.messages.create.call_args
    assert call_args is not None
    user_msg = call_args.kwargs.get("messages", [{}])[0].get("content", "")
    assert "sunset cruise" in user_msg.lower()
    assert "Friday" in user_msg

    # Cleanup
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


# --- Test 5: JSON parse failure falls back gracefully ---
@patch("dashboard.api.anthropic")
def test_suggest_reply_json_fallback(mock_anthropic_module):
    from shared import state_registry
    phone = "119_fallback_phone"

    state_registry.wa_store_message(phone, "user", "Hello")

    # Mock Claude returning non-JSON
    mock_client = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Hi there, thanks for reaching out! Let me help you.")]
    mock_client.messages.create.return_value = mock_response

    token = _login()
    r = client.post("/dashboard/api/messages/suggest-reply",
                     json={"phone": phone},
                     headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert "subject" in data
    assert "body" in data
    # Fallback: body should contain the raw text
    assert "thanks for reaching out" in data["body"].lower()

    # Cleanup
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()
