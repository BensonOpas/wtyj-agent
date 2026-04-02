# BRIEF 052 — Sheets: Manifests summary tab
**Status:** Draft | **Files:** sheets_writer.py, format_sheets.py, email_poller.py | **Depends on:** Brief 051 | **Blocks:** nothing

## Context
The booking system now writes manifest-style calendar events (one per departure slot) but the Google Sheets dashboard has no aggregated view. The Bookings tab shows individual customer rows — the operator cannot see total attendance, revenue, or confirmed/pending counts per departure at a glance. A Manifests tab that mirrors the calendar manifest data would give the operator a quick summary view.

## Why This Approach
We could query state_registry at format time to build a summary, but that only works on-demand. Instead, we log a manifest summary row to Sheets every time a manifest event is created or updated (i.e., every successful booking). Each row represents the state of a departure slot at the time of the booking — latest row for a given slot is the current state. This is consistent with how the other tabs work (append-only logging). The alternative — updating a single row per slot in-place — would require `sheets.spreadsheets.values.update` with row lookup, which is fragile and slow.

**Revenue approximation:** Revenue is computed as `total_guests * price_adult_usd`. The system supports child pricing (Brief 038, `price_child_usd` in client.json), but `trip_bookings` does not store per-booking price. This is a known approximation — revenue figures will be slightly inflated for bookings that include children. Accurate per-booking revenue tracking would require adding a `price_paid` column to `trip_bookings`, which is out of scope for this brief.

**Manual Sheets tab creation:** The "Manifests" tab must be created manually in the Google Sheet before the first booking is logged. This follows the same pattern as the Escalations tab (documented in CLAUDE.md Known Open Issues). Without the tab, `_append()` will fail silently.

## Source Material

### sheets_writer.py existing `_append()` pattern (used by all log functions)
```python
def _append(tab_name: str, row: list) -> None:
    spreadsheet_id = _get_spreadsheet_id()
    params = json.dumps({
        'spreadsheetId': spreadsheet_id,
        'range': f'{tab_name}!A:A',
        'valueInputOption': 'USER_ENTERED',
        'insertDataOption': 'INSERT_ROWS',
    })
    body = json.dumps({'values': [row]})
    env = os.environ.copy()
    env['GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE'] = KEY_PATH
    try:
        r = subprocess.run(
            ['gws', 'sheets', 'spreadsheets', 'values', 'append',
             '--params', params, '--json', body],
            capture_output=True, text=True, timeout=30,
            env=env
        )
```

### format_sheets.py TABS list pattern
```python
TABS = [
    {'name': 'Bookings',     'headers': BOOKINGS_HEADERS,     'widths': BOOKINGS_WIDTHS},
    {'name': 'Complaints',   'headers': COMPLAINTS_HEADERS,   'widths': COMPLAINTS_WIDTHS},
    {'name': 'All Events',   'headers': ALL_EVENTS_HEADERS,   'widths': ALL_EVENTS_WIDTHS},
    {'name': 'Escalations',  'headers': ESCALATIONS_HEADERS,  'widths': ESCALATIONS_WIDTHS},
]
```

### email_poller.py Step 5 success path — manifest + booking log (lines ~813–859)
After `create_or_update_manifest()` succeeds, the code logs to bm_logger and calls `sheets_writer.log_hold_created()`. The new `sheets_writer.log_manifest_update()` call goes here, immediately after `sheets_writer.log_hold_created()`.

### Data available at the Step 5 success point
- `fields_now` dict with: trip_key, date, departure_time, guests, customer_name, phone, experience, special_requests
- `res` dict with: ok, eventId, htmlLink
- `booking_ref` string
- `price_usd` int (per-guest price)
- `config_loader.get_trip(trip_key)` gives: capacity, display_name

### state_registry.get_slot_passengers() returns
```python
[{"id": int, "guests": int, "booking_ref": str, "status": str,
  "customer_name": str, "customer_email": str, "created_at": str}, ...]
```

## Instructions

### Step 1 — Add `log_manifest_update()` to sheets_writer.py

Add the following function after `log_hold_failed()` (before `log_escalation()`):

```python
def log_manifest_update(data: dict):
    """Log a manifest summary row to the Manifests tab."""
    try:
        row = [
            _now(),
            data.get('trip_key', ''),
            data.get('date', ''),
            data.get('departure_time', ''),
            str(data.get('total_guests', '')),
            str(data.get('capacity', '')),
            str(data.get('confirmed_count', '')),
            str(data.get('pending_count', '')),
            f"${data.get('total_revenue', 0):,} USD",
            data.get('calendar_link', ''),
            data.get('booking_ref', ''),
        ]
        _append('Manifests', row)
    except Exception as e:
        print(f"sheets_writer: log_manifest_update error: {e}")
```

Update the file header: `# LAST MODIFIED: Brief 052`

### Step 2 — Add Manifests tab config to format_sheets.py

Add the following constants immediately after the `ESCALATIONS_WIDTHS` line:

```python
MANIFESTS_HEADERS = [
    'Timestamp', 'Trip', 'Date', 'Departure', 'Total Guests',
    'Capacity', 'Confirmed', 'Pending', 'Revenue', 'Calendar Link',
    'Last Booking Ref'
]
MANIFESTS_WIDTHS = [180, 160, 110, 100, 100, 80, 90, 80, 130, 220, 130]
```

Add the Manifests entry to the TABS list:

```python
TABS = [
    {'name': 'Bookings',     'headers': BOOKINGS_HEADERS,     'widths': BOOKINGS_WIDTHS},
    {'name': 'Complaints',   'headers': COMPLAINTS_HEADERS,   'widths': COMPLAINTS_WIDTHS},
    {'name': 'All Events',   'headers': ALL_EVENTS_HEADERS,   'widths': ALL_EVENTS_WIDTHS},
    {'name': 'Escalations',  'headers': ESCALATIONS_HEADERS,  'widths': ESCALATIONS_WIDTHS},
    {'name': 'Manifests',    'headers': MANIFESTS_HEADERS,    'widths': MANIFESTS_WIDTHS},
]
```

Update the file header: `# LAST MODIFIED: Brief 052`

### Step 3 — Call `log_manifest_update()` from email_poller.py

In Step 5 success path, immediately after the `sheets_writer.log_hold_created({...})` call (around line 858), add:

```python
                            # Log manifest summary to Sheets
                            _manifest_trip_key = fields_now.get("trip_key", "")
                            _manifest_passengers = state_registry.get_slot_passengers(
                                _manifest_trip_key,
                                fields_now.get("date", ""),
                                fields_now.get("departure_time", ""),
                            )
                            _manifest_confirmed = sum(1 for p in _manifest_passengers if p["status"] == "confirmed")
                            _manifest_pending = sum(1 for p in _manifest_passengers if p["status"] == "soft_hold")
                            _manifest_total_guests = sum(p["guests"] for p in _manifest_passengers)
                            _manifest_total_revenue = _manifest_total_guests * price_usd
                            _manifest_capacity = config_loader.get_trip(_manifest_trip_key).get("capacity", 20)
                            sheets_writer.log_manifest_update({
                                "trip_key": _manifest_trip_key,
                                "date": fields_now.get("date", ""),
                                "departure_time": fields_now.get("departure_time", ""),
                                "total_guests": _manifest_total_guests,
                                "capacity": _manifest_capacity,
                                "confirmed_count": _manifest_confirmed,
                                "pending_count": _manifest_pending,
                                "total_revenue": _manifest_total_revenue,
                                "calendar_link": th["flags"].get("event_link", ""),
                                "booking_ref": booking_ref,
                            })
```

Update the file header: `# LAST MODIFIED: Brief 052`

### Step 4 — Update file headers

- sheets_writer.py: Change `# LAST MODIFIED: Brief 040` to `# LAST MODIFIED: Brief 052`
- format_sheets.py: Change `# LAST MODIFIED: Brief 049` to `# LAST MODIFIED: Brief 052`
- email_poller.py: Change `# LAST MODIFIED: Brief 051` to `# LAST MODIFIED: Brief 052`

## Tests

Create `bluemarlin/tests/test_052_manifests_sheet_tab.py`:

```python
#!/usr/bin/env python3
"""Tests for Brief 052 — Manifests sheet tab."""
import sys, os
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

print("Running Brief 052 tests...")

# ── sheets_writer.py ──
import sheets_writer
import inspect

# T1: log_manifest_update function exists
check("T1: log_manifest_update exists", hasattr(sheets_writer, "log_manifest_update"))

# T2: log_manifest_update is callable
check("T2: log_manifest_update is callable", callable(getattr(sheets_writer, "log_manifest_update", None)))

# T3: log_manifest_update accepts data dict
sig = inspect.signature(sheets_writer.log_manifest_update)
params = list(sig.parameters.keys())
check("T3: log_manifest_update param is 'data'", params == ["data"])

# T4: sheets_writer header says Brief 052
with open(os.path.join(os.path.dirname(__file__), "..", "src", "sheets_writer.py")) as f:
    sw_src = f.read()
check("T4: sheets_writer header says Brief 052", "Brief 052" in sw_src)

# T5: log_manifest_update appends to 'Manifests' tab
check("T5: 'Manifests' tab name in log_manifest_update", "'Manifests'" in sw_src)

# ── format_sheets.py ──
with open(os.path.join(os.path.dirname(__file__), "..", "src", "format_sheets.py")) as f:
    fs_src = f.read()

# T6: MANIFESTS_HEADERS defined
check("T6: MANIFESTS_HEADERS defined", "MANIFESTS_HEADERS" in fs_src)

# T7: MANIFESTS_WIDTHS defined
check("T7: MANIFESTS_WIDTHS defined", "MANIFESTS_WIDTHS" in fs_src)

# T8: MANIFESTS_HEADERS has 11 columns
import format_sheets
check("T8: MANIFESTS_HEADERS has 11 columns", len(format_sheets.MANIFESTS_HEADERS) == 11)

# T9: MANIFESTS_WIDTHS has 11 values
check("T9: MANIFESTS_WIDTHS has 11 values", len(format_sheets.MANIFESTS_WIDTHS) == 11)

# T10: Manifests tab in TABS list
tab_names = [t["name"] for t in format_sheets.TABS]
check("T10: 'Manifests' in TABS list", "Manifests" in tab_names)

# T11: Manifests tab headers match MANIFESTS_HEADERS
manifests_tab = next(t for t in format_sheets.TABS if t["name"] == "Manifests")
check("T11: Manifests tab headers match", manifests_tab["headers"] is format_sheets.MANIFESTS_HEADERS)

# T12: Manifests tab widths match MANIFESTS_WIDTHS
check("T12: Manifests tab widths match", manifests_tab["widths"] is format_sheets.MANIFESTS_WIDTHS)

# T13: format_sheets header says Brief 052
check("T13: format_sheets header says Brief 052", "Brief 052" in fs_src)

# T14: MANIFESTS_HEADERS first column is 'Timestamp'
check("T14: First header is 'Timestamp'", format_sheets.MANIFESTS_HEADERS[0] == "Timestamp")

# T15: MANIFESTS_HEADERS contains 'Revenue'
check("T15: Headers contain 'Revenue'", "Revenue" in format_sheets.MANIFESTS_HEADERS)

# T16: MANIFESTS_HEADERS contains 'Calendar Link'
check("T16: Headers contain 'Calendar Link'", "Calendar Link" in format_sheets.MANIFESTS_HEADERS)

# ── email_poller.py ──
with open(os.path.join(os.path.dirname(__file__), "..", "src", "email_poller.py")) as f:
    ep_src = f.read()

# T17: log_manifest_update called in email_poller
check("T17: log_manifest_update in email_poller", "sheets_writer.log_manifest_update(" in ep_src)

# T18: get_slot_passengers called in email_poller Step 5
check("T18: get_slot_passengers in email_poller", "state_registry.get_slot_passengers(" in ep_src)

# T19: log_manifest_update called after log_hold_created
pos_hold = ep_src.find("sheets_writer.log_hold_created(")
pos_manifest = ep_src.find("sheets_writer.log_manifest_update(")
check("T19: log_manifest_update after log_hold_created", 0 < pos_hold < pos_manifest)

# T20: email_poller header says Brief 052
check("T20: email_poller header says Brief 052", "Brief 052" in ep_src)

# T21: manifest log includes capacity
check("T21: 'capacity' in manifest log call",
      '"capacity":' in ep_src[pos_manifest:pos_manifest+600] or "'capacity':" in ep_src[pos_manifest:pos_manifest+600])

# T22: manifest log includes total_revenue
check("T22: 'total_revenue' in manifest log call",
      '"total_revenue":' in ep_src[pos_manifest:pos_manifest+600] or "'total_revenue':" in ep_src[pos_manifest:pos_manifest+600])

# ── Behavioral tests: call log_manifest_update with known data ──
# Monkey-patch _append to capture the row instead of calling gws
_captured_rows = []
_orig_append = sheets_writer._append
def _mock_append(tab_name, row):
    _captured_rows.append((tab_name, row))
sheets_writer._append = _mock_append

try:
    sheets_writer.log_manifest_update({
        "trip_key": "klein_curacao",
        "date": "2026-04-01",
        "departure_time": "08:00",
        "total_guests": 12,
        "capacity": 30,
        "confirmed_count": 2,
        "pending_count": 1,
        "total_revenue": 1440,
        "calendar_link": "https://calendar.google.com/event?eid=abc123",
        "booking_ref": "BF-2026-50123",
    })
finally:
    sheets_writer._append = _orig_append

# T23: _append was called with 'Manifests' tab
check("T23: _append called with 'Manifests' tab",
      len(_captured_rows) == 1 and _captured_rows[0][0] == "Manifests")

_row = _captured_rows[0][1] if _captured_rows else []

# T24: row has 11 columns
check("T24: row has 11 columns", len(_row) == 11)

# T25: revenue formatted as "$1,440 USD"
check("T25: revenue formatted as '$1,440 USD'", _row[8] == "$1,440 USD" if len(_row) > 8 else False)

# T26: booking_ref is last column
check("T26: booking_ref 'BF-2026-50123' in last column",
      _row[10] == "BF-2026-50123" if len(_row) > 10 else False)

# T27: trip_key is second column
check("T27: trip_key 'klein_curacao' in column 1",
      _row[1] == "klein_curacao" if len(_row) > 1 else False)

# T28: capacity as string '30' in column 5
check("T28: capacity '30' in column 5",
      _row[5] == "30" if len(_row) > 5 else False)

print(f"\n{passed}/{passed+failed} tests passed.")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("All tests passed.")
```

## Success Condition
All 28 tests pass. `sheets_writer.log_manifest_update()` exists and is called from email_poller.py after each successful manifest creation. `format_sheets.py` includes the Manifests tab with 11-column headers and widths.

## Rollback
Revert changes to sheets_writer.py, format_sheets.py, email_poller.py. Delete test file. If the Manifests tab was already created in Google Sheets, it can be left in place (no harm from an empty tab).
