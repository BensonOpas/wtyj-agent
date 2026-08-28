import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
from PIL import Image
from pypdf import PdfReader

from agents.social import ali_quote_delivery as delivery
from agents.social import ali_quote_download as download
from agents.social import ali_quote_workflow as workflow
from agents.social.ali_quote_brand_card import (
    HEIGHT as BRAND_CARD_HEIGHT,
    MAX_IMAGE_BYTES,
    WIDTH as BRAND_CARD_WIDTH,
    render_quote_brand_card,
)
from agents.social.ali_quote_download import sign_download, verify_download
from agents.social.ali_quote_pdf import render_quote_pdf
from agents.social.ali_quote_presentation import (
    format_usd_money,
    total_quote_amount,
    usd_cents,
    usd_money,
)


CLASS_ID = "30000000-0000-4000-8000-000000000001"
DEPOSIT_ID = "90000000-0000-4000-8000-000000000001"
CHILD_SEAT_ID = "c5b7e180-5eaa-4f5d-8a41-180000000001"


def raw_config(automation=True):
    return {
        "slug": "ali-car-rental",
        "workflow": {"type": "ali_quote", "required_deposit_charge_id": DEPOSIT_ID},
        "features": {
            "ali_quote_automation": automation,
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


def child_seat(locale="en", quantity=2):
    names = {
        "en": "Child seat", "nl": "Kinderzitje",
        "pap": "Stul pa mucha", "de": "Kindersitz",
    }
    return {
        "id": CHILD_SEAT_ID,
        "name": names[locale],
        "quantity": quantity,
        "billing_basis": "per_day",
        "unit_price_usd": "5.00",
    }


def pricing_with_child_seats():
    value = pricing()
    value["items"].insert(1, {
        "code": "extra.per_day", "category": "extra",
        "description": "Child seat", "quantity": 2, "refundable": False,
        "billingBasis": "per_day", "rentalDays": 7,
        "unitPrice": {"currency": "USD", "amount": "5.00"},
        "total": {"currency": "USD", "amount": "70.00"},
    })
    value["rentalTotal"] = {"currency": "USD", "amount": "350.00"}
    value["reservationDeposit"] = {"currency": "USD", "amount": "87.50"}
    return value


def owner_example_pricing():
    value = pricing()
    value["items"][0]["unitPrice"] = {"currency": "USD", "amount": "1260.00"}
    value["items"][0]["total"] = {"currency": "USD", "amount": "1260.00"}
    value["items"][1]["unitPrice"] = {"currency": "USD", "amount": "200.00"}
    value["items"][1]["total"] = {"currency": "USD", "amount": "200.00"}
    value["rentalTotal"] = {"currency": "USD", "amount": "1260.00"}
    value["refundableSecurityDeposit"] = {"currency": "USD", "amount": "200.00"}
    value["reservationDeposit"] = {"currency": "USD", "amount": "315.00"}
    return value


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


def test_workflow_is_strictly_ali_tenant_scoped_and_master_switched():
    assert workflow.tenant_configured(raw_config())
    assert workflow.tenant_enabled(raw_config())
    paused = raw_config(automation=False)
    assert workflow.tenant_configured(paused)
    assert not workflow.tenant_enabled(paused)
    wrong = raw_config()
    wrong["slug"] = "other-tenant"
    assert not workflow.tenant_enabled(wrong)
    wrong = raw_config()
    wrong["workflow"]["type"] = "booking"
    assert not workflow.tenant_enabled(wrong)


def test_confirmation_variants_and_corrections_change_the_summary_hash():
    accepted = (
        "yes", "yes it does", "yes, it does look right", "Yes, it looks good",
        "That’s correct.",
        "Everything looks right.", "All good.", "Go ahead.",
        "Yes, how much?", "Yes\nHow much", "OK", "OK thanks",
        "send it", "SEND QUOTE", "Send my quote", "I agree",
        "ja dat klopt", "alles ziet er goed uit", "ga maar door",
        "si tur kos ta bon", "esaki ta korekto", "por sigui",
        "ja das stimmt", "alles sieht richtig aus", "machen Sie weiter",
    )
    for phrase in accepted:
        assert workflow.is_unambiguous_confirmation(phrase)
    rejected = (
        "no", "not correct", "yes but change the dates", "it looks right except for pickup",
        "yes, can you add a child seat?", "yes add a child seat", "I think so?", "almost right",
        "nee", "ja maar wijzig de datum", "bijna goed", "si pero cambia e fecha",
        "kisas", "nein", "ja aber ändern Sie die Abholung", "fast richtig",
    )
    for phrase in rejected:
        assert not workflow.is_unambiguous_confirmation(phrase)
    assert workflow.confirmation_decision("yes it does") == (
        True, "affirmative_allowlist",
    )
    assert workflow.confirmation_decision("yes add a child seat") == (
        False, "correction_or_new_detail",
    )
    _, first = workflow.normalized_summary(customer(), rental())
    changed = rental()
    changed["return_location"] = "Synthetic hotel return"
    _, second = workflow.normalized_summary(customer(), changed)
    assert first != second


def test_nick_confirmation_copy_is_first_person_and_human_in_all_locales():
    expected = {
        "en": ("I have these details from you:", "Does everything look right? Choose an option below."),
        "nl": ("Ik heb deze gegevens van je:", "Klopt alles? Kies hieronder een optie."),
        "pap": ("Mi tin e detayanan aki di bo:", "Tur kos ta bon? Skohe un opshon aki bou."),
        "de": ("Ich habe diese Angaben von Ihnen:", "Stimmt alles? Wählen Sie unten eine Option."),
    }
    banned = (
        "reply yes", "please confirm", "antwoord ja", "konfirmá e det",
        "antworten sie mit ja", "just checking", "does that all look right",
    )
    for locale, (opening, closing) in expected.items():
        summary, _ = workflow.normalized_summary(customer(), rental(locale))
        text = workflow._summary_text(summary)
        assert text.startswith(opening)
        assert text.endswith(closing)
        assert "2026-09-01" not in text
        assert "2026-09-08" not in text
        assert not any(phrase in text.lower() for phrase in banned)


def test_send_my_quote_control_is_signed_opaque_current_and_stale(monkeypatch):
    monkeypatch.setenv(
        "ALI_QUOTE_CONFIRMATION_SECRET",
        "synthetic-confirmation-secret-32-bytes",
    )
    summary, summary_hash = workflow.normalized_summary(customer(), rental())
    plan = workflow.AliTurnPlan(
        "summary",
        workflow._summary_text(summary),
        "SUMMARY_PRESENTED",
        "continue_intake",
        "initial_or_corrected_complete_draft",
        "a" * 64,
        "b" * 64,
        summary_hash,
        1,
    )

    control = workflow.build_quote_confirmation_control(
        "conversation-synthetic", plan,
    )
    payload = control["button"]["payload"]
    change_payload = control["buttons"][1]["payload"]
    assert control["button"]["title"] == "Send My Quote"
    assert [button["title"] for button in control["buttons"]] == [
        "Send My Quote", "Change Something",
    ]
    assert control["fallback_text"].endswith(
        "Reply SEND QUOTE to continue, or CHANGE DETAILS to make a correction."
    )
    assert payload.startswith("ali_quote_confirm:v1:")
    assert change_payload.startswith("ali_quote_change:v1:")
    assert "Synthetic" not in payload
    flags = {
        "awaiting_quote_confirmation": True,
        "ali_presented_summary_hash": summary_hash,
        "ali_summary_version": 1,
    }
    assert workflow.resolve_quote_confirmation_interaction(
        "button_reply", payload, "conversation-synthetic", flags,
    ) == "current"
    assert workflow.resolve_quote_confirmation_interaction(
        "button_reply", change_payload, "conversation-synthetic", flags,
    ) == "change"
    flags["ali_summary_version"] = 2
    assert workflow.resolve_quote_confirmation_interaction(
        "button_reply", payload, "conversation-synthetic", flags,
    ) == "stale"


def test_existing_send_my_quote_signature_remains_valid_after_two_action_release():
    secret = "synthetic-confirmation-secret-32-bytes"
    conversation_id = "conversation-synthetic"
    summary_hash = "c" * 64
    version = 7
    legacy_material = f"{conversation_id}\x1f{summary_hash}\x1f{version}"
    legacy_signature = workflow.hmac.new(
        secret.encode("utf-8"),
        legacy_material.encode("utf-8"),
        workflow.hashlib.sha256,
    ).hexdigest()

    assert workflow.quote_confirmation_payload(
        conversation_id, summary_hash, version, secret=secret,
    ) == f"ali_quote_confirm:v1:{legacy_signature}"


def test_nick_progress_copy_is_direct_and_quote_led_in_all_locales():
    expected = {
        "en": "Thanks, I have everything I need. I’m preparing your official quote now and will send it here in a few minutes.",
        "nl": "Bedankt, ik heb alles wat ik nodig heb. Ik maak je officiële offerte nu klaar en stuur die hier over een paar minuten.",
        "pap": "Danki, mi tin tur loke mi mester. Mi ta prepara bo oferta ofisial awor i lo manda e aki den un par di minüt.",
        "de": "Danke, ich habe alle Angaben. Ich bereite Ihr offizielles Angebot jetzt vor und sende es Ihnen hier in wenigen Minuten.",
    }
    assert workflow.PREPARING == expected
    assert all("30" not in text for text in workflow.PREPARING.values())
    assert all("reply yes" not in text.lower() for text in workflow.PREPARING.values())


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


def test_existing_quote_database_adds_brand_delivery_columns(monkeypatch, tmp_path):
    configure_db(monkeypatch, tmp_path)
    connection = sqlite3.connect(workflow.state_registry.DB_PATH)
    connection.execute(
        "CREATE TABLE ali_quotes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, public_id TEXT NOT NULL UNIQUE, "
        "conversation_id TEXT NOT NULL, zernio_account_id TEXT NOT NULL, "
        "summary_hash TEXT NOT NULL, summary_version INTEGER NOT NULL, locale TEXT NOT NULL, "
        "customer_json TEXT NOT NULL, rental_json TEXT NOT NULL, ali_request_json TEXT NOT NULL, "
        "idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL, "
        "confirmed_at TEXT NOT NULL, sla_due_at TEXT NOT NULL, "
        "quote_reference TEXT, quote_snapshot_id TEXT, pricing_json TEXT, expires_at TEXT, "
        "pdf_path TEXT, pdf_sha256 TEXT, whatsapp_status TEXT NOT NULL DEFAULT 'pending', "
        "staff_email_status TEXT NOT NULL DEFAULT 'pending', "
        "notification_status_json TEXT NOT NULL DEFAULT '{}', "
        "attempt_count INTEGER NOT NULL DEFAULT 0, last_error_code TEXT, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "UNIQUE(conversation_id, summary_hash))"
    )
    connection.commit()
    connection.close()

    workflow.ensure_schema()

    connection = sqlite3.connect(workflow.state_registry.DB_PATH)
    columns = {
        row[1]: row for row in connection.execute("PRAGMA table_info(ali_quotes)")
    }
    connection.close()
    assert "brand_image_path" in columns
    assert "brand_image_sha256" in columns
    assert columns["brand_image_status"][4] == "'pending'"


def test_child_seat_summary_and_no_pii_request_are_catalog_grounded_in_all_locales():
    for locale in ("en", "nl", "pap", "de"):
        selected = rental(locale)
        selected["supplements"] = [child_seat(locale)]
        selected.pop("extra_ids", None)
        summary, _digest = workflow.normalized_summary(customer(), selected)
        text = workflow._summary_text(summary)
        assert child_seat(locale)["name"] in text
        assert "2 × USD 5.00" in text
        assert "7" in text
        assert "USD 70.00" in text

        request = workflow.build_ali_request(selected, DEPOSIT_ID)
        assert request["extraSelections"] == [{"id": CHILD_SEAT_ID, "quantity": 2}]
        serialized = json.dumps(request).lower()
        assert "child seat" not in serialized
        assert "synthetic" not in serialized


def test_supplement_change_creates_replacement_quote_without_mutating_original(monkeypatch, tmp_path):
    configure_db(monkeypatch, tmp_path)
    first_rental = rental()
    first_rental["supplements"] = [child_seat(quantity=1)]
    first_rental.pop("extra_ids", None)
    _, first_hash = workflow.normalized_summary(customer(), first_rental)
    first, created = workflow.create_confirmed_quote(
        "replacement-conversation", "account-synthetic", customer(),
        first_rental, first_hash, "yes", DEPOSIT_ID, raw_config=raw_config(),
    )
    assert created

    changed_rental = rental()
    changed_rental["supplements"] = [child_seat(quantity=2)]
    changed_rental.pop("extra_ids", None)
    _, changed_hash = workflow.normalized_summary(customer(), changed_rental)
    replacement, replacement_created = workflow.create_confirmed_quote(
        "replacement-conversation", "account-synthetic", customer(),
        changed_rental, changed_hash, "yes", DEPOSIT_ID, raw_config=raw_config(),
    )

    assert replacement_created
    assert replacement["public_id"] != first["public_id"]
    assert json.loads(workflow.get_quote(first["public_id"])["ali_request_json"])["extraSelections"] == [
        {"id": CHILD_SEAT_ID, "quantity": 1},
    ]
    assert json.loads(replacement["ali_request_json"])["extraSelections"] == [
        {"id": CHILD_SEAT_ID, "quantity": 2},
    ]


def test_customer_delivery_delay_uses_persisted_confirmation(monkeypatch, tmp_path):
    quote = confirmed_quote(monkeypatch, tmp_path)
    confirmed_at = datetime.fromisoformat(quote["confirmed_at"].replace("Z", "+00:00"))

    assert workflow.seconds_until_customer_quote_delivery(
        quote, now=confirmed_at + timedelta(seconds=60),
    ) == 120
    assert workflow.seconds_until_customer_quote_delivery(
        quote, now=confirmed_at + timedelta(seconds=180),
    ) == 0
    assert workflow.seconds_until_customer_quote_delivery(
        quote, now=confirmed_at + timedelta(minutes=10),
    ) == 0


def test_fresh_confirmation_delays_only_customer_whatsapp(monkeypatch, tmp_path):
    quote = confirmed_quote(monkeypatch, tmp_path)
    confirmed_at = datetime.fromisoformat(quote["confirmed_at"].replace("Z", "+00:00"))
    events = []

    def render_pdf(*_args, **_kwargs):
        events.append("pdf")
        path = tmp_path / "quote.pdf"
        data = b"%PDF-1.4\nsynthetic quote"
        path.write_bytes(data)
        return str(path), hashlib.sha256(data).hexdigest()

    monkeypatch.setattr(workflow, "render_quote_pdf", render_pdf)

    class Client:
        def create_quote(self, _request, _idempotency_key):
            events.append("pricing")
            return pricing()

    adapters = workflow.DeliveryAdapters(
        send_brand_image=lambda *_: events.append("image") or True,
        send_whatsapp=lambda *_: events.append("whatsapp") or True,
        send_staff_email=lambda *_: events.append("email") or True,
        send_operator_alerts=lambda *_: events.append("alerts") or {"whatsapp": "sent"},
        escalate=lambda *_: events.append("escalate"),
    )
    result = workflow.process_quote(
        quote["public_id"], Client(), adapters,
        {"automation": True, "customer_delivery": True, "staff_email": True, "operator_alerts": True},
        output_root=str(tmp_path),
        sleep=lambda seconds: events.append(("sleep", seconds)),
        now=lambda: confirmed_at,
    )

    assert result["status"] == "complete"
    assert events == [
        "pricing", "pdf", "email", "alerts", ("sleep", 180.0),
        "image", "whatsapp",
    ]


def test_resume_at_plus_60_waits_only_remaining_120_seconds(monkeypatch, tmp_path):
    quote = confirmed_quote(monkeypatch, tmp_path)
    confirmed_at = datetime.fromisoformat(quote["confirmed_at"].replace("Z", "+00:00"))
    events = []

    class Client:
        def create_quote(self, _request, _idempotency_key):
            events.append("pricing")
            return pricing()

    adapters = workflow.DeliveryAdapters(
        send_brand_image=lambda *_: events.append("image") or True,
        send_whatsapp=lambda *_: events.append("whatsapp") or True,
        send_staff_email=lambda *_: events.append("email") or True,
        send_operator_alerts=lambda *_: events.append("alerts") or {"whatsapp": "sent"},
        escalate=lambda *_: events.append("escalate"),
    )
    immediate_only = {
        "automation": True,
        "customer_delivery": False,
        "staff_email": True,
        "operator_alerts": True,
    }
    workflow.process_quote(
        quote["public_id"], Client(), adapters, immediate_only,
        output_root=str(tmp_path), now=lambda: confirmed_at,
    )
    assert events == ["pricing", "email", "alerts"]

    events.clear()
    result = workflow.process_quote(
        quote["public_id"], Client(), adapters,
        {**immediate_only, "customer_delivery": True},
        output_root=str(tmp_path),
        sleep=lambda seconds: events.append(("sleep", seconds)),
        now=lambda: confirmed_at + timedelta(seconds=60),
    )

    assert result["status"] == "complete"
    assert events == [("sleep", 120.0), "image", "whatsapp"]


def test_resume_at_three_minute_boundary_sends_without_wait(monkeypatch, tmp_path):
    quote = confirmed_quote(monkeypatch, tmp_path)
    confirmed_at = datetime.fromisoformat(quote["confirmed_at"].replace("Z", "+00:00"))
    events = []

    class Client:
        def create_quote(self, _request, _idempotency_key):
            return pricing()

    adapters = workflow.DeliveryAdapters(
        send_brand_image=lambda *_: events.append("image") or True,
        send_whatsapp=lambda *_: events.append("whatsapp") or True,
        send_staff_email=lambda *_: events.append("email") or True,
        send_operator_alerts=lambda *_: events.append("alerts") or {"whatsapp": "sent"},
        escalate=lambda *_: events.append("escalate"),
    )
    immediate_only = {
        "automation": True,
        "customer_delivery": False,
        "staff_email": True,
        "operator_alerts": True,
    }
    workflow.process_quote(
        quote["public_id"], Client(), adapters, immediate_only,
        output_root=str(tmp_path), now=lambda: confirmed_at,
    )
    events.clear()

    result = workflow.process_quote(
        quote["public_id"], Client(), adapters,
        {**immediate_only, "customer_delivery": True},
        output_root=str(tmp_path),
        sleep=lambda seconds: events.append(("sleep", seconds)),
        now=lambda: confirmed_at + timedelta(seconds=180),
    )

    assert result["status"] == "complete"
    assert events == ["image", "whatsapp"]


def test_change_during_customer_delay_supersedes_both_assets_only(monkeypatch, tmp_path):
    quote = confirmed_quote(monkeypatch, tmp_path)
    confirmed_at = datetime.fromisoformat(quote["confirmed_at"].replace("Z", "+00:00"))
    events = []

    class Client:
        def create_quote(self, _request, _idempotency_key):
            events.append("pricing")
            return pricing()

    def interrupt_delay(seconds):
        events.append(("sleep", seconds))
        assert workflow.supersede_pending_customer_delivery(
            quote["conversation_id"], "a" * 64,
        ) == quote["public_id"]

    adapters = workflow.DeliveryAdapters(
        send_brand_image=lambda *_: events.append("image") or True,
        send_whatsapp=lambda *_: events.append("whatsapp") or True,
        send_staff_email=lambda *_: events.append("email") or True,
        send_operator_alerts=lambda *_: events.append("alerts") or {"whatsapp": "sent"},
        escalate=lambda *_: events.append("escalate"),
    )
    result = workflow.process_quote(
        quote["public_id"], Client(), adapters,
        {"automation": True, "customer_delivery": True, "staff_email": True, "operator_alerts": True},
        output_root=str(tmp_path), sleep=interrupt_delay, now=lambda: confirmed_at,
    )

    assert result["status"] == "superseded"
    assert result["staff_email_status"] == "sent"
    assert result["brand_image_status"] == "superseded"
    assert result["whatsapp_status"] == "superseded"
    assert result["pdf_path"]
    assert events == ["pricing", "email", "alerts", ("sleep", 180.0)]


def test_summary_versions_make_a_to_b_to_a_three_immutable_quotes(monkeypatch, tmp_path):
    configure_db(monkeypatch, tmp_path)
    selected_a = rental()
    selected_b = {**rental(), "return_location": "Synthetic hotel B"}
    rows = []
    for version, selected in enumerate((selected_a, selected_b, selected_a), start=1):
        _, digest = workflow.normalized_summary(customer(), selected, version=version)
        row, created = workflow.create_confirmed_quote(
            "synthetic-a-b-a", "synthetic-account", customer(), selected,
            digest, "yes", DEPOSIT_ID, summary_version=version,
            raw_config=raw_config(),
        )
        assert created
        rows.append(row)
    assert len({row["public_id"] for row in rows}) == 3
    assert len({row["summary_hash"] for row in rows}) == 3


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
        assert "USD 430.00" in text
        assert pricing()["quoteReference"] in text
        assert "2026-09-01" not in text
        assert "2026-09-08" not in text


def test_quote_grand_total_uses_integer_cents_and_preserves_reservation_amount():
    snapshot = owner_example_pricing()

    assert usd_cents(snapshot["rentalTotal"]) == 126_000
    assert usd_cents(snapshot["refundableSecurityDeposit"]) == 20_000
    assert total_quote_amount(snapshot) == {
        "currency": "USD", "amount": "1460.00",
    }
    assert format_usd_money(total_quote_amount(snapshot)) == "USD 1,460.00"
    assert snapshot["reservationDeposit"] == {
        "currency": "USD", "amount": "315.00",
    }
    assert usd_money(146_000) == total_quote_amount(snapshot)


def test_pdf_grand_total_hierarchy_is_localized_in_all_languages(tmp_path):
    expected = {
        "en": (
            "Total quote amount",
            "Includes a refundable security deposit of USD 200.00.",
            "Rental charges",
        ),
        "nl": (
            "Totaalbedrag offerte",
            "Inclusief een terugbetaalbare borg van USD 200.00.",
            "Huurkosten",
        ),
        "pap": (
            "Montante total di oferta",
            "Ta inkluí un depósito reembolsabel di USD 200.00.",
            "Gastunan di huur",
        ),
        "de": (
            "Gesamtbetrag des Angebots",
            "Enthält eine rückerstattbare Kaution von USD 200.00.",
            "Mietkosten",
        ),
    }
    for locale, labels in expected.items():
        path, _digest = render_quote_pdf(
            f"owner-example-{locale}", locale, customer(), rental(locale),
            owner_example_pricing(), output_root=str(tmp_path),
        )
        reader = PdfReader(path)
        assert len(reader.pages) == 1
        text = reader.pages[0].extract_text()
        for label in labels:
            assert label in text
        assert "USD 1,460.00" in text
        assert "USD 1,260.00" in text
        assert text.count("USD 200.00") == 2
        assert "USD 315.00" not in text


def test_zero_deposit_pdf_omits_refundable_explanation(tmp_path):
    snapshot = pricing()
    snapshot["refundableSecurityDeposit"] = {
        "currency": "USD", "amount": "0.00",
    }
    snapshot["items"][1]["unitPrice"] = {"currency": "USD", "amount": "0.00"}
    snapshot["items"][1]["total"] = {"currency": "USD", "amount": "0.00"}
    path, _digest = render_quote_pdf(
        "zero-deposit", "en", customer(), rental(), snapshot,
        output_root=str(tmp_path),
    )
    text = PdfReader(path).pages[0].extract_text()
    assert "Total quote amount" in text
    assert "Rental charges" in text
    assert "USD 280.00" in text
    assert "Includes a refundable security deposit" not in text


def test_supplements_are_included_in_grand_total_once(tmp_path):
    snapshot = pricing_with_child_seats()
    path, _digest = render_quote_pdf(
        "supplement-grand-total", "en", customer(),
        {**rental(), "supplements": [child_seat()]}, snapshot,
        output_root=str(tmp_path),
    )
    text = PdfReader(path).pages[0].extract_text()
    assert total_quote_amount(snapshot) == {
        "currency": "USD", "amount": "500.00",
    }
    assert "USD 500.00" in text
    assert "USD 350.00" in text
    assert text.count("USD 70.00") == 1


def test_pdf_itemizes_supplement_basis_unit_days_and_total_in_all_locales(tmp_path):
    expected_basis = {
        "en": "per rental day", "nl": "per huurdag",
        "pap": "pa dia di huur", "de": "pro Miettag",
    }
    for locale in ("en", "nl", "pap", "de"):
        selected_rental = rental(locale)
        selected_rental["supplements"] = [child_seat(locale)]
        path, _digest = render_quote_pdf(
            f"supplement-{locale}", locale, customer(), selected_rental,
            pricing_with_child_seats(), output_root=str(tmp_path),
        )
        reader = PdfReader(path)
        assert len(reader.pages) == 1
        text = reader.pages[0].extract_text()
        assert child_seat(locale)["name"] in text
        assert "USD 5.00" in text
        assert expected_basis[locale] in text
        assert "USD 70.00" in text


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
        "customer_json": json.dumps(customer()),
    }
    assert delivery.send_customer_whatsapp(quote, "/private/quote.pdf")
    assert captured["kwargs"]["attachment_type"] == "file"
    assert captured["kwargs"]["attachment_name"] == (
        "Ali-Car-Rental-Quote-Synthetic-Customer-2026-09-01-ABCD1234.pdf"
    )
    assert captured["args"][3].startswith("https://unboks.example/api/public/ali-quote/")
    assert "4 September 2026 at 10:00 (Curaçao time)" in captured["args"][2]
    assert "T" not in captured["args"][2].split("Valid until:", 1)[1].split("\n", 1)[0]
    assert "Subject to final vehicle availability confirmation." not in captured["args"][2]


