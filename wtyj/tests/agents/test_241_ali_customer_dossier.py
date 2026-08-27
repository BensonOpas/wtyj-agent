"""Issue 241: secure Ali customer-file workflow."""

from __future__ import annotations

import base64
import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
from pypdf import PdfReader

from agents.social import ali_customer_dossier as dossier
from agents.social import ali_quote_workflow as quotes
from agents.social import ali_reservation_workflow as reservations


CLASS_ID = "30000000-0000-4000-8000-000000000001"
DEPOSIT_ID = "90000000-0000-4000-8000-000000000001"
SNAPSHOT_ID = "70000000-0000-4000-8000-000000000001"


def _png(color=(12, 38, 60)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (320, 200), color).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def configured(monkeypatch, tmp_path):
    template = tmp_path / "approved-contract-v1.txt"
    template.write_text(
        "Customer: {customer_name}\nQuote: {quote_reference}\n"
        "Rental: {rental_start} to {rental_end}\nVehicle: {vehicle}\n"
        "Rental total: {rental_total}\nRefundable deposit: {refundable_deposit}\n"
        "Grand total: {grand_total}\n",
        encoding="utf-8",
    )
    raw = {
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
        "features": {
            "ali_quote_automation": True,
            "ali_customer_dossier_enabled": True,
        },
        "ali_customer_dossier": {
            "contract_template_path": str(template),
            "contract_template_version": "owner-approved-v1",
            "payment_allowed_domains": ["pay.example.test"],
            "document_retention_days": 30,
            "paper_shredding_policy": "Cross-cut shred after approved retention period.",
            "private_storage_root": str(tmp_path / "private"),
            "link_ttl_seconds": 1800,
        },
    }
    monkeypatch.setattr(dossier.state_registry, "DB_PATH", str(tmp_path / "tenant.db"))
    monkeypatch.setattr(dossier.config_loader, "get_raw", lambda: raw)
    monkeypatch.setenv("ALI_RESERVATION_TOKEN_SECRET", "synthetic-token-secret-for-issue-241")
    monkeypatch.setenv("UNBOKS_PUBLIC_BASE_URL", "https://api.example.test/api/ali-car-rental")
    return {"root": tmp_path, "raw": raw}


def _pricing() -> dict:
    created = datetime.now(timezone.utc)
    return {
        "quoteSnapshotId": SNAPSHOT_ID,
        "quoteReference": "ALI-20990101-DOSSIER",
        "catalogVersion": 1,
        "availabilityMode": "request_only",
        "currency": "USD",
        "rentalDays": 7,
        "items": [],
        "rentalTotal": {"currency": "USD", "amount": "280.00"},
        "refundableSecurityDeposit": {"currency": "USD", "amount": "200.00"},
        "reservationDeposit": {"currency": "USD", "amount": "70.00"},
        "total": {"currency": "USD", "amount": "480.00"},
        "createdAt": created.isoformat().replace("+00:00", "Z"),
        "expiresAt": (created + timedelta(days=3650)).isoformat().replace("+00:00", "Z"),
    }


def _reservation(raw: dict) -> dict:
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
    _, digest = quotes.normalized_summary(customer, rental)
    quote, _ = quotes.create_confirmed_quote(
        "conversation-241",
        "account-241",
        customer,
        rental,
        digest,
        "yes",
        DEPOSIT_ID,
        raw_config=raw,
    )
    pricing = _pricing()
    quote = quotes.update_quote(
        quote["public_id"],
        status="complete",
        quote_reference=pricing["quoteReference"],
        quote_snapshot_id=pricing["quoteSnapshotId"],
        pricing_json=json.dumps(pricing),
        expires_at=pricing["expiresAt"],
        whatsapp_status="accepted",
    )
    created = reservations.handle_exact_reserve(
        quote["conversation_id"], quote["zernio_account_id"], "reserve-241",
    )["reservation"]
    return reservations.apply_staff_decision(
        created["public_id"], "approve", "staff-241",
        expected_revision=created["revision"],
    )


def _upload_all(reservation: dict) -> list[dict]:
    links = dossier.issue_document_links(reservation["public_id"], "staff-241")["links"]
    by_slot = {item["slot"]: item for item in links}
    documents = []
    for slot in ("license_front", "identity"):
        token = by_slot[slot]["url"].rsplit("/", 1)[-1]
        payload = _png()
        uploaded = dossier.store_document_upload(token, payload, "image/png")
        replay = dossier.store_document_upload(token, payload, "image/png")
        assert replay["public_id"] == uploaded["public_id"]
        documents.append(uploaded)
    documents.append(dossier.mark_document_slot_not_required(
        reservation["public_id"], "license_back", "staff-241",
    ))
    for document in documents:
        if document["slot"] != "license_back":
            dossier.review_document(
                reservation["public_id"], document["public_id"], "verified", "staff-241",
            )
    return documents


