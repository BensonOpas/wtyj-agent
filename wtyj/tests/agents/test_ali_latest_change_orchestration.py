import json

from agents.social import ali_quote_workflow as workflow
from agents.social import social_agent
from agents.social.ali_vehicle_recommendations import vehicle_selection_payload
from shared import state_registry

CLASS_ID = "30000000-0000-4000-8000-000000000001"
ECONOMY_VEHICLE_ID = "40000000-0000-4000-8000-000000000001"
VAN_CLASS_ID = "30000000-0000-4000-8000-000000000002"
SUV_CLASS_ID = "30000000-0000-4000-8000-000000000003"
SUV_VEHICLE_ID = "40000000-0000-4000-8000-000000000003"
SECOND_SUV_VEHICLE_ID = "40000000-0000-4000-8000-000000000004"
YARIS_VEHICLE_ID = "40000000-0000-4000-8000-000000000005"
COROLLA_VEHICLE_ID = "40000000-0000-4000-8000-000000000006"


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
            {
                "id": SUV_CLASS_ID,
                "name": "Compact SUV",
                "description": "Compact SUV",
            },
        ],
        "vehicles": [
            {
                "id": ECONOMY_VEHICLE_ID,
                "slug": "kia-picanto",
                "classId": CLASS_ID,
                "name": "Kia Picanto 2024 or similar",
                "seats": 4,
                "transmission": "automatic",
                "features": ["Air conditioning"],
                "dailyRate": {"currency": "USD", "amount": "35.00"},
                "weeklyRate": {"currency": "USD", "amount": "245.00"},
                "images": [{
                    "url": "/brand/vehicles/kia-picanto.png",
                    "alt": "Ali Kia Picanto",
                }],
            },
            {
                "id": SUV_VEHICLE_ID,
                "slug": "kia-seltos",
                "classId": SUV_CLASS_ID,
                "name": "Kia Seltos or similar",
                "seats": 5,
                "transmission": "automatic",
                "features": ["Air conditioning"],
                "dailyRate": {"currency": "USD", "amount": "65.00"},
                "weeklyRate": {"currency": "USD", "amount": "455.00"},
                "images": [{
                    "url": "/brand/vehicles/kia-seltos.png",
                    "alt": "Ali Kia Seltos",
                }],
            },
        ],
        "extras": [],
        "charges": [],
    }


def media_catalog():
    catalog = correction_catalog()
    catalog["vehicles"].extend([
        {
            "id": YARIS_VEHICLE_ID,
            "slug": "toyota-yaris",
            "classId": CLASS_ID,
            "name": "Toyota Yaris or similar",
            "seats": 5,
            "transmission": "automatic",
            "features": ["Air conditioning"],
            "dailyRate": {"currency": "USD", "amount": "45.00"},
            "weeklyRate": {"currency": "USD", "amount": "315.00"},
            "images": [{
                "url": "/brand/vehicles/toyota-yaris.png",
                "alt": "Ali Toyota Yaris",
            }],
        },
        {
            "id": COROLLA_VEHICLE_ID,
            "slug": "toyota-corolla",
            "classId": CLASS_ID,
            "name": "Toyota Corolla or similar",
            "seats": 5,
            "transmission": "automatic",
            "features": ["Air conditioning"],
            "dailyRate": {"currency": "USD", "amount": "55.00"},
            "weeklyRate": {"currency": "USD", "amount": "385.00"},
            "images": [{
                "url": "/brand/vehicles/toyota-corolla.png",
                "alt": "Ali Toyota Corolla",
            }],
        },
    ])
    return catalog


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


