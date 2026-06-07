"""Tests for tenant knowledge media uploads and public provider URLs."""
import io
import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("PUBLIC_API_BASE_URL", "https://api.unboks.org")

from fastapi.testclient import TestClient
from PIL import Image

from agents.social.webhook_server import app
from shared import state_registry

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _reset_photos():
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM photo_library")
    conn.commit()
    conn.close()


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format="PNG")
    return buf.getvalue()


def test_knowledge_media_upload_lists_and_serves_public_image_url(monkeypatch):
    monkeypatch.setenv("TENANT_ID", "media-test")
    monkeypatch.setenv("TENANT_SLUG", "media-test")
    _reset_photos()
    token = _login()

    r = client.post(
        "/dashboard/api/knowledge/media",
        data={
            "knowledge_id": "cupcake-1",
            "source": "info_update",
            "caption": "Cupcake box",
        },
        files={"file": ("cupcake.png", _png_bytes(), "image/png")},
        headers=_auth(token),
    )

    assert r.status_code == 200, r.text
    media = r.json()
    assert media["knowledgeId"] == "cupcake-1"
    assert media["caption"] == "Cupcake box"
    assert media["mimeType"] == "image/jpeg"
    assert media["url"].startswith(
        "https://api.unboks.org/api/media-test/dashboard/api/public/media/photo_"
    )

    listed = client.get(
        "/dashboard/api/knowledge/media?knowledge_id=cupcake-1&source=info_update",
        headers=_auth(token),
    )
    assert listed.status_code == 200
    assert listed.json()["media"][0]["id"] == media["id"]

    library = client.get("/dashboard/api/knowledge/media/library", headers=_auth(token))
    assert library.status_code == 200
    assert any(item["id"] == media["id"] for item in library.json()["media"])

    public_path = media["url"].split("/dashboard/api", 1)[1]
    public = client.get(f"/dashboard/api{public_path}")
    assert public.status_code == 200
    assert public.headers["content-type"] == "image/jpeg"

    deleted = client.delete(
        f"/dashboard/api/knowledge/media/{media['id']}",
        headers=_auth(token),
    )
    assert deleted.status_code == 200

    listed_after = client.get(
        "/dashboard/api/knowledge/media?knowledge_id=cupcake-1&source=info_update",
        headers=_auth(token),
    )
    assert listed_after.status_code == 200
    assert listed_after.json()["media"] == []
