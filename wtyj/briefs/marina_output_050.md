# OUTPUT 050 — Manifest foundation: tables + calendar functions

## What was done

### Step 1 — Added `manifest_events` table to `state_registry.py`
New table in `_get_conn()`: `manifest_events(trip_key, date, departure_time, calendar_id, event_id, html_link, created_at)` with PK `(trip_key, date, departure_time)`.

### Step 2 — Added `customer_name` and `customer_email` columns to `trip_bookings`
ALTER TABLE migration with `sqlite3.OperationalError` fallback for existing DBs. Both columns `TEXT DEFAULT ''`.

### Step 3 — Updated `create_soft_hold()` signature and INSERT
Added `customer_name: str = ""` and `customer_email: str = ""` keyword args. INSERT now includes both new columns. Backward compatible — existing callers without these args still work.

### Step 4 — Added five new public functions to `state_registry.py`
- `set_booking_ref(hold_id, booking_ref)` — UPDATE booking_ref on a trip_bookings row
- `get_manifest_event(trip_key, date, departure_time)` — SELECT from manifest_events, returns dict or None
- `save_manifest_event(trip_key, date, departure_time, calendar_id, event_id, html_link)` — INSERT OR REPLACE
- `delete_manifest_event(trip_key, date, departure_time)` — DELETE from manifest_events
- `get_slot_passengers(trip_key, date, departure_time)` — SELECT active bookings for a slot (soft_hold non-expired + confirmed), ordered by created_at ASC

### Step 5 — Added `_build_manifest_body()` to `gws_calendar.py`
Queries `state_registry.get_slot_passengers()`, builds manifest-style calendar event body with:
- Summary: `TRIP_NAME — DATE TIME — N/CAPACITY pax`
- Description: Total guests + revenue header, numbered passenger list with name, pax, cost, status, booking_ref
- Start/end times via `_curacao_to_iso()`
- Internal `_total_guests` field for caller use

### Step 6 — Added `create_or_update_manifest()` to `gws_calendar.py`
Checks `state_registry.get_manifest_event()` for existing manifest. If exists: patches summary + description. If not: creates new event via `gws calendar events insert` and saves to manifest_events. Returns `{ok, eventId, htmlLink}`.

### Step 7 — Added `update_manifest()` to `gws_calendar.py`
Refreshes an existing manifest event by rebuilding the body from current passengers and patching.

### Step 8 — Added `remove_from_manifest()` to `gws_calendar.py`
Updates manifest after cancellation. If zero active passengers remain, deletes the calendar event and manifest_events row. Otherwise patches with remaining passengers.

### Step 9 — Updated file headers
Both files: `# LAST MODIFIED: Brief 050`. state_registry.py callers updated to include `gws_calendar.py`.

## Test results

```
Running Brief 050 tests...
  T1: manifest_events table exists PASS
  T2: manifest_events columns correct PASS
  T3: trip_bookings has customer_name PASS
  T4: trip_bookings has customer_email PASS
  T5: set_booking_ref callable PASS
  T6: get_manifest_event callable PASS
  T7: save_manifest_event callable PASS
  T8: delete_manifest_event callable PASS
  T9: get_slot_passengers callable PASS
  T10: save+get manifest event PASS
  T11: get_manifest_event None for missing PASS
  T12: delete_manifest_event works PASS
  T13: create_soft_hold with customer info returns hold_id PASS
  T14: get_slot_passengers returns customer PASS
  T15: set_booking_ref updates row PASS
  T16: cancelled hold excluded from passengers PASS
  T17: _build_manifest_body callable PASS
  T18: create_or_update_manifest callable PASS
  T19: update_manifest callable PASS
  T20: remove_from_manifest callable PASS
  T21: summary has 10/30 pax PASS
  T22: summary has KLEIN CURACAO PASS
  T23: description has $1,200 revenue PASS
  T24: description has Alice PASS
  T25: description has Bob PASS
  T26: description has BF-2099-10001 PASS
  T27: body has start dateTime PASS
  T28: _total_guests == 10 PASS
  T29: create_hold still callable PASS
  T30: state_registry header says Brief 050 PASS
  T31: gws_calendar header says Brief 050 PASS

31/31 tests passed.
All tests passed.
```

## Unexpected
Nothing unexpected. All changes are purely additive — existing `create_hold()`, `create_soft_hold()` (without new kwargs), and all other functions continue to work unchanged.
