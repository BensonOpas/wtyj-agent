# OUTPUT 227 — Decision-first escalation summary

## What was done
Added `escalation_summary TEXT` JSON column to `pending_notifications` (idempotent ALTER right after the Brief 213 mode ALTER). New file `wtyj/dashboard/escalation_summary.py` houses the Claude generator: `SUMMARY_TOOL` schema (5 required fields including `recommendedOptions[]` and `extractedDetails.proposedTimes[]`), `_format_history` to render conversation as plain text, `generate_summary()` returning a dict on success or None on any failure (logged via `bm_logger`). State-registry gained a parallel `_summary_dispatcher` global + `set_summary_dispatcher()` setter mirroring Brief 217's alert-dispatcher pattern. `create_pending_notification` rewritten to (a) dedup unresolved escalations by UPDATE-in-place when a `customer_id` already has a pending row, (b) call the summary dispatcher and persist its dict as JSON. `get_all_escalations` selects + parses + lifts `escalationSummary`/`recommendedOptions`/`extractedDetails` per row. New `get_active_escalation_summary_for(customer_id)` helper. Dashboard's `_conversation_status_fields` now embeds the same three fields. `_generate_escalation_summary` wrapper in `dashboard/api.py` loads channel-appropriate history (email_thread_state for email, dm_get_history for IG/FB, wa_get_full_history for whatsapp) and registers via `state_registry.set_summary_dispatcher`.

## Tests
1053 passing / 0 failures (baseline 1046 + 7 new).

## Deployment
Source committed and pushed; deploy still to fire.
