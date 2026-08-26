# BRIEF 274 — Ali PDF grand total
**Status:** Executed | **Files:** `wtyj/agents/social/ali_quote_presentation.py`, `wtyj/agents/social/ali_quote_pdf.py`, focused tests | **Depends on:** Briefs 270-273 | **Blocks:** issue 185

## Context

The official PDF currently emphasizes the rental subtotal and lists the refundable security deposit separately. Customers therefore have to add those figures themselves to understand the complete quoted amount.

## Why This Approach

Add one shared integer-cent helper over the accepted immutable pricing snapshot, then use it only in the PDF presentation. Keep `rentalTotal`, the refundable deposit, reservation payment, item rows, and historical snapshots unchanged. Computing from the two authoritative money objects was selected over summing display strings or item rows because it preserves the catalog API's accounting categories and avoids double-counting the itemized deposit.

## Instructions

1. Add strict USD integer-cent parsing, formatting, and `total_quote_amount` helpers in `wtyj/agents/social/ali_quote_presentation.py`.
2. Calculate `rentalTotal + refundableSecurityDeposit` exactly once. Do not read or mutate `reservationDeposit`.
3. Replace the PDF totals block with a dominant localized grand total, a direct refundable-deposit explanation when the deposit is non-zero, and a smaller rental-charges subtotal.
4. Preserve the itemized deposit row, PDF legal copy, immutable snapshot, WhatsApp timing/delivery, filename, and hash behavior.
5. Keep the PDF to one page with long names and supplements in EN/NL/PAP/DE.

## Tests

- Assert USD 1,260.00 + USD 200.00 = USD 1,460.00 using integer cents while reservation payment remains USD 315.00.
- Assert zero deposit equals the rental subtotal and omits the refundable-deposit explanation.
- Assert supplements already included in `rentalTotal` appear in the grand total once.
- Extract all four localized PDFs and verify the grand-total, deposit-included, and rental-charges hierarchy.
- Render all four languages plus zero-deposit and multi-supplement cases to PNG and visually inspect one-page layout.
- Run the focused and full suites.

## Success Condition

Every new Ali PDF shows one prominent complete quote amount including the separately itemized refundable deposit, with exact localized financial meaning and no accounting or delivery behavior change.

## Rollback

Revert the issue 185 merge commit and redeploy. Existing immutable pricing snapshots and historical PDF files are not modified.
