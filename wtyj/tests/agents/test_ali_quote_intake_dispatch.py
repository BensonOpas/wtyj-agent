import json
import threading

import httpx

from agents.marina import marina_agent
from agents.social import ali_quote_workflow as workflow


CLASS_ID = "30000000-0000-4000-8000-000000000001"
ECONOMY_VEHICLE_ID = "40000000-0000-4000-8000-000000000001"
CHILD_SEAT_ID = "c5b7e180-5eaa-4f5d-8a41-180000000001"
VAN_CLASS_ID = "30000000-0000-4000-8000-000000000002"
SELTOS_VEHICLE_ID = "40000000-0000-4000-8000-000000000002"


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
        "extras": [{
            "id": CHILD_SEAT_ID,
            "name": "Child seat",
            "names": {
                "en": "Child seat", "nl": "Kinderzitje",
                "pap": "Stul pa mucha", "de": "Kindersitz",
            },
            "pricingUnit": "daily",
            "billingBasis": "per_day",
            "displayOrder": 10,
            "price": {"currency": "USD", "amount": "5.00"},
        }],
        "charges": [],
    }


def correction_catalog():
    current = json.loads(json.dumps(catalog()))
    current["vehicleClasses"].append({
        "id": VAN_CLASS_ID,
        "name": "Van",
        "description": "Passenger van category",
    })
    current["vehicles"].append({
        "id": SELTOS_VEHICLE_ID,
        "classId": CLASS_ID,
        "name": "Kia Seltos or similar",
        "seats": 5,
        "transmission": "automatic",
        "features": ["Air conditioning"],
        "dailyRate": {"currency": "USD", "amount": "65.00"},
        "weeklyRate": {"currency": "USD", "amount": "455.00"},
    })
    return current


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
    assert context["supplements"] == [{
        "name": "Child seat",
        "names": {
            "en": "Child seat", "nl": "Kinderzitje",
            "pap": "Stul pa mucha", "de": "Kindersitz",
        },
        "price_usd": "5.00",
        "billing_basis": "per_day",
    }]
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


def test_supplement_names_resolve_to_server_owned_id_and_current_price_in_all_locales():
    names = {
        "en": "Child seat", "nl": "Kinderzitje",
        "pap": "Stul pa mucha", "de": "Kindersitz",
    }
    for locale, name in names.items():
        resolved = workflow.resolve_catalog_supplements({
            "conversation_language": locale,
            "supplements": [{"name": name, "quantity": 2}],
        }, catalog())
        assert resolved["supplements"] == [{
            "id": CHILD_SEAT_ID,
            "name": name,
            "quantity": 2,
            "billing_basis": "per_day",
            "unit_price_usd": "5.00",
        }]


def test_supplement_quantity_is_bounded_and_duplicate_selection_is_rejected():
    for quantity in (0, 21, -1):
        try:
            workflow.resolve_catalog_supplements({
                "conversation_language": "en",
                "supplements": [{"name": "Child seat", "quantity": quantity}],
            }, catalog())
        except workflow.AliQuoteError as exc:
            assert exc.code == "invalid_supplement_quantity"
        else:
            raise AssertionError("invalid quantity should be rejected")

    try:
        workflow.resolve_catalog_supplements({
            "conversation_language": "en",
            "supplements": [
                {"name": "Child seat", "quantity": 1},
                {"name": "Child seat", "quantity": 1},
            ],
        }, catalog())
    except workflow.AliQuoteError as exc:
        assert exc.code == "duplicate_supplement_selection"
    else:
        raise AssertionError("duplicate supplement should be rejected")


def test_marina_tool_accepts_catalog_name_and_quantity_but_no_supplement_id_or_price():
    schema = marina_agent.MARINA_TOOL["input_schema"]["properties"]["fields"]["properties"]["supplements"]
    item = schema["items"]
    assert item["required"] == ["name", "quantity"]
    assert set(item["properties"]) == {"name", "quantity"}
    assert item["properties"]["quantity"]["minimum"] == 1
    assert item["properties"]["quantity"]["maximum"] == 20
    assert item["additionalProperties"] is False


def test_ali_primary_intent_contract_is_one_structured_value():
    schema = marina_agent.MARINA_TOOL["input_schema"]["properties"]["ali_primary_intent"]
    assert set(schema["enum"]) == workflow.ALI_PRIMARY_INTENTS
    assert marina_agent._RESPONSE_DEFAULTS["ali_primary_intent"] is None


def test_ali_prompt_uses_live_catalog_and_forbids_contact_redirects(monkeypatch):
    monkeypatch.setattr(marina_agent.config_loader, "get_raw", lambda: raw_config())
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda **_kwargs: catalog())

    prompt = marina_agent._build_ali_quote_block()

    assert "ALI CAR RENTAL WHATSAPP QUOTE INTAKE" in prompt
    assert '"name": "Economy"' in prompt
    assert '"daily_usd": "35.00"' in prompt
    assert CLASS_ID not in prompt
    assert "Never tell them to contact or" in prompt
    assert "Never populate vehicle_id, vehicle_class_id, or extra_ids" in prompt
    assert "quantity 1" in prompt
    assert '"price_usd": "5.00"' in prompt
    assert "If quantity is genuinely ambiguous" in prompt
    assert "never put an ID or price there" in prompt


