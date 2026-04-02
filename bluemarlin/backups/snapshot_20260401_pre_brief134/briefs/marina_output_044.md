# OUTPUT 044 — Departure time before booking summary for multi-departure trips

## What was done

### Step 1 — Replaced departure_time instruction in BOOKING CONFIRMATION BEHAVIOUR
Removed the two bullet points (lines 136-141) that said "departure_time is NOT a required field" and allowed sending the summary without it. Replaced with a THIRD pre-summary check: if the trip has more than one departure option and departure_time is not yet chosen, ask the customer BEFORE sending the summary. If only one departure, auto-select it.

### Step 2 — Updated re-run instruction for mid-confirmation changes
Changed line 165 from "re-run the FIRST and SECOND checks" to "re-run the FIRST, SECOND, and THIRD checks" so that departure_time is also re-validated when a customer changes booking details during the confirmation phase.

### Step 3 — Updated file header
Changed `# LAST MODIFIED: Brief 041` to `# LAST MODIFIED: Brief 044`.

## Test results

```
Running Brief 044 tests...
  T1 PASS: Prompt contains THIRD check about departures array
  T2 PASS: Old departure_time instruction removed
  T3 PASS: Prompt instructs auto-select for single-departure trips
  T4 PASS: Prompt requires departure time before summary for multi-departure trips
  T5 PASS: klein_curacao has 2 departures
  T6 PASS: sunset_cruise has 1 departure
  T7 PASS: Re-run instruction includes THIRD check
  T8 PASS: File header updated to Brief 044

All 8 tests passed.
```

## Unexpected

Nothing unexpected. Brief reviewer caught two issues (stale Depends-on, missing THIRD in re-run path) which were patched before execution.
