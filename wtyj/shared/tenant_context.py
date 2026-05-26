"""Canonical tenant language, safety, and prompt context helpers.

These helpers keep live agent replies, dashboard reply suggestions, and DM
paths aligned on tenant language and safety rules.
"""

from __future__ import annotations

import re
from typing import Any

from shared import config_loader, bm_logger


_SUPPORTED_LANGUAGE_NAMES = {
    "english": "English",
    "spanish": "Spanish",
    "español": "Spanish",
    "dutch": "Dutch",
    "nederlands": "Dutch",
    "papiamentu": "Papiamentu",
    "portuguese": "Portuguese",
    "português": "Portuguese",
    "german": "German",
    "deutsch": "German",
    "swedish": "Swedish",
    "svenska": "Swedish",
}


_SPANISH_MARKERS = (
    "hola", "gracias", "quiero", "necesito", "cita", "consulta",
    "clínica", "clinica", "por favor", "mañana", "buenos", "buenas",
)
_DUTCH_MARKERS = ("hallo", "graag", "afspraak", "morgen", "bedankt")
_PAPIAMENTU_MARKERS = ("bon dia", "bon tardi", "mi ke", "mi por", "kon ta")
_PORTUGUESE_MARKERS = ("olá", "obrigado", "consulta", "marcar", "por favor")


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normal_language(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return _SUPPORTED_LANGUAGE_NAMES.get(value.strip().lower(), value.strip())


def _normal_languages(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [v.strip() for v in values.split(",")]
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        lang = _normal_language(value)
        if lang and lang not in out:
            out.append(lang)
    return out


def canonical_business(raw: dict | None = None) -> dict:
    """Return the business config shape every AI path should consume.

    Backwards compatible with old flat Nr3 tenant files by reading top-level
    fields and normalizing them into business.* without mutating disk.
    """
    raw = raw if isinstance(raw, dict) else config_loader.get_raw()
    business = dict(raw.get("business", {}) or {})
    language_candidates = (
        business.get("languages"),
        raw.get("languages"),
        raw.get("language"),
    )
    languages: list[str] = []
    for candidate in language_candidates:
        languages = _normal_languages(candidate)
        if languages:
            break
    primary = _normal_language(
        _first_text(
            business.get("primary_language"),
            raw.get("primary_language"),
            raw.get("locale_language"),
        )
    )
    if primary and primary not in languages:
        languages.insert(0, primary)
    if not primary and languages:
        primary = languages[0]

    fallbacks = {
        "slug": _first_text(business.get("slug"), raw.get("slug")),
        "name": _first_text(
            business.get("name"), raw.get("business_name"), raw.get("name"), raw.get("slug")
        ),
        "email": _first_text(business.get("email"), raw.get("email")),
        "support_email": _first_text(
            business.get("support_email"), raw.get("support_email"), raw.get("email")
        ),
        "phone": _first_text(business.get("phone"), raw.get("phone"), raw.get("whatsapp")),
        "whatsapp": _first_text(business.get("whatsapp"), raw.get("whatsapp")),
        "website": _first_text(business.get("website"), raw.get("website")),
        "country": _first_text(business.get("country"), raw.get("country")),
        "locale": _first_text(business.get("locale"), raw.get("locale")),
        "agent_name": _first_text(business.get("agent_name"), raw.get("agent_name"), "Agent"),
        "agent_tone": _first_text(
            business.get("agent_tone"),
            raw.get("agent_tone"),
            (raw.get("agent_persona") or {}).get("tone") if isinstance(raw.get("agent_persona"), dict) else "",
        ),
        "notes": _first_text(
            business.get("notes"),
            business.get("business_brief"),
            raw.get("business_brief"),
            raw.get("notes"),
        ),
        "primary_language": primary,
        "languages": languages,
    }
    for key, value in fallbacks.items():
        if value and not business.get(key):
            business[key] = value
    return business


def tenant_slug(raw: dict | None = None) -> str:
    business = canonical_business(raw)
    return (
        business.get("slug")
        or config_loader.get_raw().get("slug")
        or __import__("os").environ.get("TENANT_SLUG")
        or __import__("os").environ.get("TENANT_ID")
        or "unknown"
    )


def detect_message_language(text: str) -> str:
    clean = (text or "").strip().lower()
    if not clean:
        return ""
    marker_sets = (
        ("Spanish", _SPANISH_MARKERS),
        ("Dutch", _DUTCH_MARKERS),
        ("Papiamentu", _PAPIAMENTU_MARKERS),
        ("Portuguese", _PORTUGUESE_MARKERS),
    )
    for language, markers in marker_sets:
        if any(marker in clean for marker in markers):
            return language
    if re.search(r"\b(the|and|please|thanks|hello|hi|appointment)\b", clean):
        return "English"
    return ""


def preferred_language(message_text: str = "", raw: dict | None = None) -> str:
    business = canonical_business(raw)
    langs = business.get("languages") or []
    primary = business.get("primary_language") or (langs[0] if langs else "")
    detected = detect_message_language(message_text)
    if detected and (not langs or detected in langs):
        return detected
    if primary:
        return primary
    country_locale = f"{business.get('country', '')} {business.get('locale', '')}".lower()
    if "es" in country_locale or "spain" in country_locale or "curaçao" in country_locale:
        return "Spanish"
    bm_logger.log("tenant_language_missing", tenant=tenant_slug(raw))
    return "Multilingual"


def clinical_guardrails(raw: dict | None = None) -> list[str]:
    raw = raw if isinstance(raw, dict) else config_loader.get_raw()
    blocks: list[Any] = [
        raw.get("clinical_guardrails"),
        raw.get("safety"),
        raw.get("compliance"),
        raw.get("safety_restrictions"),
        raw.get("guardrails"),
    ]
    business = raw.get("business")
    if isinstance(business, dict):
        blocks.extend([
            business.get("clinical_guardrails"),
            business.get("safety"),
            business.get("compliance"),
            business.get("safety_restrictions"),
        ])
    rules: list[str] = []
    for block in blocks:
        if isinstance(block, str) and block.strip():
            rules.append(block.strip())
        elif isinstance(block, list):
            rules.extend(str(item).strip() for item in block if str(item).strip())
        elif isinstance(block, dict):
            for value in block.values():
                if isinstance(value, str) and value.strip():
                    rules.append(value.strip())
                elif isinstance(value, list):
                    rules.extend(str(item).strip() for item in value if str(item).strip())
    slug_name = f"{tenant_slug(raw)} {canonical_business(raw).get('name', '')}".lower()
    if any(marker in slug_name for marker in ("clinica", "clínica", "clinic", "roberto")):
        rules.extend([
            "No diagnosis.",
            "No therapy advice.",
            "No clinical advice.",
            "No crisis counseling.",
            "No emergency handling beyond safe redirection.",
            "Encourage contacting the clinic directly for clinical matters.",
            "If urgent, emergency, or crisis language appears, tell the user to contact local emergency services or a qualified professional immediately.",
        ])
    deduped: list[str] = []
    for rule in rules:
        if rule not in deduped:
            deduped.append(rule)
    return deduped


def safety_prompt_block(raw: dict | None = None) -> str:
    rules = clinical_guardrails(raw)
    if not rules:
        return ""
    return (
        "TENANT SAFETY AND COMPLIANCE RULES (highest priority):\n"
        + "\n".join(f"- {rule}" for rule in rules)
        + "\nIf these rules conflict with a user request, follow the rules and redirect safely."
    )


def language_prompt_block(channel: str, latest_message: str = "", raw: dict | None = None) -> str:
    business = canonical_business(raw)
    langs = business.get("languages") or []
    primary = business.get("primary_language") or preferred_language(latest_message, raw)
    supported = ", ".join(langs) if langs else "Not configured"
    return (
        "TENANT LANGUAGE RULES:\n"
        f"- Primary language: {primary or 'Not configured'}.\n"
        f"- Supported languages: {supported}.\n"
        "- Reply in the customer's latest message language when clear and supported.\n"
        "- If unclear, use the tenant primary language. If no language is configured, use a short neutral multilingual fallback and alert the operator.\n"
        f"- Channel: {channel}."
    )


def localized_fallback_reply(
    *,
    message_text: str = "",
    channel: str = "whatsapp",
    raw: dict | None = None,
) -> str:
    language = preferred_language(message_text, raw)
    business = canonical_business(raw)
    name = business.get("name") or "the team"
    clinical = bool(clinical_guardrails(raw))
    if language == "Spanish":
        if clinical:
            return (
                "Gracias por escribir. Ahora no puedo responder con detalle. "
                "Para temas clínicos, contacta directamente a la clínica. "
                "Si es urgente, contacta a emergencias locales o a un profesional cualificado."
            )
        return (
            "Gracias por escribir. Ahora no puedo responder con detalle. "
            "El equipo lo revisará y te responderá pronto."
        )
    if language == "Dutch":
        return "Dank je voor je bericht. Ik kan nu niet volledig antwoorden. Het team kijkt mee en reageert zo snel mogelijk."
    if language == "Papiamentu":
        return "Masha danki pa bo mensahe. Mi no por kontestá kompleto awor. E team ta wak esaki i ta kontestá pronto."
    if language == "Portuguese":
        return "Obrigado pela mensagem. Não consigo responder em detalhe agora. A equipa vai verificar e responder em breve."
    if language == "Multilingual":
        return "Thank you / Gracias. We received your message. The team will review it and reply shortly."
    return f"Thanks for your message. I cannot answer in detail right now. {name} will review this and reply shortly."


def config_warnings(raw: dict | None = None) -> list[str]:
    raw = raw if isinstance(raw, dict) else config_loader.get_raw()
    business = canonical_business(raw)
    warnings: list[str] = []
    if not business.get("primary_language") and not business.get("languages"):
        warnings.append("Missing tenant language configuration.")
    if clinical_guardrails(raw) and not safety_prompt_block(raw):
        warnings.append("Safety notes exist but are not available for prompt injection.")
    for key in ("name", "agent_name", "whatsapp", "website", "country", "locale"):
        if not business.get(key):
            warnings.append(f"Missing business.{key}.")
    return warnings
