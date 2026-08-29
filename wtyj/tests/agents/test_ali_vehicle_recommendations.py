"""Issue 178: premium catalog-grounded Ali vehicle discovery."""

from datetime import datetime, timedelta, timezone

import pytest

from agents.marina import marina_agent
from agents.social import ali_vehicle_recommendations as recommendations
from agents.social import zernio_dm_client
from shared import state_registry


def _vehicle(
    index,
    name,
    category_id,
    seats,
    amount,
    *,
    image=True,
    transmission="automatic",
    luggage_capacity=2,
):
    return {
        "id": f"vehicle-{index}",
        "slug": f"vehicle-{index}",
        "name": name,
        "classId": category_id,
        "seats": seats,
        "luggageCapacity": luggage_capacity,
        "transmission": transmission,
        "dailyRate": {"currency": "USD", "amount": amount},
        "images": ([{
            "url": f"/brand/vehicles/vehicle-{index}.png",
            "alt": f"Ali {name}",
        }] if image else []),
    }


def _catalog():
    return {
        "catalogVersion": 13,
        "currency": "USD",
        "availabilityMode": "request_only",
        "vehicleClasses": [
            {"id": "economy", "name": "Economy"},
            {"id": "compact", "name": "Compact Car"},
            {"id": "suv", "name": "Compact SUV"},
        ],
        "vehicles": [
            _vehicle(1, "Kia Picanto or similar", "economy", 4, "35.00"),
            _vehicle(2, "Toyota Yaris or similar", "compact", 5, "45.00"),
            _vehicle(3, "Kia Seltos or similar", "suv", 5, "65.00"),
            _vehicle(
                4, "Capacity pending", "suv", None, "75.50",
                luggage_capacity=None,
            ),
        ],
        "extras": [],
    }


def _action(mode, names, locale="en"):
    notes = {
        "en": "Final vehicle availability still needs confirmation.",
        "nl": "De definitieve voertuigbeschikbaarheid moet nog worden bevestigd.",
        "pap": "Disponibilidat final di e outo mester wordu konfirmá ainda.",
        "de": "Die endgültige Fahrzeugverfügbarkeit muss noch bestätigt werden.",
    }
    ctas = {"en": "View car", "nl": "Bekijk auto", "pap": "Mira outo", "de": "Auto ansehen"}
    return {
        "mode": mode,
        "vehicle_names": names,
        "availability_note": notes[locale],
        "cta_label": ctas[locale],
    }


def test_specific_vehicle_builds_one_image_from_current_catalog():
    plan = recommendations.build_vehicle_recommendation(
        _action("specific", ["Kia Picanto or similar"]),
        _catalog(),
        {"conversation_language": "en", "passenger_count": 2},
        {},
        "This one is a practical fit. Would you like to compare it?",
        public_base_url="https://alicarrental.com",
    )

    assert plan["kind"] == "image"
    assert len(plan["options"]) == 1
    assert "cards" not in plan
    option = plan["options"][0]
    assert option["image_url"] == (
        "https://alicarrental.com/brand/vehicles/vehicle-1.png"
    )
    assert option["whatsapp_image_url"] == (
        "https://alicarrental.com/api/v1/vehicle-media/vehicle-1?v=13"
    )
    assert option["detail_url"] == "https://alicarrental.com/en/fleet/vehicle-1"
    assert "Economy" in plan["text"]
    assert "4 seats" in plan["text"]
    assert "Cargo: approx. 2 medium suitcases" in plan["text"]
    assert "USD $35/day" in plan["text"]
    assert plan["text"].count("availability") == 1


@pytest.mark.parametrize(
    (
        "locale", "capacity_label", "luggage_label", "picker_luggage",
        "cta", "picker_text", "picker_button",
    ),
    [
        ("en", "seats", "Cargo: approx. 2 medium suitcases", "2 suitcases", "Car Details", "Choose your car below.", "Choose A Car"),
        ("nl", "zitplaatsen", "Bagageruimte: ca. 2 middelgrote koffers", "2 koffers", "Autodetails", "Kies hieronder je auto.", "Kies Een Auto"),
        ("pap", "lugá", "Espasio di ekipahe: aprox. 2 maleta mediano", "2 maleta", "Detayenan Di Outo", "Skoge bo outo aki bou.", "Skoge Un Outo"),
        ("de", "Sitzplätze", "Gepäckraum: ca. 2 mittelgroße Koffer", "2 Koffer", "Fahrzeugdetails", "Wählen Sie unten Ihr Auto aus.", "Auto Auswählen"),
    ],
)
def test_curated_carousel_is_two_to_five_suitable_localized_cards(
    locale,
    capacity_label,
    luggage_label,
    picker_luggage,
    cta,
    picker_text,
    picker_button,
):
    plan = recommendations.build_vehicle_recommendation(
        _action(
            "curated",
            ["Toyota Yaris or similar", "Kia Seltos or similar", "Capacity pending"],
            locale,
        ),
        _catalog(),
        {
            "conversation_language": locale,
            "passenger_count": 5,
            "luggage_count": 2,
        },
        {},
        "These are the options that best fit what you shared. Which one feels right?",
        public_base_url="https://alicarrental.com",
    )

    assert plan["kind"] == "carousel"
    assert len(plan["cards"]) == 3
    assert [card["card_index"] for card in plan["cards"]] == [0, 1, 2]
    assert capacity_label in plan["cards"][0]["body"]["text"]
    assert luggage_label in plan["cards"][0]["body"]["text"]
    assert capacity_label not in plan["cards"][2]["body"]["text"]
    assert luggage_label not in plan["cards"][2]["body"]["text"]
    assert "USD $75.50/day" in plan["cards"][2]["body"]["text"]
    assert "Automatic" in plan["cards"][0]["body"]["text"] if locale == "en" else True
    assert all(
        card["action"]["parameters"]["display_text"] == cta
        for card in plan["cards"]
    )
    assert all(card["type"] == "cta_url" for card in plan["cards"])
    assert plan["picker"]["text"] == picker_text
    assert plan["picker"]["button"] == picker_button
    assert picker_luggage in plan["picker"]["sections"][0]["rows"][0]["description"]
    assert all(
        "choose" not in card["action"]["parameters"]["display_text"].casefold()
        and "kies" not in card["action"]["parameters"]["display_text"].casefold()
        and "skoge" not in card["action"]["parameters"]["display_text"].casefold()
        and "wähl" not in card["action"]["parameters"]["display_text"].casefold()
        for card in plan["cards"]
    )
    assert plan["text"].count(_action("curated", ["x", "y"], locale)["availability_note"]) == 1


