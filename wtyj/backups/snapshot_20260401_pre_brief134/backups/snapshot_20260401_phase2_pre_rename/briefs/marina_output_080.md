# OUTPUT 080 — Fix Relay Double-Fire Bug

**Brief:** marina_brief_080_relay_double_fire_fix.md
**Status:** Complete
**Date:** 2026-03-13

## What Was Done

### Step 1 — Fixed `get_relay_by_token()` in `shared/state_registry.py`
Added `AND status = 'pending'` to the WHERE clause. The function now only returns notifications that haven't been processed yet.

### Step 2 — Updated log message in `agents/marina/email_poller.py`
Changed the fallback log from "no matching thread" to "no pending relay... (may be already replied)" for accurate debugging.

### Step 3 — Added regression test in `tests/social/test_077_relay_bridge.py`
New test `test_get_relay_by_token_ignores_replied`: creates a notification, marks it 'replied', verifies `get_relay_by_token()` returns `None`. Also tests 'sent' status. This is the exact scenario that caused the production double-fire.

## Test Results

```
test_077 suite: 9/9 PASSED
Full social regression: 101/101 PASSED
```

## Root Cause Analysis

`get_relay_by_token()` (Brief 077) queried `WHERE relay_token = ?` without status filtering. When an operator replied to a `[RELAY-xxx]` email, the first reply was processed correctly and marked `status='replied'`. But if a second email contained the same token (e.g., operator's reply-all, forwarded copy, or re-fetched message), `get_relay_by_token()` still returned the notification — triggering a second reformulation and WhatsApp delivery.

## Why Tests Didn't Catch It

The test_077 suite only tests the social_agent *creation* side (does semi-escalation create a relay notification?). `test_get_relay_by_token` created a notification and retrieved it, but never updated the status and tried to retrieve it again. The live tests (075/078/079) only call `handle_incoming_whatsapp_message` — they never exercise the email_poller's relay handler loop. There was zero test coverage for "what happens when a relay token is looked up after the notification is already replied?"

## Unexpected

Nothing unexpected. Clean one-line fix with full regression green.
