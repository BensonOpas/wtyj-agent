"""Tests for Brief 234 — APPROVED ANSWERS injection on IG/FB DM path."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from unittest.mock import patch

from agents.social.dm_agent import _build_dm_approved_answers_block, _build_dm_system_prompt


def test_block_empty_when_flag_off():
    """Brief 234: with features.approved_learnings_in_prompt unset/False,
    the helper returns empty string regardless of stored learnings."""
    with patch("agents.social.dm_agent.config_loader.get_raw",
               return_value={"features": {"approved_learnings_in_prompt": False}}):
        result = _build_dm_approved_answers_block("instagram_dm")
    assert result == ""


def test_block_empty_when_flag_on_but_no_learnings():
    """Brief 234: flag on but no matching rows → still empty."""
    with patch("agents.social.dm_agent.config_loader.get_raw",
               return_value={"features": {"approved_learnings_in_prompt": True}}), \
         patch("agents.social.dm_agent.state_registry.get_approved_learnings_for_prompt",
               return_value=[]):
        result = _build_dm_approved_answers_block("instagram_dm")
    assert result == ""


def test_block_renders_qa_pairs_when_present():
    """Brief 234: flag on + learnings → block contains 'APPROVED ANSWERS'
    header and each Q/A pair."""
    rows = [
        {"question": "Do you ship outside Curacao?",
         "answer": "Not yet — local pickup or delivery only."},
        {"question": "Refund policy?",
         "answer": "Within 7 days of purchase, full refund."},
    ]
    with patch("agents.social.dm_agent.config_loader.get_raw",
               return_value={"features": {"approved_learnings_in_prompt": True}}), \
         patch("agents.social.dm_agent.state_registry.get_approved_learnings_for_prompt",
               return_value=rows):
        result = _build_dm_approved_answers_block("instagram_dm")
    assert "APPROVED ANSWERS" in result
    assert "Do you ship outside Curacao?" in result
    assert "Not yet" in result
    assert "Refund policy?" in result
    assert "Within 7 days" in result


def test_block_skips_rows_with_empty_answer():
    """Brief 234: a row with an empty answer is dropped — defensive
    guard against partial data."""
    rows = [
        {"question": "real q", "answer": "real a"},
        {"question": "also real", "answer": ""},
    ]
    with patch("agents.social.dm_agent.config_loader.get_raw",
               return_value={"features": {"approved_learnings_in_prompt": True}}), \
         patch("agents.social.dm_agent.state_registry.get_approved_learnings_for_prompt",
               return_value=rows):
        result = _build_dm_approved_answers_block("instagram_dm")
    assert "real q" in result
    assert "real a" in result
    assert "also real" not in result


def test_helper_failure_returns_empty_string():
    """Brief 234: state_registry exception is swallowed; helper returns
    empty string. Never raises into _build_dm_system_prompt's call chain."""
    with patch("agents.social.dm_agent.config_loader.get_raw",
               return_value={"features": {"approved_learnings_in_prompt": True}}), \
         patch("agents.social.dm_agent.state_registry.get_approved_learnings_for_prompt",
               side_effect=Exception("db down")):
        result = _build_dm_approved_answers_block("instagram_dm")
    assert result == ""


def test_system_prompt_includes_learnings_when_flag_on(monkeypatch):
    """Brief 234: end-to-end — _build_dm_system_prompt's full output
    contains the APPROVED ANSWERS block when the flag is on AND
    learnings exist. Tests the master_prompt branch (freeform_notes set)."""
    rows = [{"question": "test234 question?", "answer": "test234 answer."}]
    fake_raw = {
        "features": {"approved_learnings_in_prompt": True, "booking_flow": False},
        "agent_persona": {"freeform_notes": "MASTER PROMPT BLOCK"},
        "terminology": {},
    }
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_raw",
                        lambda: fake_raw)
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_business",
                        lambda: {"name": "Test", "agent_name": "Marina"})
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_common_sense_knowledge",
                        lambda: {})
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_services",
                        lambda: {})
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_faq",
                        lambda: {})
    monkeypatch.setattr("agents.social.dm_agent.state_registry.get_approved_learnings_for_prompt",
                        lambda channel, limit=20: rows)
    prompt = _build_dm_system_prompt("instagram_dm")
    assert "APPROVED ANSWERS" in prompt
    assert "test234 question?" in prompt
    assert "test234 answer." in prompt


def test_system_prompt_omits_block_when_flag_off(monkeypatch):
    """Brief 234: with the flag off, _build_dm_system_prompt's output has
    NO 'APPROVED ANSWERS' header — verifies the if-block prepend is gated."""
    fake_raw = {
        "features": {"approved_learnings_in_prompt": False, "booking_flow": False},
        "agent_persona": {"freeform_notes": "MASTER PROMPT BLOCK"},
        "terminology": {},
    }
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_raw",
                        lambda: fake_raw)
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_business",
                        lambda: {"name": "Test", "agent_name": "Marina"})
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_common_sense_knowledge",
                        lambda: {})
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_services",
                        lambda: {})
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_faq",
                        lambda: {})
    prompt = _build_dm_system_prompt("instagram_dm")
    assert "APPROVED ANSWERS" not in prompt
