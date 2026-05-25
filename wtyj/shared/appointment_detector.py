"""Deterministic appointment signal detection for live conversations.

Escalation summaries already create appointment rows when the LLM summary
classifies a thread as scheduling. This module covers the normal chat path:
when a customer and Marina explicitly settle a time, write/update the
appointment row immediately without waiting for an escalation summary.
"""
import os
import re

from shared import bm_logger
from shared import config_loader
from shared import state_registry


_TIME_RE = re.compile(
    r"\b(?:[01]?\d|2[0-3])[:.][0-5]\d\b"
    r"|\b(?:1[0-2]|0?[1-9])\s*(?:am|pm)\b"
    r"|\b(?:rond|around)\s+(?:een\s+uur\s+of\s+)?(?:[1-9]|1[0-2])\b",
    re.IGNORECASE,
)

_DATE_RE = re.compile(
    r"\b(?:today|tomorrow|tonight|friday|saturday|sunday|monday|tuesday|"
    r"wednesday|thursday|maandag|dinsdag|woensdag|donderdag|vrijdag|"
    r"zaterdag|zondag|morgen|overmorgen|vandaag|vanavond|"
    r"ma(?:n|\u00f1)an|ma(?:n|\u00f1)ana)\b",
    re.IGNORECASE,
)

_APPOINTMENT_RE = re.compile(
    r"\b(?:appointment|afspraak|consultation|consult|meeting|come by|"
    r"kom(?:en)?\s+langs|visit|bezoek)\b",
    re.IGNORECASE,
)

_CONFIRM_RE = re.compile(
    r"\b(?:is fine|fine|deal|perfect|confirmed|all noted|see you|"
    r"team will be ready|expect you|noted|klopt|is goed|tot dan|"
    r"we hebben|we have a deal|bon|te ma(?:n|\u00f1)an)\b",
    re.IGNORECASE,
)

_NEGATIVE_RE = re.compile(
    r"\b(?:cancel|cancellation|annuleer|annuleren|geen afspraak|"
    r"no appointment|not coming)\b",
    re.IGNORECASE,
)

_ROBERTO_APPOINTMENT_TENANTS = {"clinica-roberto"}

_ROBERTO_BOOKING_INTENT_RE = re.compile(
    r"\b(?:"
    r"pedir\s+cita|solicitar\s+(?:una\s+)?cita|quiero\s+(?:una\s+)?cita|"
    r"me\s+gustar(?:i|\u00ed)a\s+(?:pedir|solicitar|reservar)|"
    r"reservar\s+(?:una\s+)?cita|concertar\s+(?:una\s+)?cita|"
    r"coger\s+(?:una\s+)?cita|agendar\s+(?:una\s+)?cita|"
    r"dar\s+cita|dais\s+cita|disponibilidad|huecos?\s+libres?|"
    r"primera\s+sesi[o\u00f3]n|sesi[o\u00f3]n\s+gratis|prueba\s+de\s+una\s+sesi[o\u00f3]n\s+gratis"
    r")\b",
    re.IGNORECASE,
)

_ROBERTO_SERVICE_RE = re.compile(
    r"\b(?:"
    r"terapia|psic[o\u00f3]log[oa]|psicolog[i\u00ed]a|emdr|pareja|individual|"
    r"familiar|infantil|adolescente|online|presencial|coaching|"
    r"depresi[o\u00f3]n|ansiedad|ira|estr[e\u00e9]s|embarazo|trauma|"
    r"shock\s+post[-\s]?traum[a\u00e1]tico"
    r")\b",
    re.IGNORECASE,
)

_ROBERTO_CENTER_RE = re.compile(
    r"\b(?:retiro|atocha|legan[e\u00e9]s|carrascal|m[o\u00f3]stoles|"
    r"getafe|alcobendas|fuenlabrada|online|presencial)\b",
    re.IGNORECASE,
)

