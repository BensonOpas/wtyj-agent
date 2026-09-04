"""Issue 331: no-money checkout, signed callback, and receipt."""

from pathlib import Path

import pytest
from pypdf import PdfReader

from agents.social import (
    mermaid_demo_payment, mermaid_documents, mermaid_reservation_store,
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


def pending(locale="en"):
    reservation = mermaid_reservation_store.confirm_reservation(
        f"guest-{locale}",
        {"trip_date": "2026-09-05", "adults": 2, "children": 1, "infants": 1,
         "customer_name": "Ana Silva", "pickup_preference": "pier", "language": locale,
         "phase": "summary_confirmed"},
        idempotency_key=f"confirm-{locale}", zernio_account_id="demo-account",
    )
    reservation = mermaid_reservation_store.transition(
        reservation["public_id"], "quote_ready", idempotency_key=f"quote-{locale}",
        actor="system", reason="test quote",
    )
    return mermaid_reservation_store.transition(
        reservation["public_id"], "demo_payment_pending", idempotency_key=f"pending-{locale}",
        actor="system", reason="test payment link",
    )


def token(reservation, now=1000):
    expires = now + 3600
    return expires, mermaid_demo_payment.sign_payment(reservation["public_id"], expires, "test-secret")


def test_checkout_contains_summary_but_no_real_payment_fields(monkeypatch):
    reservation = pending()
    expires, signature = token(reservation)
    monkeypatch.setattr(mermaid_demo_payment.time, "time", lambda: 1000)
    response = mermaid_demo_payment.checkout_page(reservation["public_id"], expires, signature)
    body = response.body.decode()
    assert response.status_code == 200
    assert "PAYMENT SIMULATION - NO MONEY" in body
    assert "Ana Silva" in body and "USD 375.00" in body
    assert "Simulate successful payment" in body
    for forbidden in ('name="card', 'name="account', 'name="password', "cvv", "iban"):
        assert forbidden not in body.casefold()


def test_cancel_and_invalid_signature_leave_reservation_pending(monkeypatch):
    reservation = pending()
    expires, signature = token(reservation)
    monkeypatch.setattr(mermaid_demo_payment.time, "time", lambda: 1000)
    invalid = mermaid_demo_payment.complete_checkout(reservation["public_id"], expires, "bad", "success")
    cancelled = mermaid_demo_payment.complete_checkout(reservation["public_id"], expires, signature, "cancel")
    assert invalid.status_code == 404
    assert "No payment was recorded" in cancelled.body.decode()
    assert mermaid_reservation_store.get_reservation(reservation["public_id"])["state"] == "demo_payment_pending"


def test_success_is_atomic_replay_safe_and_sends_one_receipt(monkeypatch):
    reservation = pending()
    expires, signature = token(reservation)
    monkeypatch.setattr(mermaid_demo_payment.time, "time", lambda: 1000)
    sends = []
    monkeypatch.setattr(mermaid_demo_payment, "send_reply", lambda *args, **kwargs: sends.append((args, kwargs)) or True)

    first = mermaid_demo_payment.complete_checkout(reservation["public_id"], expires, signature, "success")
    second = mermaid_demo_payment.complete_checkout(reservation["public_id"], expires, signature, "success")
    booked = mermaid_reservation_store.get_reservation(reservation["public_id"])
    assert first.status_code == second.status_code == 200
    assert booked["state"] == "booked"
    assert booked["booking_code"].startswith("MER-DEMO-")
    assert booked["payment_reference"].startswith("PAY-DEMO-")
    assert booked["receipt_public_id"].startswith("mdoc_")
    assert len(sends) == 1
    args, kwargs = sends[0]
    assert booked["booking_code"] in args[3]
    assert "06:45" in args[3]
    assert kwargs["attachment_type"] == "file"
    assert kwargs["attachment_name"].startswith("Mermaid - Demo Payment Receipt - ")
    assert kwargs["attachment_name"].endswith(".pdf")
    assert kwargs["confirm_delivery"] is True

    job = mermaid_documents.delivery_job(
        "mjob_" + __import__("hashlib").sha256(f"receipt:{reservation['public_id']}".encode()).hexdigest()[:24]
    )
    assert job["status"] == "delivered"
    events = mermaid_reservation_store.events(reservation["public_id"])
    assert [event["to_state"] for event in events[-2:]] == ["demo_paid", "booked"]


def test_receipt_is_a_payment_receipt_not_confirmation(monkeypatch):
    reservation = pending()
    expires, signature = token(reservation)
    monkeypatch.setattr(mermaid_demo_payment.time, "time", lambda: 1000)
    monkeypatch.setattr(mermaid_demo_payment, "send_reply", lambda *args, **kwargs: True)
    mermaid_demo_payment.complete_checkout(reservation["public_id"], expires, signature, "success")
    booked = mermaid_reservation_store.get_reservation(reservation["public_id"])
    conn = mermaid_documents._conn()
    try:
        document = dict(conn.execute("SELECT * FROM mermaid_documents WHERE public_id=?", (booked["receipt_public_id"],)).fetchone())
    finally:
        conn.close()
    reader = PdfReader(document["path"])
    assert len(reader.pages) == 1
    assert len(reader.pages[0].images) >= 1
    assert "Payment receipt" in reader.metadata.title
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "SIMULATED PAYMENT - DEMO ONLY" in text
    assert "Payment receipt" in text
    assert booked["booking_code"] in text
    assert "USD 375.00" in text
    assert "final confirmation" not in text.casefold()


@pytest.mark.parametrize("locale", ["en", "nl", "de", "es", "pap", "pt"])
def test_six_language_success_copy_is_warm_and_grounded(locale):
    reservation = pending(locale)
    payment = {"currency": "USD", "amount": 375}
    text = mermaid_demo_payment.success_message(reservation, payment)
    assert reservation["booking_code"] in text
    assert ("Saturday 5 September 2026" if locale == "en" else "2026-09-05") in text
    assert "USD 375.00" in text
    assert "06:45" in text
    assert "Mermaid" in text


def test_customer_text_cannot_mark_payment_paid():
    reservation = pending()
    reply = mermaid_reservation_workflow.handle_demo_message({
        "from": reservation["conversation_id"], "text": "I paid", "message_id": "paid-text",
    })
    assert "cannot verify payment" in reply
    assert mermaid_reservation_store.get_reservation(reservation["public_id"])["state"] == "demo_payment_pending"


def test_demo_never_enables_reminders():
    assert mermaid_catalog.demo_features()["reminders"] is False


def test_presentation_refresh_preserves_booking_payment_and_delivery(monkeypatch):
    from scripts.refresh_mermaid_pdf_presentation import refresh
    reservation = pending()
    mermaid_documents.create_quote(reservation)
    expires, signature = token(reservation)
    monkeypatch.setattr(mermaid_demo_payment.time, "time", lambda: 1000)
    monkeypatch.setattr(mermaid_demo_payment, "send_reply", lambda *args, **kwargs: True)
    mermaid_demo_payment.complete_checkout(reservation["public_id"], expires, signature, "success")
    before = mermaid_reservation_store.get_reservation(reservation["public_id"])
    conn = mermaid_documents._conn()
    payments = [tuple(row) for row in conn.execute("SELECT * FROM mermaid_demo_payments")]
    jobs = [tuple(row) for row in conn.execute("SELECT * FROM mermaid_delivery_jobs")]
    originals = [row[0] for row in conn.execute("SELECT path FROM mermaid_documents")]
    refresh()
    refresh()
    assert mermaid_reservation_store.get_reservation(reservation["public_id"]) == before
    assert [tuple(row) for row in conn.execute("SELECT * FROM mermaid_demo_payments")] == payments
    assert [tuple(row) for row in conn.execute("SELECT * FROM mermaid_delivery_jobs")] == jobs
    assert all(Path(path).exists() for path in originals)
    assert all(Path(row[0]).parent.name == "presentation-v2" for row in conn.execute("SELECT path FROM mermaid_documents"))
    conn.close()
