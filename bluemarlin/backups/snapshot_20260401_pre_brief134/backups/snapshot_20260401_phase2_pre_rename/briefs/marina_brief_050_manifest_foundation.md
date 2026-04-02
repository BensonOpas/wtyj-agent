# BRIEF 050 — Manifest foundation: tables + calendar functions
**Status:** Draft | **Files:** `src/state_registry.py`, `src/gws_calendar.py` | **Depends on:** Brief 039 | **Blocks:** Brief 051

## Context

Each booking currently creates a separate Google Calendar event (`HOLD — KLEIN CURACAO — John Smith`). If 10 families book the same trip/date/departure, the operator sees 10 individual events with no aggregated attendance view. The operator cannot tell at a glance how many guests are on a departure or who they are.

This brief adds the foundation: a `manifest_events` SQLite table to track per-slot calendar events, passenger info columns in `trip_bookings`, and new functions in `gws_calendar.py` to create/update/remove manifest-style calendar events.

## Why This Approach

Manifest events (one calendar event per departure slot, updated as bookings arrive) were chosen over alternatives:
- **Summary events alongside individual events** — rejected because it adds MORE calendar clutter, not less.
- **Sheets-only aggregation** — rejected because the operator uses both Calendar and Sheets equally; Calendar must show the aggregated view too.
- **Column in trip_bookings for event_id** — rejected because manifest is per-slot (1:many with bookings), so a separate table with PK `(trip_key, date, departure_time)` is the correct data model.

The brief is purely additive — no existing function signatures are changed, no existing behavior is altered. The new functions will be wired into the booking flow in Brief 051.

## Source Material

### Current `create_hold()` event format (gws_calendar.py line 104-109)
```python
event = {
    'summary': f"HOLD — {trip_key.replace('_', ' ').upper()} — {customer_name}",
    'description': f"Guests: {guests_pax}\nContact: {contact}\nPrice: ${price_usd} USD\nStatus: PENDING_PAYMENT",
    'start': {'dateTime': time_min, 'timeZone': 'America/Curacao'},
    'end': {'dateTime': time_max, 'timeZone': 'America/Curacao'},
}
```

### Current `create_soft_hold()` signature (state_registry.py line 104-105)
```python
def create_soft_hold(
    trip_key: str, date: str, departure_time: str, guests: int, capacity: int
) -> "int | None":
```

### Current `create_soft_hold()` INSERT (state_registry.py line 135-139)
```python
cur = conn.execute(
    "INSERT INTO trip_bookings "
    "(trip_key, date, departure_time, guests, status, expires_at, created_at) "
    "VALUES (?, ?, ?, ?, 'soft_hold', ?, ?)",
    (trip_key, date, departure_time, guests, expires_at, now)
)
```

### Target manifest event format
```
Title:  KLEIN CURACAO — 2026-04-01 08:00 — 12/30 pax

Description:
Total: 12 guests | Revenue: $1,440 USD

1. John Smith — 4 pax — $480 — PENDING — BF-2026-50123
2. Maria Garcia — 6 pax — $720 — CONFIRMED — BF-2026-50124
3. Hans Mueller — 2 pax — $240 — PENDING — BF-2026-50125
```

### gws CLI commands needed
```bash
# Insert (existing)
gws calendar events insert --params '{"calendarId":"..."}' --json '{"summary":"...","description":"...",...}'

# Patch (new — partial update)
gws calendar events patch --params '{"calendarId":"...","eventId":"..."}' --json '{"summary":"...","description":"..."}'

# Delete (new — for zero-passenger cleanup)
gws calendar events delete --params '{"calendarId":"...","eventId":"..."}'
```

### Trip capacities from client.json
- klein_curacao: 30
- snorkeling_3in1: 20
- west_coast_beach: 25
- sunset_cruise: 20
- jet_ski: 4

## Instructions

### Step 1 — Add `manifest_events` table to `state_registry.py`

In `_get_conn()`, after the `trip_bookings` CREATE TABLE block (after line 39), add:

```python
    conn.execute(
        "CREATE TABLE IF NOT EXISTS manifest_events ("
        "trip_key TEXT NOT NULL, "
        "date TEXT NOT NULL, "
        "departure_time TEXT NOT NULL, "
        "calendar_id TEXT NOT NULL, "
        "event_id TEXT NOT NULL, "
        "html_link TEXT DEFAULT '', "
        "created_at TEXT NOT NULL, "
        "PRIMARY KEY (trip_key, date, departure_time)"
        ")"
    )
```

### Step 2 — Add `customer_name` and `customer_email` columns to `trip_bookings`

In `_get_conn()`, after all CREATE TABLE/INDEX statements (after the new manifest_events table from Step 1), add migration for existing databases:

```python
    try:
        conn.execute("ALTER TABLE trip_bookings ADD COLUMN customer_name TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE trip_bookings ADD COLUMN customer_email TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
```

### Step 3 — Update `create_soft_hold()` signature and INSERT

Update the function signature to accept optional customer info:

```python
def create_soft_hold(
    trip_key: str, date: str, departure_time: str, guests: int, capacity: int,
    customer_name: str = "", customer_email: str = ""
) -> "int | None":
```

Update the INSERT statement inside the function (line 135-139) to include the new columns:

```python
        cur = conn.execute(
            "INSERT INTO trip_bookings "
            "(trip_key, date, departure_time, guests, status, expires_at, created_at, "
            "customer_name, customer_email) "
            "VALUES (?, ?, ?, ?, 'soft_hold', ?, ?, ?, ?)",
            (trip_key, date, departure_time, guests, expires_at, now,
             customer_name, customer_email)
        )
```

### Step 4 — Add new public functions to `state_registry.py`

Add these four functions after `cancel_hold()` (before the module-load `_get_conn().close()` line):

```python
def set_booking_ref(hold_id: int, booking_ref: str) -> bool:
    """Set booking_ref on a trip_bookings row. Returns True if row was updated."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE trip_bookings SET booking_ref=? WHERE id=?",
        (booking_ref, hold_id)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def get_manifest_event(trip_key: str, date: str, departure_time: str):
    """Returns dict {trip_key, date, departure_time, calendar_id, event_id, html_link} or None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT trip_key, date, departure_time, calendar_id, event_id, html_link "
        "FROM manifest_events WHERE trip_key=? AND date=? AND departure_time=?",
        (trip_key, date, departure_time)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "trip_key": row[0], "date": row[1], "departure_time": row[2],
        "calendar_id": row[3], "event_id": row[4], "html_link": row[5],
    }


def save_manifest_event(trip_key: str, date: str, departure_time: str,
                        calendar_id: str, event_id: str, html_link: str) -> None:
    """INSERT OR REPLACE into manifest_events."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO manifest_events "
        "(trip_key, date, departure_time, calendar_id, event_id, html_link, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (trip_key, date, departure_time, calendar_id, event_id, html_link,
         datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()


def delete_manifest_event(trip_key: str, date: str, departure_time: str) -> bool:
    """Delete manifest_events row for this slot. Returns True if row existed."""
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM manifest_events WHERE trip_key=? AND date=? AND departure_time=?",
        (trip_key, date, departure_time)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def get_slot_passengers(trip_key: str, date: str, departure_time: str) -> list:
    """Return all active bookings for this slot (soft_hold non-expired + confirmed).
    Each item: {id, guests, booking_ref, status, customer_name, customer_email, created_at}."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT id, guests, booking_ref, status, customer_name, customer_email, created_at "
        "FROM trip_bookings "
        "WHERE trip_key=? AND date=? AND departure_time=? "
        "AND status IN ('soft_hold', 'confirmed') "
        "AND (status='confirmed' OR expires_at > ?) "
        "ORDER BY created_at ASC",
        (trip_key, date, departure_time, now)
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "guests": r[1], "booking_ref": r[2] or "",
            "status": r[3], "customer_name": r[4] or "", "customer_email": r[5] or "",
            "created_at": r[6],
        }
        for r in rows
    ]
```