def test_curated_recommendation_rejects_undersized_or_fleet_dump_options():
    with pytest.raises(
        recommendations.AliVehicleRecommendationError,
        match="unsuitable_vehicle_capacity",
    ):
        recommendations.build_vehicle_recommendation(
            _action(
                "curated",
                ["Kia Picanto or similar", "Toyota Yaris or similar"],
            ),
            _catalog(),
            {"conversation_language": "en", "passenger_count": 5},
            {},
            "Two options for your trip. Which one feels right?",
        )
    with pytest.raises(
        recommendations.AliVehicleRecommendationError,
        match="invalid_recommendation_count",
    ):
        recommendations.build_vehicle_recommendation(
            _action("curated", ["one", "two", "three", "four", "five", "six"]),
            _catalog(),
            {"conversation_language": "en", "passenger_count": 2},
            {},
            "Options",
        )


def test_explicit_capacity_advisory_can_show_requested_smaller_cars():
    plan = recommendations.build_vehicle_recommendation(
        _action(
            "curated",
            ["Kia Picanto or similar", "Toyota Yaris or similar"],
        ),
        _catalog(),
        {"conversation_language": "en", "passenger_count": 6},
        {},
        (
            "These cars seat up to 5, so they will not fit your full group "
            "of 6. Which one would you like to compare?"
        ),
        capacity_advisory=True,
    )

    assert plan["kind"] == "carousel"
    assert [option["seats"] for option in plan["options"]] == [4, 5]
    assert "will not fit your full group" in plan["text"]


def test_direct_catalog_answer_can_show_cards_before_passenger_count_is_known():
    plan = recommendations.build_vehicle_recommendation(
        _action(
            "curated",
            ["Kia Picanto or similar", "Toyota Yaris or similar"],
        ),
        _catalog(),
        {"conversation_language": "en"},
        {},
        "Here are a few cars from our current fleet.",
        capacity_advisory=True,
    )

    assert plan["kind"] == "carousel"
    assert [option["seats"] for option in plan["options"]] == [4, 5]


def test_best_fit_curated_recommendation_still_requires_passenger_count():
    with pytest.raises(
        recommendations.AliVehicleRecommendationError,
        match="missing_passenger_count",
    ):
        recommendations.build_vehicle_recommendation(
            _action(
                "curated",
                ["Kia Picanto or similar", "Toyota Yaris or similar"],
            ),
            _catalog(),
            {"conversation_language": "en"},
            {},
            "Here are the best options for your group.",
        )


def test_accepted_discovery_hash_suppresses_replay():
    action = _action("specific", ["Kia Picanto or similar"])
    plan = recommendations.build_vehicle_recommendation(
        action,
        _catalog(),
        {"conversation_language": "en"},
        {},
        "Here it is. What pickup date works for you?",
    )
    flags = {
        "ali_vehicle_recommendation_deliveries": [{
            "hash": plan["state_hash"],
            "delivery": "image",
        }]
    }

    assert recommendations.build_vehicle_recommendation(
        action,
        _catalog(),
        {"conversation_language": "en"},
        flags,
        "Here it is again. What pickup date works for you?",
    ) is None


def test_curated_four_carousel_options_have_matching_native_picker_rows():
    catalog = _catalog()
    catalog["vehicles"].append(
        _vehicle(5, "Volkswagen Up or similar", "economy", 4, "30.00", transmission="manual")
    )
    plan = recommendations.build_vehicle_recommendation(
        _action(
            "curated",
            [
                "Kia Picanto or similar",
                "Toyota Yaris or similar",
                "Kia Seltos or similar",
                "Volkswagen Up or similar",
            ],
        ),
        catalog,
        {"conversation_language": "en", "passenger_count": 4},
        {},
        "Here are a few options that may suit you.",
    )

    assert len(plan["cards"]) == 4
    rows = plan["picker"]["sections"][0]["rows"]
    assert len(rows) == 4
    assert [row["id"] for row in rows] == [
        option["selection_id"] for option in plan["options"]
    ]
    assert rows[-1]["description"] == (
        "Economy · 4 seats · 2 suitcases · USD 30/day"
    )
    assert plan["picker"]["button"] == "Choose A Car"


def test_five_card_carousel_and_picker_preserve_exact_catalog_order():
    catalog = _catalog()
    catalog["vehicles"].extend([
        _vehicle(5, "Volkswagen Up or similar", "economy", 4, "30.00"),
        _vehicle(6, "Suzuki Swift or similar", "compact", 5, "50.00"),
    ])
    names = [
        "Kia Picanto or similar",
        "Toyota Yaris or similar",
        "Kia Seltos or similar",
        "Volkswagen Up or similar",
        "Suzuki Swift or similar",
    ]

    plan = recommendations.build_vehicle_recommendation(
        _action("curated", names),
        catalog,
        {"conversation_language": "en", "passenger_count": 4},
        {},
        "Here are the best matches for your trip.",
    )

    rows = plan["picker"]["sections"][0]["rows"]
    assert [option["name"] for option in plan["options"]] == names
    assert [row["id"] for row in rows] == [
        option["selection_id"] for option in plan["options"]
    ]
    assert [row["title"] for row in rows] == names
    assert all("seats" in row["description"] for row in rows)
    assert all("USD " in row["description"] for row in rows)
    assert plan["picker"]["fallback_text"].splitlines()[1:] == [
        f"{index}. {name}" for index, name in enumerate(names, start=1)
    ]


