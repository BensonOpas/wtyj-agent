"""Issue #191: Ali Quote Leads read model and authenticated API."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.social import ali_quote_workflow as workflow
from dashboard import api
from shared import state_registry


ALI_CONFIG = {
    "slug": "ali-car-rental",
    "workflow": {"type": "ali_quote"},
}
REQUIRED = {
    "customer_name": "Synthetic Customer",
    "rental_start": "2026-09-01",
    "rental_end": "2026-09-04",
    "pickup_location": "Airport",
    "return_location": "Airport",
    "driver_age": 30,
    "conversation_language": "en",
    "vehicle_class_id": "00000000-0000-4000-8000-000000000001",
    "vehicle_class_name": "Economy",
}


@pytest.fixture
def quote_leads(monkeypatch, tmp_path):
    database = tmp_path / "state.db"
    monkeypatch.setattr(state_registry, "DB_PATH", str(database))
    monkeypatch.setattr(workflow.config_loader, "get_raw", lambda: ALI_CONFIG)
    return database


def _message(conversation_id: str, role: str, stamp: str, sender_name: str = ""):
    conn = state_registry._get_conn()
    conn.execute(
        "INSERT INTO whatsapp_threads "
        "(phone, role, text, created_at, channel, sender_name) "
        "VALUES (?, ?, ?, ?, 'whatsapp', ?)",
        (conversation_id, role, "synthetic", stamp, sender_name),
    )
    conn.commit()
    conn.close()


def _state(conversation_id: str, fields: dict, flags: dict | None = None):
    state_registry.wa_save_booking_state(conversation_id, fields, flags or {})


def _quote(
    conversation_id: str,
    public_id: str,
    *,
    status: str,
    whatsapp_status: str = "pending",
):
    workflow.ensure_schema()
    now = datetime.now(timezone.utc)
    conn = workflow._connection()
    conn.execute(
        "INSERT INTO ali_quotes ("
        "public_id, conversation_id, zernio_account_id, summary_hash, "
        "summary_version, locale, customer_json, rental_json, "
        "ali_request_json, idempotency_key, status, confirmed_at, sla_due_at, "
        "quote_reference, whatsapp_status, staff_email_status, created_at, updated_at"
        ") VALUES (?, ?, 'account', ?, 1, 'en', '{}', '{}', '{}', ?, ?, ?, ?, ?, ?, "
        "'pending', ?, ?)",
        (
            public_id,
            conversation_id,
            f"hash-{public_id}",
            f"key-{public_id}",
            status,
            workflow._iso(now),
            workflow._iso(now + timedelta(minutes=30)),
            f"ALI-{public_id.upper()}-QUOTE",
            whatsapp_status,
            workflow._iso(now),
            workflow._iso(now),
        ),
    )
    conn.commit()
    conn.close()


def _escalate(conversation_id: str):
    conn = state_registry._get_conn()
    conn.execute(
        "INSERT INTO pending_notifications "
        "(notification_type, channel, customer_id, customer_name, subject, body, status, created_at) "
        "VALUES ('escalation', 'whatsapp', ?, 'Synthetic Customer', 'Synthetic', "
        "'Synthetic', 'pending', ?)",
        (conversation_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {api._SESSION_TOKEN}"}


def test_incomplete_conversation_appears_once_with_aggregated_unread(quote_leads):
    conversation_id = "191000000000000000000001"
    _state(conversation_id, {"customer_name": "Synthetic Customer"})
    _message(conversation_id, "assistant", "2026-08-26T01:00:00+00:00")
    for minute in range(1, 4):
        _message(
            conversation_id,
            "user",
            f"2026-08-26T01:0{minute}:00+00:00",
            "Synthetic Customer",
        )

    rows = workflow.list_quote_leads()

    assert len(rows) == 1
    assert rows[0]["id"] == conversation_id
    assert rows[0]["status"] == "missing_information"
    assert rows[0]["unread_count"] == 3
    assert "customer_name" not in rows[0]["missing_fields"]
    assert "vehicle_preference" in rows[0]["missing_fields"]
    assert rows[0]["phone_raw"] == "WhatsApp conversation"


def test_internal_zernio_id_is_never_masked_as_customer_phone(quote_leads):
    conversation_id = "a1b2c3d4e5f6a7b8c9d0e1f2"
    assert 9 <= len("".join(filter(str.isdigit, conversation_id))) <= 15
    _state(conversation_id, {"customer_name": "Synthetic Customer"})
    _message(
        conversation_id,
        "user",
        "2026-08-26T01:10:00+00:00",
        "Synthetic Customer",
    )

    row = workflow.list_quote_leads()[0]

    assert row["conversation_id"] == conversation_id
    assert row["phone_raw"] == "WhatsApp conversation"
    assert row["phone_normalized"] == ""


def test_provider_confirmed_phone_hydrates_masked_quote_lead():
    conversation_id = "a1b2c3d4e5f6a7b8c9d0e1f2"
    rows = [{
        "conversation_id": conversation_id,
        "phone_raw": "WhatsApp conversation",
        "phone_normalized": "",
    }]

    result = workflow.hydrate_quote_lead_contact_identities(rows, {
        conversation_id: {
            "phone": "whatsapp:+351963618003",
            "name": "Synthetic Customer",
        },
    })

    assert result[0]["phone_raw"] == "WhatsApp ••••8003"
    assert result[0]["phone_normalized"] == ""


@pytest.mark.parametrize("provider_phone", ["", "unknown", "+123"])
def test_missing_or_invalid_provider_phone_fails_closed(provider_phone):
    conversation_id = "a1b2c3d4e5f6a7b8c9d0e1f2"
    rows = [{
        "conversation_id": conversation_id,
        "phone_raw": "WhatsApp conversation",
        "phone_normalized": "",
    }]

    result = workflow.hydrate_quote_lead_contact_identities(rows, {
        conversation_id: {"phone": provider_phone},
    })

    assert result[0]["phone_raw"] == "WhatsApp conversation"
    assert result[0]["phone_normalized"] == ""


def test_three_distinct_conversations_produce_three_active_rows(quote_leads):
    for suffix in range(3):
        conversation_id = f"19100000000000000000001{suffix}"
        _state(conversation_id, {"customer_name": f"Synthetic {suffix}"})
        _message(conversation_id, "user", f"2026-08-26T02:0{suffix}:00+00:00")

    assert len(workflow.list_quote_leads(status="active")) == 3


def test_confirmed_undelivered_quote_is_ready_to_quote(quote_leads):
    conversation_id = "191000000000000000000020"
    public_id = "ready191"
    _state(conversation_id, REQUIRED, {"ali_quote_public_id": public_id})
    _quote(
        conversation_id,
        public_id,
        status="attention_required",
        whatsapp_status="failed",
    )

    row = workflow.list_quote_leads()[0]

    assert row["status"] == "ready_to_quote"
    assert row["complete"] is True
    assert row["quote_delivery_state"] == "failed"
    assert row["quote_reference"] == "ALI-READY191-QUOTE"


def test_escalation_and_processing_use_canonical_status_precedence(quote_leads):
    escalated = "191000000000000000000030"
    processing = "191000000000000000000031"
    _state(escalated, REQUIRED)
    _escalate(escalated)
    _state(processing, REQUIRED, {"ali_quote_public_id": "process191"})
    _quote(processing, "process191", status="pricing")

    rows = {item["conversation_id"]: item for item in workflow.list_quote_leads()}

    assert rows[escalated]["status"] == "needs_an_answer"
    assert rows[processing]["status"] == "in_progress"


def test_archived_blocked_and_resolved_conversations_are_excluded(quote_leads):
    for suffix, status, deleted, blocked in (
        ("1", "pending", 1, 0),
        ("2", "pending", 0, 1),
        ("3", "resolved", 0, 0),
    ):
        conversation_id = f"19100000000000000000004{suffix}"
        _state(conversation_id, REQUIRED)
        conn = state_registry._get_conn()
        conn.execute(
            "INSERT INTO conversation_status "
            "(conversation_id, channel, status, updated_at, deleted, blocked) "
            "VALUES (?, 'whatsapp', ?, ?, ?, ?)",
            (
                conversation_id,
                status,
                datetime.now(timezone.utc).isoformat(),
                deleted,
                blocked,
            ),
        )
        conn.commit()
        conn.close()

    assert workflow.list_quote_leads() == []


def test_authenticated_api_filters_counts_and_provider_identity(
    quote_leads, monkeypatch,
):
    incomplete = "191000000000000000000050"
    processing = "191000000000000000000051"
    _state(incomplete, {})
    _state(processing, REQUIRED, {"ali_quote_public_id": "api191"})
    _quote(processing, "api191", status="pdf_ready")
    captured = []
    monkeypatch.setattr(
        api,
        "resolve_zernio_conversation_contacts",
        lambda conversation_ids: (
            captured.extend(conversation_ids)
            or {processing: {"phone": "+351963618003"}}
        ),
    )
    client = _client()

    unauthenticated = client.get("/dashboard/api/quote-leads")
    active = client.get(
        "/dashboard/api/quote-leads?status=active", headers=_auth(),
    )
    filtered = client.get(
        "/dashboard/api/quote-leads?status=in_progress", headers=_auth(),
    )

    assert unauthenticated.status_code == 401
    assert active.status_code == 200
    assert active.headers["cache-control"] == (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    assert len(active.json()["items"]) == active.json()["counts"]["active"] == 2
    assert active.json()["counts"]["missing_information"] == 1
    assert active.json()["counts"]["in_progress"] == 1
    assert len(filtered.json()["items"]) == 1
    assert filtered.json()["items"][0]["conversation_id"] == processing
    assert filtered.json()["items"][0]["phone_raw"] == "WhatsApp ••••8003"
    assert processing in captured


def test_tenant_database_isolation_and_callback_endpoint_regression(
    quote_leads, monkeypatch, tmp_path,
):
    _state("191000000000000000000060", {})
    assert len(workflow.list_quote_leads()) == 1

    other_database = tmp_path / "other-tenant.db"
    monkeypatch.setattr(state_registry, "DB_PATH", str(other_database))
    assert workflow.list_quote_leads() == []

    monkeypatch.setattr(
        api.config_loader,
        "get_raw",
        lambda: {"workflow": {"type": "callback_follow_up"}},
    )
    client = _client()
    assert client.get("/dashboard/api/quote-leads", headers=_auth()).status_code == 404
    callback = client.get("/dashboard/api/follow-ups", headers=_auth())
    assert callback.status_code == 200
    assert callback.json() == {"items": [], "followUps": []}
