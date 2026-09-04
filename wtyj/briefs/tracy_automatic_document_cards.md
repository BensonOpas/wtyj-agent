# Automatic image cards and warm paid-booking closing

## Problem
The approved WhatsApp preview combines tropical artwork, an island emoji and an
Open PDF button. Automatic quotes and receipts still send plain file tiles and
the paid-booking message ends with a dense transport paragraph.

## Changes
Route this tenant's registered quote/receipt attachments through the image-card
sender. Validate the registered document, conversation and sending account;
leave unrelated attachments on their existing sender. Persist the complete
interactive payload and provider message ID so retries use the same body and
idempotency key. Delayed delivery reconciliation recognizes the card's provider
ID or exact document URL. Never claim delivery on acceptance alone.

The provider accepts an interactive object with type cta_url, image header,
body text (maximum 1024 characters), and action parameters display_text/url.
Cards are session messages; the existing tenant guard and open-window checks
remain mandatory. Do not send a separate photo or bare-file fallback.

Serve the bundled branding image from a versioned public endpoint. Customer PDF
buttons use a separate HMAC signing scope valid through 30 days after the trip,
with a minimum 30-day lifetime. Existing one-hour attachment and payment
signatures remain unchanged. Deleting a document revokes access to its card URL.

Keep the user's approved transactional wording and translations in client.json.
The receipt has short paragraphs, a pickup reminder, clear demo-payment wording
and a friendly offer to help. Titles include both sun and island emojis. No
additional model call is introduced; factual booking and payment snapshots
remain authoritative. Quote checkout links remain present in the card body.

## Tests
Exercise actual sender dispatch, ownership isolation, immutable retry payloads,
delayed confirmation, signed-link scope/expiry/revocation, localized receipt and
quote body limits, plus checkout and delivery regressions. Verify the deployed
image in an isolated database with mocked provider I/O so the user's clean-slate
conversation stays empty.

## Success
A confirmed quote and a completed demo payment each send one image card with a
working Open PDF button, and the paid-booking text ends by offering further help.

## Rollback
Restore the preceding image and client.json from the scoped release backup.
The additive card-delivery table can remain; existing booking, payment, document
and delivery records must not be discarded during a rollback.
