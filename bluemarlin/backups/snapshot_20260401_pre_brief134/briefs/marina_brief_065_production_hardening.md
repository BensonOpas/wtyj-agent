# BRIEF 065 — Production Hardening: Rate Limiting, Thread Cleanup, Monitoring, OAuth Auto-Refresh
**Status:** Draft | **Files:** `src/email_poller.py`, `src/marina_agent.py`, `briefs/MARINA_STATUS.md` | **Depends on:** 064 | **Blocks:** —

## Context

Marina is 90% done with zero functional bugs across 50 live E2E scenarios. Four gaps remain between "demo" and "production-ready":
1. No per-sender rate limiting — someone can trigger unlimited Claude API calls with different subjects
2. Thread state JSON grows unbounded — threads are never deleted
3. No API cost visibility, no health checks, no error alerting
4. OAuth refresh token auto-rotation not implemented — token expiry kills the poller

## Why This Approach

All four fixes are localized to existing files with no architectural changes. Rate limiting uses the existing thread state JSON (no new DB tables) because sender rates are ephemeral — they don't need durability. Thread cleanup archives before deleting for audit trail. Monitoring reads data already available (response.usage) rather than adding new API calls. OAuth auto-refresh saves the rotated token that Microsoft already returns — we're just not reading it.

Multi-operator routing was considered but deferred — single-operator works for the demo, and routing logic would add complexity to the relay flow without immediate need.

## Source Material

### Current oauth_token() (email_poller.py lines 114-124):
```python
def oauth_token(scope: str) -> str:
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "refresh_token": get_refresh_token(),
        "grant_type": "refresh_token",
        "scope": scope
    }).encode()
    resp = json.loads(urllib.request.urlopen(
        urllib.request.Request(f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token", data)
    ).read())
    return resp["access_token"]
```

### Current main loop error handling (email_poller.py lines 1108-1113):
```python
        im.logout()

    except Exception as ex:
        log(f"Error: {ex}")

    time.sleep(POLL_INTERVAL)
```

### Current Claude API call (marina_agent.py lines 380-386):
```python
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()
```

### Constants area (email_poller.py lines 56-69):
```python
# Anti-loop: max replies per thread within window
MAX_REPLIES_PER_THREAD = 10
REPLY_WINDOW_SECONDS = 60 * 60

_BOOKING_INTENTS = {"booking", "reschedule"}

_SYSTEM_EMAIL_PREFIXES = (
    "noreply@", "no-reply@", "no_reply@", "do-not-reply@", "donotreply@",
    "mailer-daemon@", "postmaster@", "bounce@",
)
```

## Instructions

### Step 1: Add constants to email_poller.py (after line 58)

Insert after `REPLY_WINDOW_SECONDS = 60 * 60`:

```python

# Per-sender rate limit (cross-thread)
# 20/hr is generous: a real customer doing multi-trip + questions tops out at ~10.
# Matches the per-thread limit (10) doubled to allow multi-thread legitimate use.
SENDER_RATE_LIMIT = 20
SENDER_RATE_WINDOW = 3600  # 1 hour, same window as per-thread anti-loop

# Thread cleanup — 30 days covers the longest booking-to-trip cycle.
# Booking data survives in SQLite bookings table; this only prunes conversation state.
THREAD_RETENTION_DAYS = 30
ARCHIVE_PATH = os.path.join(_CONFIG_DIR, "archived_threads.jsonl")
HEARTBEAT_PATH = os.path.join(_CONFIG_DIR, "heartbeat.txt")

# Error alerting — 3 consecutive errors ≈ 90 seconds of failures (3 × 30s poll).
# One-off exceptions are normal (network hiccup); sustained failure warrants alert.
_ERROR_ALERT_THRESHOLD = 3
```

### Step 2: Replace oauth_token() (email_poller.py lines 114-124)

Replace the entire function with:

```python
def oauth_token(scope: str) -> str:
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "refresh_token": get_refresh_token(),
        "grant_type": "refresh_token",
        "scope": scope
    }).encode()
    try:
        resp = json.loads(urllib.request.urlopen(
            urllib.request.Request(f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token", data)
        ).read())
    except Exception as e:
        log(f"OAuth token request failed: {e}")
        raise
    if "refresh_token" in resp:
        try:
            with open(REFRESH_TOKEN_PATH, "w") as f:
                f.write(resp["refresh_token"])
        except Exception as e:
            log(f"Failed to save new refresh token: {e}")
    if "access_token" not in resp:
        log(f"OAuth response missing access_token: {resp.get('error', 'unknown')}")
        raise RuntimeError(f"OAuth failed: {resp.get('error_description', 'no access_token')}")
    return resp["access_token"]
```

