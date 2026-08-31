from datetime import datetime, timedelta, timezone
import hashlib
import json

from agents.social import ali_quote_workflow as workflow
from agents.social import social_agent
from agents.social import zernio_dm_client
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
VAN_VEHICLE_ID = "40000000-0000-4000-8000-000000000007"


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


def child_seat_catalog():
    catalog = correction_catalog()
    catalog["extras"] = [{
        "id": "c5b7e180-5eaa-4f5d-8a41-180000000001",
        "name": "Child seat",
        "names": {
            "en": "Child seat", "nl": "Kinderzitje",
            "pap": "Stul pa mucha", "de": "Kindersitz",
        },
        "active": True,
        "billingBasis": "per_day",
        "price": {"currency": "USD", "amount": "5.00"},
    }]
    return catalog


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


def media_catalog_with_van():
    catalog = media_catalog()
    catalog["vehicles"].append({
        "id": VAN_VEHICLE_ID,
        "slug": "suzuki-ertiga",
        "classId": VAN_CLASS_ID,
        "name": "Suzuki Ertiga",
        "seats": 7,
        "transmission": "automatic",
        "features": ["Air conditioning"],
        "dailyRate": {"currency": "USD", "amount": "75.00"},
        "weeklyRate": {"currency": "USD", "amount": "525.00"},
        "images": [{
            "url": "/brand/vehicles/suzuki-ertiga.png",
            "alt": "Ali Suzuki Ertiga",
        }],
    })
    return catalog


def pickup_catalog():
    catalog = correction_catalog()
    catalog["pickupLocations"] = [{
        "id": "airport",
        "name": "Airport",
        "kind": "fixed",
        "active": True,
        "displayOrder": 10,
    }, {
        "id": "ali-office",
        "name": "Ali office",
        "kind": "fixed",
        "active": True,
        "displayOrder": 20,
    }, {
        "id": "hotel-delivery",
        "name": "Hotel delivery",
        "kind": "hotel_delivery",
        "requiresName": True,
        "requiresAddress": True,
        "active": True,
        "displayOrder": 30,
    }]
    catalog["returnLocations"] = []
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
    monkeypatch.setenv(
        "ALI_QUOTE_CONFIRMATION_SECRET",
        "synthetic-confirmation-secret-32-bytes",
    )
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


def test_send_my_quote_tap_bypasses_model_and_duplicate_tap_creates_one_quote(
    monkeypatch,
    tmp_path,
):
    phone = "synthetic-send-my-quote"
    fields = _stored_fields()
    _configure(monkeypatch, tmp_path, {})
    monkeypatch.setenv(
        "ALI_QUOTE_CONFIRMATION_SECRET",
        "synthetic-confirmation-secret-32-bytes",
    )
    monkeypatch.setattr(
        social_agent.marina_agent,
        "process_message",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("structured quote tap must bypass the model")
        ),
    )
    monkeypatch.setattr(workflow, "_process_production", lambda _public_id: None)

    flags = {}
    state_registry.wa_save_booking_state(phone, fields, flags)
    summary_plan = workflow.plan_ali_quote_turn(
        phone,
        "synthetic-account",
        "+351000000000",
        "complete details",
        fields,
        flags,
        "Thanks.",
        raw_config=raw_config(),
        primary_intent="continue_intake",
        supplied_action_id="a" * 64,
    )
    state_registry.wa_save_booking_state(phone, fields, flags)
    control = workflow.build_quote_confirmation_control(phone, summary_plan)
    workflow.commit_ali_turn_delivery(
        phone,
        summary_plan.delivery_commit(),
        summary_plan.text,
        ["summary-inbound"],
        confirmation_delivery="interactive",
        confirmation_payload=control["button"]["payload"],
        confirmation_provider_message_ids=["provider-summary-1"],
    )

    tap = {
        "from": phone,
        "text": "Send My Quote",
        "from_name": "Synthetic Customer",
        "message_id": "quote-tap-1",
        "_zernio_sender_id": "+351000000000",
        "_zernio_account_id": "synthetic-account",
        "_zernio_interactive_type": "button_reply",
        "_zernio_interactive_id": control["button"]["payload"],
    }
    first = social_agent.handle_incoming_whatsapp_message(
        tap, include_media=True,
    )
    assert first["ali_turn_commit"]["outbound_kind"] == "quote_preparing"
    assert first["text"] == workflow.PREPARING["en"]
    workflow.commit_ali_turn_delivery(
        phone,
        first["ali_turn_commit"],
        first["text"],
        ["quote-tap-1"],
    )

    tap["message_id"] = "quote-tap-2"
    repeated = social_agent.handle_incoming_whatsapp_message(
        tap, include_media=True,
    )
    assert repeated["text"] == workflow.QUOTE_ALREADY_PROCESSING["en"]
    workflow.ensure_schema()
    connection = workflow._connection()
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM ali_quotes WHERE conversation_id = ?",
            (phone,),
        ).fetchone()[0]
    finally:
        connection.close()
    assert count == 1


def test_change_something_tap_is_localized_preserves_details_and_closes_summary(
    monkeypatch,
    tmp_path,
):
    _configure(monkeypatch, tmp_path, {})
    monkeypatch.setattr(
        social_agent.marina_agent,
        "process_message",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("structured change tap must bypass the model")
        ),
    )
    expected = {
        "en": (["Send My Quote", "Change Something"], "Of course—what would you like to change?"),
        "nl": (["Stuur Mijn Offerte", "Iets Wijzigen"], "Natuurlijk—wat wil je wijzigen?"),
        "pap": (["Manda Mi Oferta", "Kambia Algu"], "Sigur—kiko bo ke kambia?"),
        "de": (["Angebot Senden", "Etwas Ändern"], "Natürlich—was möchten Sie ändern?"),
    }

    for index, (locale, (titles, prompt)) in enumerate(expected.items(), 1):
        phone = f"synthetic-change-summary-{locale}"
        fields = _stored_fields(locale)
        original_fields = dict(fields)
        flags = {}
        state_registry.wa_save_booking_state(phone, fields, flags)
        summary_plan = workflow.plan_ali_quote_turn(
            phone,
            "synthetic-account",
            "+351000000000",
            "complete details",
            fields,
            flags,
            "Thanks.",
            raw_config=raw_config(),
            primary_intent="continue_intake",
            supplied_action_id=f"{index:064x}",
        )
        state_registry.wa_save_booking_state(phone, fields, flags)
        control = workflow.build_quote_confirmation_control(
            phone, summary_plan, locale=locale,
        )
        assert [button["title"] for button in control["buttons"]] == titles
        workflow.commit_ali_turn_delivery(
            phone,
            summary_plan.delivery_commit(),
            summary_plan.text,
            [f"summary-{locale}"],
            confirmation_delivery="interactive",
            confirmation_payload=control["button"]["payload"],
            confirmation_provider_message_ids=[f"provider-summary-{locale}"],
        )

        result = social_agent.handle_incoming_whatsapp_message({
            "from": phone,
            "text": titles[1],
            "from_name": "Synthetic Customer",
            "message_id": f"change-tap-{locale}",
            "_zernio_sender_id": "+351000000000",
            "_zernio_account_id": "synthetic-account",
            "_zernio_interactive_type": "button_reply",
            "_zernio_interactive_id": control["buttons"][1]["payload"],
        }, include_media=True)

        assert result["text"] == prompt
        assert result["quote_confirmation"] is None
        assert result["ali_turn_commit"]["outbound_kind"] == "agent_reply"
        assert result["ali_turn_commit"]["phase"] == "DISCOVERY"
        workflow.commit_ali_turn_delivery(
            phone,
            result["ali_turn_commit"],
            result["text"],
            [f"change-tap-{locale}"],
        )
        saved = state_registry.wa_get_booking_state(phone)
        assert {
            key: saved["fields"].get(key)
            for key in original_fields
        } == original_fields
        assert saved["flags"]["ali_phase"] == "DISCOVERY"
        assert "awaiting_quote_confirmation" not in saved["flags"]
        assert "ali_presented_summary_hash" not in saved["flags"]


