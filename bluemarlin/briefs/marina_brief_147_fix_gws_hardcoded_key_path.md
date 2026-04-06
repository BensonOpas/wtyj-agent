# BRIEF 147 — Fix gws Hardcoded Calendar Key Path (production bug from Brief 145)

**Status:** Draft
**Files:** `bluemarlin/agents/marina/gws_calendar.py`, `bluemarlin/agents/marina/format_sheets.py`, `bluemarlin/agents/marina/sheets_writer.py`, `bluemarlin/tests/marina/test_147_gws_key_path.py` (new)
**Depends on:** Brief 145 (file rename), Brief 146 (Adamus deployment, where the bug surfaced)
**Blocks:** Brief 148 (.dockerignore + directory mount refactor — would break gws further if landed first)

---

## Context

Brief 145 renamed `bluemarlin/config/bluemarlin-calendar-key.json` → `bluemarlin/config/calendar-key.json` on the VPS, and updated `docker-compose.yml` and `deploy.sh` to use the new name. It missed three Python source files that hardcode the OLD filename:

- `bluemarlin/agents/marina/gws_calendar.py:14` — `_KEY_PATH = ...config/bluemarlin-calendar-key.json`
- `bluemarlin/agents/marina/format_sheets.py:15` — `KEY_PATH = ...config/bluemarlin-calendar-key.json`
- `bluemarlin/agents/marina/sheets_writer.py:12` — `KEY_PATH = ...config/bluemarlin-calendar-key.json`

The first and third are worse than just-a-stale-path: they actively **overwrite** the docker-compose env var. Both `gws_calendar._run_gws()` (line 30) and `sheets_writer._append()` (line 38) do:

```python
env = os.environ.copy()
env['GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE'] = _KEY_PATH
```

This overrides whatever value was set in the container's environment. Even though docker-compose correctly sets `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/calendar-key.json`, the Python code clobbers it with the broken path before invoking `gws`. Result: gws subprocess looks for `/app/config/bluemarlin-calendar-key.json` (which does not exist in the current image), authentication fails, every Sheets append and Calendar hold/manifest call has been silently failing since Brief 145 was deployed.

**This bug is currently active in production.** Verified by inspecting BlueMarlin's container logs:

```
sheets_writer: _append error (All Events): {
  "error": {
    "message": "Authentication failed: GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE points to
    /app/config/bluemarlin-calendar-key.json, but file does not exist"
```

We didn't notice because the live test traffic since Brief 145 hasn't completed any booking flows that hit `sheets_writer.append_booking()` or `gws_calendar.create_manifest_event()`. Read paths that go through `gws_calendar` (availability checks) are also broken — we just haven't hit them yet.

This brief fixes ONLY the hardcoded path bug. The architectural cleanup (`.dockerignore` + directory mounts) is deferred to Brief 148, which depends on this fix landing first.

---

## Why This Approach

**Alternative considered: hardcode the new filename `calendar-key.json` in all three files.** Rejected. Hardcoding the new name still leaves the bug shape (a string in the source code that has to be kept in sync with whatever the deploy infrastructure uses). The next time the file is renamed, the same bug repeats.

**Alternative considered: leave the OLD-named file in place via a symlink (`bluemarlin-calendar-key.json` → `calendar-key.json`).** Rejected. Hides the problem, makes future debugging harder, and doesn't fix the env-var override that's actively defeating docker-compose.

**Chosen approach: read the path from `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` env var with a sensible default that matches the new filename.** This:
- Honors the docker-compose `environment:` block when set (the intended design)
- Falls back to the new filename if no env var is set (works for local dev / unit tests)
- Stops overwriting the env var with the hardcoded value
- Future renames only need to touch docker-compose.yml, not source code

**Tradeoff accepted:** the default fallback path still hardcodes a filename. That's fine — it's a default, the env var wins. The fallback is only used if someone runs `gws_calendar` outside Docker without setting the env var.

---

## Source Material

### Current `gws_calendar.py` (lines 13-42, the relevant section)

