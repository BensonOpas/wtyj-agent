import copy
from datetime import datetime, timezone

import pytest

from shared import rental_catalog, state_registry


def catalog_document():
    return {
        "settings": {
            "currency": "USD",
            "quoteValidityHours": 72,
            "staffQuoteEmail": "staff@example.com",
            "customerDeliveryDelaySeconds": 180,
            "availabilityMode": "request_only",
            "availabilityCopy": "Availability requires staff confirmation.",
            "quoteFooter": "Synthetic preview",
            "pdfLogoAssetId": None,
            "refundableSecurityDepositId": "deposit",
            "refundableSecurityDepositCents": 20_000,
            "reservationDepositPercent": 15,
        },
        "categories": [{
            "id": "economy",
            "name": "Economy",
            "dailyRateCents": 3_500,
            "active": True,
            "displayOrder": 0,
            "archivedAt": None,
        }],
        "cars": [{
            "id": "picanto",
            "displayName": "Kia Picanto or similar",
            "categoryId": "economy",
            "seats": 4,
            "transmission": "automatic",
            "primaryImageAssetId": None,
            "active": True,
            "displayOrder": 0,
            "archivedAt": None,
        }],
        "supplements": [{
            "id": "child-seat",
            "name": "Child seat",
            "priceCents": 500,
            "billingBasis": "per_day",
            "quantitySelectable": True,
            "maxQuantity": 20,
            "active": True,
            "displayOrder": 0,
            "archivedAt": None,
        }, {
            "id": "airport-service",
            "name": "Airport service",
            "priceCents": 1_250,
            "billingBasis": "per_rental",
            "quantitySelectable": False,
            "maxQuantity": 1,
            "active": True,
            "displayOrder": 1,
            "archivedAt": None,
        }],
    }


def test_validation_rejects_unknown_fields_duplicate_ids_and_inactive_category():
    document = catalog_document()
    document["unexpected"] = True
    result = rental_catalog.validate_document(document, for_publish=True)
    assert result.valid is False
    assert any(error["code"] == "extra_forbidden" for error in result.errors)

    document = catalog_document()
    document["categories"][0]["active"] = False
    document["categories"].append(copy.deepcopy(document["categories"][0]))
    result = rental_catalog.validate_document(document, for_publish=True)
    assert {error["code"] for error in result.errors} >= {
        "duplicate_id", "inactive_category",
    }


def test_validation_rejects_floats_and_missing_tenant_media():
    document = catalog_document()
    document["categories"][0]["dailyRateCents"] = 35.0
    result = rental_catalog.validate_document(document)
    assert any(error["path"] == "categories.0.dailyRateCents" for error in result.errors)

    document = catalog_document()
    document["cars"][0]["primaryImageAssetId"] = "missing-image"
    result = rental_catalog.validate_document(
        document,
        for_publish=True,
        media_exists=lambda asset_id: asset_id != "missing-image",
    )
    assert any(error["code"] == "missing_media" for error in result.errors)


def test_preview_uses_integer_cents_and_separates_refundable_deposit():
    result = rental_catalog.calculate_preview(catalog_document(), {
        "rentalStart": "2026-09-01",
        "rentalEnd": "2026-09-08",
        "carId": "picanto",
        "categoryId": None,
        "supplements": [
            {"id": "child-seat", "quantity": 2},
            {"id": "airport-service", "quantity": 1},
        ],
    })
    assert result["rentalDays"] == 7
    assert result["items"][0]["subtotalCents"] == 24_500
    assert result["items"][1]["subtotalCents"] == 7_000
    assert result["items"][2]["subtotalCents"] == 1_250
    assert result["rentalTotalCents"] == 32_750
    assert result["refundableSecurityDepositCents"] == 20_000
    assert result["grandTotalCents"] == 52_750


def test_preview_rejects_duplicate_or_excess_supplements():
    scenario = {
        "rentalStart": "2026-09-01",
        "rentalEnd": "2026-09-02",
        "categoryId": "economy",
        "carId": None,
        "supplements": [
            {"id": "child-seat", "quantity": 1},
            {"id": "child-seat", "quantity": 1},
        ],
    }
    with pytest.raises(rental_catalog.RentalCatalogError, match="duplicate_supplement_selection"):
        rental_catalog.calculate_preview(catalog_document(), scenario)
    scenario["supplements"] = [{"id": "child-seat", "quantity": 21}]
    with pytest.raises(rental_catalog.RentalCatalogError, match="invalid_preview_scenario"):
        rental_catalog.calculate_preview(catalog_document(), scenario)


