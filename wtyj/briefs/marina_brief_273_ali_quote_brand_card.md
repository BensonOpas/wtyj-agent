# BRIEF 273 — Ali WhatsApp quote brand card
**Status:** Executed | **Files:** `wtyj/agents/social/ali_quote_brand_card.py`, `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/agents/social/ali_quote_delivery.py`, `wtyj/agents/social/ali_quote_download.py`, focused tests | **Depends on:** Briefs 270-272 | **Blocks:** issue 184

## Context

Zernio's current WhatsApp document payload accepts a document URL and filename but has no custom PDF-thumbnail field. The final Ali WhatsApp caption also repeats an availability sentence the owner explicitly removed. The reliable premium experience is therefore one Ali-branded image message followed by the existing official PDF message.

## Why This Approach

Generate a deterministic image from the approved local Ali logo and navy/gold system, then serve it through the existing one-hour HMAC route. Track image and PDF acceptance separately in the quote row. A fake PDF-thumbnail field was rejected because Zernio does not support it. A vehicle-specific card was rejected for this bounded issue because it adds catalog-image dependencies without improving the official-reference purpose of the card.

## Instructions

1. Add a deterministic 1200 × 675 PNG renderer using `wtyj/assets/ali-logo-full-premium.png`, a localized official-quote label, and quote reference only. Keep it below 5 MB and exclude customer PII.
2. Add backward-compatible SQLite columns in `wtyj/agents/social/ali_quote_workflow.py:278` for image path, SHA-256, and delivery status.
3. Generate the PDF and image before staff email/internal notifications, then preserve immediate staff/internal delivery in `wtyj/agents/social/ali_quote_workflow.py:689`.
4. At the existing three-minute customer boundary, send the image first and PDF second. Retry and persist each independently so replay never repeats an accepted asset and either partial failure retries only the failed asset.
5. Extend `wtyj/agents/social/ali_quote_download.py:24` without changing existing PDF signatures: an `--image` path suffix identifies the signed PNG asset.
6. Remove the availability sentence only from the EN/NL/PAP/DE customer caption at `wtyj/agents/social/ali_quote_delivery.py:24`; leave PDF/legal and staff workflow text unchanged.

## Tests

- Render all four localized cards; verify 1200 × 675 PNG, approved logo, reference, no customer PII, and size below 5 MB.
- Verify signed PDF URLs remain compatible and signed image URLs cannot be swapped or tampered with.
- Assert staff/internal operations occur before the wait, then one image and one PDF occur in order at/after the boundary.
- Verify replay sends neither asset twice; image failure still sends PDF; PDF failure after image success retries only PDF.
- Assert all four customer captions omit availability wording while the PDF legal wording remains unchanged.
- Run the full repository suite and an allowlisted production delivery.

## Success Condition

One confirmed Ali quote sends exactly one premium localized logo card immediately followed by exactly one official PDF after the three-minute boundary, with no WhatsApp availability sentence and safe partial retries.

## Rollback

Revert the issue 184 merge commit and redeploy the previous image. The additive SQLite columns may remain unused; existing PDF download signatures and historical quote files continue to work.