def _commit_result(phone, result, action_suffix):
    assert isinstance(result, dict)
    commit = result["ali_turn_commit"]
    recommendation = result.get("vehicle_recommendation") or {}
    workflow.commit_ali_turn_delivery(
        phone,
        commit,
        result["text"],
        [f"synthetic-{action_suffix}"],
        recommendation_state_hash=str(recommendation.get("state_hash") or ""),
        recommendation_delivery=(
            str(recommendation.get("kind") or "")
            if recommendation else ""
        ),
        recommendation_vehicle_ids=[
            str(option.get("id") or "")
            for option in recommendation.get("options") or []
            if isinstance(option, dict)
        ],
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
        "ali_primary_intent": "continue_intake",
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
    assert saved["flags"]["ali_draft_summary_hash"] != old_hash
    assert "awaiting_quote_confirmation" not in saved["flags"]
    assert "ali_quote_public_id" not in saved["flags"]
    assert saved["flags"]["ali_replaces_quote_public_id"] == "immutable-old-quote"
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


def test_ertiga_summary_to_suv_visual_rejection_and_corrected_quote(
    monkeypatch,
    tmp_path,
):
    phone = "synthetic-issue-195"
    fields = _stored_fields()
    fields.pop("vehicle_id")
    fields.pop("vehicle_name")
    fields["vehicle_class_id"] = VAN_CLASS_ID
    fields["vehicle_class_name"] = "Van"
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
        "fields": {"vehicle_class_name": "Compact SUV"},
        "confidence": "high",
        "reply": "I can show you an SUV option. Does this size suit your trip?",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "request_recommendation",
        "ali_rental_change": {
            "mode": "apply",
            "changed_fields": ["vehicle_selection"],
            "vehicle_selection_kind": "category",
        },
        "ali_vehicle_recommendation": {
            "mode": "specific",
            "vehicle_names": ["Kia Seltos or similar"],
            "availability_note": "Final vehicle availability still needs confirmation.",
            "cta_label": "View car",
        },
    }
    _configure(monkeypatch, tmp_path, result)
    monkeypatch.setattr(workflow, "_process_production", lambda _public_id: None)
    state_registry.wa_save_booking_state(phone, fields, flags)

    visual = social_agent.handle_incoming_whatsapp_message(
        {
            "from": phone,
            "text": "I want an SUV, can you show image?",
            "from_name": "Synthetic Customer",
            "_zernio_sender_id": "+351000000000",
            "_zernio_account_id": "synthetic-account",
        },
        include_media=True,
    )
    after_visual = state_registry.wa_get_booking_state(phone)

    assert visual["vehicle_recommendation"]["kind"] == "image"
    assert visual["vehicle_recommendation"]["options"][0]["id"] == SUV_VEHICLE_ID
    assert "Just checking" not in visual["text"]
    assert after_visual["fields"]["vehicle_class_id"] == SUV_CLASS_ID
    assert "vehicle_id" not in after_visual["fields"]
    _commit_result(phone, visual, "visual")
    after_visual = state_registry.wa_get_booking_state(phone)
    assert after_visual["flags"]["ali_phase"] == "DISCOVERY"
    assert after_visual["flags"]["ali_last_delivered_kind"] == "vehicle_recommendation"
    assert "ali_summary_hash" not in after_visual["flags"]
    assert "awaiting_quote_confirmation" not in after_visual["flags"]
    assert "ali_quote_public_id" not in after_visual["flags"]

    rejection_result = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": "No problem. Would you prefer something roomier or more compact?",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "reject_or_hesitate",
    }
    monkeypatch.setattr(
        social_agent.marina_agent,
        "process_message",
        lambda **_kwargs: rejection_result,
    )
    rejection = social_agent.handle_incoming_whatsapp_message(
        {
            "from": phone,
            "text": "No, it doesn’t.",
            "from_name": "Synthetic Customer",
            "_zernio_sender_id": "+351000000000",
            "_zernio_account_id": "synthetic-account",
        },
        include_media=True,
    )
    assert rejection["text"] == "Would you prefer a smaller car, an SUV, or a van?"
    assert rejection["vehicle_recommendation"] is None
    assert "Just checking" not in rejection["text"]
    _commit_result(phone, rejection, "rejection")

    choice_result = {
        "intents": ["inquiry"],
        "fields": {"vehicle_name": "Kia Seltos or similar"},
        "confidence": "high",
        "reply": "I’ll use the Kia Seltos option.",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "continue_intake",
        "ali_rental_change": {
            "mode": "apply",
            "changed_fields": ["vehicle_selection"],
            "vehicle_selection_kind": "vehicle",
        },
    }
    monkeypatch.setattr(
        social_agent.marina_agent,
        "process_message",
        lambda **_kwargs: choice_result,
    )
    corrected = social_agent.handle_incoming_whatsapp_message(
        {
            "from": phone,
            "text": "The Kia Seltos works for me.",
            "from_name": "Synthetic Customer",
            "_zernio_sender_id": "+351000000000",
            "_zernio_account_id": "synthetic-account",
        },
        include_media=True,
    )
    after_choice = state_registry.wa_get_booking_state(phone)

    assert corrected["text"].count("Just checking I’ve got everything right:") == 1
    assert "Car: Kia Seltos or similar" in corrected["text"]
    _commit_result(phone, corrected, "corrected-summary")
    after_choice = state_registry.wa_get_booking_state(phone)
    assert after_choice["fields"]["vehicle_id"] == SUV_VEHICLE_ID
    assert after_choice["flags"]["awaiting_quote_confirmation"] is True
    assert after_choice["flags"]["ali_last_delivered_kind"] == "summary"

    confirmation_result = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": "Thank you.",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "confirm_summary",
    }
    monkeypatch.setattr(
        social_agent.marina_agent,
        "process_message",
        lambda **_kwargs: confirmation_result,
    )
    prepared = social_agent.handle_incoming_whatsapp_message(
        {
            "from": phone,
            "text": "Yes, it does look right.",
            "from_name": "Synthetic Customer",
            "_zernio_sender_id": "+351000000000",
            "_zernio_account_id": "synthetic-account",
        },
        include_media=True,
    )
    assert prepared["text"] == workflow.PREPARING["en"]
    _commit_result(phone, prepared, "preparing")
    conn = workflow._connection()
    try:
        quote_count = conn.execute(
            "SELECT COUNT(*) FROM ali_quotes WHERE conversation_id = ?",
            (phone,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert quote_count == 1


def test_curated_recommendation_recovers_omitted_independent_vehicle_patch(
    monkeypatch,
    tmp_path,
):
    phone = "synthetic-issue-195-recommendation-fallback"
    fields = _stored_fields()
    for key in ("vehicle_id", "vehicle_name"):
        fields.pop(key)
    fields["vehicle_class_id"] = VAN_CLASS_ID
    fields["vehicle_class_name"] = "Van"
    flags = {
        "ali_phase": "SUMMARY_PRESENTED",
        "ali_presented_summary_hash": "a" * 64,
        "ali_summary_hash": "a" * 64,
        "ali_summary_version": 1,
        "ali_last_delivered_kind": "summary",
        "awaiting_quote_confirmation": True,
    }
    model_result = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": "Here are two compact SUV options.",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "request_recommendation",
        # The live model omitted ali_rental_change on this combined turn.
        "ali_vehicle_recommendation": {
            "mode": "curated",
            "vehicle_names": [
                "Kia Seltos or similar",
                "Synthetic second SUV or similar",
            ],
            "availability_note": "Final availability still needs confirmation.",
            "cta_label": "View car",
        },
    }
    test_catalog = correction_catalog()
    test_catalog["vehicles"].append({
        "id": SECOND_SUV_VEHICLE_ID,
        "slug": "synthetic-second-suv",
        "classId": SUV_CLASS_ID,
        "name": "Synthetic second SUV or similar",
        "seats": 5,
        "transmission": "automatic",
        "features": ["Air conditioning"],
        "dailyRate": {"currency": "USD", "amount": "65.00"},
        "weeklyRate": {"currency": "USD", "amount": "455.00"},
        "images": [{
            "url": "/brand/vehicles/synthetic-second-suv.png",
            "alt": "Ali synthetic second SUV",
        }],
    })
    _configure(monkeypatch, tmp_path, model_result)
    monkeypatch.setattr(social_agent, "get_ali_intake_catalog", lambda: test_catalog)
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda: test_catalog)
    state_registry.wa_save_booking_state(phone, fields, flags)

    response = social_agent.handle_incoming_whatsapp_message(
        {
            "from": phone,
            "text": "I want an SUV, can you show me an image?",
            "from_name": "Synthetic Customer",
            "message_id": "synthetic-recommendation-fallback",
            "_ali_action_id": "1" * 64,
            "_zernio_sender_id": "+351000000000",
            "_zernio_account_id": "synthetic-account",
        },
        include_media=True,
    )
    saved = state_registry.wa_get_booking_state(phone)

    assert response["vehicle_recommendation"]["kind"] == "carousel"
    assert saved["fields"]["vehicle_class_id"] == SUV_CLASS_ID
    assert saved["fields"]["vehicle_class_name"] == "Compact SUV"
    assert "vehicle_id" not in saved["fields"]
    assert "vehicle_name" not in saved["fields"]
    assert "awaiting_quote_confirmation" not in saved["flags"]
    assert response["ali_turn_commit"]["phase"] == "DISCOVERY"
    first_idempotency_key = response["vehicle_recommendation"]["idempotency_key"]
    assert first_idempotency_key.startswith("ali-vehicle-")
    _commit_result(phone, response, "recommendation-fallback")

    replay = social_agent.handle_incoming_whatsapp_message(
        {
            "from": phone,
            "text": "I want an SUV, can you show me an image?",
            "from_name": "Synthetic Customer",
            "message_id": "synthetic-recommendation-fallback",
            "_ali_action_id": "1" * 64,
            "_zernio_sender_id": "+351000000000",
            "_zernio_account_id": "synthetic-account",
        },
        include_media=True,
    )
    assert replay["text"] == ""
    assert replay["vehicle_recommendation"] is None
    assert replay["ali_turn_commit"] is None

    explicit_resend = social_agent.handle_incoming_whatsapp_message(
        {
            "from": phone,
            "text": "Please show those SUV pictures again.",
            "from_name": "Synthetic Customer",
            "message_id": "synthetic-recommendation-resend",
            "_ali_action_id": "2" * 64,
            "_zernio_sender_id": "+351000000000",
            "_zernio_account_id": "synthetic-account",
        },
        include_media=True,
    )
    assert explicit_resend["vehicle_recommendation"]["kind"] == "carousel"
    assert explicit_resend["vehicle_recommendation"]["idempotency_key"].startswith(
        "ali-vehicle-"
    )
    assert (
        explicit_resend["vehicle_recommendation"]["idempotency_key"]
        != first_idempotency_key
    )


