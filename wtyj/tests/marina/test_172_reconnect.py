"""Tests for Brief 172 — reconnect sweep additions after SR merge.

Covers the new escalation delete endpoint + helper. The other sweep reconnection
work is frontend-only; the existing brief 165 + 167 backend tests still cover
the delete/lookup paths my dashboard frontend calls.
"""
import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from shared import state_registry


def test_delete_escalation_removes_row():
    """Brief 172: delete_escalation removes a pending_notifications row."""
    nid = state_registry.create_pending_notification(
        "escalation", "whatsapp", "TEST_B172_ID", "Test B172",
        "subj", "body"
    )
    assert nid > 0

    ok = state_registry.delete_escalation(nid)
    assert ok is True

    rows = [e for e in state_registry.get_all_escalations() if e["id"] == nid]
    assert rows == []


def test_delete_escalation_nonexistent_returns_false():
    ok = state_registry.delete_escalation(99999999)
    assert ok is False



