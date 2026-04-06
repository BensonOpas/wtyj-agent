# BRIEF 120 — Fix Stale Test Dates + Verify Sheets
**Status:** Draft | **Depends on:** — | **Blocks:** —

**Files:**
- `bluemarlin/tests/social/test_070_whatsapp_booking.py`
- `bluemarlin/tests/social/test_073_whatsapp_hardening.py`

## Context
5 booking tests fail because they use hardcoded dates (2026-03-18, 2026-03-20) that have passed. The date validation in `_post_validate` correctly rejects them with "already passed." Fix: compute future dates dynamically so tests never go stale.

Sheets were also verified: headers restored via `format_sheets` on VPS, data exists (11 bookings, 12 escalations, 81 events, 9 manifests). No code changes needed for sheets.

## Why This Approach
Dynamic dates instead of new hardcoded dates. West Coast Beach runs Wed/Sun, so we compute the next Wednesday. Klein Curaçao is daily, so we use today+7. This prevents the tests from breaking again next month.

## Source Material

### Both test files — Add date helper at top (after imports)

Add to both `test_070_whatsapp_booking.py` (after line 26) and `test_073_whatsapp_hardening.py` (after its imports):

```python
def _next_weekday(weekday: int, days_ahead: int = 0) -> str:
    """Return the next occurrence of a weekday (0=Mon, 2=Wed, 6=Sun) as YYYY-MM-DD."""
    today = datetime.now(timezone.utc).date()
    d = today + timedelta(days=max(days_ahead, 1))
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d.isoformat()

# Dynamic future dates for booking tests
_NEXT_WED = _next_weekday(2)      # Next Wednesday (West Coast Beach runs Wed/Sun)
_NEXT_SUN = _next_weekday(6)      # Next Sunday
_NEXT_MON = _next_weekday(0)      # Next Monday (invalid for West Coast Beach)
_FUTURE_DATE = (datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat()  # Any future date (Klein Curacao is daily)
```

### test_070 — Replace hardcoded dates

**test_suggest_dates_west_coast (line 57-60):** This test uses `_suggest_dates("2026-03-16", ...)` — a static Monday. Replace with `_NEXT_MON`. The assertions check for "Wednesday" and "Sunday" in the output which will still be true for any Monday input.

**test_build_booking_summary_west_coast (line 66-69):** Uses `"date": "2026-03-18"`. Replace with `_NEXT_WED`. This test passes already but should be future-proofed.

**test_post_validate_day_of_week_rejection (line 112):** Uses `"date": "2026-03-16"` (Monday). Replace with `_NEXT_MON`.

**test_post_validate_multi_departure_asks (line 136):** Uses `"date": "2026-03-20"`. Replace with `_FUTURE_DATE`.

**test_post_validate_all_pass_builds_summary (line 150):** Uses `"date": "2026-03-18"`. Replace with `_NEXT_WED`.

**test_post_validate_skips_non_booking_intent (line 163):** Uses `"date": "2026-03-20"`. Replace with `_FUTURE_DATE`. Already passes but future-proof.

**test_orchestrator_post_validate_day_override (line 181):** Uses `"date": "2026-03-16"` and message text "March 16". Replace date with `_NEXT_MON`, message text doesn't matter (mock returns fields directly).

**test_orchestrator_booking_summary_sent (line 205):** Uses `"date": "2026-03-18"`. Replace with `_NEXT_WED`.

**test_orchestrator_booking_confirmed (lines 235-241):** Uses `"date": "2026-03-18"` in fields, soft hold, and flags. Replace all 4 occurrences with `_NEXT_WED`.

**test_orchestrator_slot_unavailable (line 282):** Uses `"date": "2026-03-18"`. Replace with `_NEXT_WED`.

### test_073 — Replace hardcoded dates

**test_stale_conversation_resets_fields (line 57):** Uses `"date": "2026-03-18"`. Replace with `_NEXT_WED`.

**test_stale_conversation_archives_booking (line 92):** Uses `"date": "2026-03-18"`. Replace with `_NEXT_WED`.

**test_fresh_conversation_no_reset (line 156):** Uses `"date": "2026-03-20"`. Replace with `_FUTURE_DATE`. Assert on line 169 checks `== "2026-03-20"` — change to `== _FUTURE_DATE`.

**test_change_detection_cancels_hold (lines 245-253):** Uses `"date": "2026-03-18"` in soft hold + fields + flags. Replace all with `_NEXT_WED`. Assert on line 274 checks `("west_coast_beach", "2026-03-18", "09:00")` — replace date.

**test_manifest_failure_cancels_hold (lines 289-296):** Same pattern. Replace `"2026-03-18"` with `_NEXT_WED`.

**test_hold_race_condition (line 334):** Uses `"date": "2026-03-18"`. Replace with `_NEXT_WED`.

## Tests
After applying, run both test files. All 5 previously-failing tests must pass. All previously-passing tests must still pass. Total expected: 26 passing, 0 failing.

## Success Condition
`python3 -m pytest tests/social/test_070_whatsapp_booking.py tests/social/test_073_whatsapp_hardening.py -v` shows 0 failures.

## Rollback
Revert both test files.
