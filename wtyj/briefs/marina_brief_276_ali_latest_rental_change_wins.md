# BRIEF 276 — Ali latest rental change wins
**Status:** Executed | **Files:** `wtyj/agents/marina/marina_agent.py`, `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/agents/social/social_agent.py`, focused tests | **Depends on:** Briefs 270-275 | **Blocks:** issue 190

## Context

Carlos currently merges the model's complete extracted field set into stored Ali intake state. When a customer corrects a displayed summary, a stale resolved vehicle can therefore outrank the newly extracted category, and a generic correction with no supplied value can cause the unchanged summary to repeat. The same state ambiguity applies to every quote-relevant field.

## Why This Approach

Keep the existing single Claude call responsible for understanding natural EN/NL/PAP/DE customer language, and add one structured action that identifies only facts explicitly changed in the newest inbound message. Python validates and applies that action against the current Ali catalog, clears mutually exclusive stale vehicle state, preserves unrelated facts, and invalidates the prior summary confirmation. This avoids a second model call, Python free-text classification, and any second source of catalog truth.

## Instructions

1. Extend Marina's structured response with an optional `ali_rental_change` action. Use `apply` with only the canonical quote fields explicitly changed in the newest message, or `clarify` when the customer wants a change but supplies no usable new fact.
2. Validate vehicle/category and supplement changes against the authenticated current Ali catalog. A valid category replaces stale vehicle ID/name and vice versa. Unknown or ambiguous selections preserve the prior selection and use Carlos's one concise clarification reply.
3. Apply only named changes. Preserve all unrelated dates, locations, customer data, counts, supplements, comments, and conversation language. Support explicit supplement removal and special-request removal.
4. A real change clears the prior summary hash, confirmation state, and active quote pointer without mutating historical quote rows. The deterministic handler then emits exactly one corrected summary and requires a new explicit confirmation.
5. A clarification or no-op correction must not invoke the deterministic summary handler on that turn. Log only sanitized outcome, changed field names, and selection kind; never log message text, values, or PII.
6. Include driver age, passenger/luggage counts, and special requests in the deterministic four-language summary so corrections are visible before confirmation.
7. Preserve webhook replay protection, summary-hash quote idempotency, request-only availability, existing pricing, PDF, delivery, and customer-only three-minute delay behavior.

## Tests

- Stale exact vehicle plus new category resolves to the category only; stale category plus new exact vehicle resolves to the vehicle only.
- EN/NL/PAP/DE correction actions produce one corrected summary and change its hash.
- Dates, locations, driver age, passenger/luggage, name, supplements add/change/remove, and special requests replace only their named value while unrelated facts survive.
- Unknown vehicle and generic change requests preserve state and return one clarification without repeating the stale summary.
- A changed post-quote summary requires confirmation and creates a new immutable quote only once; the prior snapshot remains unchanged.
- Sanitized decision logs contain no message text or customer values.

## Success Condition

In production, the exact old Toyota plus new Van reproduction resolves to Van only, and an allowlisted synthetic WhatsApp correction receives one corrected summary before any replacement quote is generated.

## Rollback

Revert the issue 190 merge commit and redeploy. Existing stored summaries and immutable quote rows remain valid; the new optional structured action is ignored by prior code.
