# BRIEF 039 — Capacity-aware booking with soft holds

**Status:** Draft
**Files:** `config/client.json`, `src/state_registry.py`, `src/gws_calendar.py`, `src/email_poller.py`, `src/marina_agent.py`
**Depends on:** Brief 038 (marina_agent), Brief 033 (email_poller), Brief 032 (gws_calendar)
**Blocks:** Brief 040

---

## Context

`check_availability()` in `gws_calendar.py` makes a gws CLI call to list Google Calendar events. It is binary: any event in the slot blocks the entire departure for everyone. Multiple families cannot share the same trip on the same date. Klein Curaçao has two vessels and two departure times — they share a single capacity check with no vessel separation. Abandoned mid-bookings permanently block capacity because there is no hold expiry.

There is also a secondary drift: the `CALENDARS` dict in `gws_calendar.py` contains different calendar IDs from `client.json` for four of the five trips. This drift is self-healing after this brief since `CALENDARS` will be removed.

---

## Why This Approach

Real booking platforms (Fareharbor, Rezdy, Booking.com) use a dedicated SQL availability database, not the calendar. The calendar is a crew scheduling view. Availability tracking moves to SQLite. This is the minimal change that gives correct multi-family capacity behaviour without introducing a new infrastructure dependency. The 24-hour soft hold matches the email pace of the flow: customer gets a summary → has 24 hours to confirm → capacity is reserved the whole time. The calendar continues to receive events for the crew — nothing changes for them. The `CALENDARS` and `DURATIONS_HOURS` dicts in `gws_calendar.py` are removed in favour of reading from `config_loader` (Rule 4 compliance; duration_hours and calendar_id are business data that live in client.json).

---

## Source Material

### Confirmed capacity values
Source: `ROADMAP_039_044.md` — "Demo capacity (confirm with BlueFinn before go-live)".
These are booking capacity limits (spots Marina will sell). They are intentionally lower than vessel `max_guests` in the fleet section of `client.json` — `max_guests` is the physical vessel maximum; capacity is the commercial booking ceiling.
- `klein_curacao`: 30
- `snorkeling_3in1`: 20
- `west_coast_beach`: 25
- `sunset_cruise`: 20
- `jet_ski`: 4

### Confirmed Klein Curaçao departure-level calendar IDs (from ROADMAP_039_044.md)
- 08:00 — BlueFinn2: `4ce23ea0e7ec08da249c778969d71c199b8aaf7bf6114efac4fae7e0928f1b31@group.calendar.google.com`
- 08:30 — BlueFinn1: `9f25610370f0f57fa395735502fcff767ba8276ee5a280d028fee7f003054928@group.calendar.google.com`

### Other trip calendar IDs (source of truth: current client.json trip-level values)
- `snorkeling_3in1`: `114baef90d15890abbcc550dc5ea5edf68d5676a13a0122c099ed9a9a8d52db2@group.calendar.google.com`
- `west_coast_beach`: `c24538f8ed2c35306fca340e0e3453bdda717b80274beb6e2e8cae53735e48e0@group.calendar.google.com`
- `sunset_cruise`: `d405cf341b87fcbae36131d910986534fd1d24286632dfa50b1234792aeba2ce@group.calendar.google.com`
- `jet_ski`: `f81a21bbbae8e85f364ee462285ff9f85bcb6f12c0570cac1af63cfe1e850f60@group.calendar.google.com`

### jet_ski departure design decision
`jet_ski` previously had two departure objects with `"time": "every hour"` — not a real HH:MM and not usable as a capacity key. Replace with 12 explicit hourly departures from 08:00 to 19:00. All 12 share the same `calendar_id` (single jet ski calendar). Capacity is 4 per hour slot (2 jet skis × 2 riders). `duration_hours` is 1.

---

## Instructions

Read every file listed in the header before making any change. Execute steps in order.

---

### Step 1 — `config/client.json`

#### 1a. Add `"capacity"` field to each trip (top-level, before `"departures"`)

In `klein_curacao`: add `"capacity": 30` as the first field after `"display_name"`.
In `snorkeling_3in1`: add `"capacity": 20` after `"display_name"`.
In `west_coast_beach`: add `"capacity": 25` after `"display_name"`.
In `sunset_cruise`: add `"capacity": 20` after `"display_name"`.
In `jet_ski`: add `"capacity": 4` after `"display_name"`.

#### 1b. Move `calendar_id` from trip level → departure level, and remove trip-level `calendar_id`

For each trip, find the exact JSON shown in the OLD block and replace it with the NEW block. Use the surrounding keys as anchors to locate the section. After all replacements, run `python3 -c "import json; json.load(open('config/client.json'))"` to verify valid JSON.

