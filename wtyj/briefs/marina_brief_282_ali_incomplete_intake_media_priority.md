# BRIEF 282 — Ali incomplete-intake media priority
**Status:** Implemented | **Files:** `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/tests/agents/test_ali_quote_intake_dispatch.py`, `wtyj/tests/agents/test_ali_latest_change_orchestration.py` | **Depends on:** Briefs 280 and 281 | **Blocks:** none

## Context

Production logs showed Carlos correctly classifying vehicle discovery as
`request_recommendation`, but the turn planner validated every quote field before
routing that intent. If the customer had not selected a vehicle yet—or had not yet
provided a later personal detail—the planner returned a text-only
`required_fields_incomplete` reply. No image, carousel, or picker payload was built,
even though Carlos's text claimed options were being shown.

Vehicle discovery intentionally happens before a complete quote intake. Quote-summary
validation therefore cannot be the gate for a catalog-grounded media recommendation.

## Instructions

1. Resolve the deterministic turn intent before complete-summary validation.
2. Keep human escalation as the highest-priority route.
3. When a validated recommendation action exists, route it to
   `vehicle_recommendation` in `DISCOVERY` even while quote fields are incomplete.
4. Do not create a draft hash, summary, quote, or confirmation eligibility from an
   incomplete intake.
5. Keep invalid or missing recommendation actions on the existing concise intake
   reply path; the media builder remains responsible for catalog and capacity checks.
6. Preserve provider-confirmed delivery commits, replay suppression, native picker
   behavior, and all quote timing and delivery rules.

## Tests

1. Verify an incomplete intake with a valid recommendation routes to media while
   incomplete intake without one remains a normal collecting reply.
2. Verify human escalation still wins over a recommendation request.
3. Reproduce the production shape—dates, locations, passengers, and luggage present,
   vehicle and personal details incomplete—and assert one carousel plus matching
   picker is built with no summary eligibility.
4. Run the focused Ali intake/media suites and the complete `wtyj/tests/` suite.

## Success Condition

Carlos can show approved current-catalog vehicle images and the native choice control
during discovery, before the customer has completed every quote field, without
creating a stale summary or weakening any idempotency or escalation guard.

## Rollback

Revert the Brief 282 merge commit and redeploy through the normal production pipeline.
This change adds no schema, migration, environment variable, or irreversible data.
