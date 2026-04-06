# BRIEF 053 — Stale thread reset on new conversation
**Status:** Draft | **Files:** `src/email_poller.py` | **Depends on:** none | **Blocks:** none

## Context
Thread state is keyed by `sender_email + normalized_subject` (fallback when no
References/In-Reply-To match). This key has no expiration. When a customer sends
a new email with the same subject as a previous conversation (e.g. "booking"),
the old thread's accumulated fields, flags, and messages are loaded and injected
into the Claude prompt. This caused a live bug: Benson sent a new email with
subject "booking" and inherited fields (`customer_name: 'Jan'`,
`phone: '+5999 123 4567'`, `departure_time: '08:30'`) from a weeks-old test
thread. Claude saw contradictory context and produced nonsensical replies.

The field merge logic (lines 526-531) only overwrites fields Claude explicitly
returns. Fields the customer hasn't mentioned yet (name, phone, departure_time)
survive from the stale thread because Claude doesn't return them.

## Why This Approach
Three options were considered:

1. **TTL-based thread expiry** — delete threads older than N days. Problem: a
   legitimate multi-day conversation would lose state. Would need careful tuning
   and could still fail for very long booking threads.

2. **New-email detection + thread reset** — when an inbound message has NO
   In-Reply-To and NO References headers (i.e. it's a brand-new email, not a
   reply), and the subject-based fallback matches an existing thread, reset that
   thread to a fresh state. This is clean because a truly new email always lacks
   reply headers, while a reply within the same conversation always has them.

3. **Include message history in prompt** — give Claude full conversation context
   so it can reason about staleness. Too expensive and doesn't fix the root
   cause.

**Chosen: Option 2.** It's deterministic, zero-risk to active conversations,
and fixes the exact failure mode observed. A new email is unambiguously a new
conversation — resetting the thread is correct behavior.

Additionally, as a safety net: when the subject-fallback key matches an existing
thread whose last activity was more than 24 hours ago AND the inbound message
has no reply headers, always reset. This catches edge cases where an email
client might strip headers.

## Source Material

**resolve_thread_key()** (lines 181-199): Returns subject-based fallback when
References/In-Reply-To don't match `mid_index`.

**Thread loading** (lines 377-384):
```python
th = threads.get(thread_key, {
    "fields": {},
    "flags": {},
    "last_customer_hash": "",
    "reply_times": [],
    "messages": []
})
```

**Field merge** (lines 526-531): Only overwrites fields Claude returns. Stale
fields survive if Claude doesn't mention them.

**Thread state persistence**: `config/email_thread_state.json`, loaded once at
startup, saved after every message.

## Instructions

### Step 1 — Add two helper functions

Add after `resolve_thread_key()` (after line 199), before the
`# ========= BOOKING VALIDATION HELPERS =========` comment:

```python

def _is_new_email(msg) -> bool:
    """Return True if the message has no reply headers (brand-new email)."""
    refs = (msg.get("References") or "").strip()
    irt = (msg.get("In-Reply-To") or "").strip()
    return not refs and not irt


_FRESH_THREAD = {
    "fields": {},
    "flags": {},
    "last_customer_hash": "",
    "reply_times": [],
    "messages": [],
}


def _maybe_reset_stale_thread(msg, thread_key: str, th: dict, threads: dict, now: int) -> dict:
    """If msg is a new email hitting a stale (>24h) existing thread, return a fresh thread dict.
    Otherwise return th unchanged."""
    if not _is_new_email(msg):
        return th
    if thread_key not in threads:
        return th
    _last_activity = th.get("last_activity", 0)
    _last_reply = max(th.get("reply_times", [0]) or [0])
    _last_seen = max(_last_activity, _last_reply)
    _age_hours = (now - _last_seen) / 3600 if _last_seen else 999
    if _age_hours > 24:
        log(f"Stale thread reset: {thread_key} (last activity {_age_hours:.0f}h ago)")
        return dict(_FRESH_THREAD, messages=[], reply_times=[])
    return th
```

