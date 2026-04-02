# BRIEF 032 — gws Migration: Replace calendar.js and sheets_writer.py

**Brief number:** 032
**Status:** Ready to execute
**Files modified:** email_poller.py, sheets_writer.py
**Files created:** gws_calendar.py
**Files deleted:** calendar.js
**Depends on:** Brief 031
**Blocks:** Brief 033

---

## RESEARCH PERMISSION

Before writing any code, read the gws CLI documentation to confirm exact flag syntax. You may search online:
* GitHub: `googleworkspace/cli` README and CONTEXT.md
* Confirmed flags from research: `--params '{...}'` for query params, `--json '{...}'` for request body, field masks go inside `--params` as a `"fields"` key — NOT as a separate `--fields` flag
* Verify `gws calendar events list`, `gws calendar events insert`, and `gws sheets spreadsheets values append` command paths before writing any subprocess calls

---

## CONTEXT

calendar.js is a Node.js wrapper around Google Calendar. sheets_writer.py is a Python wrapper around Google Sheets. Both are replaced with gws (Google Workspace CLI) subprocess calls. Behaviour is identical — this is an infrastructure swap only.

After this brief:
* calendar.js is deleted
* gws_calendar.py handles all calendar operations
* sheets_writer.py uses gws internally; public function signatures unchanged
* email_poller.py imports gws_calendar instead of calling Node subprocess

---

## WHAT TO BUILD

### gws_calendar.py (new file)

Contains two public functions:

`check_availability(trip_key, date, start_time)` — queries the calendar for events in the requested slot window, returns `{available: bool, reason?, error?}`

`create_hold(fields_now)` — creates a hold event in the calendar, returns `{ok: bool, eventId?, htmlLink?, error?}`

Both functions call gws as a subprocess. Internal helper functions for UTC conversion (Curaçao is UTC-4, no DST) and subprocess execution are left to your discretion. Copy CALENDARS and DURATIONS_HOURS dicts verbatim from calendar.js.

### sheets_writer.py (rewrite internals only)

Remove the googleapis Python client. Replace `_append()` with a gws subprocess call to `gws sheets spreadsheets values append`. Public function signatures — `log_hold_created`, `log_hold_failed`, `log_escalation`, `log_event` — and all row structures are unchanged from Brief 028.

Fallback for spreadsheet ID: try config_loader first, then env var `SPREADSHEET_ID`, then hardcode `1soG3zVnx-Y0WYWGJdgakXqpNeI6GAe6AD8DycOwwifE`.

### email_poller.py (call site updates only)

Remove `create_calendar_hold()` and `check_calendar_availability()` function definitions. Add `import gws_calendar`. Update call sites to use `gws_calendar.create_hold()` and `gws_calendar.check_availability()`. Remove `subprocess` from imports if no longer used elsewhere.

### calendar.js

Delete it.

---

## MANUAL VPS PREREQUISITES (not required for tests)

Before live deployment:
1. `npm install -g @googleworkspace/cli`
2. Auth via service account: `export GOOGLE_WORKSPACE_CLI_SERVICE_ACCOUNT_KEY=/path/to/key.json` — if this fails, use OAuth export path documented in gws README
3. Verify calendar access with `gws calendar events list --params '{"calendarId":"CALENDAR_ID","maxResults":1}'`

---

## TESTS

1. gws_calendar imports cleanly
2. sheets_writer imports cleanly
3. email_poller imports cleanly
4. check_availability returns `{available: True}` when gws returns empty items (mock subprocess)
5. check_availability returns `{available: False, reason: ...}` when items are present (mock subprocess)
6. check_availability returns `{available: False, error: ...}` on gws failure (mock subprocess)
7. create_hold returns `{ok: True, eventId: ...}` on success (mock subprocess)
8. create_hold returns `{ok: False, error: ...}` with no trip_key
9. sheets_writer calls gws via subprocess with 'sheets' and 'append' in args (mock subprocess)
10. calendar.js no longer exists

---

## SUCCESS CONDITION

All 10 tests pass. Booking flow and sheets logging behave identically to Brief 031 from the outside. Node.js is no longer in the production path.

---

## ROLLBACK

`git checkout v0.31-pre-gws`
