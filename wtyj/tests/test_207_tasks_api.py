"""Brief 207: Tasks API endpoints — list, create, update, attachment upload."""

import io
import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from fastapi.testclient import TestClient


def _client_and_token():
    from agents.social.webhook_server import app
    client = TestClient(app)
    login = client.post("/dashboard/api/login", json={"password": "testpass"})
    assert login.status_code == 200
    token = login.json()["token"]
    return client, {"Authorization": f"Bearer {token}"}


def test_create_task_returns_full_shape():
    """POST /tasks returns the canonical camelCase task shape with id +
    createdAt + updatedAt + null completed fields."""
    client, headers = _client_and_token()
    resp = client.post("/tasks", json={
        "assignedTo": "Calvin",
        "createdBy": "Jr",
        "bodyHtml": "<p>review the doc</p>",
        "bodyText": "review the doc",
        "attachments": [],
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    task = resp.json()
    assert len(task["id"]) == 16
    assert task["assignedTo"] == "Calvin"
    assert task["createdBy"] == "Jr"
    assert task["bodyText"] == "review the doc"
    assert task["status"] == "open"
    assert task["completedAt"] is None
    assert task["completedBy"] is None
    assert task["createdAt"]
    assert task["updatedAt"]
    assert task["attachments"] == []


def test_list_tasks_round_trip():
    """POST then GET returns the created task."""
    client, headers = _client_and_token()
    created = client.post("/tasks", json={
        "assignedTo": "Jr", "createdBy": "Calvin",
        "bodyHtml": "", "bodyText": "ping",
    }, headers=headers).json()
    listing = client.get("/tasks", headers=headers).json()
    found = [t for t in listing if t["id"] == created["id"]]
    assert len(found) == 1
    assert found[0]["bodyText"] == "ping"


def test_patch_done_sets_completed_fields():
    """PATCH status=done sets completedAt + completedBy + status."""
    client, headers = _client_and_token()
    created = client.post("/tasks", json={
        "assignedTo": "Calvin", "createdBy": "Jr",
        "bodyHtml": "", "bodyText": "do thing",
    }, headers=headers).json()
    resp = client.patch(f"/tasks/{created['id']}",
                        json={"status": "done", "completedBy": "Calvin"},
                        headers=headers)
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["status"] == "done"
    assert updated["completedBy"] == "Calvin"
    assert updated["completedAt"] is not None


def test_patch_open_clears_completed_fields():
    """PATCH status=open clears completedAt + completedBy (regression for
    re-opening a previously-closed task)."""
    client, headers = _client_and_token()
    created = client.post("/tasks", json={
        "assignedTo": "Jr", "createdBy": "Calvin",
        "bodyHtml": "", "bodyText": "reopen test",
    }, headers=headers).json()
    client.patch(f"/tasks/{created['id']}",
                 json={"status": "done", "completedBy": "Jr"},
                 headers=headers)
    resp = client.patch(f"/tasks/{created['id']}",
                        json={"status": "open"}, headers=headers)
    assert resp.status_code == 200
    reopened = resp.json()
    assert reopened["status"] == "open"
    assert reopened["completedAt"] is None
    assert reopened["completedBy"] is None


def test_upload_attachment_returns_metadata_and_persists_file():
    """POST /tasks/uploads accepts a PNG, returns metadata with URL, and the
    file is retrievable via GET /tasks/uploads/{filename}."""
    client, headers = _client_and_token()
    # Minimal valid PNG bytes (1x1 transparent)
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000d4944415478da636001000000050001a5f3e2240000000049454e44ae426082"
    )
    resp = client.post("/tasks/uploads",
                       files={"file": ("test.png", io.BytesIO(png_bytes), "image/png")},
                       headers=headers)
    assert resp.status_code == 200, resp.text
    att = resp.json()
    assert att["mimeType"] == "image/png"
    assert att["sizeBytes"] == len(png_bytes)
    assert att["url"].startswith("/tasks/uploads/")
    assert att["fileName"] == "test.png"
    # Fetch back via the URL — no auth required for serve endpoint
    get_resp = client.get(att["url"])
    assert get_resp.status_code == 200
    assert get_resp.content == png_bytes


def test_upload_rejects_disallowed_mime_type():
    """POST /tasks/uploads rejects non-image/non-allowed mime types."""
    client, headers = _client_and_token()
    resp = client.post("/tasks/uploads",
                       files={"file": ("doc.pdf", io.BytesIO(b"fake-pdf"),
                                       "application/pdf")},
                       headers=headers)
    assert resp.status_code == 400
    assert "Unsupported mime type" in resp.json()["detail"]
