# OUTPUT 046 — Hybrid refactor: Python state machine + simplified Claude prompt

## What was done

### Step 1 — Added helper functions to email_poller.py
Five new functions inserted before `# ========= MAIN LOOP =========`:
- `_day_matches(day_name, days_available)` — deterministic day-of-week validation
- `_suggest_dates(date_str, days_available)` — generates 2-3 nearby valid dates
- `_build_booking_summary(fields, trip)` — data-driven booking summary from client.json
- `_build_action_context(th)` — builds action instruction string for Claude prompt
- `_post_validate(th, result, trip)` — validates extracted fields, returns (reply_override, should_set_awaiting)

### Step 2 — Simplified marina_agent.py prompt
- Added `action_context: str = ""` parameter to `_build_prompt()`.
- Replaced 62-line BOOKING CONFIRMATION BEHAVIOUR block (FIRST/SECOND/THIRD checks, confirmation handling, slot-unavailable alternatives) with 12-line BOOKING BEHAVIOUR section. Claude now follows ACTION instructions from Python instead of managing its own state machine.
- Removed 12-line AVAILABILITY CONTEXT block — Python handles all availability logic.
- Removed `spots_remaining` and `trip_capacity` from THREAD CONTEXT.
- Updated JSON spec: simplified `reply` description, simplified `reply_hold_failed` (only for booking_confirmed), updated `flags` to include `booking_confirmed`, `awaiting_booking_confirmation` (clear only), `needs_child_ages`.

### Step 3 — Added action_context to process_message
- Added `action_context: str = ""` parameter to `process_message()`.
- Passes `action_context` through to `_build_prompt()`.
- Backward compatible — all existing callers (relay, fully_escalated) work without changes.

### Step 4 — Modified email_poller.py main loop
- **Step 1**: Builds `action_context` before calling marina_agent.
- **Step 2**: Field merge changed to always overwrite non-empty values (fixes dead-end after slot-unavailable).
- **Step 3**: Python strips Claude's attempts to SET `awaiting_booking_confirmation` (Python controls this flag). Claude can still CLEAR it (for changes).
- **Step 3a (new)**: Post-validation runs after field/flag merge. May override Claude's reply with data-driven messages (day-of-week error, departure time question, booking summary). Sets `awaiting_booking_confirmation` when all fields are valid.
- **Step 3b**: Trigger condition changed from `result.get("flags")` to `th["flags"]` (Python-managed flag). Slot-unavailable and race branches now reset `awaiting_booking_confirmation` and `slot_checked`, and override reply with unavailable message.
- **Step 5**: Removed redundant reply_text selection (now set in Step 3a). Changed `[PAYMENT_LINK]` replacement to use `reply_text` instead of `result["reply"]`.

### Step 5 — Updated file headers
Both files updated to Brief 046.

## Test results

```
Running Brief 046 tests...
  T1: daily matches any day PASS
  T2: Monday doesn't match Fridays only PASS
  T3: Friday matches Fridays only PASS
  T4: Wednesday matches Wednesdays and Sundays PASS
  T5: suggest_dates returns Friday suggestions PASS
  T6: action_context contains ACTION for awaiting PASS
  T7: action_context empty for no flags PASS
  T8: action_context mentions reply_hold_failed PASS
  T9: multi-departure asks for departure time PASS
  T10: multi-departure does not set awaiting PASS
  T11: single-departure builds summary PASS
  T12: single-departure sets awaiting PASS
  T13: wrong day returns day-of-week error PASS
  T14: wrong day does not set awaiting PASS
  T15: skips validation when already awaiting PASS
  T16: skips when missing required fields PASS
  T17: summary contains trip name PASS
  T18: summary contains price PASS
  T19: summary contains departure PASS
  T20: summary ends with lock-in question PASS
  T21: prompt has no FIRST check PASS
  T22: prompt has no SECOND check PASS
  T23: prompt has no THIRD check PASS
  T24: prompt contains BOOKING BEHAVIOUR PASS
  T25: action_context injected into prompt PASS
  T26: process_message has action_context param PASS
  T27: no AVAILABILITY CONTEXT in prompt PASS
  T28: needs_child_ages skips summary PASS

28/28 tests passed.
All tests passed.
```

## Unexpected

T28 initially failed — the test data didn't include `departure_time`, so `_post_validate` short-circuited at the departure-time check before reaching the `needs_child_ages` check. Fixed by adding `departure_time: "08:00"` to the test thread fields.
