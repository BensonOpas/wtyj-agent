# Brief 271 — Ali quote three-minute delay

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

## Acceptance tests

1. Pricing, PDF generation, staff email, and internal notifications do not wait.
2. A newly confirmed quote waits 180 seconds before the customer WhatsApp quote
   is sent.
3. A quote resumed 60 seconds after confirmation waits only 120 seconds before
   customer delivery.
4. A quote resumed at or after 180 seconds sends to the customer immediately.
5. Duplicate confirmation continues to produce one quote record and one worker.
6. Disabled automation fails closed without waiting or sending.

Tracking: GitHub issue #171.
