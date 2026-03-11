# OUTPUT_032 — gws Migration: Replace calendar.js and sheets_writer.py

## Files modified
- `bluemarlin/src/email_poller.py`
- `bluemarlin/src/sheets_writer.py`

## Files created
- `bluemarlin/src/gws_calendar.py`
- `bluemarlin/briefs/OUTPUT_032.md` (this file)

## Files deleted
- `bluemarlin/src/calendar.js`

---

## Research findings

gws CLI package: `@googleworkspace/cli` (not `@googleworkspace/gws-cli`)
Auth env var: `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` (points to service account JSON)
Flag syntax confirmed:
- `--params '{"key":"value"}'` for query parameters
- `--json '{"key":"value"}'` for request body
Commands used:
- `gws calendar events list --params '{"calendarId":"...","timeMin":"...","timeMax":"...","singleEvents":true,"orderBy":"startTime","maxResults":5}'`
- `gws calendar events insert --params '{"calendarId":"..."}' --json '{event object}'`
- `gws sheets spreadsheets values append --params '{"spreadsheetId":"...","range":"Tab!A:A","valueInputOption":"USER_ENTERED","insertDataOption":"INSERT_ROWS"}' --json '{"values":[row]}'`

---

## Changes made

### gws_calendar.py (new)

- CALENDARS and DURATIONS_HOURS dicts copied verbatim from calendar.js
- _CURACAO_TZ = timezone(timedelta(hours=-4)) — same UTC-4 offset as calendar.js
- `_curacao_to_iso(date_str, time_str)` — converts Curaçao datetime to UTC ISO 8601
- `_run_gws(args)` — subprocess helper; sets GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE env var;
  returns parsed JSON dict or {'error': str}
- `check_availability(trip_key, date, start_time)` — gws calendar events list; returns
  {available: bool, reason?, error?}
- `create_hold(fields_now)` — gws calendar events insert; returns {ok: bool, eventId?, htmlLink?, error?};
  departure_time → departures[0] → "09:00" fallback (same as old calendar.js)

### sheets_writer.py (internals rewritten)

- Removed: googleapiclient, google.oauth2, _get_service(), SCOPES
- Added: subprocess, config_loader import
- `_get_spreadsheet_id()` — tries config_loader.get_business()["spreadsheet_id"],
  then SPREADSHEET_ID env var, then hardcoded fallback
- `_append(tab_name, row)` — gws sheets spreadsheets values append subprocess call;
  sets GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE env var
- Public function signatures (log_hold_created, log_hold_failed, log_escalation, log_event)
  and all row structures unchanged from Brief 028

### email_poller.py (call sites only)

- Header: LAST MODIFIED Brief 031 → Brief 032; DEPENDS ON calendar.js → gws_calendar.py
- Removed `subprocess` from compound import line
- Added `import gws_calendar`
- Removed `create_calendar_hold()` and `check_calendar_availability()` function definitions
- Step 3b: computes start_time inline, calls `gws_calendar.check_availability(trip_key, date, start_time)`
- Step 5: `res = gws_calendar.create_hold(fields_now)`

### calendar.js

Deleted.

---

## Test results

| # | Test | Result |
|---|------|--------|
| 1 | gws_calendar imports cleanly | PASS |
| 2 | sheets_writer imports cleanly | PASS |
| 3 | email_poller imports cleanly | PASS |
| 4 | check_availability → available:True when gws returns empty items | PASS |
| 5 | check_availability → available:False with reason when items present | PASS |
| 6 | check_availability → available:False with error on gws failure | PASS |
| 7 | create_hold → ok:True with eventId on success | PASS |
| 8 | create_hold → ok:False with error when no trip_key | PASS |
| 9 | sheets_writer subprocess args contain 'gws', 'sheets', 'append' | PASS |
| 10 | calendar.js does not exist | PASS |
