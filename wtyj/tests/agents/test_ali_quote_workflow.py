import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx
from pypdf import PdfReader

from agents.social import ali_quote_delivery as delivery
from agents.social import ali_quote_workflow as workflow
from agents.social.ali_quote_download import sign_download, verify_download
from agents.social.ali_quote_pdf import render_quote_pdf


CLASS_ID = "30000000-0000-4000-8000-000000000001"
DEPOSIT_ID = "90000000-0000-4000-8000-000000000001"


def raw_config():
    return {
        "slug": "ali-car-rental",
        "workflow": {"type": "ali_quote", "required_deposit_charge_id": DEPOSIT_ID},
        "features": {
            "ali_quote_automation": False,
            "ali_quote_customer_delivery": False,
            "ali_quote_staff_email": False,
            "ali_quote_operator_alerts": False,
        },
    }


def customer():
    return {"name": "Synthetic Customer", "whatsapp": "+59990000000"}


def rental(locale="en"):
    return {
        "rental_start": "2026-09-01",
        "rental_end": "2026-09-08",
        "pickup_location": "Synthetic airport pickup",
        "return_location": "Synthetic airport return",
        "vehicle_class_id": CLASS_ID,
        "vehicle_class_name": "Small car",
        "driver_age": 40,
        "extra_ids": [],
        "conversation_language": locale,
    }


def pricing():
    created = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
    return {
        "quoteSnapshotId": "70000000-0000-4000-8000-000000000001",
        "quoteReference": "ALI-20260901-ABCD1234",
        "catalogVersion": 8,
        "availabilityMode": "request_only",
        "currency": "USD",
        "rentalDays": 7,
        "items": [{
            "code": "vehicle.weekly", "category": "vehicle", "description": "Small car - weekly rate",
            "quantity": 1, "refundable": False,
            "unitPrice": {"currency": "USD", "amount": "280.00"},
            "total": {"currency": "USD", "amount": "280.00"},
        }, {
            "code": "charge.deposit", "category": "security_deposit", "description": "Refundable security deposit",
            "quantity": 1, "refundable": True,
            "unitPrice": {"currency": "USD", "amount": "150.00"},
            "total": {"currency": "USD", "amount": "150.00"},
        }],
        "rentalTotal": {"currency": "USD", "amount": "280.00"},
        "refundableSecurityDeposit": {"currency": "USD", "amount": "150.00"},
        "reservationDeposit": {"currency": "USD", "amount": "70.00"},
        "createdAt": created.isoformat().replace("+00:00", "Z"),
        "expiresAt": (created + timedelta(hours=72)).isoformat().replace("+00:00", "Z"),
    }


def configure_db(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow.state_registry, "DB_PATH", str(tmp_path / "tenant.db"))


def confirmed_quote(monkeypatch, tmp_path):
    configure_db(monkeypatch, tmp_path)
    _, digest = workflow.normalized_summary(customer(), rental())
    quote, created = workflow.create_confirmed_quote(
        "conversation-synthetic", "account-synthetic", customer(), rental(), digest,
        "yes", DEPOSIT_ID, raw_config=raw_config(),
    )
    assert created
    return quote


def test_workflow_is_strictly_ali_tenant_scoped():
    assert workflow.tenant_enabled(raw_config())
    wrong = raw_config()
    wrong["slug"] = "other-tenant"
    assert not workflow.tenant_enabled(wrong)
    wrong = raw_config()
    wrong["workflow"]["type"] = "booking"
    assert not workflow.tenant_enabled(wrong)


def test_confirmation_variants_and_corrections_change_the_summary_hash():
    for phrase in ("yes", "correct", "ja", "klopt", "ta bon", "correcto", "stimmt", "passt"):
        assert workflow.is_unambiguous_confirmation(phrase)
    for phrase in ("no", "yes but change it", "ja?", "niet correct"):
        assert not workflow.is_unambiguous_confirmation(phrase)
    _, first = workflow.normalized_summary(customer(), rental())
    changed = rental()
    changed["return_location"] = "Synthetic hotel return"
    _, second = workflow.normalized_summary(customer(), changed)
    assert first != second


def test_duplicate_confirmation_creates_one_quote_and_ali_request_has_no_pii(monkeypatch, tmp_path):
    configure_db(monkeypatch, tmp_path)
    _, digest = workflow.normalized_summary(customer(), rental())
    args = ("conversation-synthetic", "account-synthetic", customer(), rental(), digest, "yes", DEPOSIT_ID)
    first, created_first = workflow.create_confirmed_quote(*args, raw_config=raw_config())
    second, created_second = workflow.create_confirmed_quote(*args, raw_config=raw_config())
    assert created_first is True and created_second is False
    assert first["public_id"] == second["public_id"]
    request = json.loads(first["ali_request_json"])
    assert set(request) == workflow.ALI_REQUEST_KEYS
    serialized = json.dumps(request).lower()
    assert not any(term in serialized for term in ("synthetic customer", "whatsapp", "location", "conversation", "phone", "email"))


