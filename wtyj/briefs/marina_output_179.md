# OUTPUT 179 — Email poller resilience: connection cleanup, exponential backoff, forced exit

## What was done

Added three defensive mechanisms to `email_poller.py`'s main polling loop: (1) `im.close()` / `im.logout()` in the error handler so dead IMAP sockets don't accumulate when SELECT fails or the connection drops, guarded by `im is not None` check with `im` pre-initialized to `None` before the loop; (2) exponential backoff replacing the fixed 10s sleep on error — doubles from 10s on each consecutive failure, capped at 300s, resets to 10s on success; (3) `sys.exit(1)` after 30 consecutive errors (~5 min with backoff) so supervisord restarts the process fresh with a new IMAP connection and a new OAuth token fetch. Also fixed a stale comment that said "3 × 30s = 90 seconds" when POLL_INTERVAL is actually 10s.

## Tests

847 passing / 0 failures (842 baseline + 5 new).

## Deployment

Source committed `e8b80ad`, pushed to main. Background deploy to all three containers.
