"""Issue 198: deterministic media-first discovery policy."""

import pytest

from agents.social.ali_media_first import (
    catalog_class_recommendation_action,
    conversation_repair_reply,
    derive_media_first_action,
    enforce_vehicle_first_reply,
    explicit_catalog_browse_request,
    explicit_larger_vehicle_request,
    explicit_no_preference_request,
    explicit_smaller_vehicle_request,
    infer_explicit_catalog_class_selection,
    infer_media_first_intent,
    media_first_clarification,
    add_first_turn_welcome,
)


def _vehicle(index, name, class_id, seats, amount):
    return {
        "id": f"vehicle-{index}",
        "name": name,
        "classId": class_id,
        "seats": seats,
        "dailyRate": {"currency": "USD", "amount": amount},
        "images": [{"url": f"/vehicle-{index}.png"}],
        "displayOrder": index,
    }


def _catalog():
    return {
        "vehicleClasses": [
            {"id": "economy", "name": "Economy"},
            {"id": "compact", "name": "Compact Car"},
            {"id": "suv", "name": "SUV"},
        ],
        "vehicles": [
            _vehicle(1, "Volkswagen Up or similar", "economy", 4, "30.00"),
            _vehicle(2, "Kia Picanto 2024 or similar", "economy", 4, "35.00"),
            _vehicle(3, "Kia Picanto 2026 or similar", "economy", 4, "40.00"),
            _vehicle(4, "Toyota Yaris or similar", "compact", 5, "45.00"),
            _vehicle(5, "Toyota Corolla or similar", "compact", 5, "55.00"),
            _vehicle(6, "Kia Seltos or similar", "suv", 5, "65.00"),
        ],
    }


def _catalog_with_van():
    catalog = _catalog()
    catalog["vehicleClasses"].append({"id": "van", "name": "Van"})
    catalog["vehicles"].append(
        _vehicle(7, "Suzuki Ertiga", "van", 7, "75.00")
    )
    return catalog


def test_non_discovery_after_exact_choice_does_not_repeat_visuals():
    decision = derive_media_first_action(
        "ask_question",
        None,
        "The Toyota Yaris is USD 45 per day.",
        {"conversation_language": "en", "vehicle_id": "vehicle-4"},
        {},
        _catalog(),
    )

    assert decision == {"status": "not_discovery", "action": None}


@pytest.mark.parametrize(
    ("locale", "opening"),
    [
        ("en", "Welcome to Ali Car Rental! I’m Nick"),
        ("nl", "Welkom bij Ali Car Rental! Ik ben Nick"),
        ("pap", "Bon biní na Ali Car Rental! Mi ta Nick"),
        ("de", "Willkommen bei Ali Car Rental! Ich bin Nick"),
    ],
)
def test_first_turn_welcome_is_localized_and_preserves_one_next_question(locale, opening):
    reply = add_first_turn_welcome(
        "How many people will be travelling in the car?",
        {"conversation_language": locale},
    )

    assert reply.startswith(opening)
    assert reply.endswith("How many people will be travelling in the car?")
    assert reply.count("How many people") == 1


def test_fallback_intent_detects_text_dump_and_explicit_picture_request():
    catalog = _catalog()
    assert infer_media_first_intent(
        "What else do you have?",
        "Kia Picanto 2024 or similar and Toyota Yaris or similar",
        None,
        {"vehicle_class_id": "compact"},
        {},
        catalog,
    ) == "reject_or_hesitate"
    assert infer_media_first_intent(
        "Can you show me pictures of the car?",
        "Of course.",
        None,
        {"vehicle_id": "vehicle-4"},
        {},
        catalog,
    ) == "request_recommendation"


def test_fallback_intent_does_not_repeat_visual_for_ordinary_price_answer():
    assert infer_media_first_intent(
        "What is the price?",
        "The Toyota Yaris or similar is USD 45 per day.",
        None,
        {"vehicle_id": "vehicle-4"},
        {"ali_last_recommendation_ids": ["vehicle-4"]},
        _catalog(),
    ) == ""


def test_fallback_intent_enforces_single_offer_when_no_exact_car_selected():
    assert infer_media_first_intent(
        "What do you recommend?",
        "I recommend Toyota Yaris or similar.",
        None,
        {"passenger_count": 4, "luggage_count": 1},
        {},
        _catalog(),
    ) == "request_recommendation"


