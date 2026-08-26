# BRIEF 281 — Ali carousel native vehicle selection
**Status:** Implemented | **Files:** `wtyj/agents/marina/marina_agent.py`, `wtyj/agents/social/ali_media_first.py`, `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/agents/social/ali_vehicle_recommendations.py`, `wtyj/agents/social/ali_vehicle_selection.py`, `wtyj/agents/social/social_agent.py`, `wtyj/agents/social/zernio_dm_client.py`, `wtyj/shared/state_registry.py`, `wtyj/tests/agents/test_ali_latest_change_orchestration.py`, `wtyj/tests/agents/test_ali_vehicle_recommendations.py`, `wtyj/tests/agents/test_ali_vehicle_selection.py` | **Depends on:** Brief 280 and issue #198 | **Blocks:** none

## Context

Ali's current discovery carousel is visually useful but its only card action says
“View car.” The customer must be able to make a real, deterministic vehicle choice
from the same recommendation bundle and have that choice become Carlos's canonical
catalog selection.

The verified Zernio WhatsApp contract has two distinct interaction surfaces:

- A media carousel card has a required URL action with `name="cta_url"`,
  `display_text`, and `url`. It exposes no card-level postback payload.
- A top-level reply button carries a provider-returned payload.
- A native interactive list carries one stable row `id` per option and returns that
  ID in `list_reply` metadata.

A carousel URL therefore cannot honestly be labeled as a choice and cannot be used
as evidence that a customer selected a vehicle.

## Why This Approach

The chosen design keeps the 2–5 card media carousel for browsing, gives every URL
button a server-owned localized “Car details” label, and immediately follows it
with a native list picker containing the same current catalog vehicles in the same
order. A one-car recommendation keeps its existing native postback button. The
picker payload continues to use the bounded versioned contract
`ali_vehicle_select:v1:<catalog_vehicle_id>`.

Renaming the URL CTA to “Choose this car” was rejected because a URL click produces
no provider selection payload. Parsing display labels was rejected because labels
are mutable and cannot prove tenant or active-catalog ownership. Sending all fleet
vehicles after an invalid payload was rejected because it breaks curated discovery
and could expose irrelevant options. Invalid taps instead rebuild only the last
delivered branch after revalidating every ID against the current active catalog.

The trade-off is one additional native picker message after a multi-car carousel.
That extra message is necessary to provide a real, provider-confirmed choice.

## Instructions

1. In `ali_vehicle_recommendations.py`, render server-owned localized “Car details”
   URL labels, build picker rows as category + seats + fixed USD/day rate, keep
   carousel and picker order identical, and provide a numbered text fallback.
2. Rebuild invalid-selection recovery only from `ali_last_recommendation_ids`,
   filtering inactive, missing, malformed, or cross-tenant IDs through the current
   catalog. Send no invented branch when no prior safe branch remains.
3. In `zernio_dm_client.py`, treat a standalone recovery picker as an idempotent
   recommendation delivery. Reconcile a provider-visible message before retrying,
   and fall back to numbered text only after an interactive provider failure.
4. In `ali_vehicle_selection.py`, validate the selected vehicle, active class, and
   exact USD daily rate. Persist canonical vehicle ID/name, category metadata, and
   rate metadata from the catalog rather than display text.
5. In `social_agent.py`, resolve native taps before Claude, invalidate an old summary
   on a valid change, continue the existing one-turn intake path, and attach a fresh
   native picker to the fail-closed response when the prior delivered branch remains
   valid. Do not add a Claude call.
6. Extend provider-confirmed recommendation delivery state to include standalone
   picker and picker-fallback outcomes. Preserve Brief 280's plan-send-commit boundary
   and existing quote/PDF timing and idempotency rules.
7. Keep the Marina schema backward compatible, but explicitly forbid selection
   wording on a URL CTA and explain that Python sends the native selection control.

## Tests

1. Verify 2-, 4-, and 5-car carousel/picker alignment, stable payloads, row order,
   seats/rate descriptions, and localized EN/NL/PAP/DE text.
2. Contract-test that no URL CTA is presented as “Choose this car” or its localized
   equivalent.
3. Verify a native tap and an exact typed choice resolve to the exact active catalog
   vehicle ID/name/category/rate, while inactive, stale, malformed, unknown, and
   cross-tenant IDs fail closed.
4. Verify complete intake plus a valid tap creates one fresh summary, replaces an old
   selection, invalidates the stale summary, and does not resend vehicle media.
5. Verify a stale tap rebuilds only the prior current branch without invoking Claude.
6. Verify carousel/picker partial failure, restart reconciliation, idempotency keys,
   standalone picker delivery, and numbered provider-failure fallback.
7. Run the focused recommendation/selection/orchestration suite and the complete
   `wtyj/tests/` suite.

## Success Condition

An allowlisted synthetic customer can browse a 2–5 car carousel, tap the matching
native “Choose a car” picker, persist the exact active catalog vehicle ID, and receive
Carlos's next missing intake question or one fresh summary without a repeated carousel.

## Rollback

Revert the Brief 281 merge commit and redeploy through the normal production workflow.
The change adds no database schema or migration; existing JSON flags tolerate the new
delivery values and revert safely to the prior carousel-plus-picker behavior.
