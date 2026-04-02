# OUTPUT 074 — WhatsApp: Semi-Escalation Promotion + Rate Limit Bump

**Brief:** marina_brief_074_semi_escalation_ratelimit.md
**Status:** Complete
**Date:** 2026-03-12

## What Was Done

### Step 1 — Bumped rate limit
Changed `_MAX_REPLIES_PER_HOUR` from 15 to 25 in social_agent.py.

### Step 2 — Removed uuid import
Removed `import uuid` (only used for relay_token generation, no longer needed).

### Step 3 — Converted semi-escalation to full escalation
Replaced Step 7.5 in social_agent.py. When `result.get("semi_escalation")` is True:
- Still cancels any soft hold (same capacity leak prevention)
- Sets `flags["fully_escalated"] = True` instead of relay flags
- No `awaiting_relay`, `relay_token`, or `relay_question` stored in state
- Sheets intent changed from `"semi_escalation"` to `"semi_to_full_escalation"`
- Internal note includes relay question with "(no relay bridge)" prefix
- bm_logger event changed from `whatsapp_semi_escalation` to `whatsapp_semi_to_full`

### Step 4 — Updated file header
social_agent.py header: `Last modified: Brief 074`.

### Step 5 — Updated test_071 semi-escalation assertions
- Test 3: asserts `fully_escalated is True`, `awaiting_relay not in flags`, `relay_token not in flags`
- Test 4: asserts `fully_escalated is True` (was `awaiting_relay`)
- Test 5: asserts `fully_escalated is True` (was `awaiting_relay`)

### Step 6 — Updated test_072 anti-loop test data
- `test_anti_loop_blocks_after_limit`: `range(15)` → `range(25)`
- `test_anti_loop_allows_after_window`: `range(15)` → `range(25)`
- `test_anti_loop_blocks_fully_escalated`: `range(15)` → `range(25)`

### Step 7 — Created test_074_semi_ratelimit.py
6 new tests covering semi→full promotion and rate limit at 25.

## Test Results

```
tests/social/test_074_semi_ratelimit.py — 6/6 PASSED
tests/social/test_073_whatsapp_hardening.py — 10/10 PASSED (regression)
tests/social/test_072_whatsapp_multi_trip.py — 11/11 PASSED (3 updated, regression)
tests/social/test_071_whatsapp_escalation.py — 8/8 PASSED (3 updated, regression)
tests/social/test_070_whatsapp_booking.py — 16/16 PASSED (regression)
tests/social/test_069_whatsapp_agent.py — 17/17 PASSED (regression)
tests/social/test_068_pipeline.py — 10/10 PASSED (regression)
tests/social/test_067_webhook.py — 7/7 PASSED (regression)
Total: 85/85 PASSED
```

## Unexpected

Nothing unexpected. Clean execution.
