# Mermaid demo-assumed availability and reservation state

## Scope

Create a durable Mermaid reservation aggregate and append-only event timeline.
For the demo, a valid confirmed summary transitions atomically from
`awaiting_summary_confirmation` to `demo_availability_approved` without calling
an availability provider.

Persist:

- tenant, conversation and customer bindings;
- normalized intake fields and language;
- catalog version and immutable monetary snapshot;
- state and optimistic revision;
- availability source `demo_assumed`;
- quote, payment and receipt references;
- actor, timestamps, idempotency keys and transition reasons.

Booking codes must be server generated, unique and human readable using the
`MER-DEMO-` prefix. The model must never create them.

## Acceptance

- Exactly one reservation exists per confirmed summary version.
- Replayed confirmations return the existing reservation.
- The demo makes no network call to Mermaid's reservation website.
- No wording claims seats were checked; the customer may be told that seats
  are available for the demo experience.
- Invalid/out-of-order transitions fail without partial writes.
- Cancellation before payment closes the demo reservation idempotently.
- Human takeover freezes automated mutation.
- Tenant isolation and concurrent confirmation tests pass.

## Rollback

Stop new transitions with the tenant feature flag. Preserve existing rows and
events for audit; do not destructively migrate them away.