_ROBERTO_QUALIFIER_RE = re.compile(
    r"\b(?:"
    r"centro|ma\u00f1ana|tarde|horario|nombre|apellidos?|tel[e\u00e9]fono|"
    r"correo|email|motivo|consulta|informaci[o\u00f3]n|contactarme|llamar"
    r")\b",
    re.IGNORECASE,
)

_ROBERTO_PRICE_ONLY_RE = re.compile(
    r"\b(?:precio|precios|tarifa|tarifas|cu[a\u00e1]nto\s+cuesta|coste)\b",
    re.IGNORECASE,
)


def _compact(text: str, limit: int = 160) -> str:
    value = re.sub(r"\s+", " ", (text or "")).strip(" .")
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def _sentences(text: str) -> list:
    chunks = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [_compact(chunk) for chunk in chunks if chunk and chunk.strip()]


def _current_tenant_slug() -> str:
    explicit = (os.environ.get("TENANT_SLUG") or os.environ.get("TENANT_ID") or "").strip()
    if explicit:
        return explicit.lower()
    try:
        business = config_loader.get_business() or {}
        slug = str(business.get("slug") or "").strip()
        if slug:
            return slug.lower()
    except Exception:
        pass
    try:
        raw = config_loader.get_raw() or {}
        slug = str(raw.get("slug") or "").strip()
        if slug:
            return slug.lower()
    except Exception:
        pass
    return ""


def _history_text(history: list, limit: int = 8) -> str:
    return " ".join(
        (m.get("text") or m.get("content") or "")
        for m in (history or [])[-limit:]
        if isinstance(m, dict)
    )


def _first_match(pattern: re.Pattern, text: str) -> str:
    match = pattern.search(text or "")
    return match.group(0).strip() if match else ""


def _label_from_candidates(candidates: list, required_pattern: re.Pattern) -> str:
    for text in candidates:
        for sentence in _sentences(text or ""):
            if required_pattern.search(sentence):
                return sentence
    return ""


def detect_roberto_appointment_request(user_text: str, assistant_reply: str,
                                       history: list = None,
                                       tenant_slug: str = None) -> dict | None:
    """Detect Roberto/Consulta Despertares appointment leads without a fixed time.

    Roberto's current process is manual scheduling: Marina should collect
    initial patient details and hand qualified requests to the team, not
    auto-confirm a slot. This detector is tenant-gated so other tenants keep
    their own KPI/booking logic.
    """
    slug = (tenant_slug or _current_tenant_slug()).strip().lower()
    if slug not in _ROBERTO_APPOINTMENT_TENANTS:
        return None

    history_text = _history_text(history)
    latest = " ".join([user_text or "", assistant_reply or ""])
    combined = " ".join([history_text, latest])

    if _NEGATIVE_RE.search(user_text or ""):
        return None

    has_booking_intent = bool(_ROBERTO_BOOKING_INTENT_RE.search(combined))
    has_service_need = bool(_ROBERTO_SERVICE_RE.search(combined))
    has_qualifier = bool(_ROBERTO_QUALIFIER_RE.search(combined))

    if not has_booking_intent and not (has_service_need and has_qualifier):
        return None

    if (
        _ROBERTO_PRICE_ONLY_RE.search(user_text or "")
        and not _ROBERTO_BOOKING_INTENT_RE.search(combined)
    ):
        return None

    candidates = [user_text or "", assistant_reply or "", history_text]
    label = _label_from_candidates(candidates, _ROBERTO_BOOKING_INTENT_RE)
    if not label:
        label = _label_from_candidates(candidates, _ROBERTO_SERVICE_RE)
    label = label or "Needs manual scheduling"

    center = _first_match(_ROBERTO_CENTER_RE, combined)
    service = _first_match(_ROBERTO_SERVICE_RE, combined)
    title_bits = ["Consulta Despertares appointment request"]
    if service:
        title_bits.append(service)
    if center:
        title_bits.append(center)

    proposed_times = []
    time_or_date = _first_match(_TIME_RE, combined) or _first_match(_DATE_RE, combined)
    if time_or_date:
        proposed_times.append(label)

    return {
        "title": " - ".join(title_bits),
        "date_time_label": label,
        "proposed_times": proposed_times,
        "location": center,
    }


