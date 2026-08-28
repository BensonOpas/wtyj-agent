"""Concrete Ali quote delivery adapters using existing Unboks providers."""

from __future__ import annotations

import json
import hashlib
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from agents.marina.email_adapter import smtp_send
from agents.social.ali_quote_download import build_signed_url
from agents.social.ali_quote_presentation import (
    build_quote_filename,
    format_curacao_datetime,
    format_rental_period,
)
from agents.social.ali_quote_workflow import DeliveryAdapters, get_quote, update_quote
from agents.social.ali_reservation_workflow import (
    AliReservationError,
    build_post_quote_control,
    record_confirmation_delivery,
)
from agents.social.zernio_dm_client import (
    send_dm_post_quote_actions,
    send_dm_reply,
    send_dm_reply_with_attachment,
)
from shared import bm_logger, config_loader, state_registry

CURACAO = ZoneInfo("America/Curacao")
PAYMENT_WINDOW_HOURS = 24

MESSAGES = {
    "en": ("Your official Ali Car Rental quote is ready.", "Choose what you'd like to do below."),
    "nl": ("Je officiële offerte van Ali Car Rental is klaar.", "Kies hieronder wat je wilt doen."),
    "pap": ("Bo oferta ofisial di Ali Car Rental ta kla.", "Skoh abou kiko bo ke hasi."),
    "de": ("Ihr offizielles Angebot von Ali Car Rental ist fertig.", "Wählen Sie unten aus, wie Sie fortfahren möchten."),
}

VALID_UNTIL = {
    "en": "Valid until",
    "nl": "Geldig tot",
    "pap": "Válido te ku",
    "de": "Gültig bis",
}

SUPPLEMENT_LABELS = {
    "en": ("Supplements", "per rental day", "per rental", "days"),
    "nl": ("Extra's", "per huurdag", "per huur", "dagen"),
    "pap": ("Ekstranan", "pa dia di huur", "pa huur", "dia"),
    "de": ("Extras", "pro Miettag", "pro Miete", "Tage"),
}

