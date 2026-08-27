import json
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from pypdf import PdfReader

from agents.social import ali_quote_workflow as quote_workflow
from agents.social import ali_quote_download
from agents.social import ali_quote_delivery
from agents.social import ali_reservation_workflow as workflow


SECRET = "synthetic-reservation-secret-123"
CLASS_ID = "30000000-0000-4000-8000-000000000001"
DEPOSIT_ID = "90000000-0000-4000-8000-000000000001"
SNAPSHOT_ID = "70000000-0000-4000-8000-000000000001"


def raw_config():
    return {
        "slug": "ali-car-rental",
        "workflow": {
            "type": "ali_quote",
            "required_deposit_charge_id": DEPOSIT_ID,
            "post_quote": {
                "required_checks": {
                    "identity": True,
                    "agreement": True,
                    "payment": True,
                }
            },
        },
        "features": {"ali_quote_automation": True},
    }


@pytest.fixture
def configured(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow.state_registry, "DB_PATH", str(tmp_path / "tenant.db"))
    monkeypatch.setattr(workflow.config_loader, "get_raw", raw_config)
    return tmp_path


def _pricing():
    created = datetime.now(timezone.utc)
    return {
        "quoteSnapshotId": SNAPSHOT_ID,
        "quoteReference": "ALI-20990101-TEST1234",
        "catalogVersion": 1,
        "availabilityMode": "request_only",
        "currency": "USD",
        "rentalDays": 7,
        "items": [
            {
                "code": "vehicle.weekly",
                "category": "vehicle",
                "description": "Small car - weekly rate",
                "quantity": 1,
                "refundable": False,
                "unitPrice": {"currency": "USD", "amount": "280.00"},
                "total": {"currency": "USD", "amount": "280.00"},
            },
            {
                "code": "charge.deposit",
                "category": "security_deposit",
                "description": "Refundable security deposit",
                "quantity": 1,
                "refundable": True,
                "unitPrice": {"currency": "USD", "amount": "200.00"},
                "total": {"currency": "USD", "amount": "200.00"},
            },
        ],
        "rentalTotal": {"currency": "USD", "amount": "280.00"},
        "refundableSecurityDeposit": {"currency": "USD", "amount": "200.00"},
        "reservationDeposit": {"currency": "USD", "amount": "70.00"},
        "createdAt": created.isoformat().replace("+00:00", "Z"),
        "expiresAt": (created + timedelta(days=3650)).isoformat().replace("+00:00", "Z"),
    }


def _delivered_quote(conversation="conversation-one", account="account-one"):
    customer = {"name": "Synthetic Customer", "whatsapp": "+59990000000"}
    rental = {
        "rental_start": "2099-09-01",
        "rental_end": "2099-09-08",
        "pickup_location": "Synthetic airport pickup",
        "return_location": "Synthetic airport return",
        "vehicle_class_id": CLASS_ID,
        "vehicle_class_name": "Small car",
        "driver_age": 40,
        "extra_ids": [],
        "conversation_language": "en",
    }
    _, digest = quote_workflow.normalized_summary(customer, rental)
    quote, created = quote_workflow.create_confirmed_quote(
        conversation,
        account,
        customer,
        rental,
        digest,
        "yes",
        DEPOSIT_ID,
        raw_config=raw_config(),
    )
    assert created
    pricing = _pricing()
    return quote_workflow.update_quote(
        quote["public_id"],
        status="complete",
        quote_reference=pricing["quoteReference"],
        quote_snapshot_id=pricing["quoteSnapshotId"],
        pricing_json=json.dumps(pricing),
        expires_at=pricing["expiresAt"],
        whatsapp_status="accepted",
    )