### Step 5 — Add `_build_manifest_body()` to `gws_calendar.py`

Add this function after `_run_gws()` (after line 47):

```python
def _build_manifest_body(trip_key: str, date: str, departure_time: str,
                         calendar_id: str, price_usd: int, capacity: int,
                         dur: float) -> dict:
    """Build a manifest-style Google Calendar event body for a departure slot.
    Queries state_registry for all active passengers on this slot."""
    passengers = state_registry.get_slot_passengers(trip_key, date, departure_time)
    total_guests = sum(p["guests"] for p in passengers)
    total_revenue = sum(p["guests"] * price_usd for p in passengers)

    lines = []
    lines.append(f"Total: {total_guests} guests | Revenue: ${total_revenue:,} USD")
    lines.append("")
    for i, p in enumerate(passengers, 1):
        name = p["customer_name"] or "—"
        pax = p["guests"]
        cost = pax * price_usd
        status = p["status"].upper()
        ref = p["booking_ref"] or "pending"
        lines.append(f"{i}. {name} — {pax} pax — ${cost} — {status} — {ref}")

    display_name = trip_key.replace('_', ' ').upper()
    summary = f"{display_name} — {date} {departure_time} — {total_guests}/{capacity} pax"
    description = "\n".join(lines)

    try:
        time_min = _curacao_to_iso(date, departure_time)
        year, month, day = map(int, date.split('-'))
        hour, minute = map(int, departure_time.split(':'))
        dt_start = datetime(year, month, day, hour, minute, tzinfo=_CURACAO_TZ)
        dt_end = dt_start + timedelta(hours=dur)
        time_max = dt_end.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception:
        time_min = ""
        time_max = ""

    return {
        'summary': summary,
        'description': description,
        'start': {'dateTime': time_min, 'timeZone': 'America/Curacao'},
        'end': {'dateTime': time_max, 'timeZone': 'America/Curacao'},
        '_total_guests': total_guests,
    }
```

### Step 6 — Add `create_or_update_manifest()` to `gws_calendar.py`

Add after `_build_manifest_body()`:

```python
def create_or_update_manifest(fields_now: dict) -> dict:
    """Create or update a manifest calendar event for this departure slot.
    Reads passenger list (incl. booking_refs) from state_registry — caller must
    call set_booking_ref() before this if the ref should appear in the manifest.
    Returns {ok: bool, eventId?: str, htmlLink?: str, error?: str}."""
    trip_key = fields_now.get('trip_key', '')
    if not trip_key:
        return {'ok': False, 'error': 'No trip_key in fields.'}

    trip = config_loader.get_trip(trip_key)
    departures = trip.get('departures', [])
    start_time = (
        fields_now.get('departure_time')
        or (departures[0].get('time', '09:00') if departures else '09:00')
    )
    matching_dep = next(
        (d for d in departures if d.get('time') == start_time),
        departures[0] if departures else {}
    )
    calendar_id = matching_dep.get('calendar_id', '')
    if not calendar_id or not calendar_id.endswith('@group.calendar.google.com'):
        return {'ok': False, 'error': f'Calendar ID not configured for: {trip_key} at {start_time}'}

    price_usd = trip.get('price_adult_usd', 0)
    dur = trip.get('duration_hours', 4)
    date = fields_now.get('date', '')
    capacity = trip.get('capacity', 20)

    body = _build_manifest_body(trip_key, date, start_time, calendar_id, price_usd, capacity, dur)
    body.pop('_total_guests', None)

    existing = state_registry.get_manifest_event(trip_key, date, start_time)

    if existing:
        # Update existing manifest event (patch summary + description only)
        patch_body = {'summary': body['summary'], 'description': body['description']}
        params = json.dumps({'calendarId': existing['calendar_id'], 'eventId': existing['event_id']})
        result = _run_gws(['calendar', 'events', 'patch', '--params', params, '--json', json.dumps(patch_body)])
        if 'error' in result:
            return {'ok': False, 'error': result['error']}
        return {'ok': True, 'eventId': existing['event_id'], 'htmlLink': existing['html_link']}
    else:
        # Create new manifest event
        params = json.dumps({'calendarId': calendar_id})
        result = _run_gws(['calendar', 'events', 'insert', '--params', params, '--json', json.dumps(body)])
        if 'error' in result:
            return {'ok': False, 'error': result['error']}
        event_id = result.get('id')
        if not event_id:
            return {'ok': False, 'error': f'gws returned no event id: {str(result)[:200]}'}
        html_link = result.get('htmlLink', '')
        state_registry.save_manifest_event(trip_key, date, start_time, calendar_id, event_id, html_link)
        return {'ok': True, 'eventId': event_id, 'htmlLink': html_link}
```

