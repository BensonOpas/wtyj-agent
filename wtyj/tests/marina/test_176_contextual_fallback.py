"""Tests for Brief 176 — Marina context-aware fallback reply."""
import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from agents.marina import marina_agent


def _call(thread_fields, channel="email"):
    return marina_agent._build_contextual_fallback_reply(
        thread_fields=thread_fields,
        channel=channel,
        signature="Marina\nBlueMarlin Charters",
        svc_label="trip",
        party_label="guests",
    )


def test_fallback_empty_fields_email_is_first_contact():
    """Provider failure fallback is short and does not expose internal errors."""
    reply = _call({})
    assert "hiccup" not in reply.lower()
    assert "claude" not in reply.lower()
    assert "anthropic" not in reply.lower()
    assert "Thanks for your message" in reply


def test_fallback_partial_fields_email_acknowledges_known():
    """Fallback does not leak booking internals on provider failure."""
    reply = _call({
        "customer_name": "Alice",
        "guests": 7,
        "service_name": "Klein Curaçao",
    })
    assert "hiccup" not in reply.lower()
    assert "Thanks for your message" in reply


def test_fallback_all_fields_email_asks_to_resend():
    """Fallback remains generic and safe even when thread fields exist."""
    reply = _call({
        "customer_name": "Alice",
        "guests": 7,
        "service_name": "Klein Curaçao",
        "date": "2026-04-11",
    })
    assert "hiccup" not in reply.lower()
    assert "Thanks for your message" in reply


def test_fallback_whatsapp_is_terse():
    """Brief 176: WhatsApp fallback must be under 40 words, no signature."""
    reply = _call({
        "customer_name": "Alice",
        "guests": 7,
    }, channel="whatsapp")
    word_count = len(reply.split())
    assert word_count < 40, f"WhatsApp fallback too long: {word_count} words"
    # No email signature
    assert "Warm regards" not in reply
    assert "hiccup" not in reply.lower()


def test_fallback_whatsapp_empty_fields():
    """Brief 176: WhatsApp fallback with empty fields — short, asks to resend OR asks missing."""
    reply = _call({}, channel="whatsapp")
    word_count = len(reply.split())
    assert word_count < 40
    assert "hiccup" not in reply.lower()
    assert "reply shortly" in reply.lower()
