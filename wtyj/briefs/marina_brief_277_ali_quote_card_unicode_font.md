# BRIEF 277 — Ali quote-card Unicode font reliability
**Status:** Executed | **Files:** `wtyj/agents/social/ali_quote_brand_card.py`, bundled DejaVu Sans fonts/license, focused tests, visual evidence | **Depends on:** Brief 273 | **Blocks:** issue 193

## Context

The production container has none of the host-specific font paths checked by the Ali quote-card renderer. Pillow therefore silently falls back to its limited default bitmap font and replaces the cedilla in `CURAÇAO`, corrupting every new customer-facing brand card.

## Why This Approach

Bundle the established redistributable DejaVu Sans regular and bold faces with the application and load them from an application-relative path. DejaVu Sans preserves the existing intended font family and supports every EN/NL/PAP/DE glyph used by the card. A controlled rendering exception replaces the lossy fallback so a missing or corrupt approved font stops image delivery instead of sending damaged branding.

## Instructions

1. Bundle unmodified DejaVu Sans 2.37 regular and bold TTF files under `wtyj/assets/fonts/dejavu/` with the complete upstream license.
2. Resolve the bundled files from the installed application tree before drawing. Do not search or depend on host OS font paths.
3. Raise a dedicated internal rendering error if either approved font is absent, unreadable, or corrupt. Never call `ImageFont.load_default()` for the branded card.
4. Preserve all dimensions, coordinates, colors, logo, title copy, footer copy, and quote-reference behavior.
5. Render EN/NL/PAP/DE synthetic cards, verify representative accented glyphs, PNG size/byte limits, and visually inspect a PII-free English artifact.

Font provenance: the unmodified DejaVu 2.37 TTF release was downloaded from the official `dejavu-fonts/dejavu-fonts` GitHub release (`dejavu-fonts-ttf-2.37.tar.bz2`, SHA-256 `fa9ca4d13871dd122f61258a80d01751d603b4d3ee14095d65453b4e846e17d7`). The bundled files retain the upstream `LICENSE` verbatim.

## Tests

- Regular and bold calls load the bundled app-relative files without system fonts.
- Missing and corrupt font directories raise the controlled error.
- `CURAÇAO`, `OFFICIËLE OFFERTE`, representative Papiamentu accents, and German umlauts/ß have distinct rendered glyph masks rather than the replacement glyph.
- All four localized PNGs retain 1200×675 dimensions and remain under the WhatsApp limit.
- Existing quote-card delivery, PDF, timing, and quote workflow tests remain green.

## Success Condition

The deployed Ali container loads both bundled paths and a PII-free production render visibly shows `ALI CAR RENTAL | CURAÇAO` with the correct `Ç`.

## Rollback

Revert the issue 193 merge commit and redeploy. No quote, conversation, pricing, or customer state migration is involved.
