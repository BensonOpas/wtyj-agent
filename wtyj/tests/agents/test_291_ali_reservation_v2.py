"""Brief 291: strict Ali reservation V2 state, clock and intent safety."""

from __future__ import annotations

import sqlite3
import io
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from agents.social import ali_customer_dossier as dossier
from agents.social import ali_reservation_v2 as workflow
from agents.social import ali_reservation_workflow as legacy


BASE = datetime(2099, 9, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def configured(monkeypatch, tmp_path):
    raw = {
        "slug": "ali-car-rental",
        "workflow": {
            "type": "ali_quote",
            "post_quote": {
                "v2": {
                    "hold_active_client_hours": 24,
                    "reminder_active_client_hours": [3, 12, 21],
                    "quiet_hours_start": "20:30",
                    "quiet_hours_end": "08:30",
                    "default_timezone": "America/Curacao",
                }
            },
        },
        "features": {
            "ali_post_quote_reservation_v2_enabled": True,
            "ali_reservation_v2_reminders_enabled": False,
            "ali_customer_dossier_enabled": True,
        },
        "ali_customer_dossier": {
            "private_storage_root": str(tmp_path / "private"),
        },
    }
    monkeypatch.setattr(workflow.state_registry, "DB_PATH", str(tmp_path / "tenant.db"))
    monkeypatch.setattr(legacy.state_registry, "DB_PATH", str(tmp_path / "tenant.db"))
    monkeypatch.setattr(workflow.config_loader, "get_raw", lambda: raw)
    monkeypatch.setattr(legacy.config_loader, "get_raw", lambda: raw)
    legacy.ensure_schema()
    conn = sqlite3.connect(workflow.state_registry.DB_PATH)
    conn.execute(
        "INSERT INTO ali_reservations (public_id, tenant_slug, quote_public_id, "
        "quote_snapshot_id, quote_reference, conversation_id, zernio_account_id, "
        "status, availability_status, identity_status, agreement_status, "
        "payment_status, created_at, updated_at) VALUES "
        "('reservation-291', 'ali-car-rental', 'quote-291', 'snapshot-291', "
        "'ALI-20990901-V2', 'conversation-291', 'account-291', "
        "'availability_pending', 'pending', 'not_requested', 'not_sent', "
        "'not_sent', ?, ?)",
        (BASE.isoformat(), BASE.isoformat()),
    )
    conn.commit()
    conn.close()
    return raw


def _png(color=(9, 37, 60)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 32), color).save(output, format="PNG")
    return output.getvalue()


def test_initial_case_is_staff_paused_and_one_next_action(configured):
    created = workflow.initialize_reservation(
        "reservation-291", now=BASE, client_timezone="America/Curacao",
    )
    replay = workflow.initialize_reservation("reservation-291", now=BASE)

    assert created == replay
    assert created["state"] == "availability_pending"
    assert created["responsibleParty"] == "Staff"
    assert created["clock"] == {
        "state": "paused",
        "pauseReason": "availability_approval",
        "activeClientSeconds": 0,
        "remainingSeconds": 86400,
        "holdSeconds": 86400,
        "clientTimezone": "America/Curacao",
    }
    assert created["nextAction"] == "approve_or_decline_availability"
    assert created["reminders"]["sendEnabled"] is False


def test_tenant_schedule_settings_are_validated_and_apply_to_active_case(configured):
    workflow.initialize_reservation("reservation-291", now=BASE)
    updated = workflow.save_tenant_settings(
        hold_active_client_hours=26,
        reminder_active_client_hours=[4, 13, 22],
        quiet_hours_start="21:00",
        quiet_hours_end="07:30",
        default_timezone="Europe/Lisbon",
        actor="dashboard",
    )
    case = workflow.get_case("reservation-291", now=BASE)

    assert updated == {
        "holdActiveClientHours": 26,
        "reminderActiveClientHours": [4, 13, 22],
        "quietHoursStart": "21:00",
        "quietHoursEnd": "07:30",
        "defaultTimezone": "Europe/Lisbon",
        "reminderSendEnabled": False,
    }
    assert case["clock"]["holdSeconds"] == 26 * 3600
    assert case["reminders"]["milestonesSeconds"] == [
        4 * 3600, 13 * 3600, 22 * 3600,
    ]
    with pytest.raises(legacy.AliReservationError):
        workflow.save_tenant_settings(
            hold_active_client_hours=24,
            reminder_active_client_hours=[3, 24],
            quiet_hours_start="21:00",
            quiet_hours_end="07:30",
            default_timezone="Europe/Lisbon",
            actor="dashboard",
        )