def _reserve(quote):
    control = workflow.build_post_quote_control(quote, secret=SECRET)
    payload = control["buttons"][0]["payload"]
    interaction = workflow.resolve_post_quote_interaction(
        "button_reply",
        payload,
        quote["conversation_id"],
        quote["zernio_account_id"],
        secret=SECRET,
    )
    assert interaction["status"] == "current"
    return workflow.handle_post_quote_action(interaction, action_id="inbound-message-one")


def test_signed_controls_bind_every_quote_anchor_and_reject_tampering(configured):
    quote = _delivered_quote()
    control = workflow.build_post_quote_control(quote, secret=SECRET)

    assert [button["title"] for button in control["buttons"]] == [
        "Reserve this car", "Change something", "Ask a question",
    ]
    assert control["idempotency_key"].endswith(control["state_hash"])
    reserve_payload = control["buttons"][0]["payload"]

    current = workflow.resolve_post_quote_interaction(
        "buttonReply", reserve_payload, "conversation-one", "account-one", secret=SECRET,
    )
    assert current["status"] == "current"
    assert current["action"] == "reserve"
    assert current["quote_public_id"] == quote["public_id"]

    assert workflow.resolve_post_quote_interaction(
        "buttonReply", reserve_payload, "conversation-other", "account-one", secret=SECRET,
    )["status"] == "invalid"
    assert workflow.resolve_post_quote_interaction(
        "buttonReply", reserve_payload, "conversation-one", "account-other", secret=SECRET,
    )["status"] == "invalid"
    tampered = reserve_payload[:-1] + ("0" if reserve_payload[-1] != "0" else "1")
    assert workflow.resolve_post_quote_interaction(
        "buttonReply", tampered, "conversation-one", "account-one", secret=SECRET,
    )["status"] == "invalid"
    assert workflow.resolve_post_quote_interaction(
        "buttonReply", "unrelated", "conversation-one", "account-one", secret=SECRET,
    ) is None


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("en", "How would you like to proceed?"),
        ("nl", "Hoe wil je verdergaan?"),
        ("pap", "Kon bo ke sigui?"),
        ("de", "Wie möchten Sie fortfahren?"),
    ],
)
def test_post_quote_prompt_is_natural_in_every_supported_locale(
    configured, locale, expected,
):
    quote = {**_delivered_quote(), "locale": locale}

    control = workflow.build_post_quote_control(quote, secret=SECRET)

    assert control["text"] == expected
    assert len(control["buttons"]) == 3


def test_reserve_is_exactly_once_and_never_claims_booking_confirmation(configured):
    quote = _delivered_quote()
    first = _reserve(quote)
    assert first["status"] == "created"
    assert first["reservation"]["status"] == "availability_pending"
    assert first["reservation"]["availability_status"] == "pending"
    assert "availability" in first["text"].lower()
    assert "booked" not in first["text"].lower()
    assert "confirmed" not in first["text"].lower()

    control = workflow.build_post_quote_control(quote, secret=SECRET)
    repeated_interaction = workflow.resolve_post_quote_interaction(
        "buttonReply",
        control["buttons"][0]["payload"],
        quote["conversation_id"],
        quote["zernio_account_id"],
        secret=SECRET,
    )
    assert repeated_interaction["status"] == "repeated"
    repeated = workflow.handle_post_quote_action(repeated_interaction, action_id="retry")
    assert repeated["status"] == "repeated"
    assert repeated["reservation"]["public_id"] == first["reservation"]["public_id"]
    assert len(workflow.list_reservation_events(first["reservation"]["public_id"])) == 1


