from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard import api as api_mod
from dashboard.api import router as dashboard_router
from shared import config_loader


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(dashboard_router)
    return TestClient(app)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {api_mod._SESSION_TOKEN}"}


def test_client_profile_requires_auth():
    response = _client().get("/dashboard/api/client/profile")

    assert response.status_code == 401


def test_client_profile_returns_safe_tenant_display_data(monkeypatch):
    monkeypatch.setenv("TENANT_ID", "clinica-roberto")
    monkeypatch.setattr(
        config_loader,
        "get_raw",
        lambda: {
            "slug": "clinica-roberto",
            "name": "Fallback Name",
            "status": "active",
            "password": "secret-password",
            "access_key": "secret-access-key",
            "NR3_INTERNAL_API_TOKEN": "secret-token",
        },
    )
    monkeypatch.setattr(
        config_loader,
        "get_business",
        lambda: {
            "name": "Clinica Roberto",
            "email": "client@example.com",
        },
    )

    response = _client().get("/dashboard/api/client/profile", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "slug": "clinica-roberto",
        "name": "Clinica Roberto",
        "business_name": "Clinica Roberto",
        "display_name": "Clinica Roberto",
        "status": "active",
        "business": {
            "name": "Clinica Roberto",
            "display_name": "Clinica Roberto",
        },
    }
    text = response.text
    assert "secret-password" not in text
    assert "secret-access-key" not in text
    assert "secret-token" not in text


def test_client_profile_falls_back_to_top_level_name(monkeypatch):
    monkeypatch.delenv("TENANT_ID", raising=False)
    monkeypatch.setattr(
        config_loader,
        "get_raw",
        lambda: {
            "slug": "test",
            "name": "Test Workspace",
            "status": "active",
        },
    )
    monkeypatch.setattr(config_loader, "get_business", lambda: {})

    response = _client().get("/dashboard/api/client/profile", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "test"
    assert body["name"] == "Test Workspace"
    assert body["status"] == "active"


def test_client_profile_marks_legacy_unboks_config_active(monkeypatch):
    monkeypatch.delenv("TENANT_ID", raising=False)
    monkeypatch.setattr(
        config_loader,
        "get_raw",
        lambda: {
            "business": {
                "slug": "unboks",
                "name": "Unboks",
            },
        },
    )
    monkeypatch.setattr(
        config_loader,
        "get_business",
        lambda: {
            "slug": "unboks",
            "name": "Unboks",
        },
    )

    response = _client().get("/dashboard/api/client/profile", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "unboks"
    assert body["name"] == "Unboks"
    assert body["status"] == "active"


def test_client_profile_keeps_explicit_unboks_suspended_status(monkeypatch):
    monkeypatch.delenv("TENANT_ID", raising=False)
    monkeypatch.setattr(
        config_loader,
        "get_raw",
        lambda: {
            "status": "suspended",
            "business": {
                "slug": "unboks",
                "name": "Unboks",
            },
        },
    )
    monkeypatch.setattr(
        config_loader,
        "get_business",
        lambda: {
            "slug": "unboks",
            "name": "Unboks",
        },
    )

    response = _client().get("/dashboard/api/client/profile", headers=_auth())

    assert response.status_code == 200
    assert response.json()["status"] == "suspended"
