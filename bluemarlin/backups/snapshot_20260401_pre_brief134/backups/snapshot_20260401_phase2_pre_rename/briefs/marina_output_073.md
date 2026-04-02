# OUTPUT 073 — WhatsApp Hardening: Stale Reset + Cleanup + Edge Case Tests

**Brief:** marina_brief_073_whatsapp_hardening.md
**Status:** Complete
**Date:** 2026-03-11

## What Was Done

### Step 1 — Modified `wa_get_booking_state` in `shared/state_registry.py`
- Added `last_activity` to SELECT query (4th column)
- Returns `last_activity: None` for fresh phones, ISO timestamp for existing state

### Step 2 — Added `wa_cleanup_stale_data` in `shared/state_registry.py`
- Deletes `whatsapp_threads` rows >30 days old
- Deletes `whatsapp_processed` rows >7 days old
- Returns `{threads_cleaned, processed_cleaned}` counts

### Step 3 — Updated state_registry.py header to Brief 073

### Step 4 — Added stale conversation reset to `agents/social/social_agent.py`
- Added `_STALE_CONVERSATION_SECONDS = 86400` constant
- Added `_maybe_reset_stale_conversation()` function after `_post_validate`:
  - Returns False if no last_activity or <24h since last activity
  - Archives booking to completed_bookings if hold_created
  - Resets fields (preserves _PERSISTENT_FIELDS)
  - Clears all booking flags, escalation flags, and rate-limit flags

### Step 5 — Called stale reset in `handle_incoming_whatsapp_message`
- Inserted after state load, before anti-loop guard
- Logs `whatsapp_stale_reset` event on reset

### Step 6 — Added periodic cleanup to `agents/social/webhook_server.py`
- Added `import time`, module-level `_last_cleanup_ts = 0`
- Added `_maybe_run_cleanup()` — hourly guard, calls `wa_cleanup_stale_data()`, logs if rows cleaned
- Called at start of `_process_whatsapp_event` before try block

### Step 7 — Updated file headers
- `social_agent.py`: Brief 072 → Brief 073
- `webhook_server.py`: Brief 069 → Brief 073

### Step 8 — Created `tests/social/test_073_whatsapp_hardening.py`
10 tests covering stale reset, data cleanup, and 4 edge cases.

### Regression fix — Updated `tests/social/test_069_whatsapp_agent.py`
- `test_wa_booking_state_fresh`: updated expected dict to include `last_activity: None`

## Test Results

```
Brief 073: 10/10 passed
Brief 072: 11/11 passed (regression)
Brief 071:  8/8  passed (regression)
Brief 070: 16/16 passed (regression)
Brief 069: 17/17 passed (regression, 1 fix applied)
Brief 068: 10/10 passed (regression)
Brief 067:  7/7  passed (regression)
Total:     79/79 passed
```

## Anything Unexpected

- **Test 7 initial failure**: The change detection test failed because post-validation re-triggered after the hold cancellation. When the customer changes the date (e.g., March 18 → March 25), change detection fires and cancels the old hold, but then all 4 required booking fields are still present with the new date, so `_post_validate` generates a new booking summary, sets `awaiting_booking_confirmation=True`, and Step 7 runs a new availability check + creates a new hold. Fix: also mocked `gws_calendar.check_availability` (returns unavailable) to prevent re-hold after change detection — same pattern as test_071's semi-escalation tests.

- **Test 069 regression**: `test_wa_booking_state_fresh` asserted exact dict equality without `last_activity`, which now appears in the return. Fixed by adding `"last_activity": None` to expected dict.