def test_toddler_cue_prioritizes_catalog_priced_child_seat_question(
    monkeypatch,
    tmp_path,
):
    phone = "synthetic-proactive-child-seat"
    fields = {
        "vehicle_class_name": "Compact SUV",
        "conversation_language": "en",
    }
    result = {
        "intents": ["inquiry"],
        "fields": {
            "vehicle_class_name": "Compact SUV",
            "passenger_count": 4,
            "conversation_language": "en",
        },
        "confidence": "high",
        "reply": "How much luggage will you be bringing?",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "continue_intake",
    }
    _configure(monkeypatch, tmp_path, result)
    monkeypatch.setattr(
        social_agent, "get_ali_intake_catalog", child_seat_catalog,
    )
    monkeypatch.setattr(workflow, "get_intake_catalog", child_seat_catalog)
    state_registry.wa_save_booking_state(phone, fields, {})

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "4 in total: 3 adults and 1 toddler",
        "from_name": "Synthetic Customer",
        "message_id": "child-cue-1",
        "_zernio_sender_id": "+351000000000",
        "_zernio_account_id": "synthetic-account",
    }, include_media=True)
    saved = state_registry.wa_get_booking_state(phone)

    assert response["text"] == (
        "You mentioned a child. Will you bring your own child seat, or would "
        "you like to rent one for USD 5.00 per rental day?"
    )
    assert response["vehicle_recommendation"] is None
    assert response["quote_confirmation"] is None
    assert response["ali_turn_commit"]["outbound_kind"] == "agent_reply"
    assert saved["fields"]["passenger_count"] == 4
    assert saved["flags"]["ali_child_seat_prompted"] is True


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

    assert reply.count("I have these details from you:") == 1
    assert "Car: Van" in reply
    assert "Kia Picanto" not in reply
    assert saved["fields"]["vehicle_class_id"] == VAN_CLASS_ID
    assert "vehicle_id" not in saved["fields"]
    assert saved["flags"]["ali_draft_summary_hash"] != old_hash
    assert "awaiting_quote_confirmation" not in saved["flags"]
    assert "ali_quote_public_id" not in saved["flags"]
    assert saved["flags"]["ali_replaces_quote_public_id"] == "immutable-old-quote"
    assert saved["fields"]["return_location"] == "Synthetic hotel"

    correction_text = "No, that doesn’t look right, I want a van"
    workflow.commit_ali_turn_delivery(
        phone,
        {
            "outbound_kind": "summary",
            "phase": "SUMMARY_PRESENTED",
            "primary_intent": "continue_intake",
            "reason_code": "initial_or_corrected_complete_draft",
            "action_id": hashlib.sha256(
                f"{phone}\x1f{correction_text}".encode("utf-8")
            ).hexdigest(),
            "draft_hash": saved["flags"]["ali_draft_hash"],
            "summary_hash": saved["flags"]["ali_draft_summary_hash"],
            "summary_version": saved["flags"]["ali_draft_version"],
            "quote_public_id": "",
        },
        reply,
        [],
    )

    second = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": correction_text,
        "from_name": "Synthetic Customer",
        "_zernio_sender_id": "+351000000000",
        "_zernio_account_id": "synthetic-account",
    })
    assert "I have these details from you:" not in second
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
    assert "I have these details from you:" not in visual["text"]
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
    assert "I have these details from you:" not in rejection["text"]
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

    assert corrected["text"].count("I have these details from you:") == 1
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
        "ali_vehicle_recommendation": {
            "mode": "specific",
            "vehicle_names": ["Kia Seltos or similar"],
            "availability_note": "Synthetic note",
            "cta_label": "Car Details",
        },
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


def test_incomplete_discovery_builds_carousel_before_personal_details(
    monkeypatch,
    tmp_path,
):
    phone = "synthetic-issue-208-incomplete-media"
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
    model_result = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": "Here are two options that suit your trip.",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "request_recommendation",
        "ali_vehicle_recommendation": {
            "mode": "curated",
            "vehicle_names": [
                "Toyota Yaris or similar",
                "Kia Seltos or similar",
            ],
            "availability_note": "Final availability still needs confirmation.",
            "cta_label": "View car",
        },
    }
    test_catalog = media_catalog()
    _configure(monkeypatch, tmp_path, model_result)
    monkeypatch.setattr(social_agent, "get_ali_intake_catalog", lambda: test_catalog)
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda: test_catalog)
    state_registry.wa_save_booking_state(phone, fields, {})

    response = social_agent.handle_incoming_whatsapp_message(
        {
            "from": phone,
            "text": "I want to change the car for another one",
            "from_name": "",
            "message_id": "synthetic-incomplete-recommendation",
            "_ali_action_id": "a" * 64,
            "_zernio_sender_id": "+351000000000",
            "_zernio_account_id": "synthetic-account",
        },
        include_media=True,
    )
    saved = state_registry.wa_get_booking_state(phone)
    recommendation = response["vehicle_recommendation"]

    assert recommendation["kind"] == "carousel"
    assert [option["id"] for option in recommendation["options"]] == [
        YARIS_VEHICLE_ID,
        SUV_VEHICLE_ID,
    ]
    assert [
        row["id"]
        for row in recommendation["picker"]["sections"][0]["rows"]
    ] == [
        vehicle_selection_payload(YARIS_VEHICLE_ID),
        vehicle_selection_payload(SUV_VEHICLE_ID),
    ]
    assert response["ali_turn_commit"]["phase"] == "DISCOVERY"
    assert response["ali_turn_commit"]["draft_hash"] == ""
    assert "awaiting_quote_confirmation" not in saved["flags"]
    assert "ali_summary_hash" not in saved["flags"]


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


