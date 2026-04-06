"""Tests for Brief 053 — stale thread reset on new conversation."""
import sys, os, time
from email.message import Message

from agents.marina import email_poller


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