**`klein_curacao`**

OLD — find this exact block:
```json
      "departures": [
        {
          "time": "08:00",
          "vessel": "BlueFinn2",
          "departure_point": "Jan Thiel Beach"
        },
        {
          "time": "08:30",
          "vessel": "BlueFinn1",
          "departure_point": "Jan Thiel Beach"
        }
      ],
```
Then separately find and delete this trip-level line (it appears after the `"notes"` entry):
```json
      "calendar_id": "4ce23ea0e7ec08da249c778969d71c199b8aaf7bf6114efac4fae7e0928f1b31@group.calendar.google.com"
```

NEW — replace the departures block with:
```json
      "departures": [
        {
          "time": "08:00",
          "vessel": "BlueFinn2",
          "departure_point": "Jan Thiel Beach",
          "calendar_id": "4ce23ea0e7ec08da249c778969d71c199b8aaf7bf6114efac4fae7e0928f1b31@group.calendar.google.com"
        },
        {
          "time": "08:30",
          "vessel": "BlueFinn1",
          "departure_point": "Jan Thiel Beach",
          "calendar_id": "9f25610370f0f57fa395735502fcff767ba8276ee5a280d028fee7f003054928@group.calendar.google.com"
        }
      ],
```

**`snorkeling_3in1`**

OLD — find this exact block:
```json
      "departures": [
        {
          "time": "10:00",
          "vessel": "TopCat",
          "departure_point": "Mood Beach pier"
        }
      ],
```
Then delete the trip-level line:
```json
      "calendar_id": "114baef90d15890abbcc550dc5ea5edf68d5676a13a0122c099ed9a9a8d52db2@group.calendar.google.com"
```

NEW — replace with:
```json
      "departures": [
        {
          "time": "10:00",
          "vessel": "TopCat",
          "departure_point": "Mood Beach pier",
          "calendar_id": "114baef90d15890abbcc550dc5ea5edf68d5676a13a0122c099ed9a9a8d52db2@group.calendar.google.com"
        }
      ],
```

**`west_coast_beach`**

OLD — find this exact block:
```json
      "departures": [
        {
          "time": "09:00",
          "vessel": "Red Dragon",
          "departure_point": "Mood/Tomatoes"
        }
      ],
```
Then delete the trip-level line:
```json
      "calendar_id": "c24538f8ed2c35306fca340e0e3453bdda717b80274beb6e2e8cae53735e48e0@group.calendar.google.com"
```

NEW — replace with:
```json
      "departures": [
        {
          "time": "09:00",
          "vessel": "Red Dragon",
          "departure_point": "Mood/Tomatoes",
          "calendar_id": "c24538f8ed2c35306fca340e0e3453bdda717b80274beb6e2e8cae53735e48e0@group.calendar.google.com"
        }
      ],
```

**`sunset_cruise`**

OLD — find this exact block:
```json
      "departures": [
        {
          "time": "17:30",
          "vessel": "Kailani",
          "departure_point": "Village Marina/Mood pier"
        }
      ],
```
Then delete the trip-level line:
```json
      "calendar_id": "d405cf341b87fcbae36131d910986534fd1d24286632dfa50b1234792aeba2ce@group.calendar.google.com"
```

NEW — replace with:
```json
      "departures": [
        {
          "time": "17:30",
          "vessel": "Kailani",
          "departure_point": "Village Marina/Mood pier",
          "calendar_id": "d405cf341b87fcbae36131d910986534fd1d24286632dfa50b1234792aeba2ce@group.calendar.google.com"
        }
      ],
```

**`jet_ski`** — replace the entire `"departures"` array with 12 hourly slots and add `"duration_hours": 1`. Also remove trip-level `"calendar_id"`:

