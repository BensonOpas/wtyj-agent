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
    "Hola, soy Alia, la asistente virtual de Consulta Despertares."
)
CONSULTA_DESPERTARES_OTHER_GREETING = (
    "Hola, soy Alia, la asistente virtual de Consulta Despertares"
)
CONSULTA_DESPERTARES_ENGLISH_GREETING = (
    "Hi, I'm Alia, the virtual assistant for Consulta Despertares."
)
CONSULTA_DESPERTARES_CALLBACK_CLOSING = (
    "¿Cuándo te podemos llamar para confirmar la primera cita?"
)
CONSULTA_DESPERTARES_ENGLISH_CALLBACK_CLOSING = (
    "When can we call you to confirm the first appointment?"
)
CONSULTA_DESPERTARES_APPOINTMENT_PREFERENCE_QUESTION = (
    "Antes de terminar, ¿qué día o franja horaria te vendría mejor para "
    "la primera cita?"
)
CONSULTA_DESPERTARES_ENGLISH_APPOINTMENT_PREFERENCE_QUESTION = (
    "Before we finish, what day or time window would suit you best for "
    "the first appointment?"
)
CONSULTA_DESPERTARES_ENGLISH_PROSPECT_QUESTION = (
    "Would you like to tell me a little more about what's been going on for "
    "you, so I can guide you toward the right support?"
)
CONSULTA_DESPERTARES_SPANISH_PROSPECT_QUESTION = (
    "¿Te apetece contarme un poco más sobre lo que te está pasando, para "
    "poder orientarte hacia el apoyo más adecuado?"
)
CONSULTA_DESPERTARES_RELATIONSHIP_FIRST_RULE = """
CONSULTA DESPERTARES RELATIONSHIP-FIRST INTAKE (HIGHEST PRIORITY):
The goal is a natural, supportive conversation that builds a useful prospect
card for the human team. It is NOT to collect fields as quickly as possible.
These rules override generic booking pacing and checklist-like intake.

- Listen and help first. Answer the customer's actual question before requesting
  contact details. If they share emotional or sensitive context, acknowledge it
  naturally and orient them without diagnosing.
- Before asking anything, re-read the ENTIRE conversation plus saved fields and
  silently extract every fact the customer has already volunteered. A fact from
  an earlier message is just as valid as one in the latest message. Never ask
  again for information that is already present anywhere in the thread.
- Never ask for first name, surnames, phone, or callback preference in the first
  substantive reply. First provide a useful answer or have a gentle contextual
  exchange. If the customer explicitly supplies any field, extract it silently.
- Treat a request for an appointment as the start of a conversation, not as a
  trigger to immediately request identity and phone data.
- Build the card progressively. Required for the callback: first_name, surnames,
  phone, and callback_preference. Treat appointment_preference as expected
  enrichment: ask for it once, naturally, before the handoff when the conversation
  is flowing. session_type is useful enrichment and visit_reason is always optional.
- If the customer gives a full name, store the given name in first_name and every
  remaining name word in surnames; do not make them repeat it in a labelled form.
- Store Presencial or Online in session_type only when established by what the
  customer says. Choosing a physical clinic or branch after locations are
  offered is explicit evidence for Presencial.
- Store the customer's preferred SESSION day or time in appointment_preference.
  callback_preference means only when the human team may CALL the customer.
  Never copy one value into the other.
- Capture visit_reason as one short, neutral paraphrase of why the customer
  is seeking psychological support, using what they volunteered anywhere in the
  conversation. Do not diagnose, reinterpret, or ask for intimate detail. A
  location, clinic, callback time, appointment time, or session format is NEVER
  a visit reason. If no reason was volunteered, invite it only when natural and
  make the opt-out clear.
- Ask at most ONE question total per reply. "Full name (name and surnames)" is
  one question. Never combine appointment availability and callback availability.
- On the first reply in a new conversation, greet and introduce yourself exactly
  once, in the same language as the customer's most recent message. Never include
  the greeting or introduction in two languages. On later replies, do not
  introduce yourself again.
- Do not fire intake questions back-to-back without engaging. Acknowledge or
  answer the current message naturally, then ask the single most useful missing
  question.
- Never end a substantive clinic reply with a generic service-desk closing such
  as "Is there anything else I can help you with?" or "How can I help you today?"
  Those phrases close the conversation and do not help the prospect feel heard.
- When the prospect has shared an emotional or mental-health concern and a
  specific intake field would be premature, invite them to say a little more
  about what has been going on so you can guide them toward the right support.
  Keep this gentle and optional; do not ask for intimate details or diagnose.
  Do NOT jump to "Would you like me to help you set that up?", "Would you like
  to speak with someone?", or another scheduling offer unless the prospect has
  asked to arrange contact. In this listening stage, end with the natural
  prospect-centered invitation shown below.
- The four callback fields are the minimum needed for contact, NOT a signal to
  stop the conversation or hand off immediately. Do not say that you are passing
  the details to the team while useful enrichment is still missing and the
  customer is comfortably engaged.
- After callback_preference is known, continue naturally with exactly one missing
  enrichment field per reply: first session_type, then appointment_preference,
  then an optional visit_reason invitation. appointment_preference should be
  requested once before handoff whenever the exchange remains comfortable and
  organic. Acknowledge the customer's answer before asking the next question;
  never present a checklist or fire questions back-to-back.
- Finish with a natural handoff only after those enrichment opportunities were
  completed, the customer declined them, or the customer is uncomfortable, in a
  hurry, or asks to stop. Never delay or block the callback because an enrichment
  field is missing.
- A normal request to speak with a psychologist, receive a callback, arrange an
  appointment, or ask when the team may call is the purpose of this workflow,
  not an unresolved human question. Set requires_human only when the latest
  message contains a separate question the agent genuinely cannot answer and the
  visible reply explicitly tells the customer that a human still needs to answer it.
- Natural engagement examples (adapt rather than repeat mechanically):
  English: "Would you like to tell me a little more about what's been going on for you, so I can guide you toward the right support?"
  Spanish: "¿Te apetece contarme un poco más sobre lo que te está pasando, para poder orientarte hacia el apoyo más adecuado?"
- Natural Spanish intake examples:
  "¿Preferirías que la primera sesión fuera presencial u online?";
  "¿Qué días o franjas te suelen venir mejor para la sesión?";
  "Si te apetece contarlo, ¿qué te gustaría trabajar o qué te ha llevado a buscar ayuda ahora?"
- If the customer declines, seems uncomfortable, is in a hurry, or asks to stop,
  stop collecting optional details immediately and proceed with the handoff.
- If the customer corrects you, objects, or says the exchange is confusing,
  address that first. Do not repeat or append another intake question.
- Do not ask which timezone applies. All times are understood as Spain local time.
- Do not display a checklist, field recap, or "we have everything" summary unless
  the customer explicitly asks for confirmation. A short natural acknowledgement
  is enough.
- Ask the approved callback closing only after first name, surnames, and phone are
  known, callback preference is missing, and no other question is open in the reply.
"""