def test_transition_order_and_idempotency_are_server_enforced(configured):
    workflow.initialize_reservation("reservation-291", now=BASE)
    with pytest.raises(legacy.AliReservationError) as out_of_order:
        workflow.transition(
            "reservation-291", "contract_sent", actor_type="staff",
            actor_id="staff-291", idempotency_key="bad-order", now=BASE,
        )
    assert out_of_order.value.code == "invalid_v2_transition"

    collecting = workflow.transition(
        "reservation-291", "documents_collecting", actor_type="staff",
        actor_id="staff-291", idempotency_key="availability-approved", now=BASE,
    )
    replay = workflow.transition(
        "reservation-291", "documents_collecting", actor_type="staff",
        actor_id="staff-291", idempotency_key="availability-approved",
        expected_revision=1, now=BASE + timedelta(minutes=1),
    )

    assert collecting["state"] == replay["state"] == "documents_collecting"
    assert collecting["revision"] == replay["revision"]
    assert collecting["responsibleParty"] == "Client"
    assert collecting["clock"]["state"] == "running"


def test_idempotency_keys_are_scoped_to_each_reservation(configured):
    conn = sqlite3.connect(workflow.state_registry.DB_PATH)
    conn.execute(
        "INSERT INTO ali_reservations (public_id, tenant_slug, quote_public_id, "
        "quote_snapshot_id, quote_reference, conversation_id, zernio_account_id, "
        "status, availability_status, identity_status, agreement_status, "
        "payment_status, created_at, updated_at) VALUES "
        "('reservation-292', 'ali-car-rental', 'quote-292', 'snapshot-292', "
        "'ALI-20990901-V2B', 'conversation-292', 'account-292', "
        "'availability_pending', 'pending', 'not_requested', 'not_sent', "
        "'not_sent', ?, ?)",
        (BASE.isoformat(), BASE.isoformat()),
    )
    conn.commit()
    conn.close()
    for public_id in ("reservation-291", "reservation-292"):
        workflow.initialize_reservation(public_id, now=BASE)
        changed = workflow.transition(
            public_id,
            "documents_collecting",
            actor_type="staff",
            actor_id="staff-291",
            idempotency_key="availability-approved",
            now=BASE,
        )
        assert changed["state"] == "documents_collecting"


def test_active_client_clock_pauses_and_resumes_without_charging_staff_time(configured):
    workflow.initialize_reservation("reservation-291", now=BASE)
    workflow.transition(
        "reservation-291", "documents_collecting", actor_type="staff",
        actor_id="staff-291", idempotency_key="approve", now=BASE,
    )
    review = workflow.transition(
        "reservation-291", "document_review_pending", actor_type="system",
        actor_id="document-intake", idempotency_key="all-received",
        now=BASE + timedelta(hours=2),
    )
    assert review["clock"]["activeClientSeconds"] == 7200
    assert review["clock"]["state"] == "paused"

    replacement = workflow.transition(
        "reservation-291", "document_replacement_required", actor_type="staff",
        actor_id="staff-291", idempotency_key="replace-front",
        now=BASE + timedelta(hours=20),
    )
    assert replacement["clock"]["activeClientSeconds"] == 7200
    assert replacement["clock"]["state"] == "running"

    resumed = workflow.get_case(
        "reservation-291", now=BASE + timedelta(hours=21),
    )
    assert resumed["clock"]["activeClientSeconds"] == 10800
    assert resumed["clock"]["remainingSeconds"] == 75600


