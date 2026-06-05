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
    """Brief 176: empty thread_fields on email → neutral resend/help reply."""
    reply = _call({})
    # Should NOT acknowledge any "known" details
    assert "I have" not in reply
    assert "I've got" not in reply
    # Should not assume any tenant shape such as tourism bookings.
    lower = reply.lower()
    assert "trip" not in lower
    assert "date" not in lower
    assert "guests" not in lower
    assert "what you need help with" in lower
    # Has a signature
    assert "Marina" in reply


def test_fallback_partial_fields_email_acknowledges_known():
    """Brief 176: partial fields → acknowledge known, ask for missing."""
    reply = _call({
        "customer_name": "Alice",
        "guests": 7,
        "service_name": "Klein Curaçao",
    })
    assert "Alice" in reply
    assert "7" in reply
    assert "Klein Curaçao" in reply
    # Still asks for context without assuming booking-specific fields.
    assert "what you need help with" in reply.lower()
    # Does NOT re-ask for service or guests (they're already known)
    assert "which trip" not in reply.lower()
    assert "how many guests" not in reply.lower()


def test_fallback_all_fields_email_asks_to_resend():
    """Brief 176: all fields known → don't re-ask anything; ask to resend last message."""
    reply = _call({
        "customer_name": "Alice",
        "guests": 7,
        "service_name": "Klein Curaçao",
        "date": "2026-04-11",
    })
    # Acknowledges everything
    assert "Alice" in reply
    assert "7" in reply
    assert "Klein Curaçao" in reply
    assert "2026-04-11" in reply
    # Does NOT re-ask for any of the four fields (explicit substrings the
    # missing-field branches would have produced)
    lower = reply.lower()
    assert "what date" not in lower
    assert "date works" not in lower
    assert "which trip" not in lower
    assert "how many guests" not in lower
    # Asks the customer to resend their last message
    assert "resend" in lower or "last message" in lower


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
    # Acknowledges the customer + guests
    assert "Alice" in reply
    assert "7" in reply


def test_fallback_whatsapp_empty_fields():
    """Brief 176: WhatsApp fallback with empty fields — short and tenant-neutral."""
    reply = _call({}, channel="whatsapp")
    word_count = len(reply.split())
    assert word_count < 40
    assert "hiccup" in reply.lower() or "missed" in reply.lower() or "resend" in reply.lower()
    lower = reply.lower()
    assert "trip" not in lower
    assert "date" not in lower
    assert "guests" not in lower
    assert "what you need help with" in lower
