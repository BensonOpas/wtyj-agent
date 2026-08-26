"""Issue 198: deterministic media-first discovery policy."""

import pytest

from agents.social.ali_media_first import derive_media_first_action


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
