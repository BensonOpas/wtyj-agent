# BRIEF 275 — Ali premium vehicle recommendations
**Status:** Executed | **Files:** `wtyj/agents/marina/marina_agent.py`, `wtyj/agents/social/ali_vehicle_recommendations.py`, `wtyj/agents/social/social_agent.py`, `wtyj/agents/social/webhook_server.py`, `wtyj/agents/social/zernio_dm_client.py`, `wtyj/shared/state_registry.py`, focused tests | **Depends on:** Briefs 270-274 | **Blocks:** issue 178

## Context

Ali's current WhatsApp discovery flow can describe vehicles in text but cannot present the owner-approved catalog images. Specific requests therefore lack the promised visual, while undecided customers may receive dense text instead of a curated set. Zernio's current Inbox API supports WhatsApp media carousels inside the open service window, but the existing sender exposes only text and single attachments and has no recommendation-level idempotency.

## Why This Approach

Keep the existing single Claude call responsible for understanding the customer and generating natural copy, and add one structured recommendation action to that response. Python then validates the named options against the current authenticated Ali catalog and renders only catalog facts. This was selected over Python keyword classification, a second model call, or a hardcoded fleet list because all three violate the repository architecture or create a second pricing truth. A native media carousel is used only for 2–3 curated options; one known vehicle remains a single-image message. The unavoidable CTA on each Zernio media card links to the matching Ali fleet page while ordinary typed replies remain the selection path.

## Instructions

1. Extend the Marina response schema and Ali prompt contract with an optional structured `ali_vehicle_recommendation` action. Claude chooses `specific` with exactly one current vehicle or `curated` with 2–3 current suitable vehicles, plus localized availability and CTA presentation text. The ordinary `reply` remains the only conversational copy.
2. Add a catalog-only plan builder that validates exact vehicle names, seats, fixed USD daily rates, owner-approved HTTPS images, category links, and requested passenger capacity. Omit unavailable capacity fields and reject invented or duplicate options.
3. Render one image message for a specific vehicle. Render Zernio's documented `interactive.type = carousel` payload for an undecided customer, with 2–3 media cards using `card_index`, image headers, concise factual bodies, and one CTA URL per card.
4. Derive a stable recommendation hash and provider idempotency key from catalog version, option IDs, action mode, and structured rental needs. Suppress a hash already accepted for the conversation and persist accepted image, carousel, or fallback delivery atomically.
5. Check the WhatsApp 24-hour service window before interactive delivery. Retry ambiguous provider failures with the same key, reconcile recent messages before fallback, and use the same Claude-generated text for one idempotent text fallback. Never send both a successful carousel and fallback.
6. Preserve the master Ali automation switch, existing price answers, discovery-before-personal ordering, summary confirmation, quote generation, and the separate three-minute final-quote boundary.

## Tests

- A specific exact catalog vehicle produces one image plan with exact image, category, seats, rate, locale, and no carousel.
- An undecided customer produces 2–3 suitable unique catalog cards, never all eight; missing capacity is omitted and undersized vehicles are rejected.
- The Zernio request matches the documented native carousel schema, uses an idempotency key, and sends no interactive request outside the service window.
- Provider replay/restart suppresses duplicate recommendation delivery; ambiguous failure reconciles before fallback; terminal failure sends exactly one text fallback.
- EN/NL/PAP/DE presentation is concise, typed selections remain canonical through existing catalog resolution, and existing Ali intake/quote suites stay green.

## Success Condition

An allowlisted Ali WhatsApp chat receives one premium image for a specific vehicle or one replay-safe native 2–3-card carousel for an undecided request, using only current catalog facts and owner-approved assets.

## Rollback

Revert the issue 178 merge commit and redeploy. The persisted recommendation-delivery flag is inert under the prior code and may remain in existing conversation state.