```python
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_KEY_PATH = os.path.normpath(os.path.join(_MODULE_DIR, '..', '..', 'config', 'bluemarlin-calendar-key.json'))

_CURACAO_TZ = timezone(timedelta(hours=-4))


def _curacao_to_iso(date_str: str, time_str: str) -> str:
    """Convert YYYY-MM-DD HH:MM in Curaçao time (UTC-4, no DST) to UTC ISO 8601 string."""
    year, month, day = map(int, date_str.split('-'))
    hour, minute = map(int, time_str.split(':'))
    dt = datetime(year, month, day, hour, minute, tzinfo=_CURACAO_TZ)
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _run_gws(args: list) -> dict:
    """Run gws CLI with given args. Returns parsed JSON dict or {'error': str}."""
    env = os.environ.copy()
    env['GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE'] = _KEY_PATH
    try:
        r = subprocess.run(
            ['gws'] + args,
            capture_output=True, text=True, timeout=30,
            env=env
        )
        ...
```

### Current `format_sheets.py` (lines 14-32, the relevant section)

```python
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_PATH = os.path.normpath(os.path.join(_MODULE_DIR, '..', '..', 'config', 'bluemarlin-calendar-key.json'))
_SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


def _get_spreadsheet_id() -> str:
    ...


def _get_service():
    try:
        creds = Credentials.from_service_account_file(KEY_PATH, scopes=_SCOPES)
        return build('sheets', 'v4', credentials=creds)
    except Exception as e:
        print(f"format_sheets: service init error: {e}")
        return None
```

`format_sheets.py` uses `Credentials.from_service_account_file(KEY_PATH, ...)` directly via the Google Python SDK — it does NOT shell out to `gws`. So the env var trick doesn't apply to it. Solution: have it read from the env var explicitly with the new-name fallback.

### Current `sheets_writer.py` (lines 11-50, the relevant section)

```python
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_PATH = os.path.normpath(os.path.join(_MODULE_DIR, '..', '..', 'config', 'bluemarlin-calendar-key.json'))


def _get_spreadsheet_id() -> str:
    ...


def _append(tab_name: str, row: list) -> None:
    spreadsheet_id = _get_spreadsheet_id()
    params = json.dumps({...})
    body = json.dumps({'values': [row]})
    env = os.environ.copy()
    env['GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE'] = KEY_PATH
    try:
        r = subprocess.run(
            ['gws', 'sheets', 'spreadsheets', 'values', 'append', ...],
            capture_output=True, text=True, timeout=30,
            env=env
        )
        ...
```

### Production error (verified inside running container)

```
$ ssh root@108.61.192.52 "docker exec bluemarlin-default tail -20 /app/logs/email_poller.log | grep -iE 'gws|calendar|error|key'"

sheets_writer: _append error (All Events): {
  "error": {
    "message": "Authentication failed: GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE points to
    /app/config/bluemarlin-calendar-key.json, but file does not exist"
```

### docker-compose.yml `environment:` block (current, line 10-11)

```yaml
environment:
  - GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/calendar-key.json
```

This is correctly set. The Python code is what's clobbering it.

### Container env verification (current state)

```
$ ssh root@108.61.192.52 "docker exec bluemarlin-default env | grep CREDENTIAL"
GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/calendar-key.json
```

The env var IS set correctly. The bug is purely in the Python code overwriting it.

### Inside-container file existence check (current state)

```
$ ssh root@108.61.192.52 "docker exec bluemarlin-default ls -la /app/config/bluemarlin-calendar-key.json /app/config/calendar-key.json"
ls: cannot access '/app/config/bluemarlin-calendar-key.json': No such file or directory
-rw-r--r-- 1 root root 2393 Mar  8 00:29 /app/config/calendar-key.json
```

Confirms: only the new-named file exists in the container. Old name does not.

---

## Instructions

### Step 1 — Fix `gws_calendar.py`

In `bluemarlin/agents/marina/gws_calendar.py`, replace:

```python
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_KEY_PATH = os.path.normpath(os.path.join(_MODULE_DIR, '..', '..', 'config', 'bluemarlin-calendar-key.json'))
```

with:

```python
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_KEY_PATH = os.path.normpath(os.path.join(_MODULE_DIR, '..', '..', 'config', 'calendar-key.json'))
_KEY_PATH = os.environ.get('GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE', _DEFAULT_KEY_PATH)
```

Then in `_run_gws()` at line 30, the existing line:

```python
env['GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE'] = _KEY_PATH
```

stays AS-IS. The semantic is now: pass through the env var if it's set, otherwise use the new-name default. The line still propagates the value to the subprocess; it just no longer overrides a correct value with a broken one.

