# OUTPUT 060 — Marina Tone v2: Python Templates + Claude Prompting

## What Was Done

### Part A — Python templates (email_poller.py)
- **Header**: Updated to Brief 060
- **`_build_booking_summary()`**: Rewrote from bullet-point format to natural paragraph. Old: "Here's a quick summary..." with bullets and "Shall I lock this in for you?" New: "Just to confirm the details: {trip} on {date}..." with "Want me to go ahead and book this?"
- **`_post_validate()` day-of-week**: "Great choice! Unfortunately, the {trip} doesn't run on {day}s — it runs {days_avail}." → "The {trip} doesn't run on {day}s, only {days_avail}."
- **`_post_validate()` departure options**: "Almost there! The {trip} has a couple of departure options:" → "The {trip} has a couple of departure times:"
- **Slot unavailable** (2 instances): "Oh no — it looks like the {name} on that date is fully booked!" → "Unfortunately the {name} is fully booked on that date."
- **`_suggest_dates()`**: Cleaned up bullet formatting

### Part B — Claude prompting (marina_agent.py)
- **Header**: Updated to Brief 060
- **System/user split**: Created `_build_system_prompt(thread_flags)` and `_build_user_prompt(...)`. Kept `_build_prompt()` as backward-compatible wrapper (concatenates both)
- **`process_message()`**: Updated to use `system=` parameter in API call
- **WRITING STYLE**: Replaced ~50-line negative-heavy section with positive-first section including 3 few-shot example replies (casual booking, confirmation, mid-booking question)
- **AVOID list**: Condensed to single line — em dashes, "Shall I", "I'd be happy to", forced enthusiasm, decorative bold, reasoning out loud
- **Fallback reply**: Rewritten to be less templated

### Part C — Test updates (4 files)
- **test_046**: Lines 57, 85 — "Shall I lock this in" → "Want me to go ahead and book this"
- **test_047**: Lines 32, 43 — same replacement
- **test_048**: Lines 41, 91, 100 — same replacement
- **test_038**: Line 68 — added "go ahead and book" to lock_phrases. Also fixed T1-T5 which were stale from Brief 046 (checking for SECOND:, THIRD:, old prompt phrasing already removed)

### Part D — test_marina_tone.py rewrite (11 tests)
Full rewrite with 11 tests covering:
1. `_build_system_prompt` contains WRITING STYLE
2. `_build_system_prompt` contains tone reference examples
3. `_build_system_prompt` contains JSON format spec
4. `_build_user_prompt` contains INBOUND MESSAGE and body
5. `_build_user_prompt` contains TRIPS and FAQ
6. `_build_prompt` wrapper combines both
7. Booking summary no old "Here's a quick summary" header
8. Booking summary no old "Shall I lock this in" phrase
9. Booking summary still has dollar price
10. Slot-unavailable no em dashes
11. marina_persona in client.json has hospitality reference

## Test Results

### Brief 060 tests — ALL PASS
```
test_marina_tone.py        12/12 passed
test_046_hybrid_state_machine.py  28/28 passed
test_047_reschedule_booking_flow.py  10/10 passed
test_048_human_speech_optimization.py  19/19 passed
test_038_prompt_fixes.py   7/7 passed (including 2 API calls)
```

### Other passing tests
```
test_033_thread_key.py     7/7 passed
test_034_verify_items.py   9/9 passed
test_037_extended_stress.py  6/6 passed
test_039_capacity_soft_holds.py  8/8 passed
test_042_operator_email_hardening.py  5/5 passed
test_booking_ref.py        12/12 passed
test_booking_ref_reply.py  6/6 passed
test_capacity_stress.py    28/28 passed
test_multi_trip.py         10/10 passed
test_stale_thread.py       9/9 passed
```

### Pre-existing failures (NOT caused by Brief 060)
- **test_035, test_036, test_044, test_045**: Stale prompt assertions from Briefs 035-045, superseded by Brief 046 hybrid refactor. These tests check for old prompt phrasing (LANGUAGE:, THIRD:, "day the trip does not run", "CHANGE, not a confirmation") that was already removed.
- **test_040**: API-based semi-escalation test — returns fallback (no API key configured locally)
- **test_043**: Source structure assertion — `substring not found` for old code comment pattern
- **test_049-052**: 1 infrastructure-dependent test each (sheets/calendar formatting)

## Post-Review Fixes
Output reviewer flagged 4 blocking issues, all fixed:
1. **Second slot unavailable message** (email_poller.py line 752) still had "Oh no —" phrasing — updated
2. **test_marina_tone T9** only checked `"$"` — strengthened to check `"$158"` and `"$79"`
3. **Missing test for new closer** — added `test_booking_summary_new_closer` asserting "Want me to go ahead and book this?"
4. **T10 tested hardcoded string** — replaced with `test_post_validate_day_of_week_no_em_dashes` that calls `_post_validate()` and checks the return value

## Unexpected Issues
- test_038 T1-T5 were already broken before Brief 060 — they checked for "SECOND:", child age phrasing, and mid-confirmation phrasing from Brief 038 that was removed by Brief 046. Fixed as part of Part C since the file was already being modified.

## Files Modified
| File | Changes |
|------|---------|
| `src/marina_agent.py` | System/user split, WRITING STYLE rewrite, few-shot examples, API call update, fallback rewrite |
| `src/email_poller.py` | `_build_booking_summary()`, `_post_validate()` messages, slot-unavailable messages, `_suggest_dates()` |
| `tests/test_marina_tone.py` | Full rewrite — 11 tests |
| `tests/test_046_hybrid_state_machine.py` | 2 assertion updates |
| `tests/test_047_reschedule_booking_flow.py` | 2 assertion updates |
| `tests/test_048_human_speech_optimization.py` | 3 assertion updates |
| `tests/test_038_prompt_fixes.py` | lock_phrases + 5 stale assertion fixes |
