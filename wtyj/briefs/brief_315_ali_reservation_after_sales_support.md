# BRIEF 315 — Premium Ali reservation after-sales handoff
**Status:** Executed | **Files:** `wtyj/agents/social/ali_quote_delivery.py`, `wtyj/agents/marina/marina_agent.py`, `wtyj/tests/agents/test_290_ali_reservation_workflow.py`, `wtyj/tests/agents/test_ali_quote_intake_dispatch.py` | **Depends on:** Ali reservation confirmation delivery and persisted post-quote truth | **Blocks:** None

## Context
The confirmed-reservation WhatsApp delivery attached the customer's PDF but ended after three terse lines. It did not explain what happens before pickup, what the customer should bring on arrival, how to report changed arrival details, how to reach Ali, or how to request copies by email. That made a completed rental feel transactional instead of reassuring.

## Why This Approach
The after-sales handoff belongs in the deterministic reservation-confirmation delivery because it is sent exactly once only after persisted status proves the reservation is confirmed. This prevents the model from improvising confirmation, contact, or arrival claims. Nick's prompt handles only the customer's subsequent response to the optional email offer.

The attached PDF remains the authoritative confirmation document. The WhatsApp caption adds concise operational guidance and direct support contacts without inventing opening hours, meeting points, fees, or other location-specific promises.

## Instructions
1. Keep the reservation reference and confirmation PDF attachment.
2. Add a warm confirmed-state message and a three-item arrival checklist: team handover contact, original licence and identity document, and notice of changed travel or pickup details.
3. Reassure the customer that no further action is required immediately.
4. Publish Ali's configured support email and a human-readable WhatsApp number, with safe Ali fallbacks.
5. Offer optional emailed copies of the reservation documents and agreements and ask for the customer's preferred email address.
6. After confirmation, capture an explicitly supplied email, acknowledge it warmly, never restart intake, never ask twice, and never claim email delivery before it occurs.
7. Preserve English, Dutch, Papiamentu, and German confirmation support.

## Tests
- A successful confirmed-reservation delivery contains the warm confirmation, arrival steps, support contacts, and optional email question.
- All four supported languages retain the after-sales sections and stay within WhatsApp's document-caption limit.
- The confirmation PDF name and idempotency key remain unchanged.
- Delivery success still persists as `accepted`; existing failure-without-rollback coverage remains authoritative.

## Success Condition
Every newly confirmed Ali customer receives a reassuring, actionable after-sales handoff and can optionally provide one email address for document copies without re-entering the rental flow.

## Rollback
Revert the Brief 315 commit and redeploy through the normal WTYJ pipeline. No data or schema migration is involved.
