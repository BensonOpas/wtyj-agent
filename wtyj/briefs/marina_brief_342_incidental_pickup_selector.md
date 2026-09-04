# BRIEF342 — Preserve canonical confirmation with incidental pickup selectors
**Status:** Deployed and verified at f220c3e; A4/A8 acceptance holds remain | **Files:** `wtyj/agents/social/mermaid_reservation_workflow.py`, `wtyj/tests/agents/test_mermaid_confirmation_cancellation.py` | **Depends on:** 535508c | **Blocks:** final candidate verification

## Context
Preserved follow-up PARA005 turn2 supplies complete details and explicit pickup consent with no guest question. The model nevertheless emits `status_request=pickup_pricing`. At `mermaid_reservation_workflow.py:585`, any status selector is treated as a question, so the canonical summary is delayed until turn6's YES. This repeats the original extra-confirmation defect despite saved fields remaining correct.

## Why This Approach
The existing guest-question excerpt proof already distinguishes guest uncertainty from Tracy's own questions. Apply it to incidental pickup pricing instead of allowing this informational selector to override canonical booking progression. Reject treating every price selection as consent or accepting YES before showing a summary. Keep actual mixed pickup questions informational and preserve all human/security/cancellation priorities. No Python language classification or new copy is added.

## Instructions
1. At `mermaid_reservation_workflow.py:585`, pickup_pricing alone must not establish guest uncertainty; retain the existing exact guest excerpt proof and other protected routes.
2. Track when the canonical summary or confirmation was produced by the existing state machine. Such a result must not be replaced with pickup_pricing facts from an incidental selector; real guest questions still take the existing informational path.
3. Keep current pricing, immutable reservations, explicit consent, duplicate protection and review/cancellation/security priorities.

## Tests
Across six languages, complete explicit pickup details with an empty guest excerpt and incidental pickup_pricing must show the canonical summary first. An intervening FAQ preserves that phase; one subsequent confirmation produces exactly one USD450 quote for two adults, one child and car pickup. Repeat confirmation remains idempotent. A real mixed price question must still answer current vehicle facts without premature summary/quote, and a contradictory incidental selector must not advance a review-blocked booking. Existing confirmation/cancellation and pickup tests remain green.

## Success Condition
Incidental pickup facts cannot delay or hide the one canonical summary, while actual guest questions and explicit approval requirements remain intact.

## Rollback
Revert this focused source/test commit before release; no live data migration is needed. Eventual deployment uses the reviewed Mermaid-only image/config rollback.
