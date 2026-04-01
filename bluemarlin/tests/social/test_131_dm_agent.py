# test_131_dm_agent.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test-secret")

from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from agents.social.dm_agent import handle_incoming_dm
from agents.marina.marina_agent import _build_prompt
from shared import state_registry


def _make_dm_msg(conv_id="conv_test", channel="instagram_dm", text="Hello",
                  sender_name="Test User", account_id="acc_123"):
    return {
        "conversation_id": conv_id,
        "platform": "instagram" if "instagram" in channel else "facebook",
        "channel": channel,
        "sender_name": sender_name,
        "sender_id": "user_1",
        "text": text,
        "message_id": f"msg_{conv_id}",
        "account_id": account_id,
    }


def _cleanup(conv_id):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (conv_id,))
    conn.commit()
    conn.close()


# --- Test 1: handle_dm calls marina with correct channel ---
@patch("agents.social.dm_agent.marina_agent.process_message")
def test_handle_dm_calls_marina(mock_process):
    conv = "conv_131_t1"
    _cleanup(conv)
    mock_process.return_value = {
        "intents": ["inquiry"], "fields": {}, "confidence": "high",
        "reply": "We have several boat trips!", "clarifications_needed": [],
        "requires_human": False, "flags": {}, "internal_note": ""
    }
    msg = _make_dm_msg(conv_id=conv, channel="instagram_dm", text="What trips?")
    reply = handle_incoming_dm(msg)

    assert reply == "We have several boat trips!"
    mock_process.assert_called_once()
    call_kwargs = mock_process.call_args
    assert call_kwargs[1]["channel"] == "instagram_dm"
    assert call_kwargs[1]["body"] == "What trips?"
    _cleanup(conv)


# --- Test 2: Facebook DM channel passed correctly ---
@patch("agents.social.dm_agent.marina_agent.process_message")
def test_handle_dm_facebook_channel(mock_process):
    conv = "conv_131_t2"
    _cleanup(conv)
    mock_process.return_value = {
        "intents": ["inquiry"], "fields": {}, "confidence": "high",
        "reply": "Hi from Marina!", "clarifications_needed": [],
        "requires_human": False, "flags": {}, "internal_note": ""
    }
    msg = _make_dm_msg(conv_id=conv, channel="facebook_dm")
    reply = handle_incoming_dm(msg)

    assert reply == "Hi from Marina!"
    assert mock_process.call_args[1]["channel"] == "facebook_dm"
    _cleanup(conv)


# --- Test 3: History included in marina call ---
@patch("agents.social.dm_agent.marina_agent.process_message")
def test_handle_dm_includes_history(mock_process):
    conv = "conv_131_t3"
    _cleanup(conv)
    # Store some history first
    state_registry.dm_store_message(conv, "instagram_dm", "user", "What trips?", "Alice")
    state_registry.dm_store_message(conv, "instagram_dm", "assistant", "We have boats!")

    mock_process.return_value = {
        "intents": ["inquiry"], "fields": {}, "confidence": "high",
        "reply": "The sunset cruise is great!", "clarifications_needed": [],
        "requires_human": False, "flags": {}, "internal_note": ""
    }
    msg = _make_dm_msg(conv_id=conv, channel="instagram_dm", text="Which one?")
    handle_incoming_dm(msg)

    call_kwargs = mock_process.call_args[1]
    messages = call_kwargs["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["text"] == "What trips?"
    assert messages[1]["role"] == "assistant"
    _cleanup(conv)


# --- Test 4: Rate limited after 30 replies ---
def test_handle_dm_rate_limited():
    conv = "conv_131_t4"
    _cleanup(conv)
    # Store 30 assistant messages (recent)
    for i in range(30):
        state_registry.dm_store_message(conv, "instagram_dm", "assistant", f"Reply {i}")

    msg = _make_dm_msg(conv_id=conv, channel="instagram_dm", text="One more?")
    with patch("agents.social.dm_agent.marina_agent.process_message") as mock_process:
        reply = handle_incoming_dm(msg)
        # Should be rate limited — marina not called
        mock_process.assert_not_called()
        assert reply == ""
    _cleanup(conv)


# --- Test 5: Empty reply from marina ---
@patch("agents.social.dm_agent.marina_agent.process_message")
def test_handle_dm_empty_reply(mock_process):
    conv = "conv_131_t5"
    _cleanup(conv)
    mock_process.return_value = {
        "intents": ["inquiry"], "fields": {}, "confidence": "low",
        "reply": "", "clarifications_needed": [],
        "requires_human": False, "flags": {}, "internal_note": ""
    }
    msg = _make_dm_msg(conv_id=conv, text="...")
    reply = handle_incoming_dm(msg)
    assert reply == ""
    _cleanup(conv)


# --- Test 6: Marina exception doesn't crash ---
@patch("agents.social.dm_agent.marina_agent.process_message")
def test_handle_dm_api_failure(mock_process):
    conv = "conv_131_t6"
    _cleanup(conv)
    mock_process.side_effect = Exception("API timeout")
    msg = _make_dm_msg(conv_id=conv, text="Hello")
    reply = handle_incoming_dm(msg)
    assert reply == ""
    _cleanup(conv)


# --- Test 7: DM prompt has correct writing style ---
def test_prompt_has_dm_writing_style():
    prompt = _build_prompt("conv_1", "", "Hello", {}, {},
                           channel="instagram_dm", messages=[])
    assert "INSTAGRAM DM" in prompt
    assert "BOOKING REQUESTS" in prompt
    assert "wa.me/" in prompt


# --- Test 8: DM prompt has booking redirect with real values ---
def test_prompt_has_booking_redirect():
    prompt = _build_prompt("conv_1", "", "I want to book", {}, {},
                           channel="instagram_dm", messages=[])
    # Should contain WhatsApp number from client.json
    assert "wa.me/" in prompt
    # Should contain email from client.json business section
    assert "@" in prompt  # email address present
    # Should NOT have empty redirect
    assert "or email  —" not in prompt


# --- Test 9: WhatsApp prompt unchanged (regression) ---
def test_prompt_whatsapp_unchanged():
    prompt = _build_prompt("123456", "", "Hello", {}, {},
                           channel="whatsapp", messages=[])
    assert "BOOKING REQUESTS" not in prompt
    assert "wa.me/" not in prompt
    assert "WHATSAPP" in prompt


# --- Test 10: DM fallback reply on API failure ---
def test_dm_fallback_reply():
    from agents.marina.marina_agent import process_message
    old_key = os.environ.get("ANTHROPIC_API_KEY", "")
    os.environ["ANTHROPIC_API_KEY"] = ""
    try:
        result = process_message(
            from_email="conv_1", subject="", body="Hello",
            thread_fields={}, thread_flags={},
            channel="instagram_dm"
        )
        assert result["reply"] != ""  # Should return fallback, not empty
        assert "give me a moment" in result["reply"].lower()
    finally:
        os.environ["ANTHROPIC_API_KEY"] = old_key
