# OUTPUT 097 — Graphics Overhaul

**Brief:** marina_brief_097_graphics_overhaul.md
**Status:** Complete
**Date:** 2026-03-16

## What Was Done

1. **Inter Bold font bundled** at `config/brand/Inter-Bold.ttf` (420KB, SIL license). Full Latin Extended coverage — ç, ñ, ü, ö all render correctly. No more placeholder boxes.

2. **Gradient background** — vertical gradient from primary_color (navy, top) to gradient_bottom_color (darker navy, bottom). New `_draw_gradient()` function. `gradient_bottom_color` added to client.json config.

3. **Larger text** — font sizes bumped: 72pt (short headlines), 58pt (medium), 46pt (long). Was 54/42. Line spacing 16px (was 12). Margin 120px (was 100).

4. **Better layout** — text starts at 15% from top (was 25%), occupies 40% of image height (was 50%). More breathing room, text higher up.

5. **Brand name at bottom** — "BlueFinn Charters Curaçao" in muted text above the accent bar. Read from client.json `business.name`.

6. **Thicker accent bar** — 12px (was 8px).

## Test Results
```
graphics tests: 12/12 PASSED (10 original + 2 new)
social regression: 165/165 PASSED
```

New tests:
- `test_font_is_truetype_not_default` — verifies Inter Bold loads as FreeTypeFont, measures ç and ñ
- `test_graphic_has_gradient` — verifies top pixels lighter than bottom pixels

## Unexpected
Nothing unexpected.
