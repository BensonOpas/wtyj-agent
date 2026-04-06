# BRIEF 006 — config paths
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Fix all hardcoded paths in bm_logger.py and email_poller.py
so the system works correctly from /root/bluemarlin/ on the VPS
and from ~/Projects/bluemarlin-agent/bluemarlin/ on Mac.
Fix deprecated datetime.utcnow() in bm_logger.py.
This is a path-fix brief only — no logic changes, no new features.
## Context
bm_logger.py has LOG_PATH hardcoded to /root/.openclaw/bluemarlin_demo.log
which no longer exists. It must point to bluemarlin/logs/bluemarlin.log
constructed from __file__ so it resolves correctly on any machine.
email_poller.py has REFRESH_TOKEN_PATH, STATE_DIR, THREAD_STATE_PATH
all pointing to /root/.openclaw/ which no longer exists. They must
point to the correct locations under bluemarlin/config/.
email_poller.py line 284 calls calendar.js at the old path
/root/.openclaw/workspace/calendar.js — the file now lives at
bluemarlin/src/calendar.js and must be called from there.
## Files to modify
bluemarlin/src/bm_logger.py
bluemarlin/src/email_poller.py
## Files to read before making any changes
bluemarlin/src/bm_logger.py
bluemarlin/src/email_poller.py
Read both in full before touching either.
## Changes to bm_logger.py — follow this order exactly
STEP 1
Add timezone to the datetime import. Replace:
  from datetime import datetime
with:
  from datetime import datetime, timezone
STEP 2
Replace the hardcoded LOG_PATH constant:
  LOG_PATH = "/root/.openclaw/bluemarlin_demo.log"
with:
  _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
  LOG_PATH = os.path.join(_BASE_DIR, "..", "logs", "bluemarlin.log")
  LOG_PATH = os.path.normpath(LOG_PATH)
STEP 3
Inside the log() function replace:
  "ts": datetime.utcnow().isoformat(),
with:
  "ts": datetime.now(timezone.utc).isoformat(),
STEP 4
Update the file header at the very top of the file:
  # FILE: bm_logger.py
  # CREATED: Before Brief 001 (original codebase)
  # LAST MODIFIED: Brief 006
  # DEPENDS ON: nothing
  # IMPORTS FROM: nothing
  # CALLERS: email_poller.py (original)
## Changes to email_poller.py — follow this order exactly
STEP 5
In the CONFIG block replace these three lines:
  REFRESH_TOKEN_PATH = "/root/.openclaw/azure_refresh_token.txt"
  SESSION_ID = "c5613944-cb20-4c34-941e-fd0e53f70494"
  ...
  STATE_DIR = "/root/.openclaw"
  THREAD_STATE_PATH = os.path.join(STATE_DIR, "email_thread_state.json")
With:
  _SRC_DIR = os.path.dirname(os.path.abspath(__file__))
  _CONFIG_DIR = os.path.normpath(os.path.join(_SRC_DIR, "..", "config"))
  REFRESH_TOKEN_PATH = os.path.join(_CONFIG_DIR, "azure_refresh_token.txt")
  SESSION_ID = "c5613944-cb20-4c34-941e-fd0e53f70494"
  ...
  STATE_DIR = _CONFIG_DIR
  THREAD_STATE_PATH = os.path.join(_CONFIG_DIR, "email_thread_state.json")
Keep SESSION_ID exactly where it is and exactly as it is.
Keep all other CONFIG values exactly as they are.
STEP 6
Find the calendar.js subprocess call. It currently reads:
  ["node", "/root/.openclaw/workspace/calendar.js", json.dumps(payload)]
Replace the path only — do not touch anything else on that line:
  ["node", os.path.join(_SRC_DIR, "calendar.js"), json.dumps(payload)]
STEP 7
Update the file header at the very top of email_poller.py:
  # FILE: email_poller.py
  # CREATED: Before Brief 001 (original codebase)
  # LAST MODIFIED: Brief 006
  # DEPENDS ON: claude_client.py (Brief 001)
  # DEPENDS ON: state_registry.py (Brief 004)
  # DEPENDS ON: payment_stub.py (original)
  # DEPENDS ON: bm_logger.py (original)
  # DEPENDS ON: marina_extractor.py (Brief 002)
  # DEPENDS ON: social_registry.py (original)
  # DEPENDS ON: calendar.js (original)
  # IMPORTS FROM: claude_client.py (Brief 001)
  # IMPORTS FROM: state_registry.py (Brief 004)
  # IMPORTS FROM: marina_extractor.py (Brief 002)
  # IMPORTS FROM: payment_stub.py (original)
  # IMPORTS FROM: bm_logger.py (original)
