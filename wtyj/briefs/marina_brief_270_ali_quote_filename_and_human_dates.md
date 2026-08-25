# BRIEF 270 — Ali quote filename and human-readable dates

**Status:** Executed | **Files:** `wtyj/agents/social/ali_quote_presentation.py`, `wtyj/agents/social/ali_quote_delivery.py`, `wtyj/agents/social/ali_quote_download.py`, `wtyj/agents/social/ali_quote_pdf.py`, `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/agents/social/zernio_dm_client.py`, `wtyj/tests/agents/test_ali_quote_presentation.py`, `wtyj/tests/agents/test_ali_quote_workflow.py`, `wtyj/tests/social/test_zernio_attachment_send.py` | **Depends on:** merged Ali quote delivery and Zernio WhatsApp document endpoint | **Blocks:** polished live Ali quote acceptance

## Context

A live Ali quote reached the customer, proving the confirmed-summary-to-PDF path works, but WhatsApp displayed the document as `Namnlös` (Untitled). The Zernio REST payload currently sends `attachmentUrl` and `attachmentType: file` without a recipient-visible filename. The same message exposes raw machine dates: the confirmation summary uses `YYYY-MM-DD`, and the delivered quote message prints the raw UTC `expiresAt` value.

Zernio's current send-message request supports the following document fields:

```json
{
  "accountId": "string",
  "message": "string",
  "attachmentUrl": "https://public.example/quote",
  "attachmentType": "file",
  "attachmentName": "Report.pdf"
}
```

For WhatsApp URL-based document sends, `attachmentName` controls the recipient-visible filename. Without it, WhatsApp derives a name from the URL and can show Untitled.

## Why This Approach

Add one pure presentation module for deterministic filenames and localized dates, then use it at every Ali quote surface. The filename will be `Ali-Car-Rental-Quote-<customer>-<issue-date>-<unique-reference>.pdf`; the existing immutable quote reference supplies the unique official identifier, so no second random ID or database field is needed. Dates remain authoritative ISO values in storage and API requests; only customer/staff presentation changes.

Rejected alternatives: relying only on HTTP `Content-Disposition` does not solve Zernio's WhatsApp attachment metadata; putting the customer name in the signed URL leaks PII into URLs and logs; generating a second random number creates an unnecessary identifier with no audit meaning.

## Instructions

1. Add pure helpers for safe filename components, official quote filenames, localized rental periods, and localized Curaçao timestamps in EN/NL/PAP/DE.
2. Extend `send_dm_reply_with_attachment` with an optional `attachment_name` argument. Include `attachmentName` only for file sends with a non-empty sanitized name; preserve every existing caller and payload by default.
3. Build the quote filename from stored customer name, authoritative `createdAt`, and immutable quote reference. Pass it to Zernio as `attachmentName`, staff SMTP attachment metadata, and direct signed-download `Content-Disposition`.
4. Replace raw ISO rental-period text in the deterministic confirmation summary with the localized period helper.
5. Replace raw `expiresAt` text in the customer WhatsApp quote message and staff email with localized Curaçao time. Keep the exact 72-hour expiry value unchanged.
6. Use the same localized rental period and Curaçao timestamps inside the PDF. Do not change its pricing, one-page requirement, quote reference, or availability disclaimer.
7. Add behavioral tests for filename safety and uniqueness, all four localized date formats, Zernio `attachmentName`, backwards-compatible image attachment payloads, customer message formatting, staff attachment filename, direct-download filename, and PDF/summary removal of raw ISO presentation.

## Tests

- Presentation helpers return stable customer/date/reference filenames and localized dates for all four supported languages.
- Zernio file sends include `attachmentName`; existing attachment calls without a name remain byte-for-byte unchanged.
- Ali customer delivery contains a human-readable Curaçao expiry and passes the same official filename to Zernio.
- Staff email and signed download use the same official filename.
- Confirmation summary and PDF display human-readable rental periods while stored/API ISO values remain unchanged.
- Focused Ali/Zernio tests and full repository regression pass with zero failures.

## Success Condition

A new live Ali quote arrives in WhatsApp with an official customer-specific PDF filename and no raw ISO date or timestamp in customer-visible quote text.

## Rollback

Revert the Brief 270 commit and redeploy the previous image. Stored quotes, PDF bytes already generated, immutable pricing snapshots, expiry timestamps, and conversation state require no data rollback.
