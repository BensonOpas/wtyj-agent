# OUTPUT_015 — format_sheets.py — dashboard polish

## Files modified
- `bluemarlin/src/format_sheets.py`

## Files created
- `bluemarlin/briefs/OUTPUT_015.md` (this file)

## Changes made

### File header
- `LAST MODIFIED` updated from `Brief 014` to `Brief 015`

### Unchanged (per constraints)
- `BOOKINGS_HEADERS`, `COMPLAINTS_HEADERS`, `ALL_EVENTS_HEADERS`
- `hex_to_rgb()`
- Import block

### New constants added
```python
BOOKINGS_WIDTHS   = [180,150,200,180,110,80,130,250,110,200,200,200,250]
COMPLAINTS_WIDTHS = [180,200,200,300,110,250]
ALL_EVENTS_WIDTHS = [180,150,200,200,400]
```

### TABS updated
Added `'widths'` key to each tab dict; passed as `col_widths` to `_build_requests()`.

### `_build_requests()` — full replacement
New signature: `_build_requests(sheet_id, tab_name, col_widths, banded_range_ids=None, column_count=None)`
`n = len(col_widths)` derived internally.

| # | Request | Details |
|---|---|---|
| 1 | `repeatCell` (full sheet) | Background `#1a2030`, rows 0-1001, cols 0-n |
| 2 | `repeatCell` (header row) | `#2a3545` bg, white bold 11pt, CENTER, CLIP wrap |
| 3 | `updateSheetProperties` | `frozenRowCount: 1` |
| 4 | `updateDimensionProperties` × n | One request per column, individual pixel sizes |
| 5 | `updateDimensionProperties` (rows) | All rows 0-1001, pixelSize 40 |
| 6 | `repeatCell` (body rows 1-1001) | `#1e2530` bg, `#e8edf5` text 10pt, MIDDLE, WRAP |
| pre-7 | `deleteBanding` × existing | Deletes all existing bandedRangeIds before adding new one |
| 7 | `addBanding` | Rows 1-1001, header `#2a3545`, first `#1e2530`, second `#242f3d` |
| 8 | `updateBorders` (header bottom) | SOLID_MEDIUM `#3d8eb9` |
| 9 | `deleteDimension` (guard) | Only if `column_count > n`; removes excess columns |

All requests sent in a single `batchUpdate` call per tab.

### `main()` updates
- Fetches metadata once at start; extracts `sheetId`, `columnCount`, `bandedRanges` per sheet
- Passes `banded_range_ids` and `column_count` to `_build_requests()` for idempotency guards
- Adds **second** `batchUpdate` after the main one: sets data rows (1-1001) to `pixelSize: 80` (2-line max cap)

### Idempotency mechanisms
- Banding: existing `bandedRangeId`s fetched from metadata and deleted before `addBanding`
- Column deletion: `column_count > n` guard prevents 400 error when already trimmed
- All `RepeatCell`, `UpdateSheetProperties`, `UpdateDimensionProperties`, `UpdateBorders` requests are inherently idempotent (last-write-wins)
- Verified: second run produces identical output, no errors

## Dependencies added
None.

## Assumptions
- `Sheet1` tab is left untouched — it is not in `TABS`, so the loop skips it
- `column_count` from metadata is reliable immediately after the tab was trimmed
  in a previous run — confirmed by second-run idempotency test
- `endIndex: column_count` in `deleteDimension` (not 1000) is safer and precise
- `addBanding` `headerColor` (`#2a3545`) applies to the first row of the banded range
  (row 1, first data row) — this is per the brief spec; in practice it creates a
  subtle visual break at the first data row
- The 80px second batchUpdate overrides the 40px from Request 5 for data rows only;
  the header row (set to 40px in Request 5) is not affected by the second call
  (which starts at `startIndex: 1`)

## Test results

```
# Test 1 — imports cleanly
IMPORT OK

# Test 2 — run the formatter
Formatted: Bookings
Formatted: Complaints
Formatted: All Events
Done.

# Test 3 — verify column counts after deletion
Sheet1: 26 columns
Bookings: 13 columns
Complaints: 6 columns
All Events: 5 columns

# Idempotency — second run (additional verification)
Formatted: Bookings
Formatted: Complaints
Formatted: All Events
Done.
```

All 3 tests pass. Column counts exact. Idempotency confirmed.

## Flags and uncertainties
- `Sheet1` retains 26 columns — it is not managed by this script, which is correct
- The `deleteBanding` requests are prepended to the main batch (not a separate call),
  so deletion and re-addition happen atomically in one batchUpdate — no race window
- `addBanding` does not support `headerColor` being the same as `firstBandColor`
  in all API versions; if the Sheets API ignores it, banding still works correctly
  with just the two alternating colors

## SYSTEM_STATE update block
```
Brief 015 — format_sheets.py — _build_requests() replaced with 9-request version
  New color palette: #1a2030 sheet bg, #2a3545 header, alternating #1e2530/#242f3d bands
  Individual column widths per spec; row height 40px (header) / 80px (data rows)
  Text wrap WRAP on body rows; existing banding deleted before re-adding (idempotent)
  Extra columns deleted (guarded by columnCount check)
  No changes to sheets_writer.py, email_poller.py, or any other file.
```

## Dependency impact
```
Files that import format_sheets: none (standalone run-once script)
What callers should expect differently: N/A
```

## Regression check block
```
# BRIEF_015 — format_sheets.py — runs clean and trims columns correctly
python3 bluemarlin/src/format_sheets.py && python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src')
from sheets_writer import _get_service, SPREADSHEET_ID
svc = _get_service()
sheets = {s['properties']['title']: s['properties']['gridProperties']['columnCount']
          for s in svc.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()['sheets']}
assert sheets.get('Bookings') == 13, f'Bookings cols: {sheets.get(\"Bookings\")}'
assert sheets.get('Complaints') == 6, f'Complaints cols: {sheets.get(\"Complaints\")}'
assert sheets.get('All Events') == 5, f'All Events cols: {sheets.get(\"All Events\")}'
print('format_sheets Brief 015 regression OK')
"
```