def test_invalid_selection_recovery_revalidates_last_current_catalog_branch():
    catalog = _catalog()
    catalog["vehicles"][0]["active"] = False
    plan = recommendations.build_vehicle_picker_recovery(
        catalog,
        {"conversation_language": "en"},
        {
            "ali_last_recommendation_ids": [
                "vehicle-1", "unknown-vehicle", "vehicle-3", "vehicle-2",
            ]
        },
        "That option is no longer valid. Choose from these current cars.",
        turn_id="stale-action-1",
    )

    assert plan["kind"] == "picker"
    assert [option["id"] for option in plan["options"]] == [
        "vehicle-3", "vehicle-2",
    ]
    assert [row["id"] for row in plan["picker"]["sections"][0]["rows"]] == [
        option["selection_id"] for option in plan["options"]
    ]


def test_invalid_selection_recovery_never_invents_an_unoffered_branch():
    assert recommendations.build_vehicle_picker_recovery(
        _catalog(),
        {"conversation_language": "en"},
        {"ali_last_recommendation_ids": ["cross-tenant-vehicle"]},
        "Choose a current car.",
    ) is None


def test_vehicle_selection_payload_round_trip_is_bounded_and_fail_closed():
    payload = recommendations.vehicle_selection_payload("vehicle-123")
    assert payload == "ali_vehicle_select:v1:vehicle-123"
    assert recommendations.parse_vehicle_selection_payload(payload) == "vehicle-123"
    assert recommendations.parse_vehicle_selection_payload("vehicle-123") is None
    assert recommendations.parse_vehicle_selection_payload(
        "ali_vehicle_select:v1:../../vehicle-123"
    ) is None
    with pytest.raises(
        recommendations.AliVehicleRecommendationError,
        match="invalid_vehicle_id",
    ):
        recommendations.vehicle_selection_payload("bad/id")


def test_marina_schema_exposes_structured_action_without_server_ids():
    schema = marina_agent.MARINA_TOOL["input_schema"]["properties"]
    action = schema["ali_vehicle_recommendation"]
    assert action["required"] == [
        "mode", "vehicle_names", "availability_note", "cta_label",
    ]
    assert action["properties"]["mode"]["enum"] == ["specific", "curated"]
    assert set(action["properties"]) == {
        "mode", "vehicle_names", "availability_note", "cta_label",
    }
    summary_action = schema["ali_summary_action"]
    assert summary_action["required"] == ["mode"]
    assert summary_action["properties"]["mode"]["enum"] == ["repeat"]


def test_ali_prompt_requires_one_image_or_two_to_five_curated_options(monkeypatch):
    monkeypatch.setattr(
        marina_agent.config_loader,
        "get_raw",
        lambda: {
            "slug": "ali-car-rental",
            "workflow": {"type": "ali_quote"},
            "features": {"ali_quote_automation": True},
        },
    )
    from agents.social import ali_quote_workflow
    monkeypatch.setattr(ali_quote_workflow, "get_intake_catalog", lambda **_kwargs: _catalog())

    prompt = " ".join(marina_agent._build_ali_quote_block().split())

    assert "PREMIUM VEHICLE VISUALS" in prompt
    assert "mode `specific` and exactly that catalog vehicle name" in prompt
    assert "best 2–5 suitable current vehicles" in prompt
    assert "MEDIA-FIRST IS MANDATORY" in prompt
    schema = marina_agent.MARINA_TOOL["input_schema"]["properties"]
    assert schema["ali_vehicle_recommendation"]["properties"]["vehicle_names"]["maxItems"] == 5
    assert "never dump the whole fleet" in prompt
    assert "not in `reply` and not on each card" in prompt
    assert "Ordinary typed vehicle choices remain valid" in prompt
    assert "Do not repeat the unchanged summary" in prompt
    assert "chooses one option from a visual recommendation" in prompt
    assert "is a category preference, not an exact-car selection" in prompt
    assert "punctuation-only confusion" in prompt


class _Response:
    def __init__(self, status_code, payload=None, *, headers=None, content=b""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""
        self.headers = headers or {}
        self.content = content

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=65536):
        del chunk_size
        yield self.content


_REAL_PREFLIGHT = zernio_dm_client._preflight_vehicle_media


@pytest.fixture(autouse=True)
def _valid_vehicle_media_preflight(monkeypatch):
    """Transport tests isolate Zernio; dedicated tests exercise real preflight."""
    monkeypatch.setattr(zernio_dm_client, "_preflight_vehicle_media", lambda _url: True)


def _incoming(hours_ago=1, message_id="trigger-message-1"):
    return {
        "id": message_id,
        "direction": "incoming",
        "createdAt": (
            datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        ).isoformat(),
    }


def _carousel_plan(trigger_message_id="trigger-message-1", trigger_sent_at=""):
    return recommendations.build_vehicle_recommendation(
        _action("curated", ["Toyota Yaris or similar", "Kia Seltos or similar"]),
        _catalog(),
        {"conversation_language": "en", "passenger_count": 4},
        {},
        "These two options suit your trip. Which one feels right?",
        trigger_message_id=trigger_message_id,
        trigger_sent_at=trigger_sent_at,
    )


def test_zernio_carousel_uses_official_schema_and_idempotency(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: _Response(200, {"messages": [_incoming()]}),
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda url, headers, json, timeout: (
            posts.append({"url": url, "headers": headers, "json": json})
            or _Response(201)
        ),
    )
    plan = _carousel_plan()

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result == {"success": True, "delivery": "carousel_picker"}
    assert len(posts) == 2
    assert posts[0]["headers"]["Idempotency-Key"] == (
        f"{plan['idempotency_key']}-primary"
    )
    interactive = posts[0]["json"]["interactive"]
    assert interactive["type"] == "carousel"
    assert interactive["body"] == {"text": plan["text"]}
    assert interactive["action"] == {"cards": plan["cards"]}
    assert "message" not in posts[0]["json"]
    assert posts[1]["headers"]["Idempotency-Key"] == (
        f"{plan['idempotency_key']}-picker"
    )
    picker = posts[1]["json"]["interactive"]
    assert picker["type"] == "list"
    assert picker["body"] == {"text": plan["picker"]["text"]}
    assert picker["action"] == {
        "button": plan["picker"]["button"],
        "sections": plan["picker"]["sections"],
    }


