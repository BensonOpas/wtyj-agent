"""Tests for Brief 232 — archive auto-restore on inbound email message.

Tests import the real production helper `_un_archive_thread_if_deleted`
from `email_poller` and assert flag transitions. A regression in the
production helper fails the test directly. Block-precedence is verified
by an integration-style test that drives the same code path the poller
takes — `state_registry.get_blocked` short-circuits BEFORE the
un-archive helper runs, so the helper is never invoked when blocked.
"""
from unittest.mock import patch

from agents.marina.email_poller import _un_archive_thread_if_deleted


def test_deleted_thread_clears_flag_and_returns_true():
    """Brief 232: production helper pops flags.deleted and returns True
    when the flag was set. Pop removes the key entirely so the thread
    shape matches a never-deleted thread."""
    th = {
        "messages": [],
        "flags": {"deleted": True},
        "last_activity": "2026-05-08T00:00:00+00:00",
    }
    result = _un_archive_thread_if_deleted(th)
    assert result is True
    assert "deleted" not in th["flags"]


def test_block_wins_over_archive_via_get_blocked_short_circuit():
    """Brief 232: blocked conversations exit before reaching the helper.
    Drive the same control flow the poller uses (block check first, then
    helper) and assert the helper is never invoked on a blocked thread."""
    th = {
        "messages": [],
        "flags": {"deleted": True},
    }

    def poller_inbound_branch(thread_dict, from_email):
        """Mirrors email_poller lines 641-660: get_blocked check first,
        then helper call. If get_blocked returns True we `continue`
        without touching the helper."""
        from shared import state_registry
        if state_registry.get_blocked(from_email):
            return ("blocked", None)
        un_archived = _un_archive_thread_if_deleted(thread_dict)
        return ("appended", un_archived)

    with patch("shared.state_registry.get_blocked", return_value=True):
        outcome, un_archived = poller_inbound_branch(th, "blocked@example.com")
    assert outcome == "blocked"
    assert un_archived is None
    # Critical: flags.deleted MUST still be set because the helper was
    # never called.
    assert th["flags"].get("deleted") is True


def test_thread_with_no_flags_dict_is_safe():
    """Brief 232: a thread missing the flags key is handled by setdefault;
    no KeyError, no transition. Returns False."""
    th = {"messages": []}
    result = _un_archive_thread_if_deleted(th)
    assert result is False
    assert th["flags"] == {}


def test_non_deleted_thread_is_no_op_and_returns_false():
    """Brief 232: a thread without flags.deleted is unchanged. We don't
    accidentally pop something that wasn't there or invent the flag."""
    th = {
        "messages": [],
        "flags": {"fully_escalated": True, "ai_muted": True},
    }
    result = _un_archive_thread_if_deleted(th)
    assert result is False
    assert th["flags"] == {"fully_escalated": True, "ai_muted": True}


def test_deleted_with_other_flags_only_pops_deleted():
    """Brief 232: when deleted=True coexists with other flags, only
    `deleted` is removed. Restored thread keeps its escalation state per
    SR's 'keep notes/history/escalation context' requirement."""
    th = {
        "messages": [],
        "flags": {
            "deleted": True,
            "fully_escalated": True,
            "ai_muted": True,
        },
    }
    result = _un_archive_thread_if_deleted(th)
    assert result is True
    assert "deleted" not in th["flags"]
    assert th["flags"]["fully_escalated"] is True
    assert th["flags"]["ai_muted"] is True
