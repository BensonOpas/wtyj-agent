"""Tests for Brief 174 — Marina tool use migration.

Covers:
- MARINA_TOOL schema shape (required fields, enum constraints, all field coverage)
- process_message extracts tool_use input correctly
- process_message applies defaults for optional fields missing from tool_use
- process_message falls back on empty reply after defaults
- process_message falls back on Anthropic exception (unchanged behaviour)
- process_message falls back when no tool_use block returned (defensive guard)
"""
import os
from unittest.mock import patch, MagicMock

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from agents.marina import marina_agent


# --- Schema tests ---

def test_marina_tool_schema_has_required_fields():
    """Brief 174: the schema must mark intents, confidence, reply, requires_human as required."""
    schema = marina_agent.MARINA_TOOL
    assert schema["name"] == "marina_response"
    required = schema["input_schema"]["required"]
    assert set(required) == {"intents", "confidence", "reply", "requires_human"}


def test_marina_tool_schema_intents_enum():
    """Brief 174: intents field must restrict to the known intent labels."""
    schema = marina_agent.MARINA_TOOL
    intents_prop = schema["input_schema"]["properties"]["intents"]
    assert intents_prop["type"] == "array"
    assert set(intents_prop["items"]["enum"]) == {
        "booking", "inquiry", "cancellation", "reschedule",
        "complaint", "social", "off_topic",
    }


def test_marina_tool_schema_confidence_enum():
    schema = marina_agent.MARINA_TOOL
    conf_prop = schema["input_schema"]["properties"]["confidence"]
    assert set(conf_prop["enum"]) == {"high", "medium", "low"}


def test_marina_tool_schema_has_all_fields_from_old_format():
    """Brief 174: schema properties must cover every field the old JSON format emitted.
    If a field is missing from the schema, Marina cannot emit it — breaks downstream code."""
    props = marina_agent.MARINA_TOOL["input_schema"]["properties"]
    expected_top_level = {
        "intents", "fields", "confidence", "reply", "reply_hold_failed",
        "clarifications_needed", "requires_human", "flags",
        "semi_escalation", "relay_question", "internal_note",
    }
    assert expected_top_level.issubset(set(props.keys()))
    field_props = props["fields"]["properties"]
    expected_fields = {
        "service_name", "service_key", "date", "guests",
        "customer_name", "phone", "email", "special_requests", "slot_time",
    }
    assert expected_fields.issubset(set(field_props.keys()))
    flag_props = props["flags"]["properties"]
    expected_flags = {
        "booking_confirmed", "awaiting_booking_confirmation",
        "needs_child_ages", "needs_escalation_email", "large_group",
    }
    assert expected_flags.issubset(set(flag_props.keys()))


# --- process_message integration tests ---

def _mock_tool_use_response(tool_input, output_tokens=100):
    """Build a MagicMock that looks like an Anthropic response with a single tool_use block."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "marina_response"
    tool_block.input = tool_input

    resp = MagicMock()
    resp.content = [tool_block]
    resp.usage = MagicMock(input_tokens=500, output_tokens=output_tokens)
    resp.stop_reason = "tool_use"
    return resp


@patch("agents.marina.marina_agent.anthropic.Anthropic")
def test_process_message_extracts_tool_use_input(mock_cls):
    """Brief 174: process_message returns the tool_use input dict directly."""
    mock_resp = _mock_tool_use_response({
        "intents": ["inquiry"],
        "fields": {"customer_name": "Alice"},
        "confidence": "high",
        "reply": "Hello Alice! How can I help?",
        "clarifications_needed": [],
        "requires_human": False,
        "flags": {},
        "internal_note": "Greeting",
    })
    mock_cls.return_value.messages.create.return_value = mock_resp

    result = marina_agent.process_message("alice@test.com", "Hi", "Hello", {}, {})
    assert result["reply"] == "Hello Alice! How can I help?"
    assert result["intents"] == ["inquiry"]
    assert result["fields"]["customer_name"] == "Alice"


@patch("agents.marina.marina_agent.anthropic.Anthropic")
def test_process_message_defaults_missing_optional_fields(mock_cls):
    """Brief 174: if Claude's tool_use omits an optional field (like 'clarifications_needed'),
    process_message defaults it via _RESPONSE_DEFAULTS. Claude only has to fill required fields."""
    mock_resp = _mock_tool_use_response({
        "intents": ["inquiry"],
        "confidence": "high",
        "reply": "Our trips run daily.",
        "requires_human": False,
        # No 'fields', 'flags', 'internal_note', or 'clarifications_needed'
    })
    mock_cls.return_value.messages.create.return_value = mock_resp

    result = marina_agent.process_message("x@y.com", "Hi", "When do you run?", {}, {})
    # Required field preserved
    assert result["reply"] == "Our trips run daily."
    # Optional fields defaulted
    assert result["fields"] == {}
    assert result["flags"] == {}
    assert result["clarifications_needed"] == []
    assert result["internal_note"] == ""


@patch("agents.marina.marina_agent.anthropic.Anthropic")
def test_process_message_falls_back_on_empty_reply(mock_cls):
    """Brief 174: if the tool_use has an empty reply field (even though it's required),
    process_message returns the fallback — an empty reply is useless to the customer."""
    mock_resp = _mock_tool_use_response({
        "intents": ["inquiry"],
        "confidence": "low",
        "reply": "",  # empty
        "requires_human": False,
    })
    mock_cls.return_value.messages.create.return_value = mock_resp

    result = marina_agent.process_message("x@y.com", "Hi", "hello", {}, {})
    # Fallback reply (email default from fallback dict)
    assert "service" in result["reply"].lower() or "guests" in result["reply"].lower()


@patch("agents.marina.marina_agent.anthropic.Anthropic")
def test_process_message_falls_back_on_anthropic_exception(mock_cls):
    """Brief 174: preserve the existing behaviour where an API exception triggers fallback."""
    mock_cls.return_value.messages.create.side_effect = Exception("API down")
    result = marina_agent.process_message("x@y.com", "Hi", "hello", {}, {})
    assert result["intents"] == ["inquiry"]
    # Email channel fallback
    assert "service" in result["reply"].lower() or "guests" in result["reply"].lower()


@patch("agents.marina.marina_agent.anthropic.Anthropic")
def test_process_message_falls_back_when_no_tool_use_block(mock_cls):
    """Brief 174: defensive — if Claude somehow returns a text block instead of tool_use
    (shouldn't happen with tool_choice forced, but guard the code path)."""
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "some text"
    resp = MagicMock()
    resp.content = [text_block]
    resp.usage = MagicMock(input_tokens=500, output_tokens=50)
    mock_cls.return_value.messages.create.return_value = resp

    result = marina_agent.process_message("x@y.com", "Hi", "hello", {}, {})
    # Fallback fires, no crash
    assert result["internal_note"] == "Fallback response — Claude API call failed or returned unparseable output."
