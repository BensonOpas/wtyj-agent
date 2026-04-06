# OUTPUT 007 — calendar.js — KEY_PATH and timezone fix

## Files created or modified
- `bluemarlin/src/calendar.js` — modified (Brief 007)

## Assumptions made
- `bluemarlin/config/bluemarlin-calendar-key.json` does not exist on Mac (config dir contains only `.gitkeep`). The brief notes Tests 3 and 4 may be skipped if the key file is absent — however, re-reading the actual test commands, none of the 5 tests require the key file to exist on disk. All tests passed on Mac.
- `googleapis` npm package is not installed on Mac. Test 1 produces a `Cannot find module 'googleapis'` error, which is a runtime module-resolution error, not a syntax error. This is expected and acceptable per the brief: "A syntax error will show before the argv error. Document what the output is." The file has no syntax errors.
- `path` is Node.js stdlib — no npm install required.
- No new packages installed.

## Dependencies added
- None.

## Changes made (in order per brief)
**Fix 1 — KEY_PATH:**
- Added `const path = require('path');` after `const { google } = require('googleapis');`
- Replaced `const KEY_PATH = '/root/.openclaw/bluemarlin-calendar-key.json';` with `const KEY_PATH = path.join(__dirname, '..', 'config', 'bluemarlin-calendar-key.json');`

**Fix 2 — timezone bug:**
- Replaced `const startDateTime = new Date(year, month - 1, day, hour, minute);` and `const endDateTime = new Date(startDateTime);` with:
  ```js
  // Construct time in America/Curacao (always UTC-4, no DST)
  const CURACAO_OFFSET_MS = -4 * 60 * 60 * 1000;
  const utcMs = Date.UTC(year, month - 1, day, hour, minute) - CURACAO_OFFSET_MS;
  const startDateTime = new Date(utcMs);
  const endDateTime = new Date(utcMs);
  ```

**Fix 3 — file header:**
- Added JS header comment block as the very first lines of the file

**Unchanged:** CALENDARS, DURATIONS_HOURS, createHold() signature, availability check logic, event object structure, process.argv block.

## Test results

### Test 1 — syntax check
```
Command: node -e "require('./bluemarlin/src/calendar.js')" 2>&1 | head -5
Output:
  node:internal/modules/cjs/loader:1450
    throw err;
    ^
  Error: Cannot find module 'googleapis'
```
Interpretation: No syntax errors. The JS engine parsed the file successfully and reached the `require('googleapis')` call before failing. `googleapis` is not installed on Mac (not needed for testing). This is expected per the brief.

### Test 2 — KEY_PATH resolves correctly
```
Output:
  KEY_PATH: /Users/benson/Projects/bluemarlin-agent/bluemarlin/config/bluemarlin-calendar-key.json
  Expected: /Users/benson/Projects/bluemarlin-agent/bluemarlin/config/bluemarlin-calendar-key.json
  PASS
```

### Test 3 — old KEY_PATH removed from file
```
Output:  PASS — old KEY_PATH removed
```

### Test 4 — timezone math is correct
```
Output:
  ISO string: 2026-03-20T14:00:00.000Z
  PASS — timezone math correct
```
Confirmed: 10:00 AM Curaçao time → 14:00 UTC (UTC-4 offset correctly applied).

### Test 5 — old new Date(year,...) constructor removed
```
Output:  PASS — old Date constructor removed
```

## Flags / uncertainties
- `googleapis` npm package must be installed on the VPS for the script to run. This is a pre-existing dependency, unchanged by this brief.
- `bluemarlin/config/bluemarlin-calendar-key.json` must exist on the VPS at deployment time. Not present on Mac — expected.
- On the VPS, `__dirname` will resolve to `/root/bluemarlin/src`, making `KEY_PATH` = `/root/bluemarlin/config/bluemarlin-calendar-key.json`, which matches CODEX_CONTEXT credential locations.

## SYSTEM_STATE update
Brief 007 — calendar.js — KEY_PATH now resolves relative to __dirname (bluemarlin/config/bluemarlin-calendar-key.json); timezone bug fixed: startDateTime and endDateTime now constructed via Date.UTC with explicit UTC-4 offset — Callers (email_poller.py): subprocess interface unchanged; calendar holds will now be created at the correct Curaçao local time instead of being 4 hours off.

## Dependency impact
Files that call calendar.js: email_poller.py (via subprocess in create_calendar_hold())
What callers should expect differently: No interface change. The JSON payload format and response format are identical. Calendar events will now reflect the correct Curaçao local time (10:00 AM Curaçao → 14:00 UTC, previously was 10:00 UTC which displayed as 06:00 Curaçao).

## Regression check
# BRIEF_007 — calendar.js — verifies KEY_PATH resolution, old path removed, timezone math, old constructor removed
# Tests: calendar.js
node -e "const fs=require('fs'); const c=fs.readFileSync('bluemarlin/src/calendar.js','utf8'); if(c.includes('/root/.openclaw'))process.exit(1); console.log('NO OLD PATH OK');"
node -e "const fs=require('fs'); const c=fs.readFileSync('bluemarlin/src/calendar.js','utf8'); if(c.includes('new Date(year'))process.exit(1); console.log('NO OLD DATE CONSTRUCTOR OK');"
node -e "const CURACAO_OFFSET_MS=-4*60*60*1000; const utcMs=Date.UTC(2026,2,20,10,0)-CURACAO_OFFSET_MS; const iso=new Date(utcMs).toISOString(); if(!iso.startsWith('2026-03-20T14:00:00'))process.exit(1); console.log('TZ MATH OK');"