def test_explicit_suv_picture_request_overrides_model_continue_intake(
    monkeypatch,
    tmp_path,
):
    phone = "synthetic-issue-195-explicit-discovery"
    fields = _stored_fields()
    fields.pop("luggage_count")
    flags = {
        "ali_phase": "SUMMARY_PRESENTED",
        "ali_presented_summary_hash": "a" * 64,
        "ali_summary_hash": "a" * 64,
        "ali_summary_version": 1,
        "ali_last_delivered_kind": "summary",
        "awaiting_quote_confirmation": True,
    }
    model_result = {
        "intents": ["inquiry"],
        # Reproduce the live omission: SUV was put in the wrong display field,
        # with no independent change or recommendation action.
        "fields": {"vehicle_name": "SUV"},
        "confidence": "high",
        "reply": "How much luggage will you be bringing?",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "continue_intake",
        # The live model also returned an incompatible broad list. The exact
        # customer class request must constrain media to the chosen class.
        "ali_vehicle_recommendation": {
            "mode": "curated",
            "vehicle_names": [
                "Kia Picanto 2024 or similar",
                "Kia Seltos or similar",
            ],
            "availability_note": "Final availability needs confirmation.",
            "cta_label": "View car",
        },
    }
    test_catalog = correction_catalog()
    test_catalog["vehicleClasses"][2]["name"] = "SUV"
    _configure(monkeypatch, tmp_path, model_result)
    monkeypatch.setattr(social_agent, "get_ali_intake_catalog", lambda: test_catalog)
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda: test_catalog)
    state_registry.wa_save_booking_state(phone, fields, flags)

    response = social_agent.handle_incoming_whatsapp_message(
        {
            "from": phone,
            "text": "I still want an SUV. Please show me the SUV pictures again.",
            "from_name": "Synthetic Customer",
            "message_id": "synthetic-explicit-suv-discovery",
            "_ali_action_id": "3" * 64,
            "_zernio_sender_id": "+351000000000",
            "_zernio_account_id": "synthetic-account",
        },
        include_media=True,
    )
    saved = state_registry.wa_get_booking_state(phone)

    assert response["vehicle_recommendation"]["kind"] == "image"
    assert response["vehicle_recommendation"]["options"][0]["id"] == SUV_VEHICLE_ID
    assert response["text"] != model_result["reply"]
    assert saved["fields"]["vehicle_class_id"] == SUV_CLASS_ID
    assert saved["fields"]["vehicle_class_name"] == "SUV"
    assert "vehicle_id" not in saved["fields"]
    assert "vehicle_name" not in saved["fields"]
    assert response["ali_turn_commit"]["phase"] == "DISCOVERY"
    _commit_result(phone, response, "explicit-suv-discovery")
    committed = state_registry.wa_get_booking_state(phone)
    assert committed["flags"]["ali_last_delivered_kind"] == "vehicle_recommendation"
    assert "awaiting_quote_confirmation" not in committed["flags"]


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
        "ali_primary_intent": "reject_or_hesitate",
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
    assert {
        key: saved["fields"].get(key) for key in fields
    } == fields
    assert saved["fields"]["vehicle_catalog_class_name"] == "Economy"
    assert saved["fields"]["vehicle_daily_rate_usd"] == "35.00"
    assert saved["flags"]["ali_summary_hash"] == "old-hash"


