# BRIEF 095 — Branded Graphics Engine
**Status:** Draft | **Files:** `agents/social/graphics_engine.py` (NEW), `shared/state_registry.py`, `config/client.json`, `agents/social/auto_poster.py`, `tests/social/test_095_graphics_engine.py` (NEW) | **Depends on:** Brief 092 (content drafts schema) | **Blocks:** Brief 096 (Late publishing integration)

## Context
Brief 096 will connect to Late's API to publish posts to Instagram. Instagram requires an image with every post — no text-only posting. We need a way to generate branded graphics from draft caption text. This brief builds a graphics engine using Pillow (PIL) that creates clean, premium announcement-style images: caption text on a branded background. Config-driven — brand colors, logo path, font path all come from client.json so any client can swap in their own brand assets.

## Why This Approach
We considered requiring the operator to provide photos for every post, but that blocks the autonomous flow SR described. We considered AI image generation (DALL-E), but that's a separate dependency and cost. Branded graphics are the simplest path to publishable images that look premium — they're deterministic, config-driven, and work for announcements, promos, tips, and availability updates. Real photos and AI generation layer on top later. The "billboard" concept SR described (notices, announcements, branded content) maps directly to text-on-branded-background graphics.

## Source Material

### Image specs for Instagram
- Size: 1080x1350 px (4:5 portrait, optimal for feed)
- Format: JPEG, quality 95
- Max 8MB (a 1080x1350 JPEG at quality 95 is ~300KB)

### Template design
- Background: brand primary color (solid)
- Caption text: first sentence of instagram_caption, large, centered, white/light
- Line 2 (optional): second sentence in smaller font, if caption has 2+ sentences
- Logo: bottom center, small (if logo file exists in config path)
- Bottom bar: thin accent color strip along bottom edge
- Generous whitespace — text occupies middle 60% of image

### brand_graphics config section (add to social_content in client.json)
```json
"brand_graphics": {
  "primary_color": [27, 58, 92],
  "text_color": [255, 255, 255],
  "accent_color": [212, 168, 83],
  "logo_path": "",
  "font_path": ""
}
```
Colors as RGB arrays (Pillow uses tuples). Empty logo_path means no logo. Empty font_path means use Pillow's built-in default font. **Note:** These RGB values are demo placeholders (dark navy, white, gold) — not confirmed BlueFinn brand colors. Update with real brand colors when available from the client. When a custom .ttf is available, set font_path to the absolute or relative path (e.g. `"config/brand/Inter-Bold.ttf"`).

### Font strategy
No external font download in this brief. Pillow 10+ provides `ImageFont.load_default(size=N)` which returns a proper FreeTypeFont (DejaVu Sans) that supports `.getlength()` and works well for generated graphics. A custom branded font can be configured later by placing a .ttf file and setting `font_path` in config. The code NEVER falls back to the legacy `load_default()` (no size arg) — always passes a size parameter.

### Output path convention
Generated images go to `data/graphics/draft_{id}.jpg`. The directory is created if it doesn't exist. The publish step (Brief 096) looks for images at this path.

### image_path column
Add `image_path TEXT DEFAULT ''` to content_drafts table via ALTER TABLE (same pattern as customer_name/customer_email columns in trip_bookings).

## Instructions

### Step 1 — Install Pillow

Pillow install command (for reference, not executed by this brief — executor runs it before tests):
```
pip3 install Pillow
```
On VPS: `pip3 install Pillow --break-system-packages`

The test file and graphics_engine.py import `PIL`. If Pillow is not installed, tests will fail with ImportError. No external font download needed — uses Pillow's built-in default font.

### Step 2 — Add brand_graphics config + image_path column

**2a.** In client.json, add `brand_graphics` inside the existing `social_content` section (after `emoji_style`):

```json
"brand_graphics": {
  "primary_color": [27, 58, 92],
  "text_color": [255, 255, 255],
  "accent_color": [212, 168, 83],
  "logo_path": "",
  "font_path": ""
}
```

**2b.** In state_registry.py, add an ALTER TABLE for `image_path` after the existing ALTER TABLE blocks for customer_name/customer_email (inside `_get_conn()`):