```json
"duration_hours": 1,
"departures": [
  {"time": "08:00", "vessel": "Jet Ski", "departure_point": "Spanish Water or Piscadera Bay", "calendar_id": "f81a21bbbae8e85f364ee462285ff9f85bcb6f12c0570cac1af63cfe1e850f60@group.calendar.google.com"},
  {"time": "09:00", "vessel": "Jet Ski", "departure_point": "Spanish Water or Piscadera Bay", "calendar_id": "f81a21bbbae8e85f364ee462285ff9f85bcb6f12c0570cac1af63cfe1e850f60@group.calendar.google.com"},
  {"time": "10:00", "vessel": "Jet Ski", "departure_point": "Spanish Water or Piscadera Bay", "calendar_id": "f81a21bbbae8e85f364ee462285ff9f85bcb6f12c0570cac1af63cfe1e850f60@group.calendar.google.com"},
  {"time": "11:00", "vessel": "Jet Ski", "departure_point": "Spanish Water or Piscadera Bay", "calendar_id": "f81a21bbbae8e85f364ee462285ff9f85bcb6f12c0570cac1af63cfe1e850f60@group.calendar.google.com"},
  {"time": "12:00", "vessel": "Jet Ski", "departure_point": "Spanish Water or Piscadera Bay", "calendar_id": "f81a21bbbae8e85f364ee462285ff9f85bcb6f12c0570cac1af63cfe1e850f60@group.calendar.google.com"},
  {"time": "13:00", "vessel": "Jet Ski", "departure_point": "Spanish Water or Piscadera Bay", "calendar_id": "f81a21bbbae8e85f364ee462285ff9f85bcb6f12c0570cac1af63cfe1e850f60@group.calendar.google.com"},
  {"time": "14:00", "vessel": "Jet Ski", "departure_point": "Spanish Water or Piscadera Bay", "calendar_id": "f81a21bbbae8e85f364ee462285ff9f85bcb6f12c0570cac1af63cfe1e850f60@group.calendar.google.com"},
  {"time": "15:00", "vessel": "Jet Ski", "departure_point": "Spanish Water or Piscadera Bay", "calendar_id": "f81a21bbbae8e85f364ee462285ff9f85bcb6f12c0570cac1af63cfe1e850f60@group.calendar.google.com"},
  {"time": "16:00", "vessel": "Jet Ski", "departure_point": "Spanish Water or Piscadera Bay", "calendar_id": "f81a21bbbae8e85f364ee462285ff9f85bcb6f12c0570cac1af63cfe1e850f60@group.calendar.google.com"},
  {"time": "17:00", "vessel": "Jet Ski", "departure_point": "Spanish Water or Piscadera Bay", "calendar_id": "f81a21bbbae8e85f364ee462285ff9f85bcb6f12c0570cac1af63cfe1e850f60@group.calendar.google.com"},
  {"time": "18:00", "vessel": "Jet Ski", "departure_point": "Spanish Water or Piscadera Bay", "calendar_id": "f81a21bbbae8e85f364ee462285ff9f85bcb6f12c0570cac1af63cfe1e850f60@group.calendar.google.com"},
  {"time": "19:00", "vessel": "Jet Ski", "departure_point": "Spanish Water or Piscadera Bay", "calendar_id": "f81a21bbbae8e85f364ee462285ff9f85bcb6f12c0570cac1af63cfe1e850f60@group.calendar.google.com"}
],
```

Remove trip-level `"calendar_id": "f81a21bb...@group.calendar.google.com"` from jet_ski.

Verify the resulting JSON is valid (no trailing commas, correct structure).

---

### Step 2 — `src/state_registry.py`

#### 2a. Add `timedelta` to imports

Change the import line:
```python
from datetime import datetime, timezone
```
to:
```python
from datetime import datetime, timezone, timedelta
```

#### 2b. Add `trip_bookings` table and index to `_get_conn()`

After the `processed_hashes` CREATE TABLE statement (before the `return conn` line), add:

```python
    conn.execute(
        "CREATE TABLE IF NOT EXISTS trip_bookings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "trip_key TEXT NOT NULL, "
        "date TEXT NOT NULL, "
        "departure_time TEXT NOT NULL, "
        "guests INTEGER NOT NULL, "
        "booking_ref TEXT, "
        "status TEXT DEFAULT 'soft_hold', "
        "expires_at TEXT, "
        "created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_trip_bookings_lookup "
        "ON trip_bookings(trip_key, date, departure_time, status)"
    )
```

#### 2c. Add five new public functions

Add all five functions after `mark_as_processed()` and before the module-level `_get_conn().close()` line:

