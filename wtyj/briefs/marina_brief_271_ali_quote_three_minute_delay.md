# Brief 271 — Ali customer quote three-minute delivery boundary

**Status:** Implemented | **Files:** `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/tests/agents/test_ali_quote_workflow.py` | **Depends on:** Briefs 157, 271 correction | **Blocks:** Production Ali quote timing

## Context

The first implementation delayed the entire confirmed-quote workflow. That
incorrectly postponed pricing, PDF generation, staff email, and operator
notifications. The owner requires those internal actions to start immediately;
only the final customer WhatsApp quote attachment waits for the three-minute
boundary.

## Goal

For the `ali-car-rental` tenant, send the final customer WhatsApp quote no
earlier than three minutes after the customer confirms the complete rental
summary. Keep the conversation and all quote preparation running normally.

## Scope

- Derive eligibility from the immutable `confirmed_at` timestamp already stored
  on the idempotent quote record.
- Generate pricing and the PDF immediately.
- Send staff email and operator notifications immediately.
- Gate only the final customer WhatsApp quote attachment behind the
  three-minute boundary.
- On service restart, resume pending work and wait only the remaining portion
  of the delay.
- Preserve one-quote-per-conversation-and-summary idempotency.
- Do not add a queue service, schema migration, new customer copy, or new
  configuration surface for this fixed tenant rule.

## Why This Approach

The existing immutable `confirmed_at` value is already the durable clock and
the existing quote statuses already make resumed work idempotent. Moving the
wait directly in front of `send_whatsapp` at
`wtyj/agents/social/ali_quote_workflow.py:571` is the smallest reliable fix.
The rejected alternative was a queue or scheduled-job service: it would add
operational state without improving the fixed three-minute tenant rule.

## Instructions

1. Keep pricing, PDF creation, staff email, and operator alerts before the wait
   in `wtyj/agents/social/ali_quote_workflow.py:538`.
2. Calculate the remaining customer-only delay from persisted `confirmed_at`
   immediately before customer delivery in
   `wtyj/agents/social/ali_quote_workflow.py:571`.
3. Preserve the accepted WhatsApp, sent email, notification, and quote
   idempotency guards in `wtyj/agents/social/ali_quote_workflow.py:559`.
4. Prove the timing and replay behavior in
   `wtyj/tests/agents/test_ali_quote_workflow.py:162`.

## Tests

1. Pricing, PDF generation, staff email, and internal notifications do not wait.
2. A newly confirmed quote waits 180 seconds before the customer WhatsApp quote
   is sent.
3. A quote resumed 60 seconds after confirmation waits only 120 seconds before
   customer delivery.
4. A quote resumed at or after 180 seconds sends to the customer immediately.
5. Duplicate confirmation continues to produce one quote record and one worker.
6. Disabled automation fails closed without waiting or sending.
7. Existing human confirmation and 30-minute preparation copy remain unchanged.

## Success Condition

Production pricing, PDF, staff email, and operator alerts happen immediately,
while exactly one customer WhatsApp quote is sent at or after `confirmed_at +
180 seconds`, including after restart.

## Rollback

Revert the correction commit and redeploy the previous production image only if
customer delivery regresses; do not leave the earlier whole-workflow delay live.

Tracking: GitHub issue #171.
