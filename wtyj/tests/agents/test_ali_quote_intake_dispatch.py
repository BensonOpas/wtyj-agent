import json
import threading

import httpx

from agents.marina import marina_agent
from agents.social import ali_quote_workflow as workflow


CLASS_ID = "30000000-0000-4000-8000-000000000001"
ECONOMY_VEHICLE_ID = "40000000-0000-4000-8000-000000000001"


def raw_config(automation=True):
    return {
        "slug": "ali-car-rental",
        "workflow": {
            "type": "ali_quote",
            "required_deposit_charge_id": "90000000-0000-4000-8000-000000000001",
        },
        "features": {
            "booking_flow": False,
            "ali_quote_automation": automation,
            "ali_quote_customer_delivery": False,
            "ali_quote_staff_email": False,
            "ali_quote_operator_alerts": False,
        },
    }


def catalog():
    return {
        "catalogVersion": 11,
        "currency": "USD",
        "availabilityMode": "request_only",
        "vehicleClasses": [
            {"id": CLASS_ID, "name": "Economy", "description": "Small automatic category"},
        ],
        "vehicles": [
            {
                "id": ECONOMY_VEHICLE_ID,
                "classId": CLASS_ID,
                "name": "Kia Picanto 2024 or similar",
                "dailyRate": {"currency": "USD", "amount": "35.00"},
                "weeklyRate": {"currency": "USD", "amount": "245.00"},
            },
        ],
        "extras": [],
        "charges": [],
    }


def test_authenticated_catalog_read_is_validated():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=catalog())

    client = workflow.AliQuoteClient(
        "https://alicarrental.com",
        "synthetic-service-token",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = client.get_catalog()

    assert result["catalogVersion"] == 11
    assert len(requests) == 1
    assert requests[0].headers["authorization"] == "Bearer synthetic-service-token"


def test_prompt_context_contains_names_and_rates_but_no_server_ids():
    context = workflow.catalog_prompt_context(catalog())
    serialized = json.dumps(context)

    assert context["catalog_version"] == 11
    assert context["categories"] == [{"name": "Economy", "daily_usd": "35.00"}]
    assert context["vehicles"] == [
        {"name": "Kia Picanto 2024 or similar", "category": "Economy"},
    ]
    assert CLASS_ID not in serialized
    assert ECONOMY_VEHICLE_ID not in serialized


def test_selection_is_resolved_only_against_the_published_catalog():
    resolved = workflow.resolve_catalog_selection(
        {
            "vehicle_class_name": "Economy car",
            "vehicle_class_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
        },
        catalog(),
    )

    assert resolved["vehicle_class_id"] == CLASS_ID
    assert resolved["vehicle_class_name"] == "Economy"
    assert "vehicle_id" not in resolved

    rejected = workflow.resolve_catalog_selection(
        {"vehicle_id": "ffffffff-ffff-4fff-8fff-ffffffffffff"},
        catalog(),
    )
    assert "vehicle_id" not in rejected
    assert "vehicle_class_id" not in rejected


def test_ali_prompt_uses_live_catalog_and_forbids_contact_redirects(monkeypatch):
    monkeypatch.setattr(marina_agent.config_loader, "get_raw", lambda: raw_config())
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda: catalog())

    prompt = marina_agent._build_ali_quote_block()

    assert "ALI CAR RENTAL WHATSAPP QUOTE INTAKE" in prompt
    assert '"name": "Economy"' in prompt
    assert '"daily_usd": "35.00"' in prompt
    assert CLASS_ID not in prompt
    assert "Never tell them to contact or" in prompt
    assert "Never populate vehicle_id, vehicle_class_id, or extra_ids" in prompt


def test_paused_master_switch_does_not_fetch_catalog_or_collect_details(monkeypatch):
    monkeypatch.setattr(
        marina_agent.config_loader,
        "get_raw",
        lambda: raw_config(automation=False),
    )
    monkeypatch.setattr(
        workflow,
        "get_intake_catalog",
        lambda: (_ for _ in ()).throw(AssertionError("catalog must not be fetched")),
    )

    prompt = marina_agent._build_ali_quote_block()

    assert "QUOTE WORKFLOW IS PAUSED" in prompt
    assert "Do not collect or confirm rental details" in prompt
    assert "email, telephone, a website, or a form" in prompt


def test_bad_canary_contact_redirect_is_replaced_by_safe_same_chat_fallback():
    bad_reply = (
        "For bookings, message us on WhatsApp at wa.me/9677145 or email "
        "info@alicarrental.com."
    )

    reply = workflow.sanitize_intake_reply(bad_reply, "en")

    assert reply == "I couldn't complete that step safely. Please try again here in a moment."
    assert "wa.me" not in reply
    assert "@" not in reply



def test_complete_natural_intake_maps_category_and_returns_summary(monkeypatch):
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda: catalog())
    fields = {
        "customer_name": "Synthetic Calvin",
        "rental_start": "2026-09-01",
        "rental_end": "2026-09-04",
        "pickup_location": "Curaçao International Airport",
        "return_location": "Curaçao International Airport",
        "vehicle_class_name": "Economy car",
        "driver_age": 30,
        "conversation_language": "en",
    }
    flags = {}

    reply = workflow.handle_ali_quote_turn(
        conversation_id="synthetic-8003",
        zernio_account_id="synthetic-account",
        whatsapp_number="+351000000000",
        message_text="These are my complete rental details.",
        fields=fields,
        flags=flags,
        from_name="Synthetic Calvin",
        raw_config=raw_config(),
    )

    assert reply.startswith("Just checking I’ve got everything right:")
    assert reply.endswith("Does that all look right?")
    assert "Economy" in reply
    assert "wa.me" not in reply
    assert "@" not in reply
    assert fields["vehicle_class_id"] == CLASS_ID
    assert flags["awaiting_quote_confirmation"] is True


def test_confirmation_reply_stays_immediate_while_quote_worker_runs(monkeypatch):
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda: catalog())
    fields = {
        "customer_name": "Synthetic Calvin",
        "rental_start": "2026-09-01",
        "rental_end": "2026-09-04",
        "pickup_location": "Curaçao International Airport",
        "return_location": "Curaçao International Airport",
        "vehicle_class_name": "Economy car",
        "driver_age": 30,
        "conversation_language": "en",
    }
    flags = {}
    started = []

    class RecordingThread:
        def __init__(self, target, args, daemon):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            started.append({
                "target": self.target,
                "args": self.args,
                "daemon": self.daemon,
            })

    workflow.handle_ali_quote_turn(
        "synthetic-8003", "synthetic-account", "+351000000000",
        "These are my complete rental details.", fields, flags,
        from_name="Synthetic Calvin", raw_config=raw_config(),
    )
    monkeypatch.setattr(threading, "Thread", RecordingThread)

    reply = workflow.handle_ali_quote_turn(
        "synthetic-8003", "synthetic-account", "+351000000000",
        "yes", fields, flags, from_name="Synthetic Calvin",
        raw_config=raw_config(), processor=lambda _public_id: None,
    )

    assert reply == workflow.PREPARING["en"]
    assert flags["awaiting_quote_confirmation"] is False
    assert len(started) == 1
    assert started[0]["daemon"] is True