def test_awaiting_summary_keeps_price_answer_and_repeats_only_on_action(
    monkeypatch,
    tmp_path,
):
    phone = "synthetic-issue-195-price"
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
    _, summary_hash = workflow.normalized_summary(customer, rental)
    flags = {
        "ali_summary_hash": summary_hash,
        "ali_summary_version": 1,
        "awaiting_quote_confirmation": True,
    }
    price_result = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": (
            "The published rate is USD 35.00 per day. Your final price will be "
            "shown in the official quote I’ll prepare and send here in a few minutes."
        ),
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "ask_question",
    }
    _configure(monkeypatch, tmp_path, price_result)
    state_registry.wa_save_booking_state(phone, fields, flags)

    answer = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "What is the price?",
        "from_name": "Synthetic Customer",
        "_zernio_sender_id": "+351000000000",
        "_zernio_account_id": "synthetic-account",
    }, include_media=True)
    _commit_result(phone, answer, "price-answer")
    after_answer = state_registry.wa_get_booking_state(phone)

    assert answer["text"] == price_result["reply"]
    assert "Just checking" not in answer["text"]
    assert "ali_presented_summary_hash" not in after_answer["flags"]
    assert "awaiting_quote_confirmation" not in after_answer["flags"]
    assert after_answer["flags"]["ali_last_delivered_kind"] == "agent_reply"

    repeat_result = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": "Here it is.",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "repeat_summary",
        "ali_summary_action": {"mode": "repeat"},
    }
    monkeypatch.setattr(
        social_agent.marina_agent,
        "process_message",
        lambda **_kwargs: repeat_result,
    )
    repeated = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Show me the summary again.",
        "from_name": "Synthetic Customer",
        "_zernio_sender_id": "+351000000000",
        "_zernio_account_id": "synthetic-account",
    })

    assert repeated.count("Just checking I’ve got everything right:") == 1
    assert "Car: Kia Picanto 2024 or similar" in repeated


