# BRIEF 283 — Ali summary confirmation eligibility
**Status:** Approved | **Files:** `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/agents/social/social_agent.py`, `wtyj/tests/agents/test_ali_quote_intake_dispatch.py`, `wtyj/tests/agents/test_ali_latest_change_orchestration.py` | **Depends on:** Briefs 276, 279, 280; GitHub issue #212 | **Blocks:** none

## Context

Two production Ali conversations reached complete, catalog-valid rental state but
created no current quote. In one sequence, a provider-confirmed summary was followed
by a normal logistics question. The answer was committed as `agent_reply`, which
moved the phase to `DISCOVERY` and cleared the delivered-summary hash. A later
deterministically accepted affirmative therefore failed closed as
`summary_not_delivery_eligible`. In the other sequence, model-extracted quote fields
were merged during a pure affirmative turn even though no validated
`ali_rental_change` existed. The resulting hash no longer matched the delivered
summary. Both paths reused model wording that promised a quote even though no quote
row was created.

## Why This Approach

Keep Brief 280's provider-confirmed summary hash as the decision anchor, but preserve
that anchor across only an ordinary, non-changing question. A validated correction,
recommendation, rejection, escalation, or other discovery transition still clears
eligibility exactly as before. Freeze quote-relevant model extraction on a
deterministically pure affirmative; explicit changes continue through the existing
validated `ali_rental_change` and catalog-selection paths. If an affirmative is not
eligible, show the current deterministic summary instead of trusting a model reply
that may falsely promise quote creation.

Rejected alternatives: confirming from conversational wording alone would bypass
provider delivery; keeping every non-summary reply eligible would resurrect rejected
or superseded summaries; adding another Claude call would violate the one-call rule;
and manually repairing the two live rows would hide the state-machine defect.

## Instructions

1. In `wtyj/agents/social/social_agent.py:1424-1539`, identify a pure affirmative
   with the existing deterministic `confirmation_decision()` helper. When Ali is
   configured and no validated customer change or native catalog selection is being
   applied, do not merge model-extracted quote fields on that turn. Also protect an
   already presented summary from opportunistic quote-field extraction during an
   ordinary `ask_question` turn. Continue merging non-quote metadata normally.
2. In `wtyj/agents/social/social_agent.py:1736-1742`, make a deterministically pure
   affirmative the effective `confirm_summary` intent unless a real validated
   change or recommendation owns the turn. Do not add a new language classifier or
   another model call.
3. In `wtyj/agents/social/ali_quote_workflow.py:1896-1911`, keep a non-changing
   `ask_question` in `SUMMARY_PRESENTED` when its current draft still matches the
   provider-delivered summary. All validated changes and discovery/recommendation
   paths continue to invalidate the old summary.
4. In `wtyj/agents/social/ali_quote_workflow.py:614-624`, preserve the existing
   presented-summary hash/version and awaiting flag when a provider-confirmed
   `agent_reply` commits in `SUMMARY_PRESENTED`. Do not create those fields here;
   they must already exist from a provider-confirmed summary send.
5. In `wtyj/agents/social/ali_quote_workflow.py:1930-2004`, gate confirmation on
   deterministic affirmative recognition, `SUMMARY_PRESENTED`, and an exact match
   between the current summary and the persisted provider-presented hash. The most
   recent delivered kind may be the intervening question answer because the
   provider-presented hash remains the anchor. For an accepted but ineligible
   affirmative outside a terminal quote phase, return one deterministic fresh
   summary; never reuse model wording that claims the quote is being prepared.
6. Keep logs limited to reason codes, changed field names, phases, and hash/id
   prefixes. Do not log customer text, identity, rental dates, locations, or full
   identifiers. Do not mutate or message real customer conversations during tests.

## Tests

1. Complete intake → provider-confirmed summary → ordinary question → delivered
   answer → affirmative creates exactly one quote for the unchanged summary.
2. Provider-confirmed summary → pure affirmative with conflicting model-extracted
   quote fields preserves the stored fields and creates exactly one quote.
3. A validated change contained in a question invalidates the old summary and emits
   one corrected summary before any confirmation can create a replacement quote.
4. An accepted but ineligible affirmative emits a deterministic fresh summary with
   no quote promise and creates no quote row.
5. Provider-send failure still creates no presented-summary eligibility. Duplicate
   confirmation/action replay remains idempotent.
6. Update the existing Brief 280 transition matrix to distinguish a harmless
   question from recommendation/rejection/change invalidation. Run the focused Ali
   workflow/intake/orchestration tests and then `python3 -m pytest wtyj/tests/ -q`.

## Success Condition

An unchanged, provider-delivered Ali summary remains confirmable after Carlos answers
one or more ordinary questions; pure affirmatives cannot mutate the quote draft; and
no ineligible confirmation can tell a customer that a quote is coming when no quote
was created.

## Rollback

Revert the Brief 283 merge commit and redeploy through the normal pipeline. No schema
or destructive migration is introduced. If production confirmation behavior becomes
uncertain, disable Ali quote automation while preserving stored conversations and
immutable quote rows, restore the previous image, and re-enable after health checks.
