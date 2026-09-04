# Tropical artwork in Tracy PDFs

The user requested blue sea, white beach, sunlight and the excursion boat in
the PDF. Previously the quote and receipt displayed only a small corner photo;
the WhatsApp document tile in the user's screenshot appeared blank.

Use bundled generated tropical artwork with a full-width banner in both PDFs.
The quote uses a shallow crop favoring the boat so all details remain on one
page; the receipt uses the complete panorama. Keep typography, monetary
snapshots, booking data, delivery jobs, and demo payment behavior intact.

The image is decorative branding and remains tagged as an artifact. The asset
manifest records the generation tool, prompt and original boat reference.
The original photo is retained. No external image download is needed at runtime.

Zernio's documented send-message API accepts a file URL, name, and attachment
type; it does not expose a document-thumbnail override. This change guarantees
an image inside the PDF, not a custom thumbnail in the WhatsApp document tile.
An image message can separately display artwork in WhatsApp, but is outside
this presentation change.

Validation: existing localized quote and PDF accessibility checks (29 passing),
including maximum-length customer/address fields, all price rows, one-page
output, embedded image, complete policy text, language and structural tags.
Rendered and visually inspected quote and receipt using the customer's existing
booking. The exact release image also passed 12 long-field quote/receipt renders
across six languages using production ReportLab 4.4.3.

Deployed as `wtyj-agent:tracy-tropical-8fba1de`, digest
`sha256:816a25caf5c67d7ac394166ba9e99caa8c0232bbe48bd9ec1ae283ee46bcc21d`.
Health and watchdog checks pass. The 37 messages, reservation, payment, two
issued-document records and two delivery jobs were preserved, along with six
other tenant containers. Existing delivered attachments remain immutable;
new documents use the new artwork. Rollback backup:
`/root/backups/tracy-tropical-8fba1de`.

References:
- https://docs.zernio.com/messages/send-inbox-message
- https://docs.zernio.com/platforms/whatsapp/inbox
