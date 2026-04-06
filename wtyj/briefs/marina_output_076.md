# OUTPUT 076 — WhatsApp Message Debouncing + Rate Limit 50

## What Was Done

### Step 1 — Rate limit updated in social_agent.py
- Changed `_MAX_REPLIES_PER_HOUR` from 25 to 50 (line 32)
- Updated header to `Last modified: Brief 076`

### Step 2 — Debounce added to webhook_server.py
- Added `import threading`
- Added debounce constants: `_DEBOUNCE_SECONDS = 2.0`, `_MAX_BATCH_SECONDS = 5.0`
- Added per-phone buffer state: `_message_buffers`, `_buffer_lock`
- Rewrote `_process_whatsapp_event` to buffer messages instead of processing immediately
- Added `_buffer_message(msg)` — per-phone buffer with timer scheduling
- Added `_flush_buffer(phone)` — concatenates texts, processes as single message

### Step 3 — webhook_server.py header updated
- `Last modified: Brief 076`

### Step 4 — Created tests/social/test_076_debounce.py
7 tests:
1. `test_single_message_flush` — single message buffers and flushes correctly
2. `test_rapid_fire_batched` — 3 messages concatenated into one
3. `test_different_phones_separate` — phones isolated from each other
4. `test_flush_empty_noop` — non-existent phone is safe no-op
5. `test_rate_limit_50_blocks` — 50 reply_times blocks
6. `test_rate_limit_49_allows` — 49 reply_times allows
7. `test_batched_stores_combined_text` — combined text stored in thread history

Includes autouse `cleanup_buffers` fixture to cancel timers between tests.

### Step 5 — Updated test_072 anti-loop tests
- `test_anti_loop_blocks_after_limit`: `range(25)` → `range(50)`
- `test_anti_loop_allows_after_window`: `range(25)` → `range(50)`
- `test_anti_loop_blocks_fully_escalated`: `range(25)` → `range(50)`

### Step 6 — Updated test_074 rate limit tests
- `test_rate_limit_25_blocks` → `test_rate_limit_50_blocks`: `range(25)` → `range(50)`
- `test_rate_limit_24_allows` → `test_rate_limit_49_allows`: `range(24)` → `range(49)`

### Additional: Fixed regression in test_068 and test_069
Two integration tests (`test_webhook_post_triggers_pipeline`, `test_webhook_stores_conversation`) were affected by the debounce change — messages are now buffered with a timer instead of processed synchronously. Fixed by cancelling the timer and calling `_flush_buffer()` manually after the POST.

## Test Results
```
92 passed in 0.56s
```

All 92 social tests pass: 7 new (076) + 85 existing (067-074) including updated rate limit values.

## Anything Unexpected
- test_068 and test_069 integration tests broke because FastAPI TestClient's synchronous BackgroundTasks now only buffers the message (starts a threading.Timer) instead of processing it immediately. Fixed by manually flushing the buffer after the POST in both tests.
