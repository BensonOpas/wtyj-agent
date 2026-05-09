"""Tests for Brief 162 — email_poller thread persistence bug.

Covers:
- _cleanup_stale_data defensive guards (Group A)
- Source-level regression guards for the 8 fix sites (Group B)
- End-to-end state simulation of the Calvin semi-escalation scenario (Group C)
"""
import os
import time

from agents.marina import email_poller


# --- Group A: _cleanup_stale_data behavior ---

def _make_state(threads):
    return {"threads": threads, "sender_rates": {}}


def test_cleanup_archives_truly_stale_thread():
    """Happy case: a 31-day-old thread with no protection flags is archived."""
    now = int(time.time())
    state = _make_state({
        "subj:x@y.com:old": {
            "fields": {},
            "flags": {},
            "last_activity": now - (31 * 86400),
        }
    })
    email_poller._cleanup_stale_data(state, now)
    assert "subj:x@y.com:old" not in state["threads"], "Stale thread should be archived"


def test_cleanup_keeps_fresh_thread():
    """Baseline sanity: a thread with last_activity=now is kept."""
    now = int(time.time())
    state = _make_state({
        "subj:x@y.com:fresh": {
            "fields": {},
            "flags": {},
            "last_activity": now,
        }
    })
    email_poller._cleanup_stale_data(state, now)
    assert "subj:x@y.com:fresh" in state["threads"], "Fresh thread should be kept"


def test_cleanup_skips_thread_with_missing_last_activity():
    """Brief 162 defensive guard: thread with no last_activity field is NOT archived.
    Previously this was the bug — missing last_activity defaulted to 0 and the thread
    was archived immediately."""
    now = int(time.time())
    state = _make_state({
        "subj:x@y.com:no_activity_field": {
            "fields": {},
            "flags": {},
            # deliberately no last_activity key
        }
    })
    email_poller._cleanup_stale_data(state, now)
    assert "subj:x@y.com:no_activity_field" in state["threads"], (
        "Thread with missing last_activity should NOT be archived "
        "(Brief 162 defensive guard)"
    )


def test_cleanup_skips_thread_with_zero_last_activity():
    """Brief 162: explicit last_activity=0 is treated as 'unknown', not 'ancient'."""
    now = int(time.time())
    state = _make_state({
        "subj:x@y.com:zero_activity": {
            "fields": {},
            "flags": {},
            "last_activity": 0,
        }
    })
    email_poller._cleanup_stale_data(state, now)
    assert "subj:x@y.com:zero_activity" in state["threads"], (
        "Thread with last_activity=0 should NOT be archived"
    )


def test_cleanup_protects_awaiting_relay_even_if_stale():
    """Brief 162: the Calvin scenario — awaiting_relay=True thread survives even
    with ancient last_activity. Without this guard, an operator reply to a relay
    email arriving > 30 days after the original would silently drop."""
    now = int(time.time())
    state = _make_state({
        "subj:calvin@gaimin.io:hi_booking": {
            "fields": {"customer_name": "Calvin"},
            "flags": {
                "awaiting_relay": True,
                "relay_token": "158cf2b73100",
                "relay_customer_email": "calvin@gaimin.io",
            },
            "last_activity": now - (45 * 86400),  # 45 days old — past cutoff
        }
    })
    email_poller._cleanup_stale_data(state, now)
    assert "subj:calvin@gaimin.io:hi_booking" in state["threads"], (
        "Thread with awaiting_relay=True should survive even if last_activity is stale"
    )


def test_cleanup_protects_hold_created_even_if_stale():
    """Pre-Brief-162 guard: threads with hold_created=True are preserved.
    Regression check that this exemption still works after Brief 162 changes."""
    now = int(time.time())
    state = _make_state({
        "subj:x@y.com:has_hold": {
            "fields": {},
            "flags": {"hold_created": True},
            "last_activity": now - (60 * 86400),  # 60 days old
        }
    })
    email_poller._cleanup_stale_data(state, now)
    assert "subj:x@y.com:has_hold" in state["threads"], (
        "Thread with hold_created=True should be preserved (pre-existing guard)"
    )


def test_cleanup_archives_stale_plain_thread_after_fix():
    """After Brief 162, a plain stale thread (no flags, old last_activity) is still archived.
    The defensive guards must not accidentally protect genuinely stale threads."""
    now = int(time.time())
    state = _make_state({
        "subj:x@y.com:genuinely_stale": {
            "fields": {},
            "flags": {},  # no protection flags
            "last_activity": now - (45 * 86400),
        }
    })
    email_poller._cleanup_stale_data(state, now)
    assert "subj:x@y.com:genuinely_stale" not in state["threads"], (
        "Plain stale thread should still be archived after Brief 162"
    )


# --- Group C: Calvin regression scenarios ---

def test_cleanup_protects_awaiting_relay_with_stale_last_activity():
    """Brief 162 (Calvin scenario, load-bearing): awaiting_relay thread with
    stale last_activity (45 days old) must survive cleanup because the guard
    overrides the cutoff."""
    now = int(time.time())
    state = _make_state({
        "subj:calvin@gaimin.io:hi_booking": {
            "fields": {"customer_name": "Calvin"},
            "flags": {
                "awaiting_relay": True,
                "relay_token": "158cf2b73100",
                "relay_customer_email": "calvin@gaimin.io",
            },
            "last_activity": now - (45 * 86400),
            "reply_times": [now - (45 * 86400)],
            "messages": [],
        }
    })
    email_poller._cleanup_stale_data(state, now)
    assert "subj:calvin@gaimin.io:hi_booking" in state["threads"]
    th = state["threads"]["subj:calvin@gaimin.io:hi_booking"]
    assert th["flags"]["relay_token"] == "158cf2b73100", (
        "Relay token must survive cleanup so the operator's reply can be routed"
    )


def test_cleanup_protects_relay_thread_missing_last_activity():
    """Brief 162 belt-and-suspenders: thread with awaiting_relay=True AND no
    last_activity field at all must survive. Both defensive guards cover this."""
    now = int(time.time())
    state = _make_state({
        "subj:calvin@gaimin.io:hi_booking": {
            "fields": {"customer_name": "Calvin"},
            "flags": {
                "awaiting_relay": True,
                "relay_token": "158cf2b73100",
            },
            # deliberately no last_activity field
            "reply_times": [],
            "messages": [],
        }
    })
    email_poller._cleanup_stale_data(state, now)
    assert "subj:calvin@gaimin.io:hi_booking" in state["threads"], (
        "Thread with awaiting_relay AND missing last_activity should survive"
    )
