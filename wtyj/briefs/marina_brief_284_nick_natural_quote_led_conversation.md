# BRIEF 284 — Nick: natural, first-person, quote-led Ali conversation
**Status:** Approved | **Files:** `wtyj/agents/marina/marina_agent.py`, `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/tests/agents/test_ali_quote_workflow.py`, `wtyj/tests/agents/test_ali_quote_intake_dispatch.py`, `wtyj/tests/agents/test_ali_latest_change_orchestration.py` | **Depends on:** Brief 283 / #213 | **Blocks:** none

## Context

Ali's deterministic rental summary currently opens with “Just checking I’ve got
everything right” and closes with “Does that all look right?”. The owner reports
that this sounds like a validation bot rather than an Ali employee speaking to a
customer on WhatsApp. The Ali prompt also still lacks an explicit requirement to
tell the customer why Nick is asking questions, and its discovery rules do not
clearly require vehicle guidance by needs or budget.

The approved behavior is first-person and quote-led: Nick helps the customer
choose a suitable car, says that he is gathering details to prepare an official
quote, asks one useful question at a time, and presents the completed summary as
“I have these details from you” followed by “Are these details correct?”.

## Why This Approach

Update both the model contract and the deterministic renderer. The model contract
controls discovery, guidance, and progress language while Python owns the exact
summary and post-confirmation copy. This preserves the existing one-model-call
architecture and state machine.

A prompt-only change was rejected because Python replaces the model reply when
intake is complete, so the old summary would remain. A generic global tone change
was rejected because this is Ali-specific behavior and must not affect other
tenants. New intent classifiers or additional model calls were rejected because
the existing structured Ali turn plan already has the required routing data.

## Instructions

1. In `wtyj/agents/marina/marina_agent.py:982-1100`, make Nick the only Ali
   identity and add Ali-specific quote-led guidance. Require Nick to explain by
   the first or second substantive reply that he is gathering details to help
   choose the right car and prepare an official quote.
2. In the same Ali block, require first-person ownership, one useful question at
   a time, and progress cues only when helpful. Explicitly prohibit the two old
   robotic summary phrases.
3. Extend discovery guidance to use passenger count, luggage, transmission,
   vehicle size, practical needs, comfort, or approximate daily budget only when
   relevant. Needs-based recommendations explain the fit briefly; budget-based
   recommendations use exact active-catalog daily rates at or closest to the
   stated budget.
4. In `wtyj/agents/social/ali_quote_workflow.py:1577-1645`, replace the
   deterministic EN/NL/PAP/DE summary opening and closing with natural
   first-person equivalents. Keep all canonical fields, localized dates,
   supplements, hashes, confirmation eligibility, and state transitions intact.
5. Replace the deterministic post-confirmation copy with a first-person message
   that says Nick has everything required, is preparing the official quote now,
   and will send it in the chat in a few minutes. Do not change actual processing
   or the customer-only three-minute delivery boundary.
6. Preserve catalog matching, media-first recommendations, fixed pricing,
   availability safeguards, correction precedence, idempotency, supersession,
   provider-confirmed state commits, staff email, notifications, and tenant
   isolation.
7. Update focused tests to verify runtime output and turn behavior rather than
   merely checking that source text exists. No real customer message may be sent.

## Tests

1. Render a complete summary in EN/NL/PAP/DE and assert the exact first-person
   opening and direct closing, localized human dates, canonical fields, and
   absence of the old robotic wording.
2. Drive a complete Ali intake, correction, explicit summary repeat, pending
   question, and valid confirmation through the turn planner. Assert one summary,
   no unchanged-summary loops, strict confirmation behavior, and the new
   post-confirmation quote-preparing message.
3. Build the live Ali prompt with a synthetic catalog and assert Nick identity,
   quote-purpose transparency, relevant needs/budget guidance, one-question
   behavior, and existing catalog/availability safeguards.
4. Run the focused Ali quote workflow, intake-dispatch, and latest-change suites.
5. Run the full `wtyj/tests/` suite and the normal CI/canary/production pipeline.

## Success Condition

A complete synthetic Ali WhatsApp intake produces one natural first-person
summary and, after explicit confirmation, one truthful quote-preparing message,
while all existing quote, media, timing, delivery, and tenant-isolation tests
remain green in production.

## Rollback

Revert the merge commit and redeploy through the normal pipeline. No schema or
data migration is involved; existing rental state and quote jobs remain valid.
