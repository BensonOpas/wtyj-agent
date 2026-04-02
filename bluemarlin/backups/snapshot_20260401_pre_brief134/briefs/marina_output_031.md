# OUTPUT_031 — Availability Pre-Check Before Booking Summary

## Files modified
- `bluemarlin/src/calendar.js`
- `bluemarlin/src/email_poller.py`
- `bluemarlin/src/marina_agent.py`

## Files created
- `bluemarlin/briefs/OUTPUT_031.md` (this file)

---

## Changes made

### calendar.js

**checkAvailability function** — added after createHold's closing brace:
- Accepts { package_key, date, start_time }
- Uses same UTC offset logic as createHold (CURACAO_OFFSET_MS = -4h)
- Checks calendar.events.list for existing events in the slot window
- Returns { available: true } if free, { available: false, reason: "..." } if booked,
  { available: false, error: "..." } on any error
- Uses same calendarId guard: endsWith("@group.calendar.google.com")

**process.argv routing block** — replaced:
- Parses `input.command` (defaults to 'createHold')
- Routes to checkAvailability when command === 'checkAvailability'
- Falls through to createHold otherwise

File header: LAST MODIFIED Brief 026 → Brief 031

### email_poller.py

**check_calendar_availability function** — added after create_calendar_hold():
- Builds payload with command: "checkAvailability", package_key, date, start_time
- start_time follows same departure_time → departures[0] → "09:00" fallback
- Calls calendar.js via subprocess.run
- Returns the parsed JSON dict from calendar.js

**Step 3b** — inserted between Step 3 (flags persist) and Step 4 (requires_human):
- Fires when result flags contain awaiting_booking_confirmation AND slot_checked not yet set
- Calls check_calendar_availability with th["fields"]
- Sets th["flags"]["slot_checked"] = True and th["flags"]["slot_available"] = bool
- Logs slot unavailable if applicable

**reply_text selection** — replaced `reply_text = result["reply"]` default with conditional:
- If slot_checked AND not slot_available AND awaiting_booking_confirmation:
  uses reply_hold_failed with fallback to reply
- Otherwise: uses reply as normal

File header: LAST MODIFIED Brief 030 → Brief 031

### marina_agent.py

**reply_hold_failed description** — updated:
Old: "only write this field when booking_confirmed is true..."
New: "Write this field whenever awaiting_booking_confirmation is being set to true
OR booking_confirmed is true in thread flags. Always write it alongside the summary
reply so Python can choose the correct one based on actual availability."

File header: LAST MODIFIED Brief 030 → Brief 031

---

## Test results

| # | Test | Result |
|---|------|--------|
| 1 | calendar.js passes node --check | PASS |
| 2 | checkAvailability returns available:true for free future slot | PASS |
| 3 | check_calendar_availability returns dict with available (bool) key | PASS |
| 4 | check_calendar_availability returns available:False with no trip_key | PASS |
| 5 | reply_hold_failed present when awaiting_booking_confirmation being set | PASS |
| 6 | reply_text uses reply_hold_failed when slot_checked + unavailable | PASS |
| 7 | reply_text uses reply when slot_available is True | PASS |
| 8 | slot_checked=True, slot_available is bool after Step 3b | PASS |
| 9 | email_poller imports cleanly | PASS |
| 10 | marina_agent imports cleanly | PASS |
