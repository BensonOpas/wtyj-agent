# BRIEF 037 — Extended stress test: 8 new edge case scenarios
**Status:** Draft | **Files:** `test_marina_stress.py`, `briefs/SYSTEM_STATE.md` | **Depends on:** Brief 036 | **Blocks:** 038+ (prompt fixes)

## Context
The 14-scenario stress test (S1–S14) covers the core booking flow, language
detection, trip key mapping, escalation, and day-of-week validation. However,
the following human speech patterns are untested:

- Guest count expressed as arithmetic ("me and 3 friends" = 4)
- Guest count expressed as social units ("2 couples" = 4)
- Implicit booking confirmation ("sounds good, what's next?")
- No trip named in first message
- Relative date: "next Saturday" (resolvable — must become YYYY-MM-DD)
- Holiday date: "Easter" (unresolvable — must be omitted, clarification asked)
- Mixed guest types: "2 adults and 3 kids" (pricing splits by age — gap suspected)
- Relative date arithmetic: "in 3 weeks" (resolvable — must become YYYY-MM-DD)

This brief adds S15–S22 to the stress test and runs them. No prompt changes.
The output documents what Marina actually does. Failures become source material
for Brief 038.

One confirmed gap (not just untested): child pricing. Marina has no instruction
to ask child ages. BlueFinn prices 4-12 at child rate, under-4 free. S21 is
expected to expose this.

## Why This Approach
Test before fix. We do not know which of these scenarios actually fail until we
run them against the live model. Writing prompt fixes before seeing the failure
would mean patching based on speculation. Running first gives us exact failure
modes — what field was wrong, what Marina said, what she should have said —
which makes the 038 prompt fix precise rather than broad.

## Source Material

### test_marina_stress.py — end of file (confirmed from file read this session)
The file ends at line 278:
```python
print(f"\n{DIVIDER}")
print(f"Done — 14 scenarios run. Review replies above.")
print(f"Key checks:")
print(f"  S1  — reply is in Dutch")
print(f"  S2  — awaiting_booking_confirmation=true, booking summary present")
print(f"  S3  — booking_confirmed=true, [PAYMENT_LINK] in reply")
print(f"  S4  — trip_key=snorkeling_3in1")
print(f"  S5  — trip_key=sunset_cruise")
print(f"  S6  — trip_key=jet_ski")
print(f"  S7  — trip_key=west_coast_beach")
print(f"  S8  — requires_human=true")
print(f"  S9  — date not in fields, clarification asked")
print(f"  S10 — date=2026-04-15")
print(f"  S11 — departure_time=08:00")
print(f"  S12 — awaiting_booking_confirmation reset, new date captured")
print(f"  S13 — special_requests captured")
print(f"  S14 — requires_human=true, no info requests")
print(DIVIDER)
```

### Today's date (Curaçao, confirmed from session context)
2026-03-07 (Saturday)

Derived dates for test scenarios (session-specific — compute at execution time):
- "next Saturday" from execution date = next Saturday as YYYY-MM-DD
- "in 3 weeks" from execution date = execution date + 21 days as YYYY-MM-DD
Note: Marina computes today's date independently at call time. Pass/fail for
S19 and S22 is format-only (YYYY-MM-DD string), not a specific value check.

### S7 note (west_coast_beach days_available)
April 30 2026 = Thursday. west_coast_beach runs Wed/Sun. S7 confirmed Marina
does not send a booking summary for Thursday (Brief 036). May 8 2026 = Friday
— also invalid for west_coast_beach (Wed/Sun only). S16 uses May 8 west coast
beach, so we expect Marina to flag the day mismatch rather than send a summary.
This is acceptable — S16's primary goal is guest count ("2 couples" = 4), and
the day mismatch is a secondary observation.

## Instructions

### 1. Insert S15–S22 scenarios into test_marina_stress.py

Find (exact text, lines 250–258 — the S14 run call and its closing comment):
```python
s14 = run(
    label="S14 — Cancellation request — should escalate warmly",
    from_email="lisa@example.com",
    subject="Cancel my booking",
    body="Hi, I need to cancel my booking for next week. Something came up "
         "and we can no longer make it.",
    thread_fields={},
    thread_flags={},
)

print(f"\n{DIVIDER}")
print(f"Done — 14 scenarios run. Review replies above.")
```