def test_customer_quote_captions_remove_availability_sentence_in_all_locales(monkeypatch):
    captured = []
    monkeypatch.setenv("UNBOKS_PUBLIC_BASE_URL", "https://unboks.example")
    monkeypatch.setenv("ALI_QUOTE_DOWNLOAD_SECRET", "synthetic-signing-secret")
    monkeypatch.setattr(
        delivery, "send_dm_reply_with_attachment",
        lambda *args, **kwargs: captured.append((args, kwargs)) or True,
    )
    forbidden = {
        "en": "Subject to final vehicle availability confirmation.",
        "nl": "Onder voorbehoud van definitieve beschikbaarheid.",
        "pap": "Suhéto na konfirmashon final di disponibilidat.",
        "de": "Vorbehaltlich der endgültigen Fahrzeugverfügbarkeit.",
    }
    for locale in forbidden:
        quote = {
            "public_id": f"quote-{locale}",
            "conversation_id": "conversation-synthetic",
            "zernio_account_id": "account-synthetic", "locale": locale,
            "quote_reference": pricing()["quoteReference"],
            "pricing_json": json.dumps(pricing()),
            "customer_json": json.dumps(customer()),
            "rental_json": json.dumps(rental(locale)),
        }
        assert delivery.send_customer_whatsapp(quote, "/private/quote.pdf")
        assert forbidden[locale] not in captured[-1][0][2]
        assert delivery.MESSAGES[locale][1] in captured[-1][0][2]

    assert all(
        phrase in render_quote_pdf.__globals__["LABELS"][locale]["availability"]
        for locale, phrase in forbidden.items()
    )


