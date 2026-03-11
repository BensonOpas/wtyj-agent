#!/usr/bin/env python3
"""Tests for Brief 049 — Fix format_sheets.py."""
import sys, os

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
    from agents.marina import format_sheets
    check("T1: format_sheets imports without error", True)
except Exception as e:
    check(f"T1: format_sheets imports without error ({e})", False)

# T2: _get_spreadsheet_id returns the new sheet ID
sid = format_sheets._get_spreadsheet_id()
check("T2: spreadsheet ID is new sheet", sid == "1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I")

# T3: Old banned sheet ID not in source
with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "format_sheets.py")) as f:
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
check("T18: file header says Brief", "Last modified: Brief" in source)

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