def test_provider_confirmed_payment_link_starts_a_fresh_24_hour_clock(configured):
    workflow.initialize_reservation("reservation-291", now=BASE)
    transitions = [
        ("documents_collecting", BASE),
        ("documents_collected", BASE + timedelta(hours=5)),
        ("contract_sent", BASE + timedelta(hours=5)),
        ("contract_signed", BASE + timedelta(hours=8)),
        ("prepayment_approval_pending", BASE + timedelta(hours=8)),
        ("prepayment_approved", BASE + timedelta(hours=8)),
    ]
    for index, (state, at) in enumerate(transitions):
        workflow.transition(
            "reservation-291", state, actor_type="system",
            actor_id="payment-window-test",
            idempotency_key=f"before-payment-{index}", now=at,
        )
    conn = sqlite3.connect(workflow.state_registry.DB_PATH)
    conn.execute(
        "INSERT INTO ali_reservation_v2_reminders "
        "(reservation_public_id, tenant_slug, milestone_seconds, status, "
        "idempotency_key, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "reservation-291", "ali-car-rental", 10800, "sent",
            "old-document-reminder", BASE.isoformat(),
        ),
    )
    conn.commit()
    conn.close()

    payment = workflow.transition(
        "reservation-291", "payment_link_sent", actor_type="system",
        actor_id="payment-window-test", idempotency_key="payment-link-sent",
        now=BASE + timedelta(hours=8),
    )

    assert payment["clock"]["activeClientSeconds"] == 0
    assert payment["clock"]["remainingSeconds"] == 24 * 60 * 60
    assert payment["clock"]["state"] == "running"
    conn = sqlite3.connect(workflow.state_registry.DB_PATH)
    count = conn.execute(
        "SELECT COUNT(*) FROM ali_reservation_v2_reminders WHERE "
        "reservation_public_id = 'reservation-291'",
    ).fetchone()[0]
    conn.close()
    assert count == 0


def test_contract_signature_cannot_skip_the_staff_prepayment_gate(configured):
    workflow.initialize_reservation("reservation-291", now=BASE)
    for index, state in enumerate((
        "documents_collecting",
        "documents_collected",
        "contract_sent",
        "contract_signed",
    )):
        workflow.transition(
            "reservation-291",
            state,
            actor_type="system",
            actor_id="gate-test",
            idempotency_key=f"gate-before-{index}",
            now=BASE,
        )

    with pytest.raises(legacy.AliReservationError) as skipped:
        workflow.transition(
            "reservation-291",
            "payment_link_sent",
            actor_type="system",
            actor_id="gate-test",
            idempotency_key="skip-staff-approval",
            now=BASE,
        )

    assert skipped.value.code == "invalid_v2_transition"
    pending = workflow.transition(
        "reservation-291",
        "prepayment_approval_pending",
        actor_type="system",
        actor_id="gate-test",
        idempotency_key="open-staff-review",
        now=BASE,
    )
    approved = workflow.transition(
        "reservation-291",
        "prepayment_approved",
        actor_type="staff",
        actor_id="dashboard",
        idempotency_key="approve-complete-file",
        expected_revision=pending["revision"],
        now=BASE,
    )
    assert pending["responsibleParty"] == "Staff"
    assert pending["nextAction"] == "approve_prepayment_file"
    assert approved["state"] == "prepayment_approved"


def test_reminders_use_active_time_coalesce_and_never_send_while_paused(configured):
    workflow.initialize_reservation(
        "reservation-291", now=BASE, client_timezone="America/Curacao",
    )
    workflow.transition(
        "reservation-291", "documents_collecting", actor_type="staff",
        actor_id="staff-291", idempotency_key="approve", now=BASE,
    )

    due = workflow.reminder_plan(now=BASE + timedelta(hours=3))
    assert [(item["kind"], item["milestoneSeconds"]) for item in due] == [
        ("reminder", 10800),
    ]
    workflow.record_reminder_result(due[0], sent=True, now=BASE + timedelta(hours=3))
    assert workflow.reminder_plan(now=BASE + timedelta(hours=4)) == []

    workflow.transition(
        "reservation-291", "document_review_pending", actor_type="system",
        actor_id="intake", idempotency_key="review", now=BASE + timedelta(hours=4),
    )
    assert workflow.reminder_plan(now=BASE + timedelta(hours=20)) == []

    workflow.transition(
        "reservation-291", "document_replacement_required", actor_type="staff",
        actor_id="staff-291", idempotency_key="replacement", now=BASE + timedelta(hours=20),
    )
    coalesced = workflow.reminder_plan(now=BASE + timedelta(hours=28))
    assert [item["milestoneSeconds"] for item in coalesced] == [43200]


