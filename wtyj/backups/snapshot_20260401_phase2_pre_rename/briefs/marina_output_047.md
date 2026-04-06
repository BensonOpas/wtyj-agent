# OUTPUT 047 — Treat reschedule intent as booking-active in Python validation

## What was done

### Step 1 — Added `_BOOKING_INTENTS` constant
Inserted `_BOOKING_INTENTS = {"booking", "reschedule"}` after `REPLY_WINDOW_SECONDS`, before `# ========= HELPERS =========`.

### Step 2 — Updated `_post_validate` intent gate
Changed `if "booking" not in result.get("intents", []):` to `if not any(i in _BOOKING_INTENTS for i in result.get("intents", [])):`.

### Step 3 — Updated Step 3a intent gate
Changed `if "booking" in result.get("intents", []):` to `if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):`.

### Step 4 — Updated Step 5 intent gate
Changed `if "booking" in result.get("intents", []):` to `if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):`.

### Step 5 — Updated file header
Changed `LAST MODIFIED: Brief 046` to `LAST MODIFIED: Brief 047`.

## Test results

```
Running Brief 047 tests...
  T1: booking in _BOOKING_INTENTS PASS
  T2: reschedule in _BOOKING_INTENTS PASS
  T3: inquiry NOT in _BOOKING_INTENTS PASS
  T4: reschedule triggers summary PASS
  T5: reschedule sets awaiting PASS
  T6: inquiry skips validation PASS
  T7: booking still triggers summary PASS
  T8: wrong day caught on reschedule PASS
  T9: summary has correct total PASS
  T10: summary has trip name PASS

10/10 tests passed.
All tests passed.
```

Regression (Brief 046): 28/28 tests passed.

## Unexpected
Nothing unexpected. All changes were mechanical — 1 constant added, 3 intent checks widened.
