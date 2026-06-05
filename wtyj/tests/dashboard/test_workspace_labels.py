import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("TENANT_ID", "workspace-label-test")

from dashboard.api import router
from shared import state_registry


def _client() -> tuple[TestClient, str]:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    token = client.post("/dashboard/api/login", json={"password": "testpass"}).json()["token"]
    return client, token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _wipe():
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM system_settings WHERE key = 'workspace_bookings_label'")
    conn.commit()
    conn.close()


def test_workspace_labels_default_and_save():
    try:
        _wipe()
        client, token = _client()

        default_response = client.get("/dashboard/api/settings/workspace-labels", headers=_auth(token))
        assert default_response.status_code == 200, default_response.text
        assert default_response.json()["bookingsLabel"] == "Appointments"

        save = client.put(
            "/dashboard/api/settings/workspace-labels",
            headers=_auth(token),
            json={"bookings_label": "Orders"},
        )
        assert save.status_code == 200, save.text
        assert save.json()["bookingsLabel"] == "Orders"

        persisted = client.get("/dashboard/api/settings/workspace-labels", headers=_auth(token))
        assert persisted.json()["bookingsLabel"] == "Orders"
    finally:
        _wipe()


def test_workspace_labels_accepts_short_custom_label():
    try:
        _wipe()
        client, token = _client()
        response = client.put(
            "/dashboard/api/settings/workspace-labels",
            headers=_auth(token),
            json={"bookings_label": "Requests"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["bookingsLabel"] == "Requests"
    finally:
        _wipe()


def test_workspace_labels_rejects_unsafe_label():
    try:
        _wipe()
        client, token = _client()
        response = client.put(
            "/dashboard/api/settings/workspace-labels",
            headers=_auth(token),
            json={"bookings_label": "<script>"},
        )
        assert response.status_code == 400
    finally:
        _wipe()
