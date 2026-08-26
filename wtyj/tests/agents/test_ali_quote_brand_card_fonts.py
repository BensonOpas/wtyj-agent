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


def test_four_locale_cards_use_pdf_width_geometry_and_byte_limit(tmp_path):
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
            assert image.size == (880, 675)
            assert image.format == "PNG"
        outputs.append(path)
    assert len(outputs) == 4


def test_narrow_layout_preserves_logo_proportions_and_safe_bounds():
    logo_path = Path(card.__file__).resolve().parents[2] / (
        "assets/ali-logo-full-premium.png"
    )
    with Image.open(logo_path) as source:
        source_ratio = source.width / source.height
        fitted = card._fit_logo(source, *card.LOGO_MAX_SIZE)

    fitted_ratio = fitted.width / fitted.height
    assert fitted.width <= card.LOGO_MAX_SIZE[0]
    assert fitted.height <= card.LOGO_MAX_SIZE[1]
    assert abs(fitted_ratio - source_ratio) < 0.005

    logo_left = card.LOGO_POSITION[0]
    logo_top = card.LOGO_POSITION[1] + (248 - fitted.height) // 2
    panel_left, panel_top, panel_right, panel_bottom = card.PANEL_BOX
    assert panel_left <= logo_left < logo_left + fitted.width <= panel_right
    assert panel_top <= logo_top < logo_top + fitted.height <= panel_bottom


def test_localized_titles_reference_and_footer_fit_safe_content_width():
    for title in card.TITLES.values():
        font = card._fit_font(title, 60, 48, bold=True)
        assert font.getlength(title) <= card.CONTENT_WIDTH

    maximum_reference = "ALI-" + ("W" * 40)
    reference_font = card._fit_font(maximum_reference, 37, 16, bold=True)
    assert reference_font.getlength(maximum_reference) <= card.CONTENT_WIDTH
    assert card._font(24).getlength(card.FOOTER_TEXT) <= card.CONTENT_WIDTH


def test_lower_typography_and_divider_share_canvas_midpoint():
    expected_center = card.WIDTH / 2
    for title in card.TITLES.values():
        font = card._fit_font(title, 60, 48, bold=True)
        origin = card._centered_text_x(title, font)
        assert abs(origin + (font.getlength(title) / 2) - expected_center) <= 0.5

    for reference in (
        "ALI-20260826-D15F0530",
        "ALI-" + ("W" * 40),
    ):
        font = card._fit_font(reference, 37, 16, bold=True)
        origin = card._centered_text_x(reference, font)
        assert 0 <= origin
        assert origin + font.getlength(reference) <= card.WIDTH
        assert abs(
            origin + (font.getlength(reference) / 2) - expected_center
        ) <= 0.5

    footer_font = card._font(24)
    footer_origin = card._centered_text_x(card.FOOTER_TEXT, footer_font)
    assert abs(
        footer_origin
        + (footer_font.getlength(card.FOOTER_TEXT) / 2)
        - expected_center
    ) <= 0.5

    accent_left, _, accent_right, _ = card.ACCENT_BOX
    assert accent_right - accent_left == card.ACCENT_WIDTH
    assert (accent_left + accent_right) / 2 == expected_center


def test_same_card_content_remains_deterministic_after_reflow(tmp_path):
    first_path, first_digest = card.render_quote_brand_card(
        "deterministic-one", "en", "ALI-20260826-DETERMINISTIC",
        output_root=str(tmp_path),
    )
    second_path, second_digest = card.render_quote_brand_card(
        "deterministic-two", "en", "ALI-20260826-DETERMINISTIC",
        output_root=str(tmp_path),
    )

    assert first_digest == second_digest
    assert Path(first_path).read_bytes() == Path(second_path).read_bytes()


def test_customer_copy_and_narrow_layout_constants_are_preserved():
    assert card.WIDTH == 880
    assert card.HEIGHT == 675
    assert card.CONTENT_LEFT + card.CONTENT_WIDTH + card.CONTENT_RIGHT == card.WIDTH
    assert card.FOOTER_TEXT == "ALI CAR RENTAL | CURAÇAO"
    assert card.TITLES == {
        "en": "OFFICIAL QUOTE",
        "nl": "OFFICIËLE OFFERTE",
        "pap": "OFERTA OFISIAL",
        "de": "OFFIZIELLES ANGEBOT",
    }