```python
    try:
        conn.execute("ALTER TABLE content_drafts ADD COLUMN image_path TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
```

Add a helper function before the `_get_conn().close()` line:

```python
def set_draft_image_path(draft_id: int, image_path: str) -> bool:
    """Set the generated image path for a content draft."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE content_drafts SET image_path = ? WHERE id = ?",
        (image_path, draft_id)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed
```

Also update `get_content_drafts()` to include `image_path`. In both SELECT statements, change the column list from:
```
"created_at, approved_at, published_at "
```
to:
```
"created_at, approved_at, published_at, image_path "
```
And in the return dict comprehension, add after `"published_at": r[11],`:
```python
            "image_path": r[12],
```

**2c.** Update state_registry.py header to `# Last modified: Brief 095`.

### Step 3 — Create graphics_engine.py

Create `agents/social/graphics_engine.py`:

**File header:**
```python
# bluemarlin/agents/social/graphics_engine.py
# Created: Brief 095
# Last modified: Brief 095
# Purpose: Generates branded graphics from draft post text using Pillow.
```

**Imports:**
```python
import os
import textwrap
from PIL import Image, ImageDraw, ImageFont
from shared import config_loader, state_registry, bm_logger
```

**Constants:**
```python
_IMG_WIDTH = 1080
_IMG_HEIGHT = 1350
_QUALITY = 95
_GRAPHICS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'graphics'
)
```

**`_load_brand_config()` function:**
```python
def _load_brand_config() -> dict:
    """Load brand graphics config from client.json social_content.brand_graphics.
    Returns dict with generic defaults for missing values."""
    raw = config_loader.get_raw()
    sc = raw.get("social_content", {})
    bg = sc.get("brand_graphics", {})
    return {
        "primary_color": tuple(bg.get("primary_color", [30, 30, 30])),
        "text_color": tuple(bg.get("text_color", [255, 255, 255])),
        "accent_color": tuple(bg.get("accent_color", [100, 100, 100])),
        "logo_path": bg.get("logo_path", ""),
        "font_path": bg.get("font_path", ""),
    }
```
Note: Python defaults are generic (dark grey/white), NOT client-specific. Client colors live in client.json only.

**`_load_font(font_path, size)` function:**
```python
def _load_font(font_path: str, size: int):
    """Load font from path. Falls back to Pillow built-in default (DejaVu Sans)."""
    if font_path and os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
    # Pillow 10+ load_default(size=N) returns a FreeTypeFont with full API support
    return ImageFont.load_default(size=size)
```

**`_extract_headline(caption)` function:**
```python
def _extract_headline(caption: str, max_chars: int = 120) -> str:
    """Extract the first 1-2 sentences from caption for the graphic headline.
    Caps at max_chars to prevent text overflow."""
    if not caption:
        return ""
    sentences = caption.replace("!", "!|").replace(".", ".|").replace("?", "?|").split("|")
    sentences = [s.strip() for s in sentences if s.strip()]
    headline = sentences[0] if sentences else caption
    # Add second sentence if headline is short and second exists
    if len(headline) < 60 and len(sentences) > 1:
        headline = headline + " " + sentences[1]
    if len(headline) > max_chars:
        headline = headline[:max_chars].rsplit(" ", 1)[0] + "..."
    return headline
```

**`_draw_wrapped_text(draw, text, font, text_color, box)` function:**
Takes ImageDraw, text string, font, color, and a bounding box (x, y, max_width, max_height). Wraps text to fit width, centers vertically within the box. Returns None.

```python
def _draw_wrapped_text(draw, text: str, font, text_color: tuple,
                       x: int, y: int, max_width: int, max_height: int,
                       font_size: int = 42):
    """Draw text wrapped to fit within a bounding box, centered vertically.
    font_size is passed explicitly (not read from font object) for compatibility."""
    # Estimate chars per line from font metrics
    avg_char_width = font.getlength("M")
    chars_per_line = max(1, int(max_width / avg_char_width))
    lines = textwrap.wrap(text, width=chars_per_line)

    # Calculate total text height using explicit font_size
    line_spacing = 12
    line_height = font_size + line_spacing
    total_height = len(lines) * line_height

    # Center vertically
    start_y = y + (max_height - total_height) // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_width = bbox[2] - bbox[0]
        line_x = x + (max_width - line_width) // 2  # center horizontally
        draw.text((line_x, start_y + i * line_height), line, fill=text_color, font=font)
```

