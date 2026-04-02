# BRIEF 047 — Treat reschedule intent as booking-active in Python validation
**Status:** Draft | **Files:** `email_poller.py` | **Depends on:** Brief 046 | **Blocks:** none

## Context
Live Test 5 (Brief 046 verification) revealed that when a customer changes their date within an active booking thread, Claude classifies the intent as `reschedule` instead of `booking`. Python's `_post_validate` and the Step 5 booking flow both gate on `"booking" in intents`, so the entire Python validation path (day-of-week check, departure time check, summary generation) is skipped. Claude's raw reply is sent instead — which happened to include a self-built summary in Test 5, bypassing Python's deterministic summary. No soft hold was created either.

VPS log evidence:
```
Intents: ['reschedule'] | Fields: {'date': '2026-03-13', 'trip_key': 'snorkeling_3in1', ...}
```

## Why This Approach
Three options were considered:

1. **Remove intent check entirely, gate on field completeness only** — Rejected. A pure pricing inquiry ("How much for Klein Curaçao for 2 on March 25?") would have all 4 required fields extracted but intent `inquiry`. Without an intent gate, `_post_validate` would incorrectly trigger and ask about departure preferences instead of answering the pricing question.

2. **Tell Claude to use `booking` instead of `reschedule` for mid-thread changes** — Rejected. This relies on prompt compliance, which is exactly what Brief 046 was designed to reduce dependence on.

3. **Widen the intent gate to include `reschedule`** — Selected. A `_BOOKING_INTENTS` constant makes the code explicit and extensible. Three lines change. No false positives because `reschedule` is semantically correct — it IS a booking modification. The `reschedule` intent remains valid for standalone reschedule requests (which should trigger escalation via `requires_human`), and those are caught earlier by Step 4 before reaching Step 5.

## Source Material
Current gating code in `email_poller.py`:

Line 279 (`_post_validate`):
```python
if "booking" not in result.get("intents", []):
    return None, False
```

Line 554 (Step 3a):
```python
if "booking" in result.get("intents", []):
```

Line 725 (Step 5):
```python
if "booking" in result.get("intents", []):
```

## Instructions

### Step 1 — Add `_BOOKING_INTENTS` constant
Insert after line 57 (the `REPLY_WINDOW_SECONDS` line), before `# ========= HELPERS =========`:

```python
# Intents that activate the Python booking validation and hold-creation flow.
# "reschedule" is included because mid-thread date/time changes are booking
# modifications that need the same validation (day-of-week, departure, summary).
_BOOKING_INTENTS = {"booking", "reschedule"}
```

### Step 2 — Update `_post_validate` intent gate
Change line 279 from:
```python
if "booking" not in result.get("intents", []):
```
to:
```python
if not any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
```

### Step 3 — Update Step 3a intent gate
Change line 554 from:
```python
if "booking" in result.get("intents", []):
```
to:
```python
if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
```

### Step 4 — Update Step 5 intent gate
Change line 725 from:
```python
if "booking" in result.get("intents", []):
```
to:
```python
if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
```

### Step 5 — Update file header
Change `LAST MODIFIED: Brief 046` to `LAST MODIFIED: Brief 047`.

## Tests

```python
# T1: _BOOKING_INTENTS contains both booking and reschedule
from email_poller import _BOOKING_INTENTS
check("T1: booking in _BOOKING_INTENTS", "booking" in _BOOKING_INTENTS)
check("T2: reschedule in _BOOKING_INTENTS", "reschedule" in _BOOKING_INTENTS)
check("T3: inquiry NOT in _BOOKING_INTENTS", "inquiry" not in _BOOKING_INTENTS)

# T4: _post_validate triggers on reschedule intent
from email_poller import _post_validate
th_resched = {"fields": {"experience": "3-in-1 Snorkeling", "date": "2026-03-13", "guests": "2", "trip_key": "snorkeling_3in1"}, "flags": {}}
trip_snorkel = {"display_name": "3-in-1 Snorkeling Trip", "departures": [{"time": "10:00", "vessel": "TopCat", "departure_point": "Mood Beach pier"}], "days_available": "Fridays only", "price_adult_usd": 110, "included": ["lunch", "3 snorkel sites"]}
result_resched = {"intents": ["reschedule"], "fields": {"date": "2026-03-13"}, "flags": {}}
override_r, awaiting_r = _post_validate(th_resched, result_resched, trip_snorkel)
check("T4: reschedule triggers summary", override_r is not None and "Shall I lock this in" in override_r)
check("T5: reschedule sets awaiting", awaiting_r == True)

# T6: _post_validate does NOT trigger on inquiry intent
result_inquiry = {"intents": ["inquiry"], "fields": {}, "flags": {}}
override_i, awaiting_i = _post_validate(th_resched, result_inquiry, trip_snorkel)
check("T6: inquiry skips validation", override_i is None and awaiting_i == False)

# T7: _post_validate still triggers on booking intent (regression)
result_booking = {"intents": ["booking"], "fields": {}, "flags": {}}
override_b, awaiting_b = _post_validate(th_resched, result_booking, trip_snorkel)
check("T7: booking still triggers summary", override_b is not None and "Shall I lock this in" in override_b)

# T8: wrong day + reschedule returns day-of-week error
th_bad = {"fields": {"experience": "3-in-1 Snorkeling", "date": "2026-03-09", "guests": "2", "trip_key": "snorkeling_3in1"}, "flags": {}}
result_resched_bad = {"intents": ["reschedule"], "fields": {"date": "2026-03-09"}, "flags": {}}
override_bad, awaiting_bad = _post_validate(th_bad, result_resched_bad, trip_snorkel)
check("T8: wrong day caught on reschedule", override_bad is not None and "Friday" in override_bad)

# T9: summary contains correct price for snorkeling ($110 x 2 = $220)
check("T9: summary has correct total", "$220" in override_r)

# T10: summary contains trip name
check("T10: summary has trip name", "3-in-1 Snorkeling Trip" in override_r)
```

## Success Condition
`_post_validate` and the booking flow trigger for both `booking` and `reschedule` intents, so a mid-thread date change produces a Python-generated summary with a soft hold — not a Claude-generated reply.

## Rollback
Revert `_BOOKING_INTENTS` constant and restore `"booking" in` checks on lines 279, 554, 725.
