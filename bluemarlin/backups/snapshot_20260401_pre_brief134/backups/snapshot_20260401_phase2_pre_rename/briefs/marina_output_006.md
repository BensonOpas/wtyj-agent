# OUTPUT 006 — config paths

## Files created or modified
- `bluemarlin/src/bm_logger.py` — modified (Brief 006)
- `bluemarlin/src/email_poller.py` — modified (Brief 006)
- `bluemarlin/logs/bluemarlin.log` — created automatically by bm_logger on first write (Test 2)

## Constraint verification
Before any changes, confirmed that `os` is available at the CONFIG block in email_poller.py:
- Bundled import `import imaplib, email, urllib.request, urllib.parse, json, subprocess, time, os, re, hashlib` is on line 19
- CONFIG block begins on line 29
- `os` is available at the point where `_SRC_DIR` is defined. Confirmed — safe to proceed.

## Assumptions made
- `bluemarlin/logs/` directory did not exist; `os.makedirs(..., exist_ok=True)` in `bm_logger.log()` creates it on first write. Test 2 confirmed.
- `_SRC_DIR` is defined at module level in the CONFIG block (line 35) and is available to all subsequent module-level code and all functions, including `create_calendar_hold()` where it is used for the `calendar.js` path.
- No packages installed.

## Dependencies added
- None.

## Changes made — bm_logger.py (Steps 1–4)
1. `from datetime import datetime` → `from datetime import datetime, timezone`
2. `LOG_PATH = "/root/.openclaw/bluemarlin_demo.log"` replaced with `_BASE_DIR` + `LOG_PATH` via `os.path.join` + `os.path.normpath`
3. `datetime.utcnow().isoformat()` → `datetime.now(timezone.utc).isoformat()`
4. File header added at top (Brief 006)

## Changes made — email_poller.py (Steps 5–7)
5. CONFIG block: added `_SRC_DIR`, `_CONFIG_DIR`; replaced `REFRESH_TOKEN_PATH`, `STATE_DIR`, `THREAD_STATE_PATH` with `_CONFIG_DIR`-based paths; `SESSION_ID` unchanged in place
6. `create_calendar_hold()`: `"/root/.openclaw/workspace/calendar.js"` → `os.path.join(_SRC_DIR, "calendar.js")`
7. File header updated: `LAST MODIFIED: Brief 006`, added `# DEPENDS ON: calendar.js (original)`

## Test results

### Test 1 — bm_logger imports cleanly
```
Output:  IMPORT OK
```

### Test 2 — bm_logger writes to correct path
```
Output:  PASS — log written to bluemarlin/logs/bluemarlin.log
```

### Test 3 — bm_logger timestamp uses timezone-aware datetime
```
Output:
  Timestamp: 2026-03-03T03:13:44.033890+00:00
  PASS — timezone-aware timestamp confirmed
```

### Test 4 — email_poller imports cleanly
```
Output:  IMPORT OK
```

### Test 5 — REFRESH_TOKEN_PATH points inside bluemarlin/config/
```
Output:
  REFRESH_TOKEN_PATH: /Users/benson/Projects/bluemarlin-agent/bluemarlin/config/azure_refresh_token.txt
  PASS
```

### Test 6 — THREAD_STATE_PATH points inside bluemarlin/config/
```
Output:
  THREAD_STATE_PATH: /Users/benson/Projects/bluemarlin-agent/bluemarlin/config/email_thread_state.json
  PASS
```

### Test 7 — calendar.js path updated in source
```
Output:  PASS — calendar.js path updated
```

### Test 8 — no .openclaw paths in active config
```
Output:  PASS — no .openclaw paths in active config
```

## Flags / uncertainties
- None. All 8 tests passed.
- On the VPS, `_SRC_DIR` will resolve to `/root/bluemarlin/src`, making `_CONFIG_DIR` = `/root/bluemarlin/config` and `LOG_PATH` = `/root/bluemarlin/logs/bluemarlin.log`. Both match the CODEX_CONTEXT credential locations.

## SYSTEM_STATE update
Brief 006 — bm_logger.py — LOG_PATH now resolves relative to __file__ (bluemarlin/logs/bluemarlin.log); datetime.utcnow() replaced with datetime.now(timezone.utc) — Callers: no API changes; log() return value now has timezone-aware ISO timestamp.
Brief 006 — email_poller.py — REFRESH_TOKEN_PATH, STATE_DIR, THREAD_STATE_PATH now resolve relative to __file__ under bluemarlin/config/; calendar.js path now resolves relative to __file__ under bluemarlin/src/ — Callers: none (top-level entry point); no API changes.

## Dependency impact
Files that import bm_logger: email_poller.py
What callers should expect differently: `log()` return dict now contains timezone-aware ISO 8601 timestamp (e.g. `2026-03-03T03:13:44+00:00` instead of naive UTC). No functional impact on callers that only log and discard the return value.

Files that import email_poller: none (entry point)
What callers should expect differently: N/A

## Regression check
# BRIEF_006 — bm_logger.py / email_poller.py — verifies path resolution and timezone-aware logging
# Tests: bm_logger.py, email_poller.py
python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import bm_logger; print('bm_logger IMPORT OK')"
python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import bm_logger; r=bm_logger.log('regression'); assert '+00:00' in r['ts'] or r['ts'].endswith('Z'); print('TZ OK')"
python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import email_poller; assert 'openclaw' not in email_poller.REFRESH_TOKEN_PATH; assert 'bluemarlin' in email_poller.REFRESH_TOKEN_PATH; print('PATHS OK')"
python3 -c "with open('bluemarlin/src/email_poller.py') as f: c=f.read(); assert '/root/.openclaw/workspace/calendar.js' not in c; print('CALENDAR PATH OK')"
