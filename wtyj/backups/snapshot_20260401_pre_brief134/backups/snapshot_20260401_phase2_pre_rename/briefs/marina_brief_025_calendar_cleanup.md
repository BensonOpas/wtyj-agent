# BRIEF 025 — calendar.js + email_poller.py — BlueFinn Cleanup

**Brief number:** 025
**Status:** Ready to execute
**Files modified:** bluemarlin/src/calendar.js, bluemarlin/src/email_poller.py
**Files created:** None
**Depends on:** Brief 024 (email_poller.py), Brief 022 (client.json)
**Blocks:** Nothing — this is the final cleanup before go-live

---

## CONTEXT

calendar.js was written for the old BlueMarlin demo. It has three
problems:

1. CALENDARS object uses invented BlueMarlin package keys
   (half_day_private_charter, sunset_signature_cruise,
   full_day_west_coast_escape). email_poller.py now passes real
   BlueFinn trip keys (klein_curacao, snorkeling_3in1,
   west_coast_beach, sunset_cruise, jet_ski). These do not match.
   Any hold attempt currently throws "Unknown package_key".

2. DURATIONS_HOURS uses the same invented keys.

3. The real Google Calendar IDs for BlueFinn trips are not yet
   confirmed — they are [VERIFY] placeholders in client.json.

email_poller.py has two residual BlueMarlin references:

1. smtp_send() From header: "Marina — BlueMarlin Tours Curaçao"
2. Anti-loop stop message body references "Half-Day / Sunset /
   Full-Day" — the old BlueMarlin package names

---

## SOURCE MATERIAL

Files confirmed seen this session:

calendar.js — 75 lines, LAST MODIFIED Brief 007. Current CALENDARS
keys: half_day_private_charter, sunset_signature_cruise,
full_day_west_coast_escape. Current DURATIONS_HOURS uses same keys.

email_poller.py — 452 lines, LAST MODIFIED Brief 024.

client.json trip keys (Brief 022):
  klein_curacao    — 8 hours
  snorkeling_3in1  — duration not confirmed [VERIFY]
  west_coast_beach — 6 hours
  sunset_cruise    — 2.5 hours
  jet_ski          — 1 hour per session

Calendar IDs for all five trips: [VERIFY] — not yet provided
by BlueFinn. All five are unknown.

---

## PART 1 — calendar.js

### What changes

Replace the CALENDARS object with:

```javascript
const CALENDARS = {
  klein_curacao:    "[VERIFY: BlueFinn klein_curacao calendar ID]",
  snorkeling_3in1:  "[VERIFY: BlueFinn snorkeling_3in1 calendar ID]",
  west_coast_beach: "[VERIFY: BlueFinn west_coast_beach calendar ID]",
  sunset_cruise:    "[VERIFY: BlueFinn sunset_cruise calendar ID]",
  jet_ski:          "[VERIFY: BlueFinn jet_ski calendar ID]"
};
```

Replace the DURATIONS_HOURS object with:

```javascript
const DURATIONS_HOURS = {
  klein_curacao:    8,
  snorkeling_3in1:  4,
  west_coast_beach: 6,
  sunset_cruise:    2.5,
  jet_ski:          1
};
```

Note: snorkeling_3in1 duration is unconfirmed. Use 4 as a safe
placeholder. This will be corrected when BlueFinn confirms.

The calendarId lookup currently throws on unknown package_key:

```javascript
if (!calendarId) throw new Error(`Unknown package_key: ${package_key}`);
```

This must also catch the case where calendarId is a [VERIFY]
placeholder string. Replace that line with:

```javascript
if (!calendarId || calendarId.startsWith("[VERIFY")) {
  throw new Error(`Calendar ID not yet configured for: ${package_key}`);
}
```

Update file header: LAST MODIFIED Brief 007 → Brief 025
No other changes to calendar.js.

---

## PART 2 — email_poller.py

Two surgical changes only.

### Change 1 — smtp_send From header

Current:

```
msg["From"] = "Marina — BlueMarlin Tours Curaçao <{}>".format(EMAIL_ADDR)
```

Replace with:

```
msg["From"] = "Marina — BlueFinn Charters Curaçao <{}>".format(EMAIL_ADDR)
```

### Change 2 — Anti-loop stop message

Current body text includes:

```
"1) Experience (Half-Day / Sunset / Full-Day)\n"
```

Replace with:

```
"1) Experience (Klein Curaçao / Sunset Cruise / West Coast Beach / Snorkeling / Jet Ski)\n"
```

Update file header: LAST MODIFIED Brief 024 → Brief 025
No other changes to email_poller.py.

---

## TESTS

**Test 1** — old BlueMarlin keys are gone from calendar.js
Read calendar.js as text. Assert "half_day_private_charter" not in
source. Assert "sunset_signature_cruise" not in source. Assert
"full_day_west_coast_escape" not in source.

**Test 2** — new BlueFinn keys are present in calendar.js
Read calendar.js as text. Assert all five of "klein_curacao",
"snorkeling_3in1", "west_coast_beach", "sunset_cruise", "jet_ski"
are present.

**Test 3** — VERIFY guard works
Run calendar.js with a payload containing a valid new key but without
real calendar IDs in place. Assert process exits with non-zero code
and error message contains "not yet configured". (This confirms the
guard fires, not that the hold succeeds.)

**Test 4** — DURATIONS_HOURS covers all five keys
Read calendar.js as text. Assert all five trip keys are present in
the file with their numeric durations.

**Test 5** — email_poller.py From header is correct
Read email_poller.py as text. Assert "BlueMarlin" not in source.
Assert "BlueFinn Charters Curaçao" in source.

**Test 6** — anti-loop message uses BlueFinn trip names
Read email_poller.py as text. Assert "Half-Day / Sunset / Full-Day"
not in source. Assert "Klein Curaçao" in source.

**Test 7** — email_poller.py still imports cleanly
Import email_poller from bluemarlin/src. Assert no ImportError.

**Test 8** — calendar.js parses without syntax error
Run: node --check bluemarlin/src/calendar.js
Assert exit code 0.

---

## SUCCESS CONDITION

All 8 tests pass. No BlueMarlin references remain in calendar.js or
email_poller.py. calendar.js fails gracefully with a clear error
message when calendar IDs are not yet configured.

---

## ROLLBACK

email_poller.py full pre-024 state is in ARCHIVE_PRE_022.md.
calendar.js changes are limited to two objects and one guard — revert
by restoring the three original keys if needed. Live service is not
restarted as part of this brief. VPS pull and restart happens
separately after approval.
