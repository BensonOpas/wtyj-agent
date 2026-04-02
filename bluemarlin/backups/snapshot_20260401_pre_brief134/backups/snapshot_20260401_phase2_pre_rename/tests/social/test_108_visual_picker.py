# tests/social/test_108_visual_picker.py
# Brief 108 — Visual picker backend tests

import io
import os
import sys
import pytest
from PIL import Image as PILImage

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared import state_registry
from agents.social.graphics_engine import _cover_crop, generate_composite


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(state_registry, "DB_PATH", db_path)


def _make_draft(**overrides):
    defaults = dict(
        content_class="B",
        instagram_caption="Sunset cruise tonight at $79 per person. Open bar included.",
        facebook_caption="Same caption for FB.",
        hashtags=["#sunset"],
        visual_suggestion="Golden hour on a catamaran",
        reasoning="Test",
    )
    defaults.update(overrides)
    return state_registry.save_content_draft(**defaults)


def _make_photo(**overrides):
    defaults = dict(
        filename="test.jpg", original_filename="test.jpg",
        tags=["sunset"], trip_key="sunset_cruise",
        width=1080, height=810, file_size=50000,
    )
    defaults.update(overrides)
    return state_registry.save_photo(**defaults)


def _create_test_image(tmp_path, w=200, h=300, color=(0, 128, 255)):
    img = PILImage.new("RGB", (w, h), color)
    path = str(tmp_path / "test_photo.jpg")
    img.save(path, "JPEG")
    return path


# --- state_registry tests ---

def test_set_draft_photo_id():
    draft_id = _make_draft()
    ok = state_registry.set_draft_photo_id(draft_id, 42)
    assert ok is True
    drafts = state_registry.get_content_drafts()
    draft = next(d for d in drafts if d["id"] == draft_id)
    assert draft["photo_id"] == 42


def test_increment_used_count():
    photo_id = _make_photo(filename="inc.jpg")
    photo = state_registry.get_photo_by_id(photo_id)
    assert photo["used_count"] == 0
    state_registry.increment_photo_used_count(photo_id)
    photo = state_registry.get_photo_by_id(photo_id)
    assert photo["used_count"] == 1


# --- graphics_engine tests ---

def test_cover_crop_landscape():
    img = PILImage.new("RGB", (200, 100), (255, 0, 0))
    result = _cover_crop(img, 1080, 1350)
    assert result.size == (1080, 1350)


def test_cover_crop_portrait():
    img = PILImage.new("RGB", (100, 200), (0, 255, 0))
    result = _cover_crop(img, 1080, 1350)
    assert result.size == (1080, 1350)


def test_cover_crop_square():
    img = PILImage.new("RGB", (500, 500), (0, 0, 255))
    result = _cover_crop(img, 1080, 1350)
    assert result.size == (1080, 1350)


def test_generate_composite_photo_text(tmp_path, monkeypatch):
    import agents.social.graphics_engine as ge
    monkeypatch.setattr(ge, "_GRAPHICS_DIR", str(tmp_path))
    draft_id = _make_draft(content_class="B")
    photo_path = _create_test_image(tmp_path)
    result = generate_composite(draft_id, photo_path=photo_path, mode="photo_text")
    assert result != ""
    assert os.path.exists(result)
    img = PILImage.open(result)
    assert img.size == (1080, 1350)


def test_generate_composite_photo_only(tmp_path, monkeypatch):
    import agents.social.graphics_engine as ge
    monkeypatch.setattr(ge, "_GRAPHICS_DIR", str(tmp_path))
    draft_id = _make_draft(content_class="A")
    photo_path = _create_test_image(tmp_path)
    result = generate_composite(draft_id, photo_path=photo_path, mode="photo_only")
    assert result != ""
    assert os.path.exists(result)
    img = PILImage.open(result)
    assert img.size == (1080, 1350)


def test_generate_composite_text_card(tmp_path, monkeypatch):
    import agents.social.graphics_engine as ge
    monkeypatch.setattr(ge, "_GRAPHICS_DIR", str(tmp_path))
    draft_id = _make_draft()
    result = generate_composite(draft_id, photo_path="", mode="text_card")
    assert result != ""
    assert os.path.exists(result)
