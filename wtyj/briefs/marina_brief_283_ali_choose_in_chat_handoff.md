# BRIEF 283 — Ali actionable choose-in-chat carousel handoff
**Status:** Implemented | **Files:** `wtyj/agents/social/ali_vehicle_recommendations.py`, `wtyj/agents/social/ali_vehicle_selection.py`, `wtyj/agents/social/ali_media_first.py`, `wtyj/agents/social/social_agent.py`, `wtyj/agents/marina/marina_agent.py`, `wtyj/tests/agents/test_ali_vehicle_recommendations.py`, `wtyj/tests/agents/test_ali_vehicle_selection.py`, `wtyj/tests/agents/test_ali_latest_change_orchestration.py` | **Depends on:** Briefs 280–282 | **Blocks:** none

## Context

Issue #210 replaces the generic details-page action on Ali's multi-car WhatsApp
carousel. Zernio media cards expose a URL CTA rather than a per-card postback, so a
card cannot honestly claim that opening its URL has already selected the car. The
native list picker sent immediately after the carousel remains the reliable one-tap
selection control.

## Why This Approach

A direct WhatsApp click-to-chat URL is a pure navigation handoff: it opens the
tenant-configured Ali conversation with one exact catalog name prefilled and has no
application GET endpoint capable of mutating rental state. Only the customer's later
inbound Send reaches the existing webhook, where active-catalog validation, canonical
state persistence, summary invalidation, idempotency and continuation already live.

## Instructions

1. Build every multi-card CTA from `business.whatsapp`, falling back to the tenant's
   configured `business.phone`; never embed Ali's number in shared code.
2. Use concise localized Choose-in-chat labels and localized human-readable prefilled
   choice messages for EN, NL, PAP and DE.
3. Replace verbose carousel introduction text with one localized swipe-and-choose
   instruction while preserving the separate request-only availability note.
4. Keep the native list picker after every carousel and keep the one-car native
   postback unchanged.
5. Resolve a sent handoff message only by one unique active current-catalog vehicle
   name. A stale, inactive or ambiguous handoff fails closed to the current picker.
6. Reuse the existing selection path to persist canonical ID/name/class/rate,
   invalidate any stale summary and continue once without resending media.
7. Update the model contract to describe the honest handoff, without adding another
   model call or allowing a URL open to write state.

## Tests

1. Assert two- and five-card carousel order, localized CTA labels, configured WhatsApp
   destination and exact per-card prefilled messages.
2. Assert recommendation building leaves rental fields and flags unchanged.
3. Assert all four localized sent handoff messages resolve one active catalog vehicle;
   stale, inactive and ambiguous messages fail closed.
4. Assert a handoff choice asks the next missing question or creates one fresh summary,
   and never repeats the carousel.
5. Preserve native picker, replay, partial-delivery, cross-tenant and one-car tests.
6. Run focused Ali media/selection/orchestration tests and the full `wtyj/tests/` suite.

## Success Condition

An Ali customer can swipe the carousel, tap Choose in chat on a specific card, review
and Send the prefilled exact choice, then have Carlos accept that active catalog car
and continue the quote intake once. The list picker remains the primary one-tap path.

## Rollback

Revert the Brief 283 merge commit and redeploy through the normal pipeline. There is
no schema, migration, destructive write, or irreversible data change.