### Step 2 — Fix `format_sheets.py`

In `bluemarlin/agents/marina/format_sheets.py`, replace:

```python
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_PATH = os.path.normpath(os.path.join(_MODULE_DIR, '..', '..', 'config', 'bluemarlin-calendar-key.json'))
```

with:

```python
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_KEY_PATH = os.path.normpath(os.path.join(_MODULE_DIR, '..', '..', 'config', 'calendar-key.json'))
KEY_PATH = os.environ.get('GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE', _DEFAULT_KEY_PATH)
```

`_get_service()` at line 31 reads `KEY_PATH` directly via `Credentials.from_service_account_file(KEY_PATH, ...)`. No other change needed there — once `KEY_PATH` is correct at module-load time, the function works.

### Step 3 — Fix `sheets_writer.py`

In `bluemarlin/agents/marina/sheets_writer.py`, replace:

```python
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_PATH = os.path.normpath(os.path.join(_MODULE_DIR, '..', '..', 'config', 'bluemarlin-calendar-key.json'))
```

with:

```python
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_KEY_PATH = os.path.normpath(os.path.join(_MODULE_DIR, '..', '..', 'config', 'calendar-key.json'))
KEY_PATH = os.environ.get('GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE', _DEFAULT_KEY_PATH)
```

The `_append()` function at line 38 already does `env['GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE'] = KEY_PATH`, which is now correct (passes through the env var or the new-name default).

### Step 4 — Write the tests

Create `bluemarlin/tests/marina/test_147_gws_key_path.py` with these tests. Each test must use `monkeypatch.setenv` and `importlib.reload` to defeat the module-level constant caching, since these constants are computed at import time.

1. `test_gws_calendar_uses_env_var_when_set` — set `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/tmp/sentinel-path.json`, reload `gws_calendar`, assert `gws_calendar._KEY_PATH == "/tmp/sentinel-path.json"`.

2. `test_gws_calendar_uses_new_filename_default_when_env_var_unset` — delete the env var (`monkeypatch.delenv(... raising=False)`), reload `gws_calendar`, assert `gws_calendar._KEY_PATH` ends with `calendar-key.json` AND does NOT contain `bluemarlin-calendar-key.json`.

3. `test_format_sheets_uses_env_var_when_set` — same pattern with `format_sheets.KEY_PATH`.

4. `test_format_sheets_uses_new_filename_default` — same pattern asserting new filename.

5. `test_sheets_writer_uses_env_var_when_set` — same pattern with `sheets_writer.KEY_PATH`.

6. `test_sheets_writer_uses_new_filename_default` — same pattern.

7. `test_run_gws_does_not_clobber_env_var` — this is the critical regression test. Create a fake `subprocess.run` that captures the `env` dict it was called with. Set `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/tmp/sentinel-from-compose.json` in the test env. Reload `gws_calendar`. Call `gws_calendar._run_gws(['stub-command'])`. Assert that the captured env's `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` equals `/tmp/sentinel-from-compose.json` (NOT some other path that the code might have clobbered it with). This test is what would have caught the original bug.

8. `test_sheets_writer_append_does_not_clobber_env_var` — same pattern as test 7, but for `sheets_writer._append('Test', ['row'])`. Stub out subprocess and assert env var passthrough.

9. `test_old_filename_not_referenced_in_source` — read all three source files as text, assert `bluemarlin-calendar-key.json` does NOT appear anywhere in them. Guards against future regressions where someone reintroduces the hardcoded old name.

Test file structure: use `pytest`'s `monkeypatch` fixture and `importlib.reload`. Each test that touches a module's constants should reload that module after setting/clearing env vars to defeat the cache. Tests 7 and 8 should monkeypatch `subprocess.run` (in the module under test) to a function that records its arguments to a list captured by closure.

### Step 5 — Run tests locally

```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin
python3 -m pytest tests/marina/test_147_gws_key_path.py -v
```

All 9 tests must pass. Then run full suite:

```bash
python3 -m pytest tests/ -q --tb=no
```

Expected: 656 + 9 = 665 total. Same 7 pre-existing failures unchanged. Zero new failures.

### Step 6 — Commit and push

```bash
git add -A
git commit -m "Brief 147 — Fix gws hardcoded calendar key path (production bug from Brief 145)"
git push
```

