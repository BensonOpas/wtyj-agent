# BRIEF 231 — Fix email-poller crash on ISO-string `last_activity`
**Status:** Draft | **Files:** `wtyj/agents/marina/email_poller.py`, `wtyj/tests/marina/test_231_cleanup_iso_timestamp.py` | **Depends on:** Brief 162 (defensive guards in `_cleanup_stale_data`), Brief 210 (`email_append_assistant_message` writes ISO `last_activity`), Brief 218 (`email_mark_deleted` writes ISO `last_activity`) | **Blocks:** new inbound email being ingested on any tenant whose email_thread_state.json contains a thread with an ISO-string `last_activity`

## Context

SR reported the unboks dashboard "se ha parado" — no new email arriving. Production diagnosis from `wtyj-unboks` `/app/logs/email_poller.log`:

```
IMAP connected (token refresh in 2700s)
Error: '<' not supported between instances of 'str' and 'int'
Backing off 300s (consecutive errors: 9)
```

Every poll iteration TypeErrors. Root cause is `_cleanup_stale_data` at `email_poller.py:141`:

```python
if last < cutoff:
    to_delete.append(tk)
```

Where `last = th.get("last_activity") or 0` and `cutoff = now - (THREAD_RETENTION_DAYS * 86400)`. `cutoff` is a float epoch. `last` is a string when written by `state_registry.email_append_assistant_message` (Brief 210, line 1120) or `state_registry.email_mark_deleted` (Brief 218, line 1063) — both write `datetime.now(timezone.utc).isoformat()`. The legacy writer in `email_poller.py` itself uses numeric epoch.

After SR exercised the dashboard's reply/delete buttons enough times, every thread on unboks ended up with an ISO-string `last_activity`. The cleanup runs every poll iteration → `str < float` → TypeError → backoff → retry forever. New email never processes.

Verification on production state: `cat /root/clients/unboks/config/email_thread_state.json` — all 7 threads have `flags.deleted=true` AND ISO-string `last_activity` from the dashboard write paths.

## Why This Approach

**Chosen:** parse ISO strings as `datetime.fromisoformat(...).timestamp()` when `last_activity` is a string; pass through numeric values when it's a number; skip the thread when parsing fails. Mirrors Brief 162's "missing/zero last_activity → don't archive" defensive principle: a malformed value is treated as "unknown, leave alone" rather than guessed.

**Why not normalize all writers to one format.** The right long-term fix is one canonical type for `last_activity` everywhere, but normalizing it requires updating all writers (`email_poller.py` legacy paths, `email_append_assistant_message`, `email_mark_deleted`) AND running a one-shot migration over existing tenant state files. Tonight that's three more touch points, more tests, and a data migration. The poller is broken NOW. Fix the read side defensively, hand the long-term canonicalization to a follow-up.

**Why not strip the cleanup function entirely.** Brief 162 added it on purpose — old threads accumulate disk + memory. Removing it pushes the problem onto another brief.

**Why a single fix line, not error suppression.** Wrapping `last < cutoff` in `try/except TypeError` would technically prevent the crash but leave the cleanup never archiving any ISO-stringed thread. Parsing the ISO string is a real fix; suppression would be a band-aid.

**Tradeoff:** `datetime.fromisoformat` accepts a wide range of ISO 8601 inputs (with and without offset, with and without microseconds). Both writers in question emit `datetime.now(timezone.utc).isoformat()` which fromisoformat parses cleanly. A malformed string falls through to `continue` (don't archive).

## Instructions

In `wtyj/agents/marina/email_poller.py`, replace the body of `_cleanup_stale_data`'s thread-iteration loop. Find the existing block at lines 130-142 and replace it with this version that handles both numeric and ISO-string `last_activity`:

```python
    for tk, th in threads.items():
        last_raw = th.get("last_activity") or 0
        flags = th.get("flags", {})
        # Brief 162: skip if any protection flag is set
        if flags.get("hold_created"):
            continue
        if flags.get("awaiting_relay"):
            continue
        # Brief 162: missing or zero last_activity => unknown, don't archive
        if not last_raw:
            continue
        # Brief 231: dashboard write paths (email_append_assistant_message,
        # email_mark_deleted) store last_activity as an ISO 8601 string;
        # the legacy email_poller paths store a numeric epoch. Accept both.
        # Malformed strings fall through to "don't archive" per Brief 162's
        # defensive principle (treat unknown as unknown, not as ancient).
        if isinstance(last_raw, str):
            try:
                last = datetime.fromisoformat(last_raw).timestamp()
            except (ValueError, TypeError):
                continue
        else:
            last = last_raw
        if last < cutoff:
            to_delete.append(tk)
```

No other changes needed. The `datetime` import is already present at the top of the file (`from datetime import datetime, timezone, timedelta`).

## Tests

Place at `wtyj/tests/marina/test_231_cleanup_iso_timestamp.py`. Use stdlib only — no fixtures from other modules:

```python
"""Tests for Brief 231 — _cleanup_stale_data accepts both ISO-string and
numeric epoch last_activity values."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

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
    # Should not raise; should not archive a fresh thread.
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
            "last_activity": time.time(),  # float epoch, recent
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
```

## Success Condition

After deploy, `email_poller.log` on unboks stops emitting `Error: '<' not supported between instances of 'str' and 'int'`. The poller resumes processing UNSEEN emails normally — `consecutive_errors` resets to 0 and IMAP backoff stops escalating. New regression tests in `test_231_cleanup_iso_timestamp.py` cover the four shapes (ISO-recent, ISO-old, numeric, malformed) plus the protection-flag interaction. Full suite stays at 1073 + 5 new = 1078 passing / 0 failures.

## Rollback

`git revert <commit>`. Restores the broken `last < cutoff` comparison; the poller goes back to TypeErroring. No data migration risk — the change is read-side only. The bug returns until a follow-up.
