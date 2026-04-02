# BRIEF 014 — Google Sheets dashboard formatting
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Apply professional formatting to the BlueMarlin Operations Dashboard
spreadsheet. This runs once as a setup script. It does not change
any data — only visual formatting.
## Context
sheets_writer.py writes data to three tabs:
  Bookings — 13 columns
  Complaints — 6 columns
  All Events — 5 columns
Currently the sheet has no formatting — raw data in default cells.
This brief adds a formatting script that applies the BlueMarlin
color palette once and leaves the sheet looking professional.
## File to create
bluemarlin/src/format_sheets.py
## File to read before making any changes
Read bluemarlin/src/sheets_writer.py in full — use the same
_get_service() pattern, KEY_PATH, and SPREADSHEET_ID.
## Color palette
Deep navy background:     #1a2744
Header row background:    #243460
Header text:              #ffffff (bold)
Odd rows background:      #1e2d4a
Even rows background:     #243460
Body text:                #e8edf5
Border/accent:            #2e7d9e
CREATED status bg:        #1b4332  text: #2d6a4f
FAILED status bg:         #370617  text: #c1121f
NEW status bg:            #3d2b00  text: #e9c46a
## Helper: hex_to_rgb(hex_str)
Convert #rrggbb to {red: r, green: g, blue: b} with values 0-1.
Used for all color values in the Sheets API.
## Tab definitions
Define these as constants:
BOOKINGS_HEADERS = [
    'Timestamp', 'Customer Name', 'Email', 'Experience',
    'Date', 'Guests', 'Phone', 'Special Requests',
    'Hold Status', 'Event Link', 'Payment Link', 'Error',
    'Operator Notes'
]
COMPLAINTS_HEADERS = [
    'Timestamp', 'Email', 'Subject', 'Message Preview',
    'Status', 'Operator Notes'
]
ALL_EVENTS_HEADERS = [
    'Timestamp', 'Event Type', 'Email', 'Subject', 'Details'
]
TABS = [
    {'name': 'Bookings',   'headers': BOOKINGS_HEADERS},
    {'name': 'Complaints', 'headers': COMPLAINTS_HEADERS},
    {'name': 'All Events', 'headers': ALL_EVENTS_HEADERS},
]
## Implementation
### Step 1 — get sheet metadata
Call spreadsheets().get() to retrieve sheetId for each tab by name.
Build a dict: tab_name -> sheetId.
All batchUpdate requests require sheetId not tab name.
### Step 2 — for each tab apply these formats via batchUpdate
#### 2a — set tab background color
RepeatCellRequest on entire sheet range (all rows, all cols):
  background: deep navy #1a2744
#### 2b — write header row
Use values().update() to write header labels to row 1.
valueInputOption: RAW
#### 2c — format header row
RepeatCellRequest on row 0 (first row):
  background: #243460
  text: #ffffff, bold: true, fontSize: 11
  verticalAlignment: MIDDLE
  horizontalAlignment: CENTER
#### 2d — freeze header row
UpdateSheetPropertiesRequest:
  gridProperties.frozenRowCount: 1
#### 2e — set column widths
UpdateDimensionPropertiesRequest per tab:
  Bookings: all 13 columns set to pixelSize 160
  Complaints: all 6 columns set to pixelSize 200
  All Events: columns 0-3 set to 160, column 4 (Details) set to 400
#### 2f — set row height for all rows
UpdateDimensionPropertiesRequest:
  All rows: pixelSize 32
#### 2g — set body text color for all rows below header
RepeatCellRequest on rows 1 to 1000:
  text color: #e8edf5
  fontSize: 10
  verticalAlignment: MIDDLE
#### 2h — set border on header row bottom
UpdateBordersRequest on row 0:
  bottom border: style SOLID_MEDIUM, color #2e7d9e
### Step 3 — execute all requests
Collect all requests into a single batchUpdate call per tab.
Do not make one API call per format — batch everything.
### Step 4 — print confirmation
Print one line per tab: "Formatted: {tab_name}"
Print "Done." when complete.
## File header
  # FILE: format_sheets.py
  # CREATED: Brief 014
  # LAST MODIFIED: Brief 014
  # DEPENDS ON: sheets_writer.py (KEY_PATH, SPREADSHEET_ID, _get_service)
  # RUN ONCE: python3 bluemarlin/src/format_sheets.py
  # PURPOSE: Apply BlueMarlin color palette to Operations Dashboard
## Import pattern
Import KEY_PATH, SPREADSHEET_ID, _get_service from sheets_writer:
  import sys, os
  sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
  from sheets_writer import KEY_PATH, SPREADSHEET_ID, _get_service
## Constraints
- This script runs once manually — it is NOT imported by email_poller
- Do not modify sheets_writer.py
- Do not modify email_poller.py
- Do not touch any other file
- All API calls wrapped in try/except
- Script must be safe to run multiple times — formatting is idempotent
## Test commands
# Test 1 — script imports cleanly
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
# Test 3 — verify sheet is accessible after formatting
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
from sheets_writer import _get_service, SPREADSHEET_ID
svc = _get_service()
result = svc.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
tabs = [s['properties']['title'] for s in result['sheets']]
print('Tabs found:', tabs)
assert 'Bookings' in tabs, 'FAIL: Bookings tab missing'
assert 'Complaints' in tabs, 'FAIL: Complaints tab missing'
assert 'All Events' in tabs, 'FAIL: All Events tab missing'
print('PASS')
"
## Definition of done
- [ ] format_sheets.py created in bluemarlin/src/
- [ ] File header present
- [ ] hex_to_rgb() helper implemented
- [ ] All three tabs formatted
- [ ] Header rows written with correct column names
- [ ] Header rows formatted: dark background, white bold text
- [ ] Header rows frozen
- [ ] Column widths set per tab
- [ ] Row height 32px
- [ ] Body text color set
- [ ] Bottom border on header row
- [ ] All requests batched — not one call per format
- [ ] Test 1 passes
- [ ] Test 2 runs and prints expected output
- [ ] Test 3 passes
- [ ] OUTPUT_014.md written to bluemarlin/briefs/
- [ ] OUTPUT_014.md includes SYSTEM_STATE update block
