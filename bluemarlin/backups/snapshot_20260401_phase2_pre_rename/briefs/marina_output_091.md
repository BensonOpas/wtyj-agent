# OUTPUT 091 — Name Priority + Smarter Escalation Guard

**Brief:** marina_brief_091_name_priority_and_escalation_guard.md
**Status:** Complete
**Date:** 2026-03-14

## What Was Done

1. **Name priority:** `from_id` now uses `fields.get("customer_name")` when available, falls back to WhatsApp profile `from_name`. First message uses profile name (customer_name not yet extracted), subsequent messages use the name the customer gave.

2. **Escalated guard:** Changed from "holding message only" to allowing factual questions from CLIENT DATA while maintaining escalation for the original issue. Applies to both WhatsApp and email channels (shared prompt builder). Scalable — uses "CLIENT DATA" not business-specific terms.

## Test Results
```
relay bridge tests: 15/15 PASSED (13 existing + 2 new)
social regression: 107/107 PASSED
marina tone tests: 18/18 PASSED
```

New tests:
- `test_from_id_uses_customer_name` — pre-sets customer_name "John", sends message with profile name "Calvin Profile", asserts marina_agent sees "John" not "Calvin Profile"
- `test_escalated_prompt_allows_factual` — asserts escalated prompt mentions "factual question" and "CLIENT DATA", does NOT say "holding message only"

## Unexpected
Nothing unexpected.