def test_ali_prompt_answers_known_prices_immediately_and_continues_intake(monkeypatch):
    monkeypatch.setattr(marina_agent.config_loader, "get_raw", lambda: raw_config())
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda **_kwargs: catalog())

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
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda **_kwargs: catalog())

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
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda **_kwargs: catalog())

    prompt = marina_agent._build_ali_quote_block()
    normalized = " ".join(prompt.split())

    assert "DISCOVERY BEFORE PERSONAL DETAILS is mandatory" in normalized
    assert "QUOTE-LED CUSTOMER GUIDANCE is mandatory" in normalized
    assert "Delivery code prepends the single localized Ali/Nick welcome" in normalized
    assert "Do not greet the customer, introduce Nick" in normalized
    assert "Start directly with the useful answer or the one next question" in normalized
    assert "Hi, I’m Nick from Ali Car Rental." not in normalized
    assert "help you find the right car and prepare an official quote" in normalized
    assert "Speak in the first person and take conversational ownership" in normalized
    assert "I need a few more details so I can prepare and send you an official quote" in normalized
    assert "Never add a checking-style preface" in normalized
    assert "Just checking I’ve got everything right" not in normalized
    assert "Does that all look right?" not in normalized
    assert "ask what they prefer" in normalized
    assert "If they explicitly say they are undecided" in normalized
    assert "never combine vehicle preference with passenger count" in normalized
    assert "ask only passenger_count next" in normalized
    assert "ask only about luggage when it is useful" in normalized
    assert "approximate daily budget" in normalized
    assert "Do not ask every discovery question mechanically" in normalized
    assert "never ask the vehicle question again" in normalized
    assert "Collect rental_start and rental_end during discovery" in normalized
    assert "exact current daily_usd catalog rates at or closest to that budget" in normalized
    assert "A recommendation is not a customer decision" in normalized
    assert "Only after the customer explicitly chooses" in normalized
    assert "While they are browsing or comparing, keep talking about the cars" in normalized
    assert "may you request customer_name" in normalized
    assert "Do not ask for name, age, email, identity documents" in normalized
    assert "Never ask the customer to type" in normalized
    assert "Email is optional" in normalized
    assert "never ask for any of those facts again" in normalized
    assert "Never join two requested facts" in normalized
    assert "never ask a conditional second question" in normalized


def test_ali_prompt_keeps_recommendations_catalog_grounded_and_request_only(monkeypatch):
    monkeypatch.setattr(marina_agent.config_loader, "get_raw", lambda: raw_config())
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda **_kwargs: catalog())

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

    assert reply.startswith("I have these details from you:")
    assert reply.endswith(
        "Does everything look right? Choose an option below."
    )
    assert "Economy" in reply
    assert "WhatsApp: +351000000000" in reply
    assert "wa.me" not in reply
    assert "@" not in reply
    assert fields["vehicle_class_id"] == CLASS_ID
    assert flags["awaiting_quote_confirmation"] is True


def test_unchanged_summary_questions_and_explicit_repeat_are_locale_safe(monkeypatch):
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda: catalog())
    for locale in ("en", "nl", "pap", "de"):
        fields = {
            "customer_name": "Synthetic Customer",
            "rental_start": "2026-09-01",
            "rental_end": "2026-09-04",
            "pickup_location": "Synthetic airport",
            "return_location": "Synthetic hotel",
            "vehicle_class_name": "Economy",
            "driver_age": 30,
            "conversation_language": locale,
        }
        flags = {}
        first = workflow.handle_ali_quote_turn(
            f"synthetic-{locale}",
            "synthetic-account",
            "+351000000000",
            "complete details",
            fields,
            flags,
            from_name="Synthetic Customer",
            raw_config=raw_config(),
        )

        ordinary_question = workflow.handle_ali_quote_turn(
            f"synthetic-{locale}",
            "synthetic-account",
            "+351000000000",
            "ordinary question",
            fields,
            flags,
            from_name="Synthetic Customer",
            raw_config=raw_config(),
        )
        repeated = workflow.handle_ali_quote_turn(
            f"synthetic-{locale}",
            "synthetic-account",
            "+351000000000",
            "repeat request",
            fields,
            flags,
            from_name="Synthetic Customer",
            raw_config=raw_config(),
            summary_action={"mode": "repeat"},
        )

        assert ordinary_question is None
        assert repeated == first
        assert flags["awaiting_quote_confirmation"] is True


def test_complete_intake_includes_child_seat_and_refreshes_catalog_price(monkeypatch):
    current = catalog()
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda: current)
    fields = {
        "customer_name": "Synthetic Calvin",
        "rental_start": "2026-09-01",
        "rental_end": "2026-09-08",
        "pickup_location": "Curaçao International Airport",
        "return_location": "Curaçao International Airport",
        "vehicle_class_name": "Economy",
        "driver_age": 30,
        "conversation_language": "en",
        "supplements": [{"name": "Child seat", "quantity": 2}],
    }
    flags = {}

    first = workflow.handle_ali_quote_turn(
        "synthetic-child-seat", "synthetic-account", "+351000000000",
        "Please add two child seats.", fields, flags,
        from_name="Synthetic Calvin", raw_config=raw_config(),
    )
    first_hash = flags["ali_summary_hash"]
    assert "Child seat: 2 × USD 5.00 per rental day × 7 days = USD 70.00" in first
    assert fields["supplements"][0]["id"] == CHILD_SEAT_ID

    current = json.loads(json.dumps(current))
    current["extras"][0]["price"]["amount"] = "6.00"
    changed = workflow.handle_ali_quote_turn(
        "synthetic-child-seat", "synthetic-account", "+351000000000",
        "I also need the quote.", fields, flags,
        from_name="Synthetic Calvin", raw_config=raw_config(),
    )

    assert "USD 6.00" in changed
    assert "USD 84.00" in changed
    assert flags["ali_summary_hash"] != first_hash
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

    assert corrected.startswith("I have these details from you:")
    assert "Return: Synthetic hotel return" in corrected
    assert flags["ali_summary_hash"] != previous_hash
    assert flags["awaiting_quote_confirmation"] is True
    assert started == []