def test_brand_card_is_localized_pii_free_and_mobile_sized(tmp_path):
    customer_name = customer()["name"]
    phone = customer()["whatsapp"]
    digests = set()
    for locale in ("en", "nl", "pap", "de"):
        path, digest = render_quote_brand_card(
            f"card-{locale}", locale, pricing()["quoteReference"],
            output_root=str(tmp_path),
        )
        data = open(path, "rb").read()
        digests.add(digest)
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(data) < MAX_IMAGE_BYTES
        assert hashlib.sha256(data).hexdigest() == digest
        assert customer_name.encode() not in data
        assert phone.encode() not in data
        with Image.open(path) as image:
            assert image.size == (BRAND_CARD_WIDTH, BRAND_CARD_HEIGHT)
            assert image.format == "PNG"
    assert len(digests) == 4


def test_customer_brand_card_uses_signed_image_attachment(monkeypatch):
    captured = {}
    monkeypatch.setenv("UNBOKS_PUBLIC_BASE_URL", "https://unboks.example")
    monkeypatch.setenv("ALI_QUOTE_DOWNLOAD_SECRET", "synthetic-signing-secret")
    monkeypatch.setattr(
        delivery, "send_dm_reply_with_attachment",
        lambda *args, **kwargs: captured.update({"args": args, "kwargs": kwargs}) or True,
    )
    quote = {
        "public_id": "quote-public-id",
        "conversation_id": "conversation-synthetic",
        "zernio_account_id": "account-synthetic",
    }
    assert delivery.send_customer_brand_image(quote, "/private/quote-card.png")
    assert captured["args"][2] == ""
    assert "/quote-public-id--image?" in captured["args"][3]
    assert captured["kwargs"]["attachment_type"] == "image"


