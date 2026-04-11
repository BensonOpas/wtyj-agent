# BRIEF 182 — Persistent IMAP connection for email poller
**Status:** Draft | **Files:** `wtyj/agents/marina/email_poller.py`, new `wtyj/tests/marina/test_182_persistent_imap.py` | **Depends on:** Brief 179 (backoff + exit threshold) | **Blocks:** None

## Context

Even after Brief 179 (backoff + cleanup) and the `finally`-block fix, Outlook's IMAP server intermittently rejects SELECT with `Command Error. 12` on ~50% of poll iterations. Root cause confirmed via production logs + direct IMAP test: the poller creates a **new TCP + OAuth + IMAP connection every 10 seconds**, and Outlook rate-limits rapid reconnections from the same IP.

Evidence: the `finally` block at `email_poller.py:1400-1412` closes the connection after EVERY iteration (both success and error), forcing a fresh connection on the next iteration. Direct IMAP test from inside the container succeeds (SELECT returns OK with 230 messages), proving the infrastructure is healthy — the problem is the reconnection frequency.

The heartbeat file confirms the poller IS processing emails when SELECT succeeds, but the intermittent failures generate ~6 alert emails per hour and waste ~50% of poll cycles on failed reconnections.

## Why This Approach

1. **(CHOSEN) Persistent connection with NOOP keepalive.** Connect once, keep the IMAP connection alive across iterations with `im.noop()`, reconnect only when the connection breaks or the OAuth token nears expiry (~45 min). Reduces Outlook connections from 6/minute to ~1 per 45-minute session.

2. **Keep reconnecting but slower (increase POLL_INTERVAL).** Rejected — just masks the problem. At 30s intervals Outlook might still rate-limit, and email response latency doubles.

3. **Switch to Microsoft Graph API (REST).** Eliminates IMAP entirely. Better long-term but a multi-file rewrite touching auth, message fetch, reply send, and flag management. Not a one-brief fix.

## Instructions

### Step 1: Add token refresh constant

Near `_ERROR_EXIT_THRESHOLD` at line 70, add:

```python
# Brief 182: reconnect every 45 min to refresh the OAuth token (expires at 60 min).
_TOKEN_REFRESH_SECONDS = 2700
```

### Step 2: Restructure the main loop for persistent connection

Replace the entire `while True` block at lines 515-1420 with the persistent connection pattern. The key structural changes:

**A. Move `imap_connect()` + `im.select()` from per-iteration (lines 517-519) to a conditional reconnect block at the top of the loop.** The condition is: `im is None` (first run or after error) OR time since last connect exceeds `_TOKEN_REFRESH_SECONDS`.

**B. Add `im.noop()` as keepalive** when the connection is already alive and the token hasn't expired.

**C. Remove `im.logout()` at line 1360** — this explicit logout on the success path kills the persistent connection.

**D. Remove the `finally` block at lines 1400-1412** — it kills the connection every iteration. Connection cleanup moves to the `except` block only (on error, set `im = None` to trigger reconnect on next iteration).

**E. Keep all per-UID processing (lines 524-1358) completely unchanged.** Only the connection lifecycle wrapper changes.

The new structure:

```python
    im = None  # persistent connection, reconnect when None
    _last_connect = 0
    _consecutive_errors = 0
    _error_alert_sent = False

    while True:
        try:
            now = time.time()

            # Reconnect if needed (first run, error recovery, or token refresh)
            if im is None or (now - _last_connect > _TOKEN_REFRESH_SECONDS):
                if im is not None:
                    try:
                        im.logout()
                    except Exception:
                        pass
                im = imap_connect()
                im.select(MAILBOX)
                _last_connect = now
                log(f"IMAP connected (token refresh in {_TOKEN_REFRESH_SECONDS}s)")
            else:
                # Keepalive — cheap NOOP to prevent server timeout
                im.noop()

            _cleanup_stale_data(state, int(time.time()))

            typ, data = im.uid("search", None, "UNSEEN")
            uids = data[0].split() if data and data[0] else []

            for uid in uids:
                # ... ALL existing per-UID processing stays EXACTLY as-is (lines 524-1358) ...
                pass

            # --- POST-UID WORK (unchanged) ---
            # im.logout() REMOVED — connection persists

            # Process pending operator notifications (from WhatsApp)
            _pending = state_registry.get_pending_notifications()
            for _pn in _pending:
                try:
                    smtp_send(demo_support_email, _pn["subject"], _pn["body"],
                              reply_to=EMAIL_ADDR)
                    state_registry.update_notification_status(_pn["id"], "sent")
                    log(f"Sent pending {_pn['notification_type']} "
                        f"notification id={_pn['id']} for {_pn['customer_id']}")
                except Exception as _pn_err:
                    log(f"Failed to send pending notification "
                        f"id={_pn['id']}: {_pn_err}")

            # Heartbeat
            try:
                with open(HEARTBEAT_PATH, "w") as f:
                    f.write(str(int(time.time())))
            except Exception:
                pass

        except Exception as ex:
            _consecutive_errors += 1
            log(f"Error: {ex}")
            # Kill broken connection — next iteration will reconnect
            if im is not None:
                try:
                    im.logout()
                except Exception:
                    pass
            im = None
            if _consecutive_errors >= _ERROR_ALERT_THRESHOLD and not _error_alert_sent:
                try:
                    smtp_send(demo_support_email,
                        f"[ALERT] Marina poller: {_consecutive_errors} consecutive errors",
                        f"Latest error: {ex}\n\nCheck journalctl -u bluemarlin")
                    _error_alert_sent = True
                except Exception:
                    pass
            if _consecutive_errors >= _ERROR_EXIT_THRESHOLD:
                log(f"FATAL: {_consecutive_errors} consecutive errors. Exiting for supervisord restart.")
                sys.exit(1)
        else:
            _consecutive_errors = 0
            _error_alert_sent = False
        # NO finally block — connection persists across iterations

        # Brief 179: exponential backoff on consecutive errors
        if _consecutive_errors > 0:
            _backoff = min(POLL_INTERVAL * (2 ** (_consecutive_errors - 1)), 300)
            log(f"Backing off {_backoff}s (consecutive errors: {_consecutive_errors})")
            time.sleep(_backoff)
        else:
            time.sleep(POLL_INTERVAL)
```

**Critical: the `for uid in uids:` block (lines 524-1358) stays VERBATIM.** Do NOT touch any per-UID processing code. The only lines that change are the connection lifecycle wrapper around it.

**Note on `_cleanup_stale_data` reorder:** in the current code, `_cleanup_stale_data` runs BETWEEN `imap_connect()` and `im.select()` (line 518). In the new structure, it runs AFTER the connect/NOOP block. This is intentional — `_cleanup_stale_data` is pure local file/dict cleanup with zero IMAP dependency (verified: it only touches `state["threads"]` and local JSON files). The reorder is safe.

### Step 3: Remove the explicit `im.logout()` at line 1360

This line kills the persistent connection after every successful UID loop. Delete it. The post-UID work (SMTP notifications + heartbeat at lines 1362-1380) does NOT use `im` — they're SMTP or file I/O only.

### Step 4: Remove the `finally` block at lines 1400-1412

This block closes the connection on EVERY iteration. With persistent connections, cleanup is ONLY in the `except` block (setting `im = None`) and in the reconnect logic (logging out the old connection before creating a new one).

## Tests

Create `wtyj/tests/marina/test_182_persistent_imap.py`. Tests use MagicMock to simulate the IMAP connection and verify actual function call sequences — NOT boolean expression evaluation.

1. **Token refresh constant.** Assert `_TOKEN_REFRESH_SECONDS == 2700`.

2. **First iteration connects and selects.** Mock `imap_connect` to return a MagicMock. Simulate the reconnect block with `im = None`. Assert `imap_connect` was called once AND `mock_im.select('INBOX')` was called once.

3. **Live connection NOOPs instead of reconnecting.** Create a MagicMock for `im`, set `_last_connect = time.time()` (fresh). Simulate the else branch. Assert `mock_im.noop()` was called AND `imap_connect` was NOT called.

4. **NOOP failure triggers reconnect.** Create a MagicMock for `im` with `noop` raising `Exception("socket error")`. Simulate the NOOP call in a try/except matching the real error handler. Assert `im` is set to `None` after the except AND `mock_im.logout()` was called (cleanup the broken connection).

5. **Stale token triggers reconnect even with live connection.** Create a MagicMock for `im`, set `_last_connect = time.time() - 2701`. Mock `imap_connect` to return a new MagicMock. Simulate the reconnect block. Assert `mock_old_im.logout()` was called (close old) AND `imap_connect` was called (create new) AND `new_im.select('INBOX')` was called.

## Success Condition

855 baseline + 5 new tests = **860 passing / 0 failures**. Production poller connects ONCE on startup, uses NOOP keepalive, and only reconnects on error or every 45 minutes. Zero "Command Error. 12" under normal operation.

## Rollback

`git revert <commit>`, deploy. Restores the per-iteration reconnect behavior (with Brief 179's backoff + cleanup). The intermittent SELECT errors return but the system is functional (emails process ~50% of the time).
