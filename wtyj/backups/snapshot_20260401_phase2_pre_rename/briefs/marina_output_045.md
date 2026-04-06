# OUTPUT 045 — Slot-unavailable alternative = change, not confirmation + [PAYMENT_LINK] safety net

## What was done

### Step 1 — Added slot-unavailable alternative bullet to prompt
In marina_agent.py, inserted a new bullet in the `awaiting_booking_confirmation` handler, between the "change" and "unclear" bullets. Explicitly tells Marina that picking a slot-unavailable alternative is a CHANGE, not a confirmation — must update fields, reset awaiting_booking_confirmation, re-run FIRST/SECOND/THIRD checks, and send a new summary. Must NOT set booking_confirmed.

### Step 2 — Added [PAYMENT_LINK] safety strip in email_poller.py
Added `reply_text = reply_text.replace("[PAYMENT_LINK]", "")` immediately before the booking flow's `smtp_send`. Ensures the placeholder is never sent as literal text to a customer.

### Step 3 — Updated file headers
marina_agent.py: Brief 044 → Brief 045. email_poller.py: Brief 043 → Brief 045.

## Test results

```
Running Brief 045 tests...
  T1 PASS: Prompt says picking an alternative is a CHANGE
  T2 PASS: Prompt prohibits booking_confirmed for alternatives
  T3 PASS: Alternative bullet includes FIRST, SECOND, and THIRD checks
  T4 PASS: [PAYMENT_LINK] safety strip before booking smtp_send
  T5 PASS: marina_agent.py header updated to Brief 045
  T6 PASS: email_poller.py header updated to Brief 045

All 6 tests passed.
```

## Unexpected

Nothing unexpected.
