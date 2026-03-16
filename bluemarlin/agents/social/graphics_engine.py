# bluemarlin/agents/social/graphics_engine.py
# Created: Brief 095
# Last modified: Brief 097
# Purpose: Generates branded graphics from draft post text using Pillow.

import os
import textwrap
from PIL import Image, ImageDraw, ImageFont
from shared import config_loader, state_registry, bm_logger

_IMG_WIDTH = 1080
_IMG_HEIGHT = 1350
_QUALITY = 95
_GRAPHICS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'graphics'
)


def _load_brand_config() -> dict:
    """Load brand graphics config from client.json social_content.brand_graphics.
    Returns dict with generic defaults for missing values."""
    raw = config_loader.get_raw()
    sc = raw.get("social_content", {})
    bg = sc.get("brand_graphics", {})
    return {
        "primary_color": tuple(bg.get("primary_color", [30, 30, 30])),
        "gradient_bottom_color": tuple(bg.get("gradient_bottom_color", [15, 15, 15])),
        "text_color": tuple(bg.get("text_color", [255, 255, 255])),
        "accent_color": tuple(bg.get("accent_color", [100, 100, 100])),
        "logo_path": bg.get("logo_path", ""),
        "font_path": bg.get("font_path", ""),
    }


def _load_font(font_path: str, size: int):
    """Load font from path. Falls back to Pillow built-in default (DejaVu Sans)."""
    if font_path and os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
    return ImageFont.load_default(size=size)


def _draw_gradient(img, color_top, color_bottom):
    """Draw a vertical gradient from color_top to color_bottom."""
    draw = ImageDraw.Draw(img)
    for y in range(_IMG_HEIGHT):
        ratio = y / _IMG_HEIGHT
        r = int(color_top[0] + (color_bottom[0] - color_top[0]) * ratio)
        g = int(color_top[1] + (color_bottom[1] - color_top[1]) * ratio)
        b = int(color_top[2] + (color_bottom[2] - color_top[2]) * ratio)
        draw.line([(0, y), (_IMG_WIDTH, y)], fill=(r, g, b))


def _extract_headline(caption: str, max_chars: int = 120) -> str:
    """Extract the first 1-2 sentences from caption for the graphic headline.
    Caps at max_chars to prevent text overflow."""
    if not caption:
        return ""
    sentences = caption.replace("!", "!|").replace(".", ".|").replace("?", "?|").split("|")
    sentences = [s.strip() for s in sentences if s.strip()]
    headline = sentences[0] if sentences else caption
    if len(headline) < 60 and len(sentences) > 1:
        headline = headline + " " + sentences[1]
    if len(headline) > max_chars:
        headline = headline[:max_chars].rsplit(" ", 1)[0] + "..."
    return headline


def _draw_wrapped_text(draw, text: str, font, text_color: tuple,
                       x: int, y: int, max_width: int, max_height: int,
                       font_size: int = 42):
    """Draw text wrapped to fit within a bounding box, centered vertically.
    font_size is passed explicitly (not read from font object) for compatibility."""
    avg_char_width = font.getlength("M")
    chars_per_line = max(1, int(max_width / avg_char_width))
    lines = textwrap.wrap(text, width=chars_per_line)

    line_spacing = 16
    line_height = font_size + line_spacing
    total_height = len(lines) * line_height

    start_y = y + (max_height - total_height) // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_width = bbox[2] - bbox[0]
        line_x = x + (max_width - line_width) // 2
        draw.text((line_x, start_y + i * line_height), line, fill=text_color, font=font)


def generate_graphic(draft_id: int) -> str:
    """Generate a branded graphic for a content draft.
    Returns the output file path, or empty string on failure."""
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
