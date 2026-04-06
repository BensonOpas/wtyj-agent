# BRIEF 134 — Rename: Trips→Services, Generalize Config
**Status:** Draft | **Files:** ALL source, config, tests | **Depends on:** Brief 133 | **Blocks:** Brief 135 (config-driven booking), Brief 136 (optional fields)

## Context

The codebase uses charter-specific naming throughout: `trips`, `trip_key`, `departures`, `vessel`, `departure_point`, `experience`, `price_adult_usd`. A restaurant, salon, or real estate client can't use this system without confusion. This is a mechanical rename — no logic changes, just names. Backup at `bluemarlin/backups/snapshot_20260401_pre_brief134`.

## Why This Approach

One atomic brief. Everything renamed in one commit. No half-renamed state, no backward-compat aliases. If something breaks, restore from backup. The rename map was audited across the entire codebase (150+ occurrences, 20+ files).

## Rename Map

| Current | New | Why |
|---|---|---|
| `trips` (config section) | `services` | Not every business sells trips |
| `trip_key` (field/column/param) | `service_key` | Follows from above |
| `trip_aliases` (config section) | `service_aliases` | Follows |
| `fleet` (config section) | `resources` | Vessels are one type; stylists, rooms, agents are others |
| `departures` (config array in each service) | `slots` | Not everything departs |
| `departure_time` (field/column) | `slot_time` | Follows |
| `departure_point` (config field) | `location` | Generic |
| `vessel` (config field) | `resource` | Follows from fleet→resources |
| `experience` (booking field) | `service_name` | "Experience" is charter jargon |
| `price_adult_usd` (config field) | `price` | Base price, not adult-specific |
| `price_child_usd` (config field) | `price_child` | Shorter, still clear |
| `trip_bookings` (DB table) | `service_bookings` | Follows |
| `get_trips()` | `get_services()` | config_loader function |
| `get_trip(trip_key)` | `get_service(service_key)` | config_loader function |
| `get_trip_aliases()` | `get_service_aliases()` | config_loader function |
| `get_fleet()` | `get_resources()` | config_loader function |

**NOT renaming:** `guests`, `booking_ref`, `capacity`, `duration_hours`, `hold_id`, `calendar_id`, `booking_confirmed`, `awaiting_booking_confirmation`. These are already generic.

## Instructions

### Step 1: `config/client.json`

Rename the following keys:
- Top-level `"trips"` → `"services"`
- Top-level `"trip_aliases"` → `"service_aliases"`
- Top-level `"fleet"` → `"resources"`
- In `booking_rules.required_fields`: `"experience"` → `"service_name"`
- Inside each service object:
  - `"departures"` array → `"slots"`
  - Inside each slot: `"vessel"` → `"resource"`, `"departure_point"` → `"location"`
  - `"price_adult_usd"` → `"price"`
  - `"price_child_usd"` → `"price_child"`

### Step 2: `shared/config_loader.py`

Rename functions:
- `get_trips()` → `get_services()` — reads `_load().get("services", {})`
- `get_trip(trip_key)` → `get_service(service_key)` — reads from `get_services()`
- `get_trip_aliases()` → `get_service_aliases()` — reads `_load().get("service_aliases", {})`
- `get_fleet()` → `get_resources()` — reads `_load().get("resources", {})`

### Step 3: `shared/state_registry.py`

**Database migration in `_get_conn()`:**
```python
# Schema migration: rename trip_bookings → service_bookings
try:
    conn.execute("ALTER TABLE trip_bookings RENAME TO service_bookings")
except sqlite3.OperationalError:
    pass
# Rename columns
try:
    conn.execute("ALTER TABLE service_bookings RENAME COLUMN trip_key TO service_key")
except sqlite3.OperationalError:
    pass
try:
    conn.execute("ALTER TABLE service_bookings RENAME COLUMN departure_time TO slot_time")
except sqlite3.OperationalError:
    pass
# manifest_events table
try:
    conn.execute("ALTER TABLE manifest_events RENAME COLUMN trip_key TO service_key")
except sqlite3.OperationalError:
    pass
try:
    conn.execute("ALTER TABLE manifest_events RENAME COLUMN departure_time TO slot_time")
except sqlite3.OperationalError:
    pass
# bookings table
try:
    conn.execute("ALTER TABLE bookings RENAME COLUMN trip_key TO service_key")
except sqlite3.OperationalError:
    pass
try:
    conn.execute("ALTER TABLE bookings RENAME COLUMN departure_time TO slot_time")
except sqlite3.OperationalError:
    pass
# photo_library table
try:
    conn.execute("ALTER TABLE photo_library RENAME COLUMN trip_key TO service_key")
except sqlite3.OperationalError:
    pass
```

