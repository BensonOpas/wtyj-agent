# bluemarlin/tests/social/test_093_rejection_learning.py
# Created: Brief 093
# Purpose: Tests for rejection learning system

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_token_067")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "990622044139349")

from agents.social.content_agent import (
    _build_system_prompt,
    generate_drafts,
    distill_learnings,
)
from shared import state_registry


# --- Helpers ---

def _cleanup_drafts():
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM content_drafts")
    conn.commit()
    conn.close()


def _cleanup_learnings():
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM content_learnings")
    conn.commit()
    conn.close()


def _cleanup_all():
    _cleanup_drafts()
    _cleanup_learnings()


# --- Mock responses ---

MOCK_DISTILL_RESPONSE = json.dumps({
    "learnings": [
        {
            "rule": "Never use urgency language like 'last spots' or 'don't miss out'",
            "source_pattern": "3 rejections cited 'too salesy'"
        },
        {
            "rule": "Keep sunset cruise posts focused on the experience, not the price",
            "source_pattern": "2 rejections about sunset cruise pricing"
        }
    ]
})

MOCK_DISTILL_RESPONSE_SINGLE = json.dumps({
    "learnings": [
        {
            "rule": "Avoid generic descriptions that could apply to any boat company",
            "source_pattern": "2 rejections cited 'off-brand'"
        }
    ]
})


def _mock_claude_response(response_json):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=response_json)]
    mock_msg.usage = MagicMock(input_tokens=500, output_tokens=300)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    return mock_client


def _create_rejected_drafts(count=3):
    """Create rejected drafts for testing. Returns list of draft IDs."""
    captions = [
        ("B", "Book now! Last spots!", "too salesy"),
        ("B", "Hurry! Don't miss out!", "wrong tone"),
        ("A", "We do boat trips.", "too generic"),
    ]
    ids = []
    for i in range(min(count, len(captions))):
        cls, cap, reason = captions[i]
        d = state_registry.save_content_draft(cls, cap, "", [], "", "")
        state_registry.update_draft_status(d, "rejected", rejection_reason=reason)
        ids.append(d)
    return ids


# --- Tests ---

def test_save_and_get_learning():
    _cleanup_all()
    try:
        lid = state_registry.save_content_learning("test rule")
        learnings = state_registry.get_active_learnings()
        assert len(learnings) == 1
        assert learnings[0]["rule"] == "test rule"
        assert learnings[0]["id"] == lid
    finally:
        _cleanup_all()


def test_deactivate_learning():
    _cleanup_all()
    try:
        lid = state_registry.save_content_learning("deactivate me")
        result = state_registry.deactivate_learning(lid)
        assert result is True
        assert len(state_registry.get_active_learnings()) == 0
    finally:
        _cleanup_all()


def test_deactivate_already_inactive():
    _cleanup_all()
    try:
        lid = state_registry.save_content_learning("once is enough")
        state_registry.deactivate_learning(lid)
        result = state_registry.deactivate_learning(lid)
        assert result is False
    finally:
        _cleanup_all()


def test_system_prompt_includes_learnings():
    _cleanup_all()
    try:
        state_registry.save_content_learning("rule one")
        state_registry.save_content_learning("rule two")
        prompt = _build_system_prompt(3)
        assert "BRAND LEARNINGS" in prompt
        assert "rule one" in prompt
        assert "rule two" in prompt
    finally:
        _cleanup_all()


def test_system_prompt_no_learnings_section_when_empty():
    _cleanup_all()
    try:
        prompt = _build_system_prompt(3)
        assert "BRAND LEARNINGS" not in prompt
    finally:
        _cleanup_all()


def test_system_prompt_excludes_inactive_learnings():
    _cleanup_all()
    try:
        lid1 = state_registry.save_content_learning("keep this rule")
        lid2 = state_registry.save_content_learning("remove this rule")
        state_registry.deactivate_learning(lid2)
        prompt = _build_system_prompt(3)
        assert "keep this rule" in prompt
        assert "remove this rule" not in prompt
    finally:
        _cleanup_all()


def test_distill_no_rejections_returns_empty():
    _cleanup_all()
    try:
        result = distill_learnings()
        assert result == []
        assert len(state_registry.get_active_learnings()) == 0
    finally:
        _cleanup_all()


def test_distill_saves_learnings():
    _cleanup_all()
    try:
        _create_rejected_drafts(3)
        mock_client = _mock_claude_response(MOCK_DISTILL_RESPONSE)
        with patch("agents.social.content_agent.anthropic.Anthropic", return_value=mock_client):
            result = distill_learnings()
        assert len(result) == 2
        learnings = state_registry.get_active_learnings()
        assert len(learnings) == 2
        assert "urgency" in learnings[0]["rule"]
    finally:
        _cleanup_all()


def test_distill_includes_existing_learnings_in_prompt():
    _cleanup_all()
    try:
        state_registry.save_content_learning("existing rule")
        _create_rejected_drafts(2)
        mock_client = _mock_claude_response(MOCK_DISTILL_RESPONSE)
        with patch("agents.social.content_agent.anthropic.Anthropic", return_value=mock_client):
            distill_learnings()
        call_args = mock_client.messages.create.call_args
        system_arg = call_args.kwargs.get("system", "")
        assert "EXISTING RULES" in system_arg
        assert "existing rule" in system_arg
    finally:
        _cleanup_all()


def test_distill_api_error_returns_empty():
    _cleanup_all()
    try:
        _create_rejected_drafts(2)
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API timeout")
        with patch("agents.social.content_agent.anthropic.Anthropic", return_value=mock_client):
            result = distill_learnings()
        assert result == []
        assert len(state_registry.get_active_learnings()) == 0
    finally:
        _cleanup_all()


def test_learning_source_draft_ids():
    _cleanup_all()
    try:
        d1 = state_registry.save_content_draft("A", "Caption one", "", [], "", "")
        state_registry.update_draft_status(d1, "rejected", rejection_reason="off-brand")
        d2 = state_registry.save_content_draft("A", "Caption two", "", [], "", "")
        state_registry.update_draft_status(d2, "rejected", rejection_reason="off-brand")

        mock_client = _mock_claude_response(MOCK_DISTILL_RESPONSE_SINGLE)
        with patch("agents.social.content_agent.anthropic.Anthropic", return_value=mock_client):
            result = distill_learnings()
        assert len(result) == 1
        assert d1 in result[0]["source_draft_ids"]
        assert d2 in result[0]["source_draft_ids"]
    finally:
        _cleanup_all()


def test_generate_drafts_uses_learnings():
    _cleanup_all()
    try:
        state_registry.save_content_learning("Never mention turtle petting")
        mock_response = json.dumps({"drafts": [
            {"content_class": "A", "instagram_caption": "Test.", "facebook_caption": "Test post.",
             "hashtags": [], "visual_suggestion": "", "reasoning": "test"}
        ]})
        mock_client = _mock_claude_response(mock_response)
        with patch("agents.social.content_agent.anthropic.Anthropic", return_value=mock_client):
            generate_drafts(count=1)
        call_args = mock_client.messages.create.call_args
        system_arg = call_args.kwargs.get("system", "")
        assert "Never mention turtle petting" in system_arg
    finally:
        _cleanup_all()
