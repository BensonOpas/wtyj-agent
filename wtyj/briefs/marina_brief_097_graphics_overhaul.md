# BRIEF 097 — Graphics Overhaul
**Status:** Draft | **Files:** `agents/social/graphics_engine.py`, `config/client.json`, `tests/social/test_095_graphics_engine.py` | **Depends on:** Brief 095 (graphics engine) | **Blocks:** None

## Context
Brief 095 created a working graphics engine but live testing exposed three problems: (1) the default Pillow font doesn't support Latin Extended characters — "Curaçao" renders as "Cura□ao", (2) text is too small for the 1080x1350 canvas — gets lost in the dark background, (3) flat solid background looks like a placeholder, not a premium brand post. This brief fixes all three by bundling a proper font, adding a gradient background, and improving text sizing/layout.

## Why This Approach
The Unicode issue is a font problem, not a Pillow problem. The fix is simple: bundle a .ttf font with full Latin Extended coverage. Inter Bold is free (SIL license), supports all Latin characters including ç, ñ, ü, and looks premium. The gradient and layout changes are cosmetic but critical — SR's operating brief says every visual must feel "intentional, curated, polished, premium." A flat navy box with tiny text fails that bar. The executor downloads the font file during execution (not a URL in the brief — the executor uses Bash to fetch it).

## Source Material

### Font: Inter Bold
- License: SIL Open Font License (free for commercial use)
- Coverage: Latin, Latin Extended, Cyrillic, Greek — covers ç, ñ, ü, ö, etc.
- File: `Inter-Bold.ttf` (~300KB)
- Location: `config/brand/Inter-Bold.ttf`
- The executor downloads this during execution via Bash tool

### Gradient background
Instead of `Image.new("RGB", size, solid_color)`, draw a vertical gradient from `primary_color` (top) to a darker shade (bottom). This adds depth without complexity.

```python
def _draw_gradient(img, color_top, color_bottom):
    """Draw a vertical gradient from color_top to color_bottom."""
    draw = ImageDraw.Draw(img)
    for y in range(_IMG_HEIGHT):
        ratio = y / _IMG_HEIGHT
        r = int(color_top[0] + (color_bottom[0] - color_top[0]) * ratio)
        g = int(color_top[1] + (color_bottom[1] - color_top[1]) * ratio)
        b = int(color_top[2] + (color_bottom[2] - color_top[2]) * ratio)
        draw.line([(0, y), (_IMG_WIDTH, y)], fill=(r, g, b))
```

### Improved layout (1080x1350)
```
[  top 15% — breathing room  ]
[  text area — upper 40%     ]  ← headline, large font, centered
[  middle gap — 20%          ]
[  brand line — small text   ]  ← "BlueFinn Charters Curaçao" or business name
[  accent bar — bottom 2%    ]  ← gold strip
```

### Text sizing
- Short headlines (<60 chars): 72pt
- Medium headlines (60-100 chars): 58pt
- Long headlines (>100 chars): 46pt
- Brand name at bottom: 24pt
- Line spacing: 16px (was 12px)

### Updated brand_graphics config
Add `gradient_bottom_color` to the config:
```json
"brand_graphics": {
  "primary_color": [27, 58, 92],
  "gradient_bottom_color": [15, 30, 50],
  "text_color": [255, 255, 255],
  "accent_color": [212, 168, 83],
  "logo_path": "",
  "font_path": "config/brand/Inter-Bold.ttf"
}
```

## Instructions

### Step 1 — Ensure Inter Bold font exists

**Prerequisite:** The file `config/brand/Inter-Bold.ttf` must exist before execution. The executor obtains it before starting (same as "Pillow must be installed" — a prerequisite, not a brief instruction). Create the directory if needed:
```bash
mkdir -p config/brand
```
The executor verifies the font file exists and is a valid TrueType font (non-zero bytes) before proceeding to Step 2.

### Step 2 — Update brand_graphics in client.json

In `social_content.brand_graphics`, add `gradient_bottom_color` and update `font_path`:

Change from:
```json
"brand_graphics": {
  "primary_color": [27, 58, 92],
  "text_color": [255, 255, 255],
  "accent_color": [212, 168, 83],
  "logo_path": "",
  "font_path": ""
}
```

To:
```json
"brand_graphics": {
  "primary_color": [27, 58, 92],
  "gradient_bottom_color": [15, 30, 50],
  "text_color": [255, 255, 255],
  "accent_color": [212, 168, 83],
  "logo_path": "",
  "font_path": "config/brand/Inter-Bold.ttf"
}
```

### Step 3 — Rewrite graphics_engine.py

Rewrite the file with these changes (keep the same file header, update Last modified to Brief 097):

**3a. `_load_brand_config()`** — add `gradient_bottom_color` with generic default:
```python
"gradient_bottom_color": tuple(bg.get("gradient_bottom_color", [15, 15, 15])),
```

**3b. Add `_draw_gradient()` function** — as shown in Source Material above.

**3c. Update `_load_font()`** — no change needed (already reads font_path from config).

**3d. Update text sizing in `generate_graphic()`:**
```python
    # Text sizing based on headline length
    if len(headline) < 60:
        font_size = 72
    elif len(headline) < 100:
        font_size = 58
    else:
        font_size = 46
```

**3e. Update line spacing** in `_draw_wrapped_text()`:
```python
    line_spacing = 16  # was 12
```