### Step 2 — Move `now` earlier and call `_maybe_reset_stale_thread`

Move `now = int(time.time())` from line 396 to immediately BEFORE the thread
loading at line 377. Delete the original `now = int(time.time())` at old line
396 so there is exactly one assignment.

After thread loading (line 384, after `th = threads.get(...)`) and BEFORE the
duplicate content check, add one line:

```python
                th = _maybe_reset_stale_thread(msg, thread_key, th, threads, now)
```

### Step 3 — Add `last_activity` timestamp

Add `th["last_activity"] = now` right before `threads[thread_key] = th` at
line 913 (Step 7 persist block).

### Step 4 — Update file header

Change `LAST MODIFIED` to `Brief 053`.

## Tests

Create `bluemarlin/tests/test_stale_thread.py`.
All tests call the real `_is_new_email()` and `_maybe_reset_stale_thread()`
functions from `email_poller.py` — no inline re-implementations.

```python
"""Tests for Brief 053 — stale thread reset on new conversation."""
import sys, os, time
from email.message import Message

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import email_poller


def _make_msg(from_addr="test@example.com", subject="booking",
              in_reply_to=None, references=None):
    msg = Message()
    msg["From"] = from_addr
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    return msg


def _make_thread(fields=None, flags=None, last_activity=None,
                 reply_times=None, messages=None):
    th = {
        "fields": fields or {},
        "flags": flags or {},
        "last_customer_hash": "",
        "reply_times": reply_times or [],
        "messages": messages or [],
    }
    if last_activity is not None:
        th["last_activity"] = last_activity
    return th


# --- _is_new_email tests ---

def test_is_new_email_no_headers():
    msg = _make_msg()
    assert email_poller._is_new_email(msg) == True
    print("PASS: test_is_new_email_no_headers")

def test_is_new_email_with_in_reply_to():
    msg = _make_msg(in_reply_to="<abc@mail.com>")
    assert email_poller._is_new_email(msg) == False
    print("PASS: test_is_new_email_with_in_reply_to")

def test_is_new_email_with_references():
    msg = _make_msg(references="<abc@mail.com>")
    assert email_poller._is_new_email(msg) == False
    print("PASS: test_is_new_email_with_references")

# --- _maybe_reset_stale_thread tests ---

def test_stale_48h_thread_resets():
    """New email hitting a 48h-old thread → reset."""
    old_ts = int(time.time()) - (48 * 3600)
    thread_key = "subj:test@example.com:booking"
    th = _make_thread(
        fields={"customer_name": "Jan", "phone": "+5999 123 4567", "trip_key": "klein_curacao"},
        flags={"booking_confirmed": True},
        last_activity=old_ts,
        reply_times=[old_ts],
        messages=[{"role": "customer", "body": "old msg"}],
    )
    threads = {thread_key: th}
    msg = _make_msg()
    now = int(time.time())

    result = email_poller._maybe_reset_stale_thread(msg, thread_key, th, threads, now)
    assert result["fields"] == {}, f"FAIL: stale thread fields should be empty, got {result['fields']}"
    assert result["flags"] == {}, f"FAIL: stale thread flags should be empty, got {result['flags']}"
    assert result["messages"] == [], f"FAIL: stale thread messages should be empty"
    print("PASS: test_stale_48h_thread_resets")

def test_fresh_2h_thread_not_reset():
    """New email hitting a 2h-old thread → keep state."""
    recent_ts = int(time.time()) - (2 * 3600)
    thread_key = "subj:test@example.com:booking"
    th = _make_thread(
        fields={"customer_name": "Alice", "trip_key": "snorkeling_3in1"},
        last_activity=recent_ts,
        reply_times=[recent_ts],
    )
    threads = {thread_key: th}
    msg = _make_msg()
    now = int(time.time())

    result = email_poller._maybe_reset_stale_thread(msg, thread_key, th, threads, now)
    assert result["fields"]["customer_name"] == "Alice", f"FAIL: fresh thread should keep fields"
    assert result["fields"]["trip_key"] == "snorkeling_3in1", "FAIL: fresh thread should keep trip_key"
    print("PASS: test_fresh_2h_thread_not_reset")

def test_reply_to_old_thread_not_reset():
    """Reply (has In-Reply-To) to a 48h-old thread → keep state."""
    old_ts = int(time.time()) - (48 * 3600)
    thread_key = "subj:test@example.com:booking"
    th = _make_thread(
        fields={"customer_name": "Jan", "trip_key": "klein_curacao"},
        last_activity=old_ts,
        reply_times=[old_ts],
    )
    threads = {thread_key: th}
    msg = _make_msg(in_reply_to="<original-msg@outlook.com>")
    now = int(time.time())

    result = email_poller._maybe_reset_stale_thread(msg, thread_key, th, threads, now)
    assert result["fields"]["customer_name"] == "Jan", "FAIL: reply should not reset thread"
    assert result["fields"]["trip_key"] == "klein_curacao", "FAIL: reply should keep trip_key"
    print("PASS: test_reply_to_old_thread_not_reset")

def test_legacy_thread_no_last_activity():
    """Old thread without last_activity field → fallback to reply_times."""
    old_ts = int(time.time()) - (72 * 3600)
    thread_key = "subj:test@example.com:booking"
    th = _make_thread(
        fields={"customer_name": "OldCustomer"},
        reply_times=[old_ts],
    )
    # no "last_activity" — legacy thread
    threads = {thread_key: th}
    msg = _make_msg()
    now = int(time.time())

    result = email_poller._maybe_reset_stale_thread(msg, thread_key, th, threads, now)
    assert result["fields"] == {}, f"FAIL: legacy stale thread should reset, got {result['fields']}"
    print("PASS: test_legacy_thread_no_last_activity")

def test_empty_timing_data_resets():
    """Thread with no timing data at all → treat as stale, reset."""
    thread_key = "subj:test@example.com:booking"
    th = _make_thread(fields={"customer_name": "Ghost"})
    threads = {thread_key: th}
    msg = _make_msg()
    now = int(time.time())

    result = email_poller._maybe_reset_stale_thread(msg, thread_key, th, threads, now)
    assert result["fields"] == {}, f"FAIL: thread with no timing data should reset, got {result['fields']}"
    print("PASS: test_empty_timing_data_resets")

def test_new_thread_key_not_in_threads():
    """Brand-new thread key not in threads dict → return th unchanged (no crash)."""
    thread_key = "subj:newcustomer@example.com:booking"
    th = _make_thread()
    threads = {}  # thread_key not in threads
    msg = _make_msg(from_addr="newcustomer@example.com")
    now = int(time.time())

    result = email_poller._maybe_reset_stale_thread(msg, thread_key, th, threads, now)
    assert result is th, "FAIL: new thread key should return th unchanged"
    print("PASS: test_new_thread_key_not_in_threads")


if __name__ == "__main__":
    test_is_new_email_no_headers()
    test_is_new_email_with_in_reply_to()
    test_is_new_email_with_references()
    test_stale_48h_thread_resets()
    test_fresh_2h_thread_not_reset()
    test_reply_to_old_thread_not_reset()
    test_legacy_thread_no_last_activity()
    test_empty_timing_data_resets()
    test_new_thread_key_not_in_threads()
    print(f"\n9/9 tests passed.")
```

## Success Condition
A new email from the same sender+subject as a >24h-old thread gets a fresh
thread state. Replies to active conversations are unaffected.

## Rollback
`git checkout HEAD~1 -- bluemarlin/src/email_poller.py` and remove test file.
Thread state JSON does not need reverting — reset threads simply start fresh.
