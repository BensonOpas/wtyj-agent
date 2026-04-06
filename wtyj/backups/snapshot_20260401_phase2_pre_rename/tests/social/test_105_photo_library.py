# tests/social/test_105_photo_library.py
# Brief 105 — Photo library backend tests

import io
import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from shared import state_registry


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(state_registry, "DB_PATH", db_path)


def _make_photo(**overrides):
    defaults = dict(
        filename="test_photo.jpg",
        original_filename="IMG_001.jpg",
        tags=["sunset"],
        trip_key="klein_curacao",
        source="upload",
        source_id="",
        width=1080,
        height=810,
        file_size=50000,
    )
    defaults.update(overrides)
    return state_registry.save_photo(**defaults)


# --- state_registry tests ---

def test_save_and_get_photo():
    photo_id = _make_photo()
    photos = state_registry.get_photos()
    assert len(photos) == 1
    p = photos[0]
    assert p["id"] == photo_id
    assert p["original_filename"] == "IMG_001.jpg"
    assert p["tags"] == ["sunset"]
    assert p["trip_key"] == "klein_curacao"
    assert p["source"] == "upload"
    assert p["width"] == 1080


def test_get_photos_filter_by_trip():
    _make_photo(trip_key="klein_curacao", filename="a.jpg")
    _make_photo(trip_key="sunset_cruise", filename="b.jpg")
    klein = state_registry.get_photos(trip_key="klein_curacao")
    assert len(klein) == 1
    assert klein[0]["trip_key"] == "klein_curacao"


def test_get_photo_by_id():
    photo_id = _make_photo()
    p = state_registry.get_photo_by_id(photo_id)
    assert p is not None
    assert p["id"] == photo_id
    assert p["original_filename"] == "IMG_001.jpg"


def test_get_photo_by_source_id():
    _make_photo(source="google_drive", source_id="drive_abc123", filename="c.jpg")
    p = state_registry.get_photo_by_source_id("drive_abc123")
    assert p is not None
    assert p["source"] == "google_drive"
    assert p["source_id"] == "drive_abc123"


def test_get_photo_by_source_id_empty():
    result = state_registry.get_photo_by_source_id("")
    assert result is None


def test_update_photo_tags():
    photo_id = _make_photo()
    ok = state_registry.update_photo(photo_id, tags=["boat", "ocean"])
    assert ok is True
    p = state_registry.get_photo_by_id(photo_id)
    assert p["tags"] == ["boat", "ocean"]


def test_update_photo_trip_key():
    photo_id = _make_photo()
    ok = state_registry.update_photo(photo_id, trip_key="sunset_cruise")
    assert ok is True
    p = state_registry.get_photo_by_id(photo_id)
    assert p["trip_key"] == "sunset_cruise"
    assert p["tags"] == ["sunset"]  # unchanged


def test_update_photo_filename():
    photo_id = _make_photo(filename="old_name.jpg")
    ok = state_registry.update_photo_filename(photo_id, "new_name.jpg")
    assert ok is True
    p = state_registry.get_photo_by_id(photo_id)
    assert p["filename"] == "new_name.jpg"


def test_delete_photo():
    photo_id = _make_photo(filename="to_delete.jpg")
    filename = state_registry.delete_photo(photo_id)
    assert filename == "to_delete.jpg"
    assert state_registry.get_photo_by_id(photo_id) is None


def test_delete_photo_nonexistent():
    result = state_registry.delete_photo(9999)
    assert result is None


def test_get_photo_stats():
    _make_photo(trip_key="klein_curacao", filename="d.jpg")
    _make_photo(trip_key="klein_curacao", filename="e.jpg")
    _make_photo(trip_key="sunset_cruise", filename="f.jpg")
    stats = state_registry.get_photo_stats()
    assert stats["total"] == 3
    assert stats["by_trip"]["klein_curacao"] == 2
    assert stats["by_trip"]["sunset_cruise"] == 1


# --- API endpoint tests ---

from PIL import Image as PILImage
from fastapi.testclient import TestClient
from agents.social.webhook_server import app

_client = TestClient(app)


def _login():
    resp = _client.post("/dashboard/api/login", json={"password": "testpass"})
    return resp.json()["token"]


def _make_test_image_bytes():
    """Create a small 10x10 red PNG in memory."""
    img = PILImage.new("RGB", (10, 10), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf.read()


def test_api_upload_endpoint(tmp_path, monkeypatch):
    import dashboard.api as api_mod
    monkeypatch.setattr(api_mod, "_PHOTOS_DIR", str(tmp_path))
    token = _login()
    img_bytes = _make_test_image_bytes()
    resp = _client.post(
        "/dashboard/api/photos/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("test_photo.png", img_bytes, "image/png")},
        data={"tags": "sunset, boat", "trip_key": "klein_curacao"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    photo = data["photo"]
    assert photo["original_filename"] == "test_photo.png"
    assert photo["source"] == "upload"
    assert photo["trip_key"] == "klein_curacao"
    assert photo["tags"] == ["sunset", "boat"]
    assert photo["width"] == 10
    assert photo["height"] == 10
    # Verify file exists
    assert os.path.exists(os.path.join(str(tmp_path), photo["filename"]))


def test_api_list_photos(tmp_path, monkeypatch):
    import dashboard.api as api_mod
    monkeypatch.setattr(api_mod, "_PHOTOS_DIR", str(tmp_path))
    token = _login()
    img_bytes = _make_test_image_bytes()
    _client.post(
        "/dashboard/api/photos/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("a.png", img_bytes, "image/png")},
        data={"tags": "", "trip_key": ""},
    )
    _client.post(
        "/dashboard/api/photos/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("b.png", img_bytes, "image/png")},
        data={"tags": "", "trip_key": ""},
    )
    resp = _client.get(
        "/dashboard/api/photos",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_api_delete_photo(tmp_path, monkeypatch):
    import dashboard.api as api_mod
    monkeypatch.setattr(api_mod, "_PHOTOS_DIR", str(tmp_path))
    token = _login()
    img_bytes = _make_test_image_bytes()
    upload_resp = _client.post(
        "/dashboard/api/photos/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("del.png", img_bytes, "image/png")},
        data={"tags": "", "trip_key": ""},
    )
    photo_id = upload_resp.json()["photo"]["id"]
    del_resp = _client.delete(
        f"/dashboard/api/photos/{photo_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 200
    # Verify gone
    get_resp = _client.get(
        f"/dashboard/api/photos/{photo_id}/image",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_resp.status_code == 404
