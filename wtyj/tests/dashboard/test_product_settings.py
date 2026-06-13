import json
import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("TENANT_ID", "product-settings-test")

from dashboard.api import router
from shared import config_loader


def _client() -> tuple[TestClient, str]:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    token = client.post("/dashboard/api/login", json={"password": "testpass"}).json()["token"]
    return client, token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _use_config(monkeypatch, tmp_path, data: dict) -> None:
    config_path = tmp_path / "client.json"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(config_loader, "_cache", {})


def test_product_settings_default_currency_from_business(monkeypatch, tmp_path):
    _use_config(monkeypatch, tmp_path, {"business": {"currency": "xcg"}})
    client, token = _client()

    response = client.get("/dashboard/api/settings/product-settings", headers=_auth(token))

    assert response.status_code == 200, response.text
    assert response.json() == {
        "delivery_cost_amount": None,
        "delivery_cost_currency": "XCG",
    }


def test_product_settings_save_persists_delivery_cost(monkeypatch, tmp_path):
    _use_config(monkeypatch, tmp_path, {"business": {"currency": "XCG"}})
    client, token = _client()

    response = client.put(
        "/dashboard/api/settings/product-settings",
        headers=_auth(token),
        json={"delivery_cost_amount": 5, "delivery_cost_currency": "xcg"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "delivery_cost_amount": 5.0,
        "delivery_cost_currency": "XCG",
    }
    assert config_loader.get_product_settings() == {
        "delivery_cost_amount": 5.0,
        "delivery_cost_currency": "XCG",
    }


def test_product_settings_rejects_invalid_amount(monkeypatch, tmp_path):
    _use_config(monkeypatch, tmp_path, {})
    client, token = _client()

    response = client.put(
        "/dashboard/api/settings/product-settings",
        headers=_auth(token),
        json={"delivery_cost_amount": -1, "delivery_cost_currency": "XCG"},
    )

    assert response.status_code == 400