def test_quiet_hours_defer_due_reminder(configured):
    quiet_start_utc = datetime(2099, 9, 2, 1, 0, tzinfo=timezone.utc)
    workflow.initialize_reservation(
        "reservation-291", now=quiet_start_utc - timedelta(hours=3),
        client_timezone="America/Curacao",
    )
    workflow.transition(
        "reservation-291", "documents_collecting", actor_type="staff",
        actor_id="staff-291", idempotency_key="approve-quiet",
        now=quiet_start_utc - timedelta(hours=3),
    )
    # 21:00 Curaçao: milestone is due but quiet hours suppress the plan.
    assert workflow.reminder_plan(now=quiet_start_utc) == []


def test_hold_expiry_closure_retries_until_provider_confirmed(configured):
    workflow.initialize_reservation("reservation-291", now=BASE)
    workflow.transition(
        "reservation-291", "documents_collecting", actor_type="staff",
        actor_id="staff-291", idempotency_key="approve-expiry", now=BASE,
    )
    expiry = next(
        item for item in workflow.reminder_plan(now=BASE + timedelta(hours=24))
        if item["kind"] == "expire"
    )
    expired = workflow.expire_due_case(
        expiry, now=BASE + timedelta(hours=24),
    )
    assert expired["state"] == "hold_expired"
    closure = next(
        item for item in workflow.reminder_plan(now=BASE + timedelta(hours=24))
        if item["kind"] == "expiry_closure"
    )
    workflow.record_expiry_closure_result(
        closure, sent=False, now=BASE + timedelta(hours=24),
    )
    assert any(
        item["kind"] == "expiry_closure"
        for item in workflow.reminder_plan(now=BASE + timedelta(hours=24))
    )
    workflow.record_expiry_closure_result(
        closure, sent=True, now=BASE + timedelta(hours=24),
    )
    assert workflow.reminder_plan(now=BASE + timedelta(hours=24)) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("stop messaging me", "global_opt_out"),
        ("geen berichten meer", "global_opt_out"),
        ("no manda mi mas mensahe", "global_opt_out"),
        ("Keine Nachrichten mehr", "global_opt_out"),
        ("I already rented a car", "reservation_decline"),
        ("I don't want this car", "vehicle_rejection"),
        ("I don’t want this car", "vehicle_rejection"),
        ("no", "ambiguous_negative"),
        ("book it", "typed_reserve"),
        ("I want this car", "typed_reserve"),
    ],
)
def test_structural_intent_is_deterministic_and_multilingual(text, expected):
    result = workflow.classify_structural_intent(text)
    assert result["classification"] == expected
    assert result["decisionSource"] == "deterministic"


@pytest.mark.parametrize(
    "text",
    [
        "Can you reserve it if the price is lower?",
        "I do not want this car, show me another one with 7 seats",
        "Do not contact the airport; contact me here",
        "I found another car online. Is yours cheaper?",
        "yes",
    ],
)
def test_questions_corrections_and_qualified_text_never_trigger_structural_action(text):
    assert workflow.classify_structural_intent(text)["classification"] == "none"


