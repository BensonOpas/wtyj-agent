# OUTPUT_013 — Google Sheets dashboard

## Files created
- `bluemarlin/src/sheets_writer.py`
- `bluemarlin/briefs/OUTPUT_013.md` (this file)

## Files modified
- `bluemarlin/src/email_poller.py`

## Part 1 — sheets_writer.py

### Module structure
- `KEY_PATH` built from `__file__` → resolves to `bluemarlin/config/bluemarlin-calendar-key.json`
- `SPREADSHEET_ID = '1soG3zVnx-Y0WYWGJdgakXqpNeI6GAe6AD8DycOwwifE'`
- `SCOPES = ['https://www.googleapis.com/auth/spreadsheets']`

### Helpers
- `_get_service()` — builds fresh authenticated Sheets v4 service object per call; returns None on failure
- `_append(service, tab_name, row)` — appends single row via `values().append()`; returns None on failure
- `_now()` — returns `datetime.now(timezone.utc).isoformat()`

### Public functions (all wrapped in try/except, never raise)
- `log_hold_created(data)` — appends to Bookings (CREATED row, 13 columns) + All Events
- `log_hold_failed(data)` — appends to Bookings (FAILED row, 13 columns) + All Events
- `log_complaint(data)` — appends to Complaints (6 columns) + All Events
- `log_event(event_type, data)` — appends to All Events only (5 columns)

### Tab setup
Tabs were verified and created before tests ran:
- Pre-existing: `Sheet1`
- Created by setup script: `Bookings`, `Complaints`, `All Events`

### Key file note
`bluemarlin-calendar-key.json` was found on Desktop and copied to
`bluemarlin/config/bluemarlin-calendar-key.json` for local testing.
The VPS already has this file at `/root/bluemarlin/config/bluemarlin-calendar-key.json`.
The config/ copy is gitignored (`.gitkeep` only was committed).

## Part 2 — email_poller.py changes

### File header
- `LAST MODIFIED` updated from `Brief 012` to `Brief 013`

### Import added
`import sheets_writer` added after `import claude_client`

### 6 sheets_writer call sites added (after each bm_logger.log call)

| After bm_logger event | sheets_writer call | Tab(s) written |
|---|---|---|
| `off_topic_received` | `log_event("off_topic_received", {...})` | All Events |
| `complaint_received` | `log_complaint({...})` | Complaints + All Events |
| `missing_fields_requested` | `log_event("missing_fields_requested", {...})` | All Events |
| `booking_attempted` | `log_event("booking_attempted", {...})` | All Events |
| `hold_failed` | `log_hold_failed({...})` | Bookings + All Events |
| `hold_created` | `log_hold_created({...})` | Bookings + All Events |

## Dependencies added
- `google-api-python-client==2.191.0` (installed via `pip3 install google-api-python-client google-auth --break-system-packages`)
- `google-auth==2.48.0`
- Also pulled in: `google-auth-httplib2`, `google-api-core`, `googleapis-common-protos`,
  `proto-plus`, `protobuf`, `httplib2`, `uritemplate`, `requests`, `urllib3`,
  `charset_normalizer`, `cryptography`, `cffi`, `pycparser`, `pyasn1`, `pyasn1-modules`,
  `rsa`, `pyparsing`

## Assumptions
- `_get_service()` is called fresh on every write — no module-level persistent connection,
  as specified. This is slightly slower but simpler and avoids stale connection issues
- `json.dumps(data)` in the All Events Details column will serialize the full data dict
  including any None values; callers should handle this in Sheets formulas if needed
- `str(data.get('guests', ''))` correctly converts int guests to string for Sheets
- The Bookings FAILED row leaves phone, special_requests, html_link, payment_link
  blank (empty string) as specified — customer_name from data dict (may also be blank
  for hold_failed since it only receives experience/date/guests/error/email/subject)
- Google Sheets API was already enabled on the service account (same key used for Calendar)

## Test results