### Step 7 — Deploy to VPS

```bash
ssh root@108.61.192.52 "cd /root && git pull && docker compose down && docker compose build && docker compose up -d"
ssh root@108.61.192.52 "sleep 10 && docker compose ps && curl -s http://localhost:8001/health"
```

Expected: container `bluemarlin-default` running, `{"status":"ok"}`.

### Step 8 — Verify the env var is no longer being clobbered

```bash
ssh root@108.61.192.52 "docker exec bluemarlin-default python3 -c 'from agents.marina import gws_calendar, format_sheets, sheets_writer; print(\"gws_calendar._KEY_PATH:\", gws_calendar._KEY_PATH); print(\"format_sheets.KEY_PATH:\", format_sheets.KEY_PATH); print(\"sheets_writer.KEY_PATH:\", sheets_writer.KEY_PATH)'"
```

Expected output (all three should match `/app/config/calendar-key.json` because the env var is set in the container):

```
gws_calendar._KEY_PATH: /app/config/calendar-key.json
format_sheets.KEY_PATH: /app/config/calendar-key.json
sheets_writer.KEY_PATH: /app/config/calendar-key.json
```

If any of these still says `bluemarlin-calendar-key.json`, the fix didn't apply or the deploy didn't pick up the new code.

### Step 9 — Verify the gws auth errors stop appearing

```bash
ssh root@108.61.192.52 "docker exec bluemarlin-default tail -50 /app/logs/email_poller.log | grep -iE 'sheets_writer.*error|gws.*error|Authentication failed' || echo 'NO RECENT GWS ERRORS'"
```

Expected: `NO RECENT GWS ERRORS`. If errors are still present, they may be old log lines from before the rebuild — wait 30 seconds and re-check. If they keep appearing, the fix isn't working in the live container.

### Step 10 — Trigger a real Sheets write to confirm

The most reliable verification: trigger an action that calls `sheets_writer._append()` and confirm it succeeds. Send a test email to `marina@wetakeyourjob.com` (from `butlerbensonagent@gmail.com` or any other personal address) with subject "Brief 147 verification" and body "test". The email_poller will pick it up, route through marina_agent, and depending on the flow, will at minimum write to the All Events sheet.

After ~60 seconds:

```bash
ssh root@108.61.192.52 "docker exec bluemarlin-default tail -30 /app/logs/email_poller.log | grep -iE 'sheets_writer'"
```

Expected: a `sheets_writer` log line that does NOT contain `error`, `Authentication failed`, or `does not exist`. If you see a successful append (or no error at all), Brief 147 is verified.

If the email-test isn't practical, the env-var verification in Step 8 plus the absence of errors in Step 9 is sufficient confidence.

---

## Tests

See Step 4. Nine tests in `bluemarlin/tests/marina/test_147_gws_key_path.py`:

- 6 module-constant tests (3 modules × 2 cases: env-var-set, env-var-unset)
- 2 env-var-passthrough regression tests (the actual bug guard)
- 1 source-text scan test (no occurrences of the old filename in any of the three files)

Test 7 (`test_run_gws_does_not_clobber_env_var`) is the most important — it's the test that, if it had existed when Brief 145 was written, would have caught this bug immediately.

---

## Success Condition

Inside the running BlueMarlin container, all three source files report `_KEY_PATH` (or `KEY_PATH`) equal to `/app/config/calendar-key.json` (the value docker-compose sets), AND the email_poller log shows zero new gws Authentication-failed errors after the rebuild, AND a real Sheets write succeeds (verified via email round-trip in Step 10 OR explicitly confirmed via no-error in Step 9).

---

## Rollback

**If the rebuild breaks BlueMarlin worse than it currently is:**

```bash
ssh root@108.61.192.52 "cd /root && git revert HEAD && docker compose down && docker compose build && docker compose up -d"
```

Returns to the current broken state (gws still failing, but at least everything else still runs).

**If tests fail locally before deployment:**

Don't deploy. Fix the test or the code, re-run tests until green.

**If Step 8 verification shows _KEY_PATH still wrong inside the container:**

Probable causes: Docker layer cache, git push didn't include the change, or wrong code on VPS. Diagnose by `git log` on the VPS and inspecting the file directly via `docker exec bluemarlin-default cat /app/agents/marina/gws_calendar.py | head -20`.
