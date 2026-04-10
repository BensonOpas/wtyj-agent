# BRIEF 179 — Email poller resilience: connection cleanup, exponential backoff, forced exit
**Status:** Draft | **Files:** `wtyj/agents/marina/email_poller.py`, new `wtyj/tests/marina/test_179_poller_resilience.py` | **Depends on:** None | **Blocks:** None

## Context

Production email poller has logged **106 IMAP errors** — two patterns repeating:
```
Error: SELECT command error: BAD [b'Command Error. 12']
Error: socket error: EOF
```

Benson received multiple `[ALERT] Marina poller: 3 consecutive errors` emails. The error count suggests the poller was stuck in a failure loop for ~17 minutes (106 × 10s poll interval). Investigated the code and found three design gaps:

1. **No connection cleanup on error.** When `im.select(MAILBOX)` fails (line 515) or the socket drops, the exception is caught at the top-level handler (`email_poller.py:1378`), but the dead IMAP socket `im` is never closed. Dead sockets accumulate, and Outlook may see multiple ghost connections from the same IP, worsening the rate-limiting that likely caused the error in the first place.

2. **No exponential backoff.** After an error, the poller sleeps a fixed `POLL_INTERVAL` (10s, line 44) and retries. On consecutive failures this means 6 reconnection attempts per minute against a server that's already rejecting us — the opposite of what IMAP server operators want.

3. **No forced process exit.** The `while True` loop (line 511) catches all exceptions and never exits. Supervisord is configured with `autorestart=unexpected` (`supervisord.conf`), so it WOULD restart the process on exit, giving a clean slate (new IMAP connection, new OAuth token fetch, fresh memory). But the process never exits, so supervisord never gets the chance. The poller can spin in a failure loop indefinitely.

Additionally: the comment at line 65 says "3 × 30s = 90 seconds" but `POLL_INTERVAL` is 10s, not 30s. Misleading.

The `SELECT command error: BAD [b'Command Error. 12']` itself is likely caused by Azure/Outlook rate-limiting or stale IMAP session state — not a token issue (the authentication at `imap_connect()` line 218-222 succeeds, otherwise we'd see an AUTH error, not SELECT). The fix is defensive: even if we can't prevent the server-side error, we can handle it gracefully instead of hammering the server 6 times a minute.

## Why This Approach

Three alternatives were considered:

1. **(CHOSEN) Connection cleanup + exponential backoff + forced exit after threshold.** Minimal changes to the existing polling loop, addresses all three gaps, and lets supervisord do its job. Backoff caps at 5 minutes, exit after 30 consecutive errors (~5 min with backoff).

2. **Persistent IMAP connection with keepalive.** Instead of reconnecting on every poll, keep the IMAP connection open across iterations. Lower overhead, but adds connection-state management complexity (NOOP keepalive, reconnect on stale socket, etc.). Rejected — higher risk for a production fix. Can be a follow-up optimization.

3. **Switch to Microsoft Graph API (REST) instead of IMAP.** Eliminates the IMAP socket entirely. Better long-term, but a much larger change touching auth flow, message fetch, and reply send. Not a one-brief fix.

## Instructions

### Step 1: Add connection cleanup in the error handler

At `email_poller.py:1378`, after `log(f"Error: {ex}")`, add explicit IMAP cleanup before sleeping:

```python
except Exception as ex:
    _consecutive_errors += 1
    log(f"Error: {ex}")
    # Brief 179: clean up the dead IMAP connection so ghost sockets
    # don't accumulate and worsen server-side rate limiting.
    try:
        im.close()
    except Exception:
        pass
    try:
        im.logout()
    except Exception:
        pass
```

The `im` variable is in scope because it's assigned at line 513. If `imap_connect()` itself threw (before `im` was assigned), `im` will reference the previous iteration's value or be unbound — the nested `try/except` handles both cases gracefully.

Important: the `im` variable must be pre-initialized to `None` before the `while True` loop (line 511) so the first-iteration error path doesn't hit `NameError`. Add `im = None` at line 510.

### Step 2: Replace fixed sleep with exponential backoff

Replace the final `time.sleep(POLL_INTERVAL)` at line 1393 with:

```python
if _consecutive_errors > 0:
    # Brief 179: exponential backoff — 10s, 20s, 40s, 80s, 160s, cap at 300s.
    # Reduces hammering against a server that's already rejecting us.
    _backoff = min(POLL_INTERVAL * (2 ** (_consecutive_errors - 1)), 300)
    log(f"Backing off {_backoff}s (consecutive errors: {_consecutive_errors})")
    time.sleep(_backoff)
else:
    time.sleep(POLL_INTERVAL)
```

Note: the backoff uses `_consecutive_errors - 1` as the exponent so the FIRST error still waits 10s (the normal interval). Second error = 20s. Third = 40s. Fourth = 80s. Fifth = 160s. Sixth+ = 300s (capped).

### Step 3: Add forced process exit after threshold

Add a new constant near line 67:

```python
_ERROR_EXIT_THRESHOLD = 30  # ~5 min with backoff. Supervisord restarts fresh.
```

In the error handler, after the alert block (line 1388), add:

```python
if _consecutive_errors >= _ERROR_EXIT_THRESHOLD:
    log(f"FATAL: {_consecutive_errors} consecutive errors. Exiting for supervisord restart.")
    sys.exit(1)
```

Verify `import sys` is present at the top of the file (it is — line 7).

### Step 4: Fix the stale comment

Line 65: change `3 × 30s = 90 seconds` to `3 × 10s = 30 seconds (at default POLL_INTERVAL=10)`.

## Tests

Create `wtyj/tests/marina/test_179_poller_resilience.py`:

1. **Backoff calculation.** Given `POLL_INTERVAL=10` and consecutive_errors=1,2,3,5,10, verify the sleep duration is 10, 20, 40, 160, 300 (capped). Test the formula: `min(10 * 2**(n-1), 300)`.

2. **Backoff resets on success.** After errors, if `_consecutive_errors` resets to 0, sleep should be `POLL_INTERVAL` (10s).

3. **Exit threshold.** Verify that when `_consecutive_errors >= 30`, the code calls `sys.exit(1)`. Mock `sys.exit` to capture the call without actually exiting. 

4. **Connection cleanup on error.** Mock `im.close()` and `im.logout()`, trigger an exception in the main loop, verify both cleanup methods are called.

5. **Cleanup handles unbound im.** When `imap_connect()` itself throws (before `im` is assigned to a new value), verify the error handler doesn't crash on `im.close()` — it should silently skip cleanup (im is None).

## Success Condition

842 baseline + 5 new tests = **847 passing / 0 failures**. Production poller backs off on consecutive errors instead of hammering Outlook every 10 seconds. After 30 consecutive errors, supervisord restarts the process automatically.

## Rollback

`git revert <commit>`, deploy. Restores the old fixed-interval retry behavior. No data migration, no schema change, no prompt change.
