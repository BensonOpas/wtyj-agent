# BRIEF 313 — Ali passenger count is optional discovery context
**Status:** Executed | **Files:** `wtyj/agents/marina/marina_agent.py`, `wtyj/agents/social/ali_media_first.py`, `wtyj/agents/social/ali_vehicle_recommendations.py`, `wtyj/tests/agents/test_ali_media_first.py`, `wtyj/tests/agents/test_ali_quote_intake_dispatch.py`, `wtyj/tests/agents/test_ali_vehicle_recommendations.py` | **Depends on:** Briefs 275, 282 and the latest-customer-turn discovery fixes | **Blocks:** None

## Context
Ali's live WhatsApp flow still asked how many people would travel in the car before showing options. The newer latest-turn handling correctly sent the carousel after a customer insisted that the choice did not matter, but three older passenger gates remained: the model prompt permitted the question, the deterministic media planner returned a missing-passenger clarification, and the delivery validator rejected an otherwise valid curated carousel without passenger count.

Passenger count is not required to prepare an Ali quote. Published vehicle cards already show seat and approximate luggage capacity. Asking group size therefore adds friction and makes Nick sound like a scripted intake bot.

## Why This Approach
Passenger count remains an optional structured field because customers may volunteer it, and that information is useful for capacity warnings and ranking. It is removed only as an intake requirement. If it is unknown, Nick shows current options without claiming that every option fits the customer's group.

A prompt-only change was rejected because a model can still produce an old or unexpected passenger question. A renderer-only change was also rejected because the planner could stop before reaching the renderer. The fix closes all three layers and repairs an attempted passenger question into the existing catalog-grounded carousel path.

## Instructions
1. Update the Ali tool schema and discovery instructions at `wtyj/agents/marina/marina_agent.py:145`, `wtyj/agents/marina/marina_agent.py:1061`, and `wtyj/agents/marina/marina_agent.py:1153` so passenger count is extracted only when volunteered and never asked.
2. Recognize passenger questions in all four supported locales at `wtyj/agents/social/ali_media_first.py:174` and convert them to a recommendation intent at `wtyj/agents/social/ali_media_first.py:730`.
3. Remove passenger-count clarification fallbacks and build catalog choices when capacity is unknown at `wtyj/agents/social/ali_media_first.py:1222`.
4. Keep category repair conversational by moving to pickup date instead of group size. Keep seat and luggage information on vehicle cards.
5. Allow curated carousel rendering without passenger count at `wtyj/agents/social/ali_vehicle_recommendations.py:563`. Preserve suitability rejection when a volunteered passenger count is known and the response is not explicitly advisory.
6. Add regression coverage for the reported wording, four-language interception, optional carousel validation, prompt rules, and existing orchestration behavior.

## Tests
- `test_model_passenger_question_is_repaired_into_catalog_options` covers the reported passenger-question loop in English, Dutch, Papiamentu, and German.
- `test_missing_passenger_count_shows_options_instead_of_asking` verifies that broad recommendations produce current options without passenger count.
- `test_curated_recommendation_does_not_require_passenger_count` verifies the delivery validator accepts the carousel.
- The focused production-equivalent suites for media-first discovery, recommendation delivery, quote intake dispatch, and latest-change orchestration must all pass.

## Success Condition
Nick never asks for passenger count; if it is not volunteered, he shows current vehicle options with card-owned capacity information and continues the quote flow normally.

## Rollback
Revert the Brief 313 commit and redeploy through the normal WTYJ pipeline. No data or schema migration is involved.
