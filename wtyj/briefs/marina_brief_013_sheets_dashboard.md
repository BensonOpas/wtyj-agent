# BRIEF 013 — Google Sheets dashboard
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Create a Google Sheets writer module that appends rows to the
BlueMarlin Operations Dashboard spreadsheet every time a
structured log event is written. The sheet updates in real time
as events happen — no polling, no scheduled jobs.
## Context
Brief 012 added structured logging via bm_logger for 6 events:
  hold_created, hold_failed, booking_attempted,
  missing_fields_requested, complaint_received, off_topic_received
These events are written to bluemarlin/logs/bluemarlin.log as JSONL.
This brief creates a new module sheets_writer.py that appends
rows to the Google Sheet immediately when called.
email_poller.py is then updated to call sheets_writer after
each bm_logger.log() call.
The sheet has three tabs:
  Tab 1: Bookings — one row per hold_created or hold_failed event
  Tab 2: Complaints — one row per complaint_received event
  Tab 3: All Events — one row per any structured log event
## Credentials
Service account: bluemarlin-calendar@bluemarlin-ops.iam.gserviceaccount.com
Key file: /root/bluemarlin/config/bluemarlin-calendar-key.json
Spreadsheet ID: 1soG3zVnx-Y0WYWGJdgakXqpNeI6GAe6AD8DycOwwifE
Both Google Calendar API and Google Sheets API are enabled on
this service account.
## Files to create
bluemarlin/src/sheets_writer.py
## Files to modify
bluemarlin/src/email_poller.py
## Files to read before making any changes
Read bluemarlin/src/email_poller.py in full.
Read bluemarlin/src/bm_logger.py in full.
Read bluemarlin/src/claude_client.py for import pattern reference.
## Part 1 — Create sheets_writer.py
### Sheet structure
Tab name: Bookings
Columns in order:
  A: Timestamp
  B: Customer Name
  C: Email
  D: Experience
  E: Date
  F: Guests
  G: Phone
  H: Special Requests
  I: Hold Status (CREATED or FAILED)
  J: Event Link
  K: Payment Link
  L: Error (if failed)
  M: Operator Notes (blank — client fills this in)
Tab name: Complaints
Columns in order:
  A: Timestamp
  B: Email
  C: Subject
  D: Message Preview
  E: Status (NEW)
  F: Operator Notes (blank — client fills this in)
Tab name: All Events
Columns in order:
  A: Timestamp
  B: Event Type
  C: Email
  D: Subject
  E: Details (JSON string of remaining fields)
### sheets_writer.py implementation
File header:
  # FILE: sheets_writer.py
  # CREATED: Brief 013
  # LAST MODIFIED: Brief 013
  # DEPENDS ON: bluemarlin-calendar-key.json (config)
  # IMPORTS FROM: nothing
  # CALLERS: email_poller.py
Module-level setup:
- Import: os, json, datetime, googleapiclient.discovery,
  google.oauth2.service_account
- KEY_PATH constructed from __file__ same pattern as calendar.js
  but in Python:
  _SRC_DIR = os.path.dirname(os.path.abspath(__file__))
  KEY_PATH = os.path.normpath(os.path.join(_SRC_DIR, '..', 'config',
             'bluemarlin-calendar-key.json'))
- SPREADSHEET_ID = '1soG3zVnx-Y0WYWGJdgakXqpNeI6GAe6AD8DycOwwifE'
- SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
Helper function _get_service():
- Builds and returns authenticated Google Sheets service object
- Uses google.oauth2.service_account.Credentials.from_service_account_file()
- Builds with googleapiclient.discovery.build('sheets', 'v4', credentials=creds)
- Called fresh on every write — no module-level persistent connection
Helper function _append(service, tab_name, row):
- Appends a single row to the named tab
- Uses service.spreadsheets().values().append() with:
  spreadsheetId=SPREADSHEET_ID
  range=f"{tab_name}!A:A"
  valueInputOption="USER_ENTERED"
  insertDataOption="INSERT_ROWS"
  body={"values": [row]}
- Returns the API response
- Never raises — wraps in try/except, prints error and returns None
Helper function _now():
- Returns current timestamp as string: datetime.now(timezone.utc).isoformat()
Public functions — one per event type:
def log_hold_created(data: dict):
  Appends to Bookings tab and All Events tab.
  Bookings row:
    [_now(), data.get('customer_name',''), data.get('email',''),
     data.get('experience',''), data.get('date',''),
     str(data.get('guests','')), data.get('phone',''),
     data.get('special_requests',''), 'CREATED',
     data.get('html_link',''), data.get('payment_link',''), '', '']
  All Events row:
    [_now(), 'hold_created', data.get('email',''),
     data.get('subject',''), json.dumps(data)]
def log_hold_failed(data: dict):
  Appends to Bookings tab and All Events tab.
  Bookings row:
    [_now(), data.get('customer_name',''), data.get('email',''),
     data.get('experience',''), data.get('date',''),
     str(data.get('guests','')), '', '', 'FAILED', '', '',
     data.get('error',''), '']
  All Events row:
    [_now(), 'hold_failed', data.get('email',''),
     data.get('subject',''), json.dumps(data)]
def log_complaint(data: dict):
  Appends to Complaints tab and All Events tab.
  Complaints row:
    [_now(), data.get('email',''), data.get('subject',''),
     data.get('body_snippet',''), 'NEW', '']
  All Events row:
    [_now(), 'complaint_received', data.get('email',''),
     data.get('subject',''), json.dumps(data)]
def log_event(event_type: str, data: dict):
  Generic logger — appends to All Events tab only.
  All Events row:
    [_now(), event_type, data.get('email',''),
     data.get('subject',''), json.dumps(data)]
