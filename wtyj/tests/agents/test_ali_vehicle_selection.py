"""Issue 198: native WhatsApp vehicle picker selections."""

import pytest

from agents.social.ali_vehicle_recommendations import vehicle_selection_payload
from agents.social.ali_vehicle_selection import (
    AliVehicleSelectionError,
    invalid_vehicle_selection_reply,
    resolve_typed_vehicle_selection,
    resolve_vehicle_selection,
)
from agents.social.channels.whatsapp_zernio import WhatsAppZernioChannel
from agents.social.zernio_dm_client import parse_zernio_webhook


def _catalog():
    return {
        "vehicleClasses": [{"id": "compact", "name": "Compact Car"}],
        "vehicles": [{
            "id": "vehicle-1",
            "name": "Toyota Yaris or similar",
            "classId": "compact",
            "dailyRate": {"currency": "USD", "amount": "45.00"},
        }],
    }


@pytest.mark.parametrize("interactive_type", ["button_reply", "buttonreply", "list_reply", "listreply"])
def test_native_picker_selection_resolves_canonical_catalog_fields(interactive_type):
    assert resolve_vehicle_selection(
        interactive_type,
        vehicle_selection_payload("vehicle-1"),
        _catalog(),
    ) == {
        "vehicle_id": "vehicle-1",
        "vehicle_name": "Toyota Yaris or similar",
        "vehicle_class_id": "compact",
        "vehicle_class_name": "Compact Car",
        "vehicle_catalog_class_id": "compact",
        "vehicle_catalog_class_name": "Compact Car",
        "vehicle_daily_rate_usd": "45.00",
        "vehicle_rate_currency": "USD",
    }


def test_unrelated_interactive_reply_is_ignored():
    assert resolve_vehicle_selection("list_reply", "another_feature:v1:row", _catalog()) is None
    assert resolve_vehicle_selection(
        "nfm_reply",
        "another_feature:v1:row",
        _catalog(),
    ) is None


@pytest.mark.parametrize(
    "catalog",
    [
        {"vehicleClasses": [{"id": "compact", "name": "Compact Car"}], "vehicles": []},
        {
            "vehicleClasses": [{"id": "compact", "name": "Compact Car"}],
            "vehicles": [{
                "id": "vehicle-1",
                "name": "Toyota Yaris or similar",
                "classId": "compact",
                "active": False,
                "dailyRate": {"currency": "USD", "amount": "45.00"},
            }],
        },
    ],
)
def test_removed_or_inactive_vehicle_selection_fails_closed(catalog):
    with pytest.raises(AliVehicleSelectionError, match="vehicle_selection_not_active"):
        resolve_vehicle_selection(
            "list_reply",
            vehicle_selection_payload("vehicle-1"),
            catalog,
        )


def test_cross_tenant_vehicle_id_fails_against_current_tenant_catalog():
    with pytest.raises(AliVehicleSelectionError, match="vehicle_selection_not_active"):
        resolve_vehicle_selection(
            "list_reply",
            vehicle_selection_payload("other-tenant-vehicle"),
            _catalog(),
        )


def test_malformed_ali_picker_payload_fails_closed():
    with pytest.raises(AliVehicleSelectionError, match="payload_invalid"):
        resolve_vehicle_selection(
            "list_reply",
            "ali_vehicle_select:v1:../../vehicle-1",
            _catalog(),
        )


def test_ali_picker_payload_with_missing_type_fails_closed():
    with pytest.raises(AliVehicleSelectionError, match="type_invalid"):
        resolve_vehicle_selection(
            "",
            "ali_vehicle_select:v1:vehicle-1",
            _catalog(),
        )


@pytest.mark.parametrize(
    "message_text",
    [
        "Toyota Yaris",
        "I choose Toyota Yaris or similar",
        "Ik kies Toyota Yaris",
        "Mi ke Toyota Yaris",
        "Ich wähle Toyota Yaris",
    ],
)
def test_clear_typed_exact_choice_resolves_like_native_tap(message_text):
    selection = resolve_typed_vehicle_selection(message_text, _catalog())
    assert selection["vehicle_id"] == "vehicle-1"
    assert selection["vehicle_name"] == "Toyota Yaris or similar"


@pytest.mark.parametrize(
    "message_text",
    [
        "I choose the Toyota Yaris or similar.",
        "Ik kies voor de Toyota Yaris or similar.",
        "Mi ta skoge e Toyota Yaris or similar.",
        "Ich wähle den Toyota Yaris or similar.",
    ],
)
def test_localized_choose_in_chat_message_resolves_exact_active_vehicle(message_text):
    selection = resolve_typed_vehicle_selection(message_text, _catalog())
    assert selection["vehicle_id"] == "vehicle-1"
    assert selection["vehicle_daily_rate_usd"] == "45.00"


@pytest.mark.parametrize(
    "catalog",
    [
        {
            "vehicleClasses": [{"id": "compact", "name": "Compact Car"}],
            "vehicles": [],
        },
        {
            "vehicleClasses": [{"id": "compact", "name": "Compact Car"}],
            "vehicles": [
                {
                    "id": "vehicle-1",
                    "name": "Toyota Yaris or similar",
                    "classId": "compact",
                    "dailyRate": {"currency": "USD", "amount": "45.00"},
                },
                {
                    "id": "vehicle-2",
                    "name": "Toyota Yaris or similar",
                    "classId": "compact",
                    "dailyRate": {"currency": "USD", "amount": "45.00"},
                },
            ],
        },
    ],
)
def test_stale_or_ambiguous_handoff_message_fails_closed(catalog):
    with pytest.raises(
        AliVehicleSelectionError,
        match="vehicle_handoff_not_unique",
    ):
        resolve_typed_vehicle_selection(
            "I choose the Toyota Yaris or similar.",
            catalog,
        )


def test_non_handoff_unknown_typed_choice_remains_normal_conversation():
    assert resolve_typed_vehicle_selection(
        "I want an SUV",
        _catalog(),
    ) is None


def test_question_that_mentions_exact_vehicle_is_not_treated_as_choice():
    assert resolve_typed_vehicle_selection(
        "Toyota Yaris?", _catalog()
    ) is None
    assert resolve_typed_vehicle_selection(
        "What is the price of Toyota Yaris?", _catalog()
    ) is None


@pytest.mark.parametrize("locale", ["en", "nl", "pap", "de"])
def test_invalid_selection_clarification_is_localized(locale):
    assert invalid_vehicle_selection_reply(locale)


def test_zernio_parser_and_whatsapp_adapter_preserve_native_picker_metadata():
    payload = {
        "event": "message.received",
        "data": {
            "id": "message-1",
            "text": "Toyota Yaris or similar",
            "conversationId": "conversation-1",
            "platform": "whatsapp",
            "accountId": "account-1",
            "sender": {"id": "customer-1", "name": "Customer"},
            "metadata": {
                "interactiveType": "list_reply",
                "interactiveId": vehicle_selection_payload("vehicle-1"),
            },
        },
    }

    parsed = parse_zernio_webhook(payload)
    adapted = WhatsAppZernioChannel.from_zernio(parsed)

    assert parsed["interactive_type"] == "list_reply"
    assert parsed["interactive_id"] == vehicle_selection_payload("vehicle-1")
    assert adapted["_zernio_interactive_type"] == "list_reply"
    assert adapted["_zernio_interactive_id"] == vehicle_selection_payload(
        "vehicle-1"
    )