def test_customer_delivery_itemizes_supplement_and_keeps_deposit_separate(monkeypatch):
    captured = {}
    monkeypatch.setenv("UNBOKS_PUBLIC_BASE_URL", "https://unboks.example")
    monkeypatch.setenv("ALI_QUOTE_DOWNLOAD_SECRET", "synthetic-signing-secret")
    monkeypatch.setattr(
        delivery, "send_dm_reply_with_attachment",
        lambda *args, **kwargs: captured.update({"args": args, "kwargs": kwargs}) or True,
    )
    quote = {
        "public_id": "quote-public-id", "conversation_id": "conversation-synthetic",
        "zernio_account_id": "account-synthetic", "locale": "en",
        "quote_reference": pricing()["quoteReference"],
        "pricing_json": json.dumps(pricing_with_child_seats()),
        "customer_json": json.dumps(customer()),
        "rental_json": json.dumps({**rental(), "supplements": [child_seat()]}),
    }
    assert delivery.send_customer_whatsapp(quote, "/private/quote.pdf")
    text = captured["args"][2]
    assert "Supplements:\nChild seat: 2 × USD 5.00 per rental day × 7 days = USD 70.00" in text
    assert "Rental total: USD 350.00" in text
    assert "Refundable security deposit: USD 150.00" in text


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
    assert captured[0][1]["pdf_attachment"][0] == (
        "Ali-Car-Rental-Quote-Synthetic-Customer-2026-09-01-ABCD1234.pdf"
    )
    assert hashlib.sha256(captured[0][1]["pdf_attachment"][1]).hexdigest() == hashlib.sha256(pdf).hexdigest()


