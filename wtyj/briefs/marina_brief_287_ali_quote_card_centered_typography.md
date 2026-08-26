# BRIEF 287 — Ali quote card centered typography
**Status:** Approved by owner | **Files:** `wtyj/agents/social/ali_quote_brand_card.py`, `wtyj/tests/agents/test_ali_quote_brand_card_fonts.py` | **Depends on:** Briefs 273, 277, 286; GitHub issue #225 | **Blocks:** none

## Context

Brief 286 correctly reduced the customer-facing card to the WhatsApp PDF preview
width. The lower navy section still inherits the old left-aligned typography, so
the localized title, quote reference, footer, and gold divider feel visually
weighted to one side on the narrower canvas. The owner explicitly requested that
the text sit in the middle.

## Why This Approach

Calculate each text origin from its actual bundled-font rendered length and the
880-pixel canvas midpoint. This stays correct for EN/NL/PAP/DE and for quote
references that use a fitted font size. Center the divider by its measured width
so the entire lower section forms one balanced vertical axis. Fixed per-language
coordinates were rejected because they drift when copy or font size changes.
Centering the logo was rejected because the owner requested the text change and
the approved logo composition inside the white panel must remain unchanged.

## Instructions

1. In `wtyj/agents/social/ali_quote_brand_card.py:15-124`, preserve the 880×675
   canvas and current logo/panel geometry.
2. Add one deterministic helper that returns the integer x-origin required to
   center measured text on the canvas. Reject invalid or over-wide measurements.
3. Center the localized title, quote reference, and footer using their actual
   selected fonts. Do not alter vertical coordinates, wording, colors, or fonts.
4. Center the existing gold divider while preserving its width, height, and color.
5. Preserve deterministic PNG output, Unicode failure handling, PII exclusion,
   signed media delivery, image-before-PDF ordering, retries, idempotency, and the
   three-minute customer delivery boundary.

## Tests

1. For EN/NL/PAP/DE, assert the rendered title origin and width center on the
   880-pixel canvas within one pixel.
2. Assert representative and maximum valid quote references, the footer, and gold
   divider center within one pixel and remain inside the image bounds.
3. Preserve 880×675 geometry, deterministic output, logo aspect ratio/bounds,
   bundled-font checks, and the WhatsApp byte limit.
4. Render and visually inspect a synthetic PII-free card, then run focused Ali and
   full repository suites.

## Success Condition

The live Ali container generates an 880×675 quote card whose title, reference,
footer, and divider share the card's horizontal midpoint in all four locales.

## Rollback

Revert the Brief 287 merge commit and redeploy through the normal pipeline. No
schema, quote, customer, or data migration is introduced.