### Step 3: Add _cleanup_stale_data() function (email_poller.py, after the normalize_subject function, ~line 110)

```python
def _cleanup_stale_data(state, now):
    """Prune threads >30d old (no active hold) and trim processed_hashes."""
    cutoff = now - (THREAD_RETENTION_DAYS * 86400)
    threads = state.get("threads", {})
    to_delete = []
    for tk, th in threads.items():
        last = th.get("last_activity") or 0
        if last < cutoff and not th.get("flags", {}).get("hold_created"):
            to_delete.append(tk)
    if to_delete:
        with open(ARCHIVE_PATH, "a", encoding="utf-8") as f:
            for tk in to_delete:
                f.write(json.dumps({"archived_at": now, "thread_key": tk, "data": threads[tk]}, ensure_ascii=False) + "\n")
                del threads[tk]
        log(f"Archived {len(to_delete)} stale threads (>{THREAD_RETENTION_DAYS}d)")
    # Prune processed_hashes by count (keep last 5000)
    try:
        conn = state_registry._get_conn()
        count = conn.execute("SELECT count(*) FROM processed_hashes").fetchone()[0]
        if count > 5000:
            conn.execute("DELETE FROM processed_hashes WHERE rowid NOT IN (SELECT rowid FROM processed_hashes ORDER BY rowid DESC LIMIT 5000)")
            conn.commit()
            log(f"Pruned processed_hashes: {count} -> 5000")
        conn.close()
    except Exception:
        pass
    # Prune sender_rates
    sr = state.get("sender_rates", {})
    for em in list(sr.keys()):
        sr[em] = [t for t in sr[em] if now - t <= SENDER_RATE_WINDOW]
        if not sr[em]:
            del sr[em]
```

### Step 4: Add sender rate limiting (email_poller.py, after system email filter at line 475, before BM-003 dedup)

Insert after the `continue` on line 475 (system email skip), before the BM-003 comment on line 477:

```python

                # Per-sender rate limit (cross-thread)
                _sr = state.setdefault("sender_rates", {})
                _sr_times = _sr.get(from_email.lower(), [])
                _sr_times = [t for t in _sr_times if now - t <= SENDER_RATE_WINDOW]
                if len(_sr_times) >= SENDER_RATE_LIMIT:
                    log(f"Sender rate limit hit for {from_email}: {len(_sr_times)} emails in window")
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    _sr[from_email.lower()] = _sr_times
                    save_json(THREAD_STATE_PATH, state)
                    continue
                _sr_times.append(now)
                _sr[from_email.lower()] = _sr_times

```

Important: `now` is defined later at line 497 (`now = int(time.time())`), but the sender rate limit runs before that. Insert `now = int(time.time())` as the first line inside the `for uid in uids:` loop, before the fetch call at line 459. The existing `now = int(time.time())` at line 497 can stay — reassigning the same value is harmless.

### Step 5: Add cleanup call and heartbeat (email_poller.py main loop)

**5a.** After `state.setdefault("message_id_index", {})` (line 447), add:
```python
    _consecutive_errors = 0
    _error_alert_sent = False
```

**5b.** At the start of the try block, after `im = imap_connect()` and before `im.select(MAILBOX)` (line 451-452), add cleanup call:
```python
            _cleanup_stale_data(state, int(time.time()))
```

**5c.** After `im.logout()` (line 1108), before the except block, add heartbeat:
```python
            # Heartbeat — write timestamp for external monitoring
            try:
                with open(HEARTBEAT_PATH, "w") as f:
                    f.write(str(int(time.time())))
            except Exception:
                pass
```

**5d.** Replace the error handling block (lines 1110-1113):
```python
        except Exception as ex:
            _consecutive_errors += 1
            log(f"Error: {ex}")
            if _consecutive_errors >= _ERROR_ALERT_THRESHOLD and not _error_alert_sent:
                try:
                    smtp_send(demo_support_email,
                        f"[ALERT] Marina poller: {_consecutive_errors} consecutive errors",
                        f"Latest error: {ex}\n\nCheck journalctl -u bluemarlin")
                    _error_alert_sent = True
                except Exception:
                    pass
        else:
            _consecutive_errors = 0
            _error_alert_sent = False

        time.sleep(POLL_INTERVAL)
```

