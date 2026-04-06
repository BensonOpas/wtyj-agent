# OUTPUT 038 — Marina prompt: child age pricing + day-of-week on mid-confirmation date change

## What was done

1. **Fix 1 — SECOND child age check added to BOOKING CONFIRMATION BEHAVIOUR:** After the existing FIRST (day-of-week) check, inserted a SECOND check: if the customer mentioned children/kids and ages are unknown, ask for ages before sending the summary. Do NOT assume the child rate.

2. **Fix 2 — Mid-confirmation date change re-validates day of week:** The `awaiting_booking_confirmation` handler's "customer wants to change something" branch now checks if the change involves a date. If so, it re-validates against the trip's days_available before resetting the flag. If invalid: tell the customer which days the trip runs, do NOT reset awaiting_booking_confirmation.

3. **File header updated:** `# LAST MODIFIED: Brief 036` → `# LAST MODIFIED: Brief 038`

4. **SYSTEM_STATE.md Decision Log updated:** Brief 038 entry appended.

## Test results

```
T1 pass — SECOND check present in prompt
T2 pass — child age clarification instruction present
T3 pass — mid-confirmation date change instruction present
T4 pass — awaiting_booking_confirmation guard present in mid-confirmation handler
T5 pass — file header updated to Brief 038

T6: Running S12 re-run (mid-confirmation Sunday date change)...
T6 pass — no flag set and no lock-in offer for invalid Sunday date. flags={'awaiting_booking_confirmation': False}

T7: Running S21 re-run (2 adults 3 kids, ages unknown)...
T7 pass — no booking summary sent before asking child ages. flags={}
  clarifications: ['How old are your 3 children? Child pricing (USD 65) applies to ages 4–12, and children under 4 are free.']

All 7 tests passed.
```

## Unexpected findings

**T2/T3 test assertion case errors (caught and fixed during execution):**
The brief's test assertions used capitalized strings ("ask for them before sending the summary", "If the change involves") that did not match the lowercase text in the f-string multiline prompt. Fixed by correcting the assertion strings to match exact case. This is an execution-side test correction, not a prompt change — the prompt text was correct as written.

**S21 clarification content:** Marina's clarification was precise and accurate: "How old are your 3 children? Child pricing (USD 65) applies to ages 4–12, and children under 4 are free." She correctly referenced the actual pricing tier (though she used the hardcoded $65 value from the TRIPS data she had injected — this is expected behavior).

## Status
7/7 tests pass. Both bugs from Brief 037 stress test are confirmed fixed. Brief executed as written (with minor test assertion case corrections).
