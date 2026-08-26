from pathlib import Path

import pytest
from PIL import Image, ImageFont

from agents.social import ali_quote_brand_card as card


def test_regular_and_bold_fonts_load_from_bundled_application_assets():
    regular = card._font(24)
    bold = card._font(24, bold=True)

    assert isinstance(regular, ImageFont.FreeTypeFont)
    assert isinstance(bold, ImageFont.FreeTypeFont)
    assert Path(regular.path).resolve() == (
        card.FONT_ROOT / "DejaVuSans.ttf"
    ).resolve()
    assert Path(bold.path).resolve() == (
        card.FONT_ROOT / "DejaVuSans-Bold.ttf"
    ).resolve()
    assert "usr/share/fonts" not in str(regular.path)
    assert "System/Library/Fonts" not in str(regular.path)
    assert card.FONT_SHA256 == {
        False: "7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954",
        True: "e6476c1b80502924294eed40894c5b18e06c181444ca953e5334262df9c27724",
    }


@pytest.mark.parametrize("corrupt", [False, True])
def test_missing_or_corrupt_bundled_font_fails_closed(tmp_path, corrupt):
    if corrupt:
        (tmp_path / "DejaVuSans.ttf").write_bytes(b"not-a-font")
        (tmp_path / "DejaVuSans-Bold.ttf").write_bytes(b"not-a-font")
    for bold in (False, True):
        with pytest.raises(
            card.QuoteBrandCardRenderError,
            match="Approved bundled quote-card font unavailable",
        ):
            card._font(24, bold=bold, font_root=tmp_path)


def test_all_required_localized_glyphs_have_real_font_masks():
    samples = {
        "en": card.FOOTER_TEXT,
        "nl": card.TITLES["nl"],
        "pap": "Kòrsou, konfirmá, minüt, añanan",
        "de": "Größe, Straße, Grüße, weiß, ÄÖÜ",
    }
    replacement = bytes(card._font(36).getmask("�", mode="L"))
    for sample in samples.values():
        for character in set(sample):
            if character.isspace() or character in ",|":
                continue
            mask = card._font(36).getmask(character, mode="L")
            assert mask.getbbox() is not None
            assert bytes(mask) != replacement


def test_four_locale_cards_keep_existing_geometry_and_byte_limit(tmp_path):
    outputs = []
    for locale in ("en", "nl", "pap", "de"):
        path, digest = card.render_quote_brand_card(
            f"font-{locale}", locale, "ALI-20260826-UNICODE",
            output_root=str(tmp_path),
        )
        data = Path(path).read_bytes()
        assert digest
        assert len(data) < card.MAX_IMAGE_BYTES
        with Image.open(path) as image:
            assert image.size == (card.WIDTH, card.HEIGHT)
            assert image.format == "PNG"
        outputs.append(path)
    assert len(outputs) == 4


def test_customer_copy_and_layout_constants_are_unchanged():
    assert card.WIDTH == 1200
    assert card.HEIGHT == 675
    assert card.FOOTER_TEXT == "ALI CAR RENTAL | CURAÇAO"
    assert card.TITLES == {
        "en": "OFFICIAL QUOTE",
        "nl": "OFFICIËLE OFFERTE",
        "pap": "OFERTA OFISIAL",
        "de": "OFFIZIELLES ANGEBOT",
    }