def detect_appointment_signal(user_text: str, assistant_reply: str,
                              history: list = None) -> dict | None:
    """Return appointment details when a recent exchange clearly confirms one.

    This is intentionally conservative: it requires a time plus either an
    appointment word, a date word with confirmation language, or an assistant
    confirmation such as "See you tomorrow at 11:00".
    """
    history_text = " ".join(
        (m.get("text") or m.get("content") or "")
        for m in (history or [])[-6:]
        if isinstance(m, dict)
    )
    combined = " ".join([history_text, user_text or "", assistant_reply or ""])
    if not _TIME_RE.search(combined):
        return None

    latest = " ".join([user_text or "", assistant_reply or ""])
    if _NEGATIVE_RE.search(user_text or "") and not _CONFIRM_RE.search(latest):
        return None

    has_appointment = bool(_APPOINTMENT_RE.search(combined))
    has_date = bool(_DATE_RE.search(combined))
    has_confirm = bool(_CONFIRM_RE.search(latest))
    assistant_confirms = bool(
        _TIME_RE.search(assistant_reply or "")
        and (_DATE_RE.search(assistant_reply or "")
             or _CONFIRM_RE.search(assistant_reply or ""))
    )

    if not (has_appointment or (has_date and has_confirm) or assistant_confirms):
        return None

    candidates = []
    candidates.extend(_sentences(assistant_reply or ""))
    candidates.extend(_sentences(user_text or ""))
    for msg in reversed((history or [])[-6:]):
        if isinstance(msg, dict):
            candidates.extend(_sentences(msg.get("text") or msg.get("content") or ""))

    label = ""
    for sentence in candidates:
        if _TIME_RE.search(sentence) and (
            _DATE_RE.search(sentence)
            or _APPOINTMENT_RE.search(sentence)
            or _CONFIRM_RE.search(sentence)
        ):
            label = sentence
            break

    if not label:
        match = _TIME_RE.search(combined)
        label = match.group(0) if match else ""

    return {
        "title": "Appointment request",
        "date_time_label": label,
        "proposed_times": [label] if label else [],
    }


def upsert_pending_from_exchange(conversation_id: str, channel: str,
                                 customer_name: str, user_text: str,
                                 assistant_reply: str,
                                 history: list = None) -> int:
    """Create/update a pending appointment from the latest chat exchange.

    Operator-confirmed rows are left alone so a later conversational message
    cannot silently downgrade a confirmed appointment back to pending.
    """
    if not conversation_id:
        return 0

    signal = detect_appointment_signal(user_text, assistant_reply, history)
    if not signal:
        signal = detect_roberto_appointment_request(user_text, assistant_reply, history)
    if not signal:
        return 0

    try:
        existing = state_registry.appointment_get_by_conversation(conversation_id)
        if existing and existing.get("status") == "confirmed":
            return 0
        row_id = state_registry.appointment_upsert(
            conversation_id=conversation_id,
            channel=channel,
            customer_name=customer_name or "",
            title=signal["title"],
            proposed_times=signal["proposed_times"],
            location=signal.get("location", ""),
            status="pending_team_confirmation",
            date_time_label=signal["date_time_label"],
        )
        bm_logger.log(
            "appointment_signal_detected",
            conversation_id=conversation_id,
            channel=channel,
            title=signal["title"],
            date_time_label=signal["date_time_label"],
        )
        return row_id
    except Exception as exc:
        bm_logger.log(
            "appointment_signal_failed",
            conversation_id=conversation_id,
            channel=channel,
            error=str(exc),
        )
        return 0