Also update the CREATE TABLE statements to use new names (for fresh databases):
- `trip_bookings` → `service_bookings` with `service_key`, `slot_time`
- `manifest_events` with `service_key`, `slot_time`
- `bookings` with `service_key`, `slot_time`
- `photo_library` with `service_key`

Update all index names: `idx_trip_bookings_lookup` → `idx_service_bookings_lookup`

Update ALL function bodies: every SQL query and function parameter that references `trip_key`, `departure_time` (as column), or `trip_bookings` (as table).

Search for: `trip_key`, `departure_time` (in SQL strings only — not the Python variable in non-DB contexts), `trip_bookings`, `price_adult_usd` in state_registry.py and rename.

### Step 4: `agents/marina/marina_agent.py`

- `_SKIP_TOP_LEVEL = {"trip_aliases"}` → `{"service_aliases"}`
- `_build_trip_alias_text()` → `_build_service_alias_text()` — references `get_service_aliases()`
- `_build_client_context()`: rename `"departures"` checks to `"slots"` (lines ~59-64 check `"departures" in v` to strip `calendar_id` from slot entries — MUST be updated to `"slots"` or calendar IDs leak into the Claude prompt)
- All prompt text: `trip_key` → `service_key`, `experience` field description → `service_name`, `departure_time` field description → `slot_time`
- Fallback `clarifications_needed`: `["date", "guests", "experience"]` → `["date", "guests", "service_name"]`
- Every `config_loader.get_trip(...)` → `config_loader.get_service(...)`
- Every `config_loader.get_trips()` → `config_loader.get_services()`

### Step 5: `agents/marina/email_poller.py`

- All `fields.get("trip_key")` → `fields.get("service_key")`
- All `fields.get("experience")` → `fields.get("service_name")`
- All `fields.get("departure_time")` → `fields.get("slot_time")`
- `config_loader.get_trip(...)` → `config_loader.get_service(...)`
- `config_loader.get_trips()` → `config_loader.get_services()`
- `trip.get("departures")` → `service.get("slots")`
- `dep_info.get("vessel")` → `slot_info.get("resource")`
- `dep_info.get("departure_point")` → `slot_info.get("location")`
- `trip.get("price_adult_usd")` → `service.get("price")`
- Variable renames: `trip` → `service`, `dep_info` → `slot_info`, `dep_point` → `location`
- `_build_booking_summary(fields, trip)` → `_build_booking_summary(fields, service)`
- Booking ref regex prefix already config-driven (Brief 133)

### Step 6: `agents/social/social_agent.py`

Same pattern as email_poller:
- All `trip_key` → `service_key` in fields, flags, function calls
- All `experience` → `service_name` in fields
- All `departure_time` → `slot_time` in fields and flags (`hold_departure_time` → `hold_slot_time`, `hold_trip_key` → `hold_service_key`)
- `_build_booking_summary(fields, trip)` → `_build_booking_summary(fields, service)`
- `config_loader.get_trip(...)` → `config_loader.get_service(...)`
- `trip.get("departures")` → `service.get("slots")`
- `dep_info.get("vessel")` → `slot_info.get("resource")`
- `dep_info.get("departure_point")` → `slot_info.get("location")`
- `trip.get("price_adult_usd")` → `service.get("price")`
- `_PERSISTENT_FIELDS` if it contains `"trip_key"` or `"experience"` — rename

### Step 7: `agents/marina/gws_calendar.py`

- All `trip_key` → `service_key` in parameters and function bodies
- `departure_time` → `slot_time` in parameters and SQL-related calls
- `config_loader.get_trip(...)` → `config_loader.get_service(...)`
- `trip.get("price_adult_usd")` → `service.get("price")`
- Variable renames: `trip` → `service` where it holds config data

### Step 8: `agents/marina/sheets_writer.py`

- All `data.get('trip_key')` → `data.get('service_key')`
- All `data.get('experience')` → `data.get('service_name')`
- All `data.get('departure_time')` → `data.get('slot_time')`

### Step 9: `agents/social/dm_agent.py`

- `config_loader.get_trips()` → `config_loader.get_services()`
- Any `trip` references in the Q&A prompt → `service`

### Step 10: `agents/social/content_agent.py`

- `config_loader.get_trips()` → `config_loader.get_services()`
- `_SKIP_TOP_LEVEL = {"trip_aliases"}` → `{"service_aliases"}` (line ~19)
- `_build_client_context()`: rename `"departures"` checks to `"slots"` (same pattern as marina_agent.py — strips calendar_id from slot entries)
- Any `trip` variable names → `service`

### Step 11: `dashboard/api.py`