## Constraints
- Before making any changes, verify that `os` is available at the point where _SRC_DIR is defined in the CONFIG block. Confirm that the bundled import containing `os` appears before the CONFIG block in the file. If it does not, stop and report this in OUTPUT_006.md before proceeding.
- Do not change any logic in either file
- Do not change function signatures
- Do not change CONFIG values other than the paths listed above
- Do not touch SESSION_ID, CLIENT_ID, TENANT_ID, EMAIL_ADDR,
  IMAP_HOST, IMAP_PORT, SMTP_HOST, SMTP_PORT, MAILBOX,
  POLL_INTERVAL, or MAX_REPLIES_PER_THREAD
- Do not touch create_calendar_hold() other than the path fix
- Do not touch any other file
- Do not install any packages
- _SRC_DIR must be defined before it is used — confirm it is
  available at module level before STEP 6 uses it on line 284
## Test commands
Run all tests from the project root directory.
Report exact output of each test.
# Test 1 — bm_logger imports cleanly
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import bm_logger
print('IMPORT OK')
"
# Test 2 — bm_logger writes to correct path
python3 -c "
import sys, os
sys.path.insert(0, 'bluemarlin/src')
import bm_logger
bm_logger.log('test_event', detail='brief_006_test')
expected = os.path.normpath('bluemarlin/logs/bluemarlin.log')
assert os.path.exists(expected), f'FAIL: log not found at {expected}'
print('PASS — log written to', expected)
"
# Test 3 — bm_logger timestamp uses timezone-aware datetime
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import bm_logger
rec = bm_logger.log('tz_test')
ts = rec.get('ts', '')
print('Timestamp:', ts)
assert '+00:00' in ts or ts.endswith('Z'), f'FAIL: timestamp not timezone-aware: {ts}'
print('PASS — timezone-aware timestamp confirmed')
"
# Test 4 — email_poller imports cleanly
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
print('IMPORT OK')
"
# Test 5 — REFRESH_TOKEN_PATH points inside bluemarlin/config/
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
print('REFRESH_TOKEN_PATH:', email_poller.REFRESH_TOKEN_PATH)
assert 'bluemarlin' in email_poller.REFRESH_TOKEN_PATH, 'FAIL: path not updated'
assert 'openclaw' not in email_poller.REFRESH_TOKEN_PATH, 'FAIL: old path still present'
assert email_poller.REFRESH_TOKEN_PATH.endswith('azure_refresh_token.txt'), 'FAIL: wrong filename'
print('PASS')
"
# Test 6 — THREAD_STATE_PATH points inside bluemarlin/config/
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
print('THREAD_STATE_PATH:', email_poller.THREAD_STATE_PATH)
assert 'bluemarlin' in email_poller.THREAD_STATE_PATH, 'FAIL: path not updated'
assert 'openclaw' not in email_poller.THREAD_STATE_PATH, 'FAIL: old path still present'
assert email_poller.THREAD_STATE_PATH.endswith('email_thread_state.json'), 'FAIL: wrong filename'
print('PASS')
"
# Test 7 — calendar.js path updated in source
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
assert '/root/.openclaw/workspace/calendar.js' not in content, 'FAIL: old calendar.js path still present'
assert 'calendar.js' in content, 'FAIL: calendar.js reference missing'
print('PASS — calendar.js path updated')
"
# Test 8 — no .openclaw paths remaining in active config
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
paths = [
    email_poller.REFRESH_TOKEN_PATH,
    email_poller.THREAD_STATE_PATH,
]
for p in paths:
    assert '.openclaw' not in p, f'FAIL: .openclaw still in {p}'
print('PASS — no .openclaw paths in active config')
"
## Definition of done
- [ ] bm_logger.py modified in bluemarlin/src/
- [ ] bm_logger.py file header updated (Brief 006)
- [ ] LOG_PATH constructed from __file__ pointing to bluemarlin/logs/
- [ ] datetime.utcnow() replaced with datetime.now(timezone.utc)
- [ ] email_poller.py modified in bluemarlin/src/
- [ ] email_poller.py file header updated (Brief 006)
- [ ] REFRESH_TOKEN_PATH points to bluemarlin/config/
- [ ] THREAD_STATE_PATH points to bluemarlin/config/
- [ ] STATE_DIR points to bluemarlin/config/
- [ ] calendar.js path on line 284 updated to use _SRC_DIR
- [ ] All 8 tests pass with exact output shown
- [ ] OUTPUT_006.md written to bluemarlin/briefs/
- [ ] OUTPUT_006.md includes SYSTEM_STATE update block
- [ ] OUTPUT_006.md includes dependency impact block
- [ ] OUTPUT_006.md includes regression check block