def test_latest_category_name_beats_stale_resolved_vehicle():
    stored_plus_latest = {
        "vehicle_id": ECONOMY_VEHICLE_ID,
        "vehicle_name": "Kia Picanto 2024 or similar",
        "vehicle_class_name": "Van",
    }

    resolved = workflow.resolve_catalog_selection(
        stored_plus_latest, correction_catalog()
    )

    assert resolved["vehicle_class_id"] == VAN_CLASS_ID
    assert resolved["vehicle_class_name"] == "Van"
    assert "vehicle_id" not in resolved
    assert "vehicle_name" not in resolved


def test_structured_vehicle_correction_replaces_only_stale_selection():
    stored = {
        "customer_name": "Synthetic Customer",
        "rental_start": "2026-09-01",
        "rental_end": "2026-09-04",
        "pickup_location": "Airport",
        "return_location": "Hotel",
        "vehicle_id": ECONOMY_VEHICLE_ID,
        "vehicle_name": "Kia Picanto 2024 or similar",
        "driver_age": 30,
        "passenger_count": 4,
        "luggage_count": 2,
        "comments": "Synthetic note",
        "conversation_language": "en",
    }
    changed, outcome, names = workflow.apply_latest_rental_change(
        stored,
        {"vehicle_class_name": "Van"},
        {"mode": "apply", "changed_fields": ["vehicle_selection"], "vehicle_selection_kind": "category"},
        correction_catalog(),
    )

    assert outcome == "changed"
    assert names == ("vehicle_selection",)
    assert changed["vehicle_class_id"] == VAN_CLASS_ID
    assert changed["vehicle_class_name"] == "Van"
    assert "vehicle_id" not in changed
    assert "vehicle_name" not in changed
    assert {key: changed[key] for key in stored if not key.startswith("vehicle_")} == {
        key: value for key, value in stored.items() if not key.startswith("vehicle_")
    }

    exact, outcome, _ = workflow.apply_latest_rental_change(
        changed,
        {"vehicle_name": "Kia Seltos or similar"},
        {"mode": "apply", "changed_fields": ["vehicle_selection"], "vehicle_selection_kind": "vehicle"},
        correction_catalog(),
    )
    assert outcome == "changed"
    assert exact["vehicle_id"] == SELTOS_VEHICLE_ID
    assert "vehicle_class_id" not in exact


def test_every_quote_relevant_change_is_scoped_and_catalog_validated():
    stored = {
        "customer_name": "Synthetic Customer",
        "rental_start": "2026-09-01",
        "rental_end": "2026-09-04",
        "pickup_location": "Airport",
        "return_location": "Airport",
        "vehicle_class_id": CLASS_ID,
        "vehicle_class_name": "Economy",
        "driver_age": 30,
        "passenger_count": 2,
        "luggage_count": 1,
        "comments": "Meet at arrivals",
        "conversation_language": "en",
        "supplements": [{
            "id": CHILD_SEAT_ID,
            "name": "Child seat",
            "quantity": 1,
            "billing_basis": "per_day",
            "unit_price_usd": "5.00",
        }],
    }
    cases = (
        ("customer_name", {"customer_name": "Corrected Synthetic"}, "Corrected Synthetic"),
        ("rental_start", {"rental_start": "2026-09-02"}, "2026-09-02"),
        ("rental_end", {"rental_end": "2026-09-05"}, "2026-09-05"),
        ("pickup_location", {"pickup_location": "Synthetic hotel"}, "Synthetic hotel"),
        ("return_location", {"return_location": "Synthetic hotel"}, "Synthetic hotel"),
        ("driver_age", {"driver_age": 31}, 31),
        ("passenger_count", {"passenger_count": 3}, 3),
        ("luggage_count", {"luggage_count": 2}, 2),
        ("comments", {"comments": "Late synthetic flight"}, "Late synthetic flight"),
    )
    for key, extracted, expected in cases:
        changed, outcome, names = workflow.apply_latest_rental_change(
            stored, extracted,
            {"mode": "apply", "changed_fields": [key]},
            correction_catalog(),
        )
        assert outcome == "changed"
        assert names == (key,)
        assert changed[key] == expected
        for preserved_key, value in stored.items():
            if preserved_key != key:
                assert changed[preserved_key] == value

    changed, outcome, _ = workflow.apply_latest_rental_change(
        stored,
        {"supplements": [{"name": "Child seat", "quantity": 2}]},
        {"mode": "apply", "changed_fields": ["supplements"]},
        correction_catalog(),
    )
    assert outcome == "changed"
    assert changed["supplements"][0]["quantity"] == 2

    removed, outcome, _ = workflow.apply_latest_rental_change(
        changed, {"supplements": []},
        {"mode": "apply", "changed_fields": ["supplements"]},
        correction_catalog(),
    )
    assert outcome == "changed"
    assert removed["supplements"] == []


def test_unknown_or_unspecified_change_preserves_state_for_one_clarification():
    stored = {
        "vehicle_id": ECONOMY_VEHICLE_ID,
        "vehicle_name": "Kia Picanto 2024 or similar",
        "rental_start": "2026-09-01",
    }
    for extracted, action in (
        ({"vehicle_class_name": "Imaginary van"}, {
            "mode": "apply", "changed_fields": ["vehicle_selection"],
            "vehicle_selection_kind": "category",
        }),
        ({}, {"mode": "clarify", "changed_fields": []}),
    ):
        result, outcome, names = workflow.apply_latest_rental_change(
            stored, extracted, action, correction_catalog()
        )
        assert result == stored
        assert outcome == "clarify"
        assert names == ()


