"""Concrete Ali quote delivery adapters using existing Unboks providers."""

from __future__ import annotations

import json
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
from agents.social.ali_quote_workflow import DeliveryAdapters
from agents.social.zernio_dm_client import send_dm_reply, send_dm_reply_with_attachment
from shared import config_loader, state_registry

CURACAO = ZoneInfo("America/Curacao")

MESSAGES = {
    "en": ("Your official Ali Car Rental quote is ready.", "Reply here to accept it or ask me a question.", "Subject to final vehicle availability confirmation."),
    "nl": ("Je officiële offerte van Ali Car Rental is klaar.", "Reageer hier om te accepteren of iets te vragen.", "Onder voorbehoud van definitieve beschikbaarheid."),
    "pap": ("Bo oferta ofisial di Ali Car Rental ta kla.", "Kontestá aki pa aseptá of hasi un pregunta.", "Suhéto na konfirmashon final di disponibilidat."),
    "de": ("Ihr offizielles Angebot von Ali Car Rental ist fertig.", "Antworten Sie hier, um anzunehmen oder etwas zu fragen.", "Vorbehaltlich der endgültigen Fahrzeugverfügbarkeit."),
}

VALID_UNTIL = {
    "en": "Valid until",
    "nl": "Geldig tot",
    "pap": "Válido te ku",
    "de": "Gültig bis",
}


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
    locale = quote.get("locale") if quote.get("locale") in MESSAGES else "en"
    ready, reply, availability = MESSAGES[locale]
    text = (
        f"{ready}\n\nQuote: {quote['quote_reference']}\n"
        f"Rental total: USD {pricing['rentalTotal']['amount']}\n"
        f"Refundable security deposit: USD {pricing['refundableSecurityDeposit']['amount']}\n"
        f"{VALID_UNTIL[locale]}: {format_curacao_datetime(pricing['expiresAt'], locale)}\n\n"
        f"{reply}\n{availability}"
    )
    url = build_signed_url(base_url, quote["public_id"], secret)
    filename = build_quote_filename(
        customer.get("name", ""), quote["quote_reference"],
        pricing.get("createdAt", ""),
    )
    return send_dm_reply_with_attachment(
        quote["conversation_id"], quote["zernio_account_id"], text,
        url, attachment_type="file", attachment_name=filename,
    )


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
        send_whatsapp=send_customer_whatsapp,
        send_staff_email=send_staff_email,
        send_operator_alerts=send_operator_alerts,
        escalate=escalate,
    )
