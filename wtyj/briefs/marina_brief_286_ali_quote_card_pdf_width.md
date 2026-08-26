# BRIEF 286 — Ali quote card matches WhatsApp PDF width
**Status:** Approved by owner | **Files:** `wtyj/agents/social/ali_quote_brand_card.py`, `wtyj/tests/agents/test_ali_quote_brand_card_fonts.py`, `wtyj/tests/agents/test_ali_quote_workflow.py` | **Depends on:** Briefs 273, 277; GitHub issue #223 | **Blocks:** none

## Context

The Ali image-before-PDF delivery is correct, but the generated 1200×675 card is
16:9. In the owner's WhatsApp iOS screenshot, that card renders about 310 pixels
wide while the document preview below it renders about 225 pixels wide. The card
therefore looks oversized and visually disconnected from the official PDF. The
desired composition keeps the existing displayed height and premium brand design,
but removes the unnecessary right-side width so both customer assets align.

## Why This Approach

Keep the 675-pixel height and reflow the canvas to 880 pixels wide, matching the
observed 225/310 display-width ratio within screenshot measurement tolerance. Keep
the approved logo's source aspect ratio and the existing vertical geometry; move
only horizontal bounds and use measured font fitting for the localized title and
reference. Stretching the logo was rejected because it damages the brand. Adding
blank portrait padding was rejected because it would make the WhatsApp bubble tall
and waste space. Sending the image as a document was rejected because it removes
the intended visible premium card.

## Instructions

1. In `wtyj/agents/social/ali_quote_brand_card.py:9-94`, change the deterministic
   canvas to 880×675 and define bounded horizontal layout constants for the white
   brand panel, logo, accent, title, reference, and footer.
2. Preserve the approved logo source aspect ratio and current maximum logo size.
   Keep every element inside the narrower canvas without cropping or distortion.
3. Fit localized headings and valid quote references against the available content
   width using the already approved bundled regular/bold fonts. Fail closed if text
   cannot fit at the bounded minimum size; do not use a fallback font.
4. Preserve colors, copy, Unicode behavior, deterministic PNG output, no-PII
   boundary, signed download route, image-before-PDF order, independent retries,
   idempotency, and the three-minute final-customer delivery boundary.
5. Do not change quote data, pricing, PDF generation, customer captions, schemas,
   provider payloads, or any other tenant.

## Tests

1. Render EN/NL/PAP/DE cards and assert exact 880×675 PNG geometry, deterministic
   SHA-256 output, no customer PII, and the existing WhatsApp byte limit.
2. Assert the fitted approved logo keeps the exact source aspect ratio and remains
   fully inside the white brand panel.
3. Assert all localized titles, a maximum valid quote reference, and the footer fit
   within the declared safe content width without clipping.
4. Preserve missing/corrupt font fail-closed tests and all signed image, delivery,
   replay, timing, PDF, and workflow regressions.
5. Render and visually inspect a synthetic PII-free card, then run the focused Ali
   tests and full `wtyj/tests/` suite.

## Success Condition

The live Ali container renders an 880×675 premium card that appears at the same
WhatsApp width as the official PDF block while preserving the undistorted logo and
all existing quote delivery safeguards.

## Rollback

Revert the Brief 286 merge commit and redeploy through the normal pipeline. No
schema, quote, customer, or data migration is introduced.