Note the `else` clause on try/except — it runs only when no exception occurred, resetting the counters on success.

### Step 6: Token usage logging (marina_agent.py)

**6a.** Add `import bm_logger` after the existing `import config_loader` (line 16). Insert:
```python
import bm_logger
```

**6b.** After `raw = response.content[0].text.strip()` (line 386), insert:

```python

        # Log API token usage
        _usage = getattr(response, "usage", None)
        if _usage:
            bm_logger.log("api_usage",
                input_tokens=_usage.input_tokens,
                output_tokens=_usage.output_tokens,
                model="claude-sonnet-4-6")

```

### Step 7: Update file headers

- email_poller.py line 4: change `Brief 064` to `Brief 065`
- marina_agent.py line 4: change `Brief 064` to `Brief 065`

### Step 8: Note multi-operator in MARINA_STATUS.md

In `briefs/MARINA_STATUS.md`, in the "Production-Grade Items" table, change the multi-operator row to say "Deferred — noted for future brief when client needs it."

## Tests

Create `tests/test_065_production_hardening.py`:

### T1: Sender over rate limit → skipped
Create sender_rates with 20 timestamps (all within last 3600s) for `"spam@test.com"`. Call the rate-limit check logic. Assert: log message contains `"Sender rate limit hit"` and `"spam@test.com"`.

### T2: Sender under rate limit → processed
Create sender_rates with 5 timestamps for `"legit@test.com"`. Assert: rate-limit check does NOT trigger (len < 20). Assert: timestamp list grows to 6 after appending.

### T3: Thread >30d, no hold → archived and deleted
Create state with thread key `"test_old"`, `last_activity = now - 31*86400`, `flags = {}`. Run `_cleanup_stale_data(state, now)`. Assert: `"test_old"` not in `state["threads"]`.

### T4: Thread >30d, hold_created=True → preserved
Create state with thread key `"test_hold"`, `last_activity = now - 31*86400`, `flags = {"hold_created": True}`. Run cleanup. Assert: `"test_hold"` still in `state["threads"]`.

### T5: Thread <30d → preserved
Create state with thread key `"test_recent"`, `last_activity = now - 10*86400`. Run cleanup. Assert: `"test_recent"` still in `state["threads"]`.

### T6: Archive file contains correct JSON
After T3, read ARCHIVE_PATH. Parse last line as JSON. Assert: `parsed["thread_key"] == "test_old"`. Assert: `"archived_at"` key present. Assert: `"data"` key present and contains the original thread data.

### T7: OAuth saves new refresh token
Mock `urllib.request.urlopen` to return `{"access_token": "at_123", "refresh_token": "rt_new_456"}`. Call `oauth_token("test_scope")`. Read REFRESH_TOKEN_PATH. Assert: file content == `"rt_new_456"`. Assert: return value == `"at_123"`.

### T8: OAuth raises on missing access_token
Mock `urllib.request.urlopen` to return `{"error": "invalid_grant", "error_description": "token expired"}`. Call `oauth_token("test_scope")`. Assert: raises `RuntimeError`. Assert: exception message contains `"token expired"`.

### T9: Token usage logged
Mock `bm_logger.log` and a response object with `usage.input_tokens = 1500` and `usage.output_tokens = 200`. Run the logging code. Assert: `bm_logger.log` called with `event="api_usage"`, `input_tokens=1500`, `output_tokens=200`, `model="claude-sonnet-4-6"`.

### T10: Heartbeat file written
Write to HEARTBEAT_PATH in a temp dir. Assert: file exists. Assert: content is a valid integer. Assert: `abs(int(content) - int(time.time())) < 5`.

### T11: 3 consecutive errors → alert sent
Mock `smtp_send`. Simulate 3 increments of `_consecutive_errors`. Assert: `smtp_send` called once. Assert: first arg == `demo_support_email`. Assert: second arg starts with `"[ALERT]"`.

### T12: Error then success → counter reset
Set `_consecutive_errors = 1`, `_error_alert_sent = False`. Simulate success (the else branch). Assert: `_consecutive_errors == 0`. Assert: `_error_alert_sent == False`.

## Success Condition

All 12 tests pass. Regression tests (test_046, test_048, test_064) still pass. No new drift violations beyond the 8 pre-existing accepted ones.

## Rollback

Revert email_poller.py and marina_agent.py to Brief 064 versions. Delete test_065 file. No schema changes to roll back.
