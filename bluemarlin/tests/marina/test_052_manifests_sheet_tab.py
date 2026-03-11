#!/usr/bin/env python3
"""Tests for Brief 052 — Manifests sheet tab."""
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

print("Running Brief 052 tests...")

# ── sheets_writer.py ──
from agents.marina import sheets_writer
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
with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "sheets_writer.py")) as f:
    sw_src = f.read()
check("T4: sheets_writer header says Brief", "Last modified: Brief" in sw_src)

# T5: log_manifest_update appends to 'Manifests' tab
check("T5: 'Manifests' tab name in log_manifest_update", "'Manifests'" in sw_src)

# ── format_sheets.py ──
with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "format_sheets.py")) as f:
    fs_src = f.read()

# T6: MANIFESTS_HEADERS defined
check("T6: MANIFESTS_HEADERS defined", "MANIFESTS_HEADERS" in fs_src)

# T7: MANIFESTS_WIDTHS defined
check("T7: MANIFESTS_WIDTHS defined", "MANIFESTS_WIDTHS" in fs_src)

# T8: MANIFESTS_HEADERS has 11 columns
from agents.marina import format_sheets
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
check("T13: format_sheets header says Brief", "Last modified: Brief" in fs_src)

# T14: MANIFESTS_HEADERS first column is 'Timestamp'
check("T14: First header is 'Timestamp'", format_sheets.MANIFESTS_HEADERS[0] == "Timestamp")

# T15: MANIFESTS_HEADERS contains 'Revenue'
check("T15: Headers contain 'Revenue'", "Revenue" in format_sheets.MANIFESTS_HEADERS)

# T16: MANIFESTS_HEADERS contains 'Calendar Link'
check("T16: Headers contain 'Calendar Link'", "Calendar Link" in format_sheets.MANIFESTS_HEADERS)

# ── email_poller.py ──
with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "email_poller.py")) as f:
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
check("T20: email_poller header says Brief", "Last modified: Brief" in ep_src)

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
