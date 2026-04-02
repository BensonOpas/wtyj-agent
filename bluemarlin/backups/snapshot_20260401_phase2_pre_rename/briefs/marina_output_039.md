# OUTPUT 039 — Capacity-aware booking with soft holds

**Status:** Complete
**Brief:** BRIEF_039_capacity_soft_holds.md
**Date:** 2026-03-08

---

## What was done

### Step 1 — config/client.json
- Added `"capacity"` field to all 5 trips: klein_curacao=30, snorkeling_3in1=20, west_coast_beach=25, sunset_cruise=20, jet_ski=4
- Moved `calendar_id` from trip level → departure level for all trips
- klein_curacao: 2 departure-level calendar_ids (08:00 → BlueFinn2, 08:30 → BlueFinn1, each with their distinct calendar IDs)
- snorkeling_3in1, west_coast_beach, sunset_cruise: single departure entry updated with calendar_id
- jet_ski: replaced 2 "every hour" departures with 12 explicit hourly slots (08:00–19:00), each with the shared jet_ski calendar_id; added `"duration_hours": 1`
- All trip-level `calendar_id` entries removed
- JSON validity verified: `python3 -c "import json; json.load(open('config/client.json'))"` passed

### Step 2 — src/state_registry.py
- Added `timedelta` to datetime imports
- Added `trip_bookings` table (id, trip_key, date, departure_time, guests, booking_ref, status, expires_at, created_at) to `_get_conn()`
- Added `idx_trip_bookings_lookup` index on (trip_key, date, departure_time, status)
- Added 5 new public functions: `expire_stale_holds()`, `get_spots_remaining()`, `create_soft_hold()`, `confirm_hold()`, `cancel_hold()`
- `create_soft_hold()` uses `BEGIN IMMEDIATE` for atomic capacity check + insert (race-safe)
- Updated file header to Brief 039

### Step 3 — src/gws_calendar.py
- Added `import state_registry`
- Removed `CALENDARS` dict (5 hardcoded calendar IDs)
- Removed `DURATIONS_HOURS` dict (5 hardcoded durations)
- Replaced `check_availability()` with SQLite-based capacity check (no gws CLI call); new signature includes `new_guests` parameter; returns `{available, spots_remaining, capacity}`
- Restructured `create_hold()` opening: `trip` and `departures` resolved first, then `calendar_id` looked up from the matching departure object (`matching_dep.get('calendar_id')`)
- Replaced `DURATIONS_HOURS.get(trip_key, 4)` with `trip.get('duration_hours', 4)`
- Updated file header to Brief 039

### Step 4 — src/email_poller.py
- Step 3b replaced: now passes `new_guests` to `check_availability()`, stores `spots_remaining` and `trip_capacity` in thread flags, creates a `create_soft_hold()` SQLite hold when slot is available, handles race condition
- Added `_was_awaiting` capture before Step 3 flag merge
- Added date-change cancellation block: if `awaiting_booking_confirmation` cleared without `booking_confirmed`, old soft hold is cancelled and `slot_checked` reset
- Added `state_registry.confirm_hold()` call after successful calendar event creation
- Added `state_registry.cancel_hold()` call after failed calendar event creation
- Updated file header to Brief 039

### Step 5 — src/marina_agent.py
- Added `spots_remaining` and `trip_capacity` to THREAD CONTEXT section of prompt
- Added AVAILABILITY CONTEXT instruction section after ESCALATION BEHAVIOUR and before THREAD CONTEXT
- Updated file header to Brief 039

### Test file created
- `/Users/benson/Projects/bluemarlin-agent/bluemarlin/tests/test_039_capacity_soft_holds.py`

---

## Test results

```
Setup: cleared test rows from trip_bookings

T1: Book 20 guests klein_curacao 2026-04-01 08:00...
T1 pass — hold_id=1, spots_remaining=10

T2: Book 15 more guests same slot (would exceed capacity)...
T2 pass — correctly rejected (hold_id=None)

T3: Book 10 more guests same slot (fills to capacity)...
T3 pass — hold_id=2, spots_remaining=0

T4: Book 1 more guest (slot full)...
T4 pass — correctly rejected when full

T5: Klein Curaçao 08:30 — independent slot...
T5 pass — 08:30 independent: spots_remaining=30

T6: Klein Curaçao April 2 — fresh date...
T6 pass — April 2 fresh: spots_remaining=30

T7: Simulate expired hold...
T7 pass — expired_count=1, spots_after=4

T8: Concurrent race for last spot...
T8 pass — race handled correctly: 1 success (hold_id=5), 1 rejected

Schema check: client.json departure-level calendar_ids...
Schema pass — klein_curacao: capacity=30, 2 departure-level calendar_ids
Schema pass — jet_ski: capacity=4, duration_hours=1, 12 hourly departures 08:00–19:00

All 8 tests + schema checks passed.
```

**Result: 8/8 tests passed. All schema checks passed.**

---

## Anything unexpected

- The `compdef` warning from `.openclaw/completions/openclaw.zsh` during `source ~/.zshrc` is a pre-existing shell environment issue, not related to this brief.
- No issues encountered. All instructions executed exactly as written.