_DOSSIER_MESSAGES = {
    "en": {
        "documents": "Your car is available. I’ll help you complete the last steps so our office can review and prepare your rental. Upload each document securely below:\n{links}\n\nOur team will check the copies manually.",
        "contract": "Your pre-contract is ready to review and sign:\n{url}\n\nOur office will complete the final approval after all requirements are checked.",
        "payment": "To secure your car, please pay the {percent}% reservation payment of USD {amount} within {hours} hours using this secure link:\n{url}\n\nYour car is not reserved until our team has verified the payment. If payment is not verified within {hours} hours, this reservation request expires and the vehicle will not be held.\n\nAfter paying, reply ‘Paid’ here so our team can verify it.",
        "documents_direct": "Your car is available. Will you use a passport or an ID card for your reservation?",
        "documents_replacement": "Please resend {slot} here in WhatsApp as a clear JPG, PNG, or PDF under 10 MB.",
    },
    "nl": {
        "documents": "Je auto is beschikbaar. Ik help je met de laatste stappen zodat ons kantoor je huur kan beoordelen en voorbereiden. Upload elk document veilig hieronder:\n{links}\n\nOns team controleert de kopieën handmatig.",
        "contract": "Je voorcontract staat klaar om te bekijken en te ondertekenen:\n{url}\n\nOns kantoor geeft de definitieve goedkeuring nadat alles is gecontroleerd.",
        "payment": "Om je auto vast te leggen, betaal je binnen {hours} uur de reserveringsaanbetaling van {percent}% (USD {amount}) via deze beveiligde link:\n{url}\n\nDe auto is pas voor jou gereserveerd nadat ons team de betaling heeft gecontroleerd. Als de betaling niet binnen {hours} uur is gecontroleerd, vervalt deze reserveringsaanvraag en wordt de auto niet vastgehouden.\n\nAntwoord na betaling hier met ‘Betaald’, zodat ons team dit kan controleren.",
        "documents_direct": "Je auto is beschikbaar. Gebruik je een paspoort of identiteitskaart voor je reservering?",
        "documents_replacement": "Stuur {slot} opnieuw hier in WhatsApp als duidelijke JPG, PNG of PDF onder 10 MB.",
    },
    "pap": {
        "documents": "Bo outo ta disponibel. Mi ta yuda bo ku e último pasonan pa nos oficina por kontrolá i prepará bo huur. Carga kada dokumento sigur aki bou:\n{links}\n\nNos tim ta kontrolá e kopianan manualmente.",
        "contract": "Bo pre-kontrakto ta kla pa lesa i firma:\n{url}\n\nNos oficina ta hasi e aprobashon final despues ku tur rekisito ta kontrolá.",
        "payment": "Pa sigurá bo outo, paga e pago di reservashon di {percent}% (USD {amount}) denter di {hours} ora via e enlace sigur aki:\n{url}\n\nE outo ta reservá pa bo solamente despues ku nos tim a verifiká e pago. Si nos no por verifiká e pago denter di {hours} ora, e petishon di reservashon ta kaduká i e outo no ta wordu tené.\n\nDespues di paga, kontestá ‘Mi a paga’ aki pa nos tim por verifik'é.",
        "documents_direct": "Bo outo ta disponibel. Bo ta usa pasport òf karta di identidat pa bo reservashon?",
        "documents_replacement": "Manda {slot} atrobe aki den WhatsApp komo un JPG, PNG òf PDF kla bou di 10 MB.",
    },
    "de": {
        "documents": "Ihr Auto ist verfügbar. Ich helfe Ihnen bei den letzten Schritten, damit unser Büro die Miete prüfen und vorbereiten kann. Laden Sie jedes Dokument sicher hoch:\n{links}\n\nUnser Team prüft die Kopien manuell.",
        "contract": "Ihr Vorvertrag ist bereit zum Prüfen und Unterschreiben:\n{url}\n\nUnser Büro erteilt die endgültige Freigabe, nachdem alles geprüft wurde.",
        "payment": "Um Ihr Fahrzeug zu sichern, zahlen Sie bitte innerhalb von {hours} Stunden die Reservierungsanzahlung von {percent}% (USD {amount}) über diesen sicheren Link:\n{url}\n\nDas Fahrzeug ist erst für Sie reserviert, nachdem unser Team die Zahlung geprüft hat. Wird die Zahlung nicht innerhalb von {hours} Stunden bestätigt, verfällt die Reservierungsanfrage und das Fahrzeug wird nicht freigehalten.\n\nAntworten Sie nach der Zahlung hier mit ‘Bezahlt’, damit unser Team sie prüfen kann.",
        "documents_direct": "Ihr Auto ist verfügbar. Verwenden Sie für Ihre Reservierung einen Reisepass oder Personalausweis?",
        "documents_replacement": "Bitte senden Sie {slot} hier in WhatsApp erneut als klare JPG-, PNG- oder PDF-Datei unter 10 MB.",
    },
}

_DOCUMENT_SLOT_LABELS = {
    "en": {"license_front": "Driver’s licence — front", "license_back": "Driver’s licence — back", "identity": "Passport or national ID"},
    "nl": {"license_front": "Rijbewijs — voorkant", "license_back": "Rijbewijs — achterkant", "identity": "Paspoort of identiteitskaart"},
    "pap": {"license_front": "Rijbewijs — parti dilanti", "license_back": "Rijbewijs — parti patras", "identity": "Pasport òf karta di identidat"},
    "de": {"license_front": "Führerschein — Vorderseite", "license_back": "Führerschein — Rückseite", "identity": "Reisepass oder Personalausweis"},
}