def test_global_opt_out_is_exactly_once_and_suppresses_proactive_work(configured):
    workflow.initialize_reservation("reservation-291", now=BASE)
    workflow.transition(
        "reservation-291", "documents_collecting", actor_type="staff",
        actor_id="staff-291", idempotency_key="approve-optout", now=BASE,
    )
    first = workflow.apply_negative_intent(
        "reservation-291", "global_opt_out",
        source_message_id="message-optout-291", now=BASE + timedelta(hours=1),
    )
    replay = workflow.apply_negative_intent(
        "reservation-291", "global_opt_out",
        source_message_id="message-optout-291", now=BASE + timedelta(hours=2),
    )

    assert first["action"] == "acknowledge_opt_out_once"
    assert first["repeated"] is False
    assert replay["repeated"] is True
    assert replay["case"]["state"] == "client_opted_out"
    assert replay["case"]["doNotContact"] is True
    assert workflow.reminder_plan(now=BASE + timedelta(days=2)) == []

    conn = sqlite3.connect(workflow.state_registry.DB_PATH)
    count = conn.execute(
        "SELECT COUNT(*) FROM ali_reservation_v2_intents WHERE classification='global_opt_out'",
    ).fetchone()[0]
    preference = conn.execute(
        "SELECT do_not_contact FROM ali_reservation_v2_contact_preferences "
        "WHERE tenant_slug='ali-car-rental' AND conversation_id='conversation-291'",
    ).fetchone()
    conn.close()
    assert count == 1
    assert preference == (1,)


def test_ambiguous_negative_freezes_clock_without_cancelling(configured):
    workflow.initialize_reservation("reservation-291", now=BASE)
    workflow.transition(
        "reservation-291", "documents_collecting", actor_type="staff",
        actor_id="staff-291", idempotency_key="approve-ambiguous", now=BASE,
    )
    result = workflow.apply_negative_intent(
        "reservation-291", "ambiguous_negative",
        source_message_id="message-no-291", now=BASE + timedelta(hours=1),
    )
    assert result["case"]["state"] == "documents_collecting"
    assert result["case"]["clock"]["state"] == "paused"
    assert result["case"]["negativeIntentPending"] is True
    assert result["action"] == "ask_release_or_more_time_once"

    resumed = workflow.resolve_ambiguous_negative(
        "reservation-291",
        "more_time",
        source_message_id="message-more-time-291",
        now=BASE + timedelta(hours=2),
    )
    replay = workflow.resolve_ambiguous_negative(
        "reservation-291",
        "more_time",
        source_message_id="message-more-time-291",
        now=BASE + timedelta(hours=3),
    )
    assert resumed["case"]["clock"]["state"] == "running"
    assert resumed["case"]["negativeIntentPending"] is False
    assert resumed["case"]["clock"]["activeClientSeconds"] == 3600
    assert replay["repeated"] is True


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Give me more time", "more_time"),
        ("geef me meer tijd", "more_time"),
        ("duna mi mas tempu", "more_time"),
        ("Mehr Zeit", "more_time"),
        ("release the car", "release"),
        ("geef de auto vrij", "release"),
        ("laga e outo liber", "release"),
        ("Auto freigeben", "release"),
        ("maybe next week", "none"),
    ],
)
def test_ambiguous_resolution_is_deterministic_and_multilingual(text, expected):
    assert workflow.classify_ambiguous_resolution(text) == expected


def test_vehicle_rejection_stops_reminders_and_routes_to_change(configured):
    workflow.initialize_reservation("reservation-291", now=BASE)
    workflow.transition(
        "reservation-291", "documents_collecting", actor_type="staff",
        actor_id="staff-291", idempotency_key="approve-change", now=BASE,
    )
    result = workflow.apply_negative_intent(
        "reservation-291", "vehicle_rejection",
        source_message_id="message-reject-car-291",
        now=BASE + timedelta(hours=1),
    )
    assert result["action"] == "route_to_change_something"
    assert result["case"]["clock"]["state"] == "paused"
    assert result["case"]["clock"]["pauseReason"] == "vehicle_change"
    assert result["case"]["negativeIntentPending"] is True
    assert workflow.reminder_plan(now=BASE + timedelta(hours=12)) == []


