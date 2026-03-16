# bluemarlin/tests/social/test_095_graphics_engine.py
# Created: Brief 095
# Purpose: Tests for branded graphics engine

import os
import sys
import glob
import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_token_067")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "990622044139349")

from PIL import Image
from agents.social.graphics_engine import (
    generate_graphic,
    generate_all_pending_graphics,
    _extract_headline,
    _load_brand_config,
    _GRAPHICS_DIR,
)
from shared import state_registry


# --- Helpers ---

def _cleanup_all():
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM content_drafts")
    conn.execute("DELETE FROM content_learnings")
    conn.commit()
    conn.close()
    # Remove generated graphics
    if os.path.exists(_GRAPHICS_DIR):
        for f in glob.glob(os.path.join(_GRAPHICS_DIR, "draft_*.jpg")):
            os.remove(f)


# --- Tests ---

def test_load_brand_config_from_client_json():
    config = _load_brand_config()
    assert config["primary_color"] == (27, 58, 92)
    assert config["text_color"] == (255, 255, 255)
    assert config["font_path"] == ""


def test_extract_headline_single_sentence():
    result = _extract_headline("Crystal-clear waters await.")
    assert result == "Crystal-clear waters await."


def test_extract_headline_two_sentences_short():
    result = _extract_headline("Short one. Second part.")
    assert "Short one" in result
    assert "Second part" in result


def test_extract_headline_long_caps_at_max():
    result = _extract_headline("A" * 200)
    assert len(result) <= 123  # 120 + "..."


def test_generate_graphic_creates_file():
    _cleanup_all()
    try:
        d = state_registry.save_content_draft(
            "A", "Klein Curaçao — white sand and crystal water.", "", [], "", ""
        )
        path = generate_graphic(d)
        assert path != ""
        assert os.path.exists(path)
        img = Image.open(path)
        assert img.size == (1080, 1350)
        assert img.format == "JPEG"
    finally:
        _cleanup_all()


def test_generate_graphic_updates_draft_image_path():
    _cleanup_all()
    try:
        d = state_registry.save_content_draft(
            "B", "Sunset cruise tonight.", "", [], "", ""
        )
        path = generate_graphic(d)
        drafts = state_registry.get_content_drafts()
        match = [x for x in drafts if x["id"] == d]
        assert len(match) == 1
        assert match[0]["image_path"] != ""
        assert match[0]["image_path"] == path
    finally:
        _cleanup_all()


def test_generate_graphic_no_caption_returns_empty():
    _cleanup_all()
    try:
        d = state_registry.save_content_draft("A", "", "", [], "", "")
        path = generate_graphic(d)
        assert path == ""
    finally:
        _cleanup_all()


def test_generate_graphic_nonexistent_draft():
    path = generate_graphic(99999)
    assert path == ""


def test_generate_all_pending_skips_with_image():
    _cleanup_all()
    try:
        d1 = state_registry.save_content_draft(
            "A", "First draft caption.", "", [], "", ""
        )
        d2 = state_registry.save_content_draft(
            "B", "Second draft caption.", "", [], "", ""
        )
        # Generate graphic for first — it now has image_path
        generate_graphic(d1)
        # generate_all should only pick up the second
        results = generate_all_pending_graphics()
        draft_ids = [r[0] for r in results]
        assert d2 in draft_ids
        assert d1 not in draft_ids
    finally:
        _cleanup_all()


def test_graphic_has_brand_colors():
    _cleanup_all()
    try:
        d = state_registry.save_content_draft(
            "A", "Brand color test post.", "", [], "", ""
        )
        path = generate_graphic(d)
        img = Image.open(path)
        pixel = img.getpixel((10, 10))  # top-left corner, should be primary_color
        # Allow ±5 for JPEG compression
        assert abs(pixel[0] - 27) <= 5
        assert abs(pixel[1] - 58) <= 5
        assert abs(pixel[2] - 92) <= 5
    finally:
        _cleanup_all()
