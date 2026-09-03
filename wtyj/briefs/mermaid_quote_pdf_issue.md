# Mermaid quote PDF and WhatsApp delivery

## Scope

Generate a polished, localized Mermaid quote PDF from the immutable reservation
snapshot and deliver it to the same WhatsApp conversation.

The PDF must be visibly labeled `DEMO QUOTE - NOT A VALID TICKET` and include:

- Mermaid branding;
- quote and reservation references;
- customer, date and guest composition;
- itemized prices, currency and total;
- included breakfast, drinks, BBQ, beach house, facilities, snorkel gear and
  beach chairs;
- optional pickup status;
- Fishermen's Pier, 06:45 arrival and approximately 15:20 island departure;
- towel, sunscreen, swimwear and medication checklist;
- verified trip notes plus clearly labeled demo cancellation and safety text;
- payment next step and quote validity.

Do not claim verified insurance coverage. Do not describe the quote as a paid
receipt, ticket or final confirmation.

## Acceptance

- Six localized PDFs render without clipping, overlap, broken glyphs or black
  squares.
- Amounts are copied from the immutable snapshot; the renderer performs no
  pricing calculation.
- Filename, hash and content type are stable and audited.
- One durable idempotent delivery job sends the PDF to the same conversation.
- A provider retry cannot create a second quote or duplicate accepted delivery.
- Visual PNG review and PDF text checks pass.

## Rollback

Disable `mermaid_quote_delivery`; preserve generated private PDFs and delivery
evidence according to existing retention rules.