**3f-3i. Rewrite the body of `generate_graphic()` with this exact block order:**

```python
    # ... (draft lookup and caption extraction unchanged) ...

    brand = _load_brand_config()
    headline = _extract_headline(caption)

    # 1. Create image with gradient background
    img = Image.new("RGB", (_IMG_WIDTH, _IMG_HEIGHT), brand["primary_color"])
    _draw_gradient(img, brand["primary_color"], brand["gradient_bottom_color"])
    draw = ImageDraw.Draw(img)

    # 2. Accent bar at bottom (define bar_height FIRST — used by brand name and logo)
    bar_height = 12
    draw.rectangle(
        [0, _IMG_HEIGHT - bar_height, _IMG_WIDTH, _IMG_HEIGHT],
        fill=brand["accent_color"]
    )

    # 3. Headline text in upper portion
    if len(headline) < 60:
        font_size = 72
    elif len(headline) < 100:
        font_size = 58
    else:
        font_size = 46
    font = _load_font(brand["font_path"], font_size)
    margin = 120
    text_area_y = int(_IMG_HEIGHT * 0.15)
    text_area_height = int(_IMG_HEIGHT * 0.40)
    _draw_wrapped_text(
        draw, headline, font, brand["text_color"],
        margin, text_area_y, _IMG_WIDTH - 2 * margin, text_area_height,
        font_size=font_size
    )

    # 4. Logo if available
    logo_path = brand.get("logo_path", "")
    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            ratio = min(200 / logo.width, 60 / logo.height)
            logo = logo.resize((int(logo.width * ratio), int(logo.height * ratio)))
            logo_x = (_IMG_WIDTH - logo.width) // 2
            logo_y = _IMG_HEIGHT - bar_height - logo.height - 40
            img.paste(logo, (logo_x, logo_y), logo)
        except Exception:
            pass

    # 5. Brand name above accent bar
    business = config_loader.get_business()
    brand_name = business.get("name", "")
    if brand_name:
        brand_font = _load_font(brand["font_path"], 24)
        bbox = draw.textbbox((0, 0), brand_name, font=brand_font)
        name_width = bbox[2] - bbox[0]
        name_x = (_IMG_WIDTH - name_width) // 2
        name_y = _IMG_HEIGHT - bar_height - 50
        muted = tuple(int(c * 0.5) + 60 for c in brand["text_color"])
        draw.text((name_x, name_y), brand_name, fill=muted, font=brand_font)

    # 6. Save
    os.makedirs(_GRAPHICS_DIR, exist_ok=True)
    output_path = os.path.join(_GRAPHICS_DIR, f"draft_{draft_id}.jpg")
    img.save(output_path, "JPEG", quality=_QUALITY)

    state_registry.set_draft_image_path(draft_id, output_path)
    bm_logger.log("graphics_generated", draft_id=draft_id, path=output_path)
    return output_path
```

### Step 4 — Update tests

Update `tests/social/test_095_graphics_engine.py`:

**4a.** Update `test_load_brand_config_from_client_json` — add assertion:
```python
assert config["gradient_bottom_color"] == (15, 30, 50)
assert config["font_path"] == "config/brand/Inter-Bold.ttf"
```
Remove the old `assert config["font_path"] == ""`.

**4b.** Add new test `test_font_is_truetype_not_default` after `test_graphic_has_brand_colors`:
```python
def test_font_is_truetype_not_default():
    """Verify the configured font loads as TrueType (supports Latin Extended)."""
    from agents.social.graphics_engine import _load_font, _load_brand_config
    brand = _load_brand_config()
    font = _load_font(brand["font_path"], 48)
    # TrueType fonts are FreeTypeFont instances, default is not
    assert isinstance(font, ImageFont.FreeTypeFont), "Font should be TrueType, not default"
    # Verify font can measure Latin Extended characters without error
    assert font.getlength("Curaçao") > 0
    assert font.getlength("piña") > 0
```

**4c.** Add new test `test_graphic_has_gradient` after the Unicode test:
```python
def test_graphic_has_gradient():
    """Verify top and bottom of image have different colors (gradient)."""
    _cleanup_all()
    try:
        d = state_registry.save_content_draft(
            "A", "Gradient test post.", "", [], "", ""
        )
        path = generate_graphic(d)
        img = Image.open(path)
        top_pixel = img.getpixel((10, 10))
        bottom_pixel = img.getpixel((10, 1300))  # near bottom, above accent bar
        # Top should be lighter (primary_color), bottom should be darker (gradient_bottom)
        assert top_pixel[2] > bottom_pixel[2]  # blue channel: top > bottom
    finally:
        _cleanup_all()
```

## Tests
Run: `cd bluemarlin && python3 -m pytest tests/social/test_095_graphics_engine.py -v`

All 12 tests must pass (10 original + 2 new). The font file must exist at `config/brand/Inter-Bold.ttf` for Unicode test to be meaningful.

## Success Condition
Generated graphics have: gradient background (not flat), large readable text (72/58/46pt), proper Unicode rendering (ç, ñ), brand name at bottom, thicker accent bar. Visual quality matches "premium" standard.

## Rollback
1. Revert `agents/social/graphics_engine.py` to Brief 095 version
2. Revert `config/client.json` to Brief 095 version
3. Revert `tests/social/test_095_graphics_engine.py` to Brief 095 version
4. Delete `config/brand/Inter-Bold.ttf`
