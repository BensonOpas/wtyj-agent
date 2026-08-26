"""Issue 198: deterministic media-first discovery policy."""

import pytest

from agents.social.ali_media_first import (
    catalog_class_recommendation_action,
    conversation_repair_reply,
    derive_media_first_action,
    infer_explicit_catalog_class_selection,
    infer_media_first_intent,
    media_first_clarification,
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
    assert decision["reply_text"] == "Natural introduction"


@pytest.mark.parametrize("locale", ["en", "nl", "pap", "de"])
def test_safe_invalid_plan_clarification_never_lists_cars(locale):
    reply = media_first_clarification({
        "conversation_language": locale,
        "passenger_count": 4,
        "luggage_count": 2,
    })
    assert reply.count("?") == 1
    assert "Toyota" not in reply
