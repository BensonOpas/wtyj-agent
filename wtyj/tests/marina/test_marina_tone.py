# tests/test_marina_tone.py
# Brief 060 — Marina Tone v2: system/user split + template rewrites

import sys
import os
from agents.marina import marina_agent
from shared import config_loader
from agents.marina.email_poller import _build_booking_summary


def test_system_prompt_contains_writing_style():
    """T1: _build_system_prompt contains WRITING STYLE section."""
    sp = marina_agent._build_system_prompt({})
    assert "WRITING STYLE:" in sp


def test_system_prompt_contains_example_replies():
    """T2: _build_system_prompt contains tone reference examples."""
    sp = marina_agent._build_system_prompt({})
    assert "tone reference" in sp


def test_system_prompt_contains_json_format():
    """T3: _build_system_prompt contains JSON format spec."""
    sp = marina_agent._build_system_prompt({})
    assert '"intents"' in sp
    assert '"reply"' in sp


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


def test_booking_summary_no_old_header():
    """T7: Booking summary does NOT contain old bullet-point header."""
    service = {
        "display_name": "Sunset Cruise",
        "slots": [{"time": "17:30", "resource": "Kailani", "location": "Village Marina"}],
        "price": 79,
        "included": ["open bar", "snacks"],
    }
    summary = _build_booking_summary(
        {"service_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "slot_time": "17:30"},
        service,
    )
    assert "Here's a quick summary" not in summary


def test_booking_summary_no_old_lock_phrase():
    """T8: Booking summary does NOT contain old lock-in phrase."""
    service = {
        "display_name": "Sunset Cruise",
        "slots": [{"time": "17:30", "resource": "Kailani", "location": "Village Marina"}],
        "price": 79,
        "included": ["open bar", "snacks"],
    }
    summary = _build_booking_summary(
        {"service_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "slot_time": "17:30"},
        service,
    )
    assert "Shall I lock this in" not in summary


def test_booking_summary_has_price():
    """T9: Booking summary contains exact prices."""
    service = {
        "display_name": "Sunset Cruise",
        "slots": [{"time": "17:30", "resource": "Kailani", "location": "Village Marina"}],
        "price": 79,
        "included": ["open bar", "snacks"],
    }
    summary = _build_booking_summary(
        {"service_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "slot_time": "17:30"},
        service,
    )
    assert "$158" in summary
    assert "$79" in summary


def test_booking_summary_new_closer():
    """T10: Booking summary contains the new closer phrase."""
    service = {
        "display_name": "Sunset Cruise",
        "slots": [{"time": "17:30", "resource": "Kailani", "location": "Village Marina"}],
        "price": 79,
        "included": ["open bar", "snacks"],
    }
    summary = _build_booking_summary(
        {"service_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "slot_time": "17:30"},
        service,
    )
    assert "Want me to go ahead and book this?" in summary


def test_post_validate_day_of_week_no_em_dashes():
    """T11: Day-of-week override has no em dashes or old phrasing."""
    from agents.marina.email_poller import _post_validate
    th = {"fields": {"service_name": "Snorkeling", "date": "2026-03-09", "guests": "2", "service_key": "snorkeling_3in1"}, "flags": {}}
    service = {"display_name": "3-in-1 Snorkeling Trip", "slots": [{"time": "10:00"}], "days_available": "Fridays only"}
    result = {"intents": ["booking"], "fields": {}, "flags": {}}
    override, _ = _post_validate(th, result, service)
    assert override is not None
    assert "—" not in override
    assert "Great choice" not in override


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
    """T14: process_message defaults missing fields instead of rejecting."""
    from unittest.mock import patch, MagicMock
    # Simulate Claude returning valid JSON missing flags and internal_note
    incomplete_json = '{"intents": ["inquiry"], "fields": {}, "confidence": "high", ' \
                      '"reply": "We do boat trips!", "clarifications_needed": [], "requires_human": false}'
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=incomplete_json)]
    mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
    with patch("agents.marina.marina_agent.anthropic.Anthropic") as mock_client:
        mock_client.return_value.messages.create.return_value = mock_response
        result = marina_agent.process_message("test", "", "hello", {}, {})
    assert result["reply"] == "We do boat trips!"
    assert result["flags"] == {}
    assert result["internal_note"] == ""


def test_response_empty_reply_returns_fallback():
    """T15: process_message returns fallback when reply is empty, even if other fields present."""
    from unittest.mock import patch, MagicMock
    # Simulate Claude returning valid JSON with empty reply
    empty_reply_json = '{"intents": ["inquiry"], "fields": {}, "confidence": "high", ' \
                       '"reply": "", "clarifications_needed": [], "requires_human": false, ' \
                       '"flags": {}, "internal_note": ""}'
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=empty_reply_json)]
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
        test_system_prompt_contains_json_format,
        test_user_prompt_contains_inbound_message,
        test_user_prompt_contains_trips_and_faq,
        test_build_prompt_wrapper_combines_both,
        test_booking_summary_no_old_header,
        test_booking_summary_no_old_lock_phrase,
        test_booking_summary_has_price,
        test_booking_summary_new_closer,
        test_post_validate_day_of_week_no_em_dashes,
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
