# BRIEF 044 — Departure time required before booking summary for multi-departure trips
**Status:** Draft | **Files:** `bluemarlin/src/marina_agent.py` | **Depends on:** Brief 041 | **Blocks:** —

## Context

Live stress test: customer booked Klein Curacao for 4 guests on March 20. Marina sent the full booking summary (with `[PAYMENT_LINK]`, total price, departure options) AND set `awaiting_booking_confirmation: true` in the same message — while also asking which departure time (08:00 or 08:30). The customer then confirmed "4 adult guests" and Marina jumped to `booking_confirmed: true` without a departure time being chosen. The `[PAYMENT_LINK]` placeholder was never replaced because the hold flow fired before the customer picked a time.

The root cause is marina_agent.py lines 139–141:
```
departure_time is NOT a required field. Do not wait for it before
sending the summary. If not yet chosen, you may ask in the same
message, but still send the summary and set the confirmation flag.
```

This instruction applies to ALL trips. For single-departure trips (snorkeling_3in1, west_coast_beach, sunset_cruise) it's fine — there's only one option. But for multi-departure trips (klein_curacao: 2 departures, jet_ski: 12 departures) it causes a premature summary.

## Why This Approach

The fix is prompt-only — no Python logic changes needed. The departures array for each trip is already injected into the prompt via `_build_trips_text()`, so Marina can see how many departure options each trip has. Adding a THIRD pre-summary check (after FIRST day-of-week and SECOND child pricing) keeps the pattern consistent and is the minimal change. We do NOT make departure_time a required field in Python (email_poller.py) because that would break single-departure trips where auto-selection is correct.

## Source Material

Multi-departure trips from client.json:
- `klein_curacao`: departures = [{"time": "08:00", "vessel": "BlueFinn2"}, {"time": "08:30", "vessel": "BlueFinn1"}]
- `jet_ski`: departures = [{"time": "08:00"}, {"time": "09:00"}, ... {"time": "19:00"}] — 12 hourly slots

Single-departure trips from client.json:
- `snorkeling_3in1`: departures = [{"time": "10:00"}]
- `west_coast_beach`: departures = [{"time": "09:00"}]
- `sunset_cruise`: departures = [{"time": "17:30"}]

Current prompt text to replace (marina_agent.py lines 136–141):
```
- Send a warm booking summary to the customer listing: trip name,
  date, number of guests, departure time (if chosen), total price,
  what is included.
- departure_time is NOT a required field. Do not wait for it before
  sending the summary. If not yet chosen, you may ask in the same
  message, but still send the summary and set the confirmation flag.
```

## Instructions

### Step 1 — Replace departure_time instruction in BOOKING CONFIRMATION BEHAVIOUR

In `bluemarlin/src/marina_agent.py`, replace lines 136–141 (the two bullet points about sending the summary and departure_time) with:

```
- THIRD: check the trip's departures array in TRIPS above. If the
  trip has more than one departure option and the customer has not
  yet chosen a departure_time, ask which departure they prefer
  BEFORE sending the booking summary. Do NOT set
  awaiting_booking_confirmation until departure_time is resolved.
  If the trip has only one departure option, auto-select it and
  include it in the summary — do not ask the customer.
- Send a warm booking summary to the customer listing: trip name,
  date, number of guests, departure time, total price,
  what is included.
```

### Step 2 — Update re-run instruction for mid-confirmation changes

In `bluemarlin/src/marina_agent.py`, line 161, change:
```
  re-run the FIRST and SECOND checks before sending a
```
to:
```
  re-run the FIRST, SECOND, and THIRD checks before sending a
```

### Step 3 — Update file header

Change `# LAST MODIFIED: Brief 041` to `# LAST MODIFIED: Brief 044`.

## Tests

File: `bluemarlin/tests/test_044_departure_before_summary.py`

