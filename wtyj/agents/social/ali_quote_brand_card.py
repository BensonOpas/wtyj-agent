"""Deterministic, PII-free Ali quote card for WhatsApp delivery."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 880
HEIGHT = 675
MAX_IMAGE_BYTES = 5 * 1024 * 1024
NAVY = "#081F36"
GOLD = "#FFB91D"
WHITE = "#FFFFFF"
MUTED = "#B8C7D6"
PANEL_BOX = (48, 54, 832, 338)
PANEL_RADIUS = 34
ACCENT_WIDTH = 186
ACCENT_BOX = (
    (WIDTH - ACCENT_WIDTH) // 2,
    365,
    (WIDTH + ACCENT_WIDTH) // 2,
    373,
)
LOGO_POSITION = (78, 71)
LOGO_MAX_SIZE = (430, 250)
CONTENT_LEFT = 64
CONTENT_RIGHT = 48
CONTENT_WIDTH = WIDTH - CONTENT_LEFT - CONTENT_RIGHT
TITLE_Y = 414
REFERENCE_Y = 515
FOOTER_Y = 591

TITLES = {
    "en": "OFFICIAL QUOTE",
    "nl": "OFFICIËLE OFFERTE",
    "pap": "OFERTA OFISIAL",
    "de": "OFFIZIELLES ANGEBOT",
}
FOOTER_TEXT = "ALI CAR RENTAL | CURAÇAO"
FONT_ROOT = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "dejavu"
FONT_FILES = {
    False: "DejaVuSans.ttf",
    True: "DejaVuSans-Bold.ttf",
}
FONT_SHA256 = {
    False: "7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954",
    True: "e6476c1b80502924294eed40894c5b18e06c181444ca953e5334262df9c27724",
}


class QuoteBrandCardRenderError(RuntimeError):
    """Controlled failure for customer-facing brand-card rendering."""


def _font(size: int, *, bold: bool = False, font_root: Path | None = None):
    root = Path(font_root) if font_root is not None else FONT_ROOT
    font_path = root / FONT_FILES[bool(bold)]
    try:
        font_bytes = font_path.read_bytes()
        if hashlib.sha256(font_bytes).hexdigest() != FONT_SHA256[bool(bold)]:
            raise ValueError("font checksum mismatch")
        return ImageFont.truetype(str(font_path), size=size)
    except (OSError, ValueError) as exc:
        raise QuoteBrandCardRenderError(
            f"Approved bundled quote-card font unavailable: {font_path.name}"
        ) from exc


def _fit_logo(source: Image.Image, max_width: int, max_height: int) -> Image.Image:
    logo = source.convert("RGBA")
    logo.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return logo


def _fit_font(
    text: str,
    preferred_size: int,
    minimum_size: int,
    *,
    max_width: int = CONTENT_WIDTH,
    bold: bool = False,
):
    for size in range(preferred_size, minimum_size - 1, -1):
        font = _font(size, bold=bold)
        if font.getlength(text) <= max_width:
            return font
    raise QuoteBrandCardRenderError("Quote-card text exceeds safe width")


def _centered_text_x(text: str, font) -> int:
    rendered_width = float(font.getlength(text))
    if rendered_width <= 0 or rendered_width > WIDTH:
        raise QuoteBrandCardRenderError("Quote-card text cannot be centered")
    return round((WIDTH - rendered_width) / 2)


def render_quote_brand_card(
    public_id: str,
    locale: str,
    quote_reference: str,
    *,
    output_root: str = "/app/data/ali-quotes",
    logo_path: str | None = None,
) -> tuple[str, str]:
    if locale not in TITLES:
        raise ValueError("Unsupported quote-card locale")
    reference = str(quote_reference or "").strip().upper()
    if not re.fullmatch(r"ALI-[A-Z0-9-]{8,40}", reference):
        raise ValueError("Invalid quote reference")

    resolved_logo = Path(logo_path) if logo_path else (
        Path(__file__).resolve().parents[2] / "assets" / "ali-logo-full-premium.png"
    )
    if not resolved_logo.is_file():
        raise ValueError("Approved Ali logo is unavailable")

    image = Image.new("RGB", (WIDTH, HEIGHT), NAVY)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(PANEL_BOX, radius=PANEL_RADIUS, fill=WHITE)
    draw.rectangle(ACCENT_BOX, fill=GOLD)

    with Image.open(resolved_logo) as source:
        logo = _fit_logo(source, *LOGO_MAX_SIZE)
    logo_x = LOGO_POSITION[0]
    logo_y = LOGO_POSITION[1] + (248 - logo.height) // 2
    image.paste(logo, (logo_x, logo_y), logo)

    title_font = _fit_font(TITLES[locale], 60, 48, bold=True)
    reference_font = _fit_font(reference, 37, 16, bold=True)
    footer_font = _font(24)
    draw.text(
        (_centered_text_x(TITLES[locale], title_font), TITLE_Y),
        TITLES[locale], font=title_font, fill=WHITE,
    )
    draw.text(
        (_centered_text_x(reference, reference_font), REFERENCE_Y),
        reference, font=reference_font, fill=GOLD,
    )
    draw.text(
        (_centered_text_x(FOOTER_TEXT, footer_font), FOOTER_Y), FOOTER_TEXT,
        font=footer_font, fill=MUTED,
    )

    target = Path(output_root) / public_id / "quote-card.png"
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    image.save(target, format="PNG", optimize=True)
    data = target.read_bytes()
    if len(data) >= MAX_IMAGE_BYTES:
        raise ValueError("Quote card exceeds WhatsApp image limit")
    return str(target), hashlib.sha256(data).hexdigest()
