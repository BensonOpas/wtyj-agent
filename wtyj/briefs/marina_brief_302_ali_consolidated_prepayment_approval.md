# Brief 302 — Ali consolidated pre-payment approval
**Status:** Approved | **Files:** `agents/social/ali_reservation_v2.py`, `agents/social/ali_reservation_v2_automation.py`, `agents/social/ali_customer_dossier.py`, `agents/social/ali_reservation_v2_inbound.py`, `agents/social/webhook_server.py`, `dashboard/api.py`, `tests/agents/test_291_ali_reservation_v2.py`, `tests/agents/test_291_ali_reservation_v2_media.py`, `tests/agents/test_291_ali_reservation_v2_automation.py`, `tests/dashboard/test_241_ali_customer_dossier_api.py` | **Depends on:** Briefs 290-291 / FRD-006 | **Blocks:** GitHub issue #302 and the matching operator-dashboard control

## Context
Ali's V2 reservation flow currently pauses after the last customer document in
`agents/social/ali_reservation_v2.py:976-1047`, enters
`document_review_pending`, and requires documents to be individually marked
verified before `agents/social/ali_reservation_v2_automation.py:91-164` sends
the pre-contract. After the customer signs, the same automation module at
`agents/social/ali_reservation_v2_automation.py:172-224` immediately configures
and sends the payment link. This is the opposite of the approved owner flow:
Nick should collect each validated upload one by one without waiting for a
human, the customer should sign the pre-contract, and staff should then receive
one complete-file review before the payment-link message is released.

Normal document receipt currently creates no operator notification, which is
correct and must remain so. Technical storage/delivery failures still require a
hard attention item. The new consolidated review must be deduplicated on
signature replay and must not expose a second API path that can send payment
before approval.

## Why This Approach
Add explicit durable states for documents collected, pre-payment review pending,
and pre-payment approved. Durable states make the payment gate auditable and
allow a provider-send retry without asking the operator to approve the file
again. The final upload is acknowledged first in WhatsApp; only then does the
server send the pre-contract, preserving the customer-visible order.

Rejected alternative: silently reinterpret `documents_approved` and
`contract_signed` without new states. That would keep the diff smaller but make
the audit timeline lie and leave the existing payment-send endpoint impossible
to guard unambiguously. Also rejected: automatically verify every document.
Secure receipt is sufficient to advance, but verification is a human judgment
and must not be fabricated in stored status.

## Instructions
1. Extend the Ali-only V2 state machine in
   `agents/social/ali_reservation_v2.py:33-154` with
   `documents_collected`, `prepayment_approval_pending`, and
   `prepayment_approved`. Assign server-derived responsibility and next-action
   values. Route normal checklist completion to `documents_collected`; when a
   replacement is received after an immutable signed pre-contract, return the
   case directly to the consolidated review state.
2. In `agents/social/ali_customer_dossier.py:1434-1602`, continue storing each
   authenticated WhatsApp attachment privately with status `received`. Refresh
   the legacy identity roll-up after secure storage so dashboard data reflects
   receipt, but do not mark a document verified. Add one server-derived
   pre-payment readiness projection covering the required latest documents,
   signed pre-contract, approved availability, and configured payment route.
3. Replace per-document approval automation in
   `agents/social/ali_reservation_v2_automation.py` with an automatic
   collection-complete step that accepts `received`, `verified`, or
   `not_required` latest documents and sends the pre-contract. Retain the old
   `after_document_review` entry point as a compatibility alias for already
   queued cases.
4. Change signature automation so `contract_signed` creates
   `prepayment_approval_pending` and one deduplicated soft operator item. It
   must never configure or send a payment link. Add a staff-approval operation
   that validates the complete file, records durable `prepayment_approved`,
   resolves that exact operator item, and then sends the payment link with the
   existing provider idempotency key. A failed provider send must preserve the
   approved state for retry and create a hard delivery-attention item.
   Project that single approval into the legacy identity checklist aggregate
   without changing any individual document's `received` status, so the
   existing post-payment dossier and final-confirmation gates remain usable.
5. In `agents/social/ali_reservation_v2_inbound.py:42-102`, replace the obsolete
   "our team will review them now" final-upload copy with a concise transition
   to the pre-contract. In `agents/social/webhook_server.py:682-754`, run the
   automatic collection-complete step only after the secure-receipt
   acknowledgment has provider-confirmed delivery.
6. Add a strict authenticated endpoint in `dashboard/api.py:4520-5665` for the
   one complete-file approval. Require the V2 workflow revision. Route the
   existing payment-link send endpoint through the same approved-state guard so
   it becomes a retry surface, not a bypass.
7. Keep every change tenant-bound to `ali-car-rental`. Do not alter shared
   booking flows, other tenant configuration, or normal escalation behavior.

## Tests
1. Extend `tests/agents/test_291_ali_reservation_v2.py` to prove the new legal
   state sequence and that the payment clock still begins only after a
   provider-confirmed link.
2. Extend `tests/agents/test_291_ali_reservation_v2_media.py` to prove passport
   and ID-card uploads auto-advance to `documents_collected`, preserve
   `received` status, and return the new final-upload acknowledgment.
3. Replace the obsolete signature-auto-payment test in
   `tests/agents/test_291_ali_reservation_v2_automation.py` with behavioral
   tests proving signature replay creates one review and sends zero payment
   messages.
4. Add approval-path tests proving incomplete files and unconfigured
   per-reservation links fail closed; successful approval sends once; provider
   failure remains retryable without a second approval.
5. Add API coverage proving `/payment-link/send` returns a conflict before
   approval and the consolidated approval endpoint returns the refreshed
   customer file.

## Success Condition
For an Ali passport or ID-card journey, Nick collects every file without staff
intervention, sends the pre-contract after the final upload, creates exactly one
staff review after signature, and no server or dashboard API can send the
payment link until that one review is approved.

## Rollback
Revert the Brief 302 source commit and redeploy the prior image. No destructive
schema migration is introduced: the added V2 state values are text rows, and
existing reservation/document/contract/payment records remain intact. Cases
already in a new state can be moved to `technical_attention_required` for
manual handling before rollback if any are created during the deployment
window.