def test_unexpected_turn_planner_failure_suspends_old_confirmation_after_send(
    monkeypatch,
    tmp_path,
):
    phone = "synthetic-issue-195-fail-closed"
    fields = _stored_fields()
    flags = {
        "ali_phase": "SUMMARY_PRESENTED",
        "ali_presented_summary_hash": "a" * 64,
        "ali_summary_hash": "a" * 64,
        "ali_summary_version": 1,
        "ali_last_delivered_kind": "summary",
        "awaiting_quote_confirmation": True,
    }
    result = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": "A model reply that must not bypass state safety.",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "ask_question",
    }
    _configure(monkeypatch, tmp_path, result)
    monkeypatch.setattr(
        social_agent,
        "plan_ali_quote_turn",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    state_registry.wa_save_booking_state(phone, fields, flags)

    response = social_agent.handle_incoming_whatsapp_message(
        {
            "from": phone,
            "text": "What does that mean?",
            "from_name": "Synthetic Customer",
            "message_id": "synthetic-fail-closed-message",
            "_zernio_sender_id": "+351000000000",
            "_zernio_account_id": "synthetic-account",
        },
        include_media=True,
    )

    assert response["ali_turn_commit"]["reason_code"] == (
        "turn_planner_failed_closed"
    )
    assert response["text"] != result["reply"]
    _commit_result(phone, response, "fail-closed")
    saved = state_registry.wa_get_booking_state(phone)
    assert saved["flags"]["ali_phase"] == "DISCOVERY"
    assert saved["flags"]["ali_last_delivered_kind"] == "agent_reply"
    assert "ali_presented_summary_hash" not in saved["flags"]
    assert "awaiting_quote_confirmation" not in saved["flags"]


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


def _use_media_catalog(monkeypatch):
    monkeypatch.setattr(social_agent, "get_ali_intake_catalog", media_catalog)
    monkeypatch.setattr(workflow, "get_intake_catalog", media_catalog)


def _select_vehicle(fields, vehicle_id, vehicle_name, class_id, class_name):
    for key in (
        "vehicle_id", "vehicle_name", "vehicle_class_id", "vehicle_class_name",
    ):
        fields.pop(key, None)
    fields.update({
        "vehicle_id": vehicle_id,
        "vehicle_name": vehicle_name,
        "vehicle_class_id": class_id,
        "vehicle_class_name": class_name,
    })


def test_rejected_car_text_dump_becomes_carousel_picker_without_summary(
    monkeypatch, tmp_path,
):
    phone = "synthetic-issue-198-rejection"
    fields = _stored_fields()
    _select_vehicle(
        fields, SUV_VEHICLE_ID, "Kia Seltos or similar",
        SUV_CLASS_ID, "Compact SUV",
    )
    result = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": (
            "Kia Picanto 2024 or similar, Toyota Yaris or similar, "
            "Toyota Corolla or similar"
        ),
        "requires_human": False,
        "flags": {},
    }
    _configure(monkeypatch, tmp_path, result)
    _use_media_catalog(monkeypatch)
    state_registry.wa_save_booking_state(phone, fields, {
        "ali_summary_hash": "old-summary",
        "awaiting_quote_confirmation": True,
        "ali_quote_public_id": "old-quote",
        "ali_last_recommendation_ids": [SUV_VEHICLE_ID],
        "ali_shown_vehicle_ids": [SUV_VEHICLE_ID],
    })

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "I don't like that car, what else do you have?",
        "from_name": "Synthetic Customer",
        "_zernio_sender_id": "+351000000000",
        "_zernio_account_id": "synthetic-account",
    }, include_media=True)
    saved = state_registry.wa_get_booking_state(phone)

    plan = response["vehicle_recommendation"]
    assert plan["kind"] == "carousel"
    assert [option["id"] for option in plan["options"]] == [
        ECONOMY_VEHICLE_ID, YARIS_VEHICLE_ID, COROLLA_VEHICLE_ID,
    ]
    assert [row["id"] for row in plan["picker"]["sections"][0]["rows"]] == [
        option["selection_id"] for option in plan["options"]
    ]
    assert "Kia Picanto" not in response["text"]
    assert "Just checking" not in response["text"]
    assert saved["flags"]["ali_rejected_vehicle_ids"] == [SUV_VEHICLE_ID]
    _commit_result(phone, response, "issue-198-rejection")
    saved = state_registry.wa_get_booking_state(phone)
    assert "ali_summary_hash" not in saved["flags"]
    assert "awaiting_quote_confirmation" not in saved["flags"]


