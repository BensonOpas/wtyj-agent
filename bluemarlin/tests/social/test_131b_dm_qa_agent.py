# test_131b_dm_qa_agent.py
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
from shared import state_registry


def _make_dm_msg(conv_id="conv_131b", channel="instagram_dm", text="Hello",
                  sender_name="TestUser"):
    return {
        "conversation_id": conv_id,
        "platform": "instagram",
        "channel": channel,
        "sender_name": sender_name,
        "sender_id": "u1",
        "text": text,
        "message_id": f"msg_{conv_id}",
        "account_id": "acc_1",
    }


def _cleanup(conv_id):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (conv_id,))
    conn.commit()
    conn.close()


def _mock_anthropic_response(text="We have several boat trips!"):
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=text)]
    mock_resp.usage = MagicMock(input_tokens=100, output_tokens=50)
    return mock_resp


# --- Test 1: DM does NOT call marina_agent ---
@patch("agents.social.dm_agent.anthropic.Anthropic")
def test_dm_does_not_call_marina(mock_anthropic_cls):
    conv = "conv_131b_t1"
    _cleanup(conv)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_anthropic_response("We have boats!")
    mock_anthropic_cls.return_value = mock_client

    from agents.social.dm_agent import handle_incoming_dm
    with patch("agents.social.dm_agent.marina_agent.process_message", side_effect=Exception("Should not be called")) if hasattr(__import__("agents.social.dm_agent", fromlist=["dm_agent"]), "marina_agent") else patch.object(MagicMock(), "x"):
        # The new dm_agent doesn't import marina_agent at all
        reply = handle_incoming_dm(_make_dm_msg(conv_id=conv))
        assert reply == "We have boats!"
    _cleanup(conv)


# --- Test 2: Reply is plain text, not JSON ---
@patch("agents.social.dm_agent.anthropic.Anthropic")
def test_dm_reply_is_plain_text(mock_anthropic_cls):
    conv = "conv_131b_t2"
    _cleanup(conv)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_anthropic_response("Sure, the sunset service is on Fridays!")
    mock_anthropic_cls.return_value = mock_client

    from agents.social.dm_agent import handle_incoming_dm
    reply = handle_incoming_dm(_make_dm_msg(conv_id=conv, text="when is the sunset service?"))
    assert isinstance(reply, str)
    assert "{" not in reply
    assert "intents" not in reply
    _cleanup(conv)


# --- Test 3: Strips booking placeholders ---
@patch("agents.social.dm_agent.anthropic.Anthropic")
def test_dm_strips_booking_placeholders(mock_anthropic_cls):
    conv = "conv_131b_t3"
    _cleanup(conv)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_anthropic_response(
        "Your booking ref is [BOOKING_REF]. Pay here: [PAYMENT_LINK]"
    )
    mock_anthropic_cls.return_value = mock_client

    from agents.social.dm_agent import handle_incoming_dm
    reply = handle_incoming_dm(_make_dm_msg(conv_id=conv))
    assert "[BOOKING_REF]" not in reply
    assert "[PAYMENT_LINK]" not in reply
    assert len(reply) > 0  # Should still have some text left
    _cleanup(conv)


# --- Test 4: Prompt has service data from client.json ---
@patch("agents.social.dm_agent.anthropic.Anthropic")
def test_dm_prompt_has_trip_data(mock_anthropic_cls):
    conv = "conv_131b_t4"
    _cleanup(conv)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_anthropic_response("Great trips!")
    mock_anthropic_cls.return_value = mock_client

    from agents.social.dm_agent import handle_incoming_dm
    handle_incoming_dm(_make_dm_msg(conv_id=conv))

    # Check the system prompt passed to Claude
    call_args = mock_client.messages.create.call_args
    system_prompt = call_args[1]["system"]
    # Should contain service names from client.json
    assert "Klein" in system_prompt or "Snorkel" in system_prompt or "Jet Ski" in system_prompt
    _cleanup(conv)


# --- Test 5: Prompt has booking redirect with real values ---
@patch("agents.social.dm_agent.anthropic.Anthropic")
def test_dm_prompt_has_booking_redirect(mock_anthropic_cls):
    conv = "conv_131b_t5"
    _cleanup(conv)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_anthropic_response("Check WA!")
    mock_anthropic_cls.return_value = mock_client

    from agents.social.dm_agent import handle_incoming_dm
    handle_incoming_dm(_make_dm_msg(conv_id=conv))

    system_prompt = mock_client.messages.create.call_args[1]["system"]
    assert "wa.me/" in system_prompt
    assert "BOOKING REDIRECT" in system_prompt
    assert "@" in system_prompt  # email present
    _cleanup(conv)


# --- Test 6: Prompt has NO booking schema ---
@patch("agents.social.dm_agent.anthropic.Anthropic")
def test_dm_prompt_has_no_booking_schema(mock_anthropic_cls):
    conv = "conv_131b_t6"
    _cleanup(conv)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_anthropic_response("Hi!")
    mock_anthropic_cls.return_value = mock_client

    from agents.social.dm_agent import handle_incoming_dm
    handle_incoming_dm(_make_dm_msg(conv_id=conv))

    system_prompt = mock_client.messages.create.call_args[1]["system"]
    assert "booking_confirmed" not in system_prompt
    assert "awaiting_booking_confirmation" not in system_prompt
    assert "reply_hold_failed" not in system_prompt
    assert "BOOKING_REF" not in system_prompt
    _cleanup(conv)


# --- Test 7: Rate limiting ---
def test_dm_rate_limiting():
    conv = "conv_131b_t7"
    _cleanup(conv)
    for i in range(30):
        state_registry.dm_store_message(conv, "instagram_dm", "assistant", f"Reply {i}")

    from agents.social.dm_agent import handle_incoming_dm
    reply = handle_incoming_dm(_make_dm_msg(conv_id=conv))
    assert reply == ""
    _cleanup(conv)


# --- Test 8: Fallback on API error ---
def test_dm_fallback_on_api_error():
    conv = "conv_131b_t8"
    _cleanup(conv)
    old_key = os.environ.get("ANTHROPIC_API_KEY", "")
    os.environ["ANTHROPIC_API_KEY"] = ""
    try:
        from agents.social.dm_agent import handle_incoming_dm
        reply = handle_incoming_dm(_make_dm_msg(conv_id=conv))
        assert "give me a sec" in reply.lower() or "get back to you" in reply.lower()
    finally:
        os.environ["ANTHROPIC_API_KEY"] = old_key
    _cleanup(conv)


# --- Test 9: Marina WhatsApp still works (regression) ---
def test_marina_whatsapp_unchanged():
    from agents.marina.marina_agent import _build_prompt
    prompt = _build_prompt("123456", "", "Hello", {}, {},
                           channel="whatsapp", messages=[])
    assert "WHATSAPP" in prompt
    assert "booking_confirmed" in prompt.lower() or "BOOKING" in prompt


# --- Test 10: Marina has no DM-specific block (regression) ---
def test_marina_no_dm_channel():
    from agents.marina.marina_agent import _build_prompt
    prompt = _build_prompt("conv_1", "", "Hello", {}, {},
                           channel="instagram_dm", messages=[])
    # Should fall through to email style (no DM-specific block)
    assert "INSTAGRAM DM" not in prompt
    assert "BOOKING REDIRECT" not in prompt
    # Should have email-style writing
    assert "WRITING STYLE" in prompt
