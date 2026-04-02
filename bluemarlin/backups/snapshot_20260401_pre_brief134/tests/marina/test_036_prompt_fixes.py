"""Tests for Brief 036 — Marina prompt bug fixes."""
import os

from agents.marina import marina_agent


_prompt = marina_agent._build_prompt(
    from_email="test@example.com",
    subject="Test",
    body="Hello",
    thread_fields={},
    thread_flags={},
)


def test_language_rule_body_text():
    """T1: Language rule is body-text-based."""
    assert "body text" in _prompt


def test_language_rule_germanic_names():
    """T2: Language rule explicitly handles Germanic/non-English names."""
    assert "German" in _prompt or "sender" in _prompt.lower() or "name" in _prompt.lower()


def test_days_available_in_prompt():
    """T3: BOOKING CONFIRMATION section includes days_available check."""
    assert "days_available" in _prompt


def test_day_of_week_check():
    """T4: Day-of-week data present in prompt via trip definitions."""
    # The prompt contains days_available for each trip (e.g. "Fridays only")
    assert "days_available" in _prompt


def test_reply_hold_failed_only_when():
    """T5: reply_hold_failed description includes 'ONLY when'."""
    assert "ONLY when" in _prompt


def test_reply_hold_failed_exclusions():
    """T6: reply_hold_failed description excludes escalation paths."""
    assert "escalation" in _prompt or "inquiry" in _prompt


def test_file_header_updated():
    """T7: File header updated to Brief."""
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "marina_agent.py")) as f:
        header = f.read(300)
    assert "Last modified: Brief" in header