def test_complete_customer_file_is_human_gated_and_printable(configured):
    case = _reservation(configured["raw"])
    documents = _upload_all(case)

    contract_link = dossier.issue_contract_link(case["public_id"], "staff-241")
    contract_token = contract_link["url"].rsplit("/", 1)[-1]
    viewed = dossier.contract_review_context(contract_token)
    assert viewed["contract"]["status"] == "viewed"
    signature = "data:image/png;base64," + base64.b64encode(_png((1, 1, 1))).decode()
    signed = dossier.sign_contract(
        contract_token,
        consent=True,
        legal_name="Synthetic Customer",
        signature_data=signature,
    )
    assert signed["status"] == "signed"
    assert dossier.sign_contract(
        contract_token,
        consent=True,
        legal_name="Synthetic Customer",
        signature_data=signature,
    )["public_id"] == signed["public_id"]

    dossier.set_payment_link(
        case["public_id"],
        "https://pay.example.test/deposit/synthetic-241",
        "SYNTH-241",
        "staff-241",
    )
    dossier.mark_payment_link_sent(case["public_id"], "staff-241")
    reported = dossier.record_customer_payment_report(
        "conversation-241", "account-241", "message-241",
    )
    assert reported["payment_status"] == "customer_reports_paid"
    assert reported["status"] == "requirements_pending"

    ready = dossier.review_payment(case["public_id"], "verified", "staff-241")
    assert ready["status"] == "ready_to_confirm"
    customer_file = dossier.get_customer_file(case["public_id"])
    assert customer_file["dossier_status"] == "ready_for_review"
    assert customer_file["payment"]["status"] == "verified"
    assert "url" not in customer_file["payment"]
    assert {item["slot"] for item in customer_file["documents"]} == {
        "license_front", "license_back", "identity",
    }

    printed = dossier.generate_dossier(case["public_id"], "staff-241")
    assert printed["status"] == "ready_for_review"
    assert printed["pageCount"] >= 5
    assert PdfReader(io.BytesIO(printed["bytes"])).pages

    confirmed = reservations.confirm_reservation(
        case["public_id"],
        "staff-241",
        output_root=str(configured["root"] / "confirmations"),
        logo_path=str(configured["root"] / "no-logo.png"),
    )
    assert confirmed["status"] == "confirmed"
    assert len([event for event in reservations.list_reservation_events(case["public_id"])
                if event["event_type"] == "reservation_confirmed"]) == 1
    assert len(documents) == 3


def test_security_gates_fail_closed_without_mutating_state(configured):
    dossier.ensure_schema()
    case = reservations.handle_exact_reserve(
        *_create_minimal_delivered_quote(configured["raw"]),
    )["reservation"]
    with pytest.raises(reservations.AliReservationError) as unavailable:
        dossier.issue_document_links(case["public_id"], "staff-241")
    assert unavailable.value.code == "availability_approval_required"

    case = reservations.apply_staff_decision(case["public_id"], "approve", "staff-241")
    link = dossier.issue_document_links(case["public_id"], "staff-241")["links"][0]
    token = link["url"].rsplit("/", 1)[-1]
    with pytest.raises(reservations.AliReservationError):
        dossier.store_document_upload(token + "x", _png(), "image/png")
    with pytest.raises(reservations.AliReservationError) as mismatch:
        dossier.store_document_upload(token, b"MZ executable", "image/png")
    assert mismatch.value.code == "document_content_type_mismatch"

    uploaded = dossier.store_document_upload(token, _png(), "image/png")
    with pytest.raises(reservations.AliReservationError) as replay:
        dossier.store_document_upload(token, _png((200, 1, 1)), "image/png")
    assert replay.value.code == "upload_replay_mismatch"
    assert dossier.document_bytes(case["public_id"], uploaded["public_id"])[1] == "image/png"

    listed = reservations.list_reservations()
    serialized = json.dumps(listed)
    assert "final_notes" not in serialized
    assert "confirmation_pdf_path" not in serialized
    conn = sqlite3.connect(dossier.state_registry.DB_PATH)
    stored = conn.execute(
        "SELECT storage_name FROM ali_reservation_documents WHERE public_id = ?",
        (uploaded["public_id"],),
    ).fetchone()[0]
    conn.close()
    assert "Synthetic Customer" not in stored