def test_picker_waits_for_provider_delivered_carousel(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(zernio_dm_client.time, "sleep", lambda _seconds: None)
    plan = _carousel_plan()
    events = []
    carousel_statuses = iter(["sent", "sent", "delivered"])

    def fake_get(*_args, **_kwargs):
        if "session" not in events:
            events.append("session")
            return _Response(200, {"messages": [_incoming()]})
        if "post:carousel" in events and "post:list" not in events:
            status = next(carousel_statuses)
            events.append(f"carousel:{status}")
            return _Response(200, {"messages": [{
                "id": "carousel-id",
                "direction": "outgoing",
                "deliveryStatus": status,
            }]})
        events.append("picker:sent")
        return _Response(200, {"messages": [{
            "id": "picker-id",
            "direction": "outgoing",
            "deliveryStatus": "sent",
        }]})

    def fake_post(url, headers, json, timeout):
        del url, headers, timeout
        kind = json["interactive"]["type"]
        events.append(f"post:{kind}")
        provider_id = "carousel-id" if kind == "carousel" else "picker-id"
        return _Response(201, {"id": provider_id})

    monkeypatch.setattr(zernio_dm_client.http_requests, "get", fake_get)
    monkeypatch.setattr(zernio_dm_client.http_requests, "post", fake_post)

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result["success"] is True
    assert events.index("carousel:delivered") < events.index("post:list")


def test_closed_session_attempts_no_interactive_or_free_text(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: _Response(200, {"messages": [_incoming(25)]}),
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda *args, **kwargs: posts.append((args, kwargs)) or _Response(201),
    )

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", _carousel_plan(),
    )

    assert result == {"success": False, "delivery": "window_closed"}
    assert posts == []


def test_fresh_signed_trigger_opens_session_before_history_catches_up(
    monkeypatch,
):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    plan = _carousel_plan(
        trigger_message_id="trigger-not-listed-yet",
        trigger_sent_at=datetime.now(timezone.utc).isoformat(),
    )
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: _Response(200, {"messages": []}),
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda url, headers, json, timeout: (
            posts.append({"headers": headers, "json": json})
            or _Response(201)
        ),
    )

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result == {"success": True, "delivery": "carousel_picker"}
    assert [post["json"]["interactive"]["type"] for post in posts] == [
        "carousel", "list",
    ]


def test_quote_confirmation_rejection_sends_exact_text_fallback(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    gets = iter([
        _Response(200, {"messages": [_incoming()]}),
        _Response(200, {"messages": [_incoming()]}),
    ])
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: next(gets),
    )

    def fake_post(url, headers, json, timeout):
        posts.append({"headers": headers, "json": json})
        return _Response(400 if len(posts) == 1 else 201)

    monkeypatch.setattr(zernio_dm_client.http_requests, "post", fake_post)
    confirmation = {
        "state_hash": "a" * 64,
        "idempotency_key": "ali-quote-confirm-" + "a" * 64,
        "text": "Synthetic current rental summary",
        "fallback_text": (
            "Synthetic current rental summary\n\n"
            "Reply SEND QUOTE to continue, or CHANGE DETAILS to make a correction."
        ),
        "button": {
            "type": "postback",
            "title": "Send My Quote",
            "payload": "ali_quote_confirm:v1:" + "b" * 64,
        },
    }
    confirmation["buttons"] = [
        confirmation["button"],
        {
            "type": "postback",
            "title": "Change Something",
            "payload": "ali_quote_change:v1:" + "c" * 64,
        },
    ]

    result = zernio_dm_client.send_dm_quote_confirmation(
        "conversation-1", "account-1", confirmation,
    )

    assert result == {"success": True, "delivery": "text_fallback"}
    assert posts[0]["json"]["buttons"] == confirmation["buttons"]
    assert posts[1]["json"] == {
        "accountId": "account-1",
        "message": confirmation["fallback_text"],
    }
    assert posts[1]["headers"]["Idempotency-Key"].endswith("-fallback")


def test_specific_vehicle_posts_one_image_message(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: _Response(200, {"messages": [_incoming()]}),
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda url, headers, json, timeout: (
            posts.append({"headers": headers, "json": json})
            or _Response(201)
        ),
    )
    plan = recommendations.build_vehicle_recommendation(
        _action("specific", ["Kia Picanto or similar"]),
        _catalog(),
        {"conversation_language": "en", "passenger_count": 2},
        {},
        "Here is the Picanto. What pickup date works for you?",
    )

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result == {"success": True, "delivery": "image"}
    assert len(posts) == 1
    assert posts[0]["json"] == {
        "accountId": "account-1",
        "message": plan["text"],
        "attachmentUrl": plan["options"][0]["whatsapp_image_url"],
        "attachmentType": "image",
        "buttons": plan["buttons"],
    }
    assert posts[0]["headers"]["Idempotency-Key"] == (
        f"{plan['idempotency_key']}-primary"
    )


def test_specific_vehicle_returns_provider_message_id_for_late_failure_tracking(
    monkeypatch,
):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    gets = iter([
        _Response(200, {"messages": [_incoming()]}),
        _Response(200, {"messages": [{
            "id": "provider-image-1",
            "direction": "outgoing",
            "status": "sent",
        }]}),
    ])
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: next(gets),
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda *args, **kwargs: _Response(201, {"data": {"id": "provider-image-1"}}),
    )
    plan = recommendations.build_vehicle_recommendation(
        _action("specific", ["Kia Picanto or similar"]),
        _catalog(),
        {"conversation_language": "en", "passenger_count": 2},
        {},
        "Here is the Picanto. What pickup date works for you?",
    )

    assert zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    ) == {
        "success": True,
        "delivery": "image",
        "provider_message_ids": ["provider-image-1"],
        "provider_parts": {"image": ["provider-image-1"]},
    }


