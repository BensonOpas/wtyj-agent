"""Regression coverage for Ali customer-facing WhatsApp control labels."""

from agents.social import ali_quote_workflow
from agents.social import ali_reservation_workflow
from agents.social import ali_vehicle_recommendations


def _assert_every_word_is_capitalized(label: str) -> None:
    assert label
    assert len(label) <= 20
    for word in label.split():
        assert word[0].isupper(), label


def test_all_ali_whatsapp_button_labels_are_capitalized() -> None:
    labels = []

    for actions in ali_quote_workflow.QUOTE_CONFIRMATION_ACTIONS.values():
        labels.extend(actions)

    for copy in ali_reservation_workflow._CONTROL_COPY.values():
        labels.extend(copy[key] for key in ("reserve", "change", "question"))

    for copy in ali_vehicle_recommendations._CARD_LABELS.values():
        labels.extend(copy[key] for key in ("details", "choose_one", "choose_many"))

    for label in labels:
        _assert_every_word_is_capitalized(label)


def test_owner_required_english_button_labels_are_exact() -> None:
    assert ali_quote_workflow.QUOTE_CONFIRMATION_ACTIONS["en"] == (
        "Send My Quote",
        "Change Something",
    )
    assert {
        key: ali_reservation_workflow._CONTROL_COPY["en"][key]
        for key in ("reserve", "change", "question")
    } == {
        "reserve": "Reserve This Car",
        "change": "Change Something",
        "question": "Ask A Question",
    }
    assert {
        key: ali_vehicle_recommendations._CARD_LABELS["en"][key]
        for key in ("details", "choose_one", "choose_many")
    } == {
        "details": "Car Details",
        "choose_one": "Choose This Car",
        "choose_many": "Choose A Car",
    }
