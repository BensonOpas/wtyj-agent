# BRIEF 026 — Inject Real Calendar IDs

**Brief number:** 026
**Status:** Ready to execute
**Files modified:** bluemarlin/src/calendar.js, bluemarlin/config/client.json
**Files created:** None
**Depends on:** Brief 025 (calendar.js), Brief 022 (client.json)
**Blocks:** Nothing — this is the final step before go-live

---

## CONTEXT

calendar.js and client.json currently have [VERIFY] placeholders
for all five Google Calendar IDs. The real IDs have been provided
and must be injected exactly as given. No other changes.

---

## SOURCE MATERIAL

Real calendar IDs confirmed this session:

klein_curacao:
ed9e5c8b2357d2e21b99af2617c58836204443ed7e8d7352661426cca41cf4cb@group.calendar.google.com

snorkeling_3in1:
649576fb0d0eb17fc895981db2f5e2339ac045edf3a4292d40eff57786fa06db@group.calendar.google.com

west_coast_beach:
a85ac414af5903971715705bb8f0975a0be07ca637017c1184f1ba7cd4ab1c00@group.calendar.google.com

sunset_cruise:
a3df969d58e35c9603fe6ae6672446ec2f430ed3304f9c5aaf2178391e67defe@group.calendar.google.com

jet_ski:
903f29c1161ed6d1378b7d4b1f7ef0597ce6707e2648fd98b82b081542919f08@group.calendar.google.com

---

## PART 1 — calendar.js

Replace the CALENDARS object exactly as follows:

```javascript
const CALENDARS = {
  klein_curacao:    "ed9e5c8b2357d2e21b99af2617c58836204443ed7e8d7352661426cca41cf4cb@group.calendar.google.com",
  snorkeling_3in1:  "649576fb0d0eb17fc895981db2f5e2339ac045edf3a4292d40eff57786fa06db@group.calendar.google.com",
  west_coast_beach: "a85ac414af5903971715705bb8f0975a0be07ca637017c1184f1ba7cd4ab1c00@group.calendar.google.com",
  sunset_cruise:    "a3df969d58e35c9603fe6ae6672446ec2f430ed3304f9c5aaf2178391e67defe@group.calendar.google.com",
  jet_ski:          "903f29c1161ed6d1378b7d4b1f7ef0597ce6707e2648fd98b82b081542919f08@group.calendar.google.com"
};
```

Update file header: LAST MODIFIED Brief 025 → Brief 026
No other changes to calendar.js.

---

## PART 2 — client.json

Replace the calendar_id value for each of the five trips.
The trips block structure is unchanged — only the calendar_id
value inside each trip is updated.

- klein_curacao calendar_id:
  ed9e5c8b2357d2e21b99af2617c58836204443ed7e8d7352661426cca41cf4cb@group.calendar.google.com

- snorkeling_3in1 calendar_id:
  649576fb0d0eb17fc895981db2f5e2339ac045edf3a4292d40eff57786fa06db@group.calendar.google.com

- west_coast_beach calendar_id:
  a85ac414af5903971715705bb8f0975a0be07ca637017c1184f1ba7cd4ab1c00@group.calendar.google.com

- sunset_cruise calendar_id:
  a3df969d58e35c9603fe6ae6672446ec2f430ed3304f9c5aaf2178391e67defe@group.calendar.google.com

- jet_ski calendar_id:
  903f29c1161ed6d1378b7d4b1f7ef0597ce6707e2648fd98b82b081542919f08@group.calendar.google.com

No other changes to client.json.

---

## TESTS

**Test 1 — no [VERIFY] calendar strings remain in calendar.js**
Read calendar.js as text. Assert "[VERIFY" not in source.

**Test 2 — all five real IDs present in calendar.js**
Read calendar.js as text. Assert each of the five calendar ID
strings is present verbatim.

**Test 3 — no [VERIFY] calendar strings remain in client.json**
Read client.json as text. Assert the string
"[VERIFY: BlueFinn" does not appear next to any calendar_id key.
(Other [VERIFY] placeholders for unrelated fields may still exist.)

**Test 4 — all five real IDs present in client.json**
Read client.json as text. Assert each of the five calendar ID
strings is present verbatim.

**Test 5 — calendar.js parses without syntax error**
Run: node --check bluemarlin/src/calendar.js
Assert exit code 0.

**Test 6 — client.json parses as valid JSON**
Parse client.json with json.loads(). Assert no exception.

**Test 7 — config_loader returns correct calendar ID for sunset_cruise**
Import config_loader. Call get_trip("sunset_cruise").
Assert result["calendar_id"] ==
"a3df969d58e35c9603fe6ae6672446ec2f430ed3304f9c5aaf2178391e67defe@group.calendar.google.com"

**Test 8 — config_loader returns correct calendar ID for klein_curacao**
Import config_loader. Call get_trip("klein_curacao").
Assert result["calendar_id"] ==
"ed9e5c8b2357d2e21b99af2617c58836204443ed7e8d7352661426cca41cf4cb@group.calendar.google.com"

---

## SUCCESS CONDITION

All 8 tests pass. No [VERIFY] placeholder remains for any
calendar_id in either file. The system can now create real
Google Calendar holds for all five BlueFinn trips.

---

## ROLLBACK

If either file is corrupted, restore from:
- calendar.js: ARCHIVE_PRE_022.md contains the pre-022 version.
  Brief 025 changes are the CALENDARS and DURATIONS_HOURS objects
  plus the [VERIFY] guard — these are simple to re-apply manually.
- client.json: restore [VERIFY] placeholders for all five
  calendar_id fields. Live service is unaffected until VPS pulls.
