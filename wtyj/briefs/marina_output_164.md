# OUTPUT 164 — Support-email sender filter + Lucia cleanup

## What was done

Added `_business_sender_emails()` helper to `wtyj/agents/marina/email_poller.py` that reads `business.email`, `business.support_email`, `business.booking_email`, and `business.demo_support_email` from client.json, lowercases them, strips whitespace, filters out empty/None values, and returns a set.

Added a new guard immediately after the existing `_SYSTEM_EMAIL_PREFIXES` check in the UID loop: if `from_email.lower()` is in the business-sender set AND the subject does NOT contain `[RELAY-` or `[ESCALATION]`, mark the email Seen, log "Skipped business-sender email", and continue. The existing `demo_support_email + [RELAY-` and `demo_support_email + [ESCALATION]` guards further down remain in place — they handle the legitimate operator-reply flow which the new guard deliberately passes through.

Deleted the `SU0AHF` row for "Lucia Vasquez" from `bookings` table on the VPS (test pollution from Benson's 2026-04-08 E2E session).

## Tests — 5 new

1. `test_business_sender_emails_includes_all_four_fields` — all four business email fields present → returned set contains lowercased, deduped values
2. `test_business_sender_emails_handles_missing_fields` — missing or empty fields → filtered out
3. `test_business_sender_emails_empty_when_no_business` — empty business dict → empty set (guard is a no-op)
4. `test_business_sender_lowercase_normalization` — whitespace + mixed case → normalized to lowercase + trimmed
5. `test_source_has_business_sender_guard` — source-level regression guard that the UID-loop guard exists AND the `_is_relay` / `_is_escalation` passthrough logic is present

## Test results

```
$ python3 -m pytest wtyj/tests/marina/test_164_support_email_filter.py -v
5 passed in 0.30s

$ python3 -m pytest wtyj/tests/ -q --tb=line
758 passed, 6 warnings in 3.84s
```

**758 passing / 0 failures.** Baseline was 753 from Brief 163 + 5 new = 758. ✓

## Unexpected findings

### 1. test_066_project_structure.py flagged my `sys.path.insert`

First regression run failed one test: `test_no_sys_path_insert_in_tests` at `test_066_project_structure.py:71`. I had reflexively included `sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))` in the new test file header — this is a pattern I copied from `test_113_session_fixes.py` but that pattern is actually banned codebase-wide because `conftest.py` already handles path setup. The test enforces it as a structural invariant.

Fix: removed the `sys.path.insert` line and the `import sys` statement. Test 066 passed on the next run.

**Lesson** (added to marina_lessons.md): when copying a test file header as boilerplate, check which header lines are still necessary after Brief 154's test hygiene cleanup. `conftest.py` handles path setup for the whole test tree; no individual test file should re-do it.

### 2. Lucia SU0AHF deleted successfully, Sheets row left for manual cleanup

The VPS SQLite delete was one row. The Google Sheets Bookings tab row for Lucia is still there — I don't have a programmatic path to delete rows from Sheets (we only have append-only log functions), and writing one just for this one-time cleanup would be speculative complexity. Benson can delete the row manually from the Sheets UI if desired, or leave it as a historical artifact — it no longer affects Marina's behavior because the database is the source of truth for returning-customer lookups.

## Deployment

- Backend committed `ee899da`, pushed to main
- VPS: BlueMarlin rebuilt + redeployed, health check `{"status":"ok"}`
- Adamus skipped (email_poller exits on startup due to empty EMAIL_ADDRESS, no behavioral impact from this fix)
- Lucia `SU0AHF` verified gone from VPS `bookings` table

## Files modified

| File | Change |
|------|--------|
| `wtyj/agents/marina/email_poller.py` | `_business_sender_emails()` helper + UID-loop guard |
| `wtyj/tests/marina/test_164_support_email_filter.py` | **NEW** — 5 tests |
| `wtyj/briefs/marina_brief_164_support_email_filter.md` | **NEW** — brief |
| VPS `state_registry.db` | Lucia `SU0AHF` row deleted |

## Brief 164 is complete.
