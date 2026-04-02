# test_125_escalation_reply.py
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


# --- Test 1: Rewrite mode includes draft_text in prompt ---
@patch("dashboard.api.anthropic")
def test_rewrite_mode(mock_anthropic_module):
    from shared import state_registry
    phone = "125_rewrite_phone"
    state_registry.wa_store_message(phone, "user", "Can I bring my dog?")

    mock_client = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"subject": "Pet Policy", "body": "Hi there, unfortunately pets are not allowed on our boats for safety reasons.\\n\\nMarina\\nBlueFinn Charters"}')]
    mock_client.messages.create.return_value = mock_response

    token = _login()
    r = client.post("/dashboard/api/messages/suggest-reply",
                     json={"phone": phone, "draft_text": "no dogs allowed sorry"},
                     headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data["subject"] == "Pet Policy"

    call_args = mock_client.messages.create.call_args
    user_msg = call_args.kwargs["messages"][0]["content"]
    assert "no dogs allowed sorry" in user_msg
    assert "Rewrite this draft" in user_msg

    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


# --- Test 2: Generate mode (no draft_text) writes from scratch ---
@patch("dashboard.api.anthropic")
def test_generate_mode(mock_anthropic_module):
    from shared import state_registry
    phone = "125_generate_phone"
    state_registry.wa_store_message(phone, "user", "Hello")

    mock_client = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"subject": "Welcome", "body": "Hi!"}')]
    mock_client.messages.create.return_value = mock_response

    token = _login()
    r = client.post("/dashboard/api/messages/suggest-reply",
                     json={"phone": phone},
                     headers=_auth(token))
    assert r.status_code == 200

    call_args = mock_client.messages.create.call_args
    user_msg = call_args.kwargs["messages"][0]["content"]
    assert "Write an email reply" in user_msg
    assert "Rewrite this draft" not in user_msg

    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


# --- Test 3: Escalation reply sends WhatsApp message ---
@patch("dashboard.api.wa_send_text_message")
@patch("dashboard.api.marina_agent")
def test_escalation_reply_sends_whatsapp(mock_marina, mock_wa_send):
    from shared import state_registry
    phone = "125_relay_phone"

    state_registry.wa_store_message(phone, "user", "What is the weight limit?")
    state_registry.wa_save_booking_state(phone, {"customer_name": "Test"}, {"awaiting_relay": True, "relay_token": "abc123"})
    esc_id = state_registry.create_pending_notification(
        notification_type="relay", channel="whatsapp",
        customer_id=phone, customer_name="Test",
        subject="[RELAY-abc123] test", body="Question: weight limit",
        relay_token="abc123"
    )

    mock_marina.process_message.return_value = {
        "reply": "Great question! The weight limit is 150kg per person.",
        "intents": ["inquiry"], "fields": {}, "flags": {},
        "confidence": "high", "requires_human": False,
        "clarifications_needed": [], "internal_note": ""
    }

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/reply",
                     json={"answer": "weight limit is 150kg"},
                     headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "150kg" in data["reply"]

    mock_wa_send.assert_called_once()
    assert mock_wa_send.call_args.kwargs["to"] == phone

    escs = state_registry.get_all_escalations()
    esc = next((e for e in escs if e["id"] == esc_id), None)
    assert esc["status"] == "replied"

    wa_state = state_registry.wa_get_booking_state(phone)
    assert wa_state["flags"].get("awaiting_relay") is None

    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM pending_notifications WHERE id = ?", (esc_id,))
    conn.commit()
    conn.close()


# --- Test 4: Empty answer returns 400 ---
def test_empty_answer():
    token = _login()
    r = client.post("/dashboard/api/escalations/999/reply",
                     json={"answer": "   "},
                     headers=_auth(token))
    assert r.status_code == 400


# --- Test 5: Non-existent escalation returns 404 ---
def test_escalation_not_found():
    token = _login()
    r = client.post("/dashboard/api/escalations/99999/reply",
                     json={"answer": "test"},
                     headers=_auth(token))
    assert r.status_code == 404