**`generate_graphic(draft_id)` function — the main entry point:**

```python
def generate_graphic(draft_id: int) -> str:
    """Generate a branded graphic for a content draft.
    Returns the output file path, or empty string on failure."""
    # Get the draft
    drafts = state_registry.get_content_drafts()
    draft = next((d for d in drafts if d["id"] == draft_id), None)
    if not draft:
        bm_logger.log("graphics_draft_not_found", draft_id=draft_id)
        return ""

    caption = draft.get("instagram_caption") or draft.get("facebook_caption") or ""
    if not caption:
        bm_logger.log("graphics_no_caption", draft_id=draft_id)
        return ""

    brand = _load_brand_config()
    headline = _extract_headline(caption)

    # Create image
    img = Image.new("RGB", (_IMG_WIDTH, _IMG_HEIGHT), brand["primary_color"])
    draw = ImageDraw.Draw(img)

    # Draw accent bar at bottom
    bar_height = 8
    draw.rectangle(
        [0, _IMG_HEIGHT - bar_height, _IMG_WIDTH, _IMG_HEIGHT],
        fill=brand["accent_color"]
    )

    # Draw headline text in center area
    font_size = 54 if len(headline) < 80 else 42
    font = _load_font(brand["font_path"], font_size)
    margin = 100
    text_area_y = _IMG_HEIGHT // 4
    text_area_height = _IMG_HEIGHT // 2
    _draw_wrapped_text(
        draw, headline, font, brand["text_color"],
        margin, text_area_y, _IMG_WIDTH - 2 * margin, text_area_height,
        font_size=font_size
    )

    # Draw logo if available
    logo_path = brand.get("logo_path", "")
    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            # Resize logo to max 200px wide
            ratio = min(200 / logo.width, 60 / logo.height)
            logo = logo.resize((int(logo.width * ratio), int(logo.height * ratio)))
            logo_x = (_IMG_WIDTH - logo.width) // 2
            logo_y = _IMG_HEIGHT - bar_height - logo.height - 40
            img.paste(logo, (logo_x, logo_y), logo)
        except Exception:
            pass  # Skip logo on error

    # Save
    os.makedirs(_GRAPHICS_DIR, exist_ok=True)
    output_path = os.path.join(_GRAPHICS_DIR, f"draft_{draft_id}.jpg")
    img.save(output_path, "JPEG", quality=_QUALITY)

    # Update draft with image path
    state_registry.set_draft_image_path(draft_id, output_path)

    bm_logger.log("graphics_generated", draft_id=draft_id, path=output_path)
    return output_path
```

**`generate_all_pending_graphics()` function:**
```python
def generate_all_pending_graphics() -> list:
    """Generate graphics for all pending/approved drafts that don't have an image yet.
    Returns list of (draft_id, image_path) tuples."""
    drafts = state_registry.get_content_drafts()
    results = []
    for d in drafts:
        if d["status"] in ("pending", "approved") and not d.get("image_path"):
            path = generate_graphic(d["id"])
            if path:
                results.append((d["id"], path))
    return results
```

### Step 4 — Update auto_poster.py

Add `--graphics` flag to auto_poster.py:

**4a.** Add import at the top:
```python
from agents.social import graphics_engine
```

**4b.** Add new command function:
```python
def cmd_graphics():
    """Generate branded graphics for drafts that need images."""
    results = graphics_engine.generate_all_pending_graphics()
    if not results:
        print("No drafts need graphics (all pending/approved drafts already have images).")
        return
    for draft_id, path in results:
        print(f"  #{draft_id} → {path}")
    print(f"Generated {len(results)} graphics.")
```

