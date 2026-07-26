"""Tenant-scoped hard process rules used by live prompt builders."""

from __future__ import annotations

import re

from shared import config_loader


CLINICA_ROBERTO_SLUG = "clinica-roberto"
CONSULTA_DESPERTARES_SLUG = "consulta-despertares"

CLINICA_ROBERTO_PHONE_PRIVACY_RULE = """TENANT HARD PRIVACY RULE - CLINICA ROBERTO:
For clinica-roberto, never automatically take, copy, store, infer, or use a customer phone number from WhatsApp metadata, caller ID, profile data, sender id, or the number the customer is messaging from.
If the customer says "use this number", "take my number from WhatsApp", "you already have my number", or similar, reply that for privacy reasons the customer must type the phone number explicitly in the chat.
Spanish required wording when appropriate: "Por motivos de privacidad, no puedo tomar ni guardar automáticamente tu número desde WhatsApp. Por favor, escríbenos aquí el número de teléfono que quieres que usemos."
English required wording when appropriate: "For privacy reasons, I can't automatically take or store your phone number from WhatsApp. Please type the phone number you want us to use here in the chat."
Only after the customer explicitly types the phone number in the chat may you treat it as customer-provided contact information."""

CONSULTA_DESPERTARES_WEBSITE_GREETING = (
    "Hola, soy la asistente virtual de Consulta Despertares."
)
CONSULTA_DESPERTARES_OTHER_GREETING = (
    "Hola, soy Alia, la asistente virtual de Consulta Despertares"
)
CONSULTA_DESPERTARES_CALLBACK_CLOSING = (
    "¿Cuándo te podemos llamar para confirmar la primera cita?"
)

_CONSULTA_WEBSITE_LEAD_RE = re.compile(
    r"consulta\s+psicol[oó]gica\s+despertares.*"
    r"necesito\s+m[aá]s\s+informaci[oó]n",
    re.IGNORECASE | re.DOTALL,
)
_CONSULTA_BOOKING_RE = re.compile(
    r"\b(?:cita|terapia|consulta|reservar|reserva|acudir|appointment|book|booking)\b",
    re.IGNORECASE,
)
_CONSULTA_SPECIFIC_TIME_RE = re.compile(
    r"(?:"
    r"\b(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|"
    r"ma[ñn]ana|pasado\s+ma[ñn]ana)\b|"
    r"\b\d{1,2}\s*(?:/|-)\s*\d{1,2}(?:\s*(?:/|-)\s*\d{2,4})?\b|"
    r"\b(?:[01]?\d|2[0-3])[:.h]\d{2}\b|"
    r"\ba\s+las\s+(?:[01]?\d|2[0-3])\b"
    r")",
    re.IGNORECASE,
)
_CONSULTA_CALLBACK_CLOSING_RE = re.compile(
    r"(?:\s*\n*)?"
    r"¿?\s*cu[aá]ndo\s+(?:te\s+podemos\s+llamar|podemos\s+llamarte)"
    r"\s+para\s+confirmar\s+la\s+primera\s+cita\s*\?\s*",
    re.IGNORECASE,
)


