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
                "seats": 4,
                "transmission": "automatic",
                "features": ["1 large suitcase", "1 small suitcase", "Air conditioning"],
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
    assert context["categories"] == [{
        "name": "Economy",
        "description": "Small automatic category",
        "daily_usd": "35.00",
    }]
    assert context["vehicles"] == [
        {
            "name": "Kia Picanto 2024 or similar",
            "category": "Economy",
            "daily_usd": "35.00",
            "seats": 4,
            "transmission": "automatic",
            "features": [
                "1 large suitcase",
                "1 small suitcase",
                "Air conditioning",
            ],
        },
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


def test_ali_prompt_answers_known_prices_immediately_and_continues_intake(monkeypatch):
    monkeypatch.setattr(marina_agent.config_loader, "get_raw", lambda: raw_config())
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda: catalog())

    prompt = marina_agent._build_ali_quote_block()
    normalized = " ".join(prompt.split())

    assert "answer that question immediately" in normalized
    assert "Do not make them finish the intake" in normalized
    assert "state the exact rate as USD {daily_usd} per day" in normalized
    assert "has exactly one unambiguous match" in normalized
    assert "ask one concise clarifying question instead of guessing" in normalized
    assert "continue the one-question-at-a-time intake normally" in normalized
    assert "Do not repeat a known question or detail" in normalized
    assert "Do not calculate rental totals" in normalized
    assert "discounts, duration rates, dynamic" in normalized
    assert "Always spell the currency as USD" in normalized
    assert "never use a $ symbol or `/day` shorthand" in normalized


def test_ali_prompt_sets_official_quote_expectation_in_all_supported_languages(monkeypatch):
    monkeypatch.setattr(marina_agent.config_loader, "get_raw", lambda: raw_config())
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda: catalog())

    prompt = marina_agent._build_ali_quote_block()

    expected = (
        "Your final price will be shown in the official quote I'll prepare and send here in a few minutes.",
        "Je definitieve prijs staat in de officiële offerte die ik klaarmaak en hier over een paar minuten stuur.",
        "Bo preis final lo ta den e oferta ofisial ku mi ta prepara i manda aki den un par di minüt.",
        "Der endgültige Preis steht im offiziellen Angebot, das ich vorbereite und Ihnen hier in wenigen Minuten sende.",
    )
    for wording in expected:
        assert wording in prompt


def test_ali_prompt_discovers_vehicle_needs_before_personal_details(monkeypatch):
    monkeypatch.setattr(marina_agent.config_loader, "get_raw", lambda: raw_config())
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda: catalog())

    prompt = marina_agent._build_ali_quote_block()
    normalized = " ".join(prompt.split())

    assert "DISCOVERY BEFORE PERSONAL DETAILS is mandatory" in normalized
    assert "Hi, I’m Carlos from Ali Car Rental." in normalized
    assert "ask what they prefer" in normalized
    assert "If they explicitly say they are undecided" in normalized
    assert "never combine vehicle preference with passenger count" in normalized
    assert "ask only passenger_count next" in normalized
    assert "ask only about luggage when it is useful" in normalized
    assert "never ask the vehicle question again" in normalized
    assert "Collect rental_start and rental_end during discovery" in normalized
    assert "Only after a vehicle direction or recommendation is established" in normalized
    assert "may you request customer_name" in normalized
    assert "Do not ask for name, age, email, identity documents" in normalized
    assert "Never ask the customer to type" in normalized
    assert "Email is optional" in normalized
    assert "never ask for any of those facts again" in normalized
    assert "Never join two requested facts" in normalized
    assert "never ask a conditional second question" in normalized


def test_ali_prompt_keeps_recommendations_catalog_grounded_and_request_only(monkeypatch):
    monkeypatch.setattr(marina_agent.config_loader, "get_raw", lambda: raw_config())
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda: catalog())

    prompt = marina_agent._build_ali_quote_block()
    normalized = " ".join(prompt.split())

    assert '"seats": 4' in prompt
    assert '"transmission": "automatic"' in prompt
    assert '"features": ["1 large suitcase", "1 small suitcase", "Air conditioning"]' in prompt
    assert "recommend only suitable current catalog options" in normalized
    assert 'Say "this looks suitable" or "I can prepare a quote for this option"' in normalized
    assert "never say or imply that a vehicle is available" in normalized
    assert 'word "available" and its translations are forbidden' in normalized
    for language in ("English", "Dutch", "Papiamentu", "German"):
        assert language in normalized


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
    assert "WhatsApp: +351000000000" in reply
    assert "wa.me" not in reply
    assert "@" not in reply
    assert fields["vehicle_class_id"] == CLASS_ID
    assert flags["awaiting_quote_confirmation"] is True


def test_confirmation_reply_stays_immediate_while_quote_worker_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow.state_registry, "DB_PATH", str(tmp_path / "tenant.db"))
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
    decision_events = []

    monkeypatch.setattr(
        workflow.bm_logger,
        "log",
        lambda event, **fields: decision_events.append({"event": event, **fields}),
    )

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
        "yes, it does look right", fields, flags, from_name="Synthetic Calvin",
        raw_config=raw_config(), processor=lambda _public_id: None,
    )

    assert reply == workflow.PREPARING["en"]
    assert flags["awaiting_quote_confirmation"] is False
    assert len(started) == 1
    assert started[0]["daemon"] is True

    replay = workflow.handle_ali_quote_turn(
        "synthetic-8003", "synthetic-account", "+351000000000",
        "yes it does", fields, flags, from_name="Synthetic Calvin",
        raw_config=raw_config(), processor=lambda _public_id: None,
    )

    assert replay == workflow.PREPARING["en"]
    assert flags["awaiting_quote_confirmation"] is False
    assert len(started) == 1
    assert [event["reason_code"] for event in decision_events] == [
        "affirmative_allowlist",
        "already_confirmed",
    ]
    assert all(event["event"] == "ali_quote_confirmation_decision" for event in decision_events)
    assert all(set(event) == {
        "event", "tenant_slug", "outcome", "reason_code",
        "summary_version", "summary_hash_prefix",
    } for event in decision_events)
    serialized_events = json.dumps(decision_events).lower()
    assert "yes" not in serialized_events
    assert "synthetic calvin" not in serialized_events
    assert "+351" not in serialized_events
    assert "2026-09" not in serialized_events
    assert "curaçao" not in serialized_events


def test_correction_replaces_summary_without_starting_quote(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow.state_registry, "DB_PATH", str(tmp_path / "tenant.db"))
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

    workflow.handle_ali_quote_turn(
        "synthetic-correction", "synthetic-account", "+351000000000",
        "These are my details.", fields, flags, from_name="Synthetic Calvin",
        raw_config=raw_config(),
    )
    previous_hash = flags["ali_summary_hash"]
    fields["return_location"] = "Synthetic hotel return"

    corrected = workflow.handle_ali_quote_turn(
        "synthetic-correction", "synthetic-account", "+351000000000",
        "Yes, but return it to my hotel.", fields, flags,
        from_name="Synthetic Calvin", raw_config=raw_config(),
        processor=lambda public_id: started.append(public_id),
    )

    assert corrected.startswith("Just checking I’ve got everything right:")
    assert "Return: Synthetic hotel return" in corrected
    assert flags["ali_summary_hash"] != previous_hash
    assert flags["awaiting_quote_confirmation"] is True
    assert started == []