def test_ali_client_retries_one_transient_failure_and_validates_72_hours():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(201, json=pricing())

    client = workflow.AliQuoteClient(
        "https://alicarrental.com", "synthetic-secret",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = client.create_quote(workflow.build_ali_request(rental(), DEPOSIT_ID), "opaque_synthetic_key_12345")
    assert result["quoteReference"] == pricing()["quoteReference"]
    assert len(calls) == 2


def test_pdf_is_one_page_in_all_locales_and_displays_exact_snapshot_totals(tmp_path):
    for locale in ("en", "nl", "pap", "de"):
        path, digest = render_quote_pdf(
            f"quote-{locale}", locale, customer(), rental(locale), pricing(),
            output_root=str(tmp_path),
        )
        data = open(path, "rb").read()
        assert hashlib.sha256(data).hexdigest() == digest
        reader = PdfReader(path)
        assert len(reader.pages) == 1
        text = reader.pages[0].extract_text()
        assert "USD 280.00" in text
        assert "USD 150.00" in text
        assert pricing()["quoteReference"] in text


def test_signed_download_rejects_tampering_and_expiry():
    secret = "synthetic-signing-secret"
    now = 1_800_000_000
    expires = now + 3600
    signature = sign_download("quote-public-id", expires, secret)
    assert verify_download("quote-public-id", expires, signature, secret, now=now)
    assert not verify_download("other-id", expires, signature, secret, now=now)
    assert not verify_download("quote-public-id", expires, signature, secret, now=expires + 1)


def test_customer_delivery_uses_zernio_file_attachment(monkeypatch):
    captured = {}
    monkeypatch.setenv("UNBOKS_PUBLIC_BASE_URL", "https://unboks.example")
    monkeypatch.setenv("ALI_QUOTE_DOWNLOAD_SECRET", "synthetic-signing-secret")
    monkeypatch.setattr(delivery, "send_dm_reply_with_attachment", lambda *args, **kwargs: captured.update({"args": args, "kwargs": kwargs}) or True)
    quote = {
        "public_id": "quote-public-id", "conversation_id": "conversation-synthetic",
        "zernio_account_id": "account-synthetic", "locale": "en",
        "quote_reference": pricing()["quoteReference"], "pricing_json": json.dumps(pricing()),
    }
    assert delivery.send_customer_whatsapp(quote, "/private/quote.pdf")
    assert captured["kwargs"]["attachment_type"] == "file"
    assert captured["args"][3].startswith("https://unboks.example/api/public/ali-quote/")


def test_staff_email_attaches_identical_pdf_bytes(monkeypatch):
    pdf = b"%PDF-1.4\nsynthetic quote"
    captured = []
    monkeypatch.setattr(delivery, "resolve_staff_recipients", lambda: ["staff@example.test"])
    monkeypatch.setattr(delivery, "smtp_send", lambda *args, **kwargs: captured.append((args, kwargs)))
    quote = {
        "customer_json": json.dumps(customer()), "rental_json": json.dumps(rental()),
        "pricing_json": json.dumps(pricing()), "confirmed_at": pricing()["createdAt"],
        "conversation_id": "conversation-synthetic", "quote_reference": pricing()["quoteReference"],
    }
    assert delivery.send_staff_email(quote, pdf)
    assert captured[0][1]["pdf_attachment"][1] == pdf
    assert hashlib.sha256(captured[0][1]["pdf_attachment"][1]).hexdigest() == hashlib.sha256(pdf).hexdigest()


def test_processing_replay_does_not_redeliver(monkeypatch, tmp_path):
    quote = confirmed_quote(monkeypatch, tmp_path)
    counts = {"whatsapp": 0, "email": 0, "alerts": 0, "escalate": 0}

    class Client:
        def create_quote(self, request, idempotency_key):
            return pricing()

    adapters = workflow.DeliveryAdapters(
        send_whatsapp=lambda *_: counts.__setitem__("whatsapp", counts["whatsapp"] + 1) or True,
        send_staff_email=lambda *_: counts.__setitem__("email", counts["email"] + 1) or True,
        send_operator_alerts=lambda *_: counts.__setitem__("alerts", counts["alerts"] + 1) or {"whatsapp": "sent"},
        escalate=lambda *_: counts.__setitem__("escalate", counts["escalate"] + 1),
    )
    switches = {"automation": True, "customer_delivery": True, "staff_email": True, "operator_alerts": True}
    first = workflow.process_quote(quote["public_id"], Client(), adapters, switches, output_root=str(tmp_path))
    second = workflow.process_quote(quote["public_id"], Client(), adapters, switches, output_root=str(tmp_path))
    assert first["status"] == second["status"] == "complete"
    assert counts == {"whatsapp": 1, "email": 1, "alerts": 1, "escalate": 0}


def test_transient_delivery_retries_once_then_escalates(monkeypatch, tmp_path):
    quote = confirmed_quote(monkeypatch, tmp_path)
    counts = {"email": 0, "escalate": 0}

    class Client:
        def create_quote(self, request, idempotency_key):
            return pricing()

    def failed_email(*_args):
        counts["email"] += 1
        return False

    adapters = workflow.DeliveryAdapters(
        send_whatsapp=lambda *_: True,
        send_staff_email=failed_email,
        send_operator_alerts=lambda *_: {},
        escalate=lambda *_: counts.__setitem__("escalate", counts["escalate"] + 1),
    )
    result = workflow.process_quote(
        quote["public_id"], Client(), adapters,
        {"automation": True, "customer_delivery": False, "staff_email": True, "operator_alerts": False},
        output_root=str(tmp_path),
    )
    assert result["status"] == "attention_required"
    assert counts == {"email": 2, "escalate": 1}