def test_bare_small_car_proposes_car_but_never_assumes_it_or_repeats_on_repair(
    monkeypatch,
    tmp_path,
):
    phone = "synthetic-small-car-repair"
    test_catalog = correction_catalog()
    test_catalog["vehicleClasses"][0]["name"] = "Small Car"
    test_catalog["vehicles"][0]["name"] = "Toyota Agya"
    model_result = {
        "intents": ["inquiry"],
        # Reproduce the live model error: it promotes a category reply into
        # the category's only exact vehicle and repeats that assumption.
        "fields": {"vehicle_name": "Toyota Agya", "conversation_language": "en"},
        "confidence": "high",
        "reply": "Here is the Toyota Agya. What dates do you need?",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "request_recommendation",
        "ali_rental_change": {
            "mode": "apply",
            "changed_fields": ["vehicle_selection"],
            "vehicle_selection_kind": "vehicle",
        },
        "ali_vehicle_recommendation": {
            "mode": "specific",
            "vehicle_names": ["Toyota Agya"],
            "availability_note": "Final availability needs confirmation.",
            "cta_label": "Car Details",
        },
    }
    _configure(monkeypatch, tmp_path, model_result)
    monkeypatch.setattr(social_agent, "get_ali_intake_catalog", lambda: test_catalog)
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda: test_catalog)
    state_registry.wa_save_booking_state(
        phone, {"conversation_language": "en", "supplements": []}, {},
    )

    proposed = social_agent.handle_incoming_whatsapp_message(
        {
            "from": phone,
            "text": "Small Car",
            "from_name": "Synthetic Customer",
            "message_id": "synthetic-small-car",
            "_ali_action_id": "4" * 64,
            "_zernio_sender_id": "+351000000000",
            "_zernio_account_id": "synthetic-account",
        },
        include_media=True,
    )
    proposed_state = state_registry.wa_get_booking_state(phone)

    assert proposed["vehicle_recommendation"]["kind"] == "image"
    assert proposed["vehicle_recommendation"]["options"][0]["name"] == "Toyota Agya"
    assert proposed["text"].startswith(
        "Here is a car that matches what you asked for."
    )
    assert "What dates" not in proposed["text"]
    assert proposed_state["fields"]["vehicle_class_name"] == "Small Car"
    assert "vehicle_id" not in proposed_state["fields"]
    assert "vehicle_name" not in proposed_state["fields"]

    for text, action_id in (("Hello", "5" * 64), ("???", "6" * 64)):
        repaired = social_agent.handle_incoming_whatsapp_message(
            {
                "from": phone,
                "text": text,
                "from_name": "Synthetic Customer",
                "message_id": f"synthetic-repair-{action_id[0]}",
                "_ali_action_id": action_id,
                "_zernio_sender_id": "+351000000000",
                "_zernio_account_id": "synthetic-account",
            },
            include_media=True,
        )
        repaired_state = state_registry.wa_get_booking_state(phone)
        assert not repaired.get("vehicle_recommendation")
        assert "Small Car" in repaired["text"]
        assert "Toyota Agya" not in repaired["text"]
        assert repaired_state["fields"]["vehicle_class_name"] == "Small Car"
        assert "vehicle_id" not in repaired_state["fields"]
        assert "vehicle_name" not in repaired_state["fields"]


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
    assert "I have these details from you:" not in reply
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
        "ali_phase": "SUMMARY_PRESENTED",
        "ali_presented_summary_hash": summary_hash,
        "ali_summary_hash": summary_hash,
        "ali_summary_version": 1,
        "ali_draft_hash": workflow.normalized_summary(
            customer, rental, version=0,
        )[1],
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
    assert "I have these details from you:" not in answer["text"]
    assert after_answer["flags"]["ali_phase"] == "SUMMARY_PRESENTED"
    assert after_answer["flags"]["ali_presented_summary_hash"] == summary_hash
    assert after_answer["flags"]["awaiting_quote_confirmation"] is True
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

    assert repeated.count("I have these details from you:") == 1
    assert "Car: Kia Picanto 2024 or similar" in repeated


def test_pure_affirmative_ignores_model_quote_field_drift_and_creates_one_quote(
    monkeypatch,
    tmp_path,
):
    phone = "synthetic-issue-212-field-freeze"
    fields = _stored_fields()
    result = {
        "intents": ["inquiry"],
        "fields": {
            **fields,
            "return_location": "Incorrect model-only return",
            "driver_age": 99,
        },
        "confidence": "high",
        "reply": "Perfect, your quote is on its way.",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "confirm_summary",
    }
    _configure(monkeypatch, tmp_path, result)
    monkeypatch.setattr(workflow, "_process_production", lambda _public_id: None)
    state_registry.wa_save_booking_state(phone, fields, {})

    initial = workflow.plan_ali_quote_turn(
        phone, "synthetic-account", "+351000000000", "complete details",
        fields, {}, "Thanks.", raw_config=raw_config(),
        primary_intent="continue_intake", supplied_action_id="a" * 64,
    )
    state_registry.wa_save_booking_state(phone, fields, {})
    workflow.commit_ali_turn_delivery(
        phone, initial.delivery_commit(), initial.text, ["issue-212-summary"],
    )

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Yes, it looks good",
        "from_name": "Synthetic Customer",
        "message_id": "issue-212-confirmation",
        "_zernio_sender_id": "+351000000000",
        "_zernio_account_id": "synthetic-account",
    }, include_media=True)
    saved = state_registry.wa_get_booking_state(phone)

    assert response["ali_turn_commit"]["outbound_kind"] == "quote_preparing"
    assert saved["fields"]["return_location"] == "Synthetic hotel"
    assert saved["fields"]["driver_age"] == 30
    workflow.ensure_schema()
    connection = workflow._connection()
    try:
        rows = connection.execute(
            "SELECT summary_hash FROM ali_quotes WHERE conversation_id = ?",
            (phone,),
        ).fetchall()
    finally:
        connection.close()
    assert [row[0] for row in rows] == [initial.summary_hash]


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


