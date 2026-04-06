# OUTPUT 147 — Fix gws Hardcoded Calendar Key Path

## What was done

### Code changes
- **`bluemarlin/agents/marina/gws_calendar.py`** — `_KEY_PATH` now reads `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` from env var with `calendar-key.json` fallback (was hardcoded `bluemarlin-calendar-key.json`). Line 30's `env['GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE'] = _KEY_PATH` remains but now correctly propagates the env-var value instead of clobbering it with a stale filename.
- **`bluemarlin/agents/marina/format_sheets.py`** — same fix for `KEY_PATH`. The module uses `Credentials.from_service_account_file(KEY_PATH, ...)` directly (Google SDK, no subprocess), so it benefits from the env-var read at module-load time.
- **`bluemarlin/agents/marina/sheets_writer.py`** — same fix for `KEY_PATH`. Line 38's env override now passes through the correct value.

### New test file
- **`bluemarlin/tests/marina/test_147_gws_key_path.py`** — 9 tests covering the bug shape + guards.

### Why the Brief 145 rename didn't catch this earlier
Brief 145 only touched `docker-compose.yml` and `deploy.sh` for the rename. The three Python source files were not in Brief 145's scope. No regression test existed for "env var passthrough in _run_gws / _append," so the bug was invisible until a real booking flow tried to write to Sheets on the deployed container.

## Test results

### New tests (Brief 147)

All 9 pass:

```
test_gws_calendar_uses_env_var_when_set PASSED
test_gws_calendar_uses_new_filename_default_when_env_var_unset PASSED
test_format_sheets_uses_env_var_when_set PASSED
test_format_sheets_uses_new_filename_default PASSED
test_sheets_writer_uses_env_var_when_set PASSED
test_sheets_writer_uses_new_filename_default PASSED
test_run_gws_does_not_clobber_env_var PASSED
test_sheets_writer_append_does_not_clobber_env_var PASSED
test_old_filename_not_referenced_in_source PASSED

============================== 9 passed in 0.15s ==============================
```

The two `does_not_clobber` regression tests (7, 8) monkey-patch `subprocess.run` to capture the env dict passed through. They assert the captured env's `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` equals the sentinel value set by the test — proving the code no longer overwrites the compose value. These are the tests that would have caught the original bug if they had existed when Brief 145 landed.

### Full regression

Before Brief 147: 656 passed / 7 pre-existing failures (663 total).
After Brief 147: 665 passed / 7 failures (672 total).

Same 7 pre-existing failures unchanged. Zero new failures.

### Reload teardown fix (reviewer advisory #1 addressed)
Each reload-based test uses a pytest fixture that registers a finalizer to `importlib.reload(module)` after monkeypatch undoes the env var. This restores the module's natural state so sentinel paths don't leak into other test files via the module cache. Verified: running `test_147_gws_key_path.py` then `test_049_fix_format_sheets.py` in sequence produces no cross-test pollution.

## Deployment

### BlueMarlin redeploy

```bash
ssh root@108.61.192.52 "cd /root && git pull && docker compose down && docker compose build && docker compose up -d"
```

Built new image `root-bluemarlin` (sha256:0f25377f1578...), container `bluemarlin-default` running on port 8001, health check `{"status":"ok"}`.

### In-container module verification

```
$ docker exec bluemarlin-default python3 -c 'from agents.marina import gws_calendar, format_sheets, sheets_writer; print(gws_calendar._KEY_PATH, format_sheets.KEY_PATH, sheets_writer.KEY_PATH)'

gws_calendar._KEY_PATH: /app/config/calendar-key.json
format_sheets.KEY_PATH: /app/config/calendar-key.json
sheets_writer.KEY_PATH: /app/config/calendar-key.json
```

All three modules now honor the env var. Before the fix, they reported `.../bluemarlin-calendar-key.json`.

### Direct gws CLI call (sanity check)

```
$ docker exec bluemarlin-default bash -c 'gws sheets spreadsheets values get --params "{...1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I...All Events!A1:A1}"'

{
  "majorDimension": "ROWS",
  "range": "'All Events'!A1",
  "values": [["Timestamp"]]
}
```

gws CLI reads the env var, finds `/app/config/calendar-key.json`, authenticates, and returns real spreadsheet data. The infrastructure works.

### End-to-end proof — real write to BlueMarlin's spreadsheet

Traced `sheets_writer._append()` with a monkey-patched `subprocess.run` to capture the env and result:

```
KEY_PATH: /app/config/calendar-key.json
env var: /app/config/calendar-key.json
SUBPROCESS env CREDENTIALS: /app/config/calendar-key.json
SUBPROCESS returncode: 0
SUBPROCESS stdout: {
  "spreadsheetId": "1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I",
  "tableRange": "'All Events'!A1:E112",
  "updates": {...}
```

A real row was appended to the "All Events" tab at row 112. Authentication succeeded, write completed, no errors.

This is the mandatory verification called out in the brief (reviewer advisory #2 addressed): instead of the optional email round-trip, we exercised the exact code path (`sheets_writer._append()`) that was broken, captured the subprocess env, and confirmed a successful write to the real spreadsheet.

## Unexpected / problems encountered

**1. Old error in log file was briefly misleading.** The log file `/app/logs/email_poller.log` is mounted from the host (`/root/bluemarlin/logs/`), so log history persists across container rebuilds. After the rebuild, I initially saw the old "Authentication failed" error and worried the fix hadn't worked. Further inspection showed the error was from a pre-fix processing run, followed by several "Email poller started" lines from subsequent container restarts — the error timestamp was BEFORE the most recent restart. The mounted logs are useful for continuity but require careful reading to distinguish pre- and post-fix log entries.

**2. No lingering issues.** The fix was surgical, the tests were comprehensive, and verification was multi-layered (Python-level, gws-level, real-spreadsheet-level).

## Production impact

Brief 145 deployed ~24 hours before Brief 147. During that window, every email the poller processed that reached the booking-confirmation path or triggered a Sheets log write silently failed to record the row. The email poller continued running normally (the errors were logged but didn't crash the main loop). Customer conversations still got replies from Marina; the missing data is only the audit trail in the spreadsheet.

Impact: BlueMarlin's "All Events" tab is missing ~24 hours of booking-related writes. Actual customer service was not affected — Claude responses, email replies, state registry updates all worked independently of gws. The lost data is audit logging, not in-flight bookings.

Recovery: none required. Future writes now work correctly. The gap is a documented one-day window in the spreadsheet's history.

## Next

Brief 148 (deferred from the original Brief 147 attempt): .dockerignore + directory-mount refactor to stop baking runtime config into the Docker image. Adamus's container currently inherits BlueMarlin's runtime files from the image, which Brief 148 fixes cleanly now that the gws bug is out of the way.