def test_signed_download_uses_same_official_customer_filename(monkeypatch, tmp_path):
    quote_root = tmp_path / "quotes"
    quote_path = quote_root / "quote-public-id" / "quote.pdf"
    quote_path.parent.mkdir(parents=True)
    quote_path.write_bytes(b"%PDF-1.4\nsynthetic quote")
    quote = {
        "pdf_path": str(quote_path), "pdf_sha256": "synthetic-sha",
        "quote_reference": pricing()["quoteReference"],
        "customer_json": json.dumps(customer()),
        "pricing_json": json.dumps(pricing()),
    }
    monkeypatch.setenv("ALI_QUOTE_DATA_ROOT", str(quote_root))
    monkeypatch.setenv("ALI_QUOTE_DOWNLOAD_SECRET", "synthetic-signing-secret")
    monkeypatch.setattr(download, "get_quote", lambda _public_id: quote)
    expires = int(datetime.now(timezone.utc).timestamp()) + 3600
    signature = download.sign_download(
        "quote-public-id", expires, "synthetic-signing-secret",
    )

    response = download.quote_download_response(
        "quote-public-id", expires, signature,
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="Ali-Car-Rental-Quote-Synthetic-Customer-2026-09-01-ABCD1234.pdf"'
    )


def test_signed_image_download_is_separate_and_cannot_be_swapped(monkeypatch, tmp_path):
    quote_root = tmp_path / "quotes"
    quote_dir = quote_root / "quote-public-id"
    quote_dir.mkdir(parents=True)
    pdf_path = quote_dir / "quote.pdf"
    image_path = quote_dir / "quote-card.png"
    pdf_path.write_bytes(b"%PDF-1.4\nsynthetic quote")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic image")
    quote = {
        "pdf_path": str(pdf_path), "pdf_sha256": "pdf-digest",
        "brand_image_path": str(image_path), "brand_image_sha256": "image-digest",
        "quote_reference": pricing()["quoteReference"],
        "customer_json": json.dumps(customer()),
        "pricing_json": json.dumps(pricing()),
    }
    secret = "synthetic-signing-secret"
    monkeypatch.setenv("ALI_QUOTE_DATA_ROOT", str(quote_root))
    monkeypatch.setenv("ALI_QUOTE_DOWNLOAD_SECRET", secret)
    monkeypatch.setattr(download, "get_quote", lambda public_id: quote if public_id == "quote-public-id" else None)

    current_time = int(datetime.now(timezone.utc).timestamp())
    image_url = download.build_signed_url(
        "https://unboks.example", "quote-public-id", secret,
        now=current_time, asset="image",
    )
    parsed = urlparse(image_url)
    query = parse_qs(parsed.query)
    signed_id = parsed.path.rsplit("/", 1)[-1]
    response = download.quote_download_response(
        signed_id, int(query["expires"][0]), query["signature"][0],
    )
    assert response.status_code == 200
    assert response.media_type == "image/png"
    assert response.headers["cache-control"] == "private, no-store"

    swapped = download.quote_download_response(
        "quote-public-id", int(query["expires"][0]), query["signature"][0],
    )
    assert swapped.status_code == 404