def test_relative_post_quote_extensions_are_catalog_state_changes_in_all_locales():
    cases = {
        "en": "15 days more, we decided to stay longer",
        "nl": "15 dagen langer, we hebben besloten langer te blijven",
        "pap": "15 dia mas, nos a disidí keda mas largu",
        "de": "15 Tage länger, wir haben beschlossen länger zu bleiben",
    }
    for locale, phrase in cases.items():
        fields = _stored_fields(locale)
        fields["rental_start"] = "2026-08-30"
        fields["rental_end"] = "2026-09-14"
        assert workflow.infer_relative_rental_end_change(
            phrase,
            fields,
            change_requested=True,
        ) == "2026-09-29"


def test_relative_extension_fails_closed_without_context_or_with_uncertainty():
    fields = _stored_fields("en")
    fields["rental_start"] = "2026-08-30"
    fields["rental_end"] = "2026-09-14"
    assert workflow.infer_relative_rental_end_change(
        "15 days more, we decided to stay longer",
        fields,
        change_requested=False,
    ) is None
    assert workflow.infer_relative_rental_end_change(
        "Could we maybe stay 15 days more?",
        fields,
        change_requested=True,
    ) is None
    assert workflow.infer_relative_rental_end_change(
        "Not 15 days more",
        fields,
        change_requested=True,
    ) is None


def test_live_relative_extension_sequence_creates_one_immutable_replacement_quote(
    monkeypatch,
    tmp_path,
):
    phone = "synthetic-relative-replacement"
    fields = _stored_fields("en")
    fields["rental_start"] = "2026-08-30"
    fields["rental_end"] = "2026-09-14"
    customer = {
        "name": fields["customer_name"],
        "whatsapp": "+351000000000",
    }
    model_result = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": (
            "Nice! So 15 extra days on top of 14 September would put the "
            "return on 29 September—is that right?"
        ),
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "ask_question",
        "ali_rental_change": {"mode": "clarify", "changed_fields": []},
    }
    _configure(monkeypatch, tmp_path, model_result)
    rental = {
        key: fields.get(key)
        for key in (
            "rental_start", "rental_end", "pickup_location", "return_location",
            "vehicle_id", "vehicle_name", "vehicle_class_id", "vehicle_class_name",
            "driver_age", "passenger_count", "luggage_count", "supplements",
            "comments", "conversation_language",
        )
    }
    _, old_summary_hash = workflow.normalized_summary(customer, rental, version=1)
    old_quote, created = workflow.create_confirmed_quote(
        phone,
        "synthetic-account",
        customer,
        rental,
        old_summary_hash,
        "yes",
        raw_config()["workflow"]["required_deposit_charge_id"],
        summary_version=1,
        raw_config=raw_config(),
    )
    assert created is True
    workflow.update_quote(
        old_quote["public_id"],
        status="complete",
        quote_reference="ALI-SYNTHETIC-OLD",
        whatsapp_status="accepted",
    )
    _, old_state_hash = workflow.normalized_summary(customer, rental, version=0)
    flags = {
        "ali_phase": "QUOTED",
        "ali_draft_hash": old_state_hash,
        "ali_draft_summary_hash": old_summary_hash,
        "ali_draft_version": 1,
        "ali_active_quote_public_id": old_quote["public_id"],
        "ali_quote_public_id": old_quote["public_id"],
        "ali_post_quote_change_requested": {
            "quote_public_id": old_quote["public_id"],
            "requested_at": "2026-08-28T13:47:10Z",
        },
    }
    monkeypatch.setattr(workflow, "_process_production", lambda _public_id: None)
    state_registry.wa_save_booking_state(phone, fields, flags)

    corrected = social_agent.handle_incoming_whatsapp_message(
        {
            "from": phone,
            "text": "15 days more, we decided to stay longer",
            "from_name": "Synthetic Customer",
            "message_id": "relative-change-1",
            "_zernio_sender_id": "+351000000000",
            "_zernio_account_id": "synthetic-account",
        },
        include_media=True,
    )
    saved = state_registry.wa_get_booking_state(phone)

    assert corrected["ali_turn_commit"]["outbound_kind"] == "summary"
    assert "30 August 2026 – 29 September 2026" in corrected["text"]
    assert "14 September 2026" not in corrected["text"]
    assert saved["fields"]["rental_end"] == "2026-09-29"
    assert "ali_post_quote_change_requested" not in saved["flags"]
    assert saved["flags"]["ali_replaces_quote_public_id"] == old_quote["public_id"]

    corrected_commit = corrected["ali_turn_commit"]
    corrected_plan = workflow.AliTurnPlan(
        outbound_kind=corrected_commit["outbound_kind"],
        text=corrected["text"],
        phase=corrected_commit["phase"],
        primary_intent=corrected_commit["primary_intent"],
        reason_code=corrected_commit["reason_code"],
        action_id=corrected_commit["action_id"],
        draft_hash=corrected_commit["draft_hash"],
        summary_hash=corrected_commit["summary_hash"],
        summary_version=corrected_commit["summary_version"],
        quote_public_id=corrected_commit["quote_public_id"],
    )
    control = workflow.build_quote_confirmation_control(phone, corrected_plan)
    workflow.commit_ali_turn_delivery(
        phone,
        corrected["ali_turn_commit"],
        corrected["text"],
        ["relative-summary-inbound"],
        confirmation_delivery="interactive",
        confirmation_payload=control["button"]["payload"],
        confirmation_provider_message_ids=["relative-summary-provider"],
    )
    tap = social_agent.handle_incoming_whatsapp_message(
        {
            "from": phone,
            "text": "Send My Quote",
            "from_name": "Synthetic Customer",
            "message_id": "relative-quote-tap",
            "_zernio_sender_id": "+351000000000",
            "_zernio_account_id": "synthetic-account",
            "_zernio_interactive_type": "button_reply",
            "_zernio_interactive_id": control["button"]["payload"],
        },
        include_media=True,
    )

    assert tap["ali_turn_commit"]["outbound_kind"] == "quote_preparing"
    connection = workflow._connection()
    try:
        rows = connection.execute(
            "SELECT public_id, rental_json FROM ali_quotes "
            "WHERE conversation_id = ? ORDER BY id",
            (phone,),
        ).fetchall()
    finally:
        connection.close()
    assert len(rows) == 2
    assert rows[0]["public_id"] == old_quote["public_id"]
    assert json.loads(rows[0]["rental_json"])["rental_end"] == "2026-09-14"
    assert json.loads(rows[1]["rental_json"])["rental_end"] == "2026-09-29"


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


