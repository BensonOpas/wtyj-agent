# BRIEF 342 — Authoritative pickup-question facts
**Status:** Deployed and verified at f220c3e; A4/A8 acceptance holds remain | **Files:** `mermaid_understanding.py`, `mermaid_response_policy.py`, `mermaid_reservation_workflow.py`, tenant `response_policy.json`, pickup-question tests | **Depends on:** 2286d9f and issue 342 | **Blocks:** candidate factual acceptance

## Context
The isolated real-model audit's Papiamentu BASE-023 turn 3 asked how much pickup
costs from a hotel and explicitly said pickup had not been chosen. The saved
party was three adults, one child and one infant. The response said “Pa un
grupo di 5 persona, un auto tin kapasidat pa tur kuater” — five passengers but
space for all four. The configured five-seat car and USD 75 price were correct;
generated passenger prose was not. The original baseline evidence is untouched.

## Why This Approach
The parent explicitly authorized a structured pickup-pricing route and
configuration-owned critical wording. The model understands the enquiry; Python
uses existing catalog pickup selection, passenger labels and immutable quoted
money. Reject free-text matching and a prompt-only arithmetic reminder: neither
makes the displayed passenger count authoritative. Do not replace ordinary FAQ
answers. For a mixed pickup/FAQ message, the optional schema-validated
`other_question_reply` carries only the separate non-transport FAQ answer;
ordinary generated pickup prose is discarded. Native Papiamentu review remains
pending rather than treating these factual corrections as language approval.

## Instructions
1. Extend the single-call schema and prompt in
   `wtyj/agents/social/mermaid_understanding.py:23` with `pickup_pricing` for
   pickup price, capacity or scheduled-time enquiries. The route does not
   imply pickup consent; an explicit add-pickup request may still supply it.
2. Render current draft counts through existing `pickup_quote`, `party_text`
   and `pickup_label` in `wtyj/agents/social/mermaid_response_policy.py:110`.
   Include every age band in the passenger total. Unknown bands cannot yield
   a selected vehicle: present configured options and ask for the missing party.
3. Prefer an existing reservation's intake and monetary snapshot to draft or
   current prices. Legacy amounts cannot invent a vehicle. A booking with no
   included pickup stays excluded; current options are informational and adding
   transport needs review. Neither the reply helper nor route mutates money.
4. Integrate after higher-priority security, human, cancellation and calendar
   branches in `wtyj/agents/social/mermaid_reservation_workflow.py:686`. Preserve
   review-blocked decisions, normal intake confirmation and operator controls.
5. Put the six-language wording only in tenant
   `clients/mermaid/config/response_policy.json`; derive all times, capacities,
   currencies and prices from their existing authorities.

## Tests
The original BASE-023 reply was replayed with its original `status_request=none`
before implementation and failed on the contradictory “tur kuater”. The same
fixture with the new selector now returns the actual party and vehicle facts.
Focused coverage includes six-locale five/car, six/van, unknown infant count,
existing excluded pickup and paid immutable snapshot behavior; newly corrected
draft counts; legacy flat snapshots; over-capacity enquiries; valid mixed
consent/FAQ; ordinary FAQ preservation; security/human/cancellation/review
priority; and malformed optional-answer same-event recovery. Model/provider
calls are mocked, with real isolated SQLite for durable state. The combined
pickup, vehicle, authoritative-policy, model-recovery and soft-review gate passed
211 tests. An independent agent reviewed the final source/config diff and reran
all 46 new pickup checks successfully, with no actionable findings.

## Success Condition
A pickup enquiry gives consistent passenger count, capacity, price, scheduled
time and return coverage without changing transport choice or existing money.

## Rollback
Revert this commit before the combined release, or restore its predecessor
image and backed-up policy after deployment. No customer-state repair is needed.