def test_late_image_rejection_before_commit_uses_visible_text_fallback(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    gets = iter([
        _Response(200, {"messages": [_incoming()]}),
        _Response(200, {"messages": [{
            "id": "provider-image-1",
            "direction": "outgoing",
            "status": "failed",
        }]}),
    ])
    posts = iter([
        _Response(201, {"data": {"id": "provider-image-1"}}),
        _Response(201, {"data": {"id": "provider-fallback-1"}}),
    ])
    monkeypatch.setattr(
        zernio_dm_client.http_requests, "get", lambda *args, **kwargs: next(gets)
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests, "post", lambda *args, **kwargs: next(posts)
    )
    plan = recommendations.build_vehicle_recommendation(
        _action("specific", ["Kia Picanto or similar"]),
        _catalog(),
        {"conversation_language": "en", "passenger_count": 2},
        {},
        "Here is the Picanto. What pickup date works for you?",
    )

    assert zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    ) == {
        "success": True,
        "delivery": "fallback",
        "provider_message_ids": ["provider-fallback-1"],
        "provider_parts": {"picker_fallback": ["provider-fallback-1"]},
    }


def test_failed_visible_message_never_acknowledges_current_trigger(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    plan = recommendations.build_vehicle_recommendation(
        _action("specific", ["Kia Picanto or similar"]),
        _catalog(),
        {"conversation_language": "en", "passenger_count": 2},
        {},
        "Here is the Picanto. What pickup date works for you?",
        trigger_message_id="trigger-current",
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: _Response(200, {"messages": [
            {
                "id": "failed-current-image",
                "direction": "outgoing",
                "message": plan["text"],
                "status": "failed",
            },
            _incoming(message_id="trigger-current"),
        ]}),
    )
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda url, headers, json, timeout: (
            posts.append({"headers": headers, "json": json})
            or _Response(201, {"id": "fallback-current"})
        ),
    )

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result == {
        "success": True,
        "delivery": "fallback",
        "provider_message_ids": ["fallback-current"],
        "provider_parts": {"picker_fallback": ["fallback-current"]},
    }
    assert len(posts) == 1
    assert posts[0]["json"] == {
        "accountId": "account-1",
        "message": plan["text"],
    }


def test_parses_late_zernio_message_failure():
    parsed = zernio_dm_client.parse_zernio_failed_webhook({
        "event": "message.failed",
        "message": {
            "id": "provider-image-1",
            "conversationId": "conversation-1",
            "accountId": "account-1",
            "message": "Here is the selected car.",
            "attachments": [{"type": "image", "url": "https://assets.invalid/car.webp"}],
            "deliveryError": {"message": "Media upload error"},
        },
    })

    assert parsed == {
        "event": "message.failed",
        "conversation_id": "conversation-1",
        "message_id": "provider-image-1",
        "account_id": "account-1",
        "text": "Here is the selected car.",
        "recoverable_media": True,
        "failure_reason": "Media upload error",
    }


def test_parses_failed_media_account_from_conversation_and_singular_attachment():
    parsed = zernio_dm_client.parse_zernio_failed_webhook({
        "event": "message.failed",
        "conversation": {
            "id": "conversation-1",
            "accountId": "account-from-conversation",
        },
        "message": {
            "id": "provider-image-2",
            "message": "Here is the selected car.",
            "attachmentUrl": "https://assets.invalid/car.webp",
            "attachmentType": "image",
        },
    })

    assert parsed is not None
    assert parsed["account_id"] == "account-from-conversation"
    assert parsed["recoverable_media"] is True


def test_rejected_carousel_sends_exactly_one_idempotent_text_fallback(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    gets = iter([
        _Response(200, {"messages": [_incoming()]}),
        _Response(200, {"messages": [_incoming()]}),
    ])
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: next(gets),
    )

    def fake_post(url, headers, json, timeout):
        posts.append({"headers": headers, "json": json})
        return _Response(400 if len(posts) == 1 else 201)

    monkeypatch.setattr(zernio_dm_client.http_requests, "post", fake_post)
    plan = _carousel_plan()

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result == {"success": True, "delivery": "fallback"}
    assert len(posts) == 2
    assert "interactive" in posts[0]["json"]
    assert posts[1]["json"] == {
        "accountId": "account-1",
        "message": plan["picker"]["fallback_text"],
    }
    assert posts[1]["headers"]["Idempotency-Key"] == (
        f"{plan['idempotency_key']}-fallback"
    )


def test_ambiguous_send_reconciles_visible_carousel_without_fallback(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    plan = _carousel_plan()
    gets = iter([
        _Response(200, {"messages": [_incoming()]}),
        _Response(200, {"messages": [{
            "direction": "outgoing",
            "interactive": {"body": {"text": plan["text"]}},
        }, _incoming()]}),
    ])
    post_attempts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: next(gets),
    )

    def timeout_then_picker_success(*args, **kwargs):
        post_attempts.append((args, kwargs))
        if len(post_attempts) <= 2:
            raise zernio_dm_client.http_requests.Timeout("synthetic timeout")
        return _Response(201)

    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        timeout_then_picker_success,
    )

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result == {"success": True, "delivery": "carousel_picker"}
    assert len(post_attempts) == 3


def test_replay_reconciles_complete_carousel_picker_bundle_without_posts(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    plan = _carousel_plan()
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: _Response(200, {"messages": [
            # Zernio returns newest first: picker follows carousel.
            {
                "direction": "outgoing",
                "interactive": {"body": {"text": plan["picker"]["text"]}},
            },
            {
                "direction": "outgoing",
                "interactive": {"body": {"text": plan["text"]}},
            },
            _incoming(),
        ]}),
    )
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda *args, **kwargs: posts.append((args, kwargs)) or _Response(201),
    )

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result == {"success": True, "delivery": "carousel_picker"}
    assert posts == []


def test_prior_same_text_bundle_cannot_acknowledge_new_trigger(monkeypatch):
    """Regression for production incident #268."""
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    plan = _carousel_plan(trigger_message_id="trigger-current")
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: _Response(200, {"messages": [
            _incoming(message_id="trigger-current"),
            {
                "id": "old-picker",
                "direction": "outgoing",
                "interactive": {"body": {"text": plan["picker"]["text"]}},
            },
            {
                "id": "old-carousel",
                "direction": "outgoing",
                "interactive": {"body": {"text": plan["text"]}},
            },
            _incoming(hours_ago=2, message_id="trigger-old"),
        ]}),
    )
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda url, headers, json, timeout: (
            posts.append({"headers": headers, "json": json})
            or _Response(201)
        ),
    )

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result == {"success": True, "delivery": "carousel_picker"}
    assert [post["json"]["interactive"]["type"] for post in posts] == [
        "carousel", "list",
    ]


