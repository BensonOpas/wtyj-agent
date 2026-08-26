# Brief 275 — Ali immediate published-price answers

**Status:** Implemented | **Files:** `wtyj/agents/marina/marina_agent.py`, `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/tests/agents/test_ali_quote_intake_dispatch.py` | **Depends on:** Briefs 157, 271 | **Blocks:** Ali price-question production behavior

## Context

Ali's live published catalog already supplies fixed category and vehicle daily
rates to Carlos, but the highest-priority Ali prompt prohibited him from stating
any price. Customers therefore had to complete the full rental intake before
hearing a standard published rate.

## Goal

When an Ali WhatsApp customer asks a price question, Carlos immediately gives
the exact unambiguous published USD daily rate, explains that the final price
will be in the official quote sent here in a few minutes, and then continues
collecting the next missing rental detail naturally.

## Scope

- Expose each published vehicle's fixed daily rate in the existing no-PII prompt
  catalog alongside the category rates.
- Ground direct price answers only in one unambiguous current catalog match.
- Carry the same official-quote expectation in English, Dutch, Papiamentu, and
  German.
- Continue the existing one-question-at-a-time intake without repeating known
  facts.
- Preserve the deterministic quote, customer-only three-minute delivery gate,
  and all existing idempotency protections.
- Do not add a price engine, a second model call, dynamic pricing, discounts,
  estimates, checkout, or an admin surface.

## Why This Approach

The existing single Marina call already receives the current authenticated Ali
catalog and owns natural customer conversation. Correcting that prompt and
including the vehicle rate is the smallest grounded change. A Python keyword
classifier would duplicate language understanding and fail Rule 2; static reply
templates would violate Rule 3 and sound unnatural; a second model call would
violate the one-call architecture and add avoidable latency.

## Instructions

1. Add `daily_usd` to each vehicle in `catalog_prompt_context` without exposing
   server IDs or customer data.
2. Replace the Ali price prohibition with a highest-priority instruction to
   answer direct, unambiguous price questions immediately from the live catalog.
3. Ask one concise clarification when the requested category or vehicle is
   ambiguous or lacks a published rate; never guess.
4. After a rate, state the official-quote expectation in the customer's current
   language, then ask only the next missing intake question.
5. Keep official quote totals, extras, deposits, dates, expiry, availability,
   three-minute delivery, and idempotency under deterministic Python ownership.

## Tests

1. Category and vehicle prompt records contain exact published daily rates and
   no server-owned IDs.
2. The Ali prompt requires an immediate answer for one unambiguous match and a
   concise clarification for ambiguity.
3. The prompt includes equivalent official-quote expectations for EN/NL/PAP/DE.
4. The prompt prohibits totals, extras, deposits, discounts, dynamic rates,
   exceptions, and estimates while continuing intake without repetition.
5. Existing quote timing and replay tests remain green.

## Success Condition

In production, Carlos can answer a known standard price from the current Ali
catalog on the same turn, sets the official-quote expectation naturally in all
four supported languages, and continues intake while the separate final quote
delivery and idempotency rules remain unchanged.

## Rollback

Revert the issue #175 commit and redeploy the previous production image. The
published catalog and deterministic quote records require no data rollback.

Tracking: GitHub issue #175.
