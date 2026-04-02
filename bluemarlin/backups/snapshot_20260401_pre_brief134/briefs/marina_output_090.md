# OUTPUT 090 — Dynamic Client Context Injection

**Brief:** marina_brief_090_dynamic_client_context.md
**Status:** Complete
**Date:** 2026-03-14

## What Was Done

1. Added `get_raw()` to config_loader.py — returns full parsed client.json
2. Created `_build_client_context()` in marina_agent.py — auto-generates labeled sections from ALL top-level keys in client.json, filtering internal keys (spreadsheet_id, calendar_id, demo_support_email, agent_signature) and [VERIFY] placeholders. Skips trip_aliases (already in system prompt).
3. Replaced manual BUSINESS/TRIPS/FAQ/BOOKING RULES/PAYMENT sections in `_build_user_prompt()` with single dynamic `CLIENT DATA` block
4. Kept TIMEZONE and CURRENCY as prominent standalone lines at top of prompt
5. Removed dead code: `_filter_verify()`, `_build_trips_text()`, `_build_faq_text()`

## Test Results
```
marina tone tests: 18/18 PASSED (15 existing + 3 new)
social regression: 105/105 PASSED
```

New tests:
- T16 `test_client_context_includes_all_sections` — every top-level client.json key (except trip_aliases) has a section in the prompt
- T17 `test_client_context_excludes_internal_keys` — spreadsheet_id, calendar_id, demo_support_email not in prompt
- T18 `test_client_context_no_duplicate_aliases` — trip_aliases not duplicated in user prompt

## Design Principle Applied
Adding a new section to client.json (e.g., `parking_info`, `team`, `locations`) now requires ZERO code changes — Marina sees it automatically. This is the first step toward client-agnostic onboarding.

## Unexpected
Nothing unexpected. Existing test T5 (`test_user_prompt_contains_trips_and_faq`) still passes because "TRIPS" and "FAQ" appear as substring matches in the auto-generated section headers.