def send_customer_requirement_link(
    reservation_public_id: str,
    requirement: str,
    payload: dict,
) -> bool:
    """Send one provider-confirmed customer-file step without logging its URL."""
    from agents.social import ali_customer_dossier

    if requirement not in {"documents", "contract", "payment"}:
        raise AliReservationError("invalid_requirement_delivery", 422)
    context = ali_customer_dossier.customer_delivery_context(reservation_public_id)
    locale = context["locale"] if context["locale"] in _DOSSIER_MESSAGES else "en"
    if requirement == "documents":
        links = payload.get("links") if isinstance(payload, dict) else None
        if isinstance(payload, dict) and payload.get("mode") == "direct_whatsapp":
            links = []
            replacement_slot = str(payload.get("replacementSlot") or "")
            if replacement_slot:
                message = _DOSSIER_MESSAGES[locale]["documents_replacement"].format(
                    slot=_DOCUMENT_SLOT_LABELS[locale].get(
                        replacement_slot, replacement_slot,
                    )
                )
            else:
                message = _DOSSIER_MESSAGES[locale]["documents_direct"]
        elif not isinstance(links, list) or not links:
            raise AliReservationError("document_links_missing", 409)
        else:
            labels = _DOCUMENT_SLOT_LABELS[locale]
            rendered = "\n".join(
                f"{labels.get(str(item.get('slot')), str(item.get('slot')))}: {item.get('url')}"
                for item in links if isinstance(item, dict) and item.get("url")
            )
            message = _DOSSIER_MESSAGES[locale][requirement].format(links=rendered)
    else:
        url = str(payload.get("url") if isinstance(payload, dict) else "")
        if not url.startswith("https://"):
            raise AliReservationError("customer_requirement_url_missing", 409)
        amount = str(payload.get("amount") or "") if isinstance(payload, dict) else ""
        if requirement == "payment" and not re.fullmatch(r"\d+(?:\.\d{2})", amount):
            raise AliReservationError("customer_payment_amount_missing", 409)
        percent = payload.get("percent") if isinstance(payload, dict) else None
        if requirement == "payment" and (
            isinstance(percent, bool)
            or not isinstance(percent, int)
            or not 1 <= percent <= 100
        ):
            raise AliReservationError("customer_payment_percent_missing", 409)
        message = _DOSSIER_MESSAGES[locale][requirement].format(
            url=url,
            amount=amount,
            percent=percent,
            hours=PAYMENT_WINDOW_HOURS,
        )
    if requirement == "documents":
        delivery_material = (
            "direct_whatsapp_v2:"
            + str(payload.get("replacementSlot") or "identity_type")
            if isinstance(payload, dict) and payload.get("mode") == "direct_whatsapp"
            else "\n".join(
                str(item.get("url") or "")
                for item in links
                if isinstance(item, dict)
            )
        )
    else:
        delivery_material = url
    delivery_fingerprint = hashlib.sha256(
        delivery_material.encode("utf-8")
    ).hexdigest()[:16]
    delivered = send_dm_reply(
        context["conversation_id"],
        context["account_id"],
        message,
        confirm_delivery=True,
        idempotency_key=(
            f"ali-reservation-{requirement}-{reservation_public_id}-"
            f"{delivery_fingerprint}"
        ),
    )
    ali_customer_dossier.record_requirement_delivery(
        reservation_public_id,
        requirement,
        bool(delivered),
        "customer_requirement_delivery",
    )
    if (
        requirement == "documents"
        and isinstance(payload, dict)
        and payload.get("mode") == "direct_whatsapp"
        and not payload.get("replacementSlot")
    ):
        from agents.social import ali_reservation_v2

        if ali_reservation_v2.enabled():
            ali_reservation_v2.record_customer_delivery_result(
                reservation_public_id,
                "documents_prompt",
                sent=bool(delivered),
            )
    return bool(delivered)


_RESERVATION_REMINDERS = {
    "en": "Just a reminder — your reservation is still on hold. {next}",
    "nl": "Even een herinnering — je reservering staat nog in de wacht. {next}",
    "pap": "Un rekordatorio — bo reservashon ta ainda warda. {next}",
    "de": "Eine kurze Erinnerung — Ihre Reservierung wird noch vorgemerkt. {next}",
}

_RESERVATION_HOLD_EXPIRED = {
    "en": "I’ve released the car-category hold for now. If you still need a car later, message me and I’ll check availability again.",
    "nl": "Ik heb de reservering van de autocategorie voorlopig vrijgegeven. Als je later nog een auto nodig hebt, stuur me een bericht en ik controleer de beschikbaarheid opnieuw.",
    "pap": "Mi a laga e reserva di kategoria di outo liber pa awor. Si bo tin mester di un outo despues, manda mi un mensahe i mi lo kontrolá disponibilidat atrobe.",
    "de": "Ich habe die Vormerkung der Fahrzeugkategorie vorerst freigegeben. Wenn Sie später noch ein Auto benötigen, schreiben Sie mir und ich prüfe die Verfügbarkeit erneut.",
}