- All `trip_key` references → `service_key`
- `config_loader.get_trips()` → `config_loader.get_services()`
- `config_loader.get_trip(...)` → `config_loader.get_service(...)`

### Step 12: All test files

Every test file that references renamed fields/functions/tables. Use find-and-replace:
- `trip_key` → `service_key`
- `experience` (as dict key in test data) → `service_name`
- `departure_time` (as dict key in test data) → `slot_time`
- `get_trips` → `get_services`
- `get_trip(` → `get_service(`
- `trip_bookings` → `service_bookings`
- `"departures"` → `"slots"`
- `"vessel"` → `"resource"`
- `"departure_point"` → `"location"`
- `price_adult_usd` → `price`
- `hold_trip_key` → `hold_service_key`
- `hold_departure_time` → `hold_slot_time`

### Step 13: Migrate JSON blobs in WhatsApp booking state

The `whatsapp_booking_state` table stores `fields_json` and `flags_json` as JSON strings containing old field names (`trip_key`, `experience`, `departure_time`, `hold_trip_key`, `hold_departure_time`). These need a one-time data migration.

Add a migration function in `state_registry.py` called from `_get_conn()`:

```python
def _migrate_booking_state_field_names(conn):
    """One-time migration: rename old field names in JSON blobs."""
    rows = conn.execute("SELECT phone, fields_json, flags_json FROM whatsapp_booking_state").fetchall()
    renames = {"trip_key": "service_key", "experience": "service_name", "departure_time": "slot_time"}
    flag_renames = {"hold_trip_key": "hold_service_key", "hold_departure_time": "hold_slot_time"}
    for phone, fields_str, flags_str in rows:
        fields = json.loads(fields_str or "{}")
        flags = json.loads(flags_str or "{}")
        changed = False
        for old, new in renames.items():
            if old in fields:
                fields[new] = fields.pop(old)
                changed = True
        for old, new in flag_renames.items():
            if old in flags:
                flags[new] = flags.pop(old)
                changed = True
        if changed:
            conn.execute("UPDATE whatsapp_booking_state SET fields_json = ?, flags_json = ? WHERE phone = ?",
                         (json.dumps(fields), json.dumps(flags), phone))
    if rows:
        conn.commit()
```

Call it once in `_get_conn()` after the column renames, guarded by a check (e.g., only run if any row still has `"trip_key"` in its fields_json).

### Step 14: Migrate email thread state JSON

The email poller stores thread state in `/root/bluemarlin/config/email_thread_state.json` with the same old field names in `fields` and `flags` dicts. Add a similar migration at email_poller startup — load the JSON, rename keys in each thread's fields/flags, save back. Guard with a check so it only runs once.

### Step 15: Update stale ALTER TABLE references

In `state_registry.py`, any existing `ALTER TABLE trip_bookings ADD COLUMN ...` lines (for customer_name, customer_email migrations) must be updated to reference `service_bookings`. These are in try/except blocks so they won't crash, but they'd be dead code and fail the success condition grep.

### Step 16: Fix hardcoded trip names in email_poller anti-loop

`email_poller.py` line ~600 has a hardcoded string `"1) Experience (Klein Curaçao / Sunset Cruise / West Coast Beach / Snorkeling / Jet Ski)"`. This is a pre-existing Rule 3 violation. For this brief: rename "Experience" to "Service" in that string. The specific trip names are client data that should come from config — flag as a follow-up but don't block this brief on it.

### Step 17: Database migration on VPS

After deploying, the `_get_conn()` migrations run automatically on first connection. Verify by checking:
```sql
SELECT name FROM sqlite_master WHERE type='table';
```
Should show `service_bookings` not `trip_bookings`.

## Tests

After the rename, run the FULL test suite. Every test should pass with the new names. No new test file needed — this is a mechanical rename that existing tests validate.

Expected: same pass count as before (306 social + marina + other), minus the 2 pre-existing stale date failures.

## Success Condition

`grep -r "trip_key\|get_trips\|get_trip(\|trip_aliases\|get_fleet\|price_adult_usd\|departure_point\|\"vessel\"\|\"departures\"\|trip_bookings\|hold_trip_key\|hold_departure_time" bluemarlin/ --include="*.py" --include="*.json" | grep -v backups | grep -v archive | grep -v __pycache__` returns zero results. All tests pass. System behavior unchanged.

## Rollback

1. Restore code from `bluemarlin/backups/snapshot_20260401_pre_brief134`
2. On VPS: restore the DB backup (`cp backups/state_registry_pre_134.db data/state_registry.db`) — make a DB backup before deploying
3. Both code AND database must be restored together — restoring only code leaves the DB with renamed tables that the old code can't find