```python
def expire_stale_holds() -> int:
    """Set status='expired' for soft_hold rows past their expires_at. Returns count updated."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "UPDATE trip_bookings SET status='expired' "
        "WHERE status='soft_hold' AND expires_at < ?",
        (now,)
    )
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def get_spots_remaining(trip_key: str, date: str, departure_time: str, capacity: int) -> int:
    """Return capacity minus guests already in soft_hold (non-expired) or confirmed for this slot."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute(
        "SELECT COALESCE(SUM(guests), 0) FROM trip_bookings "
        "WHERE trip_key=? AND date=? AND departure_time=? "
        "AND status IN ('soft_hold', 'confirmed') "
        "AND (status='confirmed' OR expires_at > ?)",
        (trip_key, date, departure_time, now)
    ).fetchone()
    conn.close()
    used = row[0] if row else 0
    return max(0, capacity - used)


def create_soft_hold(
    trip_key: str, date: str, departure_time: str, guests: int, capacity: int
) -> "int | None":
    """
    Atomic: expire stale holds, check remaining capacity, insert soft_hold with 24h TTL.
    Returns the new row id (hold_id) on success, None if at capacity or on error.
    Uses BEGIN IMMEDIATE to serialise concurrent inserts.
    """
    conn = _get_conn()
    conn.isolation_level = None  # switch to manual commit/rollback for BEGIN IMMEDIATE
    now = datetime.now(timezone.utc).isoformat()
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE trip_bookings SET status='expired' "
            "WHERE status='soft_hold' AND expires_at < ?",
            (now,)
        )
        row = conn.execute(
            "SELECT COALESCE(SUM(guests), 0) FROM trip_bookings "
            "WHERE trip_key=? AND date=? AND departure_time=? "
            "AND status IN ('soft_hold', 'confirmed') "
            "AND (status='confirmed' OR expires_at > ?)",
            (trip_key, date, departure_time, now)
        ).fetchone()
        used = row[0] if row else 0
        if used + guests > capacity:
            conn.execute("COMMIT")
            conn.close()
            return None
        cur = conn.execute(
            "INSERT INTO trip_bookings "
            "(trip_key, date, departure_time, guests, status, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, 'soft_hold', ?, ?)",
            (trip_key, date, departure_time, guests, expires_at, now)
        )
        hold_id = cur.lastrowid
        conn.execute("COMMIT")
        conn.close()
        return hold_id
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        conn.close()
        return None


def confirm_hold(hold_id: int) -> bool:
    """Upgrade a soft_hold to confirmed. Clears expires_at. Returns True if row was updated."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE trip_bookings SET status='confirmed', expires_at=NULL "
        "WHERE id=? AND status='soft_hold'",
        (hold_id,)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def cancel_hold(hold_id: int) -> bool:
    """Mark a hold as cancelled. Returns True if row was updated."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE trip_bookings SET status='cancelled' WHERE id=?",
        (hold_id,)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed
```

#### 2d. Update file header

Change `# LAST MODIFIED: Brief 004` to `# LAST MODIFIED: Brief 039`.

---

### Step 3 — `src/gws_calendar.py`

#### 3a. Add `import state_registry` to imports

In the imports block (after `import config_loader`), add:
```python
import state_registry
```

#### 3b. Remove `CALENDARS` dict

Delete the entire `CALENDARS` block:
```python
# Copied verbatim from calendar.js (Brief 031)
CALENDARS = {
    "klein_curacao":    "4ce23ea0e7ec08da249c778969d71c199b8aaf7bf6114efac4fae7e0928f1b31@group.calendar.google.com",
    "snorkeling_3in1":  "114baef90d15890abbcc550dc5ea5edf68d5676a13a0122c099ed9a9a8d52db2@group.calendar.google.com",
    "west_coast_beach": "c24538f8ed2c35306fca340e0e3453bdda717b80274beb6e2e8cae53735e48e0@group.calendar.google.com",
    "sunset_cruise":    "d405cf341b87fcbae36131d910986534fd1d24286632dfa50b1234792aeba2ce@group.calendar.google.com",
    "jet_ski":          "f81a21bbbae8e85f364ee462285ff9f85bcb6f12c0570cac1af63cfe1e850f60@group.calendar.google.com",
}
```

#### 3c. Remove `DURATIONS_HOURS` dict

Delete the entire `DURATIONS_HOURS` block:
```python
DURATIONS_HOURS = {
    "klein_curacao":    8,
    "snorkeling_3in1":  4,
    "west_coast_beach": 6,
    "sunset_cruise":    2.5,
    "jet_ski":          1,
}
```

#### 3d. Replace `check_availability()` entirely

Replace the entire `check_availability` function with:

```python
def check_availability(trip_key: str, date: str, start_time: str, new_guests: int = 1) -> dict:
    """
    Check SQLite capacity for this slot. No gws CLI call.
    Returns {available: bool, spots_remaining: int, capacity: int}.
    """
    state_registry.expire_stale_holds()
    capacity = config_loader.get_trip(trip_key).get("capacity", 20)
    spots = state_registry.get_spots_remaining(trip_key, date, start_time, capacity)
    return {
        "available": spots >= new_guests,
        "spots_remaining": spots,
        "capacity": capacity,
    }
```

#### 3e. Restructure the top of `create_hold()` to resolve `trip` before looking up `calendar_id`

In the current source, the order is: `trip_key` guard → `CALENDARS.get()` guard → `trip = config_loader.get_trip(trip_key)` → `departures` → `start_time`. The calendar_id lookup must come after `trip` and `departures` are resolved, so the entire opening section must be reordered.