Replace with:
```python
s14 = run(
    label="S14 — Cancellation request — should escalate warmly",
    from_email="lisa@example.com",
    subject="Cancel my booking",
    body="Hi, I need to cancel my booking for next week. Something came up "
         "and we can no longer make it.",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S15 — Guest count via arithmetic: "me and 3 friends"
# Expected: guests=4
# -----------------------------------------------------------------------
s15 = run(
    label="S15 — Guest count arithmetic: 'me and 3 friends'",
    from_email="test15@example.com",
    subject="Sunset cruise inquiry",
    body="Hi, I want to book the sunset cruise for me and 3 friends on June 12 2026.",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S16 — Guest count via social unit: "2 couples"
# Expected: guests=4 (may also flag day mismatch for west_coast_beach)
# -----------------------------------------------------------------------
s16 = run(
    label="S16 — Guest count inference: '2 couples'",
    from_email="test16@example.com",
    subject="West coast beach trip",
    body="Hello! We're 2 couples interested in the west coast beach trip on May 8 2026.",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S17 — Implicit booking confirmation: "sounds good, what's next?"
# Thread has awaiting_booking_confirmation=true
# Expected: booking_confirmed=true
# -----------------------------------------------------------------------
s17 = run(
    label="S17 — Implicit confirmation: 'sounds good, what's next?'",
    from_email="test17@example.com",
    subject="Re: Klein Curacao booking",
    body="Sounds good, what's next?",
    thread_fields={
        "experience": "Klein Curaçao",
        "trip_key": "klein_curacao",
        "date": "2026-05-03",
        "guests": 4,
        "customer_name": "Tom",
    },
    thread_flags={
        "awaiting_booking_confirmation": True,
    },
)

# -----------------------------------------------------------------------
# S18 — No trip named
# Expected: trip_key absent, clarification asking which trip
# -----------------------------------------------------------------------
s18 = run(
    label="S18 — No trip named — should ask which trip",
    from_email="test18@example.com",
    subject="Booking inquiry",
    body="Hi, I want to book for April 22 2026 for 3 people. Name is Sara.",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S19 — Relative date: "next Saturday"
# Expected: date is a YYYY-MM-DD string (not "next Saturday"), guests=1, trip_key=jet_ski
# -----------------------------------------------------------------------
s19 = run(
    label="S19 — Relative date: 'next Saturday'",
    from_email="test19@example.com",
    subject="Jet ski booking",
    body="Can we book the jet ski for next Saturday? Just me.",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S20 — Unresolvable holiday date: "Easter"
# Expected: date omitted from fields, clarification asked
# -----------------------------------------------------------------------
s20 = run(
    label="S20 — Unresolvable date: 'Easter'",
    from_email="test20@example.com",
    subject="Klein Curacao at Easter",
    body="We want to go on the Klein Curacao trip at Easter with 4 people.",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S21 — Mixed guest types: "2 adults and 3 kids"
# Expected (ideal): Marina asks child ages for pricing
# Likely actual: guests=5, no age question — gap to document
# -----------------------------------------------------------------------
s21 = run(
    label="S21 — Child pricing gap: '2 adults and 3 kids'",
    from_email="test21@example.com",
    subject="Klein Curacao family booking",
    body="Hi, I'd like to book the Klein Curacao trip on May 20 2026. "
         "We are 2 adults and 3 kids. Name is Marco Rossi.",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S22 — Relative date arithmetic: "in 3 weeks"
# Expected: date is a YYYY-MM-DD string (not "in 3 weeks"), trip_key=snorkeling_3in1
# -----------------------------------------------------------------------
s22 = run(
    label="S22 — Relative date arithmetic: 'in 3 weeks'",
    from_email="test22@example.com",
    subject="Snorkeling trip",
    body="Hello! I want to book the snorkeling trip in 3 weeks for 2 people.",
    thread_fields={},
    thread_flags={},
)

print(f"\n{DIVIDER}")
print(f"Done — 22 scenarios run. Review replies above.")
```

### 2. Update the key checks footer

Find (exact text):
```python
print(f"Key checks:")
print(f"  S1  — reply is in Dutch")
print(f"  S2  — awaiting_booking_confirmation=true, booking summary present")
print(f"  S3  — booking_confirmed=true, [PAYMENT_LINK] in reply")
print(f"  S4  — trip_key=snorkeling_3in1")
print(f"  S5  — trip_key=sunset_cruise")
print(f"  S6  — trip_key=jet_ski")
print(f"  S7  — trip_key=west_coast_beach")
print(f"  S8  — requires_human=true")
print(f"  S9  — date not in fields, clarification asked")
print(f"  S10 — date=2026-04-15")
print(f"  S11 — departure_time=08:00")
print(f"  S12 — awaiting_booking_confirmation reset, new date captured")
print(f"  S13 — special_requests captured")
print(f"  S14 — requires_human=true, no info requests")
print(DIVIDER)
```

Replace with:
```python
print(f"Key checks:")
print(f"  S1  — reply is in Dutch")
print(f"  S2  — awaiting_booking_confirmation=true, booking summary present")
print(f"  S3  — booking_confirmed=true, [PAYMENT_LINK] in reply")
print(f"  S4  — trip_key=snorkeling_3in1")
print(f"  S5  — trip_key=sunset_cruise")
print(f"  S6  — trip_key=jet_ski")
print(f"  S7  — trip_key=west_coast_beach")
print(f"  S8  — requires_human=true")
print(f"  S9  — date not in fields, clarification asked")
print(f"  S10 — date=2026-04-15")
print(f"  S11 — departure_time=08:00")
print(f"  S12 — awaiting_booking_confirmation reset, new date captured")
print(f"  S13 — special_requests captured")
print(f"  S14 — requires_human=true, no info requests")
print(f"  S15 — guests=4 (me + 3 friends)")
print(f"  S16 — guests=4 (2 couples), day mismatch noted")
print(f"  S17 — booking_confirmed=true (implicit yes)")
print(f"  S18 — trip_key absent, clarification asked for trip")
print(f"  S19 — date is YYYY-MM-DD (not 'next Saturday'), guests=1, trip_key=jet_ski")
print(f"  S20 — date absent, clarification asked (Easter unresolvable)")
print(f"  S21 — observe: guests count and whether ages asked")
print(f"  S22 — date is YYYY-MM-DD (not 'in 3 weeks'), trip_key=snorkeling_3in1")
print(DIVIDER)
```

