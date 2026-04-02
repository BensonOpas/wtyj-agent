# OUTPUT_025 — calendar.js + email_poller.py — BlueFinn Cleanup

## Files modified
- `bluemarlin/src/calendar.js`
- `bluemarlin/src/email_poller.py`

## Files created
- `bluemarlin/briefs/OUTPUT_025.md` (this file)

---

## Part 1 — calendar.js

### CALENDARS object replaced
Old keys (invented BlueMarlin names) removed:
- half_day_private_charter
- sunset_signature_cruise
- full_day_west_coast_escape

New keys (real BlueFinn trip keys, calendar IDs are [VERIFY] placeholders):
```javascript
const CALENDARS = {
  klein_curacao:    "[VERIFY: BlueFinn klein_curacao calendar ID]",
  snorkeling_3in1:  "[VERIFY: BlueFinn snorkeling_3in1 calendar ID]",
  west_coast_beach: "[VERIFY: BlueFinn west_coast_beach calendar ID]",
  sunset_cruise:    "[VERIFY: BlueFinn sunset_cruise calendar ID]",
  jet_ski:          "[VERIFY: BlueFinn jet_ski calendar ID]"
};
```

### DURATIONS_HOURS object replaced
```javascript
const DURATIONS_HOURS = {
  klein_curacao:    8,
  snorkeling_3in1:  4,   // placeholder — unconfirmed
  west_coast_beach: 6,
  sunset_cruise:    2.5,
  jet_ski:          1
};
```

### [VERIFY] guard added
Old:
```javascript
if (!calendarId) throw new Error(`Unknown package_key: ${package_key}`);
```
New:
```javascript
if (!calendarId || calendarId.startsWith("[VERIFY")) {
  throw new Error(`Calendar ID not yet configured for: ${package_key}`);
}
```

File header: LAST MODIFIED Brief 007 → Brief 025

---

## Part 2 — email_poller.py

### Change 1 — smtp_send From header
```python
# Before
msg["From"] = "Marina — BlueMarlin Tours Curaçao <{}>".format(EMAIL_ADDR)
# After
msg["From"] = "Marina — BlueFinn Charters Curaçao <{}>".format(EMAIL_ADDR)
```

### Change 2 — Anti-loop stop message
```python
# Before
"1) Experience (Half-Day / Sunset / Full-Day)\n"
# After
"1) Experience (Klein Curaçao / Sunset Cruise / West Coast Beach / Snorkeling / Jet Ski)\n"
```

File header: LAST MODIFIED Brief 024 → Brief 025

**Note:** The Write tool in Brief 024 stored Unicode escapes (`\u00e7`, `\u2014`) as literal
escape sequences in the source file. Brief 025 edits corrected these to actual Unicode
characters so text-based assertions pass correctly.

---

## Test results

| # | Test | Result |
|---|------|--------|
| 1 | Old BlueMarlin keys gone from calendar.js | PASS |
| 2 | All five BlueFinn keys present in calendar.js | PASS |
| 3 | VERIFY guard fires — exit non-zero, "not yet configured" in error | PASS |
| 4 | DURATIONS_HOURS covers all five keys with correct durations | PASS |
| 5 | email_poller.py From header is BlueFinn Charters Curaçao, BlueMarlin absent | PASS |
| 6 | Anti-loop uses Klein Curaçao / Sunset Cruise etc., old names absent | PASS |
| 7 | email_poller.py imports cleanly | PASS |
| 8 | node --check calendar.js exits 0 | PASS |

**Note on Test 3:** `googleapis` is not installed locally (VPS-only dependency, no package.json
in project). Test was run with `NODE_PATH` pointing to the gemini-cli node_modules installation,
which provides a compatible googleapis version. The guard fires before any API call, so the
behaviour is identical to the VPS.

---

## Regression check block
```
python3 -c "
with open('bluemarlin/src/calendar.js') as f: s=f.read()
assert 'half_day_private_charter' not in s
assert 'klein_curacao' in s and 'sunset_cruise' in s
assert '[VERIFY: BlueFinn' in s
assert 'not yet configured' in s
with open('bluemarlin/src/email_poller.py') as f: s=f.read()
assert 'BlueMarlin' not in s
assert 'BlueFinn Charters Curaçao' in s
assert 'Klein Curaçao' in s
assert 'Half-Day / Sunset / Full-Day' not in s
import sys; sys.path.insert(0,'bluemarlin/src'); import email_poller
print('Brief 025 regression OK')
"
```

## [VERIFY] items remaining in calendar.js
All five calendar IDs must be provided by BlueFinn before go-live:
- klein_curacao calendar ID
- snorkeling_3in1 calendar ID
- west_coast_beach calendar ID
- sunset_cruise calendar ID
- jet_ski calendar ID

Until these are filled in, any booking attempt will fail with
"Calendar ID not yet configured for: <trip_key>" — by design.
