from agents.social.ali_quote_presentation import (
    build_quote_filename,
    format_curacao_datetime,
    format_date,
    format_rental_period,
)


def test_official_filename_uses_customer_issue_date_and_quote_unique_suffix():
    filename = build_quote_filename(
        "Calvín Adamus / ../../", "ALI-20260825-4C7CC225",
        "2026-08-25T22:50:31.396Z",
    )

    assert filename == "Ali-Car-Rental-Quote-Calvin-Adamus-2026-08-25-4C7CC225.pdf"
    assert "/" not in filename
    assert ".." not in filename


def test_rental_period_is_human_readable_in_all_supported_languages():
    expected = {
        "en": "1 September 2026 – 8 September 2026",
        "nl": "1 september 2026 – 8 september 2026",
        "pap": "1 di sèptèmber 2026 – 8 di sèptèmber 2026",
        "de": "1. September 2026 – 8. September 2026",
    }

    for locale, rendered in expected.items():
        assert format_rental_period("2026-09-01", "2026-09-08", locale) == rendered


def test_expiry_is_converted_to_curacao_time_and_localized():
    value = "2026-08-28T22:50:31.396Z"
    expected = {
        "en": "28 August 2026 at 18:50 (Curaçao time)",
        "nl": "28 augustus 2026 om 18:50 (Curaçaose tijd)",
        "pap": "28 di ougùstù 2026 pa 18:50 (ora di Kòrsou)",
        "de": "28. August 2026 um 18:50 (Curaçao-Zeit)",
    }

    for locale, rendered in expected.items():
        assert format_curacao_datetime(value, locale) == rendered


def test_unknown_locale_falls_back_to_english_without_changing_iso_input():
    source = "2026-09-05"
    assert format_date(source, "unsupported") == "5 September 2026"
    assert source == "2026-09-05"
