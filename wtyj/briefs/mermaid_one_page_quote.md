# Mermaid one-page quote
**Status:** In progress | **Files:** quote renderer, presentation-refresh page-count check, quote tests, runtime overlay | **Depends on:** live pickup and soft-review release 33272b1 | **Blocks:** compact guest quote

## Context
The user supplied a screenshot of a three-page quote with large blank areas and requested one page. The renderer uses a large full-width photograph, repeats the transport paragraph, and inserts a mandatory page break before the rules. Longer booking details overflow before that break, producing a nearly empty intermediate page.

## Why This Approach
Use a smaller photo beside the brand, a compact booking panel, one transport section, and paired included/bring columns. Preserve the itemized immutable prices and full existing rules, insurance, protocol, demo and payment wording. Reject uniformly shrinking the old pages, which would retain wasted space and make the text unreadable.

## Instructions
- Replace only the quote layout in `agents/social/mermaid_documents.py:196`; preserve shared transport/pricing helpers, receipt rendering, signed links and document delivery behavior.
- Remove the mandatory page break and duplicated transport. Keep body text readable and maintain a clear total and demo label.
- Verify a single A4 page in every supported language, including all price bands, pickup and long allowed guest/address fields. Check all required facts and inspect rendered layouts.
- Provide a regenerated local copy of the current quote and deploy the renderer as an overlay on the latest Mermaid image. Do not automatically resend customer messages or alter reservation amounts, delivery history or previously delivered files.
- Refresh only the current quote's stored presentation reference after validating the new PDF. Keep its original file and a copy of the original document record for rollback; document identity and delivery jobs remain unchanged.

## Tests
Six-language one-page output with required content; maximum-length guest/address and all fare rows; immutable totals; existing signed-download and delivery-idempotency checks. Inspect ordinary and dense page renders.

## Success Condition
New quotes and the regenerated customer example fit on one readable A4 page with all necessary booking and policy details.

## Rollback
Restore `wtyj-agent:tracy-soft-review-33272b1` in the Mermaid compose file and restart only Mermaid; preserve customer data and configuration. Retain a release backup of compose and the current runtime identity.

## Verification
- The actual Calvin quote reproduces the screenshot: three pages before, one page after. USD 600, all line items, booking details, 05:45 pickup, included/bring lists, policy text and next step are preserved.
- All six languages fit one page with 160-character names/addresses and every fare row. Actual and dense six-language layouts were rendered and visually checked without clipping or overlap.
- The previous presentation-refresh utility also assumed two quote pages; its check now accepts the new one-page quote. Signed-download, immutable totals, delivery and receipt behavior remain covered by the existing tests.
