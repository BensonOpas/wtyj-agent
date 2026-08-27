"""FRD-005 reversible Carlos catalog provider boundary."""

from agents.social import ali_quote_workflow as workflow
from shared import rental_catalog, state_registry


def raw(enabled: bool):
    return {
        "slug": "ali-car-rental",
        "workflow": {"type": "ali_quote"},
        "features": {"rental_catalog_consumer_enabled": enabled},
    }


def document():
    return {
        "settings": {
            "currency": "USD", "quoteValidityHours": 72,
            "staffQuoteEmail": "staff@example.com",
            "customerDeliveryDelaySeconds": 180,
            "availabilityMode": "request_only",
            "availabilityCopy": "Availability requires staff confirmation.",
            "quoteFooter": "", "pdfLogoAssetId": None,
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
            "categoryId": "economy", "seats": 4, "transmission": "automatic",
            "primaryImageAssetId": None, "active": True,
            "displayOrder": 0, "archivedAt": None,
        }],
        "supplements": [],
    }


def publish_catalog(monkeypatch, tmp_path):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "registry.db"))
    rental_catalog.save_draft(
        "ali-car-rental", document(), expected_revision=0, actor="test"
    )
    rental_catalog.publish(
        "ali-car-rental", expected_revision=1,
        idempotency_key="publish-1", actor="test",
    )


def test_provider_flag_is_separate_and_defaults_to_legacy():
    assert workflow.rental_control_center_provider_enabled(raw(False)) is False
    assert workflow.rental_control_center_provider_enabled(raw(True)) is True
    assert workflow.rental_control_center_provider_enabled({}) is False


def test_active_client_switches_without_rewriting_quote_state(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(workflow, "AliQuoteClient", lambda *args, **kwargs: sentinel)
    assert workflow.active_quote_client(raw(False)) is sentinel
    assert isinstance(
        workflow.active_quote_client(raw(True)),
        workflow.RentalControlCenterQuoteClient,
    )


def test_local_provider_returns_published_contract_and_quote(monkeypatch, tmp_path):
    publish_catalog(monkeypatch, tmp_path)
    client = workflow.RentalControlCenterQuoteClient()
    catalog = client.get_catalog()
    assert catalog["catalogVersion"] == 1
    assert catalog["vehicles"][0]["dailyRate"]["amount"] == "35.00"
    assert catalog["vehicles"][0]["slug"] == "kia-picanto-or-similar"
    quote = client.create_quote({
        "rentalStart": "2026-09-01",
        "rentalEnd": "2026-09-04",
        "selection": {"vehicleId": "picanto"},
        "extraSelections": [],
        "chargeSelections": ["deposit"],
    }, "quote-1")
    assert quote["catalogVersion"] == 1
    assert quote["rentalTotal"]["amount"] == "105.00"
    assert quote["refundableSecurityDeposit"]["amount"] == "200.00"


def test_catalog_cache_is_scoped_by_provider(monkeypatch):
    class Client:
        def __init__(self, version):
            self.version = version

        def get_catalog(self):
            return {"catalogVersion": self.version}

    providers = iter([Client(13), Client(1)])
    enabled = iter([False, True])
    monkeypatch.setattr(
        workflow, "rental_control_center_provider_enabled", lambda raw=None: next(enabled)
    )
    monkeypatch.setattr(workflow, "active_quote_client", lambda raw=None: next(providers))
    workflow.invalidate_catalog_cache()
    assert workflow.get_intake_catalog()["catalogVersion"] == 13
    assert workflow.get_intake_catalog()["catalogVersion"] == 1
