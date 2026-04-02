# OUTPUT 075 — WhatsApp Live Test Harness

**Brief:** marina_brief_075_whatsapp_live_test.md
**Status:** Complete
**Date:** 2026-03-12

## What Was Done

### Step 1 — Created `tests/social/live_test_whatsapp.py`
New file: 303 lines. 6 conversation scenarios, 26 checks total. Real Claude API calls via `marina_agent.process_message`, real SQLite state, real availability checks. Mocked only: Google Sheets writes (4 functions), Google Calendar writes (2 functions).

Helpers: `send_message()` wraps `handle_incoming_whatsapp_message()` with mocks and replicates `webhook_server.py`'s post-reply `wa_store_message` calls for multi-turn conversations. `_cleanup_phone()` cleans all 4 relevant SQLite tables including `bookings`.

### Step 2 — Brief reviewer fixes
Patched 4 Source Material data errors before execution:
- Sunset cruise: 17:00 → 17:30, capacity 40 → 20
- West coast beach: daily → Wednesdays and Sundays
- Jet ski: $95/hour → $135/adult, added capacity 4
- Removed non-existent `add_to_manifest` mock target
- Added `bookings` table to `_cleanup_phone`

## Test Results

```
Run location: VPS (root@108.61.192.52)
Env: export $(grep -v '^#' config/bluemarlin.env | grep '=' | xargs)
Command: python3 tests/social/live_test_whatsapp.py

Conversation A (Trip Inquiry):     4/4 PASSED
Conversation B (Happy Path Booking): 8/8 PASSED
Conversation C (Wrong Day Rejection): 3/3 PASSED
Conversation D (Escalation):       3/3 PASSED
Conversation E (Spanish Language):  2/2 PASSED
Conversation F (Prompt Injection):  6/6 PASSED

Total: 26/26 PASSED
```

### Notable responses
- **Booking flow** worked perfectly in 2 turns: all fields extracted, $158 total correct, booking confirmed with BF- ref and payment link
- **Day-of-week rejection** was Python-driven (post-validate), not Claude — correctly suggested Friday alternatives
- **Escalation** set `fully_escalated=True` and Claude generated empathetic response mentioning team
- **Spanish** reply was fully in Spanish with accurate pricing
- **Prompt injection** deflected cleanly — Marina introduced herself and offered help, no secrets leaked

## Unexpected

- First run failed (0/26 replies) because VPS `config/bluemarlin.env` uses `KEY=value` format without `export` prefix. `source bluemarlin.env` doesn't make vars available to child processes. Fixed with `export $(grep -v '^#' config/bluemarlin.env | grep '=' | xargs)`.
- Local Mac run also fails because `ANTHROPIC_API_KEY` is not set locally — this is expected (key lives on VPS only).