def test_real_change_invalidates_only_active_summary_pointer():
    flags = {
        "ali_summary_hash": "old-hash",
        "ali_summary_version": 1,
        "awaiting_quote_confirmation": True,
        "ali_quote_public_id": "historical-quote-id",
        "reply_times": [1, 2],
    }
    workflow.invalidate_active_quote_summary(flags)

    assert flags == {
        "ali_phase": "DISCOVERY",
        "ali_quote_public_id": "historical-quote-id",
        "reply_times": [1, 2],
    }


def test_delivered_question_preserves_summary_for_following_confirmation(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow.state_registry, "DB_PATH", str(tmp_path / "tenant.db"))
    monkeypatch.setattr(workflow, "get_intake_catalog", catalog)
    phone = "synthetic-delivery-anchor"
    fields = {
        "customer_name": "Synthetic Customer",
        "rental_start": "2026-09-01",
        "rental_end": "2026-09-04",
        "pickup_location": "Synthetic airport",
        "return_location": "Synthetic hotel",
        "vehicle_class_name": "Economy",
        "driver_age": 30,
        "conversation_language": "en",
    }
    flags = {}
    workflow.state_registry.wa_save_booking_state(phone, fields, flags)

    initial = workflow.plan_ali_quote_turn(
        phone, "synthetic-account", "+351000000000", "complete details",
        fields, flags, "Thanks.", raw_config=raw_config(),
        primary_intent="continue_intake", supplied_action_id="1" * 64,
    )
    workflow.state_registry.wa_save_booking_state(phone, fields, flags)
    assert initial.outbound_kind == "summary"
    workflow.commit_ali_turn_delivery(
        phone, initial.delivery_commit(), initial.text, ["anchor-summary"],
    )

    state = workflow.state_registry.wa_get_booking_state(phone)
    answer = workflow.plan_ali_quote_turn(
        phone, "synthetic-account", "+351000000000", "What is the price?",
        state["fields"], state["flags"], "USD 35.00 per day.",
        raw_config=raw_config(), primary_intent="ask_question",
        supplied_action_id="2" * 64,
    )
    workflow.state_registry.wa_save_booking_state(
        phone, state["fields"], state["flags"],
    )
    workflow.commit_ali_turn_delivery(
        phone, answer.delivery_commit(), answer.text, ["anchor-answer"],
    )

    state = workflow.state_registry.wa_get_booking_state(phone)
    assert state["flags"]["ali_phase"] == "SUMMARY_PRESENTED"
    assert state["flags"]["ali_presented_summary_hash"] == initial.summary_hash
    assert state["flags"]["awaiting_quote_confirmation"] is True
    bare_yes = workflow.plan_ali_quote_turn(
        phone, "synthetic-account", "+351000000000", "Yes\nHow much",
        state["fields"], state["flags"], "Your quote is on its way.",
        # The deterministic fallback must outrank a wrong model intent label.
        raw_config=raw_config(), primary_intent="ask_question",
        processor=lambda _public_id: None,
        supplied_action_id="3" * 64,
    )
    assert bare_yes.outbound_kind == "quote_preparing"
    assert bare_yes.reason_code == "current_summary_confirmed"
    workflow.ensure_schema()
    connection = workflow._connection()
    try:
        assert connection.execute("SELECT COUNT(*) FROM ali_quotes").fetchone()[0] == 1
    finally:
        connection.close()