_CONSULTA_WEBSITE_LEAD_RE = re.compile(
    r"consulta\s+psicol[oó]gica\s+despertares.*"
    r"necesito\s+m[aá]s\s+informaci[oó]n",
    re.IGNORECASE | re.DOTALL,
)
_CONSULTA_BOOKING_RE = re.compile(
    r"\b(?:cita|terapia|consulta|reservar|reserva|acudir|appointment|book|booking)\b",
    re.IGNORECASE,
)
_CONSULTA_SUPPORT_CONTEXT_RE = re.compile(
    r"\b(?:"
    r"feel|feeling|felt|emotion|emotional|mood|anxiety|anxious|stress|stressed|"
    r"depress(?:ed|ion)?|sad|invincible|indestructible|healthy|mental|"
    r"psychologist|psychiatrist|support|help|"
    r"siento|sentir|emoci[oó]n|estado\s+de\s+[aá]nimo|ansiedad|ansioso|"
    r"estr[eé]s|depresi[oó]n|deprimido|triste|invencible|saludable|"
    r"psic[oó]log[oa]|psiquiatra|apoyo|ayuda"
    r")\b",
    re.IGNORECASE,
)
_CONSULTA_GENERIC_HELP_CLOSING_RE = re.compile(
    r"(?:\s*\n*)?(?:"
    r"is\s+there\s+(?:anything|something)(?:\s+else)?\s+"
    r"(?:i|we)\s+can\s+help\s+you\s+with(?:\s+today)?"
    r"|how\s+can\s+(?:i|we)\s+help\s+you(?:\s+today)?"
    r"|would\s+you\s+like\s+to\s+(?:know|learn)\s+more\s+about\s+"
    r"how\s+we\s+can\s+help(?:\s+you)?"
    r"|would\s+you\s+like\s+(?:me|us)\s+to\s+help\s+you\s+"
    r"(?:set\s+(?:that|this)\s+up|with\s+(?:that|this))"
    r"|¿?te\s+gustar[ií]a\s+que\s+te\s+ayud(?:e|emos)\s+a\s+"
    r"(?:organizar|coordinar)\s+(?:eso|esto)"
    r"|¿?te\s+gustar[ií]a\s+saber\s+m[aá]s\s+sobre\s+c[oó]mo\s+"
    r"podemos\s+ayudarte"
    r"|¿?hay\s+algo\s+m[aá]s\s+en\s+lo\s+que\s+"
    r"(?:pueda|podamos)\s+ayudarte"
    r"|¿?en\s+qu[eé]\s+m[aá]s\s+(?:puedo|podemos)\s+ayudarte"
    r")\s*\?\s*$",
    re.IGNORECASE,
)

