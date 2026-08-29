"""FRD-005 authenticated operator API contract."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from dashboard import api


def document():
    return {
        "settings": {
            "currency": "USD",
            "quoteValidityHours": 72,
            "staffQuoteEmail": "staff@example.com",
            "customerDeliveryDelaySeconds": 180,
            "availabilityMode": "request_only",
            "availabilityCopy": "Availability requires staff confirmation.",
            "quoteFooter": "",
            "pdfLogoAssetId": None,
            "refundableSecurityDepositId": "deposit",
            "refundableSecurityDepositCents": 20_000,
            "reservationDepositPercent": 15,
        },
        "categories": [{
            "id": "economy", "name": "Economy", "dailyRateCents": 3_500,
            "active": True, "displayOrder": 0, "archivedAt": None,
        }],
        "cars": [{
            "id": "picanto", "displayName": "Kia Picanto or similar",
            "categoryId": "economy", "seats": 4, "luggageCapacity": 2,
            "transmission": "automatic",
            "primaryImageAssetId": None, "active": True,
            "displayOrder": 0, "archivedAt": None,
        }],
        "supplements": [{
            "id": "child-seat", "name": "Child seat", "priceCents": 500,
            "billingBasis": "per_day", "quantitySelectable": True,
            "maxQuantity": 20, "active": True, "displayOrder": 0,
            "archivedAt": None,
        }],
    }


@pytest.fixture
def client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setattr(api, "_current_tenant_slug", lambda: "rental-test")
    monkeypatch.setattr(api, "_rental_control_center_enabled", lambda: True)
    monkeypatch.setattr(api.state_registry, "DB_PATH", str(tmp_path / "registry.db"))
    monkeypatch.setenv("RENTAL_CATALOG_CONSUMER_TOKEN", "consumer-secret")
    monkeypatch.setenv("RENTAL_CATALOG_PREVIEW_ROOT", str(tmp_path / "previews"))
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def auth():
    return {"Authorization": f"Bearer {api._SESSION_TOKEN}"}


def test_every_route_requires_auth_and_capability(client, monkeypatch):
    assert client.get("/dashboard/api/rental-catalog/draft").status_code == 401
    monkeypatch.setattr(api, "_rental_control_center_enabled", lambda: False)
    response = client.get("/dashboard/api/rental-catalog/draft", headers=auth())
    assert response.status_code == 404


def test_capability_is_authenticated_tenant_owned_and_fail_closed(client, monkeypatch):
    assert client.get("/dashboard/api/rental-catalog/capability").status_code == 401
    enabled = client.get("/dashboard/api/rental-catalog/capability", headers=auth())
    assert enabled.json() == {"tenantSlug": "rental-test", "enabled": True}
    assert enabled.headers["x-unboks-tenant"] == "rental-test"
    assert enabled.headers["cache-control"].startswith("no-store")
    monkeypatch.setattr(api, "_rental_control_center_enabled", lambda: False)
    disabled = client.get("/dashboard/api/rental-catalog/capability", headers=auth())
    assert disabled.status_code == 200
    assert disabled.json() == {"tenantSlug": "rental-test", "enabled": False}


@pytest.mark.parametrize(
    ("configured", "enabled"),
    [
        (None, False),
        (False, False),
        ("false", False),
        ("true", False),
        (0, False),
        (1, False),
        ([], False),
        ({}, False),
        (True, True),
    ],
)
def test_rental_capability_requires_literal_true(monkeypatch, configured, enabled):
    monkeypatch.setattr(
        api.config_loader,
        "get_raw",
        lambda: {"features": {"rental_control_center_enabled": configured}},
    )
    assert api._rental_control_center_enabled() is enabled


def test_draft_response_identifies_tenant_and_is_no_store(client):
    response = client.get("/dashboard/api/rental-catalog/draft", headers=auth())
    assert response.status_code == 200
    assert response.json()["tenantSlug"] == "rental-test"
    assert response.json()["revision"] == 0
    assert response.headers["x-unboks-tenant"] == "rental-test"
    assert response.headers["cache-control"].startswith("no-store")


def test_save_validate_preview_publish_and_rollback_flow(client):
    first = client.put(
        "/dashboard/api/rental-catalog/draft",
        headers=auth(),
        json={"expectedRevision": 0, "document": document()},
    )
    assert first.status_code == 200, first.text
    assert first.json()["revision"] == 1

    validation = client.post(
        "/dashboard/api/rental-catalog/validate",
        headers=auth(),
        json={"document": document()},
    )
    assert validation.json() == {
        "tenantSlug": "rental-test", "valid": True, "errors": [], "warnings": [],
    }

    preview = client.post(
        "/dashboard/api/rental-catalog/preview",
        headers=auth(),
        json={
            "document": document(),
            "scenario": {
                "rentalStart": "2026-09-01", "rentalEnd": "2026-09-04",
                "carId": "picanto", "categoryId": None,
                "supplements": [{"id": "child-seat", "quantity": 1}],
            },
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["deliveryAttempted"] is False
    assert preview.json()["quote"]["grandTotalCents"] == 32_000
    assert preview.json()["customerWhatsAppText"].startswith(
        "Your official Ali Car Rental quote is ready."
    )
    assert preview.json()["pdfBytes"] > 1_000
    pdf = client.get(
        f"/dashboard/api/rental-catalog/previews/{preview.json()['pdfPreviewId']}/pdf",
        headers=auth(),
    )
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["x-unboks-tenant"] == "rental-test"
    assert pdf.content.startswith(b"%PDF")

    published = client.post(
        "/dashboard/api/rental-catalog/publish",
        headers=auth(),
        json={"expectedRevision": 1, "idempotencyKey": "publish-1"},
    )
    replay = client.post(
        "/dashboard/api/rental-catalog/publish",
        headers=auth(),
        json={"expectedRevision": 999, "idempotencyKey": "publish-1"},
    )
    assert published.status_code == replay.status_code == 200
    assert published.json()["version"] == replay.json()["version"] == 1

    changed = document()
    changed["categories"][0]["dailyRateCents"] = 4_000
    assert client.put(
        "/dashboard/api/rental-catalog/draft",
        headers=auth(),
        json={"expectedRevision": 1, "document": changed},
    ).status_code == 200
    assert client.post(
        "/dashboard/api/rental-catalog/publish",
        headers=auth(),
        json={"expectedRevision": 2, "idempotencyKey": "publish-2"},
    ).status_code == 200
    rollback = client.post(
        "/dashboard/api/rental-catalog/rollback",
        headers=auth(),
        json={"expectedCurrentVersion": 2, "idempotencyKey": "rollback-1"},
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["version"] == 3
    assert rollback.json()["sourceVersion"] == 1
    assert rollback.json()["document"] == document()


def test_stale_save_is_409_and_unknown_request_fields_are_422(client):
    assert client.put(
        "/dashboard/api/rental-catalog/draft",
        headers=auth(),
        json={"expectedRevision": 0, "document": document()},
    ).status_code == 200
    stale = client.put(
        "/dashboard/api/rental-catalog/draft",
        headers=auth(),
        json={"expectedRevision": 0, "document": document()},
    )
    unknown = client.post(
        "/dashboard/api/rental-catalog/publish",
        headers=auth(),
        json={"expectedRevision": 1, "idempotencyKey": "publish-1", "tenantId": "other"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_revision"
    assert unknown.status_code == 422


def test_field_errors_never_expose_internal_exception_or_other_tenant(client):
    invalid = document()
    invalid["cars"][0]["categoryId"] = "tenant-b-secret-category"
    response = client.put(
        "/dashboard/api/rental-catalog/draft",
        headers=auth(),
        json={"expectedRevision": 0, "document": invalid},
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["code"] == "invalid_draft"
    assert payload["detail"]["errors"][0]["path"] == "cars.0.categoryId"
    assert "traceback" not in response.text.lower()


def test_published_consumer_requires_separate_service_token(client):
    assert client.put(
        "/dashboard/api/rental-catalog/draft",
        headers=auth(),
        json={"expectedRevision": 0, "document": document()},
    ).status_code == 200
    assert client.post(
        "/dashboard/api/rental-catalog/publish",
        headers=auth(),
        json={"expectedRevision": 1, "idempotencyKey": "publish-1"},
    ).status_code == 200
    endpoint = "/dashboard/api/rental-catalog/published"
    assert client.get(endpoint).status_code == 401
    assert client.get(endpoint, headers=auth()).status_code == 401
    response = client.get(
        endpoint, headers={"Authorization": "Bearer consumer-secret"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["tenantSlug"] == "rental-test"
    assert response.json()["catalogVersion"] == 1
    assert response.headers["x-unboks-tenant"] == "rental-test"
    assert response.headers["cache-control"].startswith("no-store")


def test_rental_media_delete_fails_closed_when_historical_version_uses_asset(
    client, monkeypatch,
):
    monkeypatch.setattr(
        api,
        "_rental_media_photo",
        lambda asset_id: {
            "id": int(asset_id), "filename": "photo.jpg",
            "service_key": "knowledge:rental_catalog:picanto",
        },
    )
    monkeypatch.setattr(
        api.rental_catalog,
        "media_reference_count",
        lambda tenant, asset_id: 1,
    )
    deleted = []
    monkeypatch.setattr(api.state_registry, "delete_photo", deleted.append)
    response = client.delete(
        "/dashboard/api/rental-catalog/media/42", headers=auth()
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "rental_media_in_use"
    assert deleted == []


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("delete", "/dashboard/api/photos/42", None),
        ("delete", "/dashboard/api/knowledge/media/42", None),
        (
            "put",
            "/dashboard/api/photos/42",
            {"service_key": "knowledge:other:moved"},
        ),
    ],
)
def test_generic_photo_routes_cannot_mutate_referenced_rental_media(
    client, monkeypatch, method, path, json,
):
    photo = {
        "id": 42,
        "filename": "photo.jpg",
        "service_key": "knowledge:rental_catalog:picanto",
    }
    monkeypatch.setattr(api.state_registry, "get_photo_by_id", lambda _id: photo)
    monkeypatch.setattr(
        api.rental_catalog,
        "media_reference_count",
        lambda tenant, asset_id: 1,
    )
    deleted = []
    updated = []
    monkeypatch.setattr(api.state_registry, "delete_photo", deleted.append)
    monkeypatch.setattr(
        api.state_registry,
        "update_photo",
        lambda *args, **kwargs: updated.append((args, kwargs)) or True,
    )

    response = client.request(method, path, headers=auth(), json=json)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "rental_media_in_use"
    assert deleted == []
    assert updated == []


def test_generic_photo_delete_remains_unchanged_for_non_rental_media(
    client, monkeypatch,
):
    photo = {
        "id": 42,
        "filename": "photo.jpg",
        "service_key": "knowledge:info_update:menu",
    }
    monkeypatch.setattr(api.state_registry, "get_photo_by_id", lambda _id: photo)
    monkeypatch.setattr(api.state_registry, "delete_photo", lambda _id: "photo.jpg")
    monkeypatch.setattr(
        api.rental_catalog,
        "media_reference_count",
        lambda *_args: pytest.fail("non-Rental media must not query Rental history"),
    )
    monkeypatch.setattr(api.os, "remove", lambda _path: None)

    response = client.delete("/dashboard/api/photos/42", headers=auth())

    assert response.status_code == 200
    assert response.json() == {"ok": True}