def _live_discovery_model_result():
    return {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": "Would you prefer a smaller car, an SUV, or a van?",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "request_recommendation",
        # This simultaneous model action was the missing condition in the
        # earlier replay and preempted the customer's explicit instruction.
        "ali_vehicle_recommendation": {
            "mode": "curated",
            "vehicle_names": [
                "Toyota Yaris or similar",
                "Kia Seltos or similar",
            ],
            "availability_note": (
                "Final vehicle availability still needs confirmation."
            ),
            "cta_label": "Car Details",
        },
    }


def test_live_browse_turn_overrides_model_candidates_and_builds_carousel(
    monkeypatch, tmp_path,
):
    phone = "synthetic-issue-266-browse"
    _configure(monkeypatch, tmp_path, _live_discovery_model_result())
    _use_media_catalog(monkeypatch)
    state_registry.wa_save_booking_state(
        phone,
        {
            "conversation_language": "en",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {"ali_phase": "DISCOVERY"},
    )

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Show me what you have",
        "from_name": "Synthetic Customer",
        "message_id": "issue-266-browse-turn",
    }, include_media=True)

    recommendation = response["vehicle_recommendation"]
    assert recommendation["kind"] == "carousel"
    assert len(recommendation["options"]) == 4
    assert "current fleet" in response["text"]
    assert "fewer than 6 seats" in response["text"]
    assert "Would you prefer" not in response["text"]


def test_live_customer_question_overrides_pending_passenger_question(
    monkeypatch, tmp_path,
):
    phone = "synthetic-answer-newest-customer-question"
    stale_model_result = {
        "intents": ["inquiry"],
        "fields": {"rental_start": "2026-08-30"},
        "confidence": "high",
        "reply": "How many people will be travelling in the car?",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "request_recommendation",
    }
    _configure(monkeypatch, tmp_path, stale_model_result)
    _use_media_catalog(monkeypatch)
    state_registry.wa_save_booking_state(
        phone,
        {"conversation_language": "en"},
        {"ali_phase": "DISCOVERY"},
    )

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "what do you have available right now ? i want topick it up tomorrow",
        "from_name": "Synthetic Customer",
        "message_id": "answer-newest-question-replay",
    }, include_media=True)
    stored = state_registry.wa_get_booking_state(phone)

    recommendation = response["vehicle_recommendation"]
    assert recommendation["kind"] == "carousel"
    assert len(recommendation["options"]) == 4
    assert "current fleet" in response["text"]
    assert "How many people" not in response["text"]
    assert stored["fields"]["rental_start"] == "2026-08-30"
    assert "passenger_count" not in stored["fields"]


def test_live_browse_turn_reaches_ordered_carousel_and_picker_transport(
    monkeypatch, tmp_path,
):
    class Response:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = ""

        def json(self):
            return self._payload

    phone = "synthetic-issue-266-provider"
    _configure(monkeypatch, tmp_path, _live_discovery_model_result())
    _use_media_catalog(monkeypatch)
    state_registry.wa_save_booking_state(
        phone,
        {
            "conversation_language": "en",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {"ali_phase": "DISCOVERY"},
    )
    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Show me what you have",
        "from_name": "Synthetic Customer",
        "message_id": "issue-266-provider-turn",
    }, include_media=True)

    posts = []
    monkeypatch.setenv("LATE_API_KEY", "synthetic-key")
    monkeypatch.setattr(
        zernio_dm_client,
        "_preflight_vehicle_media",
        lambda _url: True,
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *_args, **_kwargs: Response(200, {"messages": [{
            "direction": "incoming",
            "createdAt": (
                datetime.now(timezone.utc) - timedelta(minutes=1)
            ).isoformat(),
        }]}),
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda _url, headers, json, timeout: (
            posts.append({"headers": headers, "json": json})
            or Response(201)
        ),
    )

    delivery = zernio_dm_client.send_dm_vehicle_recommendation(
        "synthetic-conversation",
        "synthetic-account",
        response["vehicle_recommendation"],
    )

    assert response["ali_turn_commit"]["outbound_kind"] == (
        "vehicle_recommendation"
    )
    assert delivery == {"success": True, "delivery": "carousel_picker"}
    assert [post["json"]["interactive"]["type"] for post in posts] == [
        "carousel", "list",
    ]
    assert all("message" not in post["json"] for post in posts)


def test_live_smaller_turn_overrides_model_candidates_and_builds_carousel(
    monkeypatch, tmp_path,
):
    phone = "synthetic-issue-266-smaller"
    _configure(monkeypatch, tmp_path, _live_discovery_model_result())
    _use_media_catalog(monkeypatch)
    state_registry.wa_save_booking_state(
        phone,
        {
            "conversation_language": "en",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {"ali_phase": "DISCOVERY"},
    )

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Smaller",
        "from_name": "Synthetic Customer",
        "message_id": "issue-266-smaller-turn",
        "_zernio_provider_message_id": "wamid.issue-268-smaller-turn",
        "_zernio_sent_at": "2026-08-27T14:59:02Z",
    }, include_media=True)

    recommendation = response["vehicle_recommendation"]
    assert recommendation["kind"] == "carousel"
    assert [option["name"] for option in recommendation["options"]] == [
        "Kia Picanto 2024 or similar",
        "Toyota Yaris or similar",
        "Toyota Corolla or similar",
    ]
    assert "seat up to 5" in response["text"]
    assert "Would you prefer" not in response["text"]
    assert recommendation["trigger_message_id"] == (
        "wamid.issue-268-smaller-turn"
    )
    assert recommendation["trigger_sent_at"] == "2026-08-27T14:59:02Z"

    state_registry.wa_save_booking_state(
        phone,
        {
            "conversation_language": "en",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {
            "ali_phase": "DISCOVERY",
            "ali_vehicle_recommendation_deliveries": [{
                "hash": recommendation["state_hash"],
                "delivery": "carousel_picker",
            }],
        },
    )
    repeated = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Smaller",
        "from_name": "Synthetic Customer",
        "message_id": "issue-266-smaller-turn-2",
    }, include_media=True)

    assert repeated["vehicle_recommendation"] is not None
    assert repeated["vehicle_recommendation"]["state_hash"] != (
        recommendation["state_hash"]
    )


