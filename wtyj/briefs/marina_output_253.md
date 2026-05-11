# OUTPUT 253 — Filter `get_all_escalations` by `conversation_status.deleted`

## What was done

P1 fix for issue #22 — Calvin found a stuck WhatsApp escalation row in the dashboard that he couldn't archive/delete from the UI. Read-only audit on unboks production confirmed root cause: Calvin's WhatsApp conversation `69efec187aca03948969dc95` was archived via Brief 249 (`conversation_status.deleted=1`) but `get_all_escalations()` had no JOIN with `conversation_status` — so 7 escalation rows on that conv (id=15, 19, 20, 22, 24, 25, 29) plus 1 on `69f7cea6e99a2574e014abec` (id=21) = **8 total stuck rows** stayed visible in the Escalations tab forever. Per-step shipped:

1. **Modified `get_all_escalations` SQL** at `wtyj/shared/state_registry.py:2240` — added `LEFT JOIN conversation_status cs ON pn.customer_id = cs.conversation_id WHERE cs.deleted IS NULL OR cs.deleted = 0`. Mirrors Brief 249's `wa_list_conversations` LEFT JOIN pattern. The `IS NULL OR = 0` semantic preserves escalations on conversations that have NO `conversation_status` row at all (most active conversations). Only rows with explicit `deleted=1` get excluded.
2. **2 new tests appended to `wtyj/tests/social/test_249_server_side_archive.py`** (extends the existing per-module file for archive-related behavior per Brief 236). Test 1 exercises the full archive → reappear cycle: pre-archive (visible) → archive (excluded) → unarchive (reappears). Proves it's a view filter, not a delete. Test 2 covers the LEFT JOIN's NULL-handling — uses direct SQL INSERT to bypass `create_pending_notification` (which UPSERTs a `conversation_status` row via `set_conversation_status` side-effect — round-1 reviewer caught this) so the LEFT JOIN's `cs.deleted IS NULL` branch is genuinely exercised.

**Brief-reviewer:** FAIL round 1 with 4 issues (wrong line numbers; Test 2 premise contradicted by `create_pending_notification`'s UPSERT; baseline 1081 vs stale MEMORY's 1015; "9 vs 8" enumeration). Round 2 PASS on design but caught 2 leftover-text propagation bugs from round-1 fixes (line 28 still said "9", Test design notes still claimed both tests use `create_pending_notification`). Round 3 patched both leftover-text bugs. **Calvin explicitly approved executing past the max-1-retry rule** because the round-2 reviewer FAIL was on text-cleanup propagation only — design (SQL fix, line numbers, test logic, rollback) was already validated as correct in round 2.

## Tests

1083 passing / 0 failures (1081 baseline + 2 new = 1083). Targeted file `wtyj/tests/social/test_249_server_side_archive.py` runs 8/8 (was 6; added 2).

## Calvin's stuck rows after deploy (verified mathematically; production verification needed)

After deploy, the LEFT JOIN excludes Calvin's 8 stuck escalation rows from the dashboard's Escalations view:
- 7 rows on `69efec187aca03948969dc95` (id=15, 19, 20, 22, 24, 25, 29) — all WhatsApp; `conversation_status.deleted=1` set by Brief 249's archive endpoint.
- 1 row on `69f7cea6e99a2574e014abec` (id=21) — WhatsApp; same archive flag.

**No data destroyed.** All 8 escalation rows remain in `pending_notifications` for audit trail. `alert_deliveries` rows referencing these `escalation_id` values are preserved. If Calvin unarchives either conversation via Brief 249's `POST /messages/conversations/{conv_id}/unarchive`, the escalation rows automatically reappear in the active view.

## Deployment

Source commit pending. Will deploy via the standard CI pipeline. **Pure SQL view filter** — no schema migration, no data mutation. Briefs 238-252 all preserved (only `get_all_escalations`'s SELECT changes; the function's signature, return shape, and downstream callers are unaffected).

## Out-of-scope (deferred per brief Step 3)

- Email-channel archive filter — Brief 253 only catches WA/IG/FB. Email uses `flags.deleted` in `email_thread_state.json`. Defer until same problem materializes for email.
- Hard-delete the 8 historical stuck rows — not needed; view filter hides them. Rows preserved for audit + reappear if Calvin unarchives.
- `?include_archived=true` flag on `list_escalations` — defer until use case materializes.
- Propagate archive state to `pending_notifications` (new `deleted` column) — schema-heavier alternative; defer.
