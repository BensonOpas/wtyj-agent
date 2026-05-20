"""Deterministic appointment signal detection for live conversations.

Escalation summaries already create appointment rows when the LLM summary
classifies a thread as scheduling. This module covers the normal chat path:
when a customer and Marina explicitly settle a time, write/update the
appointment row immediately without waiting for an escalation summary.
"""
import re

from shared import bm_logger
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
    r"zaterdag|zondag|morgen|overmorgen|vandaag|vanavond)\b",
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
    r"we hebben|we have a deal)\b",
    re.IGNORECASE,
)

_NEGATIVE_RE = re.compile(
    r"\b(?:cancel|cancellation|annuleer|annuleren|geen afspraak|"
    r"no appointment|not coming)\b",
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
            status="pending_team_confirmation",
            date_time_label=signal["date_time_label"],
        )
        bm_logger.log(
            "appointment_signal_detected",
            conversation_id=conversation_id,
            channel=channel,
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
