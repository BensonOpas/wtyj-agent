# Brief 271 — Ali quote three-minute delay

## Goal

For the `ali-car-rental` tenant, begin automatic quote processing exactly three
minutes after the customer confirms the complete rental summary. Keep the
existing public promise that the quote arrives within 30 minutes.

## Scope

- Derive eligibility from the immutable `confirmed_at` timestamp already stored
  on the idempotent quote record.
- Gate the pricing request, PDF generation, WhatsApp attachment, staff email,
  and operator notifications behind the same three-minute boundary.
- On service restart, resume pending work and wait only the remaining portion
  of the delay.
- Preserve one-quote-per-conversation-and-summary idempotency.
- Do not add a queue service, schema migration, new customer copy, or new
  configuration surface for this fixed tenant rule.

## Acceptance tests

1. A newly confirmed quote waits 180 seconds before the Ali pricing client is
   called.
2. A quote resumed 60 seconds after confirmation waits only 120 seconds.
3. A quote resumed at or after 180 seconds processes immediately.
4. Duplicate confirmation continues to produce one quote record and one worker.
5. Disabled automation fails closed without waiting or sending.

Tracking: GitHub issue #171.
