# BRIEF 290 — Ali post-quote reservation and confirmation V1
**Status:** Approved by owner | **Files:** `wtyj/agents/social/ali_reservation_workflow.py`, `wtyj/agents/social/ali_reservation_confirmation_pdf.py`, `wtyj/agents/social/ali_quote_delivery.py`, `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/agents/social/zernio_dm_client.py`, `wtyj/agents/social/social_agent.py`, `wtyj/agents/marina_agent.py`, `wtyj/dashboard/api.py`, focused tests | **Depends on:** Briefs 280, 285, 286, 289 | **Blocks:** dashboard frontend controls and real external payment/document integrations

## Context

Ali now takes a WhatsApp customer from vehicle discovery through a delivered
official quote. The live post-quote behavior is only a broad natural-language
acceptance heuristic and a soft staff notification. It does not create a
durable reservation request, record availability decisions, track required
checks, or produce a truthful confirmation. The existing payment module is a
demo stub and the generic upload route is not suitable for identity documents.

The owner approved a bounded V1 in which the customer explicitly chooses what
to do after receiving the quote, staff verifies availability and requirements,
and the system confirms only after every required condition is recorded.

## Why This Approach

Use signed, quote-bound WhatsApp actions and a separate durable reservation
state machine. A customer tapping **Reserve this car** requests an availability
check; it never means the car is booked. Staff remains the authority for
availability, identity, agreement, and payment verification. This keeps the
customer experience fast while preventing Nick from making claims that the
system cannot prove.

Store only verification statuses in V1. Do not collect licenses, passports,
signatures, payment screenshots, document numbers, or arbitrary customer URLs.
Do not use the demo payment stub. Keep the work on the isolated
`codex/ali-post-quote-v1` branch and avoid Builder's vehicle-carousel recovery
sections.

## Instructions

1. Add a tenant- and quote-bound `ali_reservations` table plus append-only
   `ali_reservation_events`. A quote may have at most one reservation. Persist
   conversation id, Zernio account id, status, availability decision, explicit
   checklist statuses, staff audit fields, reference, confirmation delivery
   state, and timestamps. Never put this truth in resettable conversation flags.
2. Implement states `availability_pending`, `requirements_pending`,
   `alternative_required`, `declined`, `ready_to_confirm`, `confirmed`,
   `cancelled`, and `superseded`. Use `BEGIN IMMEDIATE`, expected-state checks,
   idempotent repeated actions, and append an audit event for every transition.
3. After the quote PDF is provider-confirmed, send a separate three-button
   WhatsApp control: **Reserve this car**, **Change something**, and
   **Ask a question**. Sign each payload with the existing Ali secret and bind
   action, conversation id, account id, quote public id, quote snapshot id, and
   control version. Use separate stable idempotency keys and record control
   delivery independently from PDF delivery.
4. Resolve valid, repeated, stale, and invalid post-quote postbacks before the
   one Claude call. Only the signed Reserve action, or exact `RESERVE` fallback,
   may create a reservation. Reserve replies that availability is being checked.
   Change asks what should change without superseding the quote until a concrete
   change arrives. Question preserves the quote and lets the normal one-model
   path answer it. Remove broad post-quote `yes` acceptance.
5. Inject canonical quote/reservation context for ordinary post-quote messages.
   Nick must never claim availability, document approval, payment, or booking
   confirmation unless persisted state proves it.
6. Add authenticated Ali-only backend routes to list/read reservations, record
   approve/alternative/decline availability decisions, update checklist
   statuses, and confirm. Confirm atomically only when availability is approved
   and every required checklist item is `verified` or `not_required`.
7. On successful confirmation create an immutable booking reference and an
   informational confirmation PDF containing the reservation and quote
   references, final vehicle, rental dates and locations, pickup details,
   confirmed status, and issue date. It is not a rental agreement or proof of
   payment. A send failure does not undo confirmation; persist the failure and
   alert staff.
8. Expose post-quote status, checklist summary, reference, and next action in
   the Quote Leads read model without changing existing filters or counts.
9. Keep reminders in the persisted model but fail closed until an approved
   WhatsApp template and pickup time are configured. Never send free-form
   reminders outside the 24-hour WhatsApp window.
10. Preserve the quote-generation delay, vehicle carousel/picker behavior,
    quote pricing snapshot, quote PDF, staff email, operator alerts, tenant
    isolation, and one-Claude-call architecture.

## Tests

1. Signed controls round-trip, reject tampering/cross-tenant/cross-conversation
   use, reject superseded quotes, and handle repeated taps idempotently.
2. Reserve creates exactly one `availability_pending` reservation and never
   says booked or confirmed. Exact `RESERVE` works; ordinary yes does not.
3. Change and question do not create a reservation or mutate the quote.
4. Quote PDF and post-quote-control delivery use separate idempotency and status.
5. Staff decision and checklist routes enforce authentication, Ali tenant,
   legal transitions, allowed status values, and append-only audit events.
6. Confirmation is blocked until availability and every required check pass;
   successful repeated confirmation returns the same reference and PDF.
7. Confirmation delivery failure keeps the reservation confirmed and exposes
   staff attention state.
8. Quote Leads includes the reservation summary without leaking sensitive data.
9. Existing quote, carousel, social-agent, dashboard, and full repository tests
   remain green.

## Success Condition

A delivered Ali quote presents three explicit customer actions. Reserving
creates a durable staff-visible availability request. Staff can approve it,
record the manual/external checklist, and confirm exactly once. The customer is
never told the car is booked before those checks pass, and the confirmed case
has one stable reference and informational confirmation PDF.

## Rollback

Disable post-quote controls in Ali tenant configuration, revert the Brief 290
merge commit, and redeploy. Preserve reservation and audit rows for traceability;
do not delete them during rollback.