def test_provider_history_lag_uses_trigger_time_not_old_same_text(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    now = datetime.now(timezone.utc)
    trigger_time = now - timedelta(minutes=5)
    plan = _carousel_plan(
        trigger_message_id="trigger-not-visible-yet",
        trigger_sent_at=trigger_time.isoformat(),
    )
    old_time = (trigger_time - timedelta(minutes=1)).isoformat()
    old_incoming = (trigger_time - timedelta(minutes=2)).isoformat()
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: _Response(200, {"messages": [
            {
                "id": "old-picker",
                "direction": "outgoing",
                "createdAt": old_time,
                "interactive": {"body": {"text": plan["picker"]["text"]}},
            },
            {
                "id": "old-carousel",
                "direction": "outgoing",
                "createdAt": old_time,
                "interactive": {"body": {"text": plan["text"]}},
            },
            {
                "id": "trigger-old",
                "direction": "incoming",
                "createdAt": old_incoming,
            },
        ]}),
    )
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda url, headers, json, timeout: (
            posts.append({"headers": headers, "json": json})
            or _Response(201)
        ),
    )

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result == {"success": True, "delivery": "carousel_picker"}
    assert len(posts) == 2


def test_missing_trigger_anchors_disable_visible_text_reconciliation(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    plan = _carousel_plan(trigger_message_id="", trigger_sent_at="")
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: _Response(200, {"messages": [
            {
                "id": "old-picker",
                "direction": "outgoing",
                "interactive": {"body": {"text": plan["picker"]["text"]}},
            },
            {
                "id": "old-carousel",
                "direction": "outgoing",
                "interactive": {"body": {"text": plan["text"]}},
            },
            _incoming(message_id="some-other-trigger"),
        ]}),
    )
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda url, headers, json, timeout: (
            posts.append({"headers": headers, "json": json})
            or _Response(201)
        ),
    )

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result == {"success": True, "delivery": "carousel_picker"}
    assert len(posts) == 2


def test_old_picker_never_suppresses_picker_for_new_carousel(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    plan = _carousel_plan()
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: _Response(200, {"messages": [
            _incoming(),
            {
                "direction": "outgoing",
                "interactive": {"body": {"text": plan["picker"]["text"]}},
            },
        ]}),
    )
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda url, headers, json, timeout: (
            posts.append({"headers": headers, "json": json})
            or _Response(201)
        ),
    )

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result == {"success": True, "delivery": "carousel_picker"}
    assert [post["json"]["interactive"]["type"] for post in posts] == [
        "carousel", "list",
    ]
    assert posts[1]["json"]["interactive"]["action"]["button"] == (
        "Choose A Car"
    )


def test_restart_after_carousel_sends_only_missing_picker(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    plan = _carousel_plan()
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: _Response(200, {"messages": [
            {
                "direction": "outgoing",
                "interactive": {"body": {"text": plan["text"]}},
            },
            _incoming(),
        ]}),
    )
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda url, headers, json, timeout: (
            posts.append({"headers": headers, "json": json})
            or _Response(201)
        ),
    )

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result == {"success": True, "delivery": "carousel_picker"}
    assert len(posts) == 1
    assert posts[0]["json"]["interactive"]["type"] == "list"
    assert posts[0]["headers"]["Idempotency-Key"] == (
        f"{plan['idempotency_key']}-picker"
    )


def test_rejected_picker_uses_one_idempotent_instruction_fallback(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    plan = _carousel_plan()
    gets = iter([
        _Response(200, {"messages": [_incoming()]}),
        _Response(200, {"messages": [_incoming()]}),
    ])
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: next(gets),
    )
    posts = []

    def fake_post(url, headers, json, timeout):
        posts.append({"headers": headers, "json": json})
        if len(posts) == 2:
            return _Response(400)
        return _Response(201)

    monkeypatch.setattr(zernio_dm_client.http_requests, "post", fake_post)

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result == {
        "success": True,
        "delivery": "carousel_picker_fallback",
    }
    assert len(posts) == 3
    assert posts[0]["json"]["interactive"]["type"] == "carousel"
    assert posts[1]["json"]["interactive"]["type"] == "list"
    assert posts[2]["json"] == {
        "accountId": "account-1",
        "message": plan["picker"]["fallback_text"],
    }
    assert posts[2]["headers"]["Idempotency-Key"] == (
        f"{plan['idempotency_key']}-picker-fallback"
    )


def test_recovery_sends_only_native_picker_without_repeating_carousel(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    plan = recommendations.build_vehicle_picker_recovery(
        _catalog(),
        {"conversation_language": "en"},
        {"ali_last_recommendation_ids": ["vehicle-2", "vehicle-3"]},
        "That option is no longer valid. Choose from these current cars.",
        turn_id="stale-action-2",
    )
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: _Response(200, {"messages": [_incoming()]}),
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda url, headers, json, timeout: (
            posts.append({"headers": headers, "json": json}) or _Response(201)
        ),
    )

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result == {"success": True, "delivery": "picker"}
    assert len(posts) == 1
    assert posts[0]["json"]["interactive"]["type"] == "list"
    assert posts[0]["json"]["interactive"]["action"]["sections"] == (
        plan["picker"]["sections"]
    )
    assert posts[0]["headers"]["Idempotency-Key"] == (
        f"{plan['idempotency_key']}-primary"
    )


def test_recovery_picker_provider_failure_uses_numbered_text_once(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    plan = recommendations.build_vehicle_picker_recovery(
        _catalog(),
        {"conversation_language": "en"},
        {"ali_last_recommendation_ids": ["vehicle-2", "vehicle-3"]},
        "That option is no longer valid. Choose from these current cars.",
        turn_id="stale-action-3",
    )
    gets = iter([
        _Response(200, {"messages": [_incoming()]}),
        _Response(200, {"messages": [_incoming()]}),
    ])
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests, "get", lambda *args, **kwargs: next(gets)
    )

    def fake_post(url, headers, json, timeout):
        posts.append({"headers": headers, "json": json})
        return _Response(400 if len(posts) == 1 else 201)

    monkeypatch.setattr(zernio_dm_client.http_requests, "post", fake_post)

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result == {"success": True, "delivery": "picker_fallback"}
    assert len(posts) == 2
    assert posts[1]["json"] == {
        "accountId": "account-1",
        "message": plan["picker"]["fallback_text"],
    }


