# OUTPUT 182 — Persistent IMAP connection for email poller

## What was done

Restructured `email_poller.py`'s main polling loop from "new IMAP connection per iteration" to "persistent connection with NOOP keepalive." `imap_connect()` + `im.select()` now called once on startup and only again on error recovery or token refresh (every 45 min). `im.noop()` replaces reconnection on each iteration as a cheap keepalive. Removed the `finally` block that was killing the connection after every iteration, and removed the explicit `im.logout()` on the success path. Error handler sets `im = None` to signal reconnect on the next iteration. All per-UID processing (message parsing, Marina calls, SMTP replies, booking state) is completely untouched.

## Tests

860 passing / 0 failures (855 baseline + 5 new).

## Deployment

Source committed `e4f7d61`, pushed to main. Background deploy to all three containers.