def test_change_question_and_non_exact_fallback_do_not_create_cases(configured):
    quote = _delivered_quote()
    control = workflow.build_post_quote_control(quote, secret=SECRET)
    for index, expected in ((1, "change_requested"), (2, "question")):
        interaction = workflow.resolve_post_quote_interaction(
            "buttonReply",
            control["buttons"][index]["payload"],
            quote["conversation_id"],
            quote["zernio_account_id"],
            secret=SECRET,
        )
        result = workflow.handle_post_quote_action(interaction)
        assert result["status"] == expected
    assert workflow.list_reservations() == []
    assert workflow.is_exact_reserve_fallback("RESERVE")
    assert not workflow.is_exact_reserve_fallback("reserve")
    assert not workflow.is_exact_reserve_fallback("yes")

    fallback = workflow.handle_exact_reserve("conversation-one", "account-one")
    retry = workflow.handle_exact_reserve("conversation-one", "account-one")
    assert fallback["status"] == "created"
    assert retry["status"] == "repeated"
    assert fallback["reservation"]["public_id"] == retry["reservation"]["public_id"]


def test_staff_gates_confirmation_and_pdf_is_immutable_and_informational(configured):
    quote = _delivered_quote()
    reservation = _reserve(quote)["reservation"]
    with pytest.raises(workflow.AliReservationError) as blocked:
        workflow.confirm_reservation(reservation["public_id"], actor="staff-one")
    assert blocked.value.code == "confirmation_preconditions_not_met"
    assert blocked.value.status_code == 409

    approved = workflow.apply_staff_decision(
        reservation["public_id"], "approve", "staff-one",
        expected_revision=reservation["revision"],
    )
    assert approved["status"] == "requirements_pending"
    ready = workflow.update_checklist(
        reservation["public_id"],
        actor="staff-one",
        identity="verified",
        agreement="verified",
        payment="verified",
        expected_revision=approved["revision"],
    )
    assert ready["status"] == "ready_to_confirm"
    confirmed = workflow.confirm_reservation(
        reservation["public_id"],
        actor="staff-one",
        expected_revision=ready["revision"],
        output_root=str(configured / "confirmations"),
        logo_path=str(configured / "no-logo.png"),
    )
    assert confirmed["status"] == "confirmed"
    assert confirmed["confirmation_reference"].startswith("ALI-RSV-")
    assert confirmed["confirmation_pdf_sha256"]

    repeated = workflow.confirm_reservation(
        reservation["public_id"],
        actor="staff-one",
        expected_revision=1,
        output_root=str(configured / "confirmations"),
    )
    assert repeated["confirmation_reference"] == confirmed["confirmation_reference"]
    assert repeated["confirmation_pdf_path"] == confirmed["confirmation_pdf_path"]
    text = "\n".join(page.extract_text() or "" for page in PdfReader(
        confirmed["confirmation_pdf_path"]
    ).pages)
    assert "Reservation confirmation" in text
    assert "CONFIRMED" in text
    assert "not a rental agreement" in text
    assert "proof of payment" in text
    assert quote["quote_reference"] in text


def test_alternative_decline_events_and_delivery_failure_are_truthful(configured):
    quote = _delivered_quote()
    reservation = _reserve(quote)["reservation"]
    alternative = workflow.apply_staff_decision(
        reservation["public_id"],
        "alternative",
        "staff-one",
        alternative_vehicle={
            "vehicle_class_id": "class-suv",
            "vehicle_class_name": "Compact SUV",
            "daily_rate_usd": "65",
            "currency": "usd",
        },
    )
    assert alternative["status"] == "alternative_required"
    assert alternative["alternative_vehicle"]["daily_rate_usd"] == "65.00"
    with pytest.raises(workflow.AliReservationError):
        workflow.apply_staff_decision(reservation["public_id"], "approve", "staff-one")

    second_quote = _delivered_quote("conversation-two", "account-one")
    second = _reserve(second_quote)["reservation"]
    declined = workflow.apply_staff_decision(second["public_id"], "decline", "staff-one")
    assert declined["status"] == "declined"

    conn = sqlite3.connect(workflow.state_registry.DB_PATH)
    event_id = conn.execute(
        "SELECT id FROM ali_reservation_events WHERE reservation_public_id = ? ORDER BY id LIMIT 1",
        (reservation["public_id"],),
    ).fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM ali_reservation_events WHERE id = ?", (event_id,))
    conn.close()


