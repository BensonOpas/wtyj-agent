"""Issue 152: Mermaid-only reservation dashboard projection."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from dashboard import api


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "_current_tenant_slug", lambda: "mermaid")
    monkeypatch.setattr(api.config_loader, "get_raw", lambda: {
        "features": {"mermaid_dashboard_projection": True}
    })
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def auth():
    return {"Authorization": f"Bearer {api._SESSION_TOKEN}"}


def record(state="demo_payment_pending"):
    return {
        "public_id": "mer_demo_1", "conversation_id": "+5999000000",
        "customer_name": "Ana Silva", "language": "es",
        "intake": {"trip_date": "2026-09-05", "adults": 2, "children": 1,
                   "infants": 0, "pickup_preference": "pier"},
        "catalog_version": "mermaid-demo-v1", "monetary_snapshot": {
            "currency": "USD", "total": 375, "items": []
        },
        "state": state, "availability_source": "demo_assumed",
        "booking_code": "MER-DEMO-ABC12345", "quote_public_id": "quote_1",
        "payment_reference": None, "receipt_public_id": None,
        "human_takeover": False, "revision": 4,
        "created_at": "2026-09-03T12:00:00+00:00",
        "updated_at": "2026-09-03T12:10:00+00:00",
    }


def test_routes_require_auth_and_mermaid_flag(client, monkeypatch):
    assert client.get("/dashboard/api/mermaid-reservations").status_code == 401
    monkeypatch.setattr(api, "_current_tenant_slug", lambda: "ali-car-rental")
    assert client.get("/dashboard/api/mermaid-reservations", headers=auth()).status_code == 404


def test_contact_number_is_available_and_searchable_for_the_team(client, monkeypatch):
    item=record();item['intake']['contact_phone']='+12025550123'
    monkeypatch.setattr(api.mermaid_reservation_store,'list_reservations',lambda limit:[item])
    response=client.get('/dashboard/api/mermaid-reservations',params={'query':'2025550123'},headers=auth())
    assert response.status_code==200
    assert response.json()['items'][0]['contactPhone']=='+12025550123'
    assert api._mermaid_projection(record())['contactPhone'] is None


def test_list_is_no_store_searchable_and_never_exposes_prepaid_booking_code(client, monkeypatch):
    monkeypatch.setattr(api.mermaid_reservation_store, "list_reservations", lambda limit: [record()])
    response = client.get("/dashboard/api/mermaid-reservations?query=ana", headers=auth())
    payload = response.json()
    assert response.status_code == 200
    assert response.headers["x-unboks-tenant"] == "mermaid"
    assert response.headers["cache-control"].startswith("no-store")
    assert payload["demo"] is True and payload["remindersEnabled"] is False
    assert payload["items"][0]["stage"] == "payment"
    assert payload["items"][0]["bookingCode"] is None
    assert payload["items"][0]["primaryAction"] == {
        "id": "open_conversation", "label": "Open conversation", "href": "/conversations"
    }


def test_detail_includes_server_stage_documents_events_and_chronological_chat(client, monkeypatch):
    monkeypatch.setattr(api.mermaid_reservation_store, "get_reservation", lambda public_id: record("booked"))
    monkeypatch.setattr(api.mermaid_reservation_store, "events", lambda public_id: [{
        "id": 1, "event_type": "state_transition", "from_state": "demo_paid",
        "to_state": "booked", "actor": "demo_checkout", "reason": "Demo booking completed",
        "revision": 5, "created_at": "2026-09-03T12:11:00+00:00",
    }])
    monkeypatch.setattr(api.mermaid_documents, "documents_for_reservation", lambda public_id: [{
        "public_id": "receipt_1", "kind": "receipt", "delivery_status": "delivered"
    }])
    monkeypatch.setattr(api.state_registry, "wa_get_full_history", lambda conversation_id, limit: [
        {"role": "user", "text": "Hola", "created_at": "2026-09-03T12:00:00+00:00"},
        {"role": "assistant", "text": "Hola Ana", "created_at": "2026-09-03T12:00:01+00:00"},
    ])
    response = client.get("/dashboard/api/mermaid-reservations/mer_demo_1", headers=auth())
    payload = response.json()
    assert payload["stage"] == "booked"
    assert payload["bookingCode"] == "MER-DEMO-ABC12345"
    assert payload["documents"][0]["kind"] == "receipt"
    assert payload["events"][0]["toState"] == "booked"
    assert [message["role"] for message in payload["conversation"]] == ["user", "assistant"]
    assert payload["primaryAction"]["id"] == "view_receipt"


def test_conversation_detail_exposes_non_actionable_loop_stop(monkeypatch):
    monkeypatch.setattr(api.state_registry, "get_conversation_status", lambda _cid: None)
    monkeypatch.setattr(api.state_registry, "get_active_escalation_summary_for", lambda _cid: None)
    monkeypatch.setattr(api.state_registry, "get_active_escalation_mode", lambda _cid: None)
    monkeypatch.setattr(api.state_registry, "get_ai_muted", lambda _cid: False)
    monkeypatch.setattr(api.state_registry, "get_human_takeover_at", lambda _cid: None)
    monkeypatch.setattr(api.state_registry, "get_learning_status_for_conversation", lambda _cid: "none")
    monkeypatch.setattr(api.state_registry, "wa_get_booking_state", lambda _cid: {
        "fields": {},
        "flags": {
            api.state_registry.MERMAID_LOOP_STOPPED_FLAG: True,
            "mermaid_loop_stopped_at": "2026-09-04T01:14:20+00:00",
        },
    })

    result = api._conversation_status_fields("loop-guest")
    assert result["loopStopped"] is True
    assert result["loopStatus"] == "Loop detected and stopped"
    assert result["loopStoppedAt"] == "2026-09-04T01:14:20+00:00"
    assert result["escalated"] is False
    assert result["escalationMode"] is None