### 3. Run the stress test

```
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin && source ~/.zshrc && python3 test_marina_stress.py
```

Capture the full output. S1–S14 should behave as before. Focus on S15–S22.

### 4. Update SYSTEM_STATE.md Decision Log

Append to the Decision Log at the end of `briefs/SYSTEM_STATE.md`:
```
Brief 037 — Extended stress test: 8 new edge case scenarios
Decision: Add S15–S22 to test_marina_stress.py to test arithmetic guest counts, implicit confirmation, missing trip name, relative dates, and child pricing. Test-only — no prompt changes. Failures documented for 038.
Outcome: pending
```

### 5. Write OUTPUT_037.md

Write `briefs/OUTPUT_037.md` with:
- Full output of all 8 new scenarios (S15–S22)
- Per-scenario verdict: pass / fail / partial / unexpected
- Definition of pass per scenario:
  - S15: guests=4 in fields → pass; guests≠4 or absent → fail
  - S16: guests=4 in fields → pass (day mismatch also noted but not a fail)
  - S17: booking_confirmed=true in flags → pass; otherwise → fail
  - S18: trip_key absent AND clarification mentions trip → pass
  - S19: date field is a YYYY-MM-DD string (not "next Saturday") → pass
  - S20: date absent AND clarification asked → pass; date present → fail
  - S21: note exactly what guests= was returned and whether age was mentioned; no pass/fail (observation only)
  - S22: date field is a YYYY-MM-DD string (not "in 3 weeks") → pass
- Summary table: which gaps are confirmed broken and become Brief 038 targets

## Tests

Write as `bluemarlin/test_037_extended_stress.py` and run it:

```python
#!/usr/bin/env python3
# bluemarlin/test_037_extended_stress.py
# Brief 037 — Structural checks only (not model output)
# Run: cd bluemarlin && python3 test_037_extended_stress.py

import os

stress_path = os.path.join(os.path.dirname(__file__), "test_marina_stress.py")
with open(stress_path) as f:
    content = f.read()

# T1: All 8 new scenario labels present in the file
for label in ["S15", "S16", "S17", "S18", "S19", "S20", "S21", "S22"]:
    assert label in content, f"T1 fail: {label} missing from test_marina_stress.py"
print("T1 pass — all 8 new scenario labels present in test_marina_stress.py")

# T2: Footer updated to 22 scenarios
assert "22 scenarios run" in content, \
    "T2 fail: footer still says 14 scenarios"
print("T2 pass — footer updated to 22 scenarios")

# T3: S22 present in key checks footer (two-space indent distinguishes footer line from scenario body)
assert '  S22 \u2014' in content, "T3 fail: S22 footer line missing (check key checks footer was updated)"
print("T3 pass — S22 present in key checks footer")

# T4: OUTPUT_037.md exists
output_path = os.path.join(os.path.dirname(__file__), "briefs", "OUTPUT_037.md")
assert os.path.exists(output_path), "T4 fail: OUTPUT_037.md not written"
print("T4 pass — OUTPUT_037.md exists")

# T5: OUTPUT_037.md contains per-scenario verdicts
with open(output_path) as f:
    output = f.read()
for label in ["S15", "S16", "S17", "S18", "S19", "S20", "S21", "S22"]:
    assert label in output, f"T5 fail: {label} missing from OUTPUT_037.md"
print("T5 pass — all 8 scenario labels present in OUTPUT_037.md")

# T6: OUTPUT_037.md has substantial content with actual Marina field output
# (not just labels — "guests" only appears if Marina's field dict was recorded)
assert len(output) > 500 and "guests" in output, \
    f"T6 fail: OUTPUT_037.md appears to lack actual Marina output (len={len(output)}, 'guests' present={'guests' in output})"
print("T6 pass — OUTPUT_037.md contains substantial content with Marina field output")

print("\nAll 6 tests passed.")
```

## Success Condition
All 6 structural tests pass. `test_marina_stress.py` contains 22 scenarios.
`OUTPUT_037.md` documents what Marina actually returned for S15–S22 and
identifies which scenarios failed — these become Brief 038 targets.

## Rollback
`git checkout HEAD -- bluemarlin/test_marina_stress.py` restores to 14 scenarios.
Delete `briefs/OUTPUT_037.md` and `test_037_extended_stress.py` if written.
