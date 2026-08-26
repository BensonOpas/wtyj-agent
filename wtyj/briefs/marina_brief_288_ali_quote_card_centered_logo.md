# BRIEF 288 — Ali quote card centered logo lockup
**Status:** Approved by owner | **Files:** `wtyj/agents/social/ali_quote_brand_card.py`, `wtyj/tests/agents/test_ali_quote_brand_card_fonts.py` | **Depends on:** Briefs 273, 277, 286, 287; GitHub issue #228 | **Blocks:** none

## Context

Brief 287 centered the lower title, quote reference, footer, and divider on the
880-pixel card. The approved Ali logo asset in the white panel still uses a
fixed left origin inherited from the previous composition. The owner explicitly
requested that the complete lockup—including the ALI mark and the CAR RENTAL
CURAÇAO descriptor—also sit in the middle.

## Why This Approach

Treat the approved logo asset as one indivisible visual unit and calculate its
horizontal origin from the fitted asset width and canvas midpoint. The panel and
canvas share the same midpoint, so one measurement centers the full lockup in
both. Editing, cropping, or separately repositioning the descriptor was rejected
because it would alter the approved brand asset. Hardcoding a new x-coordinate
was rejected because it would drift if the approved asset dimensions change.

## Instructions

1. In `wtyj/agents/social/ali_quote_brand_card.py:15-137`, preserve the 880×675
   canvas, white panel, approved logo file, logo size cap, and aspect ratio.
2. Calculate the fitted logo's horizontal origin from its actual width and the
   card midpoint. Keep the existing vertical region unchanged.
3. Fail closed if the calculated logo rectangle falls outside the white panel.
4. Preserve the centered lower typography and divider, all copy, colors, quote
   logic, deterministic rendering, image-before-PDF delivery, idempotency, and
   the three-minute final-customer delivery boundary.

## Tests

1. Assert the complete fitted logo midpoint matches the white-panel and card
   midpoint within half a pixel.
2. Assert the centered logo stays wholly inside the panel while preserving its
   source aspect ratio and size cap.
3. Preserve all four locale renders, deterministic output, bundled-font checks,
   lower typography centering, 880×675 geometry, and WhatsApp byte limit.
4. Render and visually inspect a synthetic PII-free card, then run focused Ali
   and full repository suites.

## Success Condition

The live Ali container renders the complete approved logo lockup centered in the
white panel on the same horizontal axis as the lower quote-card content.

## Rollback

Revert the Brief 288 merge commit and redeploy through the normal pipeline. No
schema, customer, quote, or data migration is introduced.
