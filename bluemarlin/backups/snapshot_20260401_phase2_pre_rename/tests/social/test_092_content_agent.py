# bluemarlin/tests/social/test_092_content_agent.py
# Created: Brief 092
# Purpose: Tests for content agent core + draft store

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
    _build_user_prompt,
    generate_drafts,
)
from shared import state_registry, config_loader


# --- Helpers ---

def _cleanup_drafts():
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM content_drafts")
    conn.commit()
    conn.close()


# --- Mock Claude responses ---

MOCK_CLAUDE_RESPONSE_2 = json.dumps({
    "drafts": [
        {
            "content_class": "A",
            "instagram_caption": "Crystal-clear waters and white sand. Klein Curaçao is waiting.",
            "facebook_caption": "There's a small uninhabited island just off the coast of Curaçao with crystal-clear waters, white sand beaches, and sea turtles swimming right past you. That's Klein Curaçao — and we go there every day.",
            "hashtags": ["#KleinCuracao", "#BlueFinnCharters", "#CuracaoBoatTrip"],
            "visual_suggestion": "aerial shot of Klein Curaçao beach with turquoise water",
            "reasoning": "Class A evergreen — showcases flagship experience, builds brand awareness"
        },
        {
            "content_class": "C",
            "instagram_caption": "Saturday's Klein Curaçao trip is fully booked. Sunday still has spots — same water, same turtles, same open bar.",
            "facebook_caption": "This Saturday's Klein Curaçao trip is at full capacity — but don't worry. Sunday's departure still has spots available. Same crystal-clear water, same white sand, same sea turtles, and the same premium open bar from lunch. Book your spot before Sunday fills up too.",
            "hashtags": ["#KleinCuracao", "#BlueFinnCharters", "#SundayVibes"],
            "visual_suggestion": "photo of guests snorkeling near Klein Curaçao",
            "reasoning": "Class C operational — Saturday sold out, redirects demand to Sunday"
        }
    ]
})

MOCK_CLAUDE_RESPONSE_1 = json.dumps({
    "drafts": [
        {
            "content_class": "A",
            "instagram_caption": "Crystal-clear waters and white sand. Klein Curaçao is waiting.",
            "facebook_caption": "There's a small uninhabited island off the coast with crystal-clear waters and sea turtles.",
            "hashtags": ["#KleinCuracao", "#BlueFinnCharters"],
            "visual_suggestion": "aerial shot of Klein Curaçao beach",
            "reasoning": "Class A evergreen"
        }
    ]
})

MOCK_CLAUDE_RESPONSE_MISSING_FIELDS = json.dumps({
    "drafts": [
        {
            "content_class": "B",
            "instagram_caption": "Sunset cruise tonight.",
            "facebook_caption": "Join us for tonight's sunset cruise."
        }
    ]
})

MOCK_CLAUDE_RESPONSE_INVALID_CLASS = json.dumps({
    "drafts": [
        {
            "content_class": "Z",
            "instagram_caption": "Some post.",
            "facebook_caption": "Some longer post."
        }
    ]
})


def _mock_claude_response(response_json):
    """Create a mock Anthropic client that returns the given JSON."""
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=response_json)]
    mock_msg.usage = MagicMock(input_tokens=500, output_tokens=300)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    return mock_client


# --- Tests ---

def test_system_prompt_includes_brand_rules():
    prompt = _build_system_prompt(3)
    assert "premium" in prompt.lower()
    assert "brand quality" in prompt.lower()
    assert "factual correctness" in prompt.lower()
    assert "Class A" in prompt
    assert "Class B" in prompt
    assert "Class C" in prompt
    assert "Class D" in prompt


def test_system_prompt_includes_response_format():
    prompt = _build_system_prompt(3)
    assert "instagram_caption" in prompt
    assert "facebook_caption" in prompt
    assert "hashtags" in prompt
    assert "visual_suggestion" in prompt
    assert "reasoning" in prompt


def test_system_prompt_reads_config_values():
    prompt = _build_system_prompt(3)
    # brand_voice from social_content
    assert "premium, confident, clear, aspirational, experience-driven" in prompt
    # cta_default from social_content
    assert "Message us on WhatsApp to book" in prompt
    # content_boundaries from social_content
    assert "competitors" in prompt


def test_user_prompt_includes_client_data():
    prompt = _build_user_prompt(3, days_ahead=7)
    assert "Klein" in prompt  # Klein Curaçao trip
    assert "Sunset" in prompt  # Sunset Cruise
    assert "CLIENT DATA" in prompt