def test_ineligible_affirmative_returns_fresh_summary_without_quote_promise(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(workflow.state_registry, "DB_PATH", str(tmp_path / "tenant.db"))
    monkeypatch.setattr(workflow, "get_intake_catalog", catalog)
    fields = {
        "customer_name": "Synthetic Customer",
        "rental_start": "2026-09-01",
        "rental_end": "2026-09-04",
        "pickup_location": "Synthetic airport",
        "return_location": "Synthetic hotel",
        "vehicle_class_name": "Economy",
        "driver_age": 30,
        "conversation_language": "en",
    }
    flags = {"ali_phase": "DISCOVERY"}

    plan = workflow.plan_ali_quote_turn(
        "synthetic-ineligible-confirmation", "synthetic-account",
        "+351000000000", "yes it looks right", fields, flags,
        "Perfect, your quote is on its way.", raw_config=raw_config(),
        primary_intent="confirm_summary", supplied_action_id="4" * 64,
    )

    assert plan.outbound_kind == "summary"
    assert plan.reason_code == "confirmation_requires_current_summary"
    assert "I have these details from you:" in plan.text
    assert "quote is on its way" not in plan.text.lower()
    workflow.ensure_schema()
    connection = workflow._connection()
    try:
        assert connection.execute("SELECT COUNT(*) FROM ali_quotes").fetchone()[0] == 0
    finally:
        connection.close()


def test_question_with_validated_change_replaces_old_summary_before_confirmation(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(workflow.state_registry, "DB_PATH", str(tmp_path / "tenant.db"))
    monkeypatch.setattr(workflow, "get_intake_catalog", catalog)
    phone = "synthetic-question-with-change"
    original = {
        "customer_name": "Synthetic Customer",
        "rental_start": "2026-09-01",
        "rental_end": "2026-09-04",
        "pickup_location": "Synthetic airport",
        "return_location": "Synthetic hotel",
        "vehicle_class_name": "Economy",
        "driver_age": 30,
        "conversation_language": "en",
    }
    flags = {}
    workflow.state_registry.wa_save_booking_state(phone, original, flags)
    initial = workflow.plan_ali_quote_turn(
        phone, "synthetic-account", "+351000000000", "complete details",
        original, flags, "Thanks.", raw_config=raw_config(),
        primary_intent="continue_intake", supplied_action_id="5" * 64,
    )
    workflow.state_registry.wa_save_booking_state(phone, original, flags)
    workflow.commit_ali_turn_delivery(
        phone, initial.delivery_commit(), initial.text, ["question-change-summary"],
    )
    state = workflow.state_registry.wa_get_booking_state(phone)
    changed = dict(state["fields"])
    changed["return_location"] = "Corrected synthetic return"

    corrected = workflow.plan_ali_quote_turn(
        phone, "synthetic-account", "+351000000000",
        "Can I return it somewhere else instead?", changed, state["flags"],
        "Yes, I can update that.", raw_config=raw_config(),
        primary_intent="ask_question", change_outcome="changed",
        changed_fields=("return_location",), supplied_action_id="6" * 64,
    )

    assert corrected.outbound_kind == "summary"
    assert corrected.phase == "SUMMARY_PRESENTED"
    assert corrected.reason_code == "initial_or_corrected_complete_draft"
    assert corrected.summary_hash != initial.summary_hash
    assert "Corrected synthetic return" in corrected.text
    workflow.ensure_schema()
    connection = workflow._connection()
    try:
        assert connection.execute("SELECT COUNT(*) FROM ali_quotes").fetchone()[0] == 0
    finally:
        connection.close()


def test_summary_presented_transition_matrix_has_one_primary_action(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow.state_registry, "DB_PATH", str(tmp_path / "tenant.db"))
    monkeypatch.setattr(workflow, "get_intake_catalog", catalog)
    base_fields = {
        "customer_name": "Synthetic Customer",
        "rental_start": "2026-09-01",
        "rental_end": "2026-09-04",
        "pickup_location": "Synthetic airport",
        "return_location": "Synthetic hotel",
        "vehicle_class_name": "Economy",
        "driver_age": 30,
        "conversation_language": "en",
    }
    cases = (
        ("continue_intake", "one more thought", False, None, "agent_reply"),
        ("ask_question", "what is the price?", False, None, "agent_reply"),
        ("reject_or_hesitate", "I am not sure", False, None, "agent_reply"),
        (
            "request_recommendation", "show me a suitable option", True, None,
            "vehicle_recommendation",
        ),
        (
            "repeat_summary", "show the details again", False, {"mode": "repeat"},
            "summary",
        ),
        ("confirm_summary", "yes", False, None, "quote_preparing"),
        ("other", "thanks", False, None, "agent_reply"),
    )

    for index, (intent, text, recommendation, summary_action, expected) in enumerate(cases):
        phone = f"synthetic-matrix-{index}"
        fields = dict(base_fields)
        flags = {}
        workflow.state_registry.wa_save_booking_state(phone, fields, flags)
        initial = workflow.plan_ali_quote_turn(
            phone, "synthetic-account", "+351000000000", "complete details",
            fields, flags, "Thanks.", raw_config=raw_config(),
            primary_intent="continue_intake", supplied_action_id=f"{index + 1:064x}",
        )
        workflow.state_registry.wa_save_booking_state(phone, fields, flags)
        workflow.commit_ali_turn_delivery(
            phone, initial.delivery_commit(), initial.text,
            [f"matrix-summary-{index}"],
        )
        state = workflow.state_registry.wa_get_booking_state(phone)
        plan = workflow.plan_ali_quote_turn(
            phone, "synthetic-account", "+351000000000", text,
            state["fields"], state["flags"], "Natural customer answer.",
            raw_config=raw_config(), primary_intent=intent,
            recommendation_requested=recommendation,
            summary_action=summary_action,
            processor=lambda _public_id: None,
            supplied_action_id=f"{index + 100:064x}",
        )

        assert plan.outbound_kind == expected
        assert plan.primary_intent == intent


def test_processing_and_quoted_phases_cannot_reconfirm_stale_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow.state_registry, "DB_PATH", str(tmp_path / "tenant.db"))
    monkeypatch.setattr(workflow, "get_intake_catalog", catalog)
    fields = {
        "customer_name": "Synthetic Customer",
        "rental_start": "2026-09-01",
        "rental_end": "2026-09-04",
        "pickup_location": "Synthetic airport",
        "return_location": "Synthetic hotel",
        "vehicle_class_name": "Economy",
        "driver_age": 30,
        "conversation_language": "en",
    }
    for index, phase in enumerate(("QUOTE_PROCESSING", "QUOTED")):
        phone = f"synthetic-closed-phase-{index}"
        flags = {
            "ali_phase": phase,
            "ali_draft_hash": "1" * 64,
            "ali_draft_summary_hash": "2" * 64,
            "ali_draft_version": 1,
            "ali_presented_summary_hash": "2" * 64,
            "ali_last_delivered_kind": "summary",
            "awaiting_quote_confirmation": True,
        }
        workflow.state_registry.wa_save_booking_state(phone, fields, flags)
        state = workflow.state_registry.wa_get_booking_state(phone)
        question = workflow.plan_ali_quote_turn(
            phone, "synthetic-account", "+351000000000", "what is the price?",
            state["fields"], state["flags"], "USD 35.00 per day.",
            raw_config=raw_config(), primary_intent="ask_question",
            supplied_action_id=f"{index + 200:064x}",
        )
        confirmation = workflow.plan_ali_quote_turn(
            phone, "synthetic-account", "+351000000000", "yes",
            state["fields"], state["flags"], "That quote is already being handled.",
            raw_config=raw_config(), primary_intent="confirm_summary",
            supplied_action_id=f"{index + 210:064x}",
        )

        assert question.outbound_kind == "agent_reply"
        assert question.phase == phase
        assert confirmation.outbound_kind == "agent_reply"
        assert confirmation.phase == phase


def test_every_phase_by_primary_intent_has_a_deterministic_route(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow.state_registry, "DB_PATH", str(tmp_path / "tenant.db"))
    monkeypatch.setattr(workflow, "get_intake_catalog", catalog)
    complete_fields = {
        "customer_name": "Synthetic Customer",
        "rental_start": "2026-09-01",
        "rental_end": "2026-09-04",
        "pickup_location": "Synthetic airport",
        "return_location": "Synthetic hotel",
        "vehicle_class_name": "Economy",
        "driver_age": 30,
        "conversation_language": "en",
    }
    intents = (
        "continue_intake", "ask_question", "reject_or_hesitate",
        "request_recommendation", "repeat_summary", "confirm_summary", "other",
    )
    phases = (
        "COLLECTING", "DISCOVERY", "SUMMARY_PRESENTED",
        "QUOTE_PROCESSING", "QUOTED", "ESCALATED",
    )
    terminal_phases = {"QUOTE_PROCESSING", "QUOTED", "ESCALATED"}
    case_number = 500

    for locale, phase, intent in (
        (locale, phase, intent)
        for locale in ("en", "nl", "pap", "de")
        for phase in phases
        for intent in intents
    ):
            case_number += 1
            phone = f"synthetic-phase-intent-{locale}-{case_number}"
            fields = dict(complete_fields)
            fields["conversation_language"] = locale
            flags = {}
            if phase == "COLLECTING":
                fields.pop("rental_end")
                flags["ali_phase"] = phase
            else:
                seed = workflow.plan_ali_quote_turn(
                    phone, "synthetic-account", "+351000000000", "complete details",
                    fields, flags, "Thanks.", raw_config=raw_config(),
                    primary_intent="continue_intake",
                    supplied_action_id=f"{case_number + 1000:064x}",
                )
                assert seed.draft_hash and seed.summary_hash
                flags["ali_phase"] = phase
                flags["ali_last_delivered_kind"] = (
                    "summary" if phase == "SUMMARY_PRESENTED" else "agent_reply"
                )
                if phase == "SUMMARY_PRESENTED":
                    flags["ali_presented_summary_hash"] = seed.summary_hash
                    flags["ali_summary_hash"] = seed.summary_hash
                    flags["ali_summary_version"] = seed.summary_version
                    flags["awaiting_quote_confirmation"] = True
                    flags["ali_summary_anchor"] = {
                        "summary_hash": seed.summary_hash,
                        "summary_version": seed.summary_version,
                        "delivery": "plain_text",
                        "interaction_payload": "",
                    }
                if phase in terminal_phases:
                    flags["ali_active_quote_public_id"] = f"historical-{case_number}"

            plan = workflow.plan_ali_quote_turn(
                phone, "synthetic-account", "+351000000000",
                "yes" if intent == "confirm_summary" else f"synthetic {intent}",
                fields, flags, "Natural customer answer.",
                raw_config=raw_config(), primary_intent=intent,
                recommendation_requested=intent == "request_recommendation",
                summary_action={"mode": "repeat"} if intent == "repeat_summary" else None,
                processor=lambda _public_id: None,
                supplied_action_id=f"{case_number:064x}",
            )

            if intent == "request_recommendation":
                expected_kind = "vehicle_recommendation"
                expected_phase = "DISCOVERY"
            elif phase == "COLLECTING":
                expected_kind = "agent_reply"
                expected_phase = "COLLECTING"
            elif intent == "repeat_summary" and phase not in terminal_phases:
                expected_kind = "summary"
                expected_phase = "SUMMARY_PRESENTED"
            elif intent == "confirm_summary" and phase not in terminal_phases:
                expected_kind = "quote_preparing"
                if phase == "SUMMARY_PRESENTED":
                    expected_phase = "QUOTE_PROCESSING"
                else:
                    expected_kind = "summary"
                    expected_phase = "SUMMARY_PRESENTED"
            elif intent == "confirm_summary" and phase == "QUOTE_PROCESSING":
                expected_kind = "quote_preparing"
                expected_phase = "QUOTE_PROCESSING"
            else:
                expected_kind = "agent_reply"
                if phase in terminal_phases and intent in {
                    "continue_intake", "ask_question", "repeat_summary",
                    "confirm_summary", "other",
                }:
                    expected_phase = phase
                elif phase == "SUMMARY_PRESENTED" and intent == "ask_question":
                    expected_phase = "SUMMARY_PRESENTED"
                else:
                    expected_phase = "DISCOVERY"

            assert (plan.outbound_kind, plan.phase) == (
                expected_kind, expected_phase,
            ), (locale, phase, intent, plan)


def test_incomplete_quote_allows_valid_media_discovery_but_not_summary(monkeypatch):
    monkeypatch.setattr(workflow, "get_intake_catalog", catalog)
    fields = {
        "rental_start": "2026-08-29",
        "rental_end": "2026-09-26",
        "pickup_location": "Synthetic airport",
        "return_location": "Synthetic airport",
        "passenger_count": 4,
        "luggage_count": 3,
        "conversation_language": "en",
        "supplements": [],
    }
    flags = {
        "ali_phase": "COLLECTING",
        "ali_summary_hash": "a" * 64,
        "awaiting_quote_confirmation": True,
    }

    plan = workflow.plan_ali_quote_turn(
        "synthetic-incomplete-media", "synthetic-account", "+351000000000",
        "I want to see another car", fields, flags,
        "Here are a few suitable options.", raw_config=raw_config(),
        primary_intent="request_recommendation",
        recommendation_requested=True,
        supplied_action_id="8" * 64,
    )

    assert plan.outbound_kind == "vehicle_recommendation"
    assert plan.phase == "DISCOVERY"
    assert plan.reason_code == "recommendation_requested_before_quote_complete"
    assert plan.draft_hash == ""
    assert plan.summary_hash == ""
    assert "awaiting_quote_confirmation" not in flags
    assert "ali_summary_hash" in flags


def test_incomplete_quote_keeps_human_escalation_above_media(monkeypatch):
    monkeypatch.setattr(workflow, "get_intake_catalog", catalog)
    plan = workflow.plan_ali_quote_turn(
        "synthetic-incomplete-escalation", "synthetic-account", "+351000000000",
        "I need help choosing", {"conversation_language": "en"}, {},
        "I’ll have the team help with that.", raw_config=raw_config(),
        primary_intent="request_recommendation",
        requires_human=True,
        recommendation_requested=True,
        supplied_action_id="9" * 64,
    )

    assert plan.outbound_kind == "escalation"
    assert plan.phase == "ESCALATED"
    assert plan.reason_code == "required_fields_incomplete"


def test_turn_delivery_commit_is_idempotent_and_logs_no_customer_content(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow.state_registry, "DB_PATH", str(tmp_path / "tenant.db"))
    monkeypatch.setattr(workflow, "get_intake_catalog", catalog)
    events = []
    monkeypatch.setattr(
        workflow.bm_logger, "log",
        lambda event, **fields: events.append({"event": event, **fields}),
    )
    phone = "synthetic-idempotent-commit"
    fields = {
        "customer_name": "Private Synthetic Name",
        "rental_start": "2026-09-01",
        "rental_end": "2026-09-04",
        "pickup_location": "Private synthetic airport",
        "return_location": "Private synthetic hotel",
        "vehicle_class_name": "Economy",
        "driver_age": 30,
        "conversation_language": "en",
    }
    flags = {}
    workflow.state_registry.wa_save_booking_state(phone, fields, flags)
    plan = workflow.plan_ali_quote_turn(
        phone, "synthetic-account", "+351963618055", "private message text",
        fields, flags, "Private model reply.", raw_config=raw_config(),
        primary_intent="continue_intake", changed_fields=("pickup_location",),
        supplied_action_id="f" * 64,
    )
    workflow.state_registry.wa_save_booking_state(phone, fields, flags)

    assert workflow.commit_ali_turn_delivery(
        phone, plan.delivery_commit(), plan.text, ["provider-inbound-1"],
    ) is True
    assert workflow.commit_ali_turn_delivery(
        phone, plan.delivery_commit(), plan.text, ["provider-inbound-1"],
    ) is False

    connection = workflow.state_registry._get_conn()
    try:
        assistant_count = connection.execute(
            "SELECT COUNT(*) FROM whatsapp_threads "
            "WHERE phone = ? AND role = 'assistant'",
            (phone,),
        ).fetchone()[0]
    finally:
        connection.close()
    assert assistant_count == 1
    serialized = json.dumps(events, ensure_ascii=False).lower()
    assert "private synthetic name" not in serialized
    assert "+351963618055" not in serialized
    assert "private message text" not in serialized
    assert "private model reply" not in serialized


def test_late_failed_recommendation_is_removed_from_delivered_and_shown_state(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(workflow.state_registry, "DB_PATH", str(tmp_path / "tenant.db"))
    phone = "synthetic-late-recommendation-failure"
    workflow.state_registry.wa_save_booking_state(
        phone,
        {"conversation_language": "en", "vehicle_class_name": "Economy"},
        {},
    )
    plan = workflow.AliTurnPlan(
        "vehicle_recommendation",
        "Here is one suitable car.",
        "DISCOVERY",
        "request_recommendation",
        "recommendation_requested_before_quote_complete",
        "d" * 64,
    )

    assert workflow.commit_ali_turn_delivery(
        phone,
        plan.delivery_commit(),
        plan.text,
        ["synthetic-inbound"],
        recommendation_state_hash="e" * 64,
        recommendation_delivery="image",
        recommendation_vehicle_ids=[ECONOMY_VEHICLE_ID],
        recommendation_provider_message_ids=["provider-image-1"],
        recommendation_provider_parts={"image": ["provider-image-1"]},
        recommendation_snapshot={
            "kind": "image",
            "mode": "specific",
            "locale": "en",
            "state_hash": "e" * 64,
            "text": "Here is one suitable car.",
            "trigger_message_id": "wamid.synthetic-trigger",
            "trigger_sent_at": "2026-08-27T14:59:02Z",
        },
        recommendation_account_id="account-1",
    )
    committed = workflow.state_registry.wa_get_booking_state(phone)["flags"]
    assert committed["ali_shown_vehicle_ids"] == [ECONOMY_VEHICLE_ID]
    delivery = committed["ali_vehicle_recommendation_deliveries"][0]
    assert delivery["provider_parts"] == {"image": ["provider-image-1"]}
    assert delivery["account_id"] == "account-1"
    assert delivery["snapshot"]["vehicle_ids"] == [ECONOMY_VEHICLE_ID]
    assert delivery["snapshot"]["trigger_message_id"] == (
        "wamid.synthetic-trigger"
    )
    assert delivery["snapshot"]["trigger_sent_at"] == (
        "2026-08-27T14:59:02Z"
    )

    assert workflow.state_registry.wa_reconcile_vehicle_recommendation_failure(
        phone, "provider-image-1",
    )
    reconciled = workflow.state_registry.wa_get_booking_state(phone)["flags"]
    assert reconciled["ali_vehicle_recommendation_deliveries"] == []
    assert reconciled["ali_shown_vehicle_ids"] == []
    assert reconciled["ali_last_recommendation_ids"] == []


def test_failure_webhook_racing_before_commit_blocks_false_delivery_state(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(workflow.state_registry, "DB_PATH", str(tmp_path / "tenant.db"))
    phone = "synthetic-racing-recommendation-failure"
    workflow.state_registry.wa_save_booking_state(
        phone, {"conversation_language": "en", "vehicle_class_name": "Economy"}, {},
    )
    assert workflow.state_registry.wa_reconcile_vehicle_recommendation_failure(
        phone, "provider-image-race",
    )
    plan = workflow.AliTurnPlan(
        "vehicle_recommendation",
        "Here is one suitable car.",
        "DISCOVERY",
        "request_recommendation",
        "recommendation_requested_before_quote_complete",
        "c" * 64,
    )

    assert workflow.commit_ali_turn_delivery(
        phone,
        plan.delivery_commit(),
        plan.text,
        ["synthetic-inbound-race"],
        recommendation_state_hash="b" * 64,
        recommendation_delivery="image",
        recommendation_vehicle_ids=[ECONOMY_VEHICLE_ID],
        recommendation_provider_message_ids=["provider-image-race"],
    ) is False
    state = workflow.state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("ali_vehicle_recommendation_deliveries") in (None, [])
    assert "ali_last_delivered_kind" not in state["flags"]
    connection = workflow.state_registry._get_conn()
    try:
        assistant_count = connection.execute(
            "SELECT COUNT(*) FROM whatsapp_threads WHERE phone = ? AND role = 'assistant'",
            (phone,),
        ).fetchone()[0]
    finally:
        connection.close()
    assert assistant_count == 0


def test_change_action_contract_and_prompt_cover_universal_corrections(monkeypatch):
    action = marina_agent.MARINA_TOOL["input_schema"]["properties"]["ali_rental_change"]
    assert action["required"] == ["mode", "changed_fields"]
    assert action["properties"]["vehicle_selection_kind"]["enum"] == ["vehicle", "category"]
    assert set(action["properties"]["changed_fields"]["items"]["enum"]) == workflow.QUOTE_CHANGE_FIELDS
    monkeypatch.setattr(marina_agent.config_loader, "get_raw", lambda: raw_config())
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda **_kwargs: correction_catalog())

    prompt = " ".join(marina_agent._build_ali_quote_block().split())
    assert "only the facts explicitly replaced in that newest message" in prompt
    assert "special-request correction to `comments`" in prompt
    assert "`vehicle_selection_kind`" in prompt
    assert "mode `clarify`" in prompt
    assert "EN, NL, PAP, and DE" in prompt


def test_specific_recommendation_never_promotes_category_to_exact_vehicle():
    current = {
        "conversation_language": "en",
        "vehicle_class_id": CLASS_ID,
        "vehicle_class_name": "Economy",
    }

    changed, outcome, names = workflow.apply_recommendation_selection_context(
        current,
        {
            "mode": "specific",
            "vehicle_names": ["Kia Picanto 2024 or similar"],
        },
        correction_catalog(),
    )

    assert changed == current
    assert outcome == "unchanged"
    assert names == ()
    assert "vehicle_id" not in changed
    assert "vehicle_name" not in changed


def test_corrected_summary_shows_all_visible_details_in_all_locales(monkeypatch):
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda: correction_catalog())
    labels = {
        "en": ("Driver age: 31", "Passengers: 3", "Luggage: 2", "Special requests: Synthetic request"),
        "nl": ("Leeftijd bestuurder: 31", "Passagiers: 3", "Bagage: 2", "Speciale verzoeken: Synthetic request"),
        "pap": ("Edat di chauffeur: 31", "Pasaheronan: 3", "Maleta: 2", "Petishonnan spesial: Synthetic request"),
        "de": ("Alter des Fahrers: 31", "Passagiere: 3", "Gepäck: 2", "Besondere Wünsche: Synthetic request"),
    }
    for locale, expected_lines in labels.items():
        fields = {
            "customer_name": "Synthetic Customer",
            "rental_start": "2026-09-01",
            "rental_end": "2026-09-04",
            "pickup_location": "Airport",
            "return_location": "Hotel",
            "vehicle_class_name": "Van",
            "driver_age": 31,
            "passenger_count": 3,
            "luggage_count": 2,
            "comments": "Synthetic request",
            "conversation_language": locale,
        }
        flags = {}
        summary = workflow.handle_ali_quote_turn(
            f"synthetic-{locale}", "synthetic-account", "+351000000000",
            "Synthetic complete details", fields, flags,
            raw_config=raw_config(),
        )
        assert all(line in summary for line in expected_lines)
        assert flags["awaiting_quote_confirmation"] is True


def test_rental_change_log_contains_metadata_only(monkeypatch):
    events = []
    monkeypatch.setattr(
        workflow.bm_logger, "log",
        lambda event, **fields: events.append({"event": event, **fields}),
    )
    workflow.log_rental_change_decision(
        "changed", ("pickup_location", "vehicle_selection")
    )

    assert events == [{
        "event": "ali_rental_change_decision",
        "tenant_slug": "ali-car-rental",
        "outcome": "changed",
        "changed_fields": ["pickup_location", "vehicle_selection"],
    }]
    serialized = json.dumps(events).lower()
    assert "synthetic" not in serialized
    assert "whatsapp" not in serialized
    assert "+351" not in serialized
