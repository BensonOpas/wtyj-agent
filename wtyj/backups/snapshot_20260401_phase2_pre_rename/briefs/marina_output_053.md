# OUTPUT 053 — Stale thread reset on new conversation

## What was done

1. Added `_is_new_email(msg)` helper — returns True when a message has no In-Reply-To or References headers (brand-new email, not a reply).

2. Added `_maybe_reset_stale_thread(msg, thread_key, th, threads, now)` — testable function that returns a fresh thread dict when a new email hits an existing thread older than 24 hours. Returns th unchanged for replies (has headers) or fresh threads (<24h).

3. Moved `now = int(time.time())` from the anti-loop guard section to before thread loading, so it's available for both staleness check and anti-loop guard.

4. Added `th["last_activity"] = now` in the Step 7 persist block so future staleness checks have reliable timing data even for legacy threads.

5. Updated file header to Brief 053.

## Files changed
- `src/email_poller.py` — added `_is_new_email`, `_FRESH_THREAD`, `_maybe_reset_stale_thread`, moved `now`, added `last_activity` persist

## Test results
```
PASS: test_is_new_email_no_headers
PASS: test_is_new_email_with_in_reply_to
PASS: test_is_new_email_with_references
PASS: test_stale_48h_thread_resets
PASS: test_fresh_2h_thread_not_reset
PASS: test_reply_to_old_thread_not_reset
PASS: test_legacy_thread_no_last_activity
PASS: test_empty_timing_data_resets
PASS: test_new_thread_key_not_in_threads

9/9 tests passed.
```

## Nothing unexpected
All changes match the brief exactly. No additional files modified.