def current_tenant_slug() -> str:
    """Return the current tenant slug from canonical and legacy config shapes."""
    business = config_loader.get_business() or {}
    raw = config_loader.get_raw() or {}
    for value in (
        business.get("slug"),
        raw.get("slug"),
        raw.get("tenant_id"),
        raw.get("tenant_slug"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def is_clinica_roberto() -> bool:
    return current_tenant_slug() == CLINICA_ROBERTO_SLUG


def is_consulta_despertares() -> bool:
    return current_tenant_slug() == CONSULTA_DESPERTARES_SLUG


def phone_privacy_rule_block() -> str:
    if not is_clinica_roberto():
        return ""
    return CLINICA_ROBERTO_PHONE_PRIVACY_RULE


def prompt_sender_label(channel: str, sender: str) -> str:
    """Return a model-visible sender label without leaking Roberto WA metadata."""
    if channel == "whatsapp" and is_clinica_roberto():
        return "[WhatsApp sender withheld for privacy]"
    return sender


def _strip_leading_spanish_greeting(reply: str) -> str:
    """Remove a model-written Spanish salutation before adding the exact one."""
    clean = (reply or "").strip()
    if not clean:
        return ""
    return re.sub(
        r"^\s*¡?hola\b"
        r"(?:\s*,?\s*soy\b[^.!?\n]*[.!?]?|\s*[!.,:]?)\s*",
        "",
        clean,
        count=1,
        flags=re.IGNORECASE,
    ).strip()


def _strip_consulta_callback_closing(reply: str) -> str:
    """Remove the controlled callback question so it can be placed correctly."""
    clean = _CONSULTA_CALLBACK_CLOSING_RE.sub("", reply or "")
    clean = re.sub(r"[ \t]+\n", "\n", clean)
    while "\n\n\n" in clean:
        clean = clean.replace("\n\n\n", "\n\n")
    return clean.strip()


def _consulta_has_name_and_phone(fields: dict) -> bool:
    first_name = str(fields.get("first_name") or "").strip()
    surnames = str(fields.get("surnames") or "").strip()
    if not (first_name and surnames):
        name_parts = str(fields.get("customer_name") or "").strip().split()
        first_name = first_name or (name_parts[0] if name_parts else "")
        surnames = surnames or (" ".join(name_parts[1:]) if len(name_parts) > 1 else "")

    phone = str(fields.get("phone") or "").strip()
    digits = re.sub(r"\D", "", phone)
    return bool(first_name and surnames and 9 <= len(digits) <= 15)


def enforce_consulta_despertares_boundaries(
    reply: str,
    inbound_text: str,
    history: list,
    fields: dict,
    intents: list,
) -> str:
    """Deterministically enforce Consulta Despertares' mandatory boundaries.

    The model still writes the conversational body. This final guard owns the
    exact first-message greeting and the controlled callback closing so prompt
    non-compliance can never leak to a patient-facing WhatsApp reply.
    """
    if not reply or not is_consulta_despertares():
        return reply

    history = history or []
    fields = fields or {}
    intents = intents or []
    is_first_reply = not any(
        str(message.get("role") or "").lower() == "assistant"
        for message in history
        if isinstance(message, dict)
    )

    clean = _strip_consulta_callback_closing(reply)

    if is_first_reply:
        greeting = (
            CONSULTA_DESPERTARES_WEBSITE_GREETING
            if _CONSULTA_WEBSITE_LEAD_RE.search(inbound_text or "")
            else CONSULTA_DESPERTARES_OTHER_GREETING
        )
        if not clean.startswith(greeting):
            body = _strip_leading_spanish_greeting(clean)
            clean = greeting if not body else f"{greeting}\n\n{body}"
        return clean

    user_text = "\n".join(
        str(message.get("text") or "")
        for message in history
        if isinstance(message, dict)
        and str(message.get("role") or "").lower() == "user"
    )
    user_text = f"{user_text}\n{inbound_text or ''}".strip()
    booking_intent = bool(
        {"booking", "reschedule"}.intersection(
            str(intent or "").lower() for intent in intents
        )
    ) or bool(_CONSULTA_BOOKING_RE.search(user_text))
    already_has_timing = bool(
        fields.get("callback_preference")
        or fields.get("date")
        or fields.get("slot_time")
        or _CONSULTA_SPECIFIC_TIME_RE.search(user_text)
    )

    if (
        booking_intent
        and _consulta_has_name_and_phone(fields)
        and not already_has_timing
    ):
        clean = clean.rstrip()
        clean = (
            CONSULTA_DESPERTARES_CALLBACK_CLOSING
            if not clean
            else f"{clean}\n\n{CONSULTA_DESPERTARES_CALLBACK_CLOSING}"
        )
    return clean