def test_live_larger_turn_replaces_stale_undersized_model_candidates(
    monkeypatch, tmp_path,
):
    phone = "synthetic-issue-270-larger"
    _configure(monkeypatch, tmp_path, _live_discovery_model_result())
    monkeypatch.setattr(
        social_agent, "get_ali_intake_catalog", media_catalog_with_van,
    )
    monkeypatch.setattr(
        workflow, "get_intake_catalog", media_catalog_with_van,
    )
    state_registry.wa_save_booking_state(
        phone,
        {
            "conversation_language": "en",
            "vehicle_id": YARIS_VEHICLE_ID,
            "vehicle_name": "Toyota Yaris or similar",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {
            "ali_phase": "DISCOVERY",
            "ali_last_recommendation_ids": [VAN_VEHICLE_ID],
            "ali_rejected_vehicle_ids": [VAN_VEHICLE_ID],
            "ali_shown_vehicle_ids": [VAN_VEHICLE_ID],
        },
    )

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Any bigger cars?",
        "from_name": "Synthetic Customer",
        "message_id": "issue-270-larger-turn",
        "_zernio_provider_message_id": "wamid.issue-270-larger-turn",
        "_zernio_sent_at": "2026-08-27T15:33:22Z",
    }, include_media=True)

    recommendation = response["vehicle_recommendation"]
    assert response["ali_turn_commit"]["outbound_kind"] == (
        "vehicle_recommendation"
    )
    assert recommendation["kind"] == "image"
    assert [option["id"] for option in recommendation["options"]] == [
        VAN_VEHICLE_ID,
    ]
    assert "larger option" in response["text"]
    assert "Would you prefer" not in response["text"]


def test_live_article_prefixed_van_turn_builds_exact_class_image(
    monkeypatch, tmp_path,
):
    phone = "synthetic-issue-270-van"
    model_result = _live_discovery_model_result()
    model_result["fields"] = {}
    model_result["ali_vehicle_recommendation"] = None
    _configure(monkeypatch, tmp_path, model_result)
    monkeypatch.setattr(
        social_agent, "get_ali_intake_catalog", media_catalog_with_van,
    )
    monkeypatch.setattr(
        workflow, "get_intake_catalog", media_catalog_with_van,
    )
    state_registry.wa_save_booking_state(
        phone,
        {
            "conversation_language": "en",
            "vehicle_id": YARIS_VEHICLE_ID,
            "vehicle_name": "Toyota Yaris or similar",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {
            "ali_phase": "DISCOVERY",
            "ali_last_recommendation_ids": [VAN_VEHICLE_ID],
            "ali_rejected_vehicle_ids": [VAN_VEHICLE_ID],
            "ali_shown_vehicle_ids": [VAN_VEHICLE_ID],
        },
    )

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "A van",
        "from_name": "Synthetic Customer",
        "message_id": "issue-270-van-turn",
        "_zernio_provider_message_id": "wamid.issue-270-van-turn",
        "_zernio_sent_at": "2026-08-27T15:33:50Z",
    }, include_media=True)
    saved = state_registry.wa_get_booking_state(phone)

    recommendation = response["vehicle_recommendation"]
    assert response["ali_turn_commit"]["outbound_kind"] == (
        "vehicle_recommendation"
    )
    assert recommendation["kind"] == "image"
    assert [option["id"] for option in recommendation["options"]] == [
        VAN_VEHICLE_ID,
    ]
    assert saved["fields"]["vehicle_class_id"] == VAN_CLASS_ID
    assert saved["fields"]["vehicle_class_name"] == "Van"
    assert "vehicle_id" not in saved["fields"]
    assert "Would you prefer" not in response["text"]


def test_same_exact_class_can_be_reoffered_on_new_turn_without_replay_duplication(
    monkeypatch, tmp_path,
):
    phone = "synthetic-issue-270-van-repeat"
    model_result = _live_discovery_model_result()
    model_result["fields"] = {}
    model_result["ali_vehicle_recommendation"] = None
    _configure(monkeypatch, tmp_path, model_result)
    monkeypatch.setattr(
        social_agent, "get_ali_intake_catalog", media_catalog_with_van,
    )
    monkeypatch.setattr(
        workflow, "get_intake_catalog", media_catalog_with_van,
    )
    state_registry.wa_save_booking_state(
        phone,
        {
            "conversation_language": "en",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {"ali_phase": "DISCOVERY"},
    )

    first = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "A van",
        "from_name": "Synthetic Customer",
        "message_id": "issue-270-van-repeat-1",
        "_ali_action_id": "a" * 64,
    }, include_media=True)
    _commit_result(phone, first, "issue-270-van-repeat-1")
    second = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "A van",
        "from_name": "Synthetic Customer",
        "message_id": "issue-270-van-repeat-2",
        "_ali_action_id": "b" * 64,
    }, include_media=True)

    assert first["vehicle_recommendation"] is not None
    assert second["vehicle_recommendation"] is not None
    assert second["vehicle_recommendation"]["state_hash"] != (
        first["vehicle_recommendation"]["state_hash"]
    )


def test_live_no_preference_turn_ignores_model_candidates_and_uses_capacity(
    monkeypatch, tmp_path,
):
    phone = "synthetic-issue-266-no-preference"
    result = _live_discovery_model_result()
    result["reply"] = "The Toyota Yaris and Kia Seltos are good options."
    _configure(monkeypatch, tmp_path, result)
    catalog = media_catalog()
    catalog["vehicles"].append({
        "id": "40000000-0000-4000-8000-000000000007",
        "slug": "suzuki-ertiga",
        "classId": VAN_CLASS_ID,
        "name": "Suzuki Ertiga or similar",
        "seats": 7,
        "transmission": "automatic",
        "features": ["Air conditioning"],
        "dailyRate": {"currency": "USD", "amount": "75.00"},
        "weeklyRate": {"currency": "USD", "amount": "525.00"},
        "images": [{
            "url": "/brand/vehicles/suzuki-ertiga.png",
            "alt": "Ali Suzuki Ertiga",
        }],
    })
    monkeypatch.setattr(social_agent, "get_ali_intake_catalog", lambda: catalog)
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda: catalog)
    state_registry.wa_save_booking_state(
        phone,
        {
            "conversation_language": "en",
            "passenger_count": 6,
            "luggage_count": 3,
        },
        {
            "ali_phase": "DISCOVERY",
            "ali_rejected_vehicle_ids": [
                "40000000-0000-4000-8000-000000000007",
            ],
        },
    )

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Whatever",
        "from_name": "Synthetic Customer",
        "message_id": "issue-266-no-preference-turn",
    }, include_media=True)

    recommendation = response["vehicle_recommendation"]
    assert recommendation["kind"] == "image"
    assert [option["name"] for option in recommendation["options"]] == [
        "Suzuki Ertiga or similar",
    ]
    assert "Toyota Yaris" not in response["text"]
    assert "Would you prefer" not in response["text"]


