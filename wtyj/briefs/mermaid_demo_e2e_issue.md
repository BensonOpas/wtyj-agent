# Mermaid end-to-end demo verification and controlled activation

## Scope

Prove the complete synthetic customer journey without contacting a real
customer or accepting payment.

Required journeys:

- six supported languages;
- new inquiry through paid/demo-booked;
- customer supplies several facts in one message;
- correction after summary;
- question while confirmation is pending;
- duplicate inbound and duplicate payment callback;
- payment cancel/failure and retry;
- human takeover;
- customer cancellation;
- provider delivery ambiguity and recovery;
- cross-tenant access attempt.

## Acceptance

- Full repository test suite is green with no reduced denominator.
- Synthetic WhatsApp canary receives one quote PDF, one simulated payment link,
  one warm booking message and one payment receipt.
- Booking code and all amounts reconcile across chat, PDF, receipt and dashboard.
- No availability provider is called.
- No real payment fields, charge, customer contact or reminder send occurs.
- Logs and audit events contain references/statuses but no sensitive payloads.
- Feature-flag rollback is rehearsed and documented.

## Rollout

1. Enable for allowlisted synthetic conversations only.
2. Run all six language journeys.
3. Verify dashboard evidence and artifact rendering.
4. Keep real-customer delivery disabled until an explicit owner go-live action.

## Rollback

Disable all Mermaid reservation demo flags. Leave additive evidence intact.
