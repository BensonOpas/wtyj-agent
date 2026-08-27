"""Brief 290: authenticated Ali post-quote reservation dashboard API."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from dashboard import api


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(api.ali_quote_workflow, "tenant_configured", lambda: True)
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {api._SESSION_TOKEN}"}


def test_reservation_routes_require_auth_and_ali_tenant(client, monkeypatch):
    assert client.get("/dashboard/api/ali-reservations").status_code == 401

    monkeypatch.setattr(api.ali_quote_workflow, "tenant_configured", lambda: False)
    response = client.get("/dashboard/api/ali-reservations", headers=_auth())

    assert response.status_code == 404
    assert response.json()["detail"] == "Quote leads are not enabled for this tenant"


def test_list_reservations_validates_filter_and_disables_cache(client, monkeypatch):
    captured = []
    monkeypatch.setattr(
        api.ali_reservation_workflow,
        "list_reservations",
        lambda status=None: captured.append(status) or [{"public_id": "res-290"}],
    )

    response = client.get(
        "/dashboard/api/ali-reservations?status=availability_pending",
        headers=_auth(),
    )
    invalid = client.get(
        "/dashboard/api/ali-reservations?status=unknown",
        headers=_auth(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [{"public_id": "res-290"}],
        "reservations": [{"public_id": "res-290"}],
    }
    assert response.headers["cache-control"] == (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    assert captured == ["availability_pending"]
    assert invalid.status_code == 422
    assert captured == ["availability_pending"]


def test_get_reservation_returns_workflow_projection(client, monkeypatch):
    monkeypatch.setattr(
        api.ali_reservation_workflow,
        "get_reservation",
        lambda public_id: {"public_id": public_id, "status": "requirements_pending"},
    )

    response = client.get(
        "/dashboard/api/ali-reservations/res-290",
        headers=_auth(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "public_id": "res-290",
        "status": "requirements_pending",
    }


def test_payment_review_forwards_audited_override_reason(client, monkeypatch):
    captured = {}

    def review_payment(public_id, decision, actor, expected_revision=None, reason=""):
        captured.update({
            "public_id": public_id,
            "decision": decision,
            "actor": actor,
            "expected_revision": expected_revision,
            "reason": reason,
        })
        return {"public_id": public_id, "payment_status": decision}

    monkeypatch.setattr(api.ali_customer_dossier, "review_payment", review_payment)
    response = client.post(
        "/dashboard/api/ali-reservations/res-290/payment/review",
        headers=_auth(),
        json={
            "decision": "verified",
            "expectedRevision": 8,
            "reason": "Bank receipt checked by owner.",
        },
    )

    assert response.status_code == 200
    assert captured == {
        "public_id": "res-290",
        "decision": "verified",
        "actor": "dashboard",
        "expected_revision": 8,
        "reason": "Bank receipt checked by owner.",
    }


def test_alternative_decision_normalizes_allowlisted_vehicle(client, monkeypatch):
    captured = {}

    def apply_staff_decision(public_id, **kwargs):
        captured.update({"public_id": public_id, **kwargs})
        return {"public_id": public_id, "status": "alternative_required"}

    monkeypatch.setattr(
        api.ali_reservation_workflow,
        "apply_staff_decision",
        apply_staff_decision,
    )

    response = client.post(
        "/dashboard/api/ali-reservations/res-290/availability-decision",
        headers=_auth(),
        json={
            "decision": "alternative",
            "alternativeVehicle": {
                "vehicleClassId": " suv-plus ",
                "vehicleName": " Toyota 4Runner ",
                "dailyRateUsd": "95.00",
                "currency": "usd",
            },
            "expectedRevision": 2,
        },
    )

    assert response.status_code == 200
    assert captured == {
        "public_id": "res-290",
        "decision": "alternative",
        "actor": "dashboard",
        "note": None,
        "alternative_vehicle": {
            "vehicle_name": "Toyota 4Runner",
            "vehicle_class_id": "suv-plus",
            "daily_rate_usd": "95.00",
            "currency": "USD",
        },
        "expected_revision": 2,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"decision": "alternative"},
        {"decision": "alternative", "alternativeVehicle": {"currency": "USD"}},
        {
            "decision": "approve",
            "alternativeVehicle": {"vehicleClassId": "economy"},
        },
        {
            "decision": "alternative",
            "alternativeVehicle": {
                "vehicleClassId": "economy",
                "internalNotes": "must never pass through",
            },
        },
    ],
)
def test_availability_decision_rejects_invalid_alternative_payloads(client, payload):
    response = client.post(
        "/dashboard/api/ali-reservations/res-290/availability-decision",
        headers=_auth(),
        json=payload,
    )

    assert response.status_code == 422


def test_checklist_requires_one_field_and_forwards_field_specific_values(
    client, monkeypatch,
):
    captured = {}

    def update_checklist(public_id, **kwargs):
        captured.update({"public_id": public_id, **kwargs})
        return {"public_id": public_id, "status": "ready_to_confirm"}

    monkeypatch.setattr(
        api.ali_reservation_workflow,
        "update_checklist",
        update_checklist,
    )

    empty = client.patch(
        "/dashboard/api/ali-reservations/res-290/checklist",
        headers=_auth(),
        json={},
    )
    invalid = client.patch(
        "/dashboard/api/ali-reservations/res-290/checklist",
        headers=_auth(),
        json={"identity": "uploaded"},
    )
    response = client.patch(
        "/dashboard/api/ali-reservations/res-290/checklist",
        headers=_auth(),
        json={
            "identity": "verified",
            "agreement": "sent_external",
            "payment": "not_required",
            "expectedRevision": 3,
        },
    )

    assert empty.status_code == 422
    assert invalid.status_code == 422
    assert response.status_code == 200
    assert captured == {
        "public_id": "res-290",
        "identity": "verified",
        "agreement": "sent_external",
        "payment": "not_required",
        "actor": "dashboard",
        "note": None,
        "expected_revision": 3,
    }


def test_confirm_forwards_revision_and_maps_safe_workflow_conflict(client, monkeypatch):
    captured = {}

    def confirm(public_id, **kwargs):
        captured.update({"public_id": public_id, **kwargs})
        return {"public_id": public_id, "status": "confirmed", "reference": "ALI-R-290"}

    monkeypatch.setattr(api.ali_reservation_workflow, "confirm_reservation", confirm)
    monkeypatch.setattr(
        api.ali_quote_delivery,
        "send_customer_reservation_confirmation",
        lambda reservation: reservation,
    )
    response = client.post(
        "/dashboard/api/ali-reservations/res-290/confirm",
        headers=_auth(),
        json={"expectedRevision": 4},
    )

    assert response.status_code == 200
    assert captured == {
        "public_id": "res-290",
        "actor": "dashboard",
        "note": None,
        "expected_revision": 4,
    }

    def conflict(*args, **kwargs):
        raise api.ali_reservation_workflow.AliReservationError(
            "stale_revision",
            status_code=409,
        )

    monkeypatch.setattr(api.ali_reservation_workflow, "confirm_reservation", conflict)
    failed = client.post(
        "/dashboard/api/ali-reservations/res-290/confirm",
        headers=_auth(),
        json={"expectedRevision": 4},
    )

    assert failed.status_code == 409
    assert failed.json()["detail"] == (
        "Reservation state changed or this action is not allowed"
    )
    assert "stale_revision" not in failed.text


def test_document_review_and_replacement_require_a_reason(client, monkeypatch):
    reviews = []
    replacements = []
    monkeypatch.setattr(api.ali_reservation_v2, "enabled", lambda: True)
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "review_document",
        lambda *args, **kwargs: reviews.append((args, kwargs)) or {"status": "rejected"},
    )
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "request_document_replacement",
        lambda *args, **kwargs: replacements.append((args, kwargs)) or {
            "mode": "direct_whatsapp",
            "links": [],
            "replacementSlot": "license_front",
        },
    )
    monkeypatch.setattr(
        api.ali_quote_delivery,
        "send_customer_requirement_link",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "get_customer_file",
        lambda public_id: {"public_id": public_id},
    )

    missing = client.post(
        "/dashboard/api/ali-reservations/res-290/documents/doc-1/request-replacement",
        headers=_auth(),
        json={"expectedRevision": 7},
    )
    reviewed = client.post(
        "/dashboard/api/ali-reservations/res-290/documents/doc-1/review",
        headers=_auth(),
        json={
            "expectedRevision": 7,
            "decision": "rejected",
            "reason": "Image is unreadable",
        },
    )
    replaced = client.post(
        "/dashboard/api/ali-reservations/res-290/documents/doc-1/request-replacement",
        headers=_auth(),
        json={
            "expectedRevision": 7,
            "reason": "Please resend in daylight",
        },
    )

    assert missing.status_code == 422
    assert reviewed.status_code == 200
    assert reviews[0][1]["reason"] == "Image is unreadable"
    assert replaced.status_code == 200
    assert replacements[0][1]["reason"] == "Please resend in daylight"


def test_reclassify_route_forwards_only_the_allowlisted_slot(client, monkeypatch):
    captured = {}

    def reclassify(public_id, document_id, slot, actor, **kwargs):
        captured.update({
            "public_id": public_id,
            "document_id": document_id,
            "slot": slot,
            "actor": actor,
            **kwargs,
        })
        return {"status": "received", "slot": slot}

    monkeypatch.setattr(
        api.ali_customer_dossier,
        "reclassify_whatsapp_document",
        reclassify,
    )
    response = client.post(
        "/dashboard/api/ali-reservations/res-290/documents/doc-1/reclassify",
        headers=_auth(),
        json={"expectedRevision": 8, "slot": "passport"},
    )
    invalid = client.post(
        "/dashboard/api/ali-reservations/res-290/documents/doc-1/reclassify",
        headers=_auth(),
        json={"expectedRevision": 8, "slot": "credit_card"},
    )

    assert response.status_code == 200
    assert captured == {
        "public_id": "res-290",
        "document_id": "doc-1",
        "slot": "passport",
        "actor": "dashboard",
        "expected_revision": 8,
    }
    assert invalid.status_code == 422


def test_v2_schedule_settings_are_tenant_authenticated_and_no_store(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        api.ali_reservation_v2,
        "tenant_settings",
        lambda: {
            "holdActiveClientHours": 24,
            "reminderActiveClientHours": [3, 12, 21],
            "quietHoursStart": "20:30",
            "quietHoursEnd": "08:30",
            "defaultTimezone": "America/Curacao",
            "reminderSendEnabled": False,
        },
    )

    def save(**kwargs):
        captured.update(kwargs)
        return {"holdActiveClientHours": kwargs["hold_active_client_hours"]}

    monkeypatch.setattr(api.ali_reservation_v2, "save_tenant_settings", save)
    loaded = client.get(
        "/dashboard/api/ali-reservation-v2/settings",
        headers=_auth(),
    )
    saved = client.put(
        "/dashboard/api/ali-reservation-v2/settings",
        headers=_auth(),
        json={
            "holdActiveClientHours": 24,
            "reminderActiveClientHours": [3, 12, 21],
            "quietHoursStart": "20:30",
            "quietHoursEnd": "08:30",
            "defaultTimezone": "America/Curacao",
        },
    )

    assert loaded.status_code == saved.status_code == 200
    assert "no-store" in loaded.headers["cache-control"]
    assert captured == {
        "hold_active_client_hours": 24.0,
        "reminder_active_client_hours": [3.0, 12.0, 21.0],
        "quiet_hours_start": "20:30",
        "quiet_hours_end": "08:30",
        "default_timezone": "America/Curacao",
        "actor": "dashboard",
    }
