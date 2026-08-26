# BRIEF 278 — Ali Quote Leads Read Model
**Status:** Ready | **Files:** `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/dashboard/api.py`, `wtyj/tests/agents/test_ali_quote_leads.py` | **Depends on:** Brief 277 | **Blocks:** BensonOpas/wtyj-agent#191 and unboks-org/unboks-dashboard-api#107

## Context
Ali uses `workflow.type = ali_quote`. Its open WhatsApp rental state is persisted in `whatsapp_booking_state`, while the dashboard Quote Leads page currently reads `/follow-ups`, whose callback-only `follow_up_requests` source is deliberately unavailable to Ali. Production therefore has open rental conversations but an empty Quote Leads queue. Issue #191 requires an authenticated, tenant-scoped, read-only projection of existing Ali state without replaying customer messages or changing Carlos.

## Why This Approach
Project the queue at read time from `whatsapp_booking_state`, the latest matching `ali_quotes` row, active escalation state, conversation status, and message metadata in the same tenant SQLite database. This is immediately idempotent for existing conversations and keeps canonical quote completeness and delivery state beside the workflow that owns them. Rejected: copying Ali leads into `follow_up_requests`, because that schema and its status transitions belong to callback coordination and would create a second mutable truth. Rejected: a one-off migration, because the source tables already contain everything needed and new conversations must remain visible automatically.

## Instructions
1. In `wtyj/agents/social/ali_quote_workflow.py:272`, add a read-only `list_quote_leads` projection. Select one row per open, non-blocked `whatsapp_booking_state` conversation and enrich it with the latest quote, active escalation, latest sender name, and an unanswered-user-message count.
2. Use the workflow's existing required rental fields and exactly-one-selection rule. Include customer name as required because `normalized_summary` requires it. Return only UI fields, safe masked WhatsApp display, status, missing fields, next action, and quote delivery metadata; never return JSON state blobs or customer message text.
3. Project `needs_an_answer` for unresolved escalations, `missing_information` for incomplete canonical details, `in_progress` for quote workflow statuses already defined by `PENDING_STATUSES`, `ready_to_quote` for a confirmed request whose official customer delivery is not successful, and `active` for other open leads. Treat `active` query filtering as the umbrella over every open lead.
4. In `wtyj/dashboard/api.py:4392`, add authenticated `GET /quote-leads`, guard it to `workflow.type = ali_quote`, set no-cache headers, and support the approved status filters. Leave `/follow-ups` unchanged.
5. In `wtyj/tests/agents/test_ali_quote_leads.py`, cover incomplete, confirmed-ready, escalation, in-progress, aggregation, three distinct conversations, archived/blocked exclusion, authentication, Ali capability, status filtering/count agreement, tenant isolation, and callback endpoint regression.

## Tests
- Three messages in one conversation produce one row with an aggregated unread count; three conversations produce three rows.
- Incomplete, ready, escalated, and processing states project to their approved statuses and all remain in Active.
- Archived, blocked, and resolved conversations are excluded.
- The endpoint rejects missing authentication and non-Ali workflow configuration.
- `/follow-ups` remains callback-only and its existing tests remain green.

## Success Condition
The authenticated Ali `/quote-leads` endpoint exposes every existing open rental conversation exactly once with consistent tab counts, without sending a message or mutating conversation/quote state.

## Rollback
Revert the issue #191 backend commit and redeploy the prior container image; no database rollback is needed because the implementation is read-only and adds no schema.