_RESERVATION_NEXT_STEPS = {
    "en": {
        "choose_identity_type": "Tell me whether you’ll use a passport or ID card.",
        "send_expected_document": "Please send the requested document here in WhatsApp.",
        "report_payment": "Please let me know here once the payment is complete.",
    },
    "nl": {
        "choose_identity_type": "Laat weten of je een paspoort of identiteitskaart gebruikt.",
        "send_expected_document": "Stuur het gevraagde document hier in WhatsApp.",
        "report_payment": "Laat het hier weten zodra de betaling is voltooid.",
    },
    "pap": {
        "choose_identity_type": "Laga mi sa si bo ta usa pasport òf karta di identidat.",
        "send_expected_document": "Manda e dokumento pidi aki den WhatsApp.",
        "report_payment": "Laga mi sa aki ora e pago ta kla.",
    },
    "de": {
        "choose_identity_type": "Teilen Sie mir mit, ob Sie einen Reisepass oder Personalausweis verwenden.",
        "send_expected_document": "Senden Sie das angeforderte Dokument bitte hier in WhatsApp.",
        "report_payment": "Geben Sie mir hier Bescheid, sobald die Zahlung abgeschlossen ist.",
    },
}


def reservation_reminder_text(locale: str, next_action: str) -> str:
    """Return one concise reminder; pricing and customer data are never repeated."""
    language = str(locale or "en").lower().split("-", 1)[0]
    language = language if language in _RESERVATION_REMINDERS else "en"
    next_step = _RESERVATION_NEXT_STEPS[language].get(
        str(next_action or ""),
        _RESERVATION_NEXT_STEPS[language]["send_expected_document"],
    )
    return _RESERVATION_REMINDERS[language].format(next=next_step)


def reservation_hold_expired_text(locale: str) -> str:
    language = str(locale or "en").lower().split("-", 1)[0]
    return _RESERVATION_HOLD_EXPIRED.get(
        language, _RESERVATION_HOLD_EXPIRED["en"],
    )


def _supplement_summary(pricing: dict, rental: dict, locale: str) -> str:
    heading, per_day, per_rental, days_label = SUPPLEMENT_LABELS[locale]
    lines = []
    supplement_names = [
        str(item.get("name") or "")
        for item in rental.get("supplements") or []
        if isinstance(item, dict)
    ]
    supplement_index = 0
    for item in pricing.get("items") or []:
        if item.get("category") != "extra":
            continue
        name = (
            supplement_names[supplement_index]
            if supplement_index < len(supplement_names)
            else item.get("description", "Supplement")
        )
        supplement_index += 1
        basis = item.get("billingBasis")
        basis_label = per_day if basis == "per_day" else per_rental
        detail = (
            f"{name}: {item.get('quantity')} × "
            f"USD {(item.get('unitPrice') or {}).get('amount')} {basis_label}"
        )
        if basis == "per_day":
            detail += f" × {item.get('rentalDays')} {days_label}"
        detail += f" = USD {(item.get('total') or {}).get('amount')}"
        lines.append(detail)
    return f"{heading}:\n" + "\n".join(lines) + "\n" if lines else ""


def _valid_email(value: str) -> str:
    value = str(value or "").strip()
    return value if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) else ""


def resolve_staff_recipients() -> list[str]:
    business = config_loader.get_business() or {}
    default = _valid_email(business.get("support_email") or business.get("email"))
    settings = state_registry.get_alert_settings(default_email_destination=default)
    email = (settings.get("channels") or {}).get("email") or {}
    if not email.get("enabled"):
        return []
    primary = _valid_email(email.get("destination") or default)
    alternative = _valid_email(email.get("alternativeDestination"))
    return list(dict.fromkeys(value for value in (primary, alternative) if value))


def _dashboard_link(conversation_id: str) -> str:
    business = config_loader.get_business() or {}
    base = str(business.get("dashboard_url") or "").rstrip("/")
    return f"{base}/messages/{conversation_id}" if base else "Open the conversation in Unboks."


