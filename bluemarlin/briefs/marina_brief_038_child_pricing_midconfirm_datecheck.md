# BRIEF 038 — Marina prompt: child age pricing + day-of-week on mid-confirmation date change
**Status:** Draft | **Files:** `src/marina_agent.py`, `briefs/SYSTEM_STATE.md`, `test_038_prompt_fixes.py` | **Depends on:** Brief 037 | **Blocks:** nothing

## Context
Brief 037 stress test exposed two bugs:

**Bug 1 — S21: child pricing assumes 4–12 for all "kids"**
When a customer says "2 adults and 3 kids," Marina prices immediately at the
4–12 child rate without asking ages. BlueFinn pricing has three tiers:
under-4 free, 4–12 child rate, 13+ adult rate. A family with teenagers would
be undercharged. Marina showed she knows the pricing tiers (she voluntarily
added an under-4 caveat) but skips asking for ages before sending a full
booking summary. The fix: add a SECOND pre-summary check — if kids are
mentioned and ages are unknown, ask before pricing.

**Bug 2 — S12 (pre-existing): day-of-week check doesn't fire on mid-confirmation date change**
Brief 036 added a FIRST check before the booking summary that validates the
date's day of week against the trip's days_available. But this check only
runs when `awaiting_booking_confirmation` is NOT already set. When a customer
changes the date mid-confirmation ("can we change to May 10?"), Marina falls
into the "customer wants to change something" handler — which has no
day-of-week validation. Marina's own internal_note in S12 recognised the
date was invalid but still sent a booking summary and set the flag. The fix:
extend the mid-confirmation handler to re-run the day-of-week check before
resetting and re-sending a summary.

S22 ("in 3 weeks" → date not extracted) is deferred — behavior is defensible
(Marina computed the nearest valid Friday and asked for confirmation), and
is lower priority than a pricing error.

No Python logic changes. Prompt text only.

## Why This Approach
Both fixes add explicit instruction steps at the exact decision points where
Marina currently skips validation. Fix 1 inserts a SECOND check before the
summary, parallel to the existing FIRST (day-of-week) check — same pattern,
same location. Fix 2 extends the mid-confirmation handler with a conditional
that mirrors the FIRST check — same logic, applied when the customer changes
a date mid-thread. Reusing the established FIRST/SECOND pattern keeps the
prompt consistent. Alternative (restructuring the whole BOOKING CONFIRMATION
section) would be wider scope and higher risk of regression.

## Source Material

### marina_agent.py — BOOKING CONFIRMATION BEHAVIOUR (lines 99–131, confirmed from file read this session)

**Current text — FIRST check through mid-confirmation handler:**
```
BOOKING CONFIRMATION BEHAVIOUR:
When your fields response contains all four required booking fields
(experience, date, guests, trip_key) — whether extracted from this
message or already in thread context — AND "awaiting_booking_confirmation"
is not true in thread flags AND "booking_confirmed" is not true in
thread flags, do NOT assume the booking is confirmed. Instead:
- FIRST: verify the requested date's day of week matches the trip's
  days_available field shown in TRIPS above. If the date falls on a
  day the trip does not run, do NOT set awaiting_booking_confirmation
  and do NOT send a booking summary. Instead, tell the customer which
  days the trip runs and suggest the nearest valid dates.
- Send a warm booking summary to the customer listing: trip name,
  date, number of guests, departure time (if chosen), total price,
  what is included.
- departure_time is NOT a required field. Do not wait for it before
  sending the summary. If not yet chosen, you may ask in the same
  message, but still send the summary and set the confirmation flag.
- End the summary with a single clear confirmation question:
  "Shall I lock this in for you?"
- In your JSON response, the "flags" field MUST contain:
  "awaiting_booking_confirmation": true
- Do NOT set any hold-related flags.

When "awaiting_booking_confirmation" is true in thread flags:
- If the customer's message is a confirmation (yes, sure, let's do
  it, perfect, go ahead, ja, si, or any equivalent in any language):
  In your JSON response, the "flags" field MUST contain:
  "booking_confirmed": true, "awaiting_booking_confirmation": false
  Reply briefly confirming you are locking it in.
- If the customer wants to change something: update the relevant
  field, reset awaiting_booking_confirmation to false, and continue
  the conversation naturally.
- If unclear: ask for clarification.
```