```python
#!/usr/bin/env python3
"""Tests for Brief 044 — Departure time before booking summary for multi-departure trips."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_prompt_contains_third_check():
    """T1: Prompt contains THIRD check about departures array."""
    import marina_agent
    prompt = marina_agent._build_prompt("a@b.com", "test", "test", {}, {})
    assert "THIRD" in prompt, "Prompt must contain THIRD check"
    assert "departures array" in prompt, "THIRD check must reference departures array"
    print("  T1 PASS: Prompt contains THIRD check about departures array")

def test_old_instruction_removed():
    """T2: Old 'departure_time is NOT a required field' instruction is gone."""
    import marina_agent
    prompt = marina_agent._build_prompt("a@b.com", "test", "test", {}, {})
    assert "departure_time is NOT a required field" not in prompt, \
        "Old departure_time instruction must be removed"
    print("  T2 PASS: Old departure_time instruction removed")

def test_auto_select_single_departure():
    """T3: Prompt instructs auto-select for single-departure trips."""
    import marina_agent
    prompt = marina_agent._build_prompt("a@b.com", "test", "test", {}, {})
    assert "only one departure option" in prompt and "auto-select" in prompt, \
        "Prompt must instruct auto-select for single-departure trips"
    print("  T3 PASS: Prompt instructs auto-select for single-departure trips")

def test_ask_before_summary_multi_departure():
    """T4: Prompt instructs asking before summary for multi-departure trips."""
    import marina_agent
    prompt = marina_agent._build_prompt("a@b.com", "test", "test", {}, {})
    assert "more than one departure option" in prompt, \
        "Prompt must mention multi-departure condition"
    assert "BEFORE sending the booking summary" in prompt, \
        "Must instruct asking BEFORE the summary"
    assert "Do NOT set" in prompt and "awaiting_booking_confirmation until departure_time" in prompt, \
        "Must prohibit awaiting_booking_confirmation without departure_time"
    print("  T4 PASS: Prompt requires departure time before summary for multi-departure trips")

def test_klein_curacao_has_multiple_departures():
    """T5: client.json klein_curacao has 2 departures (confirms test premise)."""
    import config_loader
    trip = config_loader.get_trip("klein_curacao")
    deps = trip.get("departures", [])
    assert len(deps) == 2, f"klein_curacao must have 2 departures, got {len(deps)}"
    print("  T5 PASS: klein_curacao has 2 departures")

def test_sunset_cruise_has_single_departure():
    """T6: client.json sunset_cruise has 1 departure (confirms test premise)."""
    import config_loader
    trip = config_loader.get_trip("sunset_cruise")
    deps = trip.get("departures", [])
    assert len(deps) == 1, f"sunset_cruise must have 1 departure, got {len(deps)}"
    print("  T6 PASS: sunset_cruise has 1 departure")

def test_rerun_includes_third():
    """T7: Mid-confirmation re-run instruction includes THIRD check."""
    import marina_agent
    prompt = marina_agent._build_prompt("a@b.com", "test", "test", {}, {})
    assert "FIRST, SECOND, and THIRD checks" in prompt, \
        "Re-run instruction must include THIRD check"
    print("  T7 PASS: Re-run instruction includes THIRD check")

def test_file_header_updated():
    """T8: marina_agent.py file header says Brief 044."""
    import marina_agent
    import inspect
    source = inspect.getsource(marina_agent)
    assert "Brief 044" in source, "File header must reference Brief 044"
    print("  T8 PASS: File header updated to Brief 044")

if __name__ == "__main__":
    print("Running Brief 044 tests...")
    test_prompt_contains_third_check()
    test_old_instruction_removed()
    test_auto_select_single_departure()
    test_ask_before_summary_multi_departure()
    test_klein_curacao_has_multiple_departures()
    test_sunset_cruise_has_single_departure()
    test_rerun_includes_third()
    test_file_header_updated()
    print("\nAll 8 tests passed.")
```

## Success Condition

All 8 tests pass. Marina asks for departure time before sending booking summary for Klein Curacao and Jet Ski. Marina auto-selects for single-departure trips.

## Rollback

Revert the two bullet points in marina_agent.py lines 136–141 to original text. Change header back to Brief 041.
