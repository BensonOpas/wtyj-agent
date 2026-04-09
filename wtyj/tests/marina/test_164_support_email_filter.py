"""Tests for Brief 164 — support-email sender filter.

Covers:
- _business_sender_emails() helper returns the full set from business config
- Missing/empty fields are filtered out
- Lowercase normalization
- Source-level regression guard that the UID-loop guard exists and preserves
  the relay/escalation passthrough
"""
import os
from unittest.mock import patch

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from agents.marina import email_poller


@patch("agents.marina.email_poller.config_loader.get_business")
def test_business_sender_emails_includes_all_four_fields(mock_get_business):
    """Brief 164: helper returns all four business email fields, lowercased, deduped."""
    mock_get_business.return_value = {
        "email": "Support@Test.com",
        "support_email": "support@test.com",
        "booking_email": "BOOK@test.com",
        "demo_support_email": "support@test.com",
        "name": "Test",
    }
    result = email_poller._business_sender_emails()
    assert result == {"support@test.com", "book@test.com"}


@patch("agents.marina.email_poller.config_loader.get_business")
def test_business_sender_emails_handles_missing_fields(mock_get_business):
    """Brief 164: missing or empty fields are filtered out."""
    mock_get_business.return_value = {
        "email": "hello@test.com",
        "support_email": "",
        "booking_email": None,
        "name": "Test",
    }
    result = email_poller._business_sender_emails()
    assert result == {"hello@test.com"}


@patch("agents.marina.email_poller.config_loader.get_business")
def test_business_sender_emails_empty_when_no_business(mock_get_business):
    """Brief 164: empty business dict returns empty set (guard is a no-op)."""
    mock_get_business.return_value = {}
    assert email_poller._business_sender_emails() == set()


@patch("agents.marina.email_poller.config_loader.get_business")
def test_business_sender_lowercase_normalization(mock_get_business):
    """Brief 164: the helper must lowercase and strip whitespace so the guard
    matches case-insensitively."""
    mock_get_business.return_value = {
        "email": "Operator@Test.COM",
        "support_email": "  Ops@Test.com  ",
    }
    result = email_poller._business_sender_emails()
    assert result == {"operator@test.com", "ops@test.com"}


def test_source_has_business_sender_guard():
    """Brief 164: email_poller.py must contain the business-sender guard in the UID loop."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "..",
                             "agents", "marina", "email_poller.py")).read()
    assert "_business_sender_emails" in src, (
        "Brief 164: _business_sender_emails helper missing from email_poller.py"
    )
    assert "Skipped business-sender email" in src, (
        "Brief 164: business-sender guard log line missing from email_poller.py"
    )
    guard_idx = src.find("Skipped business-sender email")
    assert guard_idx > 0
    pre_guard = src[max(0, guard_idx - 500):guard_idx]
    assert "_is_relay" in pre_guard and "_is_escalation" in pre_guard, (
        "Brief 164: the guard must preserve relay/escalation subjects"
    )
