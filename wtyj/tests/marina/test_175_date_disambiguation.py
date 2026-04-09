"""Tests for Brief 175 — Marina date disambiguation ('next [day]' semantic fix)."""
import os
from unittest.mock import patch, MagicMock

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from agents.marina import marina_agent


# --- Prompt content tests ---

def test_system_prompt_has_date_ambiguity_rule():
    """Brief 175: the system prompt must contain the DATE AMBIGUITY RESOLUTION block."""
    prompt = marina_agent._build_system_prompt({}, channel="email")
    assert "DATE AMBIGUITY RESOLUTION" in prompt
    assert "NEAREST upcoming instance" in prompt
    assert "state your interpretation inline" in prompt


def test_system_prompt_has_next_saturday_example():
    """Brief 175: the rule must include a Thursday → 'next Saturday' = 2 days away
    example, since that's the exact ambiguity Anne-Sophie hit."""
    prompt = marina_agent._build_system_prompt({}, channel="email")
    assert "next Saturday" in prompt
    assert "2 days away" in prompt or "coming Saturday" in prompt


# --- Integration test: Anne-Sophie scenario with correct date ---

def _mock_tool_use_response(tool_input, output_tokens=100):
    """Build a MagicMock Anthropic response containing a single tool_use block."""
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
def test_ash9772_replay_with_corrected_date(mock_cls):
    """Brief 175: replay Anne-Sophie's message with a mocked Claude that resolves
    'next Saturday' correctly (as April 11, not April 18). Verify the dict flows
    through process_message with the correct date and the inline confirmation
    phrasing in the reply."""
    mock_resp = _mock_tool_use_response({
        "intents": ["booking"],
        "fields": {
            "service_name": "Klein Curaçao Trip",
            "service_key": "klein_curacao",
            "date": "2026-04-11",
            "guests": 7,
            "customer_name": "Anne-Sophie Hammar",
            "email": "ash9772@gmail.com",
            "phone": "+599 9 686 5664",
        },
        "confidence": "high",
        "reply": (
            "The Klein Curaçao Trip runs daily, so Saturday April 11 works. "
            "I'm reading 'next Saturday' as this coming Saturday (April 11) — "
            "let me know if you meant a different date. "
            "There are two departures from Jan Thiel Beach: 08:00 aboard "
            "BlueMarlin 2, 08:30 aboard BlueMarlin 1. Which works better?"
        ),
        "clarifications_needed": ["Which departure time?"],
        "requires_human": False,
        "flags": {},
        "internal_note": "Resolved 'next Saturday' as April 11 (nearest upcoming).",
    })
    mock_cls.return_value.messages.create.return_value = mock_resp

    result = marina_agent.process_message(
        "ash9772@gmail.com", "Re: Request",
        "Next Saturday and the trip to Klein curacao",
        {}, {}, channel="email",
    )
    assert result["fields"]["date"] == "2026-04-11"
    assert result["fields"]["service_key"] == "klein_curacao"
    assert result["fields"]["guests"] == 7
    assert "April 11" in result["reply"]
    assert "let me know" in result["reply"].lower() or "shout if" in result["reply"].lower()
