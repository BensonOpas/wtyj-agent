# OUTPUT 071 — WhatsApp Escalation: Semi + Full + Fully-Escalated Guard

**Brief:** marina_brief_071_whatsapp_escalation.md
**Status:** Complete
**Date:** 2026-03-11

## What Was Done

### Step 1 — Modified `agents/social/social_agent.py`
- Updated header to Brief 071, added `import json` and `import uuid`
- Added fully-escalated guard (early return before Step 1): filters relay flags, calls marina_agent with filtered flags, returns holding reply, skips entire booking flow
- Added relay flag filtering before Step 2: creates `agent_flags` dict without `awaiting_relay`, `relay_token`, `relay_question` — prevents RELAY MODE prompt injection on normal messages
- Changed marina_agent call to use `agent_flags` instead of raw `flags`
- Added Step 7.5 (semi-escalation handler): cancels soft hold, resets slot flags, clears awaiting_booking_confirmation, generates relay token, sets relay flags, overrides reply_text with Claude's holding reply, logs to Sheets + bm_logger
- Added Step 7.6 (full escalation handler): cancels soft hold, resets slot flags, sets fully_escalated, clears awaiting_booking_confirmation, overrides reply_text, logs to Sheets + bm_logger
- Added `_skip_booking` guard around Step 8 (booking confirmation)
- File grew from ~410 lines to ~498 lines

### Step 2 — Created `tests/social/test_071_whatsapp_escalation.py`
8 tests:
1. `test_fully_escalated_guard_returns_holding_reply` — pre-set fully_escalated, verify holding reply returned
2. `test_fully_escalated_guard_filters_relay_flags` — verify relay flags removed before marina_agent call, fully_escalated preserved
3. `test_semi_escalation_sets_relay_state` — verify relay flags set, Claude's reply used, Sheets logged
4. `test_semi_escalation_cancels_soft_hold` — pre-set hold, verify cancelled + remove_from_manifest called
5. `test_semi_escalation_overrides_post_validate` — booking intents + semi_escalation: reply is holding reply, not summary
6. `test_full_escalation_sets_flag_and_logs` — verify fully_escalated set, Sheets logged with correct intent
7. `test_full_escalation_skips_booking_confirmation` — booking fields + requires_human: no booking_ref, hold cancelled
8. `test_relay_flags_filtered_for_normal_message` — pre-set relay flags, verify filtered before marina_agent call

### Bonus fix — `tests/social/conftest.py`
- Fixed pre-existing test isolation bug: `test_067_webhook.py` only set `WHATSAPP_VERIFY_TOKEN` before importing `webhook_server` (which imports `whatsapp_client`), causing `_PHONE_NUMBER_ID` to be cached as empty. Added `setdefault` for all 3 WhatsApp env vars in conftest.py so they're available before any module import.

## Test Results

```
Brief 071:  8/8  passed
Brief 070: 16/16 passed (regression)
Brief 069: 17/17 passed (regression)
Brief 068: 10/10 passed (regression — includes conftest fix)
Brief 067:  7/7  passed (regression)
Total:     58/58 passed
```

## Anything Unexpected

- **Pre-existing test_068 failure**: Running all social tests together exposed a test isolation bug from Brief 067 — `conftest.py` didn't set `WHATSAPP_ACCESS_TOKEN` or `WHATSAPP_PHONE_NUMBER_ID`, so when test_067 imported `webhook_server` → `whatsapp_client`, the module-level `_PHONE_NUMBER_ID` was cached as empty. This caused `test_068::test_send_text_message_success` to fail with an empty phone number in the URL. Fixed by adding `setdefault` calls in conftest.py. This is outside the brief's scope but necessary for the full suite to pass.
- **Cleanup function fix**: The initial cleanup function referenced a non-existent `soft_holds` table. The actual table is `trip_bookings` (soft holds are stored with `status='soft_hold'`). Removed the incorrect DELETE statement — the existing `trip_bookings` cleanup covers it.
