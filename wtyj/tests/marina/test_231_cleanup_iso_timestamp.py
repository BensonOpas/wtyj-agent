"""Tests for Brief 231 — _cleanup_stale_data accepts both ISO-string and
numeric epoch last_activity values."""
import time
from datetime import datetime, timezone, timedelta

from agents.marina import email_poller


def _make_state(threads):
    return {"threads": threads}


def test_iso_string_recent_does_not_archive():
    """Brief 231: a thread with an ISO-string last_activity that is RECENT
    must not be archived (regression: was crashing with TypeError before)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    state = _make_state({
        "subj:alice@example.com:test": {
            "last_activity": now_iso,
            "flags": {},
            "messages": [],
        }
    })
    email_poller._cleanup_stale_data(state, time.time())
    assert "subj:alice@example.com:test" in state["threads"]


def test_iso_string_old_archives():
    """Brief 231: a thread with an ISO-string last_activity older than
    THREAD_RETENTION_DAYS gets archived correctly."""
    old_iso = (datetime.now(timezone.utc)
               - timedelta(days=email_poller.THREAD_RETENTION_DAYS + 5)
               ).isoformat()
    state = _make_state({
        "subj:bob@example.com:old": {
            "last_activity": old_iso,
            "flags": {},
            "messages": [],
        }
    })
    email_poller._cleanup_stale_data(state, time.time())
    assert "subj:bob@example.com:old" not in state["threads"]


def test_numeric_epoch_still_works():
    """Brief 231: legacy numeric last_activity continues to work for
    backward compat (email_poller.py's own write path uses numeric)."""
    state = _make_state({
        "subj:carol@example.com:legacy": {
            "last_activity": time.time(),
            "flags": {},
            "messages": [],
        },
        "subj:dan@example.com:legacy_old": {
            "last_activity": time.time() - (
                email_poller.THREAD_RETENTION_DAYS + 5) * 86400,
            "flags": {},
            "messages": [],
        },
    })
    email_poller._cleanup_stale_data(state, time.time())
    assert "subj:carol@example.com:legacy" in state["threads"]
    assert "subj:dan@example.com:legacy_old" not in state["threads"]


def test_malformed_iso_string_does_not_archive_or_raise():
    """Brief 231: a malformed last_activity is treated as 'unknown' per
    Brief 162's defensive principle — skip, never archive on guess, never
    raise."""
    state = _make_state({
        "subj:eve@example.com:malformed": {
            "last_activity": "not-a-real-timestamp",
            "flags": {},
            "messages": [],
        }
    })
    email_poller._cleanup_stale_data(state, time.time())
    assert "subj:eve@example.com:malformed" in state["threads"]


def test_protection_flags_skip_archive_with_iso_string():
    """Brief 231: hold_created and awaiting_relay flags continue to
    protect threads from archive even when last_activity is an old ISO
    string."""
    old_iso = (datetime.now(timezone.utc)
               - timedelta(days=email_poller.THREAD_RETENTION_DAYS + 10)
               ).isoformat()
    state = _make_state({
        "subj:frank@example.com:hold": {
            "last_activity": old_iso,
            "flags": {"hold_created": True},
            "messages": [],
        },
        "subj:grace@example.com:relay": {
            "last_activity": old_iso,
            "flags": {"awaiting_relay": True},
            "messages": [],
        },
    })
    email_poller._cleanup_stale_data(state, time.time())
    assert "subj:frank@example.com:hold" in state["threads"]
    assert "subj:grace@example.com:relay" in state["threads"]
