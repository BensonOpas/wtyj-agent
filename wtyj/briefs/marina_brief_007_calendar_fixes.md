# BRIEF 007 — calendar.js — KEY_PATH and timezone fix
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Fix two issues in calendar.js:
1. KEY_PATH is hardcoded to /root/.openclaw/bluemarlin-calendar-key.json
   which no longer exists. Fix it to resolve relative to __dirname.
2. new Date(year, month-1, day, hour, minute) constructs a date in the
   Node.js process local timezone (UTC on VPS) instead of
   America/Curacao (UTC-4). This causes all calendar holds and
   availability checks to be 4 hours wrong on the VPS.
This is a surgical fix only. CALENDARS, DURATIONS_HOURS, and all
other logic stay exactly as they are.
## Context
calendar.js is called by email_poller.py via subprocess:
  subprocess.run(["node", ".../calendar.js", json.dumps(payload)])
It receives a JSON payload and creates a Google Calendar hold event.
The key file now lives at bluemarlin/config/bluemarlin-calendar-key.json.
The VPS runs UTC. Curaçao is UTC-4. Without the fix, a customer
requesting 10:00 AM gets a hold at 2:00 PM on the calendar.
## File to modify
bluemarlin/src/calendar.js
## Files to read before making changes
Read bluemarlin/src/calendar.js in full before touching anything.
## Fix 1 — KEY_PATH
CURRENT CODE:
  const KEY_PATH = '/root/.openclaw/bluemarlin-calendar-key.json';
REPLACE WITH:
  const path = require('path');
  const KEY_PATH = path.join(__dirname, '..', 'config', 'bluemarlin-calendar-key.json');
The path module is Node.js stdlib — no npm install needed.
__dirname is the directory containing calendar.js which is
bluemarlin/src/. Joining with '..' and 'config' gives
bluemarlin/config/ which is where the key file now lives.
## Fix 2 — timezone bug
CURRENT CODE (lines 29-30):
  const startDateTime = new Date(year, month - 1, day, hour, minute);
  const endDateTime = new Date(startDateTime);
The problem: new Date(year, month-1, day, hour, minute) interprets
the values in the local system timezone. On a UTC VPS, 10:00 becomes
10:00 UTC which displays as 14:00 in Curaçao (UTC+4 error direction
— actually Curaçao is UTC-4 so 10:00 UTC = 06:00 Curaçao, meaning
we are 4 hours ahead of where we should be).
THE FIX:
Construct the date as an explicit UTC offset for America/Curacao
which is always UTC-4 (no daylight saving time).
Replace those two lines with:
  // Construct time in America/Curacao (always UTC-4, no DST)
  const CURACAO_OFFSET_MS = -4 * 60 * 60 * 1000;
  const utcMs = Date.UTC(year, month - 1, day, hour, minute) - CURACAO_OFFSET_MS;
  const startDateTime = new Date(utcMs);
  const endDateTime = new Date(utcMs);
Explanation:
- Date.UTC(year, month-1, day, hour, minute) treats the values as UTC
- Subtracting CURACAO_OFFSET_MS (-4h) converts from Curacao local
  time to UTC correctly
- The resulting Date objects are in UTC and will produce correct
  ISO strings for the Google Calendar API
- Example: customer requests 10:00 AM Curacao time
  Date.UTC gives 10:00 UTC, subtract -4h gives 14:00 UTC
  which is correct (10:00 AM Curacao = 14:00 UTC)
## Fix 3 — file header
Add this as the very first lines of the file before any requires:
  // FILE: calendar.js
  // CREATED: Before Brief 001 (original codebase)
  // LAST MODIFIED: Brief 007
  // DEPENDS ON: bluemarlin-calendar-key.json (config)
  // CALLED BY: email_poller.py via subprocess
## Constraints
- Do not change CALENDARS object
- Do not change DURATIONS_HOURS object
- Do not change createHold() function signature
- Do not change the availability check logic
- Do not change the event object structure
- Do not change the __main__ equivalent (process.argv block)
- Do not install any npm packages
- path is Node.js stdlib — no install needed
## Test commands
Run all tests from the project root directory.
Report exact output of each test.
Note: these tests require the Google Calendar key file to exist
at bluemarlin/config/bluemarlin-calendar-key.json on Mac.
If the key file does not exist on Mac, Tests 3 and 4 will be
skipped — document this in OUTPUT_007.md and note that the
real test happens on VPS where the key file exists.
# Test 1 — node can parse the file with no syntax errors
node -e "require('./bluemarlin/src/calendar.js')" 2>&1 | head -5
Note: this will likely error on process.argv[2] being undefined —
that is expected and acceptable. We are only checking for syntax
errors, not runtime errors. A syntax error will show before the
argv error. Document what the output is.
# Test 2 — KEY_PATH resolves correctly
node -e "
const path = require('path');
const KEY_PATH = path.join(__dirname, 'bluemarlin', 'src', '..', 'config', 'bluemarlin-calendar-key.json');
const expected = path.resolve('bluemarlin/config/bluemarlin-calendar-key.json');
console.log('KEY_PATH:', path.resolve(KEY_PATH));
console.log('Expected:', expected);
console.log(path.resolve(KEY_PATH) === expected ? 'PASS' : 'FAIL');
"
# Test 3 — old KEY_PATH is gone from the file
node -e "
const fs = require('fs');
const content = fs.readFileSync('bluemarlin/src/calendar.js', 'utf8');
if (content.includes('/root/.openclaw')) {
  console.log('FAIL: old KEY_PATH still present');
  process.exit(1);
}
console.log('PASS — old KEY_PATH removed');
"
# Test 4 — timezone math is correct
node -e "
// Simulate: customer requests 10:00 AM Curacao time on 2026-03-20
const year = 2026, month = 3, day = 20, hour = 10, minute = 0;
const CURACAO_OFFSET_MS = -4 * 60 * 60 * 1000;
const utcMs = Date.UTC(year, month - 1, day, hour, minute) - CURACAO_OFFSET_MS;
const startDateTime = new Date(utcMs);
const iso = startDateTime.toISOString();
console.log('ISO string:', iso);
// 10:00 AM Curacao = 14:00 UTC
if (!iso.startsWith('2026-03-20T14:00:00')) {
  console.log('FAIL: expected 2026-03-20T14:00:00Z, got', iso);
  process.exit(1);
}
console.log('PASS — timezone math correct');
"
# Test 5 — new Date() constructor removed from file
node -e "
const fs = require('fs');
const content = fs.readFileSync('bluemarlin/src/calendar.js', 'utf8');
if (content.includes('new Date(year')) {
  console.log('FAIL: old Date constructor still present');
  process.exit(1);
}
console.log('PASS — old Date constructor removed');
"
## Definition of done
- [ ] calendar.js modified in bluemarlin/src/
- [ ] File header added (Brief 007)
- [ ] path module required at top
- [ ] KEY_PATH uses __dirname and path.join
- [ ] Old hardcoded KEY_PATH removed
- [ ] CURACAO_OFFSET_MS constant added
- [ ] startDateTime and endDateTime constructed via Date.UTC
- [ ] Old new Date(year, month-1, day, hour, minute) removed
- [ ] All 5 tests pass or skipped with documented reason
- [ ] OUTPUT_007.md written to bluemarlin/briefs/
- [ ] OUTPUT_007.md includes SYSTEM_STATE update block
- [ ] OUTPUT_007.md includes dependency impact block
- [ ] OUTPUT_007.md includes regression check block
