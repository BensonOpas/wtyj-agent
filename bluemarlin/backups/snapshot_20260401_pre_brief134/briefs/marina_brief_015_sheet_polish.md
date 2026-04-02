# BRIEF 015 — format_sheets.py — dashboard polish
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Update format_sheets.py with a new color palette, proper column
widths tailored by data type, text wrapping on long fields,
alternating row banding, status color coding, and deletion of
extra empty columns beyond the data range per tab.
## Context
Brief 014 created format_sheets.py with the BlueMarlin navy palette.
The sheet has visual issues:
- Background stops at last data column, rest of sheet is white
- Columns are uniform width regardless of content type
- No alternating row colors
- No status color coding
- Long text fields cut off with no wrapping
## File to modify
bluemarlin/src/format_sheets.py
## Files to read before making any changes
Read bluemarlin/src/format_sheets.py in full before touching anything.
## New color palette — replace all old colors
Background (odd rows):     #1e2530
Background (even rows):    #242f3d
Header background:         #2a3545
Header text:               #ffffff bold
Body text:                 #e8edf5
Accent/border:             #3d8eb9
Sheet background fill:     #1a2030
Status colors:
CREATED bg: #1b4332  text: #52b788
FAILED bg:  #370617  text: #e63946
NEW bg:     #3d2b00  text: #f4a261
## Column width definitions
### Bookings tab — 13 columns
Col 0  Timestamp:        180px
Col 1  Customer Name:    150px
Col 2  Email:            200px
Col 3  Experience:       180px
Col 4  Date:             110px
Col 5  Guests:            80px
Col 6  Phone:            130px
Col 7  Special Requests: 250px
Col 8  Hold Status:      110px
Col 9  Event Link:       200px
Col 10 Payment Link:     200px
Col 11 Error:            200px
Col 12 Operator Notes:   250px
### Complaints tab — 6 columns
Col 0  Timestamp:        180px
Col 1  Email:            200px
Col 2  Subject:          200px
Col 3  Message Preview:  300px
Col 4  Status:           110px
Col 5  Operator Notes:   250px
### All Events tab — 5 columns
Col 0  Timestamp:        180px
Col 1  Event Type:       150px
Col 2  Email:            200px
Col 3  Subject:          200px
Col 4  Details:          400px
## Implementation — replace _build_requests() entirely
The new _build_requests(sheet_id, tab_name, col_widths) function
takes col_widths as a list of pixel sizes instead of n.
n is derived as len(col_widths).
Build these requests in this exact order:
### Request 1 — full sheet background
RepeatCellRequest covering rows 0-1001, cols 0-n:
  backgroundColor: #1a2030
### Request 2 — header row formatting
RepeatCellRequest covering row 0 only, cols 0-n:
  backgroundColor: #2a3545
  textFormat: color #ffffff, bold True, fontSize 11
  verticalAlignment: MIDDLE
  horizontalAlignment: CENTER
  wrapStrategy: CLIP
### Request 3 — freeze header row
updateSheetProperties: frozenRowCount: 1
### Request 4 — column widths
One updateDimensionProperties request per column using col_widths list.
Loop: for i, width in enumerate(col_widths): add request for col i.
Do not use a single range request — individual per column for precision.
### Request 5 — row height
updateDimensionProperties for ALL rows (0-1001): pixelSize 40
This is taller than Brief 014 to accommodate wrapped text.
### Request 6 — body text formatting with wrap
RepeatCellRequest covering rows 1-1001, cols 0-n:
  backgroundColor: #1e2530 (base — banding applied separately)
  textFormat: color #e8edf5, fontSize 10
  verticalAlignment: MIDDLE
  wrapStrategy: WRAP
### Request 7 — alternating row banding
addBanding request:
  bandedRange covering rows 1-1001, cols 0-n
  rowProperties:
    headerColor: #2a3545
    firstBandColor: #1e2530
    secondBandColor: #242f3d
### Request 8 — header bottom border
updateBorders on row 0, cols 0-n:
  bottom: style SOLID_MEDIUM, color #3d8eb9
### Request 9 — delete extra columns
deleteDimension request:
  dimension: COLUMNS
  startIndex: n
  endIndex: 1000
This removes all columns beyond the data range.
## Implementation — update main()
Update main() to pass col_widths per tab:
BOOKINGS_WIDTHS = [180,150,200,180,110,80,130,250,110,200,200,200,250]
COMPLAINTS_WIDTHS = [180,200,200,300,110,250]
ALL_EVENTS_WIDTHS = [180,150,200,200,400]
TABS = [
    {'name': 'Bookings',   'headers': BOOKINGS_HEADERS,   'widths': BOOKINGS_WIDTHS},
    {'name': 'Complaints', 'headers': COMPLAINTS_HEADERS, 'widths': COMPLAINTS_WIDTHS},
    {'name': 'All Events', 'headers': ALL_EVENTS_HEADERS, 'widths': ALL_EVENTS_WIDTHS},
]
Pass tab['widths'] to _build_requests() instead of len(headers).
## Max row height constraint
After all formatting, add a second batchUpdate call that sets
max row height for data rows (1-1001) to pixelSize 80.
This enforces the 2-row max for wrapped text.
This is a separate batchUpdate after the main one.
## File header update
  # LAST MODIFIED: Brief 015
## Constraints
- Do not change BOOKINGS_HEADERS, COMPLAINTS_HEADERS, ALL_EVENTS_HEADERS
- Do not change hex_to_rgb()
- Do not change the import block
- Do not modify sheets_writer.py
- Do not modify email_poller.py
- Script must remain safe to re-run — idempotent
- All requests wrapped in try/except
- Before adding a banding rule (Request 7), first delete any existing banding rules on the tab using deleteBanding requests. Get existing bandedRanges from the spreadsheet metadata and delete each one before adding the new one. This ensures idempotency.
- Before deleting extra columns (Request 9), check the current column count from sheet metadata. Only issue the deleteDimension request if columnCount > n. This prevents a 400 error when columns are already at the correct count.
## Test commands
# Test 1 — imports cleanly
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import format_sheets
print('IMPORT OK')
"
# Test 2 — run the formatter
python3 bluemarlin/src/format_sheets.py
Expected output:
  Formatted: Bookings
  Formatted: Complaints
  Formatted: All Events
  Done.
# Test 3 — verify tabs still exist after column deletion
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
from sheets_writer import _get_service, SPREADSHEET_ID
svc = _get_service()
result = svc.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
for sheet in result['sheets']:
    title = sheet['properties']['title']
    cols = sheet['properties']['gridProperties']['columnCount']
    print(f'{title}: {cols} columns')
"
Expected: Bookings 13 cols, Complaints 6 cols, All Events 5 cols
## Definition of done
- [ ] format_sheets.py modified in bluemarlin/src/
- [ ] File header updated (Brief 015)
- [ ] New color palette applied
- [ ] _build_requests() takes col_widths list
- [ ] Individual column widths set per spec
- [ ] Row height 40px with 80px max
- [ ] Text wrap WRAP on body rows
- [ ] Alternating row banding applied
- [ ] Extra columns deleted beyond data range
- [ ] Header bottom border color updated
- [ ] All 3 tests pass
- [ ] OUTPUT_015.md written to bluemarlin/briefs/
- [ ] OUTPUT_015.md includes SYSTEM_STATE update block