def test_draft_revision_is_monotonic_and_stale_write_is_rejected(tmp_path):
    db_path = str(tmp_path / "registry.db")
    first = rental_catalog.save_draft(
        "tenant-a", catalog_document(), expected_revision=0, actor="operator", db_path=db_path
    )
    assert first["revision"] == 1
    second_document = catalog_document()
    second_document["categories"][0]["dailyRateCents"] = 3_600
    second = rental_catalog.save_draft(
        "tenant-a", second_document, expected_revision=1, actor="operator", db_path=db_path
    )
    assert second["revision"] == 2
    with pytest.raises(rental_catalog.RentalCatalogError) as caught:
        rental_catalog.save_draft(
            "tenant-a", catalog_document(), expected_revision=1, actor="operator", db_path=db_path
        )
    assert caught.value.code == "stale_revision"
    assert caught.value.status_code == 409


def test_publish_is_immutable_and_idempotent(tmp_path):
    db_path = str(tmp_path / "registry.db")
    rental_catalog.save_draft(
        "tenant-a", catalog_document(), expected_revision=0, actor="operator", db_path=db_path
    )
    first = rental_catalog.publish(
        "tenant-a",
        expected_revision=1,
        idempotency_key="publish-1",
        actor="operator",
        db_path=db_path,
    )
    replay = rental_catalog.publish(
        "tenant-a",
        expected_revision=999,
        idempotency_key="publish-1",
        actor="operator",
        db_path=db_path,
    )
    assert first["version"] == replay["version"] == 1
    assert first["contentHash"] == replay["contentHash"]
    assert rental_catalog.get_published("tenant-a", db_path=db_path)["document"] == catalog_document()


def test_consumer_projection_is_carlos_compatible_and_category_priced(tmp_path):
    db_path = str(tmp_path / "registry.db")
    rental_catalog.save_draft(
        "tenant-a", catalog_document(), expected_revision=0, actor="operator", db_path=db_path
    )
    rental_catalog.publish(
        "tenant-a", expected_revision=1, idempotency_key="publish-1", actor="operator", db_path=db_path
    )
    contract = rental_catalog.consumer_catalog("tenant-a", db_path=db_path)
    assert contract["catalogVersion"] == 1
    assert contract["currency"] == "USD"
    assert contract["availabilityMode"] == "request_only"
    assert contract["reservationDepositPercent"] == 15
    assert contract["vehicleClasses"][0]["dailyRate"]["amount"] == "35.00"
    assert contract["vehicles"][0]["dailyRate"]["amount"] == "35.00"
    assert contract["vehicles"][0]["weeklyRate"]["amount"] == "245.00"
    assert contract["extras"][0]["billingBasis"] == "per_day"
    assert contract["charges"] == [{
        "id": "deposit",
        "kind": "deposit",
        "name": "Refundable security deposit",
        "price": {"currency": "USD", "amount": "200.00"},
        "refundable": True,
    }]


def test_consumer_projection_resolves_tenant_owned_media(monkeypatch, tmp_path):
    db_path = str(tmp_path / "registry.db")
    document = catalog_document()
    document["cars"][0]["primaryImageAssetId"] = "42"
    rental_catalog.save_draft(
        "tenant-a", document, expected_revision=0, actor="operator", db_path=db_path
    )
    rental_catalog.publish(
        "tenant-a", expected_revision=1, idempotency_key="publish-1",
        actor="operator", media_exists=lambda _asset_id: True, db_path=db_path,
    )
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "https://api.unboks.org")
    monkeypatch.setattr(state_registry, "get_photo_by_id", lambda _photo_id: {
        "id": 42,
        "filename": "photo_42_safe.jpg",
        "service_key": "knowledge:rental_catalog:picanto",
        "tags": ["Kia Picanto or similar"],
    })

    contract = rental_catalog.consumer_catalog("tenant-a", db_path=db_path)

    assert contract["vehicles"][0]["images"] == [{
        "assetId": "42",
        "primary": True,
        "url": (
            "https://api.unboks.org/api/tenant-a/dashboard/api/public/media/"
            "photo_42_safe.jpg"
        ),
        "alt": "Kia Picanto or similar",
    }]


def test_consumer_projection_rejects_non_catalog_media(monkeypatch, tmp_path):
    db_path = str(tmp_path / "registry.db")
    document = catalog_document()
    document["cars"][0]["primaryImageAssetId"] = "42"
    rental_catalog.save_draft(
        "tenant-a", document, expected_revision=0, actor="operator", db_path=db_path
    )
    rental_catalog.publish(
        "tenant-a", expected_revision=1, idempotency_key="publish-1",
        actor="operator", media_exists=lambda _asset_id: True, db_path=db_path,
    )
    monkeypatch.setattr(state_registry, "get_photo_by_id", lambda _photo_id: {
        "id": 42,
        "filename": "photo_42_other.jpg",
        "service_key": "knowledge:other:picanto",
        "tags": [],
    })

    contract = rental_catalog.consumer_catalog("tenant-a", db_path=db_path)

    assert contract["vehicles"][0]["images"] == []


