# bluemarlin/tests/social/test_094_auto_poster.py
# Created: Brief 094
# Purpose: Tests for auto_poster CLI entry point

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_token_067")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "990622044139349")

from agents.social.auto_poster import cmd_generate, cmd_review, cmd_publish, cmd_distill, cmd_status
from agents.social import content_agent
from shared import state_registry


# --- Helpers ---

def _cleanup_all():
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM content_drafts")
    conn.execute("DELETE FROM content_learnings")
    conn.commit()
    conn.close()


MOCK_CLAUDE_RESPONSE_2 = json.dumps({
    "drafts": [
        {
            "content_class": "A",
            "instagram_caption": "Crystal-clear waters and white sand. Klein Curaçao is waiting.",
            "facebook_caption": "There's a small uninhabited island off the coast of Curaçao.",
            "hashtags": ["#KleinCuracao", "#BlueFinnCharters"],
            "visual_suggestion": "aerial shot of Klein Curaçao",
            "reasoning": "Class A evergreen"
        },
        {
            "content_class": "C",
            "instagram_caption": "Saturday's Klein Curaçao trip is fully booked.",
            "facebook_caption": "This Saturday's Klein Curaçao trip is at full capacity.",
            "hashtags": ["#KleinCuracao"],
            "visual_suggestion": "photo of guests snorkeling",
            "reasoning": "Class C operational"
        }
    ]
})

MOCK_DISTILL_RESPONSE = json.dumps({
    "learnings": [
        {
            "rule": "Avoid urgency language in promotional posts",
            "source_pattern": "2 rejections cited urgency"
        }
    ]
})


def _mock_claude(response_json):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=response_json)]
    mock_msg.usage = MagicMock(input_tokens=500, output_tokens=300)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    return mock_client


# --- Tests ---

def test_cmd_generate_creates_drafts(capsys):
    _cleanup_all()
    try:
        mock_client = _mock_claude(MOCK_CLAUDE_RESPONSE_2)
        with patch("agents.social.content_agent.anthropic.Anthropic", return_value=mock_client):
            cmd_generate(2)
        captured = capsys.readouterr()
        drafts = state_registry.get_content_drafts()
        assert len(drafts) == 2
        assert "Generated 2 drafts" in captured.out
    finally:
        _cleanup_all()


def test_cmd_generate_no_api_key(capsys):
    _cleanup_all()
    try:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")
        with patch("agents.social.content_agent.anthropic.Anthropic", return_value=mock_client):
            cmd_generate(3)
        captured = capsys.readouterr()
        assert "No drafts generated" in captured.out
    finally:
        _cleanup_all()


def test_cmd_status_counts(capsys):
    _cleanup_all()
    try:
        # 2 pending
        state_registry.save_content_draft("A", "Pending one", "", [], "", "")
        state_registry.save_content_draft("A", "Pending two", "", [], "", "")
        # 1 approved
        d3 = state_registry.save_content_draft("B", "Approved one", "", [], "", "")
        state_registry.update_draft_status(d3, "approved")
        # 1 rejected
        d4 = state_registry.save_content_draft("C", "Rejected one", "", [], "", "")
        state_registry.update_draft_status(d4, "rejected", rejection_reason="bad")
        # 1 published
        d5 = state_registry.save_content_draft("D", "Published one", "", [], "", "")
        state_registry.update_draft_status(d5, "published")
        # 1 learning
        state_registry.save_content_learning("test rule")

        cmd_status()
        captured = capsys.readouterr()
        assert "Pending:    2" in captured.out
        assert "Approved:   1" in captured.out
        assert "Rejected:   1" in captured.out
        assert "Published:  1" in captured.out
        assert "Learnings:  1 active" in captured.out
    finally:
        _cleanup_all()


def test_cmd_review_approve(capsys):
    _cleanup_all()
    try:
        d = state_registry.save_content_draft("A", "Test IG caption", "Test FB caption", [], "", "")
        with patch("builtins.input", return_value="a"):
            cmd_review()
        captured = capsys.readouterr()
        assert "Approved" in captured.out
        drafts = state_registry.get_content_drafts()
        match = [x for x in drafts if x["id"] == d]
        assert match[0]["status"] == "approved"
    finally:
        _cleanup_all()


def test_cmd_review_reject(capsys):
    _cleanup_all()
    try:
        d = state_registry.save_content_draft("B", "Promo caption", "Promo FB", [], "", "")
        with patch("builtins.input", side_effect=["r", "too salesy"]):
            cmd_review()
        captured = capsys.readouterr()
        assert "Rejected" in captured.out
        drafts = state_registry.get_content_drafts()
        match = [x for x in drafts if x["id"] == d]
        assert match[0]["status"] == "rejected"
        assert match[0]["rejection_reason"] == "too salesy"
    finally:
        _cleanup_all()


def test_cmd_review_skip(capsys):
    _cleanup_all()
    try:
        d = state_registry.save_content_draft("A", "Skip me", "Skip FB", [], "", "")
        with patch("builtins.input", return_value="s"):
            cmd_review()
        captured = capsys.readouterr()
        assert "Skipped" in captured.out
        drafts = state_registry.get_content_drafts()
        match = [x for x in drafts if x["id"] == d]
        assert match[0]["status"] == "pending"
    finally:
        _cleanup_all()


def test_cmd_review_empty(capsys):
    _cleanup_all()
    try:
        cmd_review()
        captured = capsys.readouterr()
        assert "No pending drafts" in captured.out
    finally:
        _cleanup_all()


def test_cmd_publish_stub(capsys):
    _cleanup_all()
    try:
        d = state_registry.save_content_draft("A", "Publish me IG", "Publish me FB",
                                               ["#test"], "visual", "reason")
        state_registry.update_draft_status(d, "approved")
        cmd_publish()
        captured = capsys.readouterr()
        assert "Published" in captured.out
        assert "stub" in captured.out
        drafts = state_registry.get_content_drafts()
        match = [x for x in drafts if x["id"] == d]
        assert match[0]["status"] == "published"
    finally:
        _cleanup_all()


def test_cmd_publish_empty(capsys):
    _cleanup_all()
    try:
        cmd_publish()
        captured = capsys.readouterr()
        assert "No approved drafts" in captured.out
    finally:
        _cleanup_all()


def test_cmd_distill_from_rejections(capsys):
    _cleanup_all()
    try:
        d1 = state_registry.save_content_draft("B", "Buy now!", "", [], "", "")
        state_registry.update_draft_status(d1, "rejected", rejection_reason="too pushy")
        d2 = state_registry.save_content_draft("B", "Don't miss out!", "", [], "", "")
        state_registry.update_draft_status(d2, "rejected", rejection_reason="urgency")

        mock_client = _mock_claude(MOCK_DISTILL_RESPONSE)
        with patch("agents.social.content_agent.anthropic.Anthropic", return_value=mock_client):
            cmd_distill()
        captured = capsys.readouterr()
        assert "NEW RULE" in captured.out or "Distilled" in captured.out
        assert len(state_registry.get_active_learnings()) > 0
    finally:
        _cleanup_all()
