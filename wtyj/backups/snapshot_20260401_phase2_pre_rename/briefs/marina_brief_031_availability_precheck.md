# BRIEF 031 — Availability Pre-Check Before Booking Summary

**Brief number:** 031
**Status:** Ready to execute
**Files modified:** bluemarlin/src/calendar.js, bluemarlin/src/email_poller.py, bluemarlin/src/marina_agent.py
**Files created:** None
**Depends on:** Brief 030 (marina_agent.py, email_poller.py), Brief 026 (calendar.js)
**Blocks:** Nothing — fixes live UX problem

---

## CONTEXT

Currently Marina presents a booking summary ("Shall I lock this in?")
without knowing whether the slot is actually available. If the slot
is taken, the customer has already been shown a confident summary
and said yes before finding out.

The fix: Python checks availability immediately after marina_agent
sets awaiting_booking_confirmation, before sending the summary to
the customer. If the slot is taken, the customer gets an apology
and alternatives instead of the summary. One Claude call, two
conditional replies — same pattern as Brief 030.

---

## SOURCE MATERIAL

Files confirmed seen this session:

calendar.js createHold function (lines 26–76, Brief 026).
Availability check block inside createHold (lines 53–65):
uses calendar.events.list with timeMin/timeMax, throws
"UNAVAILABLE: Slot already booked/held" if events found.
File currently has one exported behaviour: createHold via
process.argv[2] JSON payload.

email_poller.py create_calendar_hold() — lines 175–215, Brief 030.
Calls calendar.js via subprocess.run with JSON payload.
Returns {ok, eventId?, htmlLink?, error?}.

email_poller.py main loop booking flow — lines 299–473, Brief 030.
reply_text default at line 347.
awaiting_booking_confirmation not currently detected by Python —
it is set by marina_agent in flags and merged into th["flags"].
hold trigger condition checks booking_confirmed flag.

marina_agent.py _build_prompt() — Brief 030.
reply_hold_failed currently only instructed when booking_confirmed
is true in thread flags.
awaiting_booking_confirmation behaviour section present.

---

## PART 1 — calendar.js

### Add checkAvailability function

Add the following function after the closing brace of createHold
and before the process.argv block at the bottom:
```javascript
async function checkAvailability({ package_key, date, start_time }) {
  const auth = new google.auth.GoogleAuth({
    keyFile: KEY_PATH,
    scopes: ['https://www.googleapis.com/auth/calendar']
  });

  const calendar = google.calendar({ version: 'v3', auth });
  const calendarId = CALENDARS[package_key];
  if (!calendarId || !calendarId.endsWith("@group.calendar.google.com")) {
    return { available: false, error: `Calendar ID not yet configured for: ${package_key}` };
  }

  const [year, month, day] = date.split('-').map(Number);
  const [hour, minute] = start_time.split(':').map(Number);

  const CURACAO_OFFSET_MS = -4 * 60 * 60 * 1000;
  const utcMs = Date.UTC(year, month - 1, day, hour, minute) - CURACAO_OFFSET_MS;
  const startDateTime = new Date(utcMs);
  const endDateTime = new Date(utcMs);
  const dur = DURATIONS_HOURS[package_key] || 4;
  endDateTime.setTime(endDateTime.getTime() + dur * 60 * 60 * 1000);

  const timeMin = startDateTime.toISOString();
  const timeMax = endDateTime.toISOString();

  try {
    const existing = await calendar.events.list({
      calendarId,
      timeMin,
      timeMax,
      singleEvents: true,
      orderBy: 'startTime',
      maxResults: 5
    });
    const items = existing.data.items || [];
    if (items.length > 0) {
      return { available: false, reason: `Slot already booked (${items[0].summary || 'event'})` };
    }
    return { available: true };
  } catch (err) {
    return { available: false, error: err.message };
  }
}
```

### Update process.argv routing block

Current block at the bottom of calendar.js:
```javascript
const args = JSON.parse(process.argv[2]);
createHold(args)
  .then(result => console.log(JSON.stringify(result)))
  .catch(err => { console.error(err.message); process.exit(1); });
```

Replace with:
```javascript
const input = JSON.parse(process.argv[2]);
const command = input.command || 'createHold';

if (command === 'checkAvailability') {
  checkAvailability(input)
    .then(result => console.log(JSON.stringify(result)))
    .catch(err => { console.error(err.message); process.exit(1); });
} else {
  createHold(input)
    .then(result => console.log(JSON.stringify(result)))
    .catch(err => { console.error(err.message); process.exit(1); });
}
```

Update file header: LAST MODIFIED Brief 026 → Brief 031

---

## PART 2 — email_poller.py

### Add check_calendar_availability function

Add the following function immediately after create_calendar_hold():
```python
def check_calendar_availability(fields_now: dict) -> dict:
    """
    Calls node calendar.js to check slot availability without creating a hold.
    Returns dict: {available: bool, reason?: str, error?: str}
    """
    trip_key = fields_now.get("trip_key", "")
    if not trip_key:
        return {"available": False, "error": "No trip_key in fields"}

    trip = config_loader.get_trip(trip_key)
    departures = trip.get("departures", [])
    start_time = (
        fields_now.get("departure_time")
        or (departures[0].get("time", "09:00") if departures else "09:00")
    )

    payload = {
        "command": "checkAvailability",
        "package_key": trip_key,
        "date": fields_now.get("date", ""),
        "start_time": start_time,
    }

    try:
        r = subprocess.run(
            ["node", os.path.join(_SRC_DIR, "calendar.js"), json.dumps(payload)],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            return {"available": False, "error": (r.stderr or r.stdout or "calendar.js failed").strip()[:500]}
        out = (r.stdout or "").strip()
        data = json.loads(out)
        return data
    except Exception as e:
        return {"available": False, "error": str(e)[:500]}
```