def test_processing_replay_does_not_redeliver(monkeypatch, tmp_path):
    quote = confirmed_quote(monkeypatch, tmp_path)
    _, digest = workflow.normalized_summary(customer(), rental())
    duplicate, created = workflow.create_confirmed_quote(
        "conversation-synthetic", "account-synthetic", customer(), rental(),
        digest, "yes", DEPOSIT_ID, raw_config=raw_config(),
    )
    assert created is False
    assert duplicate["public_id"] == quote["public_id"]
    counts = {"image": 0, "whatsapp": 0, "email": 0, "alerts": 0, "escalate": 0}

    class Client:
        def create_quote(self, request, idempotency_key):
            return pricing()

    adapters = workflow.DeliveryAdapters(
        send_brand_image=lambda *_: counts.__setitem__("image", counts["image"] + 1) or True,
        send_whatsapp=lambda *_: counts.__setitem__("whatsapp", counts["whatsapp"] + 1) or True,
        send_staff_email=lambda *_: counts.__setitem__("email", counts["email"] + 1) or True,
        send_operator_alerts=lambda *_: counts.__setitem__("alerts", counts["alerts"] + 1) or {"whatsapp": "sent"},
        escalate=lambda *_: counts.__setitem__("escalate", counts["escalate"] + 1),
    )
    switches = {"automation": True, "customer_delivery": True, "staff_email": True, "operator_alerts": True}
    confirmed_at = datetime.fromisoformat(quote["confirmed_at"].replace("Z", "+00:00"))
    after_boundary = lambda: confirmed_at + timedelta(seconds=180)
    first = workflow.process_quote(
        quote["public_id"], Client(), adapters, switches,
        output_root=str(tmp_path), now=after_boundary,
    )
    second = workflow.process_quote(
        quote["public_id"], Client(), adapters, switches,
        output_root=str(tmp_path), now=after_boundary,
    )
    assert first["status"] == second["status"] == "complete"
    assert counts == {"image": 1, "whatsapp": 1, "email": 1, "alerts": 1, "escalate": 0}


