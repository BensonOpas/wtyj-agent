# BRIEF 326 — Show provider-confirmed quote delivery in Ali's dashboard chat
**Status:** Approved by owner | **Files:** `wtyj/agents/social/ali_quote_delivery.py`, `wtyj/shared/state_registry.py`, focused tests | **Depends on:** Brief 285, Brief 325 quote delivery recovery | **Blocks:** none

## Context

Ali's quote pipeline can deliver the official PDF successfully and mark
`ali_quotes.whatsapp_status = accepted`, while the dashboard transcript still
ends at “I’m preparing your quote.” Federico and Ferla both have accepted quote
rows but no transcript row containing their quote reference. The customer-side
delivery is correct; the authenticated operator view is incomplete because the
production quote adapter never commits the provider-confirmed outbound caption
to `whatsapp_threads`.

## Requirement

The dashboard chat must show a clear, localized confirmation that the official
quote was sent, including the quote reference and existing pricing/validity
caption. It may appear only after WhatsApp confirms delivery. This change must
not send an additional WhatsApp message.

## Instructions

1. Add an exactly-once outbound transcript writer backed by the existing
   `(phone, source_message_key)` unique index.
2. Make the quote caption's first line explicitly say that the quote was sent
   successfully in every supported Ali locale.
3. After `send_dm_reply_with_attachment()` returns provider-confirmed success,
   write that same caption into the dashboard transcript as an assistant
   message using a deterministic key derived from the immutable quote id.
4. Never write the confirmation when provider delivery fails or is
   unconfirmed.
5. A retry or process restart must not create a duplicate dashboard message.
6. Backfill only accepted quote rows whose conversation history does not
   already contain that quote reference. Do not send customer messages and do
   not change quote, reservation, customer, document or payment state.

## Tests

1. The outbound transcript helper inserts once and treats the same source key
   as an already-satisfied success.
2. Provider-confirmed PDF delivery records one dashboard assistant message
   containing the quote reference.
3. A failed PDF delivery records no dashboard confirmation.
4. Repeating the same accepted delivery does not duplicate the transcript.
5. Every supported locale uses explicit sent-successfully wording.
6. Run the focused quote/reliability tests and the full backend suite.

## Success Condition

The operator can open any Ali conversation and immediately see a truthful
“official quote sent successfully” message after the PDF delivery, while no
false or duplicate confirmation can appear.

## Rollback

Revert Brief 326 and redeploy. Existing backfilled transcript rows can be
removed by their `ali-quote-delivered:<public_id>` source key without touching
customer messages or rental records.
