# bluemarlin/tests/social/test_068_pipeline.py
# Created: Brief 068
# Purpose: Tests for WhatsApp message pipeline

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ["WHATSAPP_VERIFY_TOKEN"] = "test_token_067"
os.environ["WHATSAPP_ACCESS_TOKEN"] = "test_access_token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "990622044139349"

from agents.social.whatsapp_client import parse_webhook_payload, send_text_message
from agents.social.social_agent import handle_incoming_whatsapp_message
from shared import state_registry


# --- Real payload from production (2026-03-11) ---
REAL_TEXT_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "967346842390828",
        "changes": [{
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {
                    "display_phone_number": "15551681192",
                    "phone_number_id": "990622044139349"
                },
                "contacts": [{"profile": {"name": "Calvin Adamus"}, "wa_id": "59996881585"}],
                "messages": [{
                    "from": "59996881585",
                    "id": "wamid.TEST_DEDUP_001",
                    "timestamp": "1773265596",
                    "text": {"body": "Test"},
                    "type": "text"
                }]
            },
            "field": "messages"
        }]
    }]
}

STATUS_UPDATE_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "967346842390828",
        "changes": [{
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {"display_phone_number": "15551681192", "phone_number_id": "990622044139349"},
                "statuses": [{"id": "wamid.xxx", "status": "delivered", "timestamp": "123", "recipient_id": "59996881585"}]
            },
            "field": "messages"
        }]
    }]
}

IMAGE_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "967346842390828",
        "changes": [{
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {"display_phone_number": "15551681192", "phone_number_id": "990622044139349"},
                "contacts": [{"profile": {"name": "Calvin Adamus"}, "wa_id": "59996881585"}],
                "messages": [{
                    "from": "59996881585",
                    "id": "wamid.IMAGE_001",
                    "timestamp": "1773265600",
                    "image": {"mime_type": "image/jpeg", "sha256": "abc", "id": "img123"},
                    "type": "image"
                }]
            },
            "field": "messages"
        }]
    }]
}


# --- Parse tests ---

def test_parse_text_message():
    """Parse real text message payload into normalized object."""
    msgs = parse_webhook_payload(REAL_TEXT_PAYLOAD)
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg["channel"] == "whatsapp"
    assert msg["from"] == "59996881585"
    assert msg["from_name"] == "Calvin Adamus"
    assert msg["message_id"] == "wamid.TEST_DEDUP_001"
    assert msg["text"] == "Test"
    assert msg["message_type"] == "text"
    assert msg["timestamp"] == "1773265596"
    assert msg["business_account_id"] == "967346842390828"
    assert msg["phone_number_id"] == "990622044139349"


def test_parse_status_update_returns_empty():
    """Status updates (delivered, read) should not produce messages."""
    msgs = parse_webhook_payload(STATUS_UPDATE_PAYLOAD)
    assert msgs == []


def test_parse_image_message():
    """Non-text message parsed with text=None."""
    msgs = parse_webhook_payload(IMAGE_PAYLOAD)
    assert len(msgs) == 1
    assert msgs[0]["text"] is None
    assert msgs[0]["message_type"] == "image"
    assert msgs[0]["from"] == "59996881585"


def test_parse_empty_payload():
    """Empty or malformed payload returns empty list."""
    assert parse_webhook_payload({}) == []
    assert parse_webhook_payload({"entry": []}) == []
    assert parse_webhook_payload({"entry": [{"changes": []}]}) == []


# --- Dedup tests ---

def test_dedup_prevents_reprocessing():
    """Same message ID should be skipped on second processing."""
    test_id = "wamid.DEDUP_TEST_068"
    # Clean up if exists from previous test run
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_processed WHERE message_id = ?", (test_id,))
    conn.commit()
    conn.close()

    assert state_registry.wa_has_been_processed(test_id) is False
    state_registry.wa_mark_as_processed(test_id)
    assert state_registry.wa_has_been_processed(test_id) is True


# --- Agent stub tests ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_agent_returns_reply(mock_process):
    """Agent returns Claude-generated reply (mocked marina_agent)."""
    mock_process.return_value = {
        "intents": ["greeting"], "fields": {}, "confidence": "high",
        "reply": "Hi! How can I help?",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }
    msg = {"from": "59996881585", "text": "Hello", "from_name": "Test", "channel": "whatsapp"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == "Hi! How can I help?"


# --- Send tests ---

@patch("agents.social.whatsapp_client.urllib.request.urlopen")
def test_send_text_message_success(mock_urlopen):
    """send_text_message calls correct URL with correct body."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"messaging_product":"whatsapp","messages":[{"id":"wamid.ok"}]}'
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    result = send_text_message("59996881585", "Hello from test")
    assert result is True

    # Verify the request
    call_args = mock_urlopen.call_args
    req = call_args[0][0]
    assert "990622044139349" in req.full_url
    assert req.get_header("Authorization") == "Bearer test_access_token"
    body = json.loads(req.data)
    assert body["messaging_product"] == "whatsapp"
    assert body["to"] == "59996881585"
    assert body["text"]["body"] == "Hello from test"


@patch("agents.social.whatsapp_client.urllib.request.urlopen")
def test_send_text_message_failure(mock_urlopen):
    """send_text_message returns False on API error."""
    mock_urlopen.side_effect = Exception("Connection refused")
    result = send_text_message("59996881585", "Hello")
    assert result is False


# --- Integration test (mocked send) ---

def test_webhook_post_triggers_pipeline():
    """POST with text message triggers parse → agent → send (mocked)."""
    from fastapi.testclient import TestClient
    from agents.social.webhook_server import app

    client = TestClient(app)

    # Use a unique message ID to avoid dedup from other tests
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "967346842390828",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "15551681192", "phone_number_id": "990622044139349"},
                    "contacts": [{"profile": {"name": "Test User"}, "wa_id": "1234567890"}],
                    "messages": [{
                        "from": "1234567890",
                        "id": "wamid.INTEGRATION_TEST_068",
                        "timestamp": "1773265700",
                        "text": {"body": "Integration test"},
                        "type": "text"
                    }]
                },
                "field": "messages"
            }]
        }]
    }

    # Clean up dedup for this test
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_processed WHERE message_id = ?", ("wamid.INTEGRATION_TEST_068",))
    conn.commit()
    conn.close()

    with patch("agents.social.webhook_server.send_text_message") as mock_send, \
         patch("agents.social.webhook_server.handle_incoming_whatsapp_message", return_value="Test reply"):
        mock_send.return_value = True
        r = client.post("/webhooks/meta/whatsapp", json=payload)
        assert r.status_code == 200
        assert r.text == "OK"
        # BackgroundTasks run synchronously in TestClient
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args[1]["to"] == "1234567890" or call_args[0][0] == "1234567890"


# --- Existing Brief 067 tests still pass ---

def test_health_endpoint():
    """GET /health still returns ok."""
    from fastapi.testclient import TestClient
    from agents.social.webhook_server import app
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