def test_user_prompt_includes_availability():
    mock_avail = [
        {
            "trip_key": "klein_curacao",
            "date": "2026-03-20",
            "departure_time": "08:00",
            "booked_guests": 25,
            "capacity": 30,
            "spots_remaining": 5,
        }
    ]
    with patch.object(state_registry, "get_availability_summary", return_value=mock_avail):
        prompt = _build_user_prompt(3, days_ahead=7)
    assert "5/30" in prompt


def test_user_prompt_no_availability_graceful():
    with patch.object(state_registry, "get_availability_summary", return_value=[]):
        prompt = _build_user_prompt(3, days_ahead=7)
    assert "No booking data available" in prompt
    assert "evergreen" in prompt.lower()


def test_generate_drafts_stores_in_db():
    _cleanup_drafts()
    try:
        mock_client = _mock_claude_response(MOCK_CLAUDE_RESPONSE_2)
        with patch("agents.social.content_agent.anthropic.Anthropic", return_value=mock_client):
            result = generate_drafts(count=2)
        drafts = state_registry.get_content_drafts()
        assert len(drafts) == 2
        assert drafts[0]["status"] == "pending"
    finally:
        _cleanup_drafts()


def test_generate_drafts_returns_structured():
    _cleanup_drafts()
    try:
        mock_client = _mock_claude_response(MOCK_CLAUDE_RESPONSE_1)
        with patch("agents.social.content_agent.anthropic.Anthropic", return_value=mock_client):
            result = generate_drafts(count=1)
        assert len(result) == 1
        draft = result[0]
        for key in ("id", "content_class", "instagram_caption", "facebook_caption",
                     "hashtags", "visual_suggestion", "reasoning", "status"):
            assert key in draft, f"Missing key: {key}"
    finally:
        _cleanup_drafts()


def test_draft_defaults_missing_fields():
    _cleanup_drafts()
    try:
        mock_client = _mock_claude_response(MOCK_CLAUDE_RESPONSE_MISSING_FIELDS)
        with patch("agents.social.content_agent.anthropic.Anthropic", return_value=mock_client):
            result = generate_drafts(count=1)
        assert len(result) == 1
        draft = result[0]
        assert draft["hashtags"] == []
        assert draft["visual_suggestion"] == ""
    finally:
        _cleanup_drafts()


def test_content_class_validation():
    _cleanup_drafts()
    try:
        mock_client = _mock_claude_response(MOCK_CLAUDE_RESPONSE_INVALID_CLASS)
        with patch("agents.social.content_agent.anthropic.Anthropic", return_value=mock_client):
            result = generate_drafts(count=1)
        assert len(result) == 1
        assert result[0]["content_class"] == "A"
    finally:
        _cleanup_drafts()


def test_generate_drafts_api_error_returns_empty():
    _cleanup_drafts()
    try:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API timeout")
        with patch("agents.social.content_agent.anthropic.Anthropic", return_value=mock_client):
            result = generate_drafts(count=3)
        assert result == []
        assert len(state_registry.get_content_drafts()) == 0
    finally:
        _cleanup_drafts()


def test_update_draft_status_approved():
    _cleanup_drafts()
    try:
        draft_id = state_registry.save_content_draft(
            "A", "Test caption IG", "Test caption FB",
            ["#test"], "test visual", "test reasoning"
        )
        state_registry.update_draft_status(draft_id, "approved")
        drafts = state_registry.get_content_drafts()
        match = [d for d in drafts if d["id"] == draft_id]
        assert len(match) == 1
        assert match[0]["status"] == "approved"
        assert match[0]["approved_at"] is not None
    finally:
        _cleanup_drafts()


def test_update_draft_status_rejected_with_reason():
    _cleanup_drafts()
    try:
        draft_id = state_registry.save_content_draft(
            "B", "Promo caption IG", "Promo caption FB",
            ["#promo"], "promo visual", "promo reasoning"
        )
        state_registry.update_draft_status(draft_id, "rejected", rejection_reason="too salesy")
        drafts = state_registry.get_content_drafts()
        match = [d for d in drafts if d["id"] == draft_id]
        assert len(match) == 1
        assert match[0]["status"] == "rejected"
        assert match[0]["rejection_reason"] == "too salesy"
    finally:
        _cleanup_drafts()


def test_availability_summary_returns_correct_structure():
    results = state_registry.get_availability_summary(days_ahead=3)
    assert isinstance(results, list)
    if results:
        for item in results:
            assert "trip_key" in item
            assert "date" in item
            assert "departure_time" in item
            assert "booked_guests" in item
            assert "capacity" in item
            assert "spots_remaining" in item
            assert item["spots_remaining"] == item["capacity"] - item["booked_guests"]
