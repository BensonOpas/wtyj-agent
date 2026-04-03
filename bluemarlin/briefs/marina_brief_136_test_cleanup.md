# BRIEF 136 — Test Debt Cleanup
**Status:** Draft | **Files:** Test files only — NO source code changes | **Depends on:** Brief 135 | **Blocks:** None

## Context

30 test failures across social + marina suites. All are test issues, not source code bugs. Categories:
1. Old "BF-" booking ref format (4 tests) — refs are now random 6-char alphanumeric
2. Missing `import re` (1 test) and `_trip` variable not renamed (2 tests)
3. Stale hardcoded dates from March 2026 (4 tests) — dates have passed
4. Prompt text assertions checking for strings that don't exist in the prompt (19 tests) — these check for "THIRD", "CHANGE", escalation behavior text that was removed/restructured in earlier briefs but tests were never updated

No source code changes. Test-only brief.

## Why This Approach

Fix all 30 at once. No partial state. The test suite should be green (or as close as possible) so future briefs can trust regression results.

## Instructions

### Category 1: Old booking ref format (social tests)

**test_070_whatsapp_booking.py:**
- Line 230 `test_orchestrator_booking_summary_sent`: fails because `create_soft_hold` returns None (stale date). Fix with dynamic date helper.
- Line 276 `test_orchestrator_booking_confirmed`: add `import re` at top. Check for `re.search(r'[A-Z0-9]{6}', reply)` instead of `'BF-' in reply`.

**test_072_whatsapp_multi_trip.py:**
- Lines 69, 84, 106, 132-157, 171-176: replace all `"BF-2026-XXXXX"` refs with 6-char alphanumeric format (e.g., `"X7K9M1"`). Update assertions to match.
- The returning customer test inserts a fake booking then sends a message containing the ref. The regex `\b[A-Z0-9]{6}\b` will find it. The DB check will confirm it exists.

**test_073_whatsapp_hardening.py:**
- Line 258 `test_change_detection_cancels_hold`: stale date. Fix with dynamic date.

**test_129_large_group.py:**
- Already has `import re` (fixed earlier). Verify assertion uses regex not "BF-".

**test_133_generalize_config.py:**
- Already fixed (Brief 135). Verify passing.

### Category 2: Missing imports / variable renames (marina tests)

**test_064_hardening.py:**
- `_trip` not defined (line 19, 26). Rename to `_svc` or `_service`. These are local variable names in the test that load service config.
- Stale dates (March 2026). Fix with dynamic date helper.

### Category 3: Stale dates (social + marina tests)

Tests with hardcoded dates like `"2026-03-18"`, `"2026-03-25"`, `"2026-03-26"` that have passed. Fix pattern:
```python
def _next_weekday(weekday_num):
    """Return next date matching weekday (0=Mon, 2=Wed, etc.)"""
    today = datetime.now(timezone.utc).date()
    d = today + timedelta(days=1)
    while d.weekday() != weekday_num:
        d += timedelta(days=1)
    return d.isoformat()
```

Apply to: test_070, test_073, test_046, test_048, test_051, test_064.

### Category 4: Pre-existing prompt assertion failures (marina tests)

These tests assert that specific text exists in Marina's prompt, but the text was removed or restructured in earlier briefs. The tests are stale. Two options:

**Option A: Delete them.** They test prompt text that no longer exists. The behavior they tested is either gone or handled differently now.

**Option B: Update them** to check for the current prompt text.

Recommend Option A for the following tests (the features they test are either removed or covered by other tests):
- test_040 (3 tests) — escalation behavior tested by live tests and Brief 071-074 tests
- test_041 (3 tests) — semi-escalation prompt tested by test_128
- test_043 (2 tests) — relay detection tested by test_077
- test_044 (4 tests) — departure-before-summary is now slot-before-summary, behavior tested by test_070
- test_045 (3 tests) — slot alternative as change, behavior tested by test_070
- test_046 (4 failing tests of many) — hybrid state machine, fix stale dates only
- test_048 (2 tests) — human speech, fix stale dates only
- test_051 (1 test) — manifest integration, fix stale date + ref format

For tests that only have stale dates or ref format issues (test_046, test_048, test_051): fix them, don't delete.

For tests that assert removed prompt text (test_040, test_041, test_043, test_044, test_045): delete them. The functionality is covered by newer, more comprehensive tests.

### Step-by-step execution

1. Add `import re` to test_070
2. Fix test_070 with dynamic dates + new ref regex
3. Fix test_072 with 6-char refs
4. Fix test_073 with dynamic date
5. Fix test_064 with `_trip` → `_svc` + dynamic dates
6. Fix test_046, test_048, test_051 with dynamic dates + ref format
7. Delete stale prompt assertion tests: test_040, test_041, test_043, test_044, test_045
8. Fix test_061 ref format (BF-2026-12345 → 6-char)
9. Run full suite

## Tests

No new test file. The fix IS the tests. Success = all tests pass.

## Success Condition

`python3 -m pytest tests/social/ tests/marina/ -q` shows 0 failures (or as close as possible).

## Rollback

Git revert. Tests only — no source code at risk.