Find and replace this exact block (lines from `calendar_id = CALENDARS.get(trip_key, '')` through the end of the `start_time` assignment, inclusive):

```python
    calendar_id = CALENDARS.get(trip_key, '')
    if not calendar_id or not calendar_id.endswith('@group.calendar.google.com'):
        return {'ok': False, 'error': f'Calendar ID not yet configured for: {trip_key}'}

    trip = config_loader.get_trip(trip_key)
    departures = trip.get('departures', [])
    start_time = (
        fields_now.get('departure_time')
        or (departures[0].get('time', '09:00') if departures else '09:00')
    )
```

Replace with:

```python
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
```

Then replace the `dur = DURATIONS_HOURS.get(trip_key, 4)` line (which appears a few lines below) with:
```python
    dur = trip.get('duration_hours', 4)
```

#### 3f. Update file header

Change `# LAST MODIFIED: Brief 032` to `# LAST MODIFIED: Brief 039`.

---

### Step 4 — `src/email_poller.py`

#### 4a. Replace Step 3b entirely

Replace the existing Step 3b block:
```python
                # Step 3b: Availability pre-check when booking summary is being sent
                if (result.get("flags", {}).get("awaiting_booking_confirmation")
                        and not th["flags"].get("slot_checked")):
                    fields_for_check = th["fields"]
                    _ck_trip = fields_for_check.get("trip_key", "")
                    _ck_deps = config_loader.get_trip(_ck_trip).get("departures", []) if _ck_trip else []
                    _ck_start = (fields_for_check.get("departure_time")
                                 or (_ck_deps[0].get("time", "09:00") if _ck_deps else "09:00"))
                    avail = gws_calendar.check_availability(
                        _ck_trip, fields_for_check.get("date", ""), _ck_start)
                    th["flags"]["slot_checked"] = True
                    th["flags"]["slot_available"] = avail.get("available", False)
                    if not avail.get("available"):
                        log(f"Slot unavailable for {from_email}: {avail.get('reason') or avail.get('error')}")
```

with:
```python
                # Step 3b: Availability pre-check + soft hold when booking summary is being sent
                if (result.get("flags", {}).get("awaiting_booking_confirmation")
                        and not th["flags"].get("slot_checked")):
                    fields_for_check = th["fields"]
                    _ck_trip = fields_for_check.get("trip_key", "")
                    _ck_deps = config_loader.get_trip(_ck_trip).get("departures", []) if _ck_trip else []
                    _ck_start = (fields_for_check.get("departure_time")
                                 or (_ck_deps[0].get("time", "09:00") if _ck_deps else "09:00"))
                    _ck_guests = int(fields_for_check.get("guests") or 1)
                    avail = gws_calendar.check_availability(
                        _ck_trip, fields_for_check.get("date", ""), _ck_start, _ck_guests)
                    th["flags"]["slot_checked"] = True
                    th["flags"]["slot_available"] = avail.get("available", False)
                    th["flags"]["spots_remaining"] = avail.get("spots_remaining", 0)
                    th["flags"]["trip_capacity"] = avail.get("capacity", 0)
                    if avail.get("available"):
                        hold_id = state_registry.create_soft_hold(
                            _ck_trip,
                            fields_for_check.get("date", ""),
                            _ck_start,
                            _ck_guests,
                            avail.get("capacity", 20)
                        )
                        if hold_id is not None:
                            th["flags"]["hold_id"] = hold_id
                            log(f"Soft hold created for {from_email}: hold_id={hold_id}, "
                                f"spots_remaining={avail.get('spots_remaining')}")
                        else:
                            # Race: capacity was grabbed between check and insert
                            th["flags"]["slot_available"] = False
                            log(f"Soft hold race for {from_email}: slot full at insert time")
                    else:
                        log(f"Slot unavailable for {from_email}: "
                            f"{avail.get('spots_remaining', 0)}/{avail.get('capacity', 0)} spots remaining")
```

#### 4b. Add date-change soft hold cancellation (two-part insertion around Step 3 flag merge)

**Part 1 — BEFORE the `# Step 3: Persist flags` comment.**

Find this exact line:
```python
                # Step 3: Persist flags
```
Insert this single line immediately before it:
```python
                _was_awaiting = th["flags"].get("awaiting_booking_confirmation", False)
```

**Part 2 — AFTER `th["flags"].update(new_flags)`, before the `log(f"Intents: ...")` line.**