**4c.** Add argparse argument:
```python
parser.add_argument("--graphics", action="store_true", help="Generate branded graphics for drafts")
```

**4d.** Add to the `any()` check and execution block:
```python
if not any([args.generate, args.review, args.publish, args.distill, args.status, args.graphics]):
```
```python
if args.graphics:
    cmd_graphics()
```

**4e.** Update auto_poster.py header to `# Last modified: Brief 095`.

### Step 5 — Create test file

Create `tests/social/test_095_graphics_engine.py`:

**File header:**
```python
# bluemarlin/tests/social/test_095_graphics_engine.py
# Created: Brief 095
# Purpose: Tests for branded graphics engine
```

**Setup:** sys.path insert, env vars.

**Imports:**
```python
import os
from PIL import Image
from agents.social.graphics_engine import (
    generate_graphic,
    generate_all_pending_graphics,
    _extract_headline,
    _load_brand_config,
    _GRAPHICS_DIR,
)
from shared import state_registry
```

**Helpers:**
- `_cleanup_all()` — deletes content_drafts rows + removes all files in `_GRAPHICS_DIR`

**Tests (10 total):**

1. **`test_load_brand_config_from_client_json`** — Call `_load_brand_config()`. Assert `primary_color == (27, 58, 92)`. Assert `text_color == (255, 255, 255)`. Assert `font_path == ""`.

2. **`test_extract_headline_single_sentence`** — Call `_extract_headline("Crystal-clear waters await.")`. Assert returns `"Crystal-clear waters await."`.

3. **`test_extract_headline_two_sentences_short`** — Call `_extract_headline("Short one. Second part.")`. Assert result contains both "Short one" and "Second part" (combined because first is <60 chars).

4. **`test_extract_headline_long_caps_at_max`** — Call `_extract_headline("A" * 200)`. Assert `len(result) <= 123` (120 + "...").

5. **`test_generate_graphic_creates_file`** — Save a draft with caption "Klein Curaçao — white sand and crystal water." Call `generate_graphic(draft_id)`. Assert returns a non-empty string. Assert file exists at returned path. Open with `Image.open()` — assert size is (1080, 1350). Assert format is JPEG. Cleanup after.

6. **`test_generate_graphic_updates_draft_image_path`** — Save a draft, generate graphic. Call `state_registry.get_content_drafts()`, find the draft. Assert `image_path` is non-empty and matches the returned path. Cleanup after.

7. **`test_generate_graphic_no_caption_returns_empty`** — Save a draft with empty instagram_caption and empty facebook_caption. Call `generate_graphic(draft_id)`. Assert returns `""`. Cleanup after.

8. **`test_generate_graphic_nonexistent_draft`** — Call `generate_graphic(99999)`. Assert returns `""`.

9. **`test_generate_all_pending_skips_with_image`** — Save 2 drafts. Generate graphic for first one (it now has image_path). Call `generate_all_pending_graphics()`. Assert returns 1 result (only the second draft). Cleanup after.

10. **`test_graphic_has_brand_colors`** — Save a draft, generate graphic. Open the image. Sample the pixel at (10, 10) (top-left, should be primary_color background). Assert pixel RGB is close to (27, 58, 92) (allow ±5 for JPEG compression). Cleanup after.

## Tests
Run: `cd bluemarlin && python3 -m pytest tests/social/test_095_graphics_engine.py -v`

All 10 tests must pass. Tests require Pillow installed (`pip3 install Pillow`). Test 10 verifies actual pixel colors match brand config.

## Success Condition
`generate_graphic(draft_id)` creates a 1080x1350 JPEG with the draft's headline text on a branded background. Colors come from client.json. `generate_all_pending_graphics()` batch-generates for all drafts missing images. `auto_poster.py --graphics` runs it from CLI.

## Rollback
1. Delete `agents/social/graphics_engine.py`
2. Revert `shared/state_registry.py` to Brief 093 version
3. Revert `config/client.json` to Brief 092 version
4. Revert `agents/social/auto_poster.py` to Brief 094 version
5. Delete `tests/social/test_095_graphics_engine.py`
6. Delete `data/graphics/` directory
