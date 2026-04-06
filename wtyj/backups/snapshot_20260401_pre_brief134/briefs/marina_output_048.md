# OUTPUT 048 — Human speech optimization: multi-topic fix + prompt hardening

## What was done

### Step 1 — Removed signatures from `_post_validate` override messages
Removed `signature = config_loader.get_agent_signature()` and trailing `f"Warm regards,\n{signature}"` from three override return paths:
- Day-of-week error in `_post_validate`
- Departure options in `_post_validate`
- `_build_booking_summary` return value

### Step 2 — Updated Step 3a to append/replace based on intents
When `_post_validate` overrides and Claude's response has non-booking intents alongside booking (e.g. `["booking", "inquiry"]`), the override is now **appended** to Claude's reply instead of replacing it. When booking is the only intent, the override replaces entirely and a signature is added. This preserves Claude's answers to non-booking questions (food, hotel pickup, etc.).

### Step 3 — Fixed field merge to allow intentional clears
Added `elif v == "" and k in th["fields"]: del th["fields"][k]` to the field merge loop. When Claude returns an empty string for an existing field, it's treated as an intentional clear. This enables date clearing when a customer rejects a date.

### Step 4 — Slot-unavailable messages left unchanged
These fire after Step 3a and always fully replace (booking can't proceed). No change needed.

### Step 5 — Hardened guests field description
Changed from `guests: exact integer only` to explicit instruction requiring a number to be explicitly stated. "We", "us", "our family" without a number must be omitted. Added "Never infer a guest count from context or business rules."

### Step 6 — Added date-clearing instruction
Added instruction after the existing date description: when the customer explicitly rejects a date, Claude MUST set date to "" to clear the old value.

### Step 7 — Added multi-topic guidance to BOOKING BEHAVIOUR
Added instruction telling Claude to answer non-booking questions in its reply, noting that Python may append booking-specific information after.

### Step 8 — Updated file headers
Both `email_poller.py` and `marina_agent.py` updated to Brief 048.

## Test results

```
Running Brief 048 tests...
  T1: day-of-week override has no signature PASS
  T2: departure override has no signature PASS
  T3: booking summary has no signature PASS
  T4: summary still has lock-in question PASS
  T5: summary still has correct price PASS
  T6: multi-intent detected as has_side_topics PASS
  T7: booking-only has no side topics PASS
  T8: reschedule+inquiry has side topics PASS
  T9: prompt has date-clearing instruction PASS
  T10: prompt still has YYYY-MM-DD instruction PASS
  T11: prompt warns against inferring guests PASS
  T12: prompt says We is not a count PASS
  T13: prompt has multi-topic guidance PASS
  T14: booking still builds summary PASS
  T15: booking still sets awaiting PASS
  T16: reschedule still triggers validation PASS
  T17: empty string clears existing date PASS
  T18: empty string for absent field is safe PASS
  T19: normal merge still works PASS

19/19 tests passed.
All tests passed.
```

Regression: Brief 046 (28/28), Brief 047 (10/10) — all pass.

## Unexpected
Brief reviewer caught a critical dead-end bug on first review: the field merge logic (lines 532-534) skips empty strings, so Claude's `date: ""` would have been silently discarded. Added Step 3 (merge fix) and integration tests T17-T19 to cover this. Second review passed.