def test_replacement_link_is_fresh_and_pickup_checks_are_durable(configured):
    case = _reservation(configured["raw"])
    links = dossier.issue_document_links(case["public_id"], "staff-241")["links"]
    front_token = next(
        item["url"].rsplit("/", 1)[-1]
        for item in links
        if item["slot"] == "license_front"
    )
    original = dossier.store_document_upload(front_token, _png(), "image/png")
    revision = reservations.get_reservation(case["public_id"])["revision"]

    replacement = dossier.request_document_replacement(
        case["public_id"],
        original["public_id"],
        "staff-241",
        expected_revision=revision,
    )

    assert replacement["document"]["status"] == "replacement_requested"
    assert replacement["links"][0]["slot"] == "license_front"
    replacement_token = replacement["links"][0]["url"].rsplit("/", 1)[-1]
    assert replacement_token != front_token
    uploaded = dossier.store_document_upload(
        replacement_token,
        _png((40, 80, 120)),
        "image/png",
    )
    assert uploaded["version"] == 2
    assert uploaded["previous_document_public_id"] == original["public_id"]

    completed = _upload_all(case)
    assert completed
    contract_link = dossier.issue_contract_link(case["public_id"], "staff-241")
    contract_token = contract_link["url"].rsplit("/", 1)[-1]
    dossier.contract_review_context(contract_token)
    signature = "data:image/png;base64," + base64.b64encode(_png((1, 1, 1))).decode()
    dossier.sign_contract(
        contract_token,
        consent=True,
        legal_name="Synthetic Customer",
        signature_data=signature,
    )
    dossier.set_payment_link(
        case["public_id"],
        "https://pay.example.test/deposit/synthetic-pickup",
        "SYNTH-PICKUP",
        "staff-241",
    )
    dossier.mark_payment_link_sent(case["public_id"], "staff-241")
    dossier.review_payment(case["public_id"], "verified", "staff-241")
    dossier.generate_dossier(case["public_id"], "staff-241")
    confirmed = reservations.confirm_reservation(
        case["public_id"],
        "staff-241",
        output_root=str(configured["root"] / "confirmations"),
        logo_path=str(configured["root"] / "no-logo.png"),
    )

    inspected_license = reservations.record_original_document_inspection(
        case["public_id"],
        "license",
        "staff-241",
        expected_revision=confirmed["revision"],
    )
    replay = reservations.record_original_document_inspection(
        case["public_id"],
        "license",
        "staff-241",
        expected_revision=inspected_license["revision"],
    )
    inspected_identity = reservations.record_original_document_inspection(
        case["public_id"],
        "identity",
        "staff-241",
        expected_revision=replay["revision"],
    )

    assert inspected_identity["pickup_checklist"] == {
        "original_license_inspected": True,
        "original_license_inspected_at": inspected_license["pickup_checklist"][
            "original_license_inspected_at"
        ],
        "original_license_inspected_by": "staff-241",
        "original_identity_inspected": True,
        "original_identity_inspected_at": inspected_identity["pickup_checklist"][
            "original_identity_inspected_at"
        ],
        "original_identity_inspected_by": "staff-241",
    }


@pytest.mark.parametrize(
    "text",
    [
        "I've paid the deposit",
        "Ik heb betaald",
        "Mi a paga e deposito",
        "Ich habe bezahlt",
    ],
)
def test_clear_multilingual_payment_reports_are_recognized(text):
    assert dossier.is_customer_payment_report(text)


@pytest.mark.parametrize(
    "text",
    [
        "Did you receive my payment?",
        "How much do I pay?",
        "I will pay tomorrow",
        "Can I pay by card?",
        "not paid",
    ],
)
def test_payment_questions_and_uncertain_statements_never_mutate_state(text):
    assert not dossier.is_customer_payment_report(text)


def test_dashboard_settings_activate_immutable_template_and_hide_payment_url(configured):
    saved = dossier.save_tenant_settings(
        payment_mode="fixed_link",
        payment_provider_name="Synthetic Pay",
        payment_url="https://pay.example.test/tenant/ali",
        clear_payment_url=False,
        payment_allowed_domains=[],
        document_retention_days=90,
        paper_shredding_policy="Securely shred paper copies after 90 days.",
        actor="staff-241",
    )

    assert saved["payment"] == {
        "mode": "fixed_link",
        "providerName": "Synthetic Pay",
        "defaultLinkConfigured": True,
        "defaultDomain": "pay.example.test",
        "allowedDomains": ["pay.example.test"],
    }
    assert "https://" not in json.dumps(saved)
    assert saved["retention"]["documentRetentionDays"] == 90

    first = dossier.upload_contract_template(
        "owner-v2",
        "approved-contract.md",
        "text/markdown",
        b"Customer: {customer_name}\nQuote: {quote_reference}\n",
        "staff-241",
    )
    replay = dossier.upload_contract_template(
        "owner-v2",
        "approved-contract.md",
        "text/markdown",
        b"Customer: {customer_name}\nQuote: {quote_reference}\n",
        "staff-241",
    )

    assert first["contractTemplate"]["publicId"] == replay["contractTemplate"]["publicId"]
    assert first["contractTemplate"]["version"] == "owner-v2"
    assert first["status"]["configurationReady"] is True
    with pytest.raises(reservations.AliReservationError) as conflict:
        dossier.upload_contract_template(
            "owner-v2",
            "different.md",
            "text/markdown",
            b"Different approved content.",
            "staff-241",
        )
    assert conflict.value.code == "contract_template_version_already_exists"


