"""Tests for Brief 180 — prompt hardening (date verification, language matching, cancellation ref)."""
import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from agents.marina import marina_agent


def test_date_verification_rule_in_prompt():
    """Brief 180: system prompt instructs Marina to verify weekday matches calendar date."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "verify that any weekday you state matches the calendar date" in prompt


def test_language_rule_says_most_recent():
    """Brief 180: language rule explicitly says MOST RECENT customer message."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "MOST RECENT customer message" in prompt
    # Old phrasing should be gone
    assert "Only fall back to English if" not in prompt


def test_cancellation_ref_echo_in_prompt():
    """Brief 180: escalation section tells Marina to echo booking ref on cancellation."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "cancel booking" in prompt
    assert "Never omit the ref" in prompt