def test_direct_whatsapp_documents_have_no_public_links_and_can_be_reclassified(configured):
    conn = sqlite3.connect(workflow.state_registry.DB_PATH)
    conn.execute(
        "UPDATE ali_reservations SET availability_status='approved', "
        "status='requirements_pending' WHERE public_id='reservation-291'",
    )
    revision = conn.execute(
        "SELECT revision FROM ali_reservations WHERE public_id='reservation-291'",
    ).fetchone()[0]
    conn.commit()
    conn.close()
    workflow.initialize_reservation("reservation-291", now=BASE)
    workflow.transition(
        "reservation-291", "documents_collecting", actor_type="staff",
        actor_id="staff-291", idempotency_key="approve-media", now=BASE,
    )
    request = dossier.issue_document_links(
        "reservation-291", "staff-291", expected_revision=revision,
    )
    assert request["mode"] == "direct_whatsapp"
    assert request["links"] == []
    due = workflow.reminder_plan(now=BASE)
    assert due == [{
        "kind": "documents_prompt",
        "reservationPublicId": "reservation-291",
        "idempotencyKey": "ali-v2-documents-prompt:reservation-291",
    }]
    workflow.record_customer_delivery_result(
        "reservation-291", "documents_prompt", sent=False, now=BASE,
    )
    assert workflow.reminder_plan(now=BASE) == due
    workflow.record_customer_delivery_result(
        "reservation-291", "documents_prompt", sent=True, now=BASE,
    )
    assert workflow.reminder_plan(now=BASE) == []
    workflow.set_identity_type(
        "reservation-291", "passport", message_id="identity-passport-291",
    )
    conn = sqlite3.connect(workflow.state_registry.DB_PATH)
    revision_after_first_request = conn.execute(
        "SELECT revision FROM ali_reservations WHERE public_id='reservation-291'",
    ).fetchone()[0]
    conn.close()
    assert dossier.issue_document_links(
        "reservation-291", "reservation_v2_scheduler",
    ) == request
    conn = sqlite3.connect(workflow.state_registry.DB_PATH)
    assert conn.execute(
        "SELECT revision FROM ali_reservations WHERE public_id='reservation-291'",
    ).fetchone()[0] == revision_after_first_request
    conn.close()
    with pytest.raises(legacy.AliReservationError) as public_context:
        dossier.document_upload_context("unused-public-token")
    assert public_context.value.code == "public_document_upload_disabled"
    with pytest.raises(legacy.AliReservationError) as public_upload:
        dossier.store_document_upload(
            "unused-public-token", _png(), "image/png",
        )
    assert public_upload.value.code == "public_document_upload_disabled"
    stored = dossier.store_whatsapp_document(
        "reservation-291",
        slot="unclassified",
        payload=_png(),
        claimed_mime="image/png",
        provider_message_id="provider-message-291",
        provider_attachment_id="provider-attachment-291",
        filename="synthetic.png",
        classification_source="unclassified",
    )
    conn = sqlite3.connect(workflow.state_registry.DB_PATH)
    revision = conn.execute(
        "SELECT revision FROM ali_reservations WHERE public_id='reservation-291'",
    ).fetchone()[0]
    conn.close()
    reassigned = dossier.reclassify_whatsapp_document(
        "reservation-291", stored["public_id"], "passport", "staff-291",
        expected_revision=revision,
    )
    assert reassigned["slot"] == "passport"
    assert reassigned["status"] == "received"
    assert reassigned["classification_source"] == "staff_reclassified"
    assert reassigned["unclassified_expires_at"] is None
    assert reassigned["workflowV2"]["expectedDocumentSlot"] == "license_front"

    with pytest.raises(legacy.AliReservationError) as missing_reason:
        dossier.review_document(
            "reservation-291", stored["public_id"], "rejected", "staff-291",
        )
    assert missing_reason.value.code == "document_review_reason_required"


def test_identity_choice_is_required_before_first_document(configured):
    workflow.initialize_reservation("reservation-291", now=BASE)
    workflow.transition(
        "reservation-291", "documents_collecting", actor_type="staff",
        actor_id="staff-291", idempotency_key="approve-docs", now=BASE,
    )
    selected = workflow.set_identity_type(
        "reservation-291", "Passport", message_id="identity-choice-291",
    )
    assert selected["identityType"] == "passport"
    assert selected["expectedDocumentSlot"] == "passport"
    assert workflow.required_document_slots("passport") == (
        "passport", "license_front", "license_back",
    )
    assert workflow.required_document_slots("id_card") == (
        "identity_front", "identity_back", "license_front", "license_back",
    )


