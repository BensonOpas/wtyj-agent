# Brief 276 — Ali vehicle discovery before personal details

**Status:** Implemented | **Files:** `wtyj/agents/marina/marina_agent.py`, `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/tests/agents/test_ali_quote_intake_dispatch.py` | **Depends on:** Briefs 157, 271, 275 | **Blocks:** Ali vehicle-first intake production behavior

## Context

Carlos had all required quote fields but no explicit intake priority. As a
result, a new customer could be asked for their name before seeing any useful
progress toward a suitable vehicle. The owner requires a premium conversation:
understand the rental need first, provide a catalog-grounded direction, and
only then request personal details.

## Goal

For Ali WhatsApp conversations, Carlos first discusses the vehicle, passenger
and relevant luggage needs, and rental dates. He acknowledges a named option or
recommends suitable current catalog options before asking for full name, driver
age, or any other personal detail.

## Scope

- Establish a highest-priority two-phase Ali intake order in the existing
  single Carlos call.
- Expose public seats, transmission, features, and category descriptions from
  the authenticated catalog for factual recommendations.
- Ask one concise question at a time and never repeat supplied facts.
- Keep direct price answers under Brief 275.
- Keep availability request-only and preserve deterministic quote generation,
  customer-only three-minute delivery, and idempotency.
- Do not add an availability calendar, document intake, UI, second model call,
  static reply generator, or Python language classifier.

## Why This Approach

The existing prompt already receives the complete conversation history and the
published catalog within the one Marina call. A stronger tenant-specific phase
contract plus factual public capability fields lets Carlos reason naturally in
all supported languages. Adding Python classifiers or hard-coded response
templates would duplicate language understanding, conflict with repository
rules, and make the conversation less human.

## Instructions

1. Introduce Carlos once on a genuinely new conversation, never on follow-ups.
2. If no selection is known, ask vehicle preference; when undecided, collect
   passenger count and only relevant luggage information before recommending.
3. Never re-ask a vehicle or any fact already supplied in the conversation.
4. Collect pickup and return dates during discovery, then acknowledge the
   selected option or offer only suitable catalog-grounded directions.
5. Ask for full name and then driver age only after a vehicle direction exists
   and dates are known. Never ask personal details in the first reply.
6. Never ask for the WhatsApp number; email is optional only for an emailed
   copy; identity documents remain outside round one. Show the captured
   WhatsApp number in the later deterministic confirmation summary.
7. Never claim availability. Use careful request-only direction language.
8. Apply the same phase order naturally in EN/NL/PAP/DE.

## Tests

1. Prompt contract makes vehicle discovery mandatory before personal details.
2. Undecided customers are routed through passenger count and relevant luggage
   one question at a time.
3. Named vehicles and supplied facts are not requested again.
4. Catalog prompt records contain seats, transmission, features, descriptions,
   rates, and no server IDs.
5. Recommendation wording remains request-only and catalog-grounded.
6. Existing direct-price, summary confirmation, quote generation, three-minute
   customer delivery, and replay tests remain green.

## Success Condition

In production, new Ali customers receive useful vehicle-first engagement in all
four languages and Carlos requests personal information only after a vehicle
direction and dates are established, without false availability or repeated
questions.

## Rollback

Revert the issue #177 commit and redeploy the previous production image. No
database or catalog rollback is required.

Tracking: GitHub issue #177.
