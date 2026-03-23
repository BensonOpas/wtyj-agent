"""Tests for Brief 035 — Marina prompt polish: language + trip key mapping."""
import os

from agents.marina import marina_agent


# Build a prompt using real data (no API call)
_prompt = marina_agent._build_prompt(
    from_email="test@example.com",
    subject="Test",
    body="Hello",
    thread_fields={},
    thread_flags={},
)


def test_language_rule_present():
    """T1: LANGUAGE RULE instruction is in the prompt."""
    assert "LANGUAGE RULE:" in _prompt


def test_language_detection_instruction():
    """T2: Language instruction mentions reading the body text."""
    assert "body text" in _prompt


def test_supported_languages_listed():
    """T3: Prompt lists supported languages."""
    assert "Dutch" in _prompt and "German" in _prompt and "Spanish" in _prompt


def test_all_trip_keys_present():
    """T4: All 5 trip keys appear in the prompt."""
    for key in ["klein_curacao", "snorkeling_3in1", "west_coast_beach", "sunset_cruise", "jet_ski"]:
        assert key in _prompt, f"trip key '{key}' missing from prompt"


def test_trip_aliases_present():
    """T5: Mapping aliases are in the prompt."""
    for alias in ["snorkeling", "west coast", "sunset", "jet ski", "Klein Curaçao"]:
        assert alias in _prompt, f"alias '{alias}' missing from prompt"


def test_file_header_updated():
    """T6: File header updated to Brief."""
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "marina_agent.py")) as f:
        header = f.read(300)
    assert "Last modified: Brief" in header


def test_claude_md_no_stale_thread_key_issue():
    """T7: CLAUDE.md no longer contains the stale thread-key issue."""
    claude_md_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "CLAUDE.md")
    with open(claude_md_path) as f:
        claude_content = f.read()
    assert "Thread key breaks on subject change" not in claude_content


def test_claude_md_no_stale_verify_issue():
    """T8: CLAUDE.md no longer contains [VERIFY] open issue."""
    claude_md_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "CLAUDE.md")
    with open(claude_md_path) as f:
        claude_content = f.read()
    assert "items remain in client.json" not in claude_content