def test_state_delivery_marker_is_atomic_and_bounded(monkeypatch, tmp_path):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    state_registry.wa_save_booking_state("conversation-1", {"passenger_count": 2}, {})
    hashes = [f"{index:064x}" for index in range(24)]
    for state_hash in hashes:
        assert state_registry.wa_mark_vehicle_recommendation_delivered(
            "conversation-1", state_hash, "carousel",
        )
    assert state_registry.wa_mark_vehicle_recommendation_delivered(
        "conversation-1", hashes[-1], "carousel",
    )

    state = state_registry.wa_get_booking_state("conversation-1")
    deliveries = state["flags"]["ali_vehicle_recommendation_deliveries"]
    assert len(deliveries) == 20
    assert deliveries[-1] == {"hash": hashes[-1], "delivery": "carousel"}
    assert state["fields"] == {"passenger_count": 2}


def test_state_delivery_marker_records_picker_vehicle_branch(monkeypatch, tmp_path):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    state_registry.wa_save_booking_state(
        "conversation-1",
        {"passenger_count": 2},
        {"ali_shown_vehicle_ids": ["vehicle-old"]},
    )
    assert state_registry.wa_mark_vehicle_recommendation_delivered(
        "conversation-1",
        "a" * 64,
        "carousel_picker",
        ["vehicle-1", "vehicle-2", "vehicle-1"],
    )

    flags = state_registry.wa_get_booking_state("conversation-1")["flags"]
    assert flags["ali_last_recommendation_ids"] == ["vehicle-1", "vehicle-2"]
    assert flags["ali_shown_vehicle_ids"] == [
        "vehicle-old", "vehicle-1", "vehicle-2",
    ]
    assert flags["ali_vehicle_recommendation_deliveries"] == [{
        "hash": "a" * 64,
        "delivery": "carousel_picker",
    }]


def test_new_inbound_turn_does_not_repeat_same_vehicle_without_visual_request():
    fields = {
        "conversation_language": "en",
        "vehicle_id": "vehicle-1",
        "passenger_count": 2,
        "luggage_count": 1,
    }
    action = {
        "mode": "specific",
        "vehicle_names": ["Toyota Yaris or similar"],
        "availability_note": "Final availability needs confirmation.",
        "cta_label": "View car",
    }
    first = recommendations.build_vehicle_recommendation(
        action, _catalog(), fields, {}, "Here it is.",
        public_base_url="https://alicarrental.com",
        turn_id="inbound-1",
    )
    second = recommendations.build_vehicle_recommendation(
        action, _catalog(), fields, {
            "ali_vehicle_recommendation_deliveries": [{
                "hash": first["state_hash"], "delivery": "image",
            }],
        }, "Here it is again.",
        public_base_url="https://alicarrental.com",
        turn_id="inbound-2",
    )

    assert second is None


def test_explicit_visual_request_can_intentionally_resend_same_vehicle():
    fields = {
        "conversation_language": "en",
        "vehicle_id": "vehicle-1",
        "passenger_count": 2,
        "luggage_count": 1,
    }
    action = {
        "mode": "specific",
        "vehicle_names": ["Toyota Yaris or similar"],
        "availability_note": "Final availability needs confirmation.",
        "cta_label": "View car",
    }
    first = recommendations.build_vehicle_recommendation(
        action, _catalog(), fields, {}, "Here it is.",
        public_base_url="https://alicarrental.com",
        turn_id="inbound-1",
        allow_repeat=True,
    )
    second = recommendations.build_vehicle_recommendation(
        action, _catalog(), fields, {
            "ali_vehicle_recommendation_deliveries": [{
                "hash": first["state_hash"], "delivery": "image",
            }],
        }, "Here it is again.",
        public_base_url="https://alicarrental.com",
        turn_id="inbound-2",
        allow_repeat=True,
    )

    assert first["state_hash"] != second["state_hash"]


def test_carousel_provider_parts_track_images_and_picker_separately(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    gets = iter([
        _Response(200, {"messages": [_incoming()]}),
        _Response(200, {"messages": [{
            "id": "provider-carousel-1", "direction": "outgoing", "status": "delivered",
        }]}),
        _Response(200, {"messages": [{
            "id": "provider-picker-1", "direction": "outgoing", "status": "sent",
        }]}),
    ])
    posts = iter([
        _Response(201, {"data": {"id": "provider-carousel-1"}}),
        _Response(201, {"data": {"id": "provider-picker-1"}}),
    ])
    monkeypatch.setattr(zernio_dm_client.http_requests, "get", lambda *a, **k: next(gets))
    monkeypatch.setattr(zernio_dm_client.http_requests, "post", lambda *a, **k: next(posts))
    staged = []
    monkeypatch.setattr(
        zernio_dm_client.state_registry,
        "wa_stage_vehicle_recommendation_delivery",
        lambda *args: staged.append(args) or True,
    )

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", _carousel_plan(),
    )

    assert result["delivery"] == "carousel_picker"
    assert result["provider_parts"] == {
        "carousel": ["provider-carousel-1"],
        "picker": ["provider-picker-1"],
    }
    assert result["provider_message_ids"] == [
        "provider-carousel-1", "provider-picker-1",
    ]
    assert staged[0][3] == {"carousel": ["provider-carousel-1"]}
    assert staged[1][3] == {
        "carousel": ["provider-carousel-1"],
        "picker": ["provider-picker-1"],
    }
    assert staged[1][1]["trigger_message_id"] == "trigger-message-1"


