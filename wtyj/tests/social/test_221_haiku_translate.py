# test_221_haiku_translate.py
# Brief 221: /ai-editor uses Haiku for action="translate" (cost reduction
# now that SR's frontend wires operator message-read translation through
# the same endpoint). action="fix" and action="style" stay on Sonnet
# because they touch operator-authored drafts where brand voice matters.
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


# --- Test 1: action="translate" routes to Haiku
@patch("dashboard.api.anthropic")
def test_ai_editor_translate_uses_haiku(mock_anthropic_module):
    mock_client = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Hello friend")]
    mock_client.messages.create.return_value = mock_response

    token = _login()
    r = client.post(
        "/dashboard/api/ai-editor",
        json={"action": "translate", "text": "Hola amigo", "targetLanguage": "English"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "Hello friend"

    call = mock_client.messages.create.call_args
    assert call.kwargs["model"] == "claude-haiku-4-5-20251001", (
        f"translate must route to Haiku, got: {call.kwargs.get('model')!r}"
    )


# --- Test 2: action="fix" stays on Sonnet (regression guard)
@patch("dashboard.api.anthropic")
def test_ai_editor_fix_still_uses_sonnet(mock_anthropic_module):
    mock_client = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="I have a draft.")]
    mock_client.messages.create.return_value = mock_response

    token = _login()
    r = client.post(
        "/dashboard/api/ai-editor",
        json={"action": "fix", "text": "i has a draft"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text

    call = mock_client.messages.create.call_args
    assert call.kwargs["model"] == "claude-sonnet-4-6", (
        f"fix must stay on Sonnet (brand-voice path), got: {call.kwargs.get('model')!r}"
    )


# --- Test 3: action="style" stays on Sonnet (regression guard)
@patch("dashboard.api.anthropic")
def test_ai_editor_style_still_uses_sonnet(mock_anthropic_module):
    mock_client = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Warmer rewrite.")]
    mock_client.messages.create.return_value = mock_response

    token = _login()
    r = client.post(
        "/dashboard/api/ai-editor",
        json={"action": "style", "text": "Hi.", "style": "warmer"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text

    call = mock_client.messages.create.call_args
    assert call.kwargs["model"] == "claude-sonnet-4-6", (
        f"style must stay on Sonnet (brand-voice path), got: {call.kwargs.get('model')!r}"
    )
