"""Operator catalog publishing: auth, persistence, races and quote isolation."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard import api
from shared import config_loader, mermaid_catalog as catalog, state_registry
from agents.social import mermaid_reservation_store as reservations

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def client(tmp_path, monkeypatch):
    baseline = json.loads((ROOT / "clients/mermaid/config/reservation_catalog.json").read_text())
    (tmp_path / "reservation_catalog.json").write_text(json.dumps(baseline))
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(tmp_path / "client.json"))
    monkeypatch.setattr(config_loader, "get_raw", lambda: {"slug": "mermaid", "features": {"mermaid_dashboard_projection": True}})
    monkeypatch.setattr(api, "_current_tenant_slug", lambda: "mermaid")
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def auth():
    return {"Authorization": "Bearer " + api._SESSION_TOKEN}


def published(client):
    response = client.get("/dashboard/api/mermaid-reservations/catalog", headers=auth())
    assert response.status_code == 200
    assert response.headers["x-unboks-tenant"] == "mermaid"
    assert response.json()["editable"] is True
    return response.json()


def put(client, changes, revision=None):
    return client.put("/dashboard/api/mermaid-reservations/catalog", headers=auth(), json={
        "expected_revision": revision or published(client)["revision"], "changes": changes,
    })


def test_save_requires_auth_and_tenant_and_feature(client, monkeypatch):
    payload = {"expected_revision": published(client)["revision"], "changes": {"service": {"name": "Edited"}}}
    assert client.put("/dashboard/api/mermaid-reservations/catalog", json=payload).status_code == 401
    monkeypatch.setattr(api, "_current_tenant_slug", lambda: "ali-car-rental")
    assert client.put("/dashboard/api/mermaid-reservations/catalog", headers=auth(), json=payload).status_code == 404
    monkeypatch.setattr(api, "_current_tenant_slug", lambda: "mermaid")
    monkeypatch.setattr(config_loader, "get_raw", lambda: {"features": {}})
    assert client.put("/dashboard/api/mermaid-reservations/catalog", headers=auth(), json=payload).status_code == 404


def test_publishes_real_catalog_and_keeps_previous_version(client, tmp_path):
    before = published(client)
    prices = copy.deepcopy(before["catalog"]["pricing"]["currencies"])
    prices["USD"]["adult"] = 180
    response = put(client, {"service": {"name": "Mermaid island day", "arrival_time": "07:00", "island_departure_time": "16:00", "meeting_point": "New approved pier", "operating_weekdays": ["monday", "thursday"]}, "pricing": {"currencies": prices}, "included": ["Breakfast", "Lunch"], "bring": ["Towel"], "extras": ["Drinks"]})
    assert response.status_code == 200, response.text
    after = response.json()
    assert published(client) == after
    assert catalog.get_catalog()["pricing"]["currencies"]["USD"]["adult"] == 180
    assert catalog.pickup_time() == "06:00"
    assert after["revision"] != before["revision"]
    assert after["catalog"]["version"] != before["catalog"]["version"]
    for field in ("tenant_slug", "guest_copy", "links"):
        assert after["catalog"][field] == before["catalog"][field]
    history = list((tmp_path / "reservation_catalog_history").glob("*.json"))
    assert len(history) == 1 and json.loads(history[0].read_text()) == before["catalog"]
    assert "no-store" in response.headers["cache-control"]


def test_vehicle_changes_reach_price_engine_without_stale_transport_prose(client):
    assert put(client, {"pricing": {"pickup_vehicles": [{"key": "car", "capacity": 4, "price": 90}, {"key": "van", "capacity": 8, "price": 140}], "pickup_overflow": "multiple_vans"}}).status_code == 200
    assert catalog.pickup_quote(4)["amount"] == 90
    assert catalog.pickup_quote(5)["amount"] == 140
    assert catalog.pickup_quote(17)["amount"] == 420
    assert not any(item.startswith("Optional island-wide pickup:") for item in catalog.get_catalog()["extras"])


def test_stale_revision_does_not_overwrite(client):
    old = published(client)["revision"]
    assert put(client, {"service": {"name": "First operator"}}, old).status_code == 200
    assert put(client, {"service": {"name": "Second operator"}}, old).status_code == 409
    assert catalog.get_catalog()["service"]["name"] == "First operator"


def test_external_file_edit_also_invalidates_revision(client):
    before = published(client)
    changed = before["catalog"]
    changed["service"]["name"] = "Changed outside dashboard"
    catalog._catalog_path().write_text(json.dumps(changed))
    assert put(client, {"service": {"name": "Stale edit"}}, before["revision"]).status_code == 409


def test_concurrent_publish_has_one_winner(client):
    old = published(client)["revision"]
    def publish(index):
        try:
            catalog.publish_catalog({"service": {"name": f"Operator {index}"}}, old)
            return "saved"
        except catalog.MermaidCatalogConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(publish, range(6)))
    assert results.count("saved") == 1
    assert results.count("conflict") == 5


@pytest.mark.parametrize("changes", [
    {"tenant_slug": "ali-car-rental"}, {"version": "anything"}, {"links": {"checkout_base_url": "https://example.com"}},
    {"guest_copy": {}}, {"features": {"real_payments": True}}, {"service": {"key": "different"}},
    {"service": {"name": ""}}, {"service": {"operating_weekdays": []}}, {"service": {"operating_weekdays": ["holiday"]}},
    {"service": {"arrival_time": "24:00"}}, {"service": {"arrival_time": "17:00"}}, {"service": {"pickup_minutes_before_arrival": 1000}},
    {"pricing": {"currencies": {"USD": {}}}}, {"pricing": {"default_currency": "GBP"}},
    {"pricing": {"default_currency": []}}, {"pricing": {"pickup_currency": []}}, {"pricing": {"pickup_overflow": []}},
    {"pricing": {"default_currency": "EUR"}},
    {"pricing": {"pickup_vehicles": [{"key": "car", "capacity": 10, "price": 80}, {"key": "van", "capacity": 9, "price": 100}]}},
    {"included": [False]}, {"bring": "Towel"}, {"extras": ["x" * 1001]},
    {"policies": {"cancellation": "Not marked as demo"}}, {"policies": {"insurance": "Fully insured"}},
])
def test_invalid_or_system_owned_fields_never_write(client, changes):
    before = catalog._catalog_path().read_bytes()
    assert put(client, changes).status_code == 422
    assert catalog._catalog_path().read_bytes() == before


def test_rejects_invalid_revision_and_unknown_request_fields(client):
    body = {"expected_revision": "old", "changes": {"included": []}}
    assert client.put("/dashboard/api/mermaid-reservations/catalog", headers=auth(), json=body).status_code == 422
    body.update(expected_revision=published(client)["revision"], tenant="other")
    assert client.put("/dashboard/api/mermaid-reservations/catalog", headers=auth(), json=body).status_code == 422


def test_failed_persistence_does_not_claim_success(client, monkeypatch):
    before = catalog._catalog_path().read_bytes()
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(catalog, "_atomic_catalog_write", fail)
    assert put(client, {"service": {"name": "Not saved"}}).status_code == 503
    assert catalog._catalog_path().read_bytes() == before


def test_existing_reservation_prices_do_not_change_after_publish(client):
    intake = {"trip_date": "2026-09-05", "adults": 2, "children": 0, "infants": 0, "customer_name": "Test guest", "contact_phone": "+5999000000", "pickup_preference": "pier", "language": "en", "phase": "summary_confirmed"}
    before = reservations.confirm_reservation("test-guest-one", intake, idempotency_key="one")
    prices = copy.deepcopy(catalog.get_catalog()["pricing"]["currencies"])
    prices["USD"]["adult"] = 200
    assert put(client, {"pricing": {"currencies": prices}}).status_code == 200
    assert reservations.get_reservation(before["public_id"])["monetary_snapshot"] == before["monetary_snapshot"]
    replay = reservations.confirm_reservation("test-guest-one", intake, idempotency_key="one")
    assert replay["monetary_snapshot"] == before["monetary_snapshot"]
    after = reservations.confirm_reservation("test-guest-two", intake, idempotency_key="two")
    assert before["monetary_snapshot"]["total"] == 300
    assert after["monetary_snapshot"]["total"] == 400
    assert after["catalog_version"] != before["catalog_version"]


def test_tracy_prompt_reads_published_catalog_without_restart(client):
    from agents.social.mermaid_understanding import system_prompt
    assert put(client, {"service": {"name": "Published trip name"}, "included": ["Freshly approved inclusion"]}).status_code == 200
    prompt = system_prompt()
    assert "Published trip name" in prompt
    assert "Freshly approved inclusion" in prompt
    assert "supersedes older business-knowledge" in prompt