@pytest.mark.parametrize(
    ("url", "response", "expected"),
    [
        (
            "https://alicarrental.com/api/v1/vehicle-media/vehicle-1?v=13",
            _Response(200, headers={"Content-Type": "image/jpeg"}, content=b"jpeg"),
            True,
        ),
        (
            "https://evil.invalid/api/v1/vehicle-media/vehicle-1?v=13",
            None,
            False,
        ),
        (
            "https://alicarrental.com/api/v1/vehicle-media/vehicle-1?v=13",
            _Response(302, headers={"Location": "https://evil.invalid/x"}),
            False,
        ),
        (
            "https://alicarrental.com/api/v1/vehicle-media/vehicle-1?v=13",
            _Response(200, headers={"Content-Type": "image/png"}, content=b"png"),
            False,
        ),
    ],
)
def test_vehicle_media_preflight_is_origin_mime_and_redirect_safe(
    monkeypatch, url, response, expected,
):
    monkeypatch.setenv("ALI_QUOTE_API_BASE_URL", "https://alicarrental.com")
    calls = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: calls.append((args, kwargs)) or response,
    )

    assert _REAL_PREFLIGHT(url) is expected
    if response is None:
        assert calls == []


def test_sparse_carousel_failure_claim_is_idempotent_and_retry_failure_advances(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    plan = _carousel_plan()
    state_registry.wa_save_booking_state(
        "conversation-1",
        {"conversation_language": "en"},
        {"ali_vehicle_recommendation_deliveries": [{
            "hash": plan["state_hash"],
            "delivery": "carousel_picker",
            "vehicle_ids": [item["id"] for item in plan["options"]],
            "provider_parts": {
                "carousel": ["provider-carousel-1"],
                "picker": ["provider-picker-1"],
            },
            "snapshot": {
                "kind": "carousel",
                "mode": "curated",
                "locale": "en",
                "state_hash": plan["state_hash"],
                "text": plan["text"],
                "vehicle_ids": [item["id"] for item in plan["options"]],
            },
            "account_id": "account-1",
        }]},
    )

    first = state_registry.wa_claim_vehicle_recommendation_failure(
        "conversation-1", "provider-carousel-1",
    )
    duplicate = state_registry.wa_claim_vehicle_recommendation_failure(
        "conversation-1", "provider-carousel-1",
    )
    assert first["stage"] == "retry"
    assert first["picker_present"] is True
    assert duplicate["already_handled"] is True

    assert state_registry.wa_complete_vehicle_recommendation_recovery(
        "conversation-1",
        first,
        {
            "success": True,
            "delivery": "carousel_retry",
            "provider_parts": {"carousel": ["provider-carousel-retry-1"]},
        },
    )
    retry_failure = state_registry.wa_claim_vehicle_recommendation_failure(
        "conversation-1", "provider-carousel-retry-1",
    )
    assert retry_failure["stage"] == "individual"
    assert retry_failure["picker_present"] is True


def test_failed_preflight_skips_carousel_and_sends_images_plus_one_picker(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    plan = _carousel_plan()
    preflights = iter([False, True, True])
    monkeypatch.setattr(
        zernio_dm_client,
        "_preflight_vehicle_media",
        lambda _url: next(preflights),
    )
    gets = iter([
        _Response(200, {"messages": [_incoming()]}),
        _Response(200, {"messages": [{"id": "image-1", "status": "delivered"}]}),
        _Response(200, {"messages": [{"id": "image-2", "status": "delivered"}]}),
        _Response(200, {"messages": [{"id": "picker-1", "status": "sent"}]}),
    ])
    posts = []
    provider_ids = iter(["image-1", "image-2", "picker-1"])
    monkeypatch.setattr(zernio_dm_client.http_requests, "get", lambda *a, **k: next(gets))
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda url, headers, json, timeout: (
            posts.append(json)
            or _Response(201, {"data": {"id": next(provider_ids)}})
        ),
    )

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result["delivery"] == "individual_picker"
    assert result["provider_parts"] == {
        "individual_images": ["image-1", "image-2"],
        "picker": ["picker-1"],
    }
    assert ["interactive" in body for body in posts] == [False, False, True]
    assert posts[-1]["interactive"]["type"] == "list"


def test_late_retry_then_individual_fallback_never_resends_picker(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    plan = _carousel_plan()
    snapshot = {
        "kind": "carousel",
        "mode": "curated",
        "locale": "en",
        "state_hash": plan["state_hash"],
        "text": plan["text"],
        "vehicle_ids": [item["id"] for item in plan["options"]],
    }
    retry_gets = iter([
        _Response(200, {"messages": [_incoming()]}),
        _Response(200, {"messages": [{"id": "carousel-retry-1", "status": "sent"}]}),
    ])
    retry_posts = []
    monkeypatch.setattr(zernio_dm_client.http_requests, "get", lambda *a, **k: next(retry_gets))
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda url, headers, json, timeout: (
            retry_posts.append(json)
            or _Response(201, {"data": {"id": "carousel-retry-1"}})
        ),
    )
    retry = zernio_dm_client.recover_dm_vehicle_recommendation(
        "conversation-1",
        "account-1",
        {"stage": "retry", "snapshot": snapshot},
        _catalog(),
    )
    assert retry["provider_parts"] == {"carousel": ["carousel-retry-1"]}
    assert len(retry_posts) == 1
    assert retry_posts[0]["interactive"]["type"] == "carousel"

    individual_gets = iter([
        _Response(200, {"messages": [_incoming()]}),
        _Response(200, {"messages": [{"id": "individual-1", "status": "delivered"}]}),
        _Response(200, {"messages": [{"id": "individual-2", "status": "delivered"}]}),
    ])
    individual_posts = []
    individual_ids = iter(["individual-1", "individual-2"])
    monkeypatch.setattr(
        zernio_dm_client.http_requests, "get", lambda *a, **k: next(individual_gets)
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda url, headers, json, timeout: (
            individual_posts.append(json)
            or _Response(201, {"data": {"id": next(individual_ids)}})
        ),
    )
    individual = zernio_dm_client.recover_dm_vehicle_recommendation(
        "conversation-1",
        "account-1",
        {"stage": "individual", "snapshot": snapshot, "picker_present": True},
        _catalog(),
    )
    assert individual["provider_parts"] == {
        "individual_images": ["individual-1", "individual-2"],
    }
    assert len(individual_posts) == 2
    assert all("interactive" not in body for body in individual_posts)
