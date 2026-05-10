"""Tests for Brief 224 — strip internal escalation tokens from Marina
replies before they reach customer-facing channels."""
import os
from unittest.mock import patch, MagicMock


def _mock_anthropic_response(reply_text: str, reply_hold_failed: str = ""):
    """Build a mock anthropic response whose tool_use block carries the given
    reply (and optionally reply_hold_failed) field."""
    block = MagicMock()
    block.type = "tool_use"
    inp = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "medium",
        "reply": reply_text,
        "clarifications_needed": [],
        "requires_human": False,
        "flags": {},
        "internal_note": "",
    }
    if reply_hold_failed:
        inp["reply_hold_failed"] = reply_hold_failed
    block.input = inp
    resp = MagicMock()
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=10, output_tokens=20)
    return resp


def _call_process_message(reply_text: str, reply_hold_failed: str = ""):
    from agents.marina import marina_agent
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
         patch("agents.marina.marina_agent.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            reply_text, reply_hold_failed)
        return marina_agent.process_message(
            from_email="alice@example.com",
            subject="hi",
            body="hello",
            thread_fields={},
            thread_flags={},
            action_context={},
            channel="email",
            messages=[],
        )


def test_escalate_token_stripped_from_reply():
    """Brief 224: [ESCALATE] sentinel removed from customer-facing reply."""
    result = _call_process_message(
        "Got it, passing this to the team.\n\nMarina\nUnboks\n[ESCALATE]"
    )
    assert "[ESCALATE]" not in result["reply"]
    assert result["reply"].endswith("Unboks")


def test_all_listed_tokens_stripped():
    """All five internal tokens listed in _INTERNAL_TOKENS are removed."""
    text = ("Reply body.\n[ESCALATE]\n[SOFT_ESCALATION]\n"
            "[HARD_ESCALATION]\n[HANDOFF]\n[HUMAN_TAKEOVER]\nMarina")
    result = _call_process_message(text)
    for tok in ("[ESCALATE]", "[SOFT_ESCALATION]", "[HARD_ESCALATION]",
                "[HANDOFF]", "[HUMAN_TAKEOVER]"):
        assert tok not in result["reply"]
    assert "Reply body." in result["reply"]
    assert "Marina" in result["reply"]


def test_booking_ref_and_payment_link_preserved():
    """Regression: legitimate template placeholders are NOT stripped."""
    text = "Booked! Ref: [BOOKING_REF]. Pay here: [PAYMENT_LINK]"
    result = _call_process_message(text)
    assert "[BOOKING_REF]" in result["reply"]
    assert "[PAYMENT_LINK]" in result["reply"]


def test_reply_hold_failed_also_stripped():
    """The booking-failure fallback field is also customer-facing — strip
    tokens from it too."""
    result = _call_process_message(
        reply_text="ok",
        reply_hold_failed="Sorry, hold failed. We'll be in touch.\n[ESCALATE]",
    )
    assert "[ESCALATE]" not in result["reply_hold_failed"]
    assert "Sorry, hold failed" in result["reply_hold_failed"]


def test_no_tokens_no_change():
    """Reply with no internal tokens is returned untouched (apart from a
    trailing rstrip), so existing prompts continue to behave the same."""
    text = "Hello! Thanks for your message.\n\nMarina"
    result = _call_process_message(text)
    assert result["reply"] == text  # no trailing whitespace to strip


# ── Brief 244: em-dash strip from customer-facing reply fields ─

def test_em_dash_stripped_from_reply():
    """Brief 244: process_message strips em-dashes from result['reply']
    before returning. Mirrors dm_agent.py:253 strip behavior — em-dash
    becomes comma (no space) to match dm_agent's existing pattern."""
    text_with_dash = (
        "The team will contact you shortly — keep an eye on your inbox.")
    result = _call_process_message(text_with_dash)
    assert "—" not in result["reply"]
    assert result["reply"] == (
        "The team will contact you shortly , keep an eye on your inbox.")


def test_em_dash_stripped_from_reply_hold_failed():
    """Brief 244: same strip applies to reply_hold_failed (apologetic
    message when slot unavailable, also customer-facing per
    marina_agent.py:109 schema)."""
    plain = "OK"
    apology_with_dash = "Sorry — that slot just got taken."
    result = _call_process_message(
        plain, reply_hold_failed=apology_with_dash)
    assert "—" not in result["reply_hold_failed"]
    assert result["reply_hold_failed"] == "Sorry , that slot just got taken."


def test_em_dash_strip_runs_after_internal_token_strip():
    """Brief 244 + Brief 224: both sanitizers compose. A reply containing
    BOTH an internal escalation token AND an em-dash gets cleaned of both
    before reaching the customer. Proves the em-dash strip is sequenced
    AFTER _strip_internal_tokens (so trailing-whitespace cleanup from
    token strip happens first, then em-dash replacement runs)."""
    dirty = "I'll escalate that — the team handles refunds. [ESCALATE]"
    result = _call_process_message(dirty)
    assert "[ESCALATE]" not in result["reply"]
    assert "—" not in result["reply"]
    assert "I'll escalate that , the team handles refunds." in result["reply"]