@pytest.mark.parametrize(
    "message_text",
    [
        "What car do you recommend?",
        "Ik wil graag advies over een auto",
        "Kua outo bo ta rekomendá?",
        "Welches Auto können Sie empfehlen?",
    ],
)
def test_recommendation_request_reopens_discovery(message_text):
    assert infer_media_first_intent(
        message_text,
        "Natural reply",
        None,
        {"vehicle_id": "vehicle-4"},
        {},
        _catalog(),
    ) == "reject_or_hesitate"


def test_changed_mind_reopens_discovery_after_exact_choice():
    assert infer_media_first_intent(
        "I changed my mind",
        "No problem.",
        None,
        {"vehicle_id": "vehicle-4"},
        {"ali_last_recommendation_ids": ["vehicle-4"]},
        _catalog(),
    ) == "reject_or_hesitate"


@pytest.mark.parametrize(
    ("message_text", "expected"),
    [
        ("Ik wil een andere auto", "reject_or_hesitate"),
        ("Mi ke mira potrèt di e outo", "request_recommendation"),
        ("Zeigen Sie mir bitte Bilder vom Auto", "request_recommendation"),
    ],
)
def test_fallback_intent_understands_supported_discovery_languages(
    message_text, expected,
):
    assert infer_media_first_intent(
        message_text,
        "Natural reply",
        None,
        {"vehicle_class_id": "compact"},
        {},
        _catalog(),
    ) == expected


@pytest.mark.parametrize(
    "message_text",
    [
        "I still want an SUV. Show me the pictures.",
        "Ik wil een SUV. Toon me de foto's.",
        "Mi ke un SUV. Mustra mi e potrètnan.",
        "Ich möchte einen SUV. Zeigen Sie mir die Bilder.",
    ],
)
def test_explicit_catalog_class_discovery_is_resolved_in_all_locales(
    message_text,
):
    assert infer_explicit_catalog_class_selection(
        message_text, _catalog(),
    ) == {
        "vehicle_class_id": "suv",
        "vehicle_class_name": "SUV",
    }


def test_bare_mobile_category_reply_is_an_explicit_category_selection():
    assert infer_explicit_catalog_class_selection(
        "SUV", _catalog(),
    ) == {
        "vehicle_class_id": "suv",
        "vehicle_class_name": "SUV",
    }


@pytest.mark.parametrize(
    "message_text",
    ["A van", "een van", "un van", "e van", "einen Van"],
)
def test_article_prefixed_active_class_is_an_explicit_selection(message_text):
    assert infer_explicit_catalog_class_selection(
        message_text, _catalog_with_van(),
    ) == {
        "vehicle_class_id": "van",
        "vehicle_class_name": "Van",
    }


