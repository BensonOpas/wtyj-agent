# tests/test_marina_tone.py
# Brief 060 — Marina Tone v2: system/user split + template rewrites

import sys
import os
from agents.marina import marina_agent
from shared import config_loader
# Brief 161: _build_booking_summary deleted — Marina writes summaries herself now.


def test_system_prompt_contains_writing_style():
    """T1: _build_system_prompt contains WRITING STYLE section."""
    sp = marina_agent._build_system_prompt({})
    assert "WRITING STYLE:" in sp


def test_system_prompt_contains_example_replies():
    """T2: _build_system_prompt contains tone reference examples."""
    sp = marina_agent._build_system_prompt({})
    assert "tone reference" in sp


def test_user_prompt_contains_inbound_message():
    """T4: _build_user_prompt contains INBOUND MESSAGE and body."""
    up = marina_agent._build_user_prompt("a@b.com", "test", "hello world", {}, {})
    assert "INBOUND MESSAGE:" in up
    assert "hello world" in up


def test_user_prompt_contains_trips_and_faq():
    """T5: _build_user_prompt contains TRIPS and FAQ sections."""
    up = marina_agent._build_user_prompt("a@b.com", "test", "hi", {}, {})
    assert "SERVICES" in up or "services" in up.lower()
    assert "FAQ" in up


def test_build_prompt_wrapper_combines_both():
    """T6: _build_prompt wrapper contains content from both system and user prompts."""
    full = marina_agent._build_prompt("a@b.com", "test", "hi", {}, {})
    assert "WRITING STYLE:" in full
    assert "INBOUND MESSAGE:" in full


# Brief 161: Tests T7-T11 deleted — _build_booking_summary removed, Marina writes
# booking summaries in the customer's language via her prompt now. The old
# hardcoded English template tests are no longer applicable.


def test_persona_in_client_json():
    """T12: marina_persona in client.json has core persona traits."""
    persona = config_loader.get_common_sense_knowledge().get("marina_persona", "")
    assert "warm" in persona
    assert "mirrors" in persona
    assert "never guesses" in persona or "never overexplains" in persona


def test_whatsapp_prompt_never_empty_rule():
    """T13: WhatsApp prompt contains the never-empty-reply rule."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "NEVER return an empty reply" in prompt


def test_response_defaults_missing_fields():
    """T14: process_message defaults missing fields instead of rejecting.
    Brief 174: mock updated to return tool_use block with sparse input."""
    from unittest.mock import patch, MagicMock
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "marina_response"
    tool_block.input = {
        "intents": ["inquiry"], "fields": {}, "confidence": "high",
        "reply": "We do boat trips!", "clarifications_needed": [],
        "requires_human": False,
        # No 'flags' or 'internal_note' — defaults should fill them
    }
    mock_response = MagicMock()
    mock_response.content = [tool_block]
    mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
    with patch("agents.marina.marina_agent.anthropic.Anthropic") as mock_client:
        mock_client.return_value.messages.create.return_value = mock_response
        result = marina_agent.process_message("test", "", "hello", {}, {})
    assert result["reply"] == "We do boat trips!"
    assert result["flags"] == {}
    assert result["internal_note"] == ""


def test_response_empty_reply_returns_fallback():
    """T15: process_message returns fallback when reply is empty, even if other fields present.
    Brief 174: mock updated to return tool_use block."""
    from unittest.mock import patch, MagicMock
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "marina_response"
    tool_block.input = {
        "intents": ["inquiry"], "fields": {}, "confidence": "high",
        "reply": "", "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": "",
    }
    mock_response = MagicMock()
    mock_response.content = [tool_block]
    mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
    with patch("agents.marina.marina_agent.anthropic.Anthropic") as mock_client:
        mock_client.return_value.messages.create.return_value = mock_response
        result = marina_agent.process_message("test", "", "hello", {}, {})
    # Email fallback should fire — non-empty reply
    assert "service" in result["reply"].lower() or "guests" in result["reply"].lower()


def test_client_context_includes_all_sections():
    """T16: All customer-facing client.json sections appear in the prompt,
    except those in marina_agent._SKIP_TOP_LEVEL which are injected elsewhere
    (service_aliases via _build_service_alias_text, agent_persona via
    _build_agent_persona_block — Brief 149)."""
    from shared import config_loader
    raw = config_loader.get_raw()
    prompt = marina_agent._build_user_prompt("test@test.com", "Test", "Hello", {}, {})
    # Every top-level key (except skipped ones) should have a section
    for key in raw:
        if key in marina_agent._SKIP_TOP_LEVEL:
            continue
        section_header = key.upper().replace("_", " ")
        assert section_header in prompt, f"Section '{section_header}' missing from prompt (key: {key})"


def test_client_context_excludes_internal_keys():
    """T17: Internal keys (calendar_id, spreadsheet_id) are not in the prompt."""
    prompt = marina_agent._build_user_prompt("test@test.com", "Test", "Hello", {}, {})
    assert "spreadsheet_id" not in prompt.lower()
    assert "calendar_id" not in prompt.lower()
    assert "demo_support_email" not in prompt.lower()


def test_client_context_no_duplicate_aliases():
    """T18: service_aliases not duplicated in user prompt (already in system prompt)."""
    prompt = marina_agent._build_user_prompt("test@test.com", "Test", "Hello", {}, {})
    assert "TRIP ALIASES" not in prompt


if __name__ == "__main__":
    tests = [
        test_system_prompt_contains_writing_style,
        test_system_prompt_contains_example_replies,
        test_user_prompt_contains_inbound_message,
        test_user_prompt_contains_trips_and_faq,
        test_build_prompt_wrapper_combines_both,
        test_persona_in_client_json,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__} — {e}")
    print(f"\n{passed}/{len(tests)} tests passed.")