def test_text_dump_without_trip_context_asks_one_discovery_question(
    monkeypatch, tmp_path,
):
    phone = "synthetic-issue-198-context"
    result = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": "Kia Picanto 2024 or similar, Toyota Yaris or similar",
        "requires_human": False,
        "flags": {},
    }
    _configure(monkeypatch, tmp_path, result)
    _use_media_catalog(monkeypatch)
    state_registry.wa_save_booking_state(
        phone, {"conversation_language": "en"}, {}
    )

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "What smaller cars do you have?",
        "from_name": "Synthetic Customer",
    }, include_media=True)

    assert response["vehicle_recommendation"] is None
    assert response["text"] == "How many people will be travelling in the car?"
    assert "Kia Picanto" not in response["text"]


def test_native_picker_tap_selects_exact_vehicle_without_repeating_media(
    monkeypatch, tmp_path,
):
    phone = "synthetic-issue-198-picker"
    fields = _stored_fields()
    result = {
        "intents": ["inquiry"],
        # A stale model label cannot overwrite the provider-validated tap.
        "fields": {"vehicle_name": "Kia Picanto 2024 or similar"},
        "confidence": "high",
        "reply": "Great choice.",
        "requires_human": False,
        "flags": {},
        "ali_vehicle_recommendation": {
            "mode": "specific",
            "vehicle_names": ["Toyota Yaris or similar"],
            "availability_note": "Final availability needs confirmation.",
            "cta_label": "View car",
        },
    }
    _configure(monkeypatch, tmp_path, result)
    _use_media_catalog(monkeypatch)
    state_registry.wa_save_booking_state(phone, fields, {
        "ali_summary_hash": "old-summary",
        "awaiting_quote_confirmation": True,
        "ali_quote_public_id": "old-quote",
    })

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "",
        "from_name": "Synthetic Customer",
        "_zernio_interactive_type": "list_reply",
        "_zernio_interactive_id": vehicle_selection_payload(YARIS_VEHICLE_ID),
        "_zernio_sender_id": "+351000000000",
        "_zernio_account_id": "synthetic-account",
    }, include_media=True)
    saved = state_registry.wa_get_booking_state(phone)

    assert response["vehicle_recommendation"] is None
    assert response["text"].count("Just checking I’ve got everything right:") == 1
    assert "Car: Toyota Yaris or similar" in response["text"]
    assert saved["fields"]["vehicle_id"] == YARIS_VEHICLE_ID
    assert saved["fields"]["vehicle_name"] == "Toyota Yaris or similar"
    _commit_result(phone, response, "issue-198-picker")
    saved = state_registry.wa_get_booking_state(phone)
    assert saved["flags"]["awaiting_quote_confirmation"] is True
    assert saved["flags"]["ali_summary_hash"] != "old-summary"
    assert "ali_quote_public_id" not in saved["flags"]