### File header (lines 1–5, confirmed from file read this session)
```python
# FILE: marina_agent.py
# CREATED: Brief 023
# LAST MODIFIED: Brief 036
```

### S12 thread context (confirmed from test_marina_stress.py)
```python
thread_fields={
    "experience": "Sunset Cruise",
    "trip_key": "sunset_cruise",
    "date": "2026-05-05",
    "guests": 2,
    "customer_name": "Alice Brown",
},
thread_flags={"awaiting_booking_confirmation": True}
body="Actually, can we change it to May 10 instead? The 5th doesn't work."
```
May 10 2026 = Sunday. sunset_cruise runs Tuesday, Thursday, Friday, Saturday.
Sunday is invalid. S12 produced a summary for Sunday — this is the bug.

### S21 input (confirmed from test_marina_stress.py)
```
body="Hi, I'd like to book the Klein Curacao trip on May 20 2026. We are 2 adults and 3 kids. Name is Marco Rossi."
```
S21 output: guests=5, priced at 2×$120 + 3×$65 = $435, summary sent, awaiting_booking_confirmation=true.
No question about child ages asked.

## Instructions

### 1. Add SECOND check (child age) to BOOKING CONFIRMATION BEHAVIOUR

Find (exact text, lines 105–110):
```
- FIRST: verify the requested date's day of week matches the trip's
  days_available field shown in TRIPS above. If the date falls on a
  day the trip does not run, do NOT set awaiting_booking_confirmation
  and do NOT send a booking summary. Instead, tell the customer which
  days the trip runs and suggest the nearest valid dates.
- Send a warm booking summary to the customer listing: trip name,
```

Replace with:
```
- FIRST: verify the requested date's day of week matches the trip's
  days_available field shown in TRIPS above. If the date falls on a
  day the trip does not run, do NOT set awaiting_booking_confirmation
  and do NOT send a booking summary. Instead, tell the customer which
  days the trip runs and suggest the nearest valid dates.
- SECOND: if the customer mentioned children, kids, or similar terms,
  check the trip's pricing tiers in TRIPS above. If the trip has
  age-based pricing and the ages of the children are unknown, ask
  for them before sending the summary. Do NOT assume the child rate
  for unspecified ages — the total price must be correct before the
  customer confirms. If ages are known (e.g. customer stated them),
  price correctly and proceed.
- Send a warm booking summary to the customer listing: trip name,
```

### 2. Fix mid-confirmation handler to re-check day of week on date change

Find (exact text, lines 128–130):
```
- If the customer wants to change something: update the relevant
  field, reset awaiting_booking_confirmation to false, and continue
  the conversation naturally.
```

Replace with:
```
- If the customer wants to change something: if the change involves
  the date, FIRST verify the new date's day of week matches the
  trip's days_available (same check as initial booking). If the new
  date is invalid, do NOT reset awaiting_booking_confirmation —
  tell the customer which days the trip runs and suggest the nearest
  valid dates. If the new date is valid (or no date was changed),
  update the relevant field, reset awaiting_booking_confirmation to
  false, and re-run the FIRST and SECOND checks before sending a
  new booking summary.
```

### 3. Update file header

Find:
```python
# LAST MODIFIED: Brief 036
```

Replace with:
```python
# LAST MODIFIED: Brief 038
```

### 4. Update SYSTEM_STATE.md Decision Log

Append to the Decision Log at the end of `briefs/SYSTEM_STATE.md`:
```
Brief 038 — Marina prompt: child age pricing + day-of-week on mid-confirmation date change
Decision: Two prompt fixes from Brief 037 stress test. Fix 1: SECOND pre-summary check asks child ages before pricing. Fix 2: mid-confirmation date-change handler re-validates day of week before resetting.
Outcome: pending
```

## Tests

Write as `bluemarlin/test_038_prompt_fixes.py` and run it:

```python
#!/usr/bin/env python3
# bluemarlin/test_038_prompt_fixes.py
# Brief 038 — child age pricing + mid-confirmation day-of-week check
# Run: cd bluemarlin && source ~/.zshrc && python3 test_038_prompt_fixes.py

import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import marina_agent

# --- Prompt structure tests (no API call) ---
prompt = marina_agent._build_prompt(
    from_email="test@example.com",
    subject="Test",
    body="Hello",
    thread_fields={},
    thread_flags={},
)

# T1: SECOND check present in prompt
assert "SECOND:" in prompt, "T1 fail: SECOND check missing from BOOKING CONFIRMATION BEHAVIOUR"
print("T1 pass — SECOND check present in prompt")

# T2: Child age instruction present
assert "ask for them before sending the summary" in prompt, \
    "T2 fail: child age clarification instruction missing"
print("T2 pass — child age clarification instruction present")

# T3: Mid-confirmation date change check present
assert "If the change involves" in prompt, \
    "T3 fail: mid-confirmation date change instruction missing"
print("T3 pass — mid-confirmation date change instruction present")

# T4: Mid-confirmation handler includes day-of-week guard
assert "do NOT reset awaiting_booking_confirmation" in prompt, \
    "T4 fail: awaiting_booking_confirmation guard missing from mid-confirmation handler"
print("T4 pass — awaiting_booking_confirmation guard present in mid-confirmation handler")

# T5: File header updated to Brief 038
with open(os.path.join(os.path.dirname(__file__), "src", "marina_agent.py")) as f:
    header = f.read(300)
assert "Brief 038" in header, "T5 fail: file header not updated to Brief 038"
print("T5 pass — file header updated to Brief 038")

# --- Live model tests (2 API calls) ---

# T6: S12 re-run — date change mid-confirmation to invalid day (Sunday sunset cruise)
# Expected: awaiting_booking_confirmation NOT set; no booking summary for Sunday
print("\nT6: Running S12 re-run (mid-confirmation Sunday date change)...")
s12 = marina_agent.process_message(
    from_email="alice@example.com",
    subject="Re: Booking sunset cruise",
    body="Actually, can we change it to May 10 instead? The 5th doesn't work.",
    thread_fields={
        "experience": "Sunset Cruise",
        "trip_key": "sunset_cruise",
        "date": "2026-05-05",
        "guests": 2,
        "customer_name": "Alice Brown",
    },
    thread_flags={"awaiting_booking_confirmation": True},
)
flags_s12 = s12.get("flags", {})
reply_s12 = s12.get("reply", "")
# Bug was: awaiting_booking_confirmation=true AND reply contained a full booking summary for Sunday
# Fix verified by: flag absent AND reply does not offer to lock in the Sunday date
assert not flags_s12.get("awaiting_booking_confirmation"), \
    f"T6 fail: awaiting_booking_confirmation=true for invalid Sunday date. flags={flags_s12}"
lock_phrases = ["shall i lock", "lock this in", "locking this in", "locking it in"]
assert not any(phrase in reply_s12.lower() for phrase in lock_phrases), \
    f"T6 fail: reply contains booking summary / lock-in offer for invalid Sunday date.\nreply={reply_s12[:300]}"
print(f"T6 pass — no flag set and no lock-in offer for invalid Sunday date. flags={flags_s12}")

# T7: S21 re-run — "2 adults and 3 kids" — should ask ages, not send summary
print("\nT7: Running S21 re-run (2 adults 3 kids, ages unknown)...")
s21 = marina_agent.process_message(
    from_email="marco@example.com",
    subject="Klein Curacao booking",
    body="Hi, I'd like to book the Klein Curacao trip on May 20 2026. We are 2 adults and 3 kids. Name is Marco Rossi.",
    thread_fields={},
    thread_flags={},
)
flags_s21 = s21.get("flags", {})
assert not flags_s21.get("awaiting_booking_confirmation"), \
    f"T7 fail: booking summary sent without asking child ages. flags={flags_s21}"
print(f"T7 pass — no booking summary sent before asking child ages. flags={flags_s21}")
print(f"  clarifications: {s21.get('clarifications_needed', [])}")

print("\nAll 7 tests passed.")
```

## Success Condition
All 7 tests pass. Prompt inspection confirms SECOND check and mid-confirmation
date guard are present. S12 re-run no longer sets `awaiting_booking_confirmation`
for an invalid Sunday date. S21 re-run does not send a booking summary before
asking for child ages.

## Rollback
`git checkout HEAD~1 -- bluemarlin/src/marina_agent.py` restores to Brief 036 state.
