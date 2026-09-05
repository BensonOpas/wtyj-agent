"""Dashboard contract for Mermaid's durable crew-assistance attention queue."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agents.social import mermaid_crew_assistance as assistance
from dashboard import api
from shared import config_loader, mermaid_customers, state_registry


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(state_registry, "_alert_dispatcher", None)
    monkeypatch.setattr(api, "_current_tenant_slug", lambda: "mermaid")
    monkeypatch.setattr(config_loader, "get_raw", lambda: {
        "slug": "mermaid",
        "features": {
            "mermaid_dashboard_projection": True,
            "mermaid_customer_accounts": True,
        },
    })
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def auth():
    return {"Authorization": f"Bearer {api._SESSION_TOKEN}"}


def reservation_record(public_id="mer_demo_1"):
    return {
        "public_id": public_id,
        "conversation_id": "conversation-a",
        "customer_name": "Test Guest",
        "language": "en",
        "intake": {
            "trip_date": "2026-09-06",
            "adults": 2,
            "children": 0,
            "infants": 0,
            "pickup_preference": "pier",
        },
        "catalog_version": "mermaid-demo-v1",
        "monetary_snapshot": {"currency": "USD", "total": 150, "items": []},
        "state": "quote_ready",
        "availability_source": "demo_assumed",
        "booking_code": "MER-DEMO-ABC12345",
        "quote_public_id": "quote_1",
        "payment_reference": None,
        "receipt_public_id": None,
        "human_takeover": False,
        "revision": 1,
        "created_at": "2026-09-04T12:00:00+00:00",
        "updated_at": "2026-09-04T12:00:00+00:00",
    }


def create_attention(**updates):
    values = {
        "conversation_id": "conversation-a",
        "note": "A guest in this party uses a wheelchair.",
        "relationship": "husband",
        "trip_date": "2026-09-06",
        "customer_name": "Test Guest",
        "source_message_id": "message-1",
    }
    values.update(updates)
    return assistance.record_wheelchair_note(**values)[0]


def test_queue_is_private_filtered_and_no_store(client, monkeypatch):
    item = create_attention()
    assert client.get("/dashboard/api/mermaid-crew-assistance").status_code == 401

    response = client.get("/dashboard/api/mermaid-crew-assistance", headers=auth())
    assert response.status_code == 200
    assert response.headers["cache-control"].startswith("no-store")
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-unboks-tenant"] == "mermaid"
    assert response.json() == {"items": [item]}
    assert "sourceMessageId" not in response.text
    assert "materialHash" not in response.text

    acknowledged = assistance.acknowledge(
        item["id"], expected_revision=1, acknowledged_by="Calvin"
    )
    assert client.get(
        "/dashboard/api/mermaid-crew-assistance", headers=auth()
    ).json() == {"items": []}
    assert client.get(
        "/dashboard/api/mermaid-crew-assistance?status=acknowledged", headers=auth()
    ).json() == {"items": [acknowledged]}
    assert len(client.get(
        "/dashboard/api/mermaid-crew-assistance?status=all", headers=auth()
    ).json()["items"]) == 1
    assert client.get(
        "/dashboard/api/mermaid-crew-assistance?status=invalid", headers=auth()
    ).status_code == 422

    monkeypatch.setattr(api, "_current_tenant_slug", lambda: "ali-car-rental")
    assert client.get(
        "/dashboard/api/mermaid-crew-assistance", headers=auth()
    ).status_code == 404


def test_acknowledge_is_idempotent_and_rejects_stale_revision(client):
    item = create_attention()
    path = f"/dashboard/api/mermaid-crew-assistance/{item['id']}/acknowledge"
    first = client.post(path, headers=auth(), json={
        "expectedRevision": 1,
        "acknowledgedBy": "Calvin",
    })
    assert first.status_code == 200
    assert first.headers["cache-control"].startswith("no-store")
    acknowledged = first.json()["item"]
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["acknowledgedBy"] == "Calvin"
    assert acknowledged["acknowledgedAt"]

    repeated = client.post(path, headers=auth(), json={
        "expectedRevision": 1,
        "acknowledgedBy": "Another operator",
    })
    assert repeated.status_code == 200
    assert repeated.json()["item"] == acknowledged

    corrected = create_attention(
        note="A guest uses a wheelchair and asked for general crew assistance.",
        source_message_id="message-2",
    )
    assert corrected["revision"] == 2
    assert corrected["status"] == "unacknowledged"
    assert client.post(path, headers=auth(), json={
        "expectedRevision": 1,
        "acknowledgedBy": "Calvin",
    }).status_code == 409
    current = client.post(path, headers=auth(), json={
        "expectedRevision": 2,
        "acknowledgedBy": "Calvin",
    })
    assert current.status_code == 200
    assert current.json()["item"]["status"] == "acknowledged"

    assert client.post(
        "/dashboard/api/mermaid-crew-assistance/999/acknowledge",
        headers=auth(),
        json={"expectedRevision": 1, "acknowledgedBy": "Calvin"},
    ).status_code == 404
    assert client.post(path, headers=auth(), json={
        "expectedRevision": 2,
        "acknowledgedBy": "   ",
    }).status_code == 422
    assert client.post(path, headers=auth(), json={
        "expectedRevision": 2,
        "acknowledgedBy": "Calvin",
        "unexpected": True,
    }).status_code == 422
    assert client.post(path, headers=auth(), json={
        "expectedRevision": True,
        "acknowledgedBy": "Calvin",
    }).status_code == 422


def test_marker_is_embedded_in_conversation_customer_and_reservation_views(
    client, monkeypatch
):
    attention = create_attention()
    assistance.link_current(
        "conversation-a", "mer_demo_1", idempotency_key="reservation-link-1"
    )
    attention = assistance.for_conversation("conversation-a")

    monkeypatch.setattr(api.state_registry, "wa_list_conversations", lambda: [{
        "phone": "conversation-a",
        "customer_name": "Test Guest",
        "last_message_at": "2026-09-04T12:00:00+00:00",
    }])
    monkeypatch.setattr(api.state_registry, "wa_list_archived_conversations", lambda: [{
        "phone": "conversation-a",
        "customer_name": "Test Guest",
        "last_message_at": "2026-09-04T12:00:00+00:00",
    }])
    monkeypatch.setattr(api.state_registry, "email_list_conversations", lambda: [])
    monkeypatch.setattr(api.state_registry, "email_list_archived_conversations", lambda: [])
    monkeypatch.setattr(api.state_registry, "wa_get_full_history", lambda phone, limit: [])
    monkeypatch.setattr(api.state_registry, "wa_get_booking_state", lambda phone: {})
    monkeypatch.setattr(api.state_registry, "get_order_state_for_conversation", lambda phone: None)

    conversations_response = client.get(
        "/dashboard/api/messages/conversations", headers=auth()
    )
    assert conversations_response.headers["cache-control"].startswith("no-store")
    assert conversations_response.headers["pragma"] == "no-cache"
    conversations = conversations_response.json()
    assert conversations[0]["crewAssistance"] == attention
    archived_response = client.get(
        "/dashboard/api/messages/conversations/archived", headers=auth()
    )
    assert archived_response.headers["cache-control"].startswith("no-store")
    assert archived_response.headers["pragma"] == "no-cache"
    assert archived_response.json()[0]["crewAssistance"] == attention
    conversation_response = client.get(
        "/dashboard/api/messages/conversations/conversation-a", headers=auth()
    )
    assert conversation_response.headers["cache-control"].startswith("no-store")
    assert conversation_response.headers["pragma"] == "no-cache"
    conversation = conversation_response.json()
    assert conversation["crewAssistance"] == attention

    account = {
        "id": 7,
        "customerName": "Test Guest",
        "conversationId": "conversation-a",
        "details": {},
        "reservationCount": 1,
        "messageCount": 1,
    }
    monkeypatch.setattr(mermaid_customers, "list_accounts", lambda *args: {
        "items": [dict(account)], "nextOffset": None,
    })
    monkeypatch.setattr(mermaid_customers, "get_account", lambda customer_id: dict(account))
    monkeypatch.setattr(
        mermaid_customers,
        "reservations_for_account",
        lambda customer_id: [reservation_record()],
    )
    monkeypatch.setattr(api.mermaid_documents, "documents_for_reservation", lambda public_id: [])

    customers = client.get("/dashboard/api/mermaid-customers", headers=auth()).json()
    assert customers["items"][0]["crewAssistance"] == attention
    customer = client.get("/dashboard/api/mermaid-customers/7", headers=auth()).json()
    assert customer["crewAssistance"] == attention
    assert customer["reservations"][0]["crewAssistance"] == attention
    assert customer["reservations"][0]["accessibilityNotes"] == attention["note"]

    monkeypatch.setattr(
        api.mermaid_reservation_store,
        "list_reservations",
        lambda limit: [reservation_record()],
    )
    monkeypatch.setattr(
        api.mermaid_reservation_store,
        "get_reservation",
        lambda public_id: reservation_record(public_id),
    )
    monkeypatch.setattr(api.mermaid_reservation_store, "events", lambda public_id: [])
    monkeypatch.setattr(mermaid_customers, "account_id", lambda conversation_id: 7)
    reservations = client.get(
        "/dashboard/api/mermaid-reservations", headers=auth()
    ).json()
    assert reservations["items"][0]["crewAssistance"] == attention
    assert reservations["items"][0]["accessibilityNotes"] == attention["note"]
    reservation = client.get(
        "/dashboard/api/mermaid-reservations/mer_demo_1", headers=auth()
    ).json()
    assert reservation["crewAssistance"] == attention
    assert reservation["accessibilityNotes"] == attention["note"]


def test_withdrawn_wheelchair_does_not_hide_unread_boarding_marker(client):
    boarding = assistance.record_boarding_assistance_note(
        "conversation-a",
        note="A guest requested general crew help while boarding.",
        trip_date="2026-09-06",
        source_message_id="boarding-before-wheelchair",
    )[0]
    wheelchair = create_attention(source_message_id="wheelchair-after-boarding")
    assistance.link_current(
        "conversation-a", "mer_demo_1", idempotency_key="link-both-kinds"
    )
    boarding = assistance.for_conversation(
        "conversation-a", kind=assistance.KIND_BOARDING_ASSISTANCE
    )

    withdrawn = assistance.withdraw(
        "conversation-a", source_message_id="withdraw-wheelchair-only"
    )

    assert withdrawn["id"] == wheelchair["id"]
    assert withdrawn["status"] == "withdrawn"
    rows = [{"phone": "conversation-a"}]
    api._attach_mermaid_crew_assistance_by_conversation(rows)
    assert rows[0]["crewAssistance"] == boarding
    assert assistance.for_reservation("mer_demo_1") == boarding
    response = client.get("/dashboard/api/mermaid-crew-assistance", headers=auth())
    assert response.status_code == 200
    assert response.json() == {"items": [boarding]}


def test_customer_intake_keeps_wheelchair_relationship(client):
    details = {
        "customer_name": "Test Guest",
        "trip_date": "2026-09-06",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "pickup_preference": "pier",
        "accessibility_notes": "A guest uses a wheelchair.",
        "wheelchair_relationship": "husband",
    }
    state_registry.wa_save_booking_state(
        "conversation-a", {"mermaid_intake": details}, {}
    )
    customer_id = mermaid_customers.account_id("conversation-a")
    assert mermaid_customers.get_account(customer_id)["details"][
        "wheelchair_relationship"
    ] == "husband"