def test_staff_email_failure_does_not_block_customer_whatsapp(monkeypatch, tmp_path):
    quote = confirmed_quote(monkeypatch, tmp_path)
    counts = {"image": 0, "whatsapp": 0, "email": 0, "escalate": 0}

    class Client:
        def create_quote(self, request, idempotency_key):
            return pricing()

    def failed_email(*_args):
        counts["email"] += 1
        return False

    adapters = workflow.DeliveryAdapters(
        send_brand_image=lambda *_: counts.__setitem__("image", counts["image"] + 1) or True,
        send_whatsapp=lambda *_: counts.__setitem__("whatsapp", counts["whatsapp"] + 1) or True,
        send_staff_email=failed_email,
        send_operator_alerts=lambda *_: {},
        escalate=lambda *_: counts.__setitem__("escalate", counts["escalate"] + 1),
    )
    result = workflow.process_quote(
        quote["public_id"], Client(), adapters,
        {"automation": True, "customer_delivery": True, "staff_email": True, "operator_alerts": False},
        output_root=str(tmp_path), delay_seconds=0,
    )
    assert result["status"] == "attention_required"
    assert result["whatsapp_status"] == "accepted"
    assert result["staff_email_status"] == "failed"
    assert counts == {"image": 1, "whatsapp": 1, "email": 2, "escalate": 1}


def test_whatsapp_failure_does_not_block_staff_email(monkeypatch, tmp_path):
    quote = confirmed_quote(monkeypatch, tmp_path)
    counts = {"image": 0, "whatsapp": 0, "email": 0, "escalate": 0}

    class Client:
        def create_quote(self, request, idempotency_key):
            return pricing()

    def failed_whatsapp(*_args):
        counts["whatsapp"] += 1
        return False

    adapters = workflow.DeliveryAdapters(
        send_brand_image=lambda *_: counts.__setitem__("image", counts["image"] + 1) or True,
        send_whatsapp=failed_whatsapp,
        send_staff_email=lambda *_: counts.__setitem__("email", counts["email"] + 1) or True,
        send_operator_alerts=lambda *_: {},
        escalate=lambda *_: counts.__setitem__("escalate", counts["escalate"] + 1),
    )
    result = workflow.process_quote(
        quote["public_id"], Client(), adapters,
        {"automation": True, "customer_delivery": True, "staff_email": True, "operator_alerts": False},
        output_root=str(tmp_path), delay_seconds=0,
    )
    assert result["status"] == "attention_required"
    assert result["whatsapp_status"] == "failed"
    assert result["staff_email_status"] == "sent"
    assert counts == {"image": 1, "whatsapp": 2, "email": 1, "escalate": 1}