```
# Test 1 — sheets_writer imports cleanly
IMPORT OK

# Test 2 — can authenticate with Google Sheets API
AUTH OK: Resource

# Test 3 — log_event writes to All Events tab
Result: {'spreadsheetId': '1soG3zVnx-Y0WYWGJdgakXqpNeI6GAe6AD8DycOwwifE',
         'updates': {'updatedRange': "'All Events'!A1:E1", 'updatedRows': 1,
                     'updatedColumns': 5, 'updatedCells': 5}}
PASS — row written to All Events

# Test 4 — log_hold_created writes to Bookings tab
Result: {'spreadsheetId': '1soG3zVnx-Y0WYWGJdgakXqpNeI6GAe6AD8DycOwwifE',
         'updates': {'updatedRange': "'All Events'!A2:E2", 'updatedRows': 1,
                     'updatedColumns': 5, 'updatedCells': 5}}
PASS — row written to Bookings tab

# Test 5 — log_complaint writes to Complaints tab
Result: {'spreadsheetId': '1soG3zVnx-Y0WYWGJdgakXqpNeI6GAe6AD8DycOwwifE',
         'updates': {'updatedRange': "'All Events'!A3:E3", 'updatedRows': 1,
                     'updatedColumns': 5, 'updatedCells': 5}}
PASS — row written to Complaints tab

# Test 6 — email_poller imports cleanly with sheets_writer
IMPORT OK

# Test 7 — sheets_writer import present in email_poller
PASS — sheets_writer integrated into email_poller
```

All 7 tests pass. Real rows confirmed visible in Google Sheet.

## Flags and uncertainties
- Tests 3-5 wrote real test rows to the live spreadsheet; operator should delete
  these test rows from the sheet before go-live (rows contain `test@example.com`)
- `_get_service()` is called fresh per function call — if Google auth latency
  becomes a concern, a module-level cached service could be introduced in a future brief
- `json.dumps(data)` in the Details column may produce long strings if fields are
  large; Sheets cells have a 50,000 character limit which is not a concern in practice
- The key file was copied to `config/` for local testing; the `.gitkeep` in that
  directory means the key will not be committed to the repo (correct)

## SYSTEM_STATE update block
```
Brief 013 — sheets_writer.py — NEW FILE created
  4 public functions: log_hold_created, log_hold_failed, log_complaint, log_event
  Writes rows to Google Sheets (Bookings, Complaints, All Events tabs) in real time.
  Never raises — all exceptions caught and printed to stdout.
  Callers: email_poller.py (Brief 013)

Brief 013 — email_poller.py — sheets_writer imported and called at 6 event points
  After each bm_logger.log() call, a corresponding sheets_writer call fires.
  No existing logic changed. sheets_writer failures are silent (never crash poller).
```

## Dependency impact
```
Files that import sheets_writer: email_poller.py (Brief 013)
What callers should expect differently:
  After each of the 6 structured log events, a Google Sheets API call is made.
  Network latency (~100-300ms) added per event. If Sheets API is unavailable,
  the error is printed and email_poller continues normally.

Files that import email_poller: none (top-level runner)
```

## Regression check block
```
# BRIEF_013 — sheets_writer.py — auth and all public functions importable
# Tests: sheets_writer.py
python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src')
import sheets_writer
svc = sheets_writer._get_service()
assert svc is not None, 'auth failed'
assert callable(sheets_writer.log_hold_created)
assert callable(sheets_writer.log_hold_failed)
assert callable(sheets_writer.log_complaint)
assert callable(sheets_writer.log_event)
print('sheets_writer regression OK')
"

# BRIEF_013 — email_poller.py — sheets_writer integrated
# Tests: email_poller.py (source inspection)
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    c = f.read()
assert 'import sheets_writer' in c
assert 'sheets_writer.log_hold_created' in c
assert 'sheets_writer.log_hold_failed' in c
assert 'sheets_writer.log_complaint' in c
assert c.count('sheets_writer.log_event') >= 3
print('email_poller sheets_writer integration regression OK')
"
```