### Step 7 — Add `update_manifest()` to `gws_calendar.py`

Add after `create_or_update_manifest()`:

```python
def update_manifest(trip_key: str, date: str, departure_time: str) -> dict:
    """Refresh an existing manifest event's summary and description.
    Returns {ok: bool, error?: str}."""
    existing = state_registry.get_manifest_event(trip_key, date, departure_time)
    if not existing:
        return {'ok': False, 'error': 'No manifest event for this slot.'}

    trip = config_loader.get_trip(trip_key)
    price_usd = trip.get('price_adult_usd', 0)
    capacity = trip.get('capacity', 20)
    dur = trip.get('duration_hours', 4)

    body = _build_manifest_body(trip_key, date, departure_time, existing['calendar_id'],
                                price_usd, capacity, dur)
    patch_body = {'summary': body['summary'], 'description': body['description']}
    params = json.dumps({'calendarId': existing['calendar_id'], 'eventId': existing['event_id']})
    result = _run_gws(['calendar', 'events', 'patch', '--params', params, '--json', json.dumps(patch_body)])
    if 'error' in result:
        return {'ok': False, 'error': result['error']}
    return {'ok': True}
```

### Step 8 — Add `remove_from_manifest()` to `gws_calendar.py`

Add after `update_manifest()`:

```python
def remove_from_manifest(trip_key: str, date: str, departure_time: str) -> dict:
    """Update manifest after a cancellation. Deletes event if zero active passengers remain.
    Returns {ok: bool, deleted?: bool, error?: str}."""
    existing = state_registry.get_manifest_event(trip_key, date, departure_time)
    if not existing:
        return {'ok': True, 'deleted': False}

    trip = config_loader.get_trip(trip_key)
    price_usd = trip.get('price_adult_usd', 0)
    capacity = trip.get('capacity', 20)
    dur = trip.get('duration_hours', 4)

    body = _build_manifest_body(trip_key, date, departure_time, existing['calendar_id'],
                                price_usd, capacity, dur)
    total_guests = body.pop('_total_guests', 0)

    if total_guests == 0:
        # No passengers left — delete the calendar event
        params = json.dumps({'calendarId': existing['calendar_id'], 'eventId': existing['event_id']})
        _run_gws(['calendar', 'events', 'delete', '--params', params])
        state_registry.delete_manifest_event(trip_key, date, departure_time)
        return {'ok': True, 'deleted': True}
    else:
        # Update manifest with remaining passengers
        patch_body = {'summary': body['summary'], 'description': body['description']}
        params = json.dumps({'calendarId': existing['calendar_id'], 'eventId': existing['event_id']})
        result = _run_gws(['calendar', 'events', 'patch', '--params', params, '--json', json.dumps(patch_body)])
        if 'error' in result:
            return {'ok': False, 'error': result['error']}
        return {'ok': True, 'deleted': False}
```

### Step 9 — Update file headers

**state_registry.py line 3:** Change `# LAST MODIFIED: Brief 039` to `# LAST MODIFIED: Brief 050`
**state_registry.py line 6:** Change `# CALLERS: email_poller.py (original)` to `# CALLERS: email_poller.py, gws_calendar.py`

**gws_calendar.py line 3:** Change `# LAST MODIFIED: Brief 039` to `# LAST MODIFIED: Brief 050`

## Tests