def test_brand_image_failure_still_sends_pdf_and_replay_retries_only_image(monkeypatch, tmp_path):
    quote = confirmed_quote(monkeypatch, tmp_path)
    counts = {"image": 0, "whatsapp": 0, "email": 0, "escalate": 0}

    class Client:
        def create_quote(self, _request, _idempotency_key):
            return pricing()

    image_succeeds = False

    def send_image(*_args):
        counts["image"] += 1
        return image_succeeds

    adapters = workflow.DeliveryAdapters(
        send_brand_image=send_image,
        send_whatsapp=lambda *_: counts.__setitem__("whatsapp", counts["whatsapp"] + 1) or True,
        send_staff_email=lambda *_: counts.__setitem__("email", counts["email"] + 1) or True,
        send_operator_alerts=lambda *_: {},
        escalate=lambda *_: counts.__setitem__("escalate", counts["escalate"] + 1),
    )
    switches = {
        "automation": True, "customer_delivery": True,
        "staff_email": True, "operator_alerts": False,
    }
    first = workflow.process_quote(
        quote["public_id"], Client(), adapters, switches,
        output_root=str(tmp_path), delay_seconds=0,
    )
    assert first["status"] == "attention_required"
    assert first["brand_image_status"] == "failed"
    assert first["whatsapp_status"] == "accepted"
    assert counts == {"image": 2, "whatsapp": 1, "email": 1, "escalate": 1}

    image_succeeds = True
    second = workflow.process_quote(
        quote["public_id"], Client(), adapters, switches,
        output_root=str(tmp_path), delay_seconds=0,
    )
    assert second["status"] == "complete"
    assert second["brand_image_status"] == "accepted"
    assert second["whatsapp_status"] == "accepted"
    assert counts == {"image": 3, "whatsapp": 1, "email": 1, "escalate": 1}


def test_pdf_failure_after_image_success_retries_only_pdf(monkeypatch, tmp_path):
    quote = confirmed_quote(monkeypatch, tmp_path)
    counts = {"image": 0, "whatsapp": 0, "email": 0, "escalate": 0}
    pdf_succeeds = False

    class Client:
        def create_quote(self, _request, _idempotency_key):
            return pricing()

    def send_pdf(*_args):
        counts["whatsapp"] += 1
        return pdf_succeeds

    adapters = workflow.DeliveryAdapters(
        send_brand_image=lambda *_: counts.__setitem__("image", counts["image"] + 1) or True,
        send_whatsapp=send_pdf,
        send_staff_email=lambda *_: counts.__setitem__("email", counts["email"] + 1) or True,
        send_operator_alerts=lambda *_: {},
        escalate=lambda *_: counts.__setitem__("escalate", counts["escalate"] + 1),
    )
    switches = {
        "automation": True, "customer_delivery": True,
        "staff_email": True, "operator_alerts": False,
    }
    first = workflow.process_quote(
        quote["public_id"], Client(), adapters, switches,
        output_root=str(tmp_path), delay_seconds=0,
    )
    assert first["status"] == "attention_required"
    assert first["brand_image_status"] == "accepted"
    assert first["whatsapp_status"] == "failed"
    assert counts == {"image": 1, "whatsapp": 2, "email": 1, "escalate": 1}

    pdf_succeeds = True
    second = workflow.process_quote(
        quote["public_id"], Client(), adapters, switches,
        output_root=str(tmp_path), delay_seconds=0,
    )
    assert second["status"] == "complete"
    assert second["brand_image_status"] == "accepted"
    assert second["whatsapp_status"] == "accepted"
    assert counts == {"image": 1, "whatsapp": 3, "email": 1, "escalate": 1}


def test_post_quote_actions_send_once_after_confirmed_pdf(monkeypatch, tmp_path):
    quote = confirmed_quote(monkeypatch, tmp_path)
    events = []

    class Client:
        def create_quote(self, _request, _idempotency_key):
            return pricing()

    adapters = workflow.DeliveryAdapters(
        send_brand_image=lambda *_: events.append("image") or True,
        send_whatsapp=lambda *_: events.append("pdf") or True,
        send_staff_email=lambda *_: events.append("email") or True,
        send_operator_alerts=lambda *_: {},
        escalate=lambda *_: events.append("escalate"),
        send_post_quote_actions=lambda *_: events.append("actions") or True,
    )
    switches = {
        "automation": True,
        "customer_delivery": True,
        "staff_email": True,
        "operator_alerts": False,
        "post_quote_actions": True,
    }
    first = workflow.process_quote(
        quote["public_id"], Client(), adapters, switches,
        output_root=str(tmp_path), delay_seconds=0,
    )
    second = workflow.process_quote(
        quote["public_id"], Client(), adapters, switches,
        output_root=str(tmp_path), delay_seconds=0,
    )

    assert first["status"] == second["status"] == "complete"
    assert first["post_quote_control_status"] == "accepted"
    assert events == ["email", "image", "pdf", "actions"]


def test_post_quote_action_failure_never_relabels_delivered_quote(monkeypatch, tmp_path):
    quote = confirmed_quote(monkeypatch, tmp_path)
    events = []

    class Client:
        def create_quote(self, _request, _idempotency_key):
            return pricing()

    adapters = workflow.DeliveryAdapters(
        send_brand_image=lambda *_: True,
        send_whatsapp=lambda *_: True,
        send_staff_email=lambda *_: True,
        send_operator_alerts=lambda *_: {},
        escalate=lambda _quote, code: events.append(code),
        send_post_quote_actions=lambda *_: False,
    )
    result = workflow.process_quote(
        quote["public_id"], Client(), adapters,
        {
            "automation": True,
            "customer_delivery": True,
            "staff_email": True,
            "operator_alerts": False,
            "post_quote_actions": True,
        },
        output_root=str(tmp_path), delay_seconds=0,
    )

    assert result["status"] == "complete"
    assert result["whatsapp_status"] == "accepted"
    assert result["post_quote_control_status"] == "failed"
    assert events == ["post_quote_control_delivery_failed"]