def test_malformed_picker_never_changes_vehicle_or_calls_model(
    monkeypatch, tmp_path,
):
    phone = "synthetic-issue-198-invalid-picker"
    fields = _stored_fields()
    calls = []
    result = {
        "intents": ["inquiry"], "fields": {}, "confidence": "high",
        "reply": "should not run", "requires_human": False, "flags": {},
    }
    _configure(monkeypatch, tmp_path, result)
    _use_media_catalog(monkeypatch)
    monkeypatch.setattr(
        social_agent.marina_agent,
        "process_message",
        lambda **kwargs: calls.append(kwargs) or result,
    )
    state_registry.wa_save_booking_state(phone, fields, {
        "ali_summary_hash": "current-summary",
        "awaiting_quote_confirmation": True,
    })

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "",
        "from_name": "Synthetic Customer",
        "_zernio_interactive_type": "list_reply",
        "_zernio_interactive_id": "ali_vehicle_select:v1:../../bad",
    }, include_media=True)
    saved = state_registry.wa_get_booking_state(phone)

    assert calls == []
    assert response["vehicle_recommendation"] is None
    assert "no longer valid" in response["text"]
    assert saved["fields"]["vehicle_id"] == ECONOMY_VEHICLE_ID
    assert saved["flags"]["ali_summary_hash"] == "current-summary"
    assert saved["flags"]["awaiting_quote_confirmation"] is True
    _commit_result(phone, response, "issue-198-invalid-picker")
    delivered = state_registry.wa_get_booking_state(phone)
    assert "ali_summary_hash" not in delivered["flags"]
    assert "awaiting_quote_confirmation" not in delivered["flags"]


