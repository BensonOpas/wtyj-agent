"""Deterministic, PII-free Ali quote card for WhatsApp delivery."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1200
HEIGHT = 675
MAX_IMAGE_BYTES = 5 * 1024 * 1024
NAVY = "#081F36"
GOLD = "#FFB91D"
WHITE = "#FFFFFF"
MUTED = "#B8C7D6"

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
    draw.rounded_rectangle((64, 54, 1136, 338), radius=34, fill=WHITE)
    draw.rectangle((64, 365, 250, 373), fill=GOLD)

    with Image.open(resolved_logo) as source:
        logo = _fit_logo(source, 430, 250)
    logo_x = 94
    logo_y = 71 + (248 - logo.height) // 2
    image.paste(logo, (logo_x, logo_y), logo)

    draw.text((86, 414), TITLES[locale], font=_font(60, bold=True), fill=WHITE)
    draw.text((88, 515), reference, font=_font(37, bold=True), fill=GOLD)
    draw.text(
        (88, 591), FOOTER_TEXT,
        font=_font(24), fill=MUTED,
    )

    target = Path(output_root) / public_id / "quote-card.png"
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    image.save(target, format="PNG", optimize=True)
    data = target.read_bytes()
    if len(data) >= MAX_IMAGE_BYTES:
        raise ValueError("Quote card exceeds WhatsApp image limit")
    return str(target), hashlib.sha256(data).hexdigest()
