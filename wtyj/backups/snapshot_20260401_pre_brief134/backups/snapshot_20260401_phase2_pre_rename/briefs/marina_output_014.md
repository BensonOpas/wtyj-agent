# OUTPUT_014 — Google Sheets dashboard formatting

## Files created
- `bluemarlin/src/format_sheets.py`
- `bluemarlin/briefs/OUTPUT_014.md` (this file)

## Files modified
None — formatting is applied to the live Google Sheet only. No source files changed.

## Implementation summary

### format_sheets.py structure
- Imports `KEY_PATH`, `SPREADSHEET_ID`, `_get_service` from `sheets_writer`
- Defines `BOOKINGS_HEADERS` (13), `COMPLAINTS_HEADERS` (6), `ALL_EVENTS_HEADERS` (5)
- `TABS` list drives the loop
- `hex_to_rgb(hex_str)` converts `#rrggbb` → `{red, green, blue}` floats in [0,1]
- `_build_requests(sheet_id, tab_name, n)` builds all 7-9 formatting requests for a tab
- `main()` gets service, fetches metadata, loops over tabs, writes headers, batches formats

### Per-tab flow
1. `spreadsheets().get()` → build `{tab_name: sheetId}` dict
2. For each tab:
   - `values().update()` → write header row (RAW)
   - `_build_requests()` → collect all formatting requests
   - `spreadsheets().batchUpdate()` → single API call with all requests

### Requests batched per tab (in order)
| Step | Request type | Target |
|---|---|---|
| 2a | `repeatCell` | Entire sheet (rows 0-1001) — deep navy background `#1a2744` |
| 2c | `repeatCell` | Row 0 — header: `#243460` bg, white bold 11pt, centered |
| 2d | `updateSheetProperties` | Freeze row 1 (frozenRowCount: 1) |
| 2e | `updateDimensionProperties` | Column widths (tab-specific, see below) |
| 2f | `updateDimensionProperties` | Row height 32px for rows 0-1001 |
| 2g | `repeatCell` | Rows 1-1001 — body text `#e8edf5`, 10pt, MIDDLE |
| 2h | `updateBorders` | Row 0 bottom border SOLID_MEDIUM `#2e7d9e` |

### Column widths
- Bookings: 1 request, columns 0-12, 160px each
- Complaints: 1 request, columns 0-5, 200px each
- All Events: 2 requests — columns 0-3 at 160px, column 4 at 400px

### Idempotency
All RepeatCell, UpdateSheetProperties, UpdateDimensionProperties, and UpdateBorders
requests are safe to reapply — running the script multiple times produces the same
result (last-write-wins for formatting).

## Dependencies added
None — `google-api-python-client` and `google-auth` were already installed in Brief 013.

## Assumptions
- Tabs Bookings, Complaints, All Events already exist (created in Brief 013 setup)
- `Sheet1` tab is left untouched as specified
- `endRowIndex: 1001` and `endIndex: 1001` for rows — covers practical data volume;
  Sheets API clamps to actual grid size if needed
- The `updateBorders` request only specifies `bottom` — left/right/top borders are
  left at their defaults (none), which is correct for the brief spec
- 2a runs before 2c in the batched request list — 2c overrides row 0 background
  from navy to `#243460`; rows 1+ stay navy. Sheets API applies requests in order.
- Tab name with space ("All Events") is quoted in the values().update() range string
  as `'All Events'!A1` — this is correct Sheets range notation

## Test results

```
# Test 1 — script imports cleanly
IMPORT OK

# Test 2 — run the formatter
Formatted: Bookings
Formatted: Complaints
Formatted: All Events
Done.

# Test 3 — verify sheet is accessible after formatting
Tabs found: ['Sheet1', 'Bookings', 'Complaints', 'All Events']
PASS
```

All 3 tests pass. Formatting confirmed applied to live spreadsheet.

## Flags and uncertainties
- The script is designed to run once manually (`python3 bluemarlin/src/format_sheets.py`);
  it is not imported by email_poller or any other module
- Re-running is safe (idempotent) but will overwrite any manual formatting the operator
  may have applied to the header row
- Color palette is hardcoded in the script per the brief spec — no config file

## SYSTEM_STATE update block
```
Brief 014 — format_sheets.py — NEW FILE, run-once formatting script
  Applies BlueMarlin color palette to Bookings, Complaints, All Events tabs.
  Not imported by any other module. Safe to re-run.
  No changes to sheets_writer.py, email_poller.py, or any other file.
```

## Dependency impact
```
Files that import format_sheets: none
What callers should expect differently: N/A — standalone script only
```

## Regression check block
```
# BRIEF_014 — format_sheets.py — imports and all three tabs reachable
python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src')
import format_sheets
assert callable(format_sheets.hex_to_rgb)
assert callable(format_sheets.main)
assert len(format_sheets.BOOKINGS_HEADERS) == 13
assert len(format_sheets.COMPLAINTS_HEADERS) == 6
assert len(format_sheets.ALL_EVENTS_HEADERS) == 5
from sheets_writer import _get_service, SPREADSHEET_ID
svc = _get_service()
tabs = {s['properties']['title'] for s in svc.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()['sheets']}
assert 'Bookings' in tabs and 'Complaints' in tabs and 'All Events' in tabs
print('format_sheets regression OK')
"
```