### Update main loop — availability check after summary intent detected

In the main loop, after Step 3 (flags merged into th["flags"]) and
before Step 4 (requires_human check), add Step 3b:
```python
# Step 3b: Availability pre-check when booking summary is being sent
if (result.get("flags", {}).get("awaiting_booking_confirmation")
        and not th["flags"].get("slot_checked")):
    fields_for_check = th["fields"]
    avail = check_calendar_availability(fields_for_check)
    th["flags"]["slot_checked"] = True
    th["flags"]["slot_available"] = avail.get("available", False)
    if not avail.get("available"):
        log(f"Slot unavailable for {from_email}: {avail.get('reason') or avail.get('error')}")
```

### Update reply selection for booking summary

Currently reply_text is set as:
```python
reply_text = result["reply"]
```

Update this default assignment to also handle slot unavailable
at summary stage:
```python
if (th["flags"].get("slot_checked")
        and not th["flags"].get("slot_available")
        and result.get("flags", {}).get("awaiting_booking_confirmation")):
    reply_text = result.get("reply_hold_failed") or result["reply"]
else:
    reply_text = result["reply"]
```

Update file header: LAST MODIFIED Brief 030 → Brief 031

---

## PART 3 — marina_agent.py

### Update reply_hold_failed instruction

In _build_prompt(), find the reply_hold_failed field description
in the JSON structure. Current instruction ends with:
"only write this field when booking_confirmed is true in thread
flags or you are sending a booking confirmation"

Replace the entire reply_hold_failed description with:
```
  "reply_hold_failed": "<reply to send if the calendar slot is unavailable or hold creation fails — apologetic, warm, offers to find another date or time, does NOT confirm the booking, does NOT include a payment link. Write this field whenever awaiting_booking_confirmation is being set to true OR booking_confirmed is true in thread flags. Always write it alongside the summary reply so Python can choose the correct one based on actual availability.>",
```

Update file header: LAST MODIFIED Brief 030 → Brief 031

---

## TESTS

**Test 1 — calendar.js passes node --check**
Run: node --check bluemarlin/src/calendar.js
Assert exit code 0.

**Test 2 — checkAvailability command returns available:true for
a free slot**
Run calendar.js with:
{"command":"checkAvailability","package_key":"sunset_cruise",
"date":"2026-06-15","start_time":"17:30"}
A date far in the future unlikely to be booked.
Assert exit code 0. Assert JSON output contains "available":true.

**Test 3 — check_calendar_availability returns dict with
available key**
Call check_calendar_availability with fields containing
trip_key="sunset_cruise", date="2026-06-15".
Assert "available" in result.
Assert isinstance(result["available"], bool).

**Test 4 — check_calendar_availability returns available:False
with no trip_key**
Call check_calendar_availability with empty fields dict.
Assert result["available"] == False.
Assert "error" in result.

**Test 5 — marina_agent returns reply_hold_failed when
awaiting_booking_confirmation is being set**
Call process_message with body:
"Sunset cruise April 25 2026 for 2 people",
thread_fields={}, thread_flags={}
Assert result.get("flags", {}).get("awaiting_booking_confirmation") == True
Assert "reply_hold_failed" in result
Assert result["reply_hold_failed"] is a non-empty string.

**Test 6 — reply_text uses reply_hold_failed when slot_checked
and slot_available is False**
Mock check_calendar_availability to return {"available": False,
"reason": "Slot already booked"}.
Mock marina_agent result with flags containing
awaiting_booking_confirmation: True and reply_hold_failed set.
Trigger Step 3b in the main loop.
Assert smtp_send is called with reply_hold_failed content.

**Test 7 — reply_text uses reply when slot_available is True**
Mock check_calendar_availability to return {"available": True}.
Same setup as Test 6.
Assert smtp_send is called with result["reply"] content (the summary).

**Test 8 — slot_checked flag set after availability check**
After triggering Step 3b, assert th["flags"]["slot_checked"] == True.
Assert th["flags"]["slot_available"] is a bool.

**Test 9 — email_poller imports cleanly**
Import email_poller. Assert no ImportError.

**Test 10 — marina_agent imports cleanly**
Import marina_agent. Assert no ImportError.

---

## SUCCESS CONDITION

All 10 tests pass. When a booking summary is about to be sent,
Python checks availability first. If unavailable, the customer
receives an apologetic reply instead of a false confirmation.
If available, the customer receives the summary as normal.
One Claude call per message throughout.

---

## ROLLBACK

check_calendar_availability is a new function — removing it
restores previous behaviour. Step 3b is an additive block.
The reply_text selection change is a simple conditional.
marina_agent prompt change is a single field description update.
None of these affect any path other than the booking summary flow.