def test_confirmation_delivery_failure_does_not_undo_confirmation(configured):
    quote = _delivered_quote()
    reservation = _reserve(quote)["reservation"]
    approved = workflow.apply_staff_decision(reservation["public_id"], "approve", "staff")
    ready = workflow.update_checklist(
        reservation["public_id"], actor="staff",
        identity="not_required", agreement="not_required", payment="not_required",
    )
    confirmed = workflow.confirm_reservation(
        reservation["public_id"], actor="staff",
        output_root=str(configured / "confirmations"),
        logo_path=str(configured / "no-logo.png"),
    )
    failed = workflow.record_confirmation_delivery(
        reservation["public_id"], "failed", error_code="provider_unavailable",
    )
    assert approved["status"] == "requirements_pending"
    assert ready["status"] == "ready_to_confirm"
    assert confirmed["status"] == "confirmed"
    assert failed["status"] == "confirmed"
    assert failed["confirmation_delivery_status"] == "failed"
    assert failed["confirmation_delivery_error_code"] == "provider_unavailable"


def test_confirmation_pdf_uses_private_signed_download(configured, monkeypatch):
    quote = _delivered_quote()
    reservation = _reserve(quote)["reservation"]
    approved = workflow.apply_staff_decision(
        reservation["public_id"], "approve", "staff",
    )
    ready = workflow.update_checklist(
        reservation["public_id"], actor="staff",
        identity="not_required", agreement="not_required", payment="not_required",
        expected_revision=approved["revision"],
    )
    output_root = configured / "confirmations"
    confirmed = workflow.confirm_reservation(
        reservation["public_id"], actor="staff",
        expected_revision=ready["revision"], output_root=str(output_root),
        logo_path=str(configured / "no-logo.png"),
    )
    monkeypatch.setenv("ALI_QUOTE_DOWNLOAD_SECRET", SECRET)
    monkeypatch.setenv("ALI_RESERVATION_DATA_ROOT", str(output_root))
    url = ali_quote_download.build_signed_url(
        "https://example.test", confirmed["public_id"], SECRET,
        asset="confirmation",
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    signed_id = parsed.path.rsplit("/", 1)[-1]
    response = ali_quote_download.quote_download_response(
        signed_id, int(query["expires"][0]), query["signature"][0],
    )
    assert response.status_code == 200
    assert confirmed["confirmation_reference"] in response.headers["content-disposition"]


def test_confirmation_send_failure_is_recorded_without_rollback(configured, monkeypatch):
    quote = _delivered_quote()
    reservation = _reserve(quote)["reservation"]
    approved = workflow.apply_staff_decision(
        reservation["public_id"], "approve", "staff",
    )
    ready = workflow.update_checklist(
        reservation["public_id"], actor="staff",
        identity="not_required", agreement="not_required", payment="not_required",
        expected_revision=approved["revision"],
    )
    confirmed = workflow.confirm_reservation(
        reservation["public_id"], actor="staff",
        expected_revision=ready["revision"],
        output_root=str(configured / "confirmations"),
        logo_path=str(configured / "no-logo.png"),
    )
    alerts = []
    monkeypatch.setenv("UNBOKS_PUBLIC_BASE_URL", "https://example.test")
    monkeypatch.setenv("ALI_QUOTE_DOWNLOAD_SECRET", SECRET)
    monkeypatch.setattr(
        ali_quote_delivery, "send_dm_reply_with_attachment", lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        ali_quote_delivery.state_registry,
        "create_pending_notification",
        lambda *args, **kwargs: alerts.append((args, kwargs)) or 290,
    )

    result = ali_quote_delivery.send_customer_reservation_confirmation(confirmed)

    assert result["status"] == "confirmed"
    assert result["confirmation_delivery_status"] == "failed"
    assert result["confirmation_delivery_error_code"] == "customer_confirmation_delivery_failed"
    assert len(alerts) == 1