def test_live_no_preference_reopens_a_previously_delivered_suitable_car(
    monkeypatch, tmp_path,
):
    phone = "synthetic-issue-266-no-preference-reopen"
    result = _live_discovery_model_result()
    _configure(monkeypatch, tmp_path, result)
    catalog = media_catalog()
    ertiga_id = "40000000-0000-4000-8000-000000000007"
    catalog["vehicles"].append({
        "id": ertiga_id,
        "slug": "suzuki-ertiga",
        "classId": VAN_CLASS_ID,
        "name": "Suzuki Ertiga or similar",
        "seats": 7,
        "transmission": "automatic",
        "features": ["Air conditioning"],
        "dailyRate": {"currency": "USD", "amount": "75.00"},
        "weeklyRate": {"currency": "USD", "amount": "525.00"},
        "images": [{
            "url": "/brand/vehicles/suzuki-ertiga.png",
            "alt": "Ali Suzuki Ertiga",
        }],
    })
    monkeypatch.setattr(social_agent, "get_ali_intake_catalog", lambda: catalog)
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda: catalog)
    fields = {
        "conversation_language": "en",
        "passenger_count": 6,
        "luggage_count": 3,
    }
    prior = social_agent.build_vehicle_recommendation(
        {
            "mode": "specific",
            "vehicle_names": ["Suzuki Ertiga or similar"],
            "availability_note": (
                "Final vehicle availability still needs confirmation."
            ),
            "cta_label": "Car Details",
        },
        catalog,
        fields,
        {},
        "Here is the suitable van.",
    )
    state_registry.wa_save_booking_state(phone, fields, {
        "ali_phase": "DISCOVERY",
        "ali_last_recommendation_ids": [ertiga_id],
        "ali_rejected_vehicle_ids": [ertiga_id],
        "ali_vehicle_recommendation_deliveries": [{
            "state_hash": prior["state_hash"],
            "delivery": "image",
        }],
    })

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Whatever",
        "from_name": "Synthetic Customer",
        "message_id": "issue-266-no-preference-reopen-turn",
    }, include_media=True)

    recommendation = response["vehicle_recommendation"]
    assert recommendation["kind"] == "image"
    assert recommendation["options"][0]["id"] == ertiga_id
    assert recommendation["state_hash"] != prior["state_hash"]
    assert "Would you prefer" not in response["text"]


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
    assert "I have these details from you:" not in response["text"]
    assert saved["flags"]["ali_rejected_vehicle_ids"] == [SUV_VEHICLE_ID]
    _commit_result(phone, response, "issue-198-rejection")
    saved = state_registry.wa_get_booking_state(phone)
    assert "ali_summary_hash" not in saved["flags"]
    assert "awaiting_quote_confirmation" not in saved["flags"]


def test_direct_smaller_car_question_is_answered_before_trip_context(
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

    recommendation = response["vehicle_recommendation"]
    assert recommendation["kind"] == "carousel"
    assert [option["id"] for option in recommendation["options"]] == [
        ECONOMY_VEHICLE_ID, YARIS_VEHICLE_ID, COROLLA_VEHICLE_ID,
    ]
    assert response["text"].startswith("Here are the smaller cars.")
    assert "How many people" not in response["text"]


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
    assert response["text"].count("I have these details from you:") == 1
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


def test_pickup_options_question_preserves_selected_car_and_never_sends_cars(
    monkeypatch, tmp_path,
):
    phone = "synthetic-pickup-options-guard"
    fields = _stored_fields()
    fields.pop("pickup_location")
    stale_model_result = {
        "intents": ["inquiry"],
        "fields": {
            "vehicle_name": "Kia Seltos or similar",
            "vehicle_class_name": "Compact SUV",
        },
        "confidence": "high",
        "reply": "Here are a few cars from our fleet.",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "request_recommendation",
        "ali_vehicle_recommendation": {
            "mode": "specific",
            "vehicle_names": ["Kia Seltos or similar"],
        },
    }
    _configure(monkeypatch, tmp_path, stale_model_result)
    monkeypatch.setattr(social_agent, "get_ali_intake_catalog", pickup_catalog)
    monkeypatch.setattr(workflow, "get_intake_catalog", pickup_catalog)
    state_registry.wa_save_booking_state(phone, fields, {})

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "wbich options do you have for picking up the car ?",
        "from_name": "Synthetic Customer",
    }, include_media=True)
    stored = state_registry.wa_get_booking_state(phone)

    assert response["vehicle_recommendation"] is None
    assert response["ali_turn_commit"]["outbound_kind"] == "agent_reply"
    assert "• Airport" in response["text"]
    assert "• Ali office" in response["text"]
    assert "• Hotel delivery" in response["text"]
    assert stored["fields"]["vehicle_id"] == ECONOMY_VEHICLE_ID
    assert stored["fields"]["vehicle_name"] == "Kia Picanto 2024 or similar"
    assert "pickup_location" not in stored["fields"]


def test_hotel_delivery_collects_name_then_partial_address_one_at_a_time(
    monkeypatch, tmp_path,
):
    phone = "synthetic-hotel-delivery-sequence"
    fields = _stored_fields()
    fields.pop("pickup_location")
    model_result = {
        "intents": ["inquiry"],
        "fields": {"pickup_location": "Hotel delivery"},
        "confidence": "high",
        "reply": "Please send the hotel name and address.",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "continue_intake",
    }
    _configure(monkeypatch, tmp_path, model_result)
    monkeypatch.setattr(social_agent, "get_ali_intake_catalog", pickup_catalog)
    monkeypatch.setattr(workflow, "get_intake_catalog", pickup_catalog)
    state_registry.wa_save_booking_state(phone, fields, {})

    selected = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Hotel delivery",
        "from_name": "Synthetic Customer",
    }, include_media=True)
    after_choice = state_registry.wa_get_booking_state(phone)

    assert selected["text"] == "Hotel delivery works. What is the name of the hotel?"
    assert selected["text"].count("?") == 1
    assert "pickup_location" not in after_choice["fields"]
    assert after_choice["flags"]["ali_pickup_hotel_detail_stage"] == "name"

    question_result = {
        **model_result,
        "fields": {},
        "reply": "I don’t have a confirmed hotel-delivery fee, so I don’t want to guess.",
        "ali_primary_intent": "ask_question",
    }
    monkeypatch.setattr(
        social_agent.marina_agent,
        "process_message",
        lambda **_kwargs: question_result,
    )
    answered = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Is hotel delivery free?",
        "from_name": "Synthetic Customer",
    }, include_media=True)
    after_question = state_registry.wa_get_booking_state(phone)

    assert answered["text"] == question_result["reply"]
    assert "pickup_hotel_name" not in after_question["fields"]
    assert after_question["flags"]["ali_pickup_hotel_detail_stage"] == "name"

    monkeypatch.setattr(
        social_agent.marina_agent,
        "process_message",
        lambda **_kwargs: {**model_result, "fields": {}},
    )
    named = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Avila Beach Hotel",
        "from_name": "Synthetic Customer",
    }, include_media=True)
    after_name = state_registry.wa_get_booking_state(phone)

    assert "What is the hotel address?" in named["text"]
    assert "partial address is fine" in named["text"]
    assert named["text"].count("?") == 1
    assert after_name["fields"]["pickup_hotel_name"] == "Avila Beach Hotel"
    assert "pickup_location" not in after_name["fields"]
    assert after_name["flags"]["ali_pickup_hotel_detail_stage"] == "address"

    completed = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Penstraat",
        "from_name": "Synthetic Customer",
    }, include_media=True)
    after_address = state_registry.wa_get_booking_state(phone)

    assert completed["vehicle_recommendation"] is None
    assert after_address["fields"]["pickup_location"] == (
        "Hotel delivery — Avila Beach Hotel, Penstraat"
    )
    assert "ali_pickup_hotel_detail_stage" not in after_address["flags"]