All public functions:
- Never raise exceptions — wrap everything in try/except
- Print errors to stdout for journald capture
- Return None on failure, API response on success
### Package requirement
google-api-python-client and google-auth must be installed.
Install with:
  pip install google-api-python-client google-auth --break-system-packages
## Part 2 — Update email_poller.py
Add import at top of email_poller.py after existing imports:
  import sheets_writer
Then add sheets_writer calls immediately after each bm_logger.log() call:
After bm_logger.log("hold_created", ...):
  sheets_writer.log_hold_created({
      "email": from_email,
      "subject": subj,
      "customer_name": fields_now.get("customer_name"),
      "experience": fields_now.get("experience"),
      "date": fields_now.get("date"),
      "guests": fields_now.get("guests"),
      "phone": fields_now.get("phone"),
      "special_requests": fields_now.get("special_requests"),
      "html_link": th["flags"].get("event_link"),
      "payment_link": th["flags"].get("payment_link"),
  })
After bm_logger.log("hold_failed", ...):
  sheets_writer.log_hold_failed({
      "email": from_email,
      "subject": subj,
      "experience": fields_now.get("experience"),
      "date": fields_now.get("date"),
      "guests": fields_now.get("guests"),
      "error": res.get("error"),
  })
After bm_logger.log("complaint_received", ...):
  sheets_writer.log_complaint({
      "email": from_email,
      "subject": subj,
      "body_snippet": body[:200],
  })
After bm_logger.log("off_topic_received", ...):
  sheets_writer.log_event("off_topic_received", {
      "email": from_email,
      "subject": subj,
  })
After bm_logger.log("missing_fields_requested", ...):
  sheets_writer.log_event("missing_fields_requested", {
      "email": from_email,
      "subject": subj,
      "missing": missing,
  })
After bm_logger.log("booking_attempted", ...):
  sheets_writer.log_event("booking_attempted", {
      "email": from_email,
      "subject": subj,
      "experience": fields_now.get("experience"),
      "date": fields_now.get("date"),
  })
Update email_poller.py file header:
  # LAST MODIFIED: Brief 013
## Tab setup requirement
Before running tests, verify the three tabs exist in the spreadsheet.
If they do not exist, create them using the Sheets API:
  sheets.spreadsheets.batchUpdate with addSheet requests for
  Bookings, Complaints, All Events.
Only create tabs that don't already exist.
Do not delete or modify existing tabs.
## Constraints
- sheets_writer.py must never crash email_poller.py —
  all exceptions caught and printed, never re-raised
- Never store credentials in source code
- KEY_PATH must resolve from __file__ not working directory
- Do not change any existing logic in email_poller.py
- Do not change bm_logger.py
- Do not change any reply messages
## Test commands
Install packages first:
  pip install google-api-python-client google-auth --break-system-packages
# Test 1 — sheets_writer imports cleanly
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import sheets_writer
print('IMPORT OK')
"
# Test 2 — can authenticate with Google Sheets API
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import sheets_writer
svc = sheets_writer._get_service()
assert svc is not None, 'FAIL: _get_service() returned None — check credentials and Sheets API enablement'
print('AUTH OK:', type(svc).__name__)
"
# Test 3 — log_event writes to All Events tab
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import sheets_writer
result = sheets_writer.log_event('test_event', {
    'email': 'test@example.com',
    'subject': 'Brief 013 test',
    'detail': 'automated test row'
})
print('Result:', result)
print('PASS — row written to All Events')
"
# Test 4 — log_hold_created writes to Bookings tab
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import sheets_writer
result = sheets_writer.log_hold_created({
    'email': 'test@example.com',
    'subject': 'Test booking',
    'customer_name': 'Test Customer',
    'experience': 'sunset_signature_cruise',
    'date': '2026-03-20',
    'guests': 2,
    'phone': '+5999000000',
    'special_requests': 'Test special request',
    'html_link': 'https://example.com/event',
    'payment_link': 'https://example.com/pay',
})
print('Result:', result)
print('PASS — row written to Bookings tab')
"
# Test 5 — log_complaint writes to Complaints tab
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import sheets_writer
result = sheets_writer.log_complaint({
    'email': 'test@example.com',
    'subject': 'Test complaint',
    'body_snippet': 'This is a test complaint message for Brief 013',
})
print('Result:', result)
print('PASS — row written to Complaints tab')
"
# Test 6 — email_poller imports cleanly with sheets_writer
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
print('IMPORT OK')
"
# Test 7 — sheets_writer import present in email_poller
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
assert 'import sheets_writer' in content, 'FAIL: sheets_writer not imported'
assert 'sheets_writer.log_hold_created' in content, 'FAIL: log_hold_created not called'
assert 'sheets_writer.log_complaint' in content, 'FAIL: log_complaint not called'
print('PASS — sheets_writer integrated into email_poller')
"
## Definition of done
- [ ] sheets_writer.py created in bluemarlin/src/
- [ ] File header present
- [ ] KEY_PATH resolves from __file__
- [ ] SPREADSHEET_ID hardcoded as constant
- [ ] Three tabs exist in spreadsheet: Bookings, Complaints, All Events
- [ ] All 4 public functions implemented and never raise
- [ ] email_poller.py updated with import and 6 call sites
- [ ] email_poller.py file header updated (Brief 013)
- [ ] google-api-python-client and google-auth installed on VPS
- [ ] All 7 tests pass with exact output and real rows visible in sheet
- [ ] OUTPUT_013.md written to bluemarlin/briefs/
- [ ] OUTPUT_013.md includes SYSTEM_STATE update block
- [ ] OUTPUT_013.md includes dependency impact block
- [ ] OUTPUT_013.md includes regression check block