@pytest.mark.parametrize(
    "message_text",
    [
        "Any bigger cars?",
        "Wat hebben jullie groter?",
        "Tin un outo mas grandi?",
        "Haben Sie ein größeres Auto?",
    ],
)
def test_larger_direction_is_actionable_in_all_locales(message_text):
    catalog = _catalog_with_van()
    assert explicit_larger_vehicle_request(message_text) is True
    assert infer_media_first_intent(
        message_text,
        "Would you prefer a smaller car, an SUV, or a van?",
        None,
        {
            "vehicle_id": "vehicle-4",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {},
        catalog,
    ) == "request_recommendation"


def test_negated_larger_direction_is_not_actionable():
    assert explicit_larger_vehicle_request(
        "I do not want a bigger car",
    ) is False


def test_larger_direction_overrides_stale_car_and_reopens_shown_van():
    decision = derive_media_first_action(
        "request_recommendation",
        {
            "mode": "curated",
            "vehicle_names": [
                "Toyota Yaris or similar",
                "Kia Seltos or similar",
            ],
        },
        "Would you prefer a smaller car, an SUV, or a van?",
        {
            "conversation_language": "en",
            "vehicle_id": "vehicle-4",
            "vehicle_name": "Toyota Yaris or similar",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {
            "ali_last_recommendation_ids": ["vehicle-7"],
            "ali_rejected_vehicle_ids": ["vehicle-7"],
            "ali_shown_vehicle_ids": ["vehicle-7"],
        },
        _catalog_with_van(),
        message_text="Any bigger cars?",
    )

    assert decision["status"] == "planned"
    assert decision["reason"] == "explicit_larger_preference"
    assert decision["action"]["mode"] == "specific"
    assert decision["action"]["vehicle_names"] == ["Suzuki Ertiga"]
    assert "larger option" in decision["reply_text"]


def test_exact_van_scope_overrides_stale_selection_and_delivery_history():
    catalog = _catalog_with_van()
    message_text = "A van"
    intent = infer_media_first_intent(
        message_text,
        "Would you prefer a smaller car, an SUV, or a van?",
        None,
        {
            "conversation_language": "en",
            "vehicle_id": "vehicle-4",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {"ali_last_recommendation_ids": ["vehicle-7"]},
        catalog,
    )
    decision = derive_media_first_action(
        intent,
        None,
        "Would you prefer a smaller car, an SUV, or a van?",
        {
            "conversation_language": "en",
            "vehicle_id": "vehicle-4",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {
            "ali_last_recommendation_ids": ["vehicle-7"],
            "ali_rejected_vehicle_ids": ["vehicle-7"],
            "ali_shown_vehicle_ids": ["vehicle-7"],
        },
        catalog,
        message_text=message_text,
    )

    assert decision["status"] == "planned"
    assert decision["reason"] == "explicit_catalog_class"
    assert decision["action"]["vehicle_names"] == ["Suzuki Ertiga"]


def test_undersized_model_candidates_are_repaired_from_catalog_capacity():
    decision = derive_media_first_action(
        "request_recommendation",
        {
            "mode": "curated",
            "vehicle_names": [
                "Toyota Yaris or similar",
                "Kia Seltos or similar",
            ],
        },
        "Here are two options.",
        {
            "conversation_language": "en",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {},
        _catalog_with_van(),
        message_text="What do you recommend?",
    )

    assert decision["status"] == "planned"
    assert decision["reason"] == "capacity_curated"
    assert decision["action"]["vehicle_names"] == ["Suzuki Ertiga"]


def test_confusion_and_reengagement_keep_category_without_assuming_vehicle():
    fields = {"conversation_language": "en", "vehicle_class_name": "Small Car"}
    confused = conversation_repair_reply("???", fields, {})
    resumed = conversation_repair_reply("Hello", fields, {})

    assert "Small Car" in confused
    assert "haven't selected a specific car" in confused
    assert "Small Car" in resumed
    assert "How many people" in resumed


@pytest.mark.parametrize(
    "message_text",
    [
        "I don't want an SUV.",
        "Ik wil geen SUV.",
        "Mi no ke SUV.",
        "Ich will keinen SUV.",
    ],
)
def test_negative_catalog_class_mentions_never_become_a_selection(message_text):
    assert infer_explicit_catalog_class_selection(message_text, _catalog()) is None


def test_longest_explicit_catalog_class_label_wins():
    catalog = _catalog()
    catalog["vehicleClasses"].append({"id": "compact-suv", "name": "Compact SUV"})

    assert infer_explicit_catalog_class_selection(
        "Please show me the Compact SUV pictures.", catalog,
    ) == {
        "vehicle_class_id": "compact-suv",
        "vehicle_class_name": "Compact SUV",
    }


def test_validated_class_builds_server_owned_recommendation_action():
    assert catalog_class_recommendation_action(
        {"vehicle_class_id": "suv", "vehicle_class_name": "SUV"},
        _catalog(),
    ) == {
        "mode": "specific",
        "vehicle_names": ["Kia Seltos or similar"],
        "selection_context": "category",
    }


def test_stale_or_cross_catalog_class_cannot_build_recommendation_action():
    assert catalog_class_recommendation_action(
        {"vehicle_class_id": "other-tenant", "vehicle_class_name": "SUV"},
        _catalog(),
    ) is None


def test_text_vehicle_dump_is_converted_to_one_curated_visual_action():
    reply = (
        "Kia Picanto 2024 or similar, Kia Picanto 2026 or similar, "
        "Toyota Yaris or similar, Toyota Corolla or similar"
    )
    decision = derive_media_first_action(
        "request_recommendation",
        None,
        reply,
        {
            "conversation_language": "en",
            "passenger_count": 4,
            "luggage_count": 2,
        },
        {},
        _catalog(),
    )

    assert decision["status"] == "planned"
    assert decision["action"]["mode"] == "curated"
    assert decision["action"]["vehicle_names"] == [
        "Kia Picanto 2024 or similar",
        "Kia Picanto 2026 or similar",
        "Toyota Yaris or similar",
        "Toyota Corolla or similar",
    ]
    assert "Kia Picanto" not in decision["reply_text"]
    assert "Which one do you prefer?" in decision["reply_text"]
    assert decision["reason"] == "catalog_names_in_reply"


@pytest.mark.parametrize(
    ("locale", "message_text"),
    [
        ("en", "I want the cheapest option"),
        ("nl", "Wat is de goedkoopste auto?"),
        ("pap", "Kua ta e mas barata?"),
        ("de", "Welches Auto ist am günstigsten?"),
    ],
)
def test_explicit_cheapest_request_overrides_model_prose_with_catalog_truth(
    locale, message_text,
):
    catalog = _catalog()
    catalog["vehicles"][0]["name"] = "Toyota Agya"
    catalog["vehicles"][0]["displayOrder"] = 99
    decision = derive_media_first_action(
        "request_recommendation",
        {
            "mode": "curated",
            "vehicle_names": [
                "Kia Picanto 2024 or similar",
                "Kia Picanto 2026 or similar",
            ],
        },
        "The Picanto is the cheapest automatic.",
        {
            "conversation_language": locale,
            "passenger_count": 3,
            "luggage_count": 2,
        },
        {},
        catalog,
        message_text=message_text,
    )

    assert decision["status"] == "planned"
    assert decision["reason"] == "lowest_price_catalog"
    assert decision["action"]["vehicle_names"][0] == "Toyota Agya"
    assert "30.00" in decision["reply_text"]
    assert "Picanto is the cheapest" not in decision["reply_text"]


def test_rejection_excludes_last_recommendation_and_prefers_unseen_options():
    decision = derive_media_first_action(
        "reject_or_hesitate",
        None,
        "No, what else do you have?",
        {
            "conversation_language": "en",
            "passenger_count": 4,
            "luggage_count": 2,
        },
        {
            "ali_last_recommendation_ids": ["vehicle-4", "vehicle-5"],
            "ali_shown_vehicle_ids": ["vehicle-1", "vehicle-4", "vehicle-5"],
        },
        _catalog(),
    )

    assert decision["status"] == "planned"
    assert decision["vehicle_ids"] == ["vehicle-2", "vehicle-3", "vehicle-6"]


def test_explicit_selected_vehicle_picture_is_one_specific_action():
    decision = derive_media_first_action(
        "request_recommendation",
        None,
        "Can you show me that car?",
        {"conversation_language": "en", "vehicle_id": "vehicle-4"},
        {},
        _catalog(),
    )

    assert decision["status"] == "planned"
    assert decision["action"]["mode"] == "specific"
    assert decision["action"]["vehicle_names"] == ["Toyota Yaris or similar"]
    assert decision["reason"] == "selected_vehicle_picture"


@pytest.mark.parametrize(
    ("fields", "reason", "question"),
    [
        (
            {"conversation_language": "en"},
            "missing_passenger_count",
            "How many people",
        ),
        (
            {"conversation_language": "en", "passenger_count": 4},
            "missing_luggage_count",
            "How much luggage",
        ),
    ],
)
def test_missing_trip_context_asks_one_useful_question(fields, reason, question):
    decision = derive_media_first_action(
        "request_recommendation",
        None,
        "What cars do you recommend?",
        fields,
        {},
        _catalog(),
    )

    assert decision["status"] == "needs_context"
    assert decision["action"] is None
    assert decision["reason"] == reason
    assert question in decision["reply_text"]
    assert decision["reply_text"].count("?") == 1


@pytest.mark.parametrize("locale", ["en", "nl", "pap", "de"])
def test_media_first_copy_is_localized(locale):
    decision = derive_media_first_action(
        "request_recommendation",
        {
            "mode": "specific",
            "vehicle_names": ["Toyota Yaris or similar"],
        },
        "Natural introduction",
        {"conversation_language": locale},
        {},
        _catalog(),
    )

    assert decision["status"] == "planned"
    assert decision["action"]["mode"] == "specific"
    assert decision["action"]["availability_note"]
    assert len(decision["action"]["cta_label"]) <= 24
    assert decision["reply_text"] != "Natural introduction"
    assert decision["reply_text"]


@pytest.mark.parametrize(
    "message_text",
    [
        "What ya have?",
        "Show me what you have",
        "Show me which kind of cars you have!",
        "Wat voor auto's hebben jullie?",
        "Kua outonan bo tin?",
        "Welche Autos haben Sie?",
    ],
)
def test_explicit_catalog_browse_is_actionable_in_all_locales(message_text):
    assert explicit_catalog_browse_request(message_text) is True
    assert infer_media_first_intent(
        message_text,
        "The Kia Picanto and Toyota Yaris are good options.",
        None,
        {"passenger_count": 6, "luggage_count": 3},
        {"ali_last_recommendation_ids": ["vehicle-6"]},
        _catalog(),
    ) == "request_recommendation"


def test_calvin_browse_replay_returns_visual_options_instead_of_looping():
    decision = derive_media_first_action(
        "request_recommendation",
        None,
        "Would you prefer a smaller car, an SUV, or a van?",
        {
            "conversation_language": "en",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {
            "ali_last_recommendation_ids": ["vehicle-6"],
            "ali_rejected_vehicle_ids": ["vehicle-6"],
        },
        _catalog(),
        message_text="Show me what you have",
    )

    assert decision["status"] == "planned"
    assert decision["action"]["mode"] == "curated"
    assert len(decision["action"]["vehicle_names"]) == 5
    assert decision["reason"] == "explicit_catalog_browse"
    assert "current fleet" in decision["reply_text"]
    assert "fewer than 6 seats" in decision["reply_text"]
    assert "Would you prefer" not in decision["reply_text"]


def test_explicit_browse_overrides_simultaneous_model_candidates():
    decision = derive_media_first_action(
        "request_recommendation",
        {
            "mode": "curated",
            "vehicle_names": [
                "Kia Picanto 2024 or similar",
                "Toyota Yaris or similar",
            ],
        },
        "Would you prefer a smaller car, an SUV, or a van?",
        {
            "conversation_language": "en",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {},
        _catalog(),
        message_text="Show me what you have",
    )

    assert decision["status"] == "planned"
    assert decision["reason"] == "explicit_catalog_browse"
    assert len(decision["action"]["vehicle_names"]) == 5
    assert "fewer than 6 seats" in decision["reply_text"]


@pytest.mark.parametrize(
    "message_text",
    ["Whatever", "no preference", "maakt niet uit", "egal"],
)
def test_no_preference_is_a_suitable_recommendation_request(message_text):
    assert explicit_no_preference_request(message_text) is True
    assert infer_media_first_intent(
        message_text,
        "Would you prefer a smaller car, an SUV, or a van?",
        None,
        {"passenger_count": 6, "luggage_count": 3},
        {"ali_last_recommendation_ids": ["vehicle-6"]},
        _catalog(),
    ) == "request_recommendation"


def test_no_preference_reopens_the_only_suitable_previously_rejected_car():
    catalog = _catalog()
    catalog["vehicleClasses"].append({"id": "van", "name": "Van"})
    catalog["vehicles"].append(
        _vehicle(7, "Suzuki Ertiga", "van", 7, "75.00")
    )

    decision = derive_media_first_action(
        "request_recommendation",
        None,
        "Would you prefer a smaller car, an SUV, or a van?",
        {
            "conversation_language": "en",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {
            "ali_last_recommendation_ids": ["vehicle-7"],
            "ali_rejected_vehicle_ids": ["vehicle-7"],
            "ali_shown_vehicle_ids": ["vehicle-7"],
        },
        catalog,
        message_text="Whatever",
    )

    assert decision["status"] == "planned"
    assert decision["reason"] == "capacity_curated"
    assert decision["action"]["mode"] == "specific"
    assert decision["action"]["vehicle_names"] == ["Suzuki Ertiga"]
    assert "Would you prefer" not in decision["reply_text"]


def test_no_preference_overrides_simultaneous_model_candidates():
    catalog = _catalog()
    catalog["vehicleClasses"].append({"id": "van", "name": "Van"})
    catalog["vehicles"].append(
        _vehicle(7, "Suzuki Ertiga", "van", 7, "75.00")
    )

    decision = derive_media_first_action(
        "request_recommendation",
        {
            "mode": "curated",
            "vehicle_names": [
                "Kia Picanto 2024 or similar",
                "Toyota Yaris or similar",
            ],
        },
        "The Kia Picanto and Toyota Yaris are good options.",
        {
            "conversation_language": "en",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {},
        catalog,
        message_text="Whatever",
    )

    assert decision["status"] == "planned"
    assert decision["reason"] == "capacity_curated"
    assert decision["action"]["vehicle_names"] == ["Suzuki Ertiga"]


@pytest.mark.parametrize(
    "message_text",
    ["Smaller", "kleinere auto", "outo mas chikí", "kleiner Wagen"],
)
def test_smaller_preference_is_actionable_in_all_locales(message_text):
    assert explicit_smaller_vehicle_request(message_text) is True
    assert infer_media_first_intent(
        message_text,
        "Would you prefer a smaller car, an SUV, or a van?",
        None,
        {"passenger_count": 6, "luggage_count": 3},
        {"ali_last_recommendation_ids": ["vehicle-6"]},
        _catalog(),
    ) == "request_recommendation"


def test_calvin_smaller_replay_shows_smaller_cars_with_capacity_context():
    decision = derive_media_first_action(
        "request_recommendation",
        None,
        "Would you prefer a smaller car, an SUV, or a van?",
        {
            "conversation_language": "en",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {
            "ali_last_recommendation_ids": ["vehicle-6"],
            "ali_rejected_vehicle_ids": ["vehicle-6"],
        },
        _catalog(),
        message_text="Smaller car",
    )

    assert decision["status"] == "planned"
    assert decision["reason"] == "explicit_smaller_preference"
    assert "Kia Seltos" not in decision["action"]["vehicle_names"]
    assert "seat up to 5" in decision["reply_text"]
    assert "6 people" in decision["reply_text"]


def test_explicit_smaller_overrides_simultaneous_model_candidates():
    decision = derive_media_first_action(
        "request_recommendation",
        {
            "mode": "curated",
            "vehicle_names": [
                "Kia Seltos or similar",
                "Toyota Yaris or similar",
            ],
        },
        "Would you prefer a smaller car, an SUV, or a van?",
        {
            "conversation_language": "en",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {},
        _catalog(),
        message_text="Smaller",
    )

    assert decision["status"] == "planned"
    assert decision["reason"] == "explicit_smaller_preference"
    assert "Kia Seltos" not in decision["action"]["vehicle_names"]
    assert "seat up to 5" in decision["reply_text"]


def test_negative_smaller_phrase_is_not_treated_as_positive_preference():
    assert explicit_smaller_vehicle_request("I don't want a smaller car") is False


def test_personal_details_are_blocked_until_vehicle_direction_is_chosen():
    fields = {
        "conversation_language": "en",
        "passenger_count": 6,
        "luggage_count": 3,
    }
    reply = enforce_vehicle_first_reply(
        "The Suzuki Ertiga is the largest option. What's your full name for the quote?",
        fields,
    )

    assert reply == "Would you prefer a smaller car, an SUV, or a van?"
    assert "name" not in reply.casefold()


def test_specific_recommendation_never_keeps_model_personal_question():
    decision = derive_media_first_action(
        "request_recommendation",
        {
            "mode": "specific",
            "vehicle_names": ["Kia Seltos or similar"],
        },
        "The Seltos fits your trip. What's your full name for the quote?",
        {
            "conversation_language": "en",
            "passenger_count": 4,
            "luggage_count": 2,
        },
        {},
        _catalog(),
    )

    assert decision["status"] == "planned"
    assert "name" not in decision["reply_text"].casefold()
    assert "feel right" in decision["reply_text"]


@pytest.mark.parametrize("locale", ["en", "nl", "pap", "de"])
def test_safe_invalid_plan_clarification_never_lists_cars(locale):
    reply = media_first_clarification({
        "conversation_language": locale,
        "passenger_count": 4,
        "luggage_count": 2,
    })
    assert reply.count("?") == 1
    assert "Toyota" not in reply
