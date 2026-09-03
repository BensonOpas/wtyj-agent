# Mermaid WhatsApp reservations demo - controlling epic

## Outcome

Deliver a Mermaid-only demonstration in which TRACY takes a customer from the
first Klein Curacao question to a completed simulated payment and a WhatsApp
payment receipt with a unique demo booking code. The customer stays in the
WhatsApp conversation for discovery, intake, confirmation, quote delivery and
post-payment guidance. A payment-only demo page may open from WhatsApp, but it
must not repeat the reservation form.

## Product principles

- TRACY answers the customer's latest question first and asks one useful
  reservation question at a time.
- TRACY detects and replies in Dutch, German, English, Spanish, Papiamentu or
  Portuguese.
- The tone is warm, energetic, reassuring and appropriate for a customer who
  is excited about a tropical island day trip.
- The demo assumes seats are available. It performs no external availability
  check and records that the approval source was `demo_assumed`.
- Prices and published trip facts come from one Mermaid demo catalog.
- The quote PDF is delivered to the same WhatsApp conversation.
- Payment is simulated. No real card data or money is accepted.
- After simulated payment, TRACY sends a receipt with a server-generated demo
  booking code; there is no second final-confirmation PDF.
- Reminder scheduling and proactive reminder sends are out of scope.
- Every retry is idempotent and tenant isolated. No behavior changes for Ali,
  Roberto/Despertares or any other tenant.

## Ordered delivery issues

- [x] [#327 Mermaid demo catalog and tenant feature controls](https://github.com/BensonOpas/wtyj-agent/issues/327) — implemented in PR #334
- [x] [#328 Multilingual natural reservation intake and canonical confirmation](https://github.com/BensonOpas/wtyj-agent/issues/328) — implemented in PR #334
- [x] [#329 Demo-assumed availability and durable reservation state machine](https://github.com/BensonOpas/wtyj-agent/issues/329) — implemented in PR #334
- [x] [#330 Mermaid quote PDF generation and same-chat delivery](https://github.com/BensonOpas/wtyj-agent/issues/330) — implemented in PR #334
- [x] [#331 Simulated payment checkout, verified callback and receipt/booking code](https://github.com/BensonOpas/wtyj-agent/issues/331) — implemented in PR #334
- [x] [dashboard #152 Mermaid reservation visibility](https://github.com/unboks-org/unboks-dashboard-api/issues/152) — implemented in dashboard PR #153
- [x] [#333 Full synthetic WhatsApp journey, safety verification and controlled rollout](https://github.com/BensonOpas/wtyj-agent/issues/333) — implemented in PR #334

## Mermaid demo lifecycle

```text
inquiry
-> collecting_details
-> demo_availability_approved
-> awaiting_summary_confirmation
-> quote_ready
-> quote_sent
-> demo_payment_pending
-> demo_paid
-> booked
```

Correction, question, cancellation, human takeover and technical-attention
paths must not be mistaken for confirmation or payment.

## Definition of done

- A synthetic customer completes the entire flow in each supported language.
- Required details are asked once and stored structurally.
- The customer confirms one canonical summary.
- One immutable price snapshot and one branded demo quote PDF are created.
- The PDF is accepted by the configured WhatsApp provider for the same chat.
- The payment-only demo page cannot charge money or accept real card data.
- One signed callback moves the reservation to `demo_paid` exactly once.
- One payment receipt and one unique `MER-DEMO-*` booking code are delivered.
- The dashboard displays the conversation, reservation stage, quote, payment
  status and timeline without exposing another tenant.
- Duplicate webhooks, customer confirmations, payment callbacks and delivery
  retries do not duplicate any business record or customer message.
- No reminder is scheduled or sent.

## Dependencies

Depends on the Mermaid tenant foundation in BensonOpas/wtyj-agent issue #323
and PR #324. Implementation may be developed as a stacked branch but must be
rebased on the merged Mermaid foundation before final merge.

## Out of scope

- Real seat inventory or availability holds.
- Real payment provider credentials, money movement, refunds or chargebacks.
- Production insurance/legal approval.
- Proactive reminders or attempts to bypass Meta's 24-hour rules.
- Changes to Mermaid's official website or official social accounts.
- Contacting real customers during testing.

## Rollback

Disable the Mermaid-only `mermaid_reservation_demo` and
`mermaid_demo_payment` feature flags. Keep additive records for audit and
diagnosis; do not delete customer or payment evidence as part of rollback.