def test_local_quote_snapshot_is_idempotent_and_financially_immutable(tmp_path):
    db_path = str(tmp_path / "registry.db")
    rental_catalog.save_draft(
        "ali-car-rental", catalog_document(), expected_revision=0, actor="operator", db_path=db_path
    )
    rental_catalog.publish(
        "ali-car-rental", expected_revision=1, idempotency_key="publish-1", actor="operator", db_path=db_path
    )
    request = {
        "rentalStart": "2026-09-01",
        "rentalEnd": "2026-09-08",
        "selection": {"vehicleId": "picanto"},
        "extraSelections": [{"id": "child-seat", "quantity": 2}],
        "chargeSelections": ["deposit"],
    }
    instant = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
    quote = rental_catalog.create_quote_snapshot(
        "ali-car-rental", request, idempotency_key="quote-1", db_path=db_path,
        now=lambda: instant,
    )
    assert quote["catalogVersion"] == 1
    assert quote["quoteReference"].startswith("ALI-20260901-")
    assert quote["rentalTotal"] == {"currency": "USD", "amount": "315.00"}
    assert quote["refundableSecurityDeposit"] == {"currency": "USD", "amount": "200.00"}
    assert quote["total"] == {"currency": "USD", "amount": "515.00"}
    assert quote["reservationDeposit"] == {"currency": "USD", "amount": "47.25"}
    assert quote["expiresAt"] == "2026-09-04T14:00:00Z"

    changed = catalog_document()
    changed["categories"][0]["dailyRateCents"] = 9_500
    rental_catalog.save_draft(
        "ali-car-rental", changed, expected_revision=1, actor="operator", db_path=db_path
    )
    rental_catalog.publish(
        "ali-car-rental", expected_revision=2, idempotency_key="publish-2", actor="operator", db_path=db_path
    )
    replay = rental_catalog.create_quote_snapshot(
        "ali-car-rental", request, idempotency_key="quote-1", db_path=db_path,
        now=lambda: datetime(2027, 1, 1, tzinfo=timezone.utc),
    )
    assert replay == quote


def test_rollback_creates_new_version_and_realigns_draft(tmp_path):
    db_path = str(tmp_path / "registry.db")
    original = catalog_document()
    rental_catalog.save_draft(
        "tenant-a", original, expected_revision=0, actor="operator", db_path=db_path
    )
    rental_catalog.publish(
        "tenant-a", expected_revision=1, idempotency_key="publish-1", actor="operator", db_path=db_path
    )
    changed = catalog_document()
    changed["categories"][0]["dailyRateCents"] = 4_000
    rental_catalog.save_draft(
        "tenant-a", changed, expected_revision=1, actor="operator", db_path=db_path
    )
    rental_catalog.publish(
        "tenant-a", expected_revision=2, idempotency_key="publish-2", actor="operator", db_path=db_path
    )
    rollback = rental_catalog.rollback(
        "tenant-a",
        expected_current_version=2,
        idempotency_key="rollback-1",
        actor="operator",
        db_path=db_path,
    )
    assert rollback["version"] == 3
    assert rollback["sourceVersion"] == 1
    assert rollback["document"] == original
    assert rollback["draftRevision"] == 3
    assert rental_catalog.get_draft("tenant-a", db_path=db_path)["document"] == original


def test_tenants_never_share_drafts_or_versions(tmp_path):
    db_path = str(tmp_path / "registry.db")
    tenant_a = catalog_document()
    tenant_b = catalog_document()
    tenant_b["categories"][0]["dailyRateCents"] = 9_500
    rental_catalog.save_draft(
        "tenant-a", tenant_a, expected_revision=0, actor="operator", db_path=db_path
    )
    rental_catalog.save_draft(
        "tenant-b", tenant_b, expected_revision=0, actor="operator", db_path=db_path
    )
    rental_catalog.publish(
        "tenant-a", expected_revision=1, idempotency_key="same-key", actor="operator", db_path=db_path
    )
    rental_catalog.publish(
        "tenant-b", expected_revision=1, idempotency_key="same-key", actor="operator", db_path=db_path
    )
    assert rental_catalog.get_published("tenant-a", db_path=db_path)["document"] == tenant_a
    assert rental_catalog.get_published("tenant-b", db_path=db_path)["document"] == tenant_b


def test_published_media_reference_survives_draft_replacement(tmp_path):
    db_path = str(tmp_path / "registry.db")
    with_image = catalog_document()
    with_image["cars"][0]["primaryImageAssetId"] = "42"
    rental_catalog.save_draft(
        "tenant-a", with_image, expected_revision=0, actor="operator", db_path=db_path
    )
    assert rental_catalog.media_reference_count("tenant-a", "42", db_path=db_path) == 1
    rental_catalog.publish(
        "tenant-a", expected_revision=1, idempotency_key="publish-1",
        actor="operator", media_exists=lambda _asset_id: True, db_path=db_path,
    )
    assert rental_catalog.media_reference_count("tenant-a", "42", db_path=db_path) == 2
    without_image = catalog_document()
    rental_catalog.save_draft(
        "tenant-a", without_image, expected_revision=1, actor="operator", db_path=db_path
    )
    assert rental_catalog.media_reference_count("tenant-a", "42", db_path=db_path) == 1
