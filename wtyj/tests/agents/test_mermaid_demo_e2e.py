"""Issue 333: full synthetic Mermaid WhatsApp reservation journeys."""

from pathlib import Path
import re
from urllib.parse import urlparse

import pytest
from pypdf import PdfReader

from agents.social import (
    mermaid_demo_payment,
    mermaid_documents,
    mermaid_reservation_store,
    mermaid_reservation_workflow,
)
from shared import config_loader, mermaid_catalog, state_registry


ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "clients" / "mermaid" / "config" / "client.json"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(CONFIG))
    monkeypatch.setattr(config_loader, "_cache", {})
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("MERMAID_DOCUMENT_ROOT", str(tmp_path / "documents"))
    monkeypatch.setenv("MERMAID_DEMO_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("UNBOKS_PUBLIC_BASE_URL", "https://demo.example")


JOURNEYS = [
    ("en", "English: My name is Ana Silva. Date 2026-09-05, 2 adults, 1 child, 0 infants, meet at Fishermen's Pier.", "yes"),
    ("nl", "Nederlands: Mijn naam is Ana Silva. Datum 2026-09-05, 2 volwassenen, 1 kind, 0 baby's, Fishermen's Pier.", "ja"),
    ("de", "Deutsch: Ich heiße Ana Silva. Datum 2026-09-05, 2 Erwachsene, 1 Kind, 0 Kleinkinder, Fishermen's Pier.", "ja"),
    ("es", "Español: Me llamo Ana Silva. Fecha 2026-09-05, 2 adultos, 1 niño, 0 bebés, Fishermen's Pier.", "sí"),
    ("pap", "Papiamentu: Mi nòmber ta Ana Silva. Fecha 2026-09-05, 2 adulto, 1 mucha di 4, 0 mucha di 0, Fishermen's Pier.", "si"),
    ("pt", "Português: Meu nome é Ana Silva. Data 2026-09-05, 2 adultos, 1 criança, 0 bebês, Fishermen's Pier.", "sim"),
]


def _payment_token(reply: dict) -> tuple[str, int, str]:
    url = re.search(r"https://unboks\.org/mermaid/pay/[^\s]+", reply["text"]).group(0)
    parsed = urlparse(url)
    assert not parsed.query and len(parsed.path.rsplit("/",1)[-1])==22
    return mermaid_demo_payment.resolve_checkout_token(parsed.path.rsplit("/",1)[-1])


def _pdf_text(path: str) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


@pytest.mark.parametrize("locale,opening,confirmation", JOURNEYS)
def test_full_six_language_whatsapp_journey(locale, opening, confirmation, monkeypatch):
    phone = f"synthetic-{locale}"
    summary = mermaid_reservation_workflow.handle_demo_message({
        "from": phone,
        "from_name": "Ana Silva",
        "text": opening,
        "message_id": f"{locale}-opening",
        "_zernio_account_id": "synthetic-account",
    }, include_media=True)
    assert summary["media"] is None
    assert state_registry.wa_get_booking_state(phone)["fields"]["mermaid_intake"]["phase"] == "collecting"
    summary = mermaid_reservation_workflow.handle_demo_message({
        "from": phone, "text": "+1 202 555 0123", "message_id": f"{locale}-contact",
        "_zernio_account_id": "synthetic-account",
    }, include_media=True)
    intake = state_registry.wa_get_booking_state(phone)["fields"]["mermaid_intake"]
    assert intake["contact_phone"] == "+12025550123"
    assert intake["language"] == locale
    assert intake["phase"] == "awaiting_summary_confirmation"
    assert intake["trip_date"] == "2026-09-05"
    assert (intake["adults"], intake["children"], intake["infants"]) == (2, 1, 0)
    assert intake["customer_name"] == "Ana Silva"
    assert intake["pickup_preference"] == "pier"

    quote_reply = mermaid_reservation_workflow.handle_demo_message({
        "from": phone,
        "from_name": "Ana Silva",
        "text": confirmation,
        "message_id": f"{locale}-confirm",
        "_zernio_account_id": "synthetic-account",
    }, include_media=True)
    assert quote_reply["media"]["type"] == "file"
    assert quote_reply["media"]["filename"].endswith(".pdf")
    assert "demo" in quote_reply["text"].casefold()
    reservation_id, expires, signature = _payment_token(quote_reply)
    reservation = mermaid_reservation_store.get_reservation(reservation_id)
    assert reservation["state"] == "demo_payment_pending"
    assert reservation["availability_source"] == "demo_assumed"
    assert reservation["language"] == locale
    assert reservation["monetary_snapshot"]["total"] == 375
    assert reservation["booking_code"].startswith("MER-DEMO-")

    documents = mermaid_documents.documents_for_reservation(reservation_id)
    assert [item["kind"] for item in documents] == ["quote"]
    quote_path = Path(__import__("os").environ["MERMAID_DOCUMENT_ROOT"]) / reservation_id / quote_reply["media"]["filename"]
    quote_text = _pdf_text(str(quote_path))
    assert "USD 375.00" in quote_text
    assert "06:45" in quote_text and "15:20" in quote_text

    sends = []
    monkeypatch.setattr(mermaid_demo_payment, "send_reply", lambda *args, **kwargs: sends.append((args, kwargs)) or True)
    monkeypatch.setattr(mermaid_demo_payment.time, "time", lambda: expires - 3600)
    result = mermaid_demo_payment.complete_checkout(reservation_id, expires, signature, "success")
    replay = mermaid_demo_payment.complete_checkout(reservation_id, expires, signature, "success")
    assert result.status_code == replay.status_code == 200

    booked = mermaid_reservation_store.get_reservation(reservation_id)
    assert booked["state"] == "booked"
    assert len(sends) == 1
    sent_args, sent_kwargs = sends[0]
    assert sent_args[1] == phone
    assert booked["booking_code"] in sent_args[3]
    assert "USD 375.00" in sent_args[3]
    assert sent_kwargs["attachment_type"] == "file"
    assert sent_kwargs["idempotency_key"] == f"mermaid-receipt:{reservation_id}"

    documents = mermaid_documents.documents_for_reservation(reservation_id)
    assert [item["kind"] for item in documents] == ["quote", "receipt"]
    assert documents[1]["delivery_status"] == "delivered"
    receipt_name = next(Path(__import__("os").environ["MERMAID_DOCUMENT_ROOT"]).joinpath(reservation_id).glob("*Receipt*.pdf"))
    receipt_text = _pdf_text(str(receipt_name))
    assert booked["booking_code"] in receipt_text
    assert "USD 375.00" in receipt_text
    assert "SIMULATED PAYMENT - DEMO ONLY" in receipt_text


def test_duplicate_confirmation_cancel_retry_and_delivery_recovery(monkeypatch):
    phone = "synthetic-retries"
    opening = JOURNEYS[0][1]
    mermaid_reservation_workflow.handle_demo_message({
        "from": phone, "text": opening, "message_id": "opening",
    }, include_media=True)
    mermaid_reservation_workflow.handle_demo_message({
        "from": phone, "text": "+1 202 555 0123", "message_id": "contact",
    }, include_media=True)
    first = mermaid_reservation_workflow.handle_demo_message({
        "from": phone, "text": "yes", "message_id": "confirm",
    }, include_media=True)
    duplicate = mermaid_reservation_workflow.handle_demo_message({
        "from": phone, "text": "yes", "message_id": "confirm",
    }, include_media=True)
    assert duplicate["duplicate"] is True
    assert duplicate["media"] is None
    reservation_id, expires, signature = _payment_token(first)

    monkeypatch.setattr(mermaid_demo_payment.time, "time", lambda: expires - 3600)
    cancelled = mermaid_demo_payment.complete_checkout(reservation_id, expires, signature, "cancel")
    assert "No payment was recorded" in cancelled.body.decode()
    assert mermaid_reservation_store.get_reservation(reservation_id)["state"] == "demo_payment_pending"

    sends = []
    monkeypatch.setattr(mermaid_demo_payment, "send_reply", lambda *args, **kwargs: sends.append((args, kwargs)) or len(sends) > 1)
    mermaid_demo_payment.complete_checkout(reservation_id, expires, signature, "success")
    documents = mermaid_documents.documents_for_reservation(reservation_id)
    receipt = next(item for item in documents if item["kind"] == "receipt")
    assert receipt["delivery_status"] == "pending"
    assert receipt["delivery_attempts"] == 1

    from agents.social import mermaid_delivery_reconciliation
    def reconcile(job_id):
        mermaid_documents.mark_delivery(job_id, True, count_attempt=False)
        return "delivered"
    monkeypatch.setattr(mermaid_delivery_reconciliation, "reconcile_job", reconcile)
    mermaid_demo_payment.complete_checkout(reservation_id, expires, signature, "success")
    documents = mermaid_documents.documents_for_reservation(reservation_id)
    receipt = next(item for item in documents if item["kind"] == "receipt")
    assert receipt["delivery_status"] == "delivered"
    assert receipt["delivery_attempts"] == 1
    assert len(sends) == 1


def test_demo_flags_provide_immediate_safe_rollback():
    features = mermaid_catalog.demo_features()
    assert features["intake"] is True
    assert features["quote_delivery"] is True
    assert features["demo_payment"] is True
    assert features["dashboard_projection"] is True
    assert features["reminders"] is False
