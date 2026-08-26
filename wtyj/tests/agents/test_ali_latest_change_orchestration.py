import json

from agents.social import ali_quote_workflow as workflow
from agents.social import social_agent
from shared import state_registry

CLASS_ID = "30000000-0000-4000-8000-000000000001"
ECONOMY_VEHICLE_ID = "40000000-0000-4000-8000-000000000001"
VAN_CLASS_ID = "30000000-0000-4000-8000-000000000002"


def raw_config():
    return {
        "slug": "ali-car-rental",
        "workflow": {
            "type": "ali_quote",
            "required_deposit_charge_id": "90000000-0000-4000-8000-000000000001",
        },
        "features": {
            "booking_flow": False,
            "ali_quote_automation": True,
            "ali_quote_customer_delivery": False,
            "ali_quote_staff_email": False,
            "ali_quote_operator_alerts": False,
        },
    }


def correction_catalog():
    return {
        "catalogVersion": 11,
        "currency": "USD",
        "availabilityMode": "request_only",
        "vehicleClasses": [
            {"id": CLASS_ID, "name": "Economy", "description": "Economy"},
            {"id": VAN_CLASS_ID, "name": "Van", "description": "Van"},
        ],
        "vehicles": [{
            "id": ECONOMY_VEHICLE_ID,
            "classId": CLASS_ID,
            "name": "Kia Picanto 2024 or similar",
            "seats": 4,
            "transmission": "automatic",
            "features": ["Air conditioning"],
            "dailyRate": {"currency": "USD", "amount": "35.00"},
            "weeklyRate": {"currency": "USD", "amount": "245.00"},
        }],
        "extras": [],
        "charges": [],
    }


def _stored_fields(locale="en"):
    return {
        "customer_name": "Synthetic Customer",
        "rental_start": "2026-09-01",
        "rental_end": "2026-09-04",
        "pickup_location": "Synthetic airport",
        "return_location": "Synthetic hotel",
        "vehicle_id": ECONOMY_VEHICLE_ID,
        "vehicle_name": "Kia Picanto 2024 or similar",
        "driver_age": 30,
        "passenger_count": 2,
        "luggage_count": 1,
        "comments": "Synthetic request",
        "conversation_language": locale,
        "supplements": [],
    }


def _configure(monkeypatch, tmp_path, model_result):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "tenant.db"))
    monkeypatch.setattr(social_agent.config_loader, "get_raw", lambda: raw_config())
    monkeypatch.setattr(social_agent, "get_ali_intake_catalog", correction_catalog)
    monkeypatch.setattr(workflow, "get_intake_catalog", correction_catalog)
    monkeypatch.setattr(
        social_agent.marina_agent, "process_message", lambda **_kwargs: model_result
    )
    monkeypatch.setattr(
        social_agent.state_registry,
        "customer_lookup_or_create",
        lambda *_args, **_kwargs: {"id": 1, "display_name": "Synthetic Customer"},
    )
    monkeypatch.setattr(
        social_agent.state_registry, "customer_get_full", lambda *_args, **_kwargs: {}
    )
    monkeypatch.setattr(
        social_agent.state_registry, "customer_record_interaction", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        social_agent.state_registry, "customer_add_identifier", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        social_agent.state_registry, "customer_update_display_name", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        social_agent.appointment_detector,
        "upsert_pending_from_exchange",
        lambda **_kwargs: 0,
    )


