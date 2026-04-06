# OUTPUT 072 — WhatsApp: Multi-Trip Reset, Returning Customer, Anti-Loop

**Brief:** marina_brief_072_whatsapp_multi_trip_returning_antiloop.md
**Status:** Complete
**Date:** 2026-03-11

## What Was Done

### Step 1 — Modified `agents/social/social_agent.py`
- Updated header to Brief 072, added `import re`
- Added constants: `_MAX_REPLIES_PER_HOUR = 15`, `_REPLY_WINDOW_SECONDS = 3600`
- Added anti-loop guard after state load: filters reply_times to 1hr window, returns empty string if count >= 15, saves state before returning
- Added `reply_times` to both `_esc_flags` and `agent_flags` filter lists (prevents leaking internal state to marina_agent prompt)
- Added reply_times recording + `wa_save_booking_state` to fully-escalated guard's early return path (anti-loop works on escalated threads)
- Added returning customer detection (booking ref regex + phone-based lookup) with dual-set to both `flags` and `agent_flags`
- Added completed bookings injection into `agent_flags` (summary + max_bookings_reached)
- Added multi-trip reset after marina_agent call, before field merge: archives booking, clears fields (preserves persistent), clears booking flags
- Added one-shot flag clearing (`unknown_ref`) after marina_agent call
- Added reply timestamp recording before final state persistence
- File grew from ~498 lines to ~597 lines

### Step 2 — Created `tests/social/test_072_whatsapp_multi_trip.py`
11 tests:
1. `test_multi_trip_reset_archives_booking` — pre-set completed booking, verify archived + fields/flags reset
2. `test_multi_trip_max_bookings_no_reset` — 3 completed bookings (max), verify no reset
3. `test_returning_customer_by_ref` — booking ref in message, verify flags + fields pre-populated + marina_agent sees it
4. `test_returning_customer_unknown_ref` — unknown ref, verify marina_agent sees it, cleared after call
5. `test_returning_customer_by_phone` — phone-based lookup, verify `_past_customer_bookings` in agent_flags
6. `test_anti_loop_blocks_after_limit` — 15 recent timestamps, verify empty reply + no marina_agent call
7. `test_anti_loop_allows_after_window` — 15 old timestamps (2hrs ago), verify pruned + call proceeds
8. `test_reply_times_recorded` — fresh phone, verify 1 timestamp recorded after reply
9. `test_reply_times_not_in_agent_flags` — verify reply_times filtered from marina_agent flags
10. `test_completed_bookings_summary_in_agent_flags` — verify summary with booking_ref injected
11. `test_anti_loop_blocks_fully_escalated` — fully_escalated + rate limited, verify anti-loop fires first

## Test Results

```
Brief 072: 11/11 passed
Brief 071:  8/8  passed (regression)
Brief 070: 16/16 passed (regression)
Brief 069: 17/17 passed (regression)
Brief 068: 10/10 passed (regression)
Brief 067:  7/7  passed (regression)
Total:     69/69 passed
```

## Anything Unexpected

- **Test 10 assertion fix**: The completed bookings summary uses `experience` ("Klein Curaçao") over `trip_key` ("klein_curacao") when both are present (code: `_cb.get('experience', _cb.get('trip_key', '?'))`). Initial assertion checked for "klein_curacao" which doesn't appear in the summary. Fixed to check for "Klein Cura" instead.
- **Brief review rounds**: Three review passes needed. Round 1 caught the fully-escalated path bypassing reply_times (anti-loop would never trigger on escalated threads) and incomplete test mocks. Round 2 caught that `returning_booking`/`unknown_ref` flags were set on `flags` after `agent_flags` was already copied, so marina_agent would never see them. Fixed with dual-set to both dicts.
