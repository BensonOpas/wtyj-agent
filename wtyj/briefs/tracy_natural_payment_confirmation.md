# Tracy natural approval and payment handoff
**Status:** Tested; deployment pending | **Files:** Mermaid reservation workflow, understanding prompt, response-policy copy and booking UX tests | **Depends on:** exact-age release `tracy-age-1b5d54f` | **Blocks:** natural confirmation-to-payment flow

## Context
A guest replied to a complete summary with “Yes, looks good, where and when do I pay?” Tracy classified the question as a request for recorded payment status. She did not accept the clear approval, create the quote or provide checkout, and then repeated a technically true but robotic sentence about no completed payment.

## Decision
Treat a clear natural approval followed only by a procedural payment question as confirmation when the displayed summary is still awaiting approval and no booking facts changed. The server then creates the immutable quote, one-page PDF and checkout link, which directly answer the question. Questions without approval and messages containing a correction, uncertainty or new condition do not confirm.

Replace the no-reservation payment-status wording with a concise explanation of the next step in all six supported languages. Keep payment completion dependent on the signed demo callback and retain one model call per inbound message.

## Tests
Replay the exact guest sentence with the model selecting payment status and verify a quote PDF, pending reservation and checkout link are created. Verify a payment question without approval does not create a reservation and receives the useful next-step reply. Retain the confirmation, cancellation, payment-record, delivery and review-policy suites.

## Current Conversation Repair
The missed approval was repaired once using the already displayed and explicitly approved details. Reservation `mer_e2f8b106dfc6418cb22c69e9f8a7a502` is in `demo_payment_pending`; the one-page quote PDF and short demo payment link were sent through the original Mermaid WhatsApp account with provider-confirmed delivery. The known nine-month infant age and snapshotted USD 525 total are preserved.

## Rollback
Restore the prior Mermaid image and response-policy configuration while preserving the live database, current reservation, documents and message history.
