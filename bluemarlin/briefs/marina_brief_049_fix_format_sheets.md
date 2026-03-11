# BRIEF 049 — Fix format_sheets.py + apply formatting to new dashboard
**Status:** Draft | **Files:** format_sheets.py | **Depends on:** Brief 032 (gws migration), Brief 028 (sheets columns) | **Blocks:** nothing

## Context
The old Google Sheet was banned. A new plain sheet (`1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I`) is in use — it has data but zero formatting (no colors, no column widths, no banding). `format_sheets.py` cannot run because Brief 032 removed `_get_service()` and the module-level `SPREADSHEET_ID` constant from `sheets_writer.py`, but format_sheets still imports both — crashing on import. Additionally, the Bookings tab headers are stale: format_sheets defines 13 columns, but `sheets_writer.log_hold_created()` writes 15 columns (booking_ref, trip_key, departure_time, total_price, payment_status were added in Brief 028).

## Why This Approach
The simplest fix: give format_sheets.py its own service initialization using google-api-python-client (already installed on VPS from Brief 013) instead of importing from sheets_writer, which no longer exposes those symbols. The Bookings headers are updated to match the exact column order written by `sheets_writer.log_hold_created()`. No other files are touched.

## Source Material

### sheets_writer.log_hold_created() column order (15 values):
```python
row_bookings = [
    _now(),                              # 0  Timestamp
    data.get('booking_ref', ''),         # 1  Booking Ref
    data.get('customer_name', ''),       # 2  Customer Name
    data.get('email', ''),               # 3  Email
    data.get('experience', ''),          # 4  Experience
    data.get('trip_key', ''),            # 5  Trip Key
    data.get('date', ''),                # 6  Date
    str(data.get('guests', '')),         # 7  Guests
    data.get('departure_time', ''),      # 8  Departure Time
    data.get('phone', ''),              # 9  Phone
    data.get('special_requests', ''),    # 10 Special Requests
    str(data.get('total_price', '')),    # 11 Total Price
    data.get('payment_status', ''),      # 12 Payment Status
    data.get('html_link', ''),           # 13 Event Link
    data.get('payment_link', ''),        # 14 Payment Link
]
```

### sheets_writer.log_escalation() column order (7 values):
```python
row_escalations = [
    _now(),                                       # 0  Timestamp
    data.get('customer_name', ''),                # 1  Customer Name
    data.get('email', ''),                        # 2  Email
    data.get('intent', ''),                       # 3  Intent
    json.dumps(data.get('fields_collected', {})), # 4  Fields Collected
    data.get('internal_note', ''),                # 5  Internal Note
    data.get('messages_json', ''),                # 6  Chat Log
]
```

### Current format_sheets.py imports (broken):
```python
from sheets_writer import KEY_PATH, SPREADSHEET_ID, _get_service
```
`KEY_PATH` still exists in sheets_writer. `SPREADSHEET_ID` and `_get_service` do not.

### Key file path (same as sheets_writer):
```python
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_PATH = os.path.normpath(os.path.join(_SRC_DIR, '..', 'config', 'bluemarlin-calendar-key.json'))
```

### Spreadsheet ID resolution (same as sheets_writer._get_spreadsheet_id):
```python
def _get_spreadsheet_id() -> str:
    try:
        sid = config_loader.get_business().get('spreadsheet_id', '')
        if sid:
            return sid
    except Exception:
        pass
    return os.environ.get('SPREADSHEET_ID', '')
```

## Instructions

### Step 1 — Replace broken import block
Replace lines 5–11 (from `# DEPENDS ON:` through `from sheets_writer import ...`) with:

```python
# DEPENDS ON: config/bluemarlin-calendar-key.json, config_loader.py
# RUN ONCE: python3 bluemarlin/src/format_sheets.py
# PURPOSE: Apply BlueMarlin color palette to Operations Dashboard
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_PATH = os.path.normpath(os.path.join(_SRC_DIR, '..', 'config', 'bluemarlin-calendar-key.json'))
_SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


def _get_spreadsheet_id() -> str:
    try:
        sid = config_loader.get_business().get('spreadsheet_id', '')
        if sid:
            return sid
    except Exception:
        pass
    return os.environ.get('SPREADSHEET_ID', '')


def _get_service():
    try:
        creds = Credentials.from_service_account_file(KEY_PATH, scopes=_SCOPES)
        return build('sheets', 'v4', credentials=creds)
    except Exception as e:
        print(f"format_sheets: service init error: {e}")
        return None
```

### Step 2 — Update BOOKINGS_HEADERS to match actual 15-column layout
Replace the existing BOOKINGS_HEADERS (13 items) with:

```python
BOOKINGS_HEADERS = [
    'Timestamp', 'Booking Ref', 'Customer Name', 'Email', 'Experience',
    'Trip Key', 'Date', 'Guests', 'Departure Time', 'Phone',
    'Special Requests', 'Total Price', 'Payment Status', 'Event Link',
    'Payment Link'
]
```

