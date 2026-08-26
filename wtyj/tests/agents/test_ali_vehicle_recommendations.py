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
):
    return {
        "id": f"vehicle-{index}",
        "slug": f"vehicle-{index}",
        "name": name,
        "classId": category_id,
        "seats": seats,
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
            _vehicle(4, "Capacity pending", "suv", None, "75.50"),
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
        "This one is a practical fit. How many bags are you bringing?",
        public_base_url="https://alicarrental.com",
    )

    assert plan["kind"] == "image"
    assert len(plan["options"]) == 1
    assert "cards" not in plan
    option = plan["options"][0]
    assert option["image_url"] == (
        "https://alicarrental.com/brand/vehicles/vehicle-1.png"
    )
    assert option["detail_url"] == "https://alicarrental.com/en/fleet/vehicle-1"
    assert "Economy" in plan["text"]
    assert "4 seats" in plan["text"]
    assert "USD $35/day" in plan["text"]
    assert plan["text"].count("availability") == 1


@pytest.mark.parametrize(
    ("locale", "capacity_label", "cta"),
    [
        ("en", "seats", "View car"),
        ("nl", "zitplaatsen", "Bekijk auto"),
        ("pap", "lugá", "Mira outo"),
        ("de", "Sitzplätze", "Auto ansehen"),
    ],
)
def test_curated_carousel_is_two_to_five_suitable_localized_cards(
    locale,
    capacity_label,
    cta,
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
    assert capacity_label not in plan["cards"][2]["body"]["text"]
    assert "USD $75.50/day" in plan["cards"][2]["body"]["text"]
    assert "Automatic" in plan["cards"][0]["body"]["text"] if locale == "en" else True
    assert all(
        card["action"]["parameters"]["display_text"] == cta
        for card in plan["cards"]
    )
    assert all(card["type"] == "cta_url" for card in plan["cards"])
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
    assert rows[-1]["description"].startswith("Economy · Manual")
    assert plan["picker"]["button"] == "Choose a car"


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


def test_ali_prompt_requests_one_image_or_two_to_three_curated_options(monkeypatch):
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
    assert "best 2–3 suitable current vehicles" in prompt
    assert "never dump the whole fleet" in prompt
    assert "not in `reply` and not on each card" in prompt
    assert "Ordinary typed vehicle choices remain valid" in prompt
    assert "Do not repeat the unchanged summary" in prompt
    assert "chooses one option from a visual recommendation" in prompt


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


def _incoming(hours_ago=1):
    return {
        "direction": "incoming",
        "createdAt": (
            datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        ).isoformat(),
    }


def _carousel_plan():
    return recommendations.build_vehicle_recommendation(
        _action("curated", ["Toyota Yaris or similar", "Kia Seltos or similar"]),
        _catalog(),
        {"conversation_language": "en", "passenger_count": 4},
        {},
        "These two options suit your trip. Which one feels right?",
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
        "attachmentUrl": plan["options"][0]["image_url"],
        "attachmentType": "image",
        "buttons": plan["buttons"],
    }
    assert posts[0]["headers"]["Idempotency-Key"] == (
        f"{plan['idempotency_key']}-primary"
    )


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
    assert posts[1]["json"] == {"accountId": "account-1", "message": plan["text"]}
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
        }]}),
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
            _incoming(),
            {
                "direction": "outgoing",
                "interactive": {"body": {"text": plan["text"]}},
            },
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
        lambda *args, **kwargs: posts.append((args, kwargs)) or _Response(201),
    )

    result = zernio_dm_client.send_dm_vehicle_recommendation(
        "conversation-1", "account-1", plan,
    )

    assert result == {"success": True, "delivery": "carousel_picker"}
    assert posts == []


def test_restart_after_carousel_sends_only_missing_picker(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    plan = _carousel_plan()
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *args, **kwargs: _Response(200, {"messages": [
            _incoming(),
            {
                "direction": "outgoing",
                "interactive": {"body": {"text": plan["text"]}},
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