Find this exact sequence:
```python
                th["flags"].update(new_flags)

                log(f"Intents: {result.get('intents')} | Fields: {th['fields']}")
```
Replace with:
```python
                th["flags"].update(new_flags)

                # If awaiting_booking_confirmation cleared without booking_confirmed being set,
                # the customer changed something — cancel old soft hold and reset slot check
                if _was_awaiting and not th["flags"].get("awaiting_booking_confirmation") \
                        and not th["flags"].get("booking_confirmed"):
                    if th["flags"].get("hold_id"):
                        state_registry.cancel_hold(th["flags"]["hold_id"])
                        th["flags"].pop("hold_id", None)
                    th["flags"]["slot_checked"] = False
                    th["flags"]["slot_available"] = False
                    log(f"Soft hold cancelled for {from_email}: customer changed booking details")

                log(f"Intents: {result.get('intents')} | Fields: {th['fields']}")
```

#### 4c. Add `confirm_hold` after successful calendar event creation

Inside the `else:` branch after `res.get("ok")` is True (the hold success path), immediately after the line `th["flags"]["hold_created"] = True`, add:

```python
                            if th["flags"].get("hold_id"):
                                state_registry.confirm_hold(th["flags"]["hold_id"])
```

#### 4d. Add `cancel_hold` after failed calendar event creation

Inside the `if not res.get("ok"):` branch, immediately after `bm_logger.log("hold_failed", ...)`, add:

```python
                            if th["flags"].get("hold_id"):
                                state_registry.cancel_hold(th["flags"]["hold_id"])
```

#### 4e. Update file header

Change `# LAST MODIFIED: Brief 033` to `# LAST MODIFIED: Brief 039`.

---

### Step 5 — `src/marina_agent.py`

#### 5a. Add spots_remaining and trip_capacity to thread context

In `_build_prompt()`, the THREAD CONTEXT section currently reads:
```python
THREAD CONTEXT (already collected this conversation):
  Fields: {json.dumps(thread_fields, ensure_ascii=False)}
  Flags: {json.dumps(thread_flags, ensure_ascii=False)}
```

Change it to:
```python
THREAD CONTEXT (already collected this conversation):
  Fields: {json.dumps(thread_fields, ensure_ascii=False)}
  Flags: {json.dumps(thread_flags, ensure_ascii=False)}
  spots_remaining: {thread_flags.get('spots_remaining', 'unknown')}
  trip_capacity: {thread_flags.get('trip_capacity', 'unknown')}
```

#### 5b. Add AVAILABILITY CONTEXT instruction section

After the ESCALATION BEHAVIOUR section (which ends with "Sign off warmly.") and before the THREAD CONTEXT section, add:

```python
AVAILABILITY CONTEXT:
When spots_remaining is a number in thread flags (not 'unknown'):
- If spots_remaining > 5: mention availability naturally in the booking summary,
  e.g. "There's still plenty of room on this date!"
- If 1 <= spots_remaining <= 5: add gentle urgency, e.g. "Only {{N}} spot(s) left
  for this date — I'd recommend locking it in soon!" (replace {{N}} with the actual number)
- If spots_remaining = 0: do NOT send the booking summary. Apologize warmly,
  explain the slot is fully booked, and suggest 2-3 alternative nearby dates
  for the same trip. Use reply_hold_failed for this message.
Note: Python sets slot_available in thread flags before sending your reply.
When slot_available is false, Python will send reply_hold_failed instead of
reply. Always write both when sending a booking summary.

```

#### 5c. Update file header

Change `# LAST MODIFIED: Brief 038` to `# LAST MODIFIED: Brief 039`.

---

## Tests

Create `bluemarlin/tests/test_039_capacity_soft_holds.py`:

```python
#!/usr/bin/env python3
# bluemarlin/tests/test_039_capacity_soft_holds.py
# Brief 039 — Capacity-aware booking with soft holds
# Run: cd bluemarlin && source ~/.zshrc && python3 tests/test_039_capacity_soft_holds.py

import os, sys, sqlite3, threading, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import state_registry
import gws_calendar
import config_loader

# ── Setup: clear trip_bookings for a clean run ──────────────────────────────
conn = sqlite3.connect(state_registry.DB_PATH)
conn.execute("DELETE FROM trip_bookings WHERE trip_key='klein_curacao' AND date='2026-04-01'")
conn.execute("DELETE FROM trip_bookings WHERE trip_key='klein_curacao' AND date='2026-04-02'")
conn.execute("DELETE FROM trip_bookings WHERE trip_key='jet_ski' AND date='2026-04-01'")
conn.commit()
conn.close()
print("Setup: cleared test rows from trip_bookings\n")

# T1: Book 20 guests Klein Curaçao 2026-04-01 08:00 → succeeds, spots_remaining = 10
print("T1: Book 20 guests klein_curacao 2026-04-01 08:00...")
hold1 = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 20, 30)
assert hold1 is not None, f"T1 fail: create_soft_hold returned None (expected hold_id)"
spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
assert spots == 10, f"T1 fail: expected spots_remaining=10, got {spots}"
print(f"T1 pass — hold_id={hold1}, spots_remaining={spots}")

# T2: Book 15 more guests same slot → FAILS (20+15=35 > 30)
print("\nT2: Book 15 more guests same slot (would exceed capacity)...")
hold2 = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 15, 30)
assert hold2 is None, f"T2 fail: expected None (over capacity), got hold_id={hold2}"
print(f"T2 pass — correctly rejected (hold_id=None)")

# T3: Book 10 more guests same slot → SUCCEEDS (20+10=30, exactly at limit)
print("\nT3: Book 10 more guests same slot (fills to capacity)...")
hold3 = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 10, 30)
assert hold3 is not None, f"T3 fail: expected hold_id, got None (should fit at limit)"
spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
assert spots == 0, f"T3 fail: expected spots_remaining=0, got {spots}"
print(f"T3 pass — hold_id={hold3}, spots_remaining={spots}")

# T4: Book 1 more → FAILS (slot full)
print("\nT4: Book 1 more guest (slot full)...")
hold4 = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 1, 30)
assert hold4 is None, f"T4 fail: expected None (slot full), got hold_id={hold4}"
print(f"T4 pass — correctly rejected when full")

# T5: Same trip 08:30 → independent slot, 30 available
print("\nT5: Klein Curaçao 08:30 — independent slot...")
avail5 = gws_calendar.check_availability("klein_curacao", "2026-04-01", "08:30", 1)
assert avail5["available"], f"T5 fail: 08:30 slot should be independent, got {avail5}"
assert avail5["spots_remaining"] == 30, \
    f"T5 fail: expected 30 spots for 08:30, got {avail5['spots_remaining']}"
print(f"T5 pass — 08:30 independent: spots_remaining={avail5['spots_remaining']}")

# T6: Same trip April 2 → fresh slot, 30 available
print("\nT6: Klein Curaçao April 2 — fresh date...")
avail6 = gws_calendar.check_availability("klein_curacao", "2026-04-02", "08:00", 1)
assert avail6["available"], f"T6 fail: April 2 should be fresh, got {avail6}"
assert avail6["spots_remaining"] == 30, \
    f"T6 fail: expected 30 for April 2, got {avail6['spots_remaining']}"
print(f"T6 pass — April 2 fresh: spots_remaining={avail6['spots_remaining']}")

# T7: Simulate 24h expiry → expired hold's guests released
# get_spots_remaining filters by expires_at > now, so an already-expired row
# is already invisible to it. To correctly test expiry, we must:
# 1. Insert an ACTIVE hold (expires far in the future) → capacity consumed
# 2. Verify spots are consumed (spots_before == 0)
# 3. Force-expire by updating expires_at to the past via direct SQL
# 4. Call expire_stale_holds() → status becomes 'expired'
# 5. Verify spots are released (spots_after == 4)
print("\nT7: Simulate expired hold...")
conn = sqlite3.connect(state_registry.DB_PATH)
conn.execute("DELETE FROM trip_bookings WHERE trip_key='jet_ski' AND date='2026-04-01'")
future_exp = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
now_str = datetime.now(timezone.utc).isoformat()
conn.execute(
    "INSERT INTO trip_bookings "
    "(trip_key, date, departure_time, guests, status, expires_at, created_at) "
    "VALUES ('jet_ski', '2026-04-01', '10:00', 4, 'soft_hold', ?, ?)",
    (future_exp, now_str)
)
conn.commit()
conn.close()
spots_before = state_registry.get_spots_remaining("jet_ski", "2026-04-01", "10:00", 4)
assert spots_before == 0, f"T7 fail: expected 0 spots with active hold, got {spots_before}"
# Force expiry by backdating expires_at
conn = sqlite3.connect(state_registry.DB_PATH)
conn.execute(
    "UPDATE trip_bookings SET expires_at='2020-01-01T00:00:00+00:00' "
    "WHERE trip_key='jet_ski' AND date='2026-04-01' AND departure_time='10:00'"
)
conn.commit()
conn.close()
expired_count = state_registry.expire_stale_holds()
assert expired_count >= 1, f"T7 fail: expected at least 1 expired hold, got {expired_count}"
spots_after = state_registry.get_spots_remaining("jet_ski", "2026-04-01", "10:00", 4)
assert spots_after == 4, f"T7 fail: expected 4 spots after expiry, got {spots_after}"
print(f"T7 pass — expired_count={expired_count}, spots_after={spots_after}")

# T8: Concurrent race — two threads both check available, only one gets the last spot
print("\nT8: Concurrent race for last spot...")
conn = sqlite3.connect(state_registry.DB_PATH)
conn.execute("DELETE FROM trip_bookings WHERE trip_key='klein_curacao' AND date='2026-04-01'")
conn.commit()
conn.close()
# Pre-fill 29 guests so only 1 spot remains
hold_pre = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 29, 30)
assert hold_pre is not None, "T8 setup fail"

results = []
def try_grab(guests):
    hid = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", guests, 30)
    results.append(hid)

t1 = threading.Thread(target=try_grab, args=(1,))
t2 = threading.Thread(target=try_grab, args=(1,))
t1.start(); t2.start()
t1.join(); t2.join()

successful = [r for r in results if r is not None]
failed = [r for r in results if r is None]
assert len(successful) == 1, \
    f"T8 fail: expected exactly 1 success, got {len(successful)} successes. results={results}"
assert len(failed) == 1, \
    f"T8 fail: expected exactly 1 failure, got {len(failed)} failures. results={results}"
print(f"T8 pass — race handled correctly: 1 success (hold_id={successful[0]}), 1 rejected")

# ── Schema checks ────────────────────────────────────────────────────────────
print("\nSchema check: client.json departure-level calendar_ids...")
kc = config_loader.get_trip("klein_curacao")
assert kc.get("capacity") == 30, f"Schema fail: klein_curacao capacity={kc.get('capacity')}"
assert "calendar_id" not in kc, "Schema fail: trip-level calendar_id still present on klein_curacao"
kc_deps = kc.get("departures", [])
assert len(kc_deps) == 2, f"Schema fail: expected 2 klein_curacao departures, got {len(kc_deps)}"
assert kc_deps[0].get("time") == "08:00", f"Schema fail: first departure not 08:00"
assert kc_deps[0].get("calendar_id", "").endswith("@group.calendar.google.com"), \
    "Schema fail: 08:00 departure missing calendar_id"
assert kc_deps[1].get("time") == "08:30", f"Schema fail: second departure not 08:30"
assert kc_deps[1].get("calendar_id") == \
    "9f25610370f0f57fa395735502fcff767ba8276ee5a280d028fee7f003054928@group.calendar.google.com", \
    f"Schema fail: 08:30 calendar_id wrong"
print("Schema pass — klein_curacao: capacity=30, 2 departure-level calendar_ids")

jk = config_loader.get_trip("jet_ski")
assert jk.get("capacity") == 4, f"Schema fail: jet_ski capacity={jk.get('capacity')}"
assert jk.get("duration_hours") == 1, f"Schema fail: jet_ski duration_hours={jk.get('duration_hours')}"
assert "calendar_id" not in jk, "Schema fail: trip-level calendar_id still present on jet_ski"
jk_deps = jk.get("departures", [])
assert len(jk_deps) == 12, f"Schema fail: jet_ski should have 12 departures, got {len(jk_deps)}"
assert jk_deps[0].get("time") == "08:00", f"Schema fail: first jet_ski departure not 08:00"
assert jk_deps[-1].get("time") == "19:00", f"Schema fail: last jet_ski departure not 19:00"
print("Schema pass — jet_ski: capacity=4, duration_hours=1, 12 hourly departures 08:00–19:00")

print("\nAll 8 tests + schema checks passed.")
```

---

## Success Condition

`python3 tests/test_039_capacity_soft_holds.py` prints "All 8 tests + schema checks passed." with no assertion errors.

---

## Rollback

1. Revert `client.json` changes: restore original `departures` arrays (without `calendar_id` inside), restore trip-level `calendar_id` keys, remove `capacity` fields, remove jet_ski `duration_hours`.
2. Revert `state_registry.py`: remove the five new functions, remove the `trip_bookings` table and index from `_get_conn()`, change `timedelta` import back to `datetime, timezone`. The `trip_bookings` table in the DB will persist but is harmless until the module re-creates it on next import.
3. Revert `gws_calendar.py`: restore `CALENDARS` and `DURATIONS_HOURS` dicts, restore original `check_availability()` (gws CLI version), restore `CALENDARS.get(trip_key)` and `DURATIONS_HOURS.get(trip_key)` in `create_hold()`, remove `import state_registry`.
4. Revert `email_poller.py`: restore original Step 3b, remove `_was_awaiting` block and date-change cancellation, remove `confirm_hold`/`cancel_hold` calls from Step 4.
5. Revert `marina_agent.py`: remove `spots_remaining`/`trip_capacity` from thread context, remove AVAILABILITY CONTEXT section.