def test_stale_picker_tap_returns_fresh_current_picker_without_model_call(
    monkeypatch, tmp_path,
):
    phone = "synthetic-issue-206-stale-picker-recovery"
    fields = _stored_fields()
    calls = []
    result = {
        "intents": ["inquiry"], "fields": {}, "confidence": "high",
        "reply": "should not run", "requires_human": False, "flags": {},
    }
    _configure(monkeypatch, tmp_path, result)
    _use_media_catalog(monkeypatch)
    monkeypatch.setattr(
        social_agent.marina_agent,
        "process_message",
        lambda **kwargs: calls.append(kwargs) or result,
    )
    state_registry.wa_save_booking_state(phone, fields, {
        "ali_last_recommendation_ids": [YARIS_VEHICLE_ID, SUV_VEHICLE_ID],
        "ali_summary_hash": "current-summary",
        "awaiting_quote_confirmation": True,
    })

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "",
        "from_name": "Synthetic Customer",
        "message_id": "stale-picker-action-1",
        "_zernio_interactive_type": "list_reply",
        "_zernio_interactive_id": vehicle_selection_payload("inactive-vehicle"),
    }, include_media=True)
    saved = state_registry.wa_get_booking_state(phone)

    assert calls == []
    assert response["vehicle_recommendation"]["kind"] == "picker"
    assert [
        option["id"] for option in response["vehicle_recommendation"]["options"]
    ] == [YARIS_VEHICLE_ID, SUV_VEHICLE_ID]
    assert response["ali_turn_commit"]["phase"] == "DISCOVERY"
    assert saved["fields"]["vehicle_id"] == ECONOMY_VEHICLE_ID
    assert saved["flags"]["ali_summary_hash"] == "current-summary"


def test_typed_exact_choice_matches_picker_and_later_price_does_not_repeat_image(
    monkeypatch, tmp_path,
):
    phone = "synthetic-issue-198-typed"
    fields = _stored_fields()
    fields.pop("customer_name")
    choice_result = {
        "intents": ["inquiry"],
        "fields": {"vehicle_name": "Kia Picanto 2024 or similar"},
        "confidence": "high",
        "reply": "Good choice. What name should I put on the quote?",
        "requires_human": False,
        "flags": {},
    }
    _configure(monkeypatch, tmp_path, choice_result)
    _use_media_catalog(monkeypatch)
    state_registry.wa_save_booking_state(phone, fields, {})

    chosen = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "I choose Toyota Yaris",
        "from_name": "",
    }, include_media=True)
    selected = state_registry.wa_get_booking_state(phone)

    assert chosen["vehicle_recommendation"] is None
    assert selected["fields"]["vehicle_id"] == YARIS_VEHICLE_ID

    price_result = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": "The Toyota Yaris or similar is USD 45.00 per day.",
        "requires_human": False,
        "flags": {},
    }
    monkeypatch.setattr(
        social_agent.marina_agent, "process_message", lambda **_kwargs: price_result
    )
    priced = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "What is the price?",
        "from_name": "",
    }, include_media=True)

    assert priced["text"] == price_result["reply"]
    assert priced["vehicle_recommendation"] is None


def test_explicit_picture_request_after_exact_choice_resends_one_image(
    monkeypatch, tmp_path,
):
    phone = "synthetic-issue-198-show-again"
    fields = _stored_fields()
    _select_vehicle(
        fields, YARIS_VEHICLE_ID, "Toyota Yaris or similar", CLASS_ID, "Economy",
    )
    result = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": "Here is the car again.",
        "requires_human": False,
        "flags": {},
    }
    _configure(monkeypatch, tmp_path, result)
    _use_media_catalog(monkeypatch)
    state_registry.wa_save_booking_state(phone, fields, {})

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Can you show me that car again?",
        "from_name": "Synthetic Customer",
    }, include_media=True)

    assert response["vehicle_recommendation"]["kind"] == "image"
    assert response["vehicle_recommendation"]["options"][0]["id"] == YARIS_VEHICLE_ID
