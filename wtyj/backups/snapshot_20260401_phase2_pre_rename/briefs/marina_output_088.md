# OUTPUT 088 — Resilient Response Validation

**Brief:** marina_brief_088_resilient_response_validation.md
**Status:** Complete
**Date:** 2026-03-14

## What Was Done

1. Replaced `_REQUIRED_RESPONSE_FIELDS` (strict all-or-nothing) with `_RESPONSE_DEFAULTS` (default missing fields)
2. Validation now defaults missing fields to safe values instead of rejecting. Logs `claude_field_defaulted` for each defaulted field.
3. If reply is empty after defaults, fallback fires (preserves email fallback reply)
4. Strengthened JSON format instruction to tell Claude all fields are required, including empty ones

## Test Results
```
marina tone tests: 15/15 PASSED (13 existing + 2 new)
social regression: 104/104 PASSED
```

New tests:
- T14 `test_response_defaults_missing_fields` — Claude returns JSON missing `flags` and `internal_note` → reply goes through, missing fields defaulted
- T15 `test_response_empty_reply_returns_fallback` — Claude returns JSON with empty reply → fallback fires (email safety preserved)

## Unexpected
Nothing unexpected.
