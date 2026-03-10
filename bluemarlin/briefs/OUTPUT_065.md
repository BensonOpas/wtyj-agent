# OUTPUT 065 — Production Hardening

**Status:** Complete
**Date:** 2026-03-10

## What Was Done

### Fix 1: Per-Sender Rate Limiting
- Added `SENDER_RATE_LIMIT = 20` and `SENDER_RATE_WINDOW = 3600` constants
- Added sender rate check after system email filter, before BM-003 dedup
- Added `now = int(time.time())` at top of `for uid in uids:` loop so rate limit has access to timestamp
- Tracks timestamps per sender in `state["sender_rates"]` dict
- Silent skip (mark Seen, no reply) when limit hit

### Fix 2: Thread State Cleanup
- Added `_cleanup_stale_data(state, now)` function after `normalize_subject()`
- Archives threads >30 days old (without active holds) to JSONL before deletion
- Prunes `processed_hashes` table to keep last 5000 rows
- Prunes expired `sender_rates` entries
- Called at top of each poll cycle after `imap_connect()`

### Fix 3: Monitoring
- **Token usage:** Added `import bm_logger` to marina_agent.py. After `response.content[0].text.strip()`, logs `api_usage` event with `input_tokens`, `output_tokens`, `model`
- **Heartbeat:** Writes current timestamp to `config/heartbeat.txt` after each successful poll cycle
- **Error alerting:** Tracks `_consecutive_errors` counter. After 3 consecutive failures, sends `[ALERT]` email via `smtp_send()`. Resets on success (`else` branch on try/except)

### Fix 4: OAuth Auto-Refresh
- Replaced `oauth_token()` with error-handling version
- Saves `resp["refresh_token"]` back to `REFRESH_TOKEN_PATH` when Microsoft returns one
- Raises `RuntimeError` with `error_description` if `access_token` missing
- Logs failures for debugging

### File Headers
- email_poller.py: `Brief 064` → `Brief 065`
- marina_agent.py: `Brief 064` → `Brief 065`

### MARINA_STATUS.md
- Updated Production-Grade Items table: rate limiting, cleanup, monitoring, OAuth all marked Done
- Multi-operator routing marked "Deferred — noted for future brief when client needs it"

## Files Modified
- `src/email_poller.py` — constants, _cleanup_stale_data(), oauth_token(), sender rate limit, heartbeat, error alerting
- `src/marina_agent.py` — bm_logger import + token usage logging (6 lines)
- `briefs/MARINA_STATUS.md` — production items table updated

## Files Created
- `tests/test_065_production_hardening.py` — 12 pytest tests

## Test Results

### Brief 065 Tests: 12/12 passed
```
test_sender_over_rate_limit PASSED
test_sender_under_rate_limit PASSED
test_old_thread_no_hold_archived PASSED
test_old_thread_with_hold_preserved PASSED
test_recent_thread_preserved PASSED
test_archive_file_json PASSED
test_oauth_saves_refresh_token PASSED
test_oauth_raises_on_missing_access_token PASSED
test_token_usage_logged PASSED
test_heartbeat_file_written PASSED
test_consecutive_errors_trigger_alert PASSED
test_error_then_success_resets_counter PASSED
```

### Regression Tests: All pass
- test_046_hybrid_state_machine: 28/28 passed
- test_048_human_speech_optimization: 19/19 passed
- test_064_hardening: 14/14 passed

## Anything Unexpected
None.