```python
#!/usr/bin/env python3
"""Tests for Brief 050 — Manifest foundation."""
import sys, os, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        print(f"  {name} PASS")
        passed += 1
    else:
        print(f"  {name} FAIL")
        failed += 1

print("Running Brief 050 tests...")

import state_registry
import gws_calendar

# ── state_registry: manifest_events table ──

# T1: manifest_events table exists
conn = state_registry._get_conn()
tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
conn.close()
check("T1: manifest_events table exists", "manifest_events" in tables)

# T2: manifest_events has correct columns
conn = state_registry._get_conn()
cols = [r[1] for r in conn.execute("PRAGMA table_info(manifest_events)").fetchall()]
conn.close()
check("T2: manifest_events columns correct",
      cols == ["trip_key", "date", "departure_time", "calendar_id", "event_id", "html_link", "created_at"])

# T3: trip_bookings has customer_name column
conn = state_registry._get_conn()
cols_tb = [r[1] for r in conn.execute("PRAGMA table_info(trip_bookings)").fetchall()]
conn.close()
check("T3: trip_bookings has customer_name", "customer_name" in cols_tb)

# T4: trip_bookings has customer_email column
check("T4: trip_bookings has customer_email", "customer_email" in cols_tb)

# ── state_registry: new functions exist ──

check("T5: set_booking_ref callable", callable(getattr(state_registry, 'set_booking_ref', None)))
check("T6: get_manifest_event callable", callable(getattr(state_registry, 'get_manifest_event', None)))
check("T7: save_manifest_event callable", callable(getattr(state_registry, 'save_manifest_event', None)))
check("T8: delete_manifest_event callable", callable(getattr(state_registry, 'delete_manifest_event', None)))
check("T9: get_slot_passengers callable", callable(getattr(state_registry, 'get_slot_passengers', None)))

# ── state_registry: manifest CRUD ──

# T10: save + get manifest event
state_registry.save_manifest_event("test_trip", "2099-01-01", "09:00",
                                   "cal@group.calendar.google.com", "evt_123", "https://cal/evt_123")
me = state_registry.get_manifest_event("test_trip", "2099-01-01", "09:00")
check("T10: save+get manifest event", me is not None and me["event_id"] == "evt_123")

# T11: get_manifest_event returns None for missing slot
missing = state_registry.get_manifest_event("no_trip", "2099-01-01", "09:00")
check("T11: get_manifest_event None for missing", missing is None)

# T12: delete_manifest_event removes row
state_registry.delete_manifest_event("test_trip", "2099-01-01", "09:00")
deleted = state_registry.get_manifest_event("test_trip", "2099-01-01", "09:00")
check("T12: delete_manifest_event works", deleted is None)

# ── state_registry: create_soft_hold with customer info ──

# T13: create_soft_hold accepts customer_name and customer_email
hold_id = state_registry.create_soft_hold(
    "test_manifest", "2099-06-01", "10:00", 4, 30,
    customer_name="Test Customer", customer_email="test@example.com"
)
check("T13: create_soft_hold with customer info returns hold_id", hold_id is not None)

# T14: get_slot_passengers returns the customer info
passengers = state_registry.get_slot_passengers("test_manifest", "2099-06-01", "10:00")
check("T14: get_slot_passengers returns customer",
      len(passengers) == 1 and passengers[0]["customer_name"] == "Test Customer"
      and passengers[0]["customer_email"] == "test@example.com"
      and passengers[0]["guests"] == 4)

# T15: set_booking_ref updates the row
state_registry.set_booking_ref(hold_id, "BF-2099-00001")
passengers2 = state_registry.get_slot_passengers("test_manifest", "2099-06-01", "10:00")
check("T15: set_booking_ref updates row", passengers2[0]["booking_ref"] == "BF-2099-00001")

# T16: get_slot_passengers excludes cancelled holds
state_registry.cancel_hold(hold_id)
passengers3 = state_registry.get_slot_passengers("test_manifest", "2099-06-01", "10:00")
check("T16: cancelled hold excluded from passengers", len(passengers3) == 0)

# ── gws_calendar: new functions exist ──

check("T17: _build_manifest_body callable", callable(getattr(gws_calendar, '_build_manifest_body', None)))
# T18-T20: gws_calendar public functions are callable-only checks because
# create_or_update_manifest, update_manifest, and remove_from_manifest call
# _run_gws (live gws CLI) — behavioral testing requires VPS with credentials.
check("T18: create_or_update_manifest callable", callable(getattr(gws_calendar, 'create_or_update_manifest', None)))
check("T19: update_manifest callable", callable(getattr(gws_calendar, 'update_manifest', None)))
check("T20: remove_from_manifest callable", callable(getattr(gws_calendar, 'remove_from_manifest', None)))

# ── gws_calendar: _build_manifest_body output ──

# Insert two test passengers for manifest body test
h1 = state_registry.create_soft_hold("klein_curacao", "2099-07-01", "08:00", 4, 30,
                                     customer_name="Alice", customer_email="alice@test.com")
state_registry.set_booking_ref(h1, "BF-2099-10001")
h2 = state_registry.create_soft_hold("klein_curacao", "2099-07-01", "08:00", 6, 30,
                                     customer_name="Bob", customer_email="bob@test.com")
state_registry.set_booking_ref(h2, "BF-2099-10002")

body = gws_calendar._build_manifest_body(
    "klein_curacao", "2099-07-01", "08:00",
    "cal@group.calendar.google.com", 120, 30, 8
)

# T21: manifest summary contains guest count and capacity
check("T21: summary has 10/30 pax", "10/30 pax" in body["summary"])

# T22: manifest summary contains trip name
check("T22: summary has KLEIN CURACAO", "KLEIN CURACAO" in body["summary"])

# T23: manifest description has total revenue (10 * $120 = $1,200)
check("T23: description has $1,200 revenue", "$1,200" in body["description"])

# T24: manifest description lists both passengers
check("T24: description has Alice", "Alice" in body["description"])
check("T25: description has Bob", "Bob" in body["description"])

# T26: manifest description has booking refs
check("T26: description has BF-2099-10001", "BF-2099-10001" in body["description"])

# T27: manifest body has start/end times
check("T27: body has start dateTime", body["start"]["dateTime"] != "")

# T28: _total_guests field present
check("T28: _total_guests == 10", body.get("_total_guests") == 10)

# ── gws_calendar: create_hold still exists (backward compat) ──
check("T29: create_hold still callable", callable(getattr(gws_calendar, 'create_hold', None)))

# ── file headers ──
with open(os.path.join(os.path.dirname(__file__), "..", "src", "state_registry.py")) as f:
    sr_src = f.read()
check("T30: state_registry header says Brief 050", "Brief 050" in sr_src)

with open(os.path.join(os.path.dirname(__file__), "..", "src", "gws_calendar.py")) as f:
    gc_src = f.read()
check("T31: gws_calendar header says Brief 050", "Brief 050" in gc_src)

# ── Cleanup test data ──
conn = state_registry._get_conn()
conn.execute("DELETE FROM trip_bookings WHERE trip_key IN ('test_manifest', 'klein_curacao') AND date LIKE '2099%'")
conn.execute("DELETE FROM manifest_events WHERE trip_key='test_trip'")
conn.commit()
conn.close()

print(f"\n{passed}/{passed+failed} tests passed.")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("All tests passed.")
```

## Success Condition

All 31 tests pass. `state_registry.py` has the `manifest_events` table and five new public functions. `gws_calendar.py` has `_build_manifest_body`, `create_or_update_manifest`, `update_manifest`, and `remove_from_manifest`. Old `create_hold()` is untouched. No existing behavior changed.

## Rollback

```bash
git checkout HEAD -- bluemarlin/src/state_registry.py bluemarlin/src/gws_calendar.py
# Delete the test DB if it was recreated with new schema:
rm bluemarlin/src/state_registry.db
# Reimport to recreate without new tables:
cd bluemarlin/src && python3 -c "import state_registry"
```