_CONSULTA_CALLBACK_CLOSING_RE = re.compile(
    r"(?:\s*\n*)?(?:"
    r"¿?\s*cu[aá]ndo\s+(?:te\s+podemos\s+llamar|podemos\s+llamarte)"
    r"\s+para\s+confirmar\s+la\s+primera\s+cita"
    r"|when\s+can\s+we\s+call\s+you\s+to\s+confirm\s+the\s+first\s+appointment"
    r")\s*\?\s*",
    re.IGNORECASE,
)
_CONSULTA_APPOINTMENT_PREFERENCE_QUESTION_RE = re.compile(
    r"(?:"
    r"¿?\s*qu[eé]\s+(?:d[ií]a|d[ií]as|franja|franjas|horario)"
    r"[^?\n]*(?:cita|sesi[oó]n)"
    r"|what\s+(?:day|days|time|time\s+window)"
    r"[^?\n]*(?:appointment|session)"
    r")",
    re.IGNORECASE,
)
_CONSULTA_INTAKE_OPTOUT_RE = re.compile(
    r"\b(?:"
    r"no\s+tengo\s+preferencia|me\s+da\s+igual|"
    r"cualquier\s+(?:d[ií]a|hora|momento)|cuando\s+sea|"
    r"prefiero\s+no|no\s+quiero\s+(?:decir|responder|seguir)|"
    r"no\s+me\s+preguntes|tengo\s+prisa|no\s+puedo\s+seguir|"
    r"d[eé]jalo|nada\s+m[aá]s|"
    r"no\s+preference|any\s+(?:day|time)|whenever|"
    r"rather\s+not|don['’]?t\s+want\s+to\s+(?:say|answer|continue)|"
    r"stop\s+asking|in\s+a\s+hurry|can['’]?t\s+continue"
    r")\b",
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


_ENGLISH_LANGUAGE_MARKERS = {
    "hi", "hello", "hey", "after", "winning", "feel", "that", "healthy",
    "why", "write", "english", "please", "thanks", "thank", "want", "would",
    "like", "need", "help", "appointment", "call", "today", "tomorrow",
    "morning", "afternoon", "online", "person", "session", "fight",
}
_SPANISH_LANGUAGE_MARKERS = {
    "hola", "buenas", "después", "ganar", "ganando", "siento", "saludable",
    "por", "qué", "escribes", "español", "gracias", "quiero", "quisiera",
    "necesito", "ayuda", "cita", "llamar", "hoy", "mañana", "tarde",
    "presencial", "sesión", "luchar", "puedo", "podemos",
}
_LANGUAGE_TOKEN_RE = re.compile(r"[a-záéíóúüñ]+", re.IGNORECASE)


def detect_english_or_spanish(text: str) -> str:
    """Return English/Spanish only when the text provides usable evidence."""
    tokens = [token.lower() for token in _LANGUAGE_TOKEN_RE.findall(text or "")]
    if not tokens:
        return ""

    english_score = sum(token in _ENGLISH_LANGUAGE_MARKERS for token in tokens)
    spanish_score = sum(token in _SPANISH_LANGUAGE_MARKERS for token in tokens)

    normalized = " ".join(tokens)
    if re.search(r"\b(?:i am|i'm|i feel|i want|i need|can you|could you|would you)\b", normalized):
        english_score += 3
    if re.search(r"\b(?:me siento|yo quiero|necesito|puedes|podrías|me gustaría)\b", normalized):
        spanish_score += 3
    if tokens[0] in {"hi", "hello", "hey"}:
        english_score += 3
    if tokens[0] in {"hola", "buenas"}:
        spanish_score += 3

    if english_score > spanish_score:
        return "English"
    if spanish_score > english_score:
        return "Spanish"
    return ""


def consulta_despertares_reply_language(
    inbound_text: str,
    history: list | None = None,
) -> str:
    """Lock Despertares to the latest identifiable customer language."""
    if not is_consulta_despertares():
        return ""

    detected = detect_english_or_spanish(inbound_text)
    if detected:
        return detected

    for message in reversed(history or []):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").lower() != "user":
            continue
        detected = detect_english_or_spanish(str(message.get("text") or ""))
        if detected:
            return detected

    # The clinic's normal operating language is Spanish when the message is
    # genuinely language-neutral (numbers, punctuation, or emoji only).
    return "Spanish"


def consulta_despertares_language_lock(
    inbound_text: str,
    history: list | None = None,
) -> str:
    language = consulta_despertares_reply_language(inbound_text, history)
    if not language:
        return ""
    return (
        f"REPLY LANGUAGE LOCK (HIGHEST PRIORITY): {language}. "
        f"Write the ENTIRE visible reply in {language}, including greeting, "
        "acknowledgement, explanation, and every question. Ignore the language "
        "of earlier assistant messages when it conflicts with this lock."
    )


def consulta_despertares_relationship_rule_block() -> str:
    if not is_consulta_despertares():
        return ""
    return CONSULTA_DESPERTARES_RELATIONSHIP_FIRST_RULE


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

    The model writes the conversational body and language-matched introduction.
    This final guard owns the exact website-lead greeting and the controlled
    callback and appointment-preference questions so prompt non-compliance
    cannot leak to a patient-facing WhatsApp reply.
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

    if not is_first_reply and _CONSULTA_GENERIC_HELP_CLOSING_RE.search(clean):
        language = consulta_despertares_reply_language(inbound_text, history)
        prospect_question = (
            CONSULTA_DESPERTARES_ENGLISH_PROSPECT_QUESTION
            if language == "English"
            else CONSULTA_DESPERTARES_SPANISH_PROSPECT_QUESTION
        )
        clean = _CONSULTA_GENERIC_HELP_CLOSING_RE.sub(
            f"\n\n{prospect_question}",
            clean,
        ).strip()

    if (
        not is_first_reply
        and _CONSULTA_SUPPORT_CONTEXT_RE.search(inbound_text or "")
        and "?" not in clean
        and "¿" not in clean
    ):
        language = consulta_despertares_reply_language(inbound_text, history)
        prospect_question = (
            CONSULTA_DESPERTARES_ENGLISH_PROSPECT_QUESTION
            if language == "English"
            else CONSULTA_DESPERTARES_SPANISH_PROSPECT_QUESTION
        )
        clean = f"{clean.rstrip()}\n\n{prospect_question}"

    if is_first_reply:
        language = consulta_despertares_reply_language(inbound_text, history)
        if _CONSULTA_WEBSITE_LEAD_RE.search(inbound_text or ""):
            greeting = CONSULTA_DESPERTARES_WEBSITE_GREETING
        elif language == "English":
            greeting = CONSULTA_DESPERTARES_ENGLISH_GREETING
        else:
            greeting = CONSULTA_DESPERTARES_OTHER_GREETING + "."

        if not clean.startswith(greeting):
            body = _strip_leading_spanish_greeting(clean)
            body = re.sub(
                r"^\s*(?:(?:hi|hello)\b\s*[!.,:]?\s*)?"
                r"(?:i['’]?m|i\s+am)\b[^.!?\n]*[.!?]?\s*",
                "",
                body,
                count=1,
                flags=re.IGNORECASE,
            ).strip()
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
    already_has_callback_preference = bool(
        str(fields.get("callback_preference") or "").strip()
    )
    already_has_appointment_preference = bool(
        str(fields.get("appointment_preference") or "").strip()
    )
    appointment_preference_already_asked = any(
        str(message.get("role") or "").lower() == "assistant"
        and _CONSULTA_APPOINTMENT_PREFERENCE_QUESTION_RE.search(
            str(message.get("text") or "")
        )
        for message in history
        if isinstance(message, dict)
    )
    customer_opted_out = bool(
        _CONSULTA_INTAKE_OPTOUT_RE.search(inbound_text or "")
    )
    reply_already_asks_a_question = "?" in clean or "¿" in clean

    if (
        booking_intent
        and _consulta_has_name_and_phone(fields)
        and not already_has_callback_preference
        and not reply_already_asks_a_question
    ):
        clean = clean.rstrip()
        language = consulta_despertares_reply_language(inbound_text, history)
        closing = (
            CONSULTA_DESPERTARES_ENGLISH_CALLBACK_CLOSING
            if language == "English"
            else CONSULTA_DESPERTARES_CALLBACK_CLOSING
        )
        clean = closing if not clean else f"{clean}\n\n{closing}"

    if (
        booking_intent
        and _consulta_has_name_and_phone(fields)
        and already_has_callback_preference
        and not already_has_appointment_preference
        and not appointment_preference_already_asked
        and not customer_opted_out
        and not reply_already_asks_a_question
    ):
        language = consulta_despertares_reply_language(inbound_text, history)
        question = (
            CONSULTA_DESPERTARES_ENGLISH_APPOINTMENT_PREFERENCE_QUESTION
            if language == "English"
            else CONSULTA_DESPERTARES_APPOINTMENT_PREFERENCE_QUESTION
        )
        clean = question if not clean else f"{clean.rstrip()}\n\n{question}"
    return clean