def test_exact_vehicle_correction_emits_one_new_summary_and_persists_van(monkeypatch, tmp_path):
    phone = "synthetic-issue-190"
    fields = _stored_fields()
    customer = {"name": fields["customer_name"], "whatsapp": "+351000000000"}
    rental = {
        key: fields.get(key) for key in (
            "rental_start", "rental_end", "pickup_location", "return_location",
            "vehicle_id", "vehicle_name", "vehicle_class_id", "vehicle_class_name",
            "driver_age", "passenger_count", "luggage_count", "supplements",
            "comments", "conversation_language",
        )
    }
    _, old_hash = workflow.normalized_summary(customer, rental)
    flags = {
        "ali_summary_hash": old_hash,
        "ali_summary_version": 1,
        "awaiting_quote_confirmation": True,
        "ali_quote_public_id": "immutable-old-quote",
    }
    result = {
        "intents": ["inquiry"],
        "fields": {**fields, "vehicle_class_name": "Van"},
        "confidence": "high",
        "reply": "Of course. I’ll update the vehicle.",
        "requires_human": False,
        "flags": {},
        "ali_rental_change": {
            "mode": "apply", "changed_fields": ["vehicle_selection"],
            "vehicle_selection_kind": "category",
        },
    }
    _configure(monkeypatch, tmp_path, result)
    state_registry.wa_save_booking_state(phone, fields, flags)

    reply = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "No, that doesn’t look right, I want a van",
        "from_name": "Synthetic Customer",
        "_zernio_sender_id": "+351000000000",
        "_zernio_account_id": "synthetic-account",
    })
    saved = state_registry.wa_get_booking_state(phone)

    assert reply.count("Just checking I’ve got everything right:") == 1
    assert "Car: Van" in reply
    assert "Kia Picanto" not in reply
    assert saved["fields"]["vehicle_class_id"] == VAN_CLASS_ID
    assert "vehicle_id" not in saved["fields"]
    assert saved["flags"]["ali_summary_hash"] != old_hash
    assert saved["flags"]["awaiting_quote_confirmation"] is True
    assert "ali_quote_public_id" not in saved["flags"]
    assert saved["fields"]["return_location"] == "Synthetic hotel"

    second = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "No, that doesn’t look right, I want a van",
        "from_name": "Synthetic Customer",
        "_zernio_sender_id": "+351000000000",
        "_zernio_account_id": "synthetic-account",
    })
    assert "Just checking I’ve got everything right:" not in second
    assert second == "Of course. I’ll update the vehicle."


def test_generic_change_request_asks_clarification_without_old_summary(monkeypatch, tmp_path):
    phone = "synthetic-issue-190-clarify"
    fields = _stored_fields()
    flags = {"ali_summary_hash": "old-hash", "awaiting_quote_confirmation": True}
    result = {
        "intents": ["inquiry"],
        "fields": fields,
        "confidence": "high",
        "reply": "What would you like me to change?",
        "requires_human": False,
        "flags": {},
        "ali_rental_change": {"mode": "clarify", "changed_fields": []},
    }
    _configure(monkeypatch, tmp_path, result)
    state_registry.wa_save_booking_state(phone, fields, flags)

    reply = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "I want to change something",
        "from_name": "Synthetic Customer",
        "_zernio_sender_id": "+351000000000",
        "_zernio_account_id": "synthetic-account",
    })
    saved = state_registry.wa_get_booking_state(phone)

    assert reply == "What would you like me to change?"
    assert "Just checking" not in reply
    assert saved["fields"] == fields
    assert saved["flags"]["ali_summary_hash"] == "old-hash"


def test_four_language_vehicle_change_actions_use_same_canonical_state():
    phrases = {
        "en": "I want a van",
        "nl": "Ik wil een busje",
        "pap": "Mi ke un van",
        "de": "Ich möchte einen Van",
    }
    for locale, phrase in phrases.items():
        changed, outcome, names = workflow.apply_latest_rental_change(
            _stored_fields(locale),
            {"vehicle_class_name": "Van"},
            {"mode": "apply", "changed_fields": ["vehicle_selection"], "vehicle_selection_kind": "category"},
            correction_catalog(),
        )
        assert phrase
        assert outcome == "changed"
        assert names == ("vehicle_selection",)
        assert changed["vehicle_class_id"] == VAN_CLASS_ID
        assert changed["conversation_language"] == locale
        assert "vehicle_id" not in changed


def test_orchestration_source_does_not_log_customer_change_values():
    source = open(social_agent.__file__, encoding="utf-8").read()
    assert "log_rental_change_decision(_ali_change_outcome, _ali_change_fields)" in source
    assert "ali_rental_change_decision" not in source
    assert json.dumps({"message_text": "not logged"})
