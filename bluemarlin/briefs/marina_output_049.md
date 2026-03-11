# OUTPUT 049 — Fix format_sheets.py + apply formatting to new dashboard

## What was done

### Step 1 — Replaced broken import block
Removed `from sheets_writer import KEY_PATH, SPREADSHEET_ID, _get_service`. Added local imports of `google.oauth2.service_account.Credentials` and `googleapiclient.discovery.build`. Added local `KEY_PATH`, `_SCOPES`, `_get_spreadsheet_id()` (mirrors sheets_writer logic via config_loader), and `_get_service()` (builds Sheets v4 service from service account key).

### Step 2 — Updated BOOKINGS_HEADERS to 15 columns
Replaced stale 13-column headers with the actual column order from `sheets_writer.log_hold_created()`:
Timestamp, Booking Ref, Customer Name, Email, Experience, Trip Key, Date, Guests, Departure Time, Phone, Special Requests, Total Price, Payment Status, Event Link, Payment Link.

### Step 3 — Updated BOOKINGS_WIDTHS to 15 values
`[180, 130, 150, 220, 160, 140, 110, 80, 120, 130, 220, 100, 120, 220, 220]`

### Step 4 — Updated main() to use local _get_spreadsheet_id()
Replaced all 4 `SPREADSHEET_ID` references in main() with local `spreadsheet_id` variable from `_get_spreadsheet_id()`. Added guard for missing spreadsheet ID.

### Step 5 — Updated file header
`# LAST MODIFIED: Brief 049`

## Test results

```
Running Brief 049 tests...
  T1: format_sheets imports without error PASS
  T2: spreadsheet ID is new sheet PASS
  T3: old banned sheet ID not in source PASS
  T4: BOOKINGS_HEADERS has 15 columns PASS
  T5: BOOKINGS_WIDTHS has 15 values PASS
  T6: col 0 is Timestamp PASS
  T7: col 1 is Booking Ref PASS
  T8: col 5 is Trip Key PASS
  T9: col 8 is Departure Time PASS
  T10: col 11 is Total Price PASS
  T11: col 14 is Payment Link PASS
  T12: COMPLAINTS_HEADERS has 6 columns PASS
  T13: ESCALATIONS_HEADERS has 7 columns PASS
  T14: ALL_EVENTS_HEADERS has 5 columns PASS
  T15: _get_service is callable PASS
  T16: _get_spreadsheet_id is callable PASS
  T17: no sheets_writer import PASS
  T18: file header says Brief 049 PASS
  T19: KEY_PATH defined in format_sheets PASS
  T20: _build_requests returns list of requests PASS

20/20 tests passed.
All tests passed.
```

## Unexpected
Nothing unexpected. Straightforward fix — broken imports replaced with local initialization, stale headers updated to match actual data.
