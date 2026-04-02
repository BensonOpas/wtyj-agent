# OUTPUT 093 — Rejection Learning

**Brief:** marina_brief_093_rejection_learning.md
**Status:** Complete
**Date:** 2026-03-16

## What Was Done

1. **content_learnings table** added to state_registry.py — stores distilled brand rules with rule text, source_draft_ids (JSON array tracking which rejections led to this learning), active flag, and timestamp. CRUD functions: save_content_learning, get_active_learnings, deactivate_learning.

2. **Brand learnings injected into system prompt** — `_build_system_prompt()` in content_agent.py now reads active learnings from SQLite and includes a "BRAND LEARNINGS (from operator feedback — follow these strictly)" section. Only appears when learnings exist. Deactivated learnings are excluded.

3. **distill_learnings()** function added to content_agent.py — separate Claude call (not part of generation flow) that reads all rejected drafts with reasons, builds a rejection summary, and asks Claude to identify patterns and propose actionable brand rules. Includes existing learnings in the prompt to prevent duplicates. Stores proposed rules in SQLite. Manual trigger — operator runs when enough rejection data exists.

## Test Results
```
rejection learning tests: 12/12 PASSED
social regression: 133/133 PASSED
```

## Unexpected
Nothing unexpected.