def test_airport_pickup_then_airport_return_never_emits_hotel_delivery_copy(
    monkeypatch, tmp_path,
):
    phone = "synthetic-airport-pickup-and-return"
    fields = _stored_fields("es")
    fields.pop("pickup_location")
    fields.pop("return_location")
    pickup_result = {
        "intents": ["inquiry"],
        "fields": {"pickup_location": "Airport"},
        "confidence": "high",
        "reply": "Gracias. ¿Dónde deseas devolver el auto?",
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "continue_intake",
    }
    _configure(monkeypatch, tmp_path, pickup_result)
    location_catalog = pickup_catalog()
    location_catalog["returnLocations"] = [{
        "id": "airport-return",
        "name": "Airport",
        "kind": "fixed",
        "active": True,
        "displayOrder": 10,
    }]
    monkeypatch.setattr(
        social_agent, "get_ali_intake_catalog", lambda: location_catalog,
    )
    monkeypatch.setattr(
        workflow, "get_intake_catalog", lambda: location_catalog,
    )
    state_registry.wa_save_booking_state(phone, fields, {})

    pickup = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Airport",
        "from_name": "Federico Barcio",
    }, include_media=True)
    after_pickup = state_registry.wa_get_booking_state(phone)

    assert after_pickup["fields"]["pickup_location"] == "Airport"
    assert "devolver el auto" in pickup["text"]
    assert "hotel" not in pickup["text"].lower()

    return_result = {
        **pickup_result,
        "fields": {"return_location": "Airport"},
        "reply": "Perfecto. Guardé el aeropuerto para la devolución.",
    }
    monkeypatch.setattr(
        social_agent.marina_agent,
        "process_message",
        lambda **_kwargs: return_result,
    )
    returned = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Airport",
        "from_name": "Federico Barcio",
    }, include_media=True)
    after_return = state_registry.wa_get_booking_state(phone)

    assert after_return["fields"]["pickup_location"] == "Airport"
    assert after_return["fields"]["return_location"] == "Airport"
    assert after_return["fields"]["pickup_location_kind"] == "fixed"
    assert "ali_pickup_hotel_detail_stage" not in after_return["flags"]
    assert "hotel delivery" not in returned["text"].lower()
    assert "entrega en el hotel" not in returned["text"].lower()


def test_confirmed_reservation_email_uses_model_reply_without_quote_rewrite(
    monkeypatch, tmp_path,
):
    phone = "synthetic-confirmed-after-sales-email"
    expected_reply = (
        "Thank you—I’ve saved your email address. Our team will send your "
        "reservation documents and agreements to Calvin@gaimin.io. If you "
        "need anything else before pickup, just message me here."
    )
    model_result = {
        "intents": ["inquiry"],
        "fields": {"email": "Calvin@gaimin.io"},
        "confidence": "high",
        "reply": expected_reply,
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "other",
    }
    _configure(monkeypatch, tmp_path, model_result)
    monkeypatch.setattr(
        social_agent,
        "get_ali_quote_context",
        lambda *_args, **_kwargs: {"status": "quoted"},
    )
    monkeypatch.setattr(
        social_agent,
        "get_ali_reservation_context",
        lambda *_args, **_kwargs: {
            "status": "confirmed",
            "confirmation_reference": "ALI-RSV-SYNTHETIC",
        },
    )
    state_registry.wa_save_booking_state(
        phone,
        _stored_fields(),
        {"ali_phase": "QUOTED"},
    )

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Calvin@gaimin.io",
        "from_name": "Synthetic Customer",
        "message_id": "confirmed-email-1",
        "_zernio_sender_id": "+5999677145",
        "_zernio_account_id": "synthetic-account",
    }, include_media=True)
    stored = state_registry.wa_get_booking_state(phone)

    assert response["text"] == expected_reply
    assert "couldn't complete that step safely" not in response["text"]
    assert response["ali_turn_commit"] is None
    assert response["quote_confirmation"] is None
    assert response["vehicle_recommendation"] is None
    assert stored["fields"]["email"] == "Calvin@gaimin.io"


def test_confirmed_reservation_short_ack_does_not_repeat_confirmation(
    monkeypatch, tmp_path,
):
    phone = "synthetic-confirmed-after-sales-ack"
    expected_reply = (
        "You’re very welcome. If you need anything else before pickup, "
        "just message me here."
    )
    model_result = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": expected_reply,
        "requires_human": False,
        "flags": {},
        "ali_primary_intent": "other",
    }
    _configure(monkeypatch, tmp_path, model_result)
    monkeypatch.setattr(
        social_agent,
        "get_ali_quote_context",
        lambda *_args, **_kwargs: {"status": "quoted"},
    )
    monkeypatch.setattr(
        social_agent,
        "get_ali_reservation_context",
        lambda *_args, **_kwargs: {
            "status": "confirmed",
            "confirmation_reference": "ALI-RSV-SYNTHETIC",
        },
    )
    state_registry.wa_save_booking_state(
        phone,
        _stored_fields(),
        {"ali_phase": "QUOTED"},
    )

    response = social_agent.handle_incoming_whatsapp_message({
        "from": phone,
        "text": "Ok",
        "from_name": "Synthetic Customer",
        "message_id": "confirmed-ack-1",
        "_zernio_sender_id": "+5999677145",
        "_zernio_account_id": "synthetic-account",
    }, include_media=True)

    assert response["text"] == expected_reply
    assert "ALI-RSV-SYNTHETIC" not in response["text"]
    assert "reservation is confirmed" not in response["text"].lower()
    assert response["ali_turn_commit"] is None
    assert response["quote_confirmation"] is None
    assert response["vehicle_recommendation"] is None