def send_staff_email(quote: dict, pdf_bytes: bytes) -> bool:
    recipients = resolve_staff_recipients()
    if not recipients:
        return False
    customer = json.loads(quote["customer_json"])
    rental = json.loads(quote["rental_json"])
    pricing = json.loads(quote["pricing_json"])
    elapsed = max(0, int((datetime.now(tz=CURACAO) - datetime.fromisoformat(quote["confirmed_at"].replace("Z", "+00:00")).astimezone(CURACAO)).total_seconds() // 60))
    vehicle = rental.get("vehicle_name") or rental.get("vehicle_class_name") or "Selected category"
    body = (
        f"Customer: {customer.get('name', '')}\n"
        f"WhatsApp: {customer.get('whatsapp', '')}\n"
        f"Vehicle: {vehicle}\n"
        f"Rental period: {format_rental_period(rental.get('rental_start', ''), rental.get('rental_end', ''), 'en')}\n"
        f"Pickup: {rental.get('pickup_location')}\nReturn: {rental.get('return_location')}\n"
        f"Rental total: USD {pricing['rentalTotal']['amount']}\n"
        f"Refundable deposit: USD {pricing['refundableSecurityDeposit']['amount']}\n"
        f"Valid until: {format_curacao_datetime(pricing.get('expiresAt', ''), 'en')}\nElapsed SLA time: {elapsed} minutes\n"
        f"Conversation: {_dashboard_link(quote['conversation_id'])}"
    )
    subject = f"New Ali quote - {quote['quote_reference']} - {customer.get('name', '')}"
    filename = build_quote_filename(
        customer.get("name", ""), quote["quote_reference"],
        pricing.get("createdAt", ""),
    )
    try:
        for recipient in recipients:
            smtp_send(recipient, subject, body, pdf_attachment=(filename, pdf_bytes))
        return True
    except Exception:
        return False


def send_customer_whatsapp(quote: dict, _pdf_path: str) -> bool:
    base_url = os.environ.get("UNBOKS_PUBLIC_BASE_URL", "")
    secret = os.environ.get("ALI_QUOTE_DOWNLOAD_SECRET", "")
    if not base_url.startswith("https://") or not secret:
        return False
    pricing = json.loads(quote["pricing_json"])
    customer = json.loads(quote["customer_json"])
    text = build_customer_quote_text(quote)
    url = build_signed_url(base_url, quote["public_id"], secret)
    filename = build_quote_filename(
        customer.get("name", ""), quote["quote_reference"],
        pricing.get("createdAt", ""),
    )
    delivered = send_dm_reply_with_attachment(
        quote["conversation_id"], quote["zernio_account_id"], text,
        url, attachment_type="file", attachment_name=filename,
        idempotency_key=f"ali-quote-pdf-{quote['public_id']}",
    )
    bm_logger.log(
        "ali_quote_pdf_terminal_delivery",
        quote_public_id_prefix=str(quote.get("public_id") or "")[:12],
        quote_reference=str(quote.get("quote_reference") or "")[:40],
        delivered=delivered,
    )
    return delivered


def build_customer_quote_text(quote: dict) -> str:
    """Build the production customer caption without performing delivery."""
    pricing = json.loads(quote["pricing_json"])
    rental = json.loads(quote.get("rental_json") or "{}")
    locale = quote.get("locale") if quote.get("locale") in MESSAGES else "en"
    ready, reply = MESSAGES[locale]
    supplement_summary = _supplement_summary(pricing, rental, locale)
    return (
        f"{ready}\n\nQuote: {quote['quote_reference']}\n"
        f"Rental total: USD {pricing['rentalTotal']['amount']}\n"
        f"{supplement_summary}"
        f"Refundable security deposit: USD {pricing['refundableSecurityDeposit']['amount']}\n"
        f"{VALID_UNTIL[locale]}: {format_curacao_datetime(pricing['expiresAt'], locale)}\n\n"
        f"{reply}"
    )


def send_customer_brand_image(quote: dict, _image_path: str) -> bool:
    base_url = os.environ.get("UNBOKS_PUBLIC_BASE_URL", "")
    secret = os.environ.get("ALI_QUOTE_DOWNLOAD_SECRET", "")
    if not base_url.startswith("https://") or not secret:
        return False
    url = build_signed_url(
        base_url, quote["public_id"], secret, asset="image",
    )
    return send_dm_reply_with_attachment(
        quote["conversation_id"], quote["zernio_account_id"], "",
        url, attachment_type="image",
    )


def send_customer_post_quote_actions(quote: dict) -> bool:
    """Send and persist the signed choices only after confirmed PDF delivery."""
    try:
        control = build_post_quote_control(quote)
    except AliReservationError:
        return False
    result = send_dm_post_quote_actions(
        quote["conversation_id"],
        quote["zernio_account_id"],
        control,
    )
    provider_ids = [
        str(item)
        for item in result.get("provider_message_ids") or []
        if str(item).strip()
    ][:10]
    if provider_ids:
        update_quote(
            quote["public_id"],
            post_quote_control_provider_ids_json=json.dumps(provider_ids),
        )
    return bool(result.get("success"))


def send_customer_reservation_confirmation(reservation: dict) -> dict:
    """Deliver a confirmed informational PDF without rolling back confirmation."""
    if (
        not isinstance(reservation, dict)
        or reservation.get("status") != "confirmed"
        or not reservation.get("confirmation_pdf_path")
    ):
        raise AliReservationError("reservation_not_confirmed", 409)
    if reservation.get("confirmation_delivery_status") in {"accepted", "confirmed"}:
        return reservation
    base_url = os.environ.get("UNBOKS_PUBLIC_BASE_URL", "")
    secret = os.environ.get("ALI_QUOTE_DOWNLOAD_SECRET", "")
    if not base_url.startswith("https://") or not secret:
        ok = False
    else:
        url = build_signed_url(
            base_url,
            reservation["public_id"],
            secret,
            asset="confirmation",
        )
        reference = str(reservation.get("confirmation_reference") or "")
        filename = f"Ali-Car-Rental-Reservation-{reference}.pdf"
        text = (
            "Your Ali Car Rental reservation is confirmed.\n\n"
            f"Reservation: {reference}\n"
            "Your confirmation document is attached."
        )
        ok = send_dm_reply_with_attachment(
            reservation["conversation_id"],
            reservation["zernio_account_id"],
            text,
            url,
            attachment_type="file",
            attachment_name=filename,
            idempotency_key=(
                f"ali-reservation-confirmation-{reservation['public_id']}"
            ),
        )
    updated = record_confirmation_delivery(
        reservation["public_id"],
        "accepted" if ok else "failed",
        actor="confirmation_delivery",
        error_code=None if ok else "customer_confirmation_delivery_failed",
    )
    if not ok:
        quote = get_quote(str(reservation.get("quote_public_id") or "")) or {}
        try:
            customer = json.loads(quote.get("customer_json") or "{}")
        except (TypeError, ValueError):
            customer = {}
        state_registry.create_pending_notification(
            "escalation",
            "whatsapp",
            reservation["conversation_id"],
            customer.get("name") or "Ali reservation customer",
            "[ALI CONFIRMATION DELIVERY FAILED]",
            (
                "The reservation is confirmed, but its customer confirmation "
                "document was not delivered. Open the conversation in Unboks."
            ),
            mode="hard",
        )
    return updated


def send_operator_alerts(quote: dict) -> dict:
    settings = state_registry.get_alert_settings(default_email_destination="")
    channels = settings.get("channels") or {}
    customer = json.loads(quote["customer_json"])
    rental = json.loads(quote["rental_json"])
    pricing = json.loads(quote["pricing_json"])
    text = (
        "New Ali quote ready\n"
        f"Customer: {customer.get('name', '')}\nQuote: {quote['quote_reference']}\n"
        f"Vehicle: {rental.get('vehicle_name') or rental.get('vehicle_class_name') or 'Selected category'}\n"
        f"Total: USD {pricing['rentalTotal']['amount']}\nOpen in Unboks"
    )
    outcomes = {}
    whatsapp = channels.get("whatsapp") or {}
    if whatsapp.get("enabled"):
        route = state_registry.get_resolved_operator_whatsapp_route()
        if route:
            outcomes["whatsapp"] = "sent" if send_dm_reply(route["conversation_id"], route["account_id"], text) else "failed"
        else:
            outcomes["whatsapp"] = "skipped"
    for channel in ("telegram", "messenger"):
        if (channels.get(channel) or {}).get("enabled"):
            outcomes[channel] = "skipped"
    return outcomes


def escalate(quote: dict, code: str) -> None:
    state_registry.create_pending_notification(
        "escalation", "whatsapp", quote["conversation_id"], "Ali quote customer",
        f"[ALI QUOTE ATTENTION] {quote.get('quote_reference') or quote['public_id']}",
        f"Quote stage failed safely. Code: {code}. Open the conversation in Unboks.",
        mode="hard",
    )


def production_adapters() -> DeliveryAdapters:
    return DeliveryAdapters(
        send_brand_image=send_customer_brand_image,
        send_whatsapp=send_customer_whatsapp,
        send_staff_email=send_staff_email,
        send_operator_alerts=send_operator_alerts,
        escalate=escalate,
        send_post_quote_actions=send_customer_post_quote_actions,
    )