### Step 3 — Update BOOKINGS_WIDTHS to 15 values
Replace the existing BOOKINGS_WIDTHS (13 values) with:

```python
BOOKINGS_WIDTHS = [180, 130, 150, 220, 160, 140, 110, 80, 120, 130, 220, 100, 120, 220, 220]
```

### Step 4 — Update main() to use local _get_spreadsheet_id()
In `main()`, replace:
```python
meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
```
with:
```python
spreadsheet_id = _get_spreadsheet_id()
if not spreadsheet_id:
    print("format_sheets: no spreadsheet ID found — check client.json or SPREADSHEET_ID env")
    return
meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
```

And replace every other `SPREADSHEET_ID` reference in main() with `spreadsheet_id` (the local variable). There are 3 more occurrences:
- `service.spreadsheets().values().update(spreadsheetId=SPREADSHEET_ID, ...)`
- `service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, ...)`  (main formatting)
- `service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, ...)`  (row height)

### Step 5 — Update file header
Change `# LAST MODIFIED: Brief 040` to `# LAST MODIFIED: Brief 049`.

## Tests

```python
#!/usr/bin/env python3
"""Tests for Brief 049 — Fix format_sheets.py."""
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

print("Running Brief 049 tests...")

# T1: format_sheets imports cleanly (no crash)
try:
    import format_sheets
    check("T1: format_sheets imports without error", True)
except Exception as e:
    check(f"T1: format_sheets imports without error ({e})", False)

# T2: _get_spreadsheet_id returns the new sheet ID
sid = format_sheets._get_spreadsheet_id()
check("T2: spreadsheet ID is new sheet", sid == "1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I")

# T3: Old banned sheet ID not in source
with open(os.path.join(os.path.dirname(__file__), "..", "src", "format_sheets.py")) as f:
    source = f.read()
check("T3: old banned sheet ID not in source", "1soG3zVnx" not in source)

# T4: BOOKINGS_HEADERS has 15 columns
check("T4: BOOKINGS_HEADERS has 15 columns", len(format_sheets.BOOKINGS_HEADERS) == 15)

# T5: BOOKINGS_WIDTHS has 15 values
check("T5: BOOKINGS_WIDTHS has 15 values", len(format_sheets.BOOKINGS_WIDTHS) == 15)

# T6: Headers match actual sheets_writer column order
check("T6: col 0 is Timestamp", format_sheets.BOOKINGS_HEADERS[0] == "Timestamp")
check("T7: col 1 is Booking Ref", format_sheets.BOOKINGS_HEADERS[1] == "Booking Ref")
check("T8: col 5 is Trip Key", format_sheets.BOOKINGS_HEADERS[5] == "Trip Key")
check("T9: col 8 is Departure Time", format_sheets.BOOKINGS_HEADERS[8] == "Departure Time")
check("T10: col 11 is Total Price", format_sheets.BOOKINGS_HEADERS[11] == "Total Price")
check("T11: col 14 is Payment Link", format_sheets.BOOKINGS_HEADERS[14] == "Payment Link")

# T12: COMPLAINTS_HEADERS unchanged (6 columns)
check("T12: COMPLAINTS_HEADERS has 6 columns", len(format_sheets.COMPLAINTS_HEADERS) == 6)

# T13: ESCALATIONS_HEADERS unchanged (7 columns)
check("T13: ESCALATIONS_HEADERS has 7 columns", len(format_sheets.ESCALATIONS_HEADERS) == 7)

# T14: ALL_EVENTS_HEADERS unchanged (5 columns)
check("T14: ALL_EVENTS_HEADERS has 5 columns", len(format_sheets.ALL_EVENTS_HEADERS) == 5)

# T15: _get_service function exists
check("T15: _get_service is callable", callable(getattr(format_sheets, '_get_service', None)))

# T16: _get_spreadsheet_id function exists
check("T16: _get_spreadsheet_id is callable", callable(getattr(format_sheets, '_get_spreadsheet_id', None)))

# T17: No reference to sheets_writer in imports
check("T17: no sheets_writer import", "from sheets_writer" not in source and "import sheets_writer" not in source)

# T18: File header says Brief 049
check("T18: file header says Brief 049", "Brief 049" in source)

# T19: KEY_PATH defined locally
check("T19: KEY_PATH defined in format_sheets", hasattr(format_sheets, 'KEY_PATH'))

# T20: _build_requests still works (basic sanity)
reqs = format_sheets._build_requests(0, 'Bookings', format_sheets.BOOKINGS_WIDTHS)
check("T20: _build_requests returns list of requests", isinstance(reqs, list) and len(reqs) > 5)

print(f"\n{passed}/{passed+failed} tests passed.")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("All tests passed.")
```

## Success Condition
`format_sheets.py` imports cleanly, all 20 tests pass, and running `python3 bluemarlin/src/format_sheets.py` on VPS applies full formatting to the new dashboard.

## Rollback
Revert format_sheets.py to its previous state: `git checkout HEAD -- bluemarlin/src/format_sheets.py`