def test_fixed_tenant_payment_link_can_be_applied_without_browser_readback(configured):
    dossier.save_tenant_settings(
        payment_mode="fixed_link",
        payment_provider_name="Synthetic Pay",
        payment_url="https://pay.example.test/tenant/ali",
        clear_payment_url=False,
        payment_allowed_domains=["pay.example.test"],
        document_retention_days=90,
        paper_shredding_policy="Securely shred paper copies after 90 days.",
        actor="staff-241",
    )
    case = _reservation(configured["raw"])

    saved = dossier.set_payment_link(
        case["public_id"], "", "SYNTHETIC-REF", "staff-241",
    )
    customer_file = dossier.get_customer_file(case["public_id"])

    assert saved["paymentDomain"] == "pay.example.test"
    assert customer_file["payment"]["tenantDefaultAvailable"] is True
    assert customer_file["payment"]["domain"] == "pay.example.test"
    assert "url" not in customer_file["payment"]

    with pytest.raises(reservations.AliReservationError) as removed_domain:
        dossier.save_tenant_settings(
            payment_mode="fixed_link",
            payment_provider_name="Synthetic Pay",
            payment_url=None,
            clear_payment_url=False,
            payment_allowed_domains=["different.example.test"],
            document_retention_days=90,
            paper_shredding_policy="Securely shred paper copies after 90 days.",
            actor="staff-241",
        )
    assert removed_domain.value.code == "payment_url_not_allowed"


def test_retention_deletes_private_bytes_after_rental_window(configured):
    dossier.save_tenant_settings(
        payment_mode="per_reservation",
        payment_provider_name="Synthetic Pay",
        payment_url=None,
        clear_payment_url=True,
        payment_allowed_domains=["pay.example.test"],
        document_retention_days=90,
        paper_shredding_policy="Securely shred paper copies after 90 days.",
        actor="staff-241",
    )
    case = _reservation(configured["raw"])
    link = dossier.issue_document_links(case["public_id"], "staff-241")["links"][0]
    document = dossier.store_document_upload(
        link["url"].rsplit("/", 1)[-1], _png(), "image/png",
    )
    stored_before, _ = dossier.document_bytes(case["public_id"], document["public_id"])
    assert stored_before
    conn = sqlite3.connect(dossier.state_registry.DB_PATH)
    conn.execute(
        "UPDATE ali_reservations SET status = 'confirmed' WHERE public_id = ?",
        (case["public_id"],),
    )
    conn.commit()
    conn.close()

    result = dossier.purge_expired_documents(
        datetime(2200, 1, 1, tzinfo=timezone.utc),
    )

    assert result == {"documentsDeleted": 1, "retentionDays": 90}
    with pytest.raises(reservations.AliReservationError) as missing:
        dossier.document_bytes(case["public_id"], document["public_id"])
    assert missing.value.code == "document_not_found"
    conn = sqlite3.connect(dossier.state_registry.DB_PATH)
    row = conn.execute(
        "SELECT status, storage_name, sha256, size_bytes FROM ali_reservation_documents "
        "WHERE public_id = ?",
        (document["public_id"],),
    ).fetchone()
    conn.close()
    assert row == ("deleted", None, None, 0)


def _create_minimal_delivered_quote(raw: dict) -> tuple[str, str]:
    customer = {"name": "Synthetic Customer", "whatsapp": "+59990000000"}
    rental = {
        "rental_start": "2099-09-01",
        "rental_end": "2099-09-08",
        "pickup_location": "Synthetic pickup",
        "return_location": "Synthetic return",
        "vehicle_class_id": CLASS_ID,
        "vehicle_class_name": "Small car",
        "driver_age": 40,
        "extra_ids": [],
        "conversation_language": "en",
    }
    _, digest = quotes.normalized_summary(customer, rental)
    quote, _ = quotes.create_confirmed_quote(
        "conversation-minimal", "account-minimal", customer, rental, digest,
        "yes", DEPOSIT_ID, raw_config=raw,
    )
    pricing = _pricing()
    quotes.update_quote(
        quote["public_id"], status="complete",
        quote_reference=pricing["quoteReference"],
        quote_snapshot_id=pricing["quoteSnapshotId"],
        pricing_json=json.dumps(pricing), expires_at=pricing["expiresAt"],
        whatsapp_status="accepted",
    )
    return "conversation-minimal", "account-minimal"