def test_single_file_approval_advances_only_the_legacy_identity_rollup(configured):
    workflow.initialize_reservation("reservation-291", now=BASE)
    legacy.apply_staff_decision(
        "reservation-291", "approve", "staff-291",
    )
    workflow.set_identity_type(
        "reservation-291", "passport", message_id="identity-choice-291",
    )
    for index in range(3):
        slot = workflow.get_case("reservation-291")["expectedDocumentSlot"]
        assert slot in {"passport", "license_front", "license_back"}
        dossier.store_whatsapp_document(
            "reservation-291",
            slot=slot,
            payload=_png((9 + index, 37, 60)),
            claimed_mime="image/png",
            provider_message_id=f"provider-message-{index}",
            provider_attachment_id=f"provider-attachment-{index}",
            filename=f"synthetic-{index}.png",
            classification_source="expected_slot",
        )

    before = legacy.get_reservation("reservation-291")
    assert before["identity_status"] == "received"
    approved = dossier.record_prepayment_file_approval(
        "reservation-291", "dashboard",
    )

    assert approved["identity_status"] == "verified"
    assert {
        document["status"]
        for document in dossier.list_documents("reservation-291")
    } == {"received"}


def test_replayed_identity_choice_does_not_reset_document_progress(configured):
    workflow.initialize_reservation("reservation-291", now=BASE)
    workflow.transition(
        "reservation-291", "documents_collecting", actor_type="staff",
        actor_id="staff-291", idempotency_key="approve-docs-replay", now=BASE,
    )
    selected = workflow.set_identity_type(
        "reservation-291", "Passport", message_id="identity-choice-first",
    )
    conn = sqlite3.connect(workflow.state_registry.DB_PATH)
    conn.execute(
        "UPDATE ali_reservation_v2_cases SET expected_document_slot = ? "
        "WHERE tenant_slug = ? AND reservation_public_id = ?",
        ("license_back", "ali-car-rental", "reservation-291"),
    )
    conn.commit()
    conn.close()

    replayed = workflow.set_identity_type(
        "reservation-291", "passport", message_id="identity-choice-replay",
    )

    assert selected["expectedDocumentSlot"] == "passport"
    assert replayed["identityType"] == "passport"
    assert replayed["expectedDocumentSlot"] == "license_back"
    with pytest.raises(legacy.AliReservationError) as changed:
        workflow.set_identity_type(
            "reservation-291", "ID card", message_id="identity-choice-change",
        )
    assert changed.value.code == "identity_type_change_requires_staff"


def test_early_payment_verification_requires_and_audits_reason(
    configured, monkeypatch,
):
    dossier.ensure_schema()
    conn = sqlite3.connect(workflow.state_registry.DB_PATH)
    conn.execute(
        "UPDATE ali_reservations SET availability_status='approved', "
        "payment_status='link_sent' WHERE public_id='reservation-291'",
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        "agents.social.ali_reservation_v2_automation.after_payment_review",
        lambda _public_id, _decision: {"handled": True},
    )

    with pytest.raises(legacy.AliReservationError) as missing_reason:
        dossier.review_payment(
            "reservation-291", "verified", "staff-291",
        )
    assert missing_reason.value.code == "payment_review_reason_required"

    verified = dossier.review_payment(
        "reservation-291",
        "verified",
        "staff-291",
        reason="Owner verified the bank receipt directly.",
    )
    assert verified["payment_status"] == "verified"
    conn = sqlite3.connect(workflow.state_registry.DB_PATH)
    conn.row_factory = sqlite3.Row
    payment = conn.execute(
        "SELECT review_reason, verified_at FROM ali_reservation_payments "
        "WHERE reservation_public_id='reservation-291'",
    ).fetchone()
    conn.close()
    assert payment["review_reason"] == "Owner verified the bank receipt directly."
    assert payment["verified_at"]
    events = legacy.list_reservation_events("reservation-291")
    event = next(
        item for item in events
        if item["event_type"] == "payment_reviewed"
    )
    assert event["metadata"] == {
        "decision": "verified",
        "override": True,
        "reason_present": True,
    }
