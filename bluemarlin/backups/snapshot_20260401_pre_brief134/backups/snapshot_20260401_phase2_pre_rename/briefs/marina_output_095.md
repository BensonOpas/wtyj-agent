# OUTPUT 095 — Branded Graphics Engine

**Brief:** marina_brief_095_branded_graphics_engine.md
**Status:** Complete
**Date:** 2026-03-16

## What Was Done

1. **graphics_engine.py** created in agents/social/ — generates 1080x1350 JPEG images from draft caption text. Brand colors (primary background, text color, accent bar) read from client.json `social_content.brand_graphics`. Uses Pillow's built-in default font (DejaVu Sans via `load_default(size=N)`). Custom font configurable via `font_path`. Headline extracted from first 1-2 sentences of caption, centered with word wrap.

2. **image_path column** added to content_drafts table via ALTER TABLE. New `set_draft_image_path()` function. `get_content_drafts()` now returns `image_path` field.

3. **brand_graphics config** added to social_content in client.json — primary_color [27,58,92], text_color [255,255,255], accent_color [212,168,83] (demo placeholders), empty logo_path and font_path.

4. **--graphics flag** added to auto_poster.py — `cmd_graphics()` calls `generate_all_pending_graphics()` for batch image generation.

## Test Results
```
graphics engine tests: 10/10 PASSED
social regression: 153/153 PASSED
```

## Unexpected
Nothing unexpected.
