"""Tenant-isolated Ali WhatsApp-to-quote workflow.

This module owns only the confirmed-summary to delivery path. Ali receives a
strict pricing request with no customer or conversation data.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx

from agents.social.ali_quote_brand_card import render_quote_brand_card
from agents.social.ali_quote_pdf import render_quote_pdf
from agents.social.ali_quote_presentation import format_rental_period
from shared import bm_logger, config_loader, state_registry

TENANT_SLUG = "ali-car-rental"
WORKFLOW_TYPE = "ali_quote"
LOCALES = {"en", "nl", "pap", "de"}
PENDING_STATUSES = ("confirmed", "pricing", "quoted", "pdf_ready", "delivering")
ALI_PHASES = {
    "COLLECTING", "DISCOVERY", "SUMMARY_PRESENTED",
    "QUOTE_PROCESSING", "QUOTED", "ESCALATED",
}
ALI_PRIMARY_INTENTS = {
    "continue_intake", "ask_question", "reject_or_hesitate",
    "request_recommendation", "repeat_summary", "confirm_summary", "other",
}
ALI_OUTBOUND_KINDS = {
    "agent_reply", "vehicle_recommendation", "summary",
    "quote_preparing", "escalation",
}
REQUIRED_RENTAL_FIELDS = {
    "rental_start", "rental_end", "pickup_location", "return_location",
    "driver_age", "conversation_language",
}
SELECTION_FIELDS = ("vehicle_id", "vehicle_class_id")
VEHICLE_STATE_FIELDS = (
    "vehicle_id", "vehicle_name", "vehicle_class_id", "vehicle_class_name",
    "vehicle_catalog_class_id", "vehicle_catalog_class_name",
    "vehicle_daily_rate_usd", "vehicle_rate_currency",
)
QUOTE_LEAD_STATUSES = {
    "active", "missing_information", "ready_to_quote",
    "needs_an_answer", "in_progress",
}
QUOTE_LEAD_REQUIRED_FIELDS = (
    "customer_name", "rental_start", "rental_end", "pickup_location",
    "return_location", "driver_age", "conversation_language",
    "vehicle_preference",
)
QUOTE_LEAD_FIELD_LABELS = {
    "customer_name": "Full name",
    "rental_start": "Pickup date",
    "rental_end": "Return date",
    "pickup_location": "Pickup location",
    "return_location": "Return location",
    "driver_age": "Driver's age",
    "conversation_language": "Conversation language",
    "vehicle_preference": "Preferred vehicle/category",
}
ALI_REQUEST_KEYS = {"rentalStart", "rentalEnd", "selection", "extraSelections", "chargeSelections"}
AFFIRMATIVE = {
    # English
    "yes", "yes it does", "yes it looks right", "yes it does look right",
    "that is right", "that s right", "that is correct", "that s correct",
    "everything looks right", "yes it looks good", "yes looks good",
    "all good", "correct", "looks good", "go ahead",
    # Dutch
    "ja", "ja dat klopt", "dat klopt", "klopt", "dat is juist", "dat is correct",
    "alles klopt", "alles ziet er goed uit", "ziet er goed uit", "helemaal goed",
    "alles goed", "akkoord", "ga verder", "ga maar door",
    # Papiamentu
    "si", "si e ta bon", "si ta bon", "si tur kos ta bon", "ta bon",
    "tur kos ta bon", "tur kos korekto", "esaki ta bon", "esaki ta korekto",
    "ta korekto", "korekto", "correcto", "por sigui", "sigui", "bai dilanti",
    # German
    "ja das stimmt", "das stimmt", "stimmt", "ja das passt", "das passt", "passt",
    "alles stimmt", "alles sieht richtig aus", "alles sieht gut aus", "das ist richtig",
    "das ist korrekt", "alles korrekt", "alles gut", "korrekt", "machen sie weiter",
    "mach weiter", "weiter", "ja bitte",
}
NEGATION_OR_QUALIFICATION = {
    "no", "not", "but", "except", "almost", "maybe", "think", "probably",
    "nee", "niet", "maar", "behalve", "bijna", "misschien", "denk",
    "pero", "ma", "kasi", "kisas",
    "nein", "kein", "nicht", "aber", "außer", "fast", "vielleicht", "glaube",
    "denke", "wahrscheinlich",
}
CORRECTION_OR_DETAIL = {
    "change", "correct", "add", "remove", "date", "dates", "pickup", "return",
    "child", "seat", "luggage", "driver", "age", "name", "location", "airport",
    "hotel", "extra",
    "wijzig", "verander", "corrigeer", "voeg", "toevoegen", "verwijder", "datum",
    "data", "ophalen", "terugbrengen", "kinderzitje", "bagage", "leeftijd", "naam",
    "locatie",
    "cambia", "kambia", "korekshon", "agrega", "kita", "fecha", "stul", "mucha",
    "maleta", "edat", "nòmber", "lokashon",
    "ändern", "korrigieren", "hinzufügen", "entfernen", "datum", "daten", "abholung",
    "rückgabe", "kindersitz", "gepäck", "alter", "name", "ort", "flughafen", "hotel",
}
_CATALOG_CACHE = {"expires_at": 0.0, "value": None}
_CATALOG_CACHE_SECONDS = 60.0
CUSTOMER_QUOTE_DELAY_SECONDS = 3 * 60
_FORBIDDEN_CONTACT_REDIRECT = re.compile(
    r"(?:https?://)?wa\.me/|mailto:|tel:|[\w.+-]+@[\w.-]+\.[a-z]{2,}",
    flags=re.IGNORECASE,
)
_INTAKE_SAFETY_FALLBACK = {
    "en": "I couldn't complete that step safely. Please try again here in a moment.",
    "nl": "Ik kon die stap niet veilig afronden. Probeer het hier over een moment opnieuw.",
    "pap": "Mi no por a kompletá e paso ei na un manera sigur. Purba atrobe aki den un momentu.",
    "de": "Ich konnte diesen Schritt nicht sicher abschließen. Bitte versuchen Sie es gleich hier erneut.",
}


class AliQuoteError(RuntimeError):
    """Safe workflow error carrying only a machine-readable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class AliTurnPlan:
    """One deterministic customer-visible action for an Ali inbound turn."""

    outbound_kind: str
    text: str
    phase: str
    primary_intent: str
    reason_code: str
    action_id: str
    draft_hash: str = ""
    summary_hash: str = ""
    summary_version: int = 0
    quote_public_id: str = ""

    def __post_init__(self) -> None:
        if self.outbound_kind not in ALI_OUTBOUND_KINDS:
            raise AliQuoteError("invalid_turn_outbound_kind")
        if self.phase not in ALI_PHASES:
            raise AliQuoteError("invalid_turn_phase")
        if self.primary_intent not in ALI_PRIMARY_INTENTS:
            raise AliQuoteError("invalid_turn_primary_intent")
        if not re.fullmatch(r"[0-9a-f]{64}", self.action_id):
            raise AliQuoteError("invalid_turn_action_id")

    def delivery_commit(self) -> dict:
        return {
            "outbound_kind": self.outbound_kind,
            "phase": self.phase,
            "primary_intent": self.primary_intent,
            "reason_code": self.reason_code,
            "action_id": self.action_id,
            "draft_hash": self.draft_hash,
            "summary_hash": self.summary_hash,
            "summary_version": self.summary_version,
            "quote_public_id": self.quote_public_id,
        }


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def seconds_until_customer_quote_delivery(
    quote: dict,
    *,
    now: datetime | None = None,
    delay_seconds: int = CUSTOMER_QUOTE_DELAY_SECONDS,
) -> float:
    """Return the remaining customer-only delay from persisted confirmation."""
    try:
        confirmed_at = datetime.fromisoformat(
            str(quote["confirmed_at"]).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise AliQuoteError("invalid_confirmation_timestamp") from exc
    current = (now or _now()).astimezone(timezone.utc)
    eligible_at = confirmed_at + timedelta(seconds=max(0, int(delay_seconds)))
    return max(0.0, (eligible_at - current).total_seconds())


def tenant_configured(raw: dict | None = None) -> bool:
    raw = raw if raw is not None else (config_loader.get_raw() or {})
    slug = str(raw.get("slug") or (raw.get("business") or {}).get("slug") or "").strip().lower()
    return slug == TENANT_SLUG and (raw.get("workflow") or {}).get("type") == WORKFLOW_TYPE


def tenant_enabled(raw: dict | None = None) -> bool:
    """Master kill switch for Ali intake and quote processing."""
    raw = raw if raw is not None else (config_loader.get_raw() or {})
    return tenant_configured(raw) and feature_switches(raw)["automation"]


def feature_switches(raw: dict | None = None) -> dict[str, bool]:
    raw = raw if raw is not None else (config_loader.get_raw() or {})
    features = raw.get("features") or {}
    return {
        "automation": bool(features.get("ali_quote_automation", False)),
        "customer_delivery": bool(features.get("ali_quote_customer_delivery", False)),
        "staff_email": bool(features.get("ali_quote_staff_email", False)),
        "operator_alerts": bool(features.get("ali_quote_operator_alerts", False)),
    }


def validate_rental_fields(rental: dict) -> dict:
    if not isinstance(rental, dict):
        raise AliQuoteError("invalid_rental_fields")
    missing = [key for key in REQUIRED_RENTAL_FIELDS if rental.get(key) in (None, "")]
    selections = [key for key in SELECTION_FIELDS if rental.get(key)]
    if missing or len(selections) != 1:
        raise AliQuoteError("incomplete_rental_fields")
    try:
        start = datetime.strptime(str(rental["rental_start"]), "%Y-%m-%d").date()
        end = datetime.strptime(str(rental["rental_end"]), "%Y-%m-%d").date()
    except ValueError as exc:
        raise AliQuoteError("invalid_rental_period") from exc
    days = max(1, (end - start).days)
    if end < start or days > 365:
        raise AliQuoteError("invalid_rental_period")
    try:
        age = int(rental["driver_age"])
    except (TypeError, ValueError) as exc:
        raise AliQuoteError("invalid_driver_age") from exc
    if age < 15 or age > 110:
        raise AliQuoteError("invalid_driver_age")
    locale = str(rental["conversation_language"]).lower()
    if locale not in LOCALES:
        raise AliQuoteError("unsupported_locale")
    normalized = dict(rental)
    normalized["driver_age"] = age
    normalized["conversation_language"] = locale
    supplements = []
    for item in normalized.get("supplements") or []:
        if not isinstance(item, dict) or not re.fullmatch(
            r"[0-9a-fA-F-]{36}", str(item.get("id") or "")
        ):
            raise AliQuoteError("invalid_supplement_selection")
        quantity = item.get("quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 20:
            raise AliQuoteError("invalid_supplement_quantity")
        supplements.append({**item, "id": str(item["id"]), "quantity": quantity})
    legacy_ids = sorted(set(normalized.get("extra_ids") or []))
    if supplements and legacy_ids:
        raise AliQuoteError("duplicate_supplement_state")
    normalized["supplements"] = sorted(supplements, key=lambda item: item["id"])
    normalized["extra_ids"] = legacy_ids
    return normalized


def normalized_summary(customer: dict, rental: dict, version: int = 1) -> tuple[dict, str]:
    if not isinstance(customer, dict) or not str(customer.get("name") or "").strip():
        raise AliQuoteError("missing_customer_name")
    if not str(customer.get("whatsapp") or "").strip():
        raise AliQuoteError("missing_conversation_whatsapp")
    rental = validate_rental_fields(rental)
    summary = {"version": version, "customer": customer, "rental": rental}
    return summary, hashlib.sha256(_json(summary).encode("utf-8")).hexdigest()


def confirmation_decision(text: str) -> tuple[bool, str]:
    """Classify a displayed-summary response without retaining its content."""
    normalized = " ".join(re.sub(r"[^\w\s]", " ", str(text or "").lower(), flags=re.UNICODE).split())
    if not normalized:
        return False, "empty"
    if "?" in str(text or ""):
        return False, "question"
    words = set(normalized.split())
    if normalized in AFFIRMATIVE:
        return True, "affirmative_allowlist"
    if words & NEGATION_OR_QUALIFICATION:
        return False, "negation_or_qualification"
    if words & CORRECTION_OR_DETAIL:
        return False, "correction_or_new_detail"
    return False, "not_allowlisted"


def is_unambiguous_confirmation(text: str) -> bool:
    return confirmation_decision(text)[0]


def _log_confirmation_decision(
    accepted: bool,
    reason_code: str,
    summary_hash: str,
    summary_version: int,
) -> None:
    """Log tenant-safe decision metadata only; never message content or PII."""
    bm_logger.log(
        "ali_quote_confirmation_decision",
        tenant_slug=TENANT_SLUG,
        outcome="accepted" if accepted else "rejected",
        reason_code=reason_code,
        summary_version=int(summary_version),
        summary_hash_prefix=str(summary_hash or "")[:12],
    )


def build_ali_request(rental: dict, required_deposit_id: str) -> dict:
    rental = validate_rental_fields(rental)
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", str(required_deposit_id or "")):
        raise AliQuoteError("missing_deposit_charge")
    selection = (
        {"vehicleId": rental["vehicle_id"]}
        if rental.get("vehicle_id") else {"classId": rental["vehicle_class_id"]}
    )
    request = {
        "rentalStart": rental["rental_start"],
        "rentalEnd": rental["rental_end"],
        "selection": selection,
        "extraSelections": [
            {"id": item["id"], "quantity": item["quantity"]}
            for item in rental.get("supplements") or []
        ] or rental.get("extra_ids") or [],
        "chargeSelections": [required_deposit_id],
    }
    if set(request) != ALI_REQUEST_KEYS:
        raise AliQuoteError("ali_request_boundary_failed")
    serialized = _json(request).lower()
    if any(term in serialized for term in ("customer", "whatsapp", "phone", "email", "location", "comment", "conversation", "name")):
        raise AliQuoteError("ali_request_contains_pii")
    return request


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(state_registry.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema() -> None:
    conn = _connection()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ali_quotes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, public_id TEXT NOT NULL UNIQUE, "
        "conversation_id TEXT NOT NULL, zernio_account_id TEXT NOT NULL, "
        "summary_hash TEXT NOT NULL, summary_version INTEGER NOT NULL, locale TEXT NOT NULL, "
        "customer_json TEXT NOT NULL, rental_json TEXT NOT NULL, ali_request_json TEXT NOT NULL, "
        "idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL, "
        "confirmed_at TEXT NOT NULL, sla_due_at TEXT NOT NULL, "
        "quote_reference TEXT, quote_snapshot_id TEXT, pricing_json TEXT, expires_at TEXT, "
        "pdf_path TEXT, pdf_sha256 TEXT, whatsapp_status TEXT NOT NULL DEFAULT 'pending', "
        "brand_image_path TEXT, brand_image_sha256 TEXT, "
        "brand_image_status TEXT NOT NULL DEFAULT 'pending', "
        "customer_delivery_superseded_at TEXT, "
        "customer_delivery_superseded_by_hash TEXT, "
        "staff_email_status TEXT NOT NULL DEFAULT 'pending', "
        "notification_status_json TEXT NOT NULL DEFAULT '{}', "
        "attempt_count INTEGER NOT NULL DEFAULT 0, last_error_code TEXT, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "UNIQUE(conversation_id, summary_hash))"
    )
    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(ali_quotes)").fetchall()
    }
    additions = {
        "brand_image_path": "TEXT",
        "brand_image_sha256": "TEXT",
        "brand_image_status": "TEXT NOT NULL DEFAULT 'pending'",
        "customer_delivery_superseded_at": "TEXT",
        "customer_delivery_superseded_by_hash": "TEXT",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE ali_quotes ADD COLUMN {name} {definition}")
    conn.commit()
    conn.close()


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def create_confirmed_quote(
    conversation_id: str,
    zernio_account_id: str,
    customer: dict,
    rental: dict,
    stored_summary_hash: str,
    confirmation_text: str,
    required_deposit_id: str,
    summary_version: int = 1,
    raw_config: dict | None = None,
) -> tuple[dict, bool]:
    if not tenant_enabled(raw_config):
        raise AliQuoteError("wrong_tenant_or_workflow")
    if not is_unambiguous_confirmation(confirmation_text):
        raise AliQuoteError("ambiguous_confirmation")
    summary, current_hash = normalized_summary(customer, rental, summary_version)
    if not hmac.compare_digest(current_hash, str(stored_summary_hash or "")):
        raise AliQuoteError("stale_summary")
    ali_request = build_ali_request(rental, required_deposit_id)
    confirmed = _now()
    values = {
        "public_id": str(uuid.uuid4()),
        "conversation_id": conversation_id,
        "zernio_account_id": zernio_account_id,
        "summary_hash": current_hash,
        "summary_version": summary_version,
        "locale": summary["rental"]["conversation_language"],
        "customer_json": _json(customer),
        "rental_json": _json(summary["rental"]),
        "ali_request_json": _json(ali_request),
        "idempotency_key": secrets.token_urlsafe(24).replace("-", "_")[:40],
        "status": "confirmed",
        "confirmed_at": _iso(confirmed),
        "sla_due_at": _iso(confirmed + timedelta(minutes=30)),
        "created_at": _iso(confirmed),
        "updated_at": _iso(confirmed),
    }
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM ali_quotes WHERE conversation_id = ? AND summary_hash = ?",
            (conversation_id, current_hash),
        ).fetchone()
        if existing:
            conn.commit()
            return _row(existing), False
        columns = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        conn.execute(f"INSERT INTO ali_quotes ({columns}) VALUES ({placeholders})", tuple(values.values()))
        created = conn.execute("SELECT * FROM ali_quotes WHERE public_id = ?", (values["public_id"],)).fetchone()
        conn.commit()
        return _row(created), True
    finally:
        conn.close()


def get_quote(public_id: str) -> dict | None:
    ensure_schema()
    conn = _connection()
    row = conn.execute("SELECT * FROM ali_quotes WHERE public_id = ?", (public_id,)).fetchone()
    conn.close()
    return _row(row)


def update_quote(public_id: str, **changes) -> dict:
    allowed = {
        "status", "quote_reference", "quote_snapshot_id", "pricing_json", "expires_at",
        "pdf_path", "pdf_sha256", "whatsapp_status", "staff_email_status",
        "brand_image_path", "brand_image_sha256", "brand_image_status",
        "customer_delivery_superseded_at", "customer_delivery_superseded_by_hash",
        "notification_status_json", "attempt_count", "last_error_code",
    }
    if not changes or set(changes) - allowed:
        raise AliQuoteError("invalid_quote_update")
    changes["updated_at"] = _iso(_now())
    conn = _connection()
    assignments = ", ".join(f"{key} = ?" for key in changes)
    conn.execute(f"UPDATE ali_quotes SET {assignments} WHERE public_id = ?", (*changes.values(), public_id))
    conn.commit()
    row = conn.execute("SELECT * FROM ali_quotes WHERE public_id = ?", (public_id,)).fetchone()
    conn.close()
    if not row:
        raise AliQuoteError("quote_not_found")
    return _row(row)


def resumable_quotes() -> list[dict]:
    ensure_schema()
    conn = _connection()
    placeholders = ",".join("?" for _ in PENDING_STATUSES)
    rows = conn.execute(f"SELECT * FROM ali_quotes WHERE status IN ({placeholders}) ORDER BY id", PENDING_STATUSES).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def supersede_pending_customer_delivery(
    conversation_id: str,
    replacement_draft_hash: str,
) -> str | None:
    """Supersede only the customer assets for the newest undelivered quote."""
    if not re.fullmatch(r"[0-9a-f]{64}", str(replacement_draft_hash or "")):
        return None
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM ali_quotes WHERE conversation_id = ? "
            "AND status IN ('confirmed','pricing','quoted','pdf_ready','delivering') "
            "AND whatsapp_status != 'accepted' "
            "AND customer_delivery_superseded_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        if not row:
            conn.commit()
            return None
        timestamp = _iso(_now())
        conn.execute(
            "UPDATE ali_quotes SET customer_delivery_superseded_at = ?, "
            "customer_delivery_superseded_by_hash = ?, updated_at = ? "
            "WHERE public_id = ? AND customer_delivery_superseded_at IS NULL",
            (timestamp, replacement_draft_hash, timestamp, row["public_id"]),
        )
        conn.commit()
        return str(row["public_id"])
    finally:
        conn.close()


def customer_delivery_is_superseded(quote: dict | None) -> bool:
    return bool((quote or {}).get("customer_delivery_superseded_at"))


def commit_ali_turn_delivery(
    conversation_id: str,
    commit: dict,
    assistant_text: str,
    inbound_message_ids: list[str] | None = None,
    *,
    channel: str = "whatsapp",
    recommendation_state_hash: str = "",
    recommendation_delivery: str = "",
    recommendation_vehicle_ids: list[str] | None = None,
) -> bool:
    """Atomically commit provider-confirmed Ali state, timeline, and inbound rows.

    Returns ``True`` only when this action id is committed for the first time.
    No customer content is copied into flags or logs.
    """
    kind = str((commit or {}).get("outbound_kind") or "")
    phase = str((commit or {}).get("phase") or "")
    intent = str((commit or {}).get("primary_intent") or "")
    action_id = str((commit or {}).get("action_id") or "")
    draft_hash = str((commit or {}).get("draft_hash") or "")
    summary_hash = str((commit or {}).get("summary_hash") or "")
    summary_version = int((commit or {}).get("summary_version") or 0)
    quote_public_id = str((commit or {}).get("quote_public_id") or "")
    if (
        kind not in ALI_OUTBOUND_KINDS
        or phase not in ALI_PHASES
        or intent not in ALI_PRIMARY_INTENTS
        or not re.fullmatch(r"[0-9a-f]{64}", action_id)
        or (draft_hash and not re.fullmatch(r"[0-9a-f]{64}", draft_hash))
        or (summary_hash and not re.fullmatch(r"[0-9a-f]{64}", summary_hash))
    ):
        raise AliQuoteError("invalid_turn_delivery_commit")
    if kind == "summary" and (not summary_hash or summary_version < 1):
        raise AliQuoteError("invalid_summary_delivery_commit")

    conn = state_registry._get_conn()
    now = _iso(_now())
    ids = list(dict.fromkeys(
        str(value) for value in (inbound_message_ids or []) if str(value)
    ))
    recommendation_ids = []
    for value in recommendation_vehicle_ids or []:
        vehicle_id = str(value or "").strip()
        if (
            vehicle_id
            and len(vehicle_id) <= 160
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", vehicle_id)
            and vehicle_id not in recommendation_ids
        ):
            recommendation_ids.append(vehicle_id)
    recommendation_ids = recommendation_ids[:5]
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT flags_json FROM whatsapp_booking_state WHERE phone = ?",
            (conversation_id,),
        ).fetchone()
        if not row:
            conn.rollback()
            raise AliQuoteError("turn_state_not_found")
        flags = json.loads(row[0] or "{}")
        if flags.get("ali_last_delivery_action_id") == action_id:
            for message_id in ids:
                conn.execute(
                    "UPDATE inbound_processing_events SET status = 'replied', "
                    "reason = 'provider_send_ok', updated_at = ? WHERE message_id = ?",
                    (now, message_id),
                )
            conn.commit()
            return False

        flags["ali_phase"] = phase
        flags["ali_last_delivered_kind"] = kind
        flags["ali_last_delivery_action_id"] = action_id
        if draft_hash:
            flags["ali_draft_hash"] = draft_hash
        if quote_public_id:
            flags["ali_active_quote_public_id"] = quote_public_id
            flags["ali_quote_public_id"] = quote_public_id
        if kind == "summary":
            flags["ali_presented_summary_hash"] = summary_hash
            flags["ali_summary_hash"] = summary_hash
            flags["ali_summary_version"] = summary_version
            flags["awaiting_quote_confirmation"] = True
        elif not (
            kind == "agent_reply"
            and phase == "SUMMARY_PRESENTED"
            and re.fullmatch(
                r"[0-9a-f]{64}",
                str(flags.get("ali_presented_summary_hash") or ""),
            )
            and flags.get("awaiting_quote_confirmation") is True
        ):
            flags.pop("ali_presented_summary_hash", None)
            flags.pop("awaiting_quote_confirmation", None)
            if kind not in {"quote_preparing"}:
                flags.pop("ali_summary_hash", None)
                flags.pop("ali_summary_version", None)

        if kind == "vehicle_recommendation" and re.fullmatch(
            r"[0-9a-f]{64}", recommendation_state_hash
        ) and recommendation_delivery in {
            "image", "carousel", "fallback", "carousel_picker",
            "carousel_picker_fallback", "picker", "picker_fallback",
        }:
            existing = flags.get("ali_vehicle_recommendation_deliveries") or []
            normalized = [
                item for item in existing
                if isinstance(item, dict)
                and re.fullmatch(r"[0-9a-f]{64}", str(item.get("hash") or ""))
            ]
            if not any(item["hash"] == recommendation_state_hash for item in normalized):
                normalized.append({
                    "hash": recommendation_state_hash,
                    "delivery": recommendation_delivery,
                    "action_id": action_id,
                })
            flags["ali_vehicle_recommendation_deliveries"] = normalized[-20:]
            if recommendation_ids:
                flags["ali_last_recommendation_ids"] = recommendation_ids
                shown = [
                    str(value).strip()
                    for value in flags.get("ali_shown_vehicle_ids") or []
                    if isinstance(value, str) and str(value).strip()
                ]
                for vehicle_id in recommendation_ids:
                    if vehicle_id not in shown:
                        shown.append(vehicle_id)
                flags["ali_shown_vehicle_ids"] = shown[-40:]

        conn.execute(
            "UPDATE whatsapp_booking_state SET flags_json = ?, last_activity = ? "
            "WHERE phone = ?",
            (json.dumps(flags, ensure_ascii=False), now, conversation_id),
        )
        conn.execute(
            "INSERT INTO whatsapp_threads "
            "(phone, role, text, created_at, channel, sender_name) "
            "VALUES (?, 'assistant', ?, ?, ?, '')",
            (conversation_id, str(assistant_text or ""), now, channel),
        )
        for message_id in ids:
            conn.execute(
                "UPDATE inbound_processing_events SET status = 'replied', "
                "reason = 'provider_send_ok', last_error = '', updated_at = ? "
                "WHERE message_id = ?",
                (now, message_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    bm_logger.log(
        "ali_turn_delivery_committed",
        phase=phase,
        primary_intent=intent,
        route=kind,
        reason_code=str((commit or {}).get("reason_code") or "")[:60],
        draft_hash_prefix=draft_hash[:12],
        action_id_prefix=action_id[:12],
    )
    return True


def _set_quote_conversation_phase(quote: dict, phase: str) -> None:
    """Advance only the still-active quote pointer; never reopen an old quote."""
    if phase not in {"QUOTED", "ESCALATED"}:
        return
    conn = state_registry._get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT flags_json FROM whatsapp_booking_state WHERE phone = ?",
            (quote["conversation_id"],),
        ).fetchone()
        if not row:
            conn.commit()
            return
        flags = json.loads(row[0] or "{}")
        active = flags.get("ali_active_quote_public_id") or flags.get("ali_quote_public_id")
        if active == quote["public_id"]:
            flags["ali_phase"] = phase
            conn.execute(
                "UPDATE whatsapp_booking_state SET flags_json = ? WHERE phone = ?",
                (json.dumps(flags, ensure_ascii=False), quote["conversation_id"]),
            )
        conn.commit()
    finally:
        conn.close()


def _quote_lead_missing_fields(fields: dict) -> list[str]:
    missing = [
        key for key in QUOTE_LEAD_REQUIRED_FIELDS
        if key != "vehicle_preference" and fields.get(key) in (None, "")
    ]
    if len([key for key in SELECTION_FIELDS if fields.get(key)]) != 1:
        missing.append("vehicle_preference")
    return missing


def _masked_whatsapp_identifier(value: object) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if 9 <= len(digits) <= 15:
        return f"WhatsApp ••••{digits[-4:]}"
    return "WhatsApp conversation"


def _quote_lead_status(
    fields: dict,
    flags: dict,
    quote: dict | None,
    has_active_escalation: bool,
) -> str:
    if has_active_escalation:
        return "needs_an_answer"
    if _quote_lead_missing_fields(fields):
        return "missing_information"
    if quote and quote.get("status") in PENDING_STATUSES:
        return "in_progress"
    if flags.get("ali_quote_public_id"):
        if not quote or quote.get("whatsapp_status") != "accepted":
            return "ready_to_quote"
    return "active"


def list_quote_leads(status: str | None = None, limit: int = 200) -> list[dict]:
    """Project Ali's open rental conversations into one read-only lead queue.

    ``active`` is an umbrella filter over all non-closed leads. Other filters
    select the row's canonical projected status. The tenant database itself is
    the isolation boundary; no customer state is copied into another table.
    """
    if status is not None and status not in QUOTE_LEAD_STATUSES:
        raise ValueError("Invalid quote lead status")
    registry_connection = state_registry._get_conn()
    registry_connection.close()
    ensure_schema()
    conn = _connection()
    try:
        state_rows = conn.execute(
            "SELECT w.phone, w.fields_json, w.flags_json, w.last_activity, "
            "w.created_at, COALESCE(cs.status, 'pending'), "
            "COALESCE(cs.deleted, 0), COALESCE(cs.blocked, 0), "
            "(SELECT sender_name FROM whatsapp_threads t "
            " WHERE t.phone = w.phone AND t.role = 'user' AND t.sender_name != '' "
            " ORDER BY t.created_at DESC LIMIT 1), "
            "(SELECT channel FROM whatsapp_threads t WHERE t.phone = w.phone "
            " ORDER BY t.created_at DESC LIMIT 1), "
            "(SELECT COUNT(*) FROM whatsapp_threads incoming "
            " WHERE incoming.phone = w.phone AND incoming.role = 'user' "
            " AND incoming.created_at > COALESCE(("
            "   SELECT MAX(outgoing.created_at) FROM whatsapp_threads outgoing "
            "   WHERE outgoing.phone = w.phone "
            "   AND outgoing.role IN ('assistant', 'operator')"
            " ), '')) "
            "FROM whatsapp_booking_state w "
            "LEFT JOIN conversation_status cs ON cs.conversation_id = w.phone "
            "WHERE COALESCE(cs.deleted, 0) = 0 "
            "AND COALESCE(cs.blocked, 0) = 0 "
            "AND COALESCE(cs.status, 'pending') NOT IN ('resolved', 'closed', 'archived') "
            "ORDER BY w.last_activity DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        quote_rows = conn.execute(
            "SELECT q.* FROM ali_quotes q INNER JOIN ("
            " SELECT conversation_id, MAX(id) AS latest_id FROM ali_quotes "
            " GROUP BY conversation_id"
            ") latest ON latest.latest_id = q.id"
        ).fetchall()
        latest_quotes = {
            str(row["conversation_id"]): dict(row) for row in quote_rows
        }
        escalation_ids = {
            str(row[0]) for row in conn.execute(
                "SELECT DISTINCT customer_id FROM pending_notifications "
                "WHERE notification_type = 'escalation' "
                "AND status != 'resolved'"
            ).fetchall() if row[0]
        }
    finally:
        conn.close()

    leads = []
    for row in state_rows:
        conversation_id = str(row[0])
        try:
            fields = json.loads(row[1] or "{}")
            flags = json.loads(row[2] or "{}")
        except (TypeError, ValueError):
            fields, flags = {}, {}
        quote = latest_quotes.get(conversation_id)
        known_customer_name = str(
            fields.get("customer_name")
            or fields.get("name")
            or " ".join(
                str(fields.get(key) or "").strip()
                for key in ("first_name", "surnames")
            ).strip()
            or row[8]
            or ""
        ).strip()
        projected_fields = dict(fields)
        if known_customer_name:
            projected_fields["customer_name"] = known_customer_name
        projected_status = _quote_lead_status(
            projected_fields, flags, quote, conversation_id in escalation_ids,
        )
        if status not in (None, "active") and projected_status != status:
            continue
        customer_name = known_customer_name or "WhatsApp customer"
        selection = str(
            fields.get("vehicle_name") or fields.get("vehicle_class_name") or ""
        ).strip()
        locale = str(fields.get("conversation_language") or "en").lower()
        if locale not in LOCALES:
            locale = "en"
        rental_start = str(fields.get("rental_start") or "").strip()
        rental_end = str(fields.get("rental_end") or "").strip()
        rental_period = ""
        if rental_start and rental_end:
            rental_period = format_rental_period(rental_start, rental_end, locale)
        missing = _quote_lead_missing_fields(projected_fields)
        next_action = {
            "needs_an_answer": "Review and answer the customer conversation.",
            "missing_information": (
                f"Collect {QUOTE_LEAD_FIELD_LABELS[missing[0]].lower()}."
                if missing else "Collect the remaining rental details."
            ),
            "in_progress": "Official quote creation or delivery is in progress.",
            "ready_to_quote": "Resume official quote delivery.",
            "active": (
                "Waiting for customer confirmation of the rental summary."
                if flags.get("awaiting_quote_confirmation")
                else "Review the open rental conversation."
            ),
        }[projected_status]
        whatsapp_status = str((quote or {}).get("whatsapp_status") or "")
        delivery_state = (
            "delivered" if whatsapp_status == "accepted"
            else "failed" if whatsapp_status == "failed"
            else "pending" if quote else "not_started"
        )
        leads.append({
            "id": conversation_id,
            "conversation_id": conversation_id,
            "channel": str(row[9] or "whatsapp"),
            "customer_name": customer_name,
            "first_name": customer_name,
            "surnames": "",
            "phone_raw": _masked_whatsapp_identifier(conversation_id),
            "phone_normalized": "",
            "vehicle_preference": selection,
            "rental_period": rental_period,
            "pickup_datetime": rental_start,
            "return_datetime": rental_end,
            "pickup_location": str(fields.get("pickup_location") or ""),
            "return_location": str(fields.get("return_location") or ""),
            "driver_age": fields.get("driver_age"),
            "passenger_count": fields.get("passenger_count"),
            "flight_number": str(fields.get("flight_number") or ""),
            "luggage": str(fields.get("luggage_count") or fields.get("luggage") or ""),
            "child_seat": ", ".join(
                f"{item.get('name')} × {item.get('quantity')}"
                for item in fields.get("supplements") or []
                if isinstance(item, dict) and item.get("name")
            ),
            "notes": str(fields.get("comments") or ""),
            "workflow_type": WORKFLOW_TYPE,
            "required_fields": list(QUOTE_LEAD_REQUIRED_FIELDS),
            "missing_fields": missing,
            "field_labels": dict(QUOTE_LEAD_FIELD_LABELS),
            "complete": not missing,
            "status": projected_status,
            "next_action": next_action,
            "last_activity": str(row[3] or ""),
            "created_at": str(row[4] or row[3] or ""),
            "updated_at": str(row[3] or ""),
            "unread_count": int(row[10] or 0),
            "quote_reference": (quote or {}).get("quote_reference"),
            "quote_status": (quote or {}).get("status"),
            "quote_delivery_state": delivery_state,
            "whatsapp_status": whatsapp_status or None,
            "staff_email_status": (quote or {}).get("staff_email_status"),
            "visit_reason": "",
            "handoff_reason": next_action,
            "callback_preference": "",
        })
    return leads


class AliQuoteClient:
    def __init__(self, base_url: str, service_token: str, client: httpx.Client | None = None):
        if not base_url.startswith("https://") or not service_token:
            raise AliQuoteError("ali_client_unconfigured")
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token
        self.client = client or httpx.Client(timeout=12.0)

    def get_catalog(self) -> dict:
        for attempt in range(2):
            try:
                response = self.client.get(
                    f"{self.base_url}/api/v1/catalog",
                    headers={
                        "Authorization": f"Bearer {self.service_token}",
                        "Accept": "application/json",
                    },
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == 0:
                    continue
                raise AliQuoteError("ali_catalog_temporary_failure") from exc
            if response.status_code == 200:
                payload = response.json()
                required = {
                    "catalogVersion", "currency", "availabilityMode",
                    "vehicleClasses", "vehicles", "extras",
                }
                if (
                    not required.issubset(payload)
                    or payload.get("currency") != "USD"
                    or payload.get("availabilityMode") != "request_only"
                    or not isinstance(payload.get("vehicleClasses"), list)
                    or not isinstance(payload.get("vehicles"), list)
                    or not isinstance(payload.get("extras"), list)
                ):
                    raise AliQuoteError("ali_catalog_invalid")
                for item in [*payload["vehicleClasses"], *payload["vehicles"]]:
                    if not isinstance(item, dict) or not str(item.get("id") or "").strip() or not str(item.get("name") or "").strip():
                        raise AliQuoteError("ali_catalog_invalid")
                return payload
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 0:
                    continue
                raise AliQuoteError("ali_catalog_temporary_failure")
            raise AliQuoteError(f"ali_catalog_http_{response.status_code}")
        raise AliQuoteError("ali_catalog_temporary_failure")

    def create_quote(self, request: dict, idempotency_key: str) -> dict:
        if set(request) != ALI_REQUEST_KEYS:
            raise AliQuoteError("ali_request_boundary_failed")
        for attempt in range(2):
            try:
                response = self.client.post(
                    f"{self.base_url}/api/v1/quotes",
                    headers={"Authorization": f"Bearer {self.service_token}", "Idempotency-Key": idempotency_key},
                    json=request,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == 0:
                    continue
                raise AliQuoteError("ali_temporary_failure") from exc
            if response.status_code in (200, 201):
                payload = response.json()
                required = {"quoteSnapshotId", "quoteReference", "catalogVersion", "availabilityMode", "currency", "rentalDays", "items", "rentalTotal", "refundableSecurityDeposit", "reservationDeposit", "createdAt", "expiresAt"}
                if not required.issubset(payload) or payload.get("availabilityMode") != "request_only" or payload.get("currency") != "USD":
                    raise AliQuoteError("ali_response_invalid")
                created = datetime.fromisoformat(payload["createdAt"].replace("Z", "+00:00"))
                expires = datetime.fromisoformat(payload["expiresAt"].replace("Z", "+00:00"))
                if expires - created != timedelta(hours=72):
                    raise AliQuoteError("ali_expiry_invalid")
                return payload
            if response.status_code in (429,) or response.status_code >= 500:
                if attempt == 0:
                    continue
                raise AliQuoteError("ali_temporary_failure")
            raise AliQuoteError(f"ali_http_{response.status_code}")
        raise AliQuoteError("ali_temporary_failure")


def get_intake_catalog(
    client: AliQuoteClient | None = None,
    *,
    force_refresh: bool = False,
) -> dict:
    """Return the current published Ali catalog without customer data."""
    now = time.monotonic()
    cached = _CATALOG_CACHE.get("value")
    if not force_refresh and cached is not None and now < float(_CATALOG_CACHE["expires_at"]):
        return cached
    active_client = client or AliQuoteClient(
        os.environ.get("ALI_QUOTE_API_BASE_URL", "https://alicarrental.com"),
        os.environ.get("ALI_QUOTE_API_TOKEN", ""),
    )
    catalog = active_client.get_catalog()
    _CATALOG_CACHE["value"] = catalog
    _CATALOG_CACHE["expires_at"] = now + _CATALOG_CACHE_SECONDS
    return catalog


def catalog_prompt_context(catalog: dict) -> dict:
    """Expose only current public names and fixed rates to the intake prompt."""
    rates_by_class: dict[str, set[str]] = {}
    vehicles = []
    for vehicle in catalog.get("vehicles") or []:
        class_id = str(vehicle.get("classId") or "")
        amount = str((vehicle.get("dailyRate") or {}).get("amount") or "")
        if class_id and amount:
            rates_by_class.setdefault(class_id, set()).add(amount)
        vehicles.append({
            "name": str(vehicle.get("name") or ""),
            "category": next((
                str(item.get("name") or "")
                for item in catalog.get("vehicleClasses") or []
                if item.get("id") == class_id
            ), ""),
            "daily_usd": amount or None,
            "seats": vehicle.get("seats"),
            "transmission": str(vehicle.get("transmission") or "") or None,
            "features": [
                str(feature)
                for feature in vehicle.get("features") or []
                if str(feature).strip()
            ],
        })
    categories = []
    for item in catalog.get("vehicleClasses") or []:
        rates = sorted(rates_by_class.get(str(item.get("id") or ""), set()))
        categories.append({
            "name": str(item.get("name") or ""),
            "description": str(item.get("description") or "") or None,
            "daily_usd": rates[0] if len(rates) == 1 else None,
        })
    return {
        "catalog_version": catalog.get("catalogVersion"),
        "availability_mode": "request_only",
        "currency": "USD",
        "categories": categories,
        "vehicles": vehicles,
        "supplements": [{
            "name": str(item.get("name") or ""),
            "names": {
                locale: str(name)
                for locale, name in (item.get("names") or {}).items()
                if locale in LOCALES and str(name).strip()
            },
            "price_usd": str((item.get("price") or {}).get("amount") or "") or None,
            "billing_basis": str(item.get("billingBasis") or ""),
        } for item in catalog.get("extras") or [] if isinstance(item, dict)],
    }


def sanitize_intake_reply(reply: str, locale: str | None = None) -> str:
    """Fail closed if Marina tries to redirect an Ali WhatsApp customer."""
    text = str(reply or "").strip()
    if not _FORBIDDEN_CONTACT_REDIRECT.search(text):
        return text
    selected_locale = str(locale or "en").lower()
    return _INTAKE_SAFETY_FALLBACK.get(selected_locale, _INTAKE_SAFETY_FALLBACK["en"])


def _normalize_catalog_label(value: object) -> str:
    normalized = str(value or "").casefold()
    normalized = re.sub(r"\bor\s+similar\b", " ", normalized)
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    ignored = {"car", "cars", "vehicle", "vehicles", "category", "class", "rental"}
    return " ".join(part for part in normalized.split() if part not in ignored)


def resolve_catalog_selection(fields: dict, catalog: dict) -> dict:
    """Map a customer-facing selection to one current server-owned ID."""
    resolved = dict(fields or {})
    classes = [
        item for item in catalog.get("vehicleClasses") or []
        if isinstance(item, dict) and item.get("active", True) is not False
    ]
    vehicles = [
        item for item in catalog.get("vehicles") or []
        if isinstance(item, dict) and item.get("active", True) is not False
    ]
    class_by_id = {str(item.get("id")): item for item in classes if item.get("id")}
    vehicle_by_id = {str(item.get("id")): item for item in vehicles if item.get("id")}

    def unique_name_match(items: list[dict], value: object) -> dict | None:
        target = _normalize_catalog_label(value)
        if not target:
            return None
        matches = [item for item in items if _normalize_catalog_label(item.get("name")) == target]
        return matches[0] if len(matches) == 1 else None

    vehicle_from_id = vehicle_by_id.get(str(resolved.get("vehicle_id") or ""))
    class_from_id = class_by_id.get(str(resolved.get("vehicle_class_id") or ""))
    vehicle = vehicle_from_id
    vehicle = vehicle or unique_name_match(vehicles, resolved.get("vehicle_name"))
    vehicle_class = class_from_id
    vehicle_class = vehicle_class or unique_name_match(classes, resolved.get("vehicle_class_name"))

    # A persisted selection carries its server-owned ID. The one-call intake
    # contract never lets Claude emit IDs, so a matching name of the opposing
    # kind is necessarily newer than that persisted selection.
    if vehicle_from_id and vehicle_class and not class_from_id:
        vehicle = None
    elif class_from_id and vehicle and not vehicle_from_id:
        vehicle_class = None

    for key in VEHICLE_STATE_FIELDS:
        resolved.pop(key, None)
    if vehicle:
        resolved["vehicle_id"] = str(vehicle["id"])
        resolved["vehicle_name"] = str(vehicle["name"])
        catalog_class = class_by_id.get(str(vehicle.get("classId") or ""))
        rate = vehicle.get("dailyRate") or {}
        rate_amount = str(rate.get("amount") or "")
        rate_currency = str(rate.get("currency") or "").upper()
        if catalog_class:
            resolved["vehicle_catalog_class_id"] = str(catalog_class["id"])
            resolved["vehicle_catalog_class_name"] = str(catalog_class["name"])
        if re.fullmatch(r"(?:0|[1-9]\d*)\.\d{2}", rate_amount) and rate_currency == "USD":
            resolved["vehicle_daily_rate_usd"] = rate_amount
            resolved["vehicle_rate_currency"] = rate_currency
    elif vehicle_class:
        resolved["vehicle_class_id"] = str(vehicle_class["id"])
        resolved["vehicle_class_name"] = str(vehicle_class["name"])
    return resolved


QUOTE_CHANGE_FIELDS = frozenset({
    "customer_name", "rental_start", "rental_end", "pickup_location",
    "return_location", "vehicle_selection", "driver_age", "passenger_count",
    "luggage_count", "supplements", "comments",
})


def apply_latest_rental_change(
    stored_fields: dict,
    extracted_fields: dict,
    action: object,
    catalog: dict,
) -> tuple[dict, str, tuple[str, ...]]:
    """Apply only newest explicit quote changes using catalog-owned truth.

    The outcome is one of ``changed``, ``unchanged``, ``clarify`` or
    ``not_applicable``. No customer values are returned for logging.
    """
    current = dict(stored_fields or {})
    if not isinstance(action, dict):
        return current, "not_applicable", ()
    mode = action.get("mode")
    requested = action.get("changed_fields")
    if mode == "clarify":
        return current, "clarify", ()
    if mode != "apply" or not isinstance(requested, list):
        return current, "clarify", ()
    changed_fields = tuple(dict.fromkeys(str(item) for item in requested))
    if not changed_fields or any(item not in QUOTE_CHANGE_FIELDS for item in changed_fields):
        return current, "clarify", ()
    extracted = extracted_fields if isinstance(extracted_fields, dict) else {}
    candidate = dict(current)

    for key in changed_fields:
        if key == "vehicle_selection":
            kind = action.get("vehicle_selection_kind")
            selected_key = {
                "vehicle": "vehicle_name",
                "category": "vehicle_class_name",
            }.get(kind)
            if not selected_key or not str(extracted.get(selected_key) or "").strip():
                return current, "clarify", ()
            selection = {selected_key: extracted[selected_key]}
            resolved = resolve_catalog_selection(selection, catalog)
            resolved_selection = {
                name: resolved[name]
                for name in VEHICLE_STATE_FIELDS
                if name in resolved
            }
            if not (
                {"vehicle_id", "vehicle_name"} <= resolved_selection.keys()
                or {"vehicle_class_id", "vehicle_class_name"} <= resolved_selection.keys()
            ):
                return current, "clarify", ()
            for name in VEHICLE_STATE_FIELDS:
                candidate.pop(name, None)
            candidate.update(resolved_selection)
            continue
        if key == "supplements":
            if "supplements" not in extracted or not isinstance(extracted["supplements"], list):
                return current, "clarify", ()
            try:
                resolved = resolve_catalog_supplements(
                    {**candidate, "supplements": extracted["supplements"]}, catalog
                )
            except AliQuoteError:
                return current, "clarify", ()
            candidate["supplements"] = resolved.get("supplements") or []
            candidate.pop("extra_ids", None)
            continue
        if key == "comments":
            if "comments" in extracted:
                value = extracted.get("comments")
            elif "special_requests" in extracted:
                value = extracted.get("special_requests")
            else:
                return current, "clarify", ()
            if str(value or "").strip():
                candidate["comments"] = str(value).strip()
            else:
                candidate.pop("comments", None)
            candidate.pop("special_requests", None)
            continue
        if key not in extracted or extracted.get(key) in (None, ""):
            return current, "clarify", ()
        candidate[key] = extracted[key]

    outcome = "changed" if candidate != current else "unchanged"
    return candidate, outcome, tuple(sorted(changed_fields))


def apply_recommendation_selection_context(
    stored_fields: dict,
    recommendation_action: object,
    catalog: dict,
) -> tuple[dict, str, tuple[str, ...]]:
    """Use a validated recommendation as the selection fallback.

    Marina should emit ``ali_rental_change`` for a combined selection change
    and media request. If it omits only that independent patch, the catalog-
    validated recommendation still proves the safe selection context without
    parsing customer language in Python: one exact option selects that vehicle;
    curated options from one class select the class; mixed options reopen
    discovery and clear the stale selection.
    """
    current = dict(stored_fields or {})
    if not isinstance(recommendation_action, dict):
        return current, "not_applicable", ()
    mode = recommendation_action.get("mode")
    names = recommendation_action.get("vehicle_names")
    if mode not in {"specific", "curated"} or not isinstance(names, list):
        return current, "clarify", ()
    requested_names = [str(name or "").strip() for name in names]
    if not requested_names or any(not name for name in requested_names):
        return current, "clarify", ()
    vehicles = {
        str(item.get("name") or "").strip().casefold(): item
        for item in catalog.get("vehicles") or []
        if isinstance(item, dict) and item.get("id") and item.get("name")
    }
    options = [vehicles.get(name.casefold()) for name in requested_names]
    if any(option is None for option in options):
        return current, "clarify", ()

    if mode == "specific":
        if len(options) != 1:
            return current, "clarify", ()
        return apply_latest_rental_change(
            current,
            {"vehicle_name": options[0]["name"]},
            {
                "mode": "apply",
                "changed_fields": ["vehicle_selection"],
                "vehicle_selection_kind": "vehicle",
            },
            catalog,
        )

    class_ids = {str(option.get("classId") or "") for option in options}
    class_ids.discard("")
    if len(class_ids) == 1:
        class_id = next(iter(class_ids))
        vehicle_class = next(
            (
                item for item in catalog.get("vehicleClasses") or []
                if isinstance(item, dict) and str(item.get("id") or "") == class_id
            ),
            None,
        )
        if vehicle_class and vehicle_class.get("name"):
            return apply_latest_rental_change(
                current,
                {"vehicle_class_name": vehicle_class["name"]},
                {
                    "mode": "apply",
                    "changed_fields": ["vehicle_selection"],
                    "vehicle_selection_kind": "category",
                },
                catalog,
            )

    candidate = dict(current)
    for key in VEHICLE_STATE_FIELDS:
        candidate.pop(key, None)
    return (
        candidate,
        "changed" if candidate != current else "unchanged",
        ("vehicle_selection",) if candidate != current else (),
    )


def log_rental_change_decision(outcome: str, changed_fields: tuple[str, ...]) -> None:
    """Record only fixed metadata; never message text, values, or PII."""
    bm_logger.log(
        "ali_rental_change_decision",
        tenant_slug=TENANT_SLUG,
        outcome=str(outcome),
        changed_fields=list(changed_fields),
    )


def invalidate_active_quote_summary(flags: dict) -> None:
    """Suspend the delivered summary without deleting immutable quote linkage."""
    for key in (
        "ali_summary_hash", "ali_summary_version",
        "ali_presented_summary_hash", "awaiting_quote_confirmation",
    ):
        flags.pop(key, None)
    flags["ali_phase"] = "DISCOVERY"


def _money_cents(amount: object) -> int:
    text = str(amount or "")
    if not re.fullmatch(r"(?:0|[1-9]\d*)\.\d{2}", text):
        raise AliQuoteError("invalid_supplement_price")
    whole, fraction = text.split(".")
    cents = int(whole) * 100 + int(fraction)
    if cents < 0:
        raise AliQuoteError("invalid_supplement_price")
    return cents


def _money_text(cents: int) -> str:
    if not isinstance(cents, int) or cents < 0:
        raise AliQuoteError("invalid_supplement_price")
    return f"{cents // 100}.{cents % 100:02d}"


def resolve_catalog_supplements(fields: dict, catalog: dict) -> dict:
    """Resolve model-visible supplement names to current Ali-owned IDs and prices."""
    resolved = dict(fields or {})
    extras = [item for item in catalog.get("extras") or [] if isinstance(item, dict)]
    extra_by_id = {str(item.get("id")): item for item in extras if item.get("id")}

    def labels(item: dict) -> set[str]:
        values = [item.get("name"), *(item.get("names") or {}).values()]
        return {_normalize_catalog_label(value) for value in values if str(value or "").strip()}

    canonical = []
    seen = set()
    for requested in resolved.get("supplements") or []:
        if not isinstance(requested, dict):
            raise AliQuoteError("invalid_supplement_selection")
        quantity = requested.get("quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 20:
            raise AliQuoteError("invalid_supplement_quantity")
        item = extra_by_id.get(str(requested.get("id") or ""))
        if item is None:
            target = _normalize_catalog_label(requested.get("name"))
            matches = [extra for extra in extras if target and target in labels(extra)]
            item = matches[0] if len(matches) == 1 else None
        if item is None:
            raise AliQuoteError("supplement_not_in_catalog")
        public_id = str(item.get("id") or "")
        if public_id in seen:
            raise AliQuoteError("duplicate_supplement_selection")
        basis = str(item.get("billingBasis") or "")
        if basis not in {"per_day", "per_rental"}:
            raise AliQuoteError("invalid_supplement_basis")
        amount = str((item.get("price") or {}).get("amount") or "")
        _money_cents(amount)
        locale = str(resolved.get("conversation_language") or "en").lower()
        localized_name = str((item.get("names") or {}).get(locale) or item.get("name") or "")
        canonical.append({
            "id": public_id,
            "name": localized_name,
            "quantity": quantity,
            "billing_basis": basis,
            "unit_price_usd": amount,
        })
        seen.add(public_id)
    resolved["supplements"] = sorted(canonical, key=lambda item: item["id"])
    resolved.pop("extra_ids", None)
    return resolved


@dataclass
class DeliveryAdapters:
    send_brand_image: Callable[[dict, str], bool]
    send_whatsapp: Callable[[dict, str], bool]
    send_staff_email: Callable[[dict, bytes], bool]
    send_operator_alerts: Callable[[dict], dict]
    escalate: Callable[[dict, str], None]


def _attempt_twice(operation: Callable, *args) -> bool:
    for attempt in range(2):
        try:
            if operation(*args):
                return True
        except (TimeoutError, ConnectionError, OSError):
            pass
        if attempt == 0:
            continue
    return False


def _finish_superseded_customer_delivery(public_id: str) -> dict:
    quote = get_quote(public_id)
    if not quote:
        raise AliQuoteError("quote_not_found")
    changes = {
        "status": "superseded",
        "last_error_code": None,
    }
    if quote.get("brand_image_status") != "accepted":
        changes["brand_image_status"] = "superseded"
    if quote.get("whatsapp_status") != "accepted":
        changes["whatsapp_status"] = "superseded"
    return update_quote(public_id, **changes)


def process_quote(
    public_id: str,
    ali_client: AliQuoteClient,
    adapters: DeliveryAdapters,
    switches: dict[str, bool] | None = None,
    output_root: str = "/app/data/ali-quotes",
    logo_path: str | None = None,
    delay_seconds: int = CUSTOMER_QUOTE_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = _now,
) -> dict:
    quote = get_quote(public_id)
    if not quote:
        raise AliQuoteError("quote_not_found")
    switches = switches or feature_switches()
    if not switches.get("automation"):
        adapters.escalate(quote, "automation_disabled")
        return update_quote(public_id, status="attention_required", last_error_code="automation_disabled")
    try:
        pricing = json.loads(quote["pricing_json"]) if quote.get("pricing_json") else None
        if pricing is None:
            update_quote(public_id, status="pricing")
            pricing = ali_client.create_quote(json.loads(quote["ali_request_json"]), quote["idempotency_key"])
            quote = update_quote(
                public_id, status="quoted", quote_reference=pricing["quoteReference"],
                quote_snapshot_id=pricing["quoteSnapshotId"], pricing_json=_json(pricing),
                expires_at=pricing["expiresAt"],
            )
        if not quote.get("pdf_path"):
            path, digest = render_quote_pdf(
                public_id, quote["locale"], json.loads(quote["customer_json"]),
                json.loads(quote["rental_json"]), pricing, output_root=output_root,
                logo_path=logo_path,
            )
            quote = update_quote(public_id, status="pdf_ready", pdf_path=path, pdf_sha256=digest)
        pdf_bytes = open(quote["pdf_path"], "rb").read()
        if hashlib.sha256(pdf_bytes).hexdigest() != quote["pdf_sha256"]:
            raise AliQuoteError("pdf_integrity_failed")
        brand_image_ready = False
        if not quote.get("brand_image_path"):
            try:
                image_path, image_digest = render_quote_brand_card(
                    public_id, quote["locale"], quote["quote_reference"],
                    output_root=output_root, logo_path=logo_path,
                )
                quote = update_quote(
                    public_id, brand_image_path=image_path,
                    brand_image_sha256=image_digest,
                )
            except (OSError, ValueError):
                quote = update_quote(
                    public_id, brand_image_path=None, brand_image_sha256=None,
                    brand_image_status="failed",
                )
        if quote.get("brand_image_path") and quote.get("brand_image_sha256"):
            try:
                image_bytes = open(quote["brand_image_path"], "rb").read()
                brand_image_ready = (
                    hashlib.sha256(image_bytes).hexdigest()
                    == quote["brand_image_sha256"]
                )
            except OSError:
                brand_image_ready = False
            if not brand_image_ready:
                quote = update_quote(
                    public_id, brand_image_path=None, brand_image_sha256=None,
                    brand_image_status="failed",
                )
        quote = update_quote(public_id, status="delivering")
        delivery_errors = []
        if switches.get("staff_email") and quote["staff_email_status"] != "sent":
            ok = _attempt_twice(adapters.send_staff_email, quote, pdf_bytes)
            quote = update_quote(public_id, staff_email_status="sent" if ok else "failed")
            if not ok:
                delivery_errors.append("staff_email_failed")
        if switches.get("operator_alerts") and quote.get("notification_status_json") in (None, "", "{}"):
            outcomes = adapters.send_operator_alerts(quote)
            quote = update_quote(public_id, notification_status_json=_json(outcomes))
        customer_delivery_pending = switches.get("customer_delivery") and (
            quote["brand_image_status"] != "accepted"
            or quote["whatsapp_status"] != "accepted"
        )
        if customer_delivery_pending:
            remaining_delay = seconds_until_customer_quote_delivery(
                quote, now=now(), delay_seconds=delay_seconds,
            )
            if remaining_delay:
                sleep(remaining_delay)
            quote = get_quote(public_id)
            if customer_delivery_is_superseded(quote):
                return _finish_superseded_customer_delivery(public_id)
        if switches.get("customer_delivery") and quote["brand_image_status"] != "accepted":
            quote = get_quote(public_id)
            if customer_delivery_is_superseded(quote):
                return _finish_superseded_customer_delivery(public_id)
            ok = brand_image_ready and _attempt_twice(
                adapters.send_brand_image, quote, quote["brand_image_path"],
            )
            quote = update_quote(
                public_id, brand_image_status="accepted" if ok else "failed",
            )
            if not ok:
                delivery_errors.append("brand_image_delivery_failed")
        if switches.get("customer_delivery") and quote["whatsapp_status"] != "accepted":
            quote = get_quote(public_id)
            if customer_delivery_is_superseded(quote):
                return _finish_superseded_customer_delivery(public_id)
            ok = _attempt_twice(adapters.send_whatsapp, quote, quote["pdf_path"])
            quote = update_quote(public_id, whatsapp_status="accepted" if ok else "failed")
            if not ok:
                delivery_errors.append("whatsapp_delivery_failed")
        if delivery_errors:
            raise AliQuoteError(delivery_errors[0])
        complete = (
            quote["staff_email_status"] == "sent"
            and quote["brand_image_status"] == "accepted"
            and quote["whatsapp_status"] == "accepted"
        )
        result = update_quote(public_id, status="complete" if complete else "pdf_ready")
        if result["status"] == "complete":
            _set_quote_conversation_phase(result, "QUOTED")
        return result
    except AliQuoteError as exc:
        attempts = int(quote.get("attempt_count") or 0) + 1
        failed = update_quote(public_id, status="attention_required", attempt_count=attempts, last_error_code=exc.code)
        _set_quote_conversation_phase(failed, "ESCALATED")
        adapters.escalate(failed, exc.code)
        return failed


SUMMARY_LABELS = {
    "en": ("Just checking I’ve got everything right:", "Name", "WhatsApp", "Rental period", "Pickup", "Return", "Car", "Does that all look right?"),
    "nl": ("Even controleren of ik alles goed heb:", "Naam", "WhatsApp", "Huurperiode", "Ophalen", "Terugbrengen", "Auto", "Klopt dit zo?"),
    "pap": ("Laga mi wak si mi tin tur kos korekto:", "Nòmber", "WhatsApp", "Periodo di huur", "Busca", "Devolvé", "Outo", "Tur kos ta bon asina?"),
    "de": ("Ich prüfe kurz, ob ich alles richtig verstanden habe:", "Name", "WhatsApp", "Mietzeitraum", "Abholung", "Rückgabe", "Fahrzeug", "Passt das so?"),
}

SUPPLEMENT_LABELS = {
    "en": {"heading": "Supplements", "per_day": "per rental day", "per_rental": "per rental", "days": "days"},
    "nl": {"heading": "Extra's", "per_day": "per huurdag", "per_rental": "per huur", "days": "dagen"},
    "pap": {"heading": "Ekstranan", "per_day": "pa dia di huur", "per_rental": "pa huur", "days": "dia"},
    "de": {"heading": "Extras", "per_day": "pro Miettag", "per_rental": "pro Miete", "days": "Tage"},
}

SUMMARY_DETAIL_LABELS = {
    "en": {"driver_age": "Driver age", "passengers": "Passengers", "luggage": "Luggage", "comments": "Special requests"},
    "nl": {"driver_age": "Leeftijd bestuurder", "passengers": "Passagiers", "luggage": "Bagage", "comments": "Speciale verzoeken"},
    "pap": {"driver_age": "Edat di chauffeur", "passengers": "Pasaheronan", "luggage": "Maleta", "comments": "Petishonnan spesial"},
    "de": {"driver_age": "Alter des Fahrers", "passengers": "Passagiere", "luggage": "Gepäck", "comments": "Besondere Wünsche"},
}

PREPARING = {
    "en": "Great, I have everything I need. I’ll prepare your official quote and send it here on WhatsApp within 30 minutes.",
    "nl": "Prima, ik heb alles wat ik nodig heb. Ik maak je officiële offerte en stuur die binnen 30 minuten hier via WhatsApp.",
    "pap": "Bon, mi tin tur loke mi mester. Mi ta prepara bo oferta ofisial i lo manda esaki aki via WhatsApp denter di 30 minüt.",
    "de": "Alles klar, ich habe alle Angaben. Ich erstelle jetzt Ihr offizielles Angebot und sende es innerhalb von 30 Minuten hier per WhatsApp.",
}

FALLBACK = {
    "en": "I've passed your confirmed request to our team so they can finish your quote. They'll continue with you here on WhatsApp.",
    "nl": "Ik heb je bevestigde aanvraag aan ons team doorgegeven. Zij ronden je offerte af en helpen je hier verder via WhatsApp.",
    "pap": "Mi a pasa bo petishon konfirmá pa nos tim. Nan lo kaba ku bo oferta i sigui ku bo aki via WhatsApp.",
    "de": "Ich habe Ihre bestätigte Anfrage an unser Team weitergegeben. Es erstellt Ihr Angebot und meldet sich hier in WhatsApp.",
}


def _summary_text(summary: dict) -> str:
    rental = summary["rental"]
    customer = summary["customer"]
    labels = SUMMARY_LABELS[rental["conversation_language"]]
    vehicle = rental.get("vehicle_name") or rental.get("vehicle_class_name") or "-"
    period = format_rental_period(
        rental["rental_start"], rental["rental_end"],
        rental["conversation_language"],
    )
    supplement_lines = []
    supplement_labels = SUPPLEMENT_LABELS[rental["conversation_language"]]
    rental_days = max(1, (
        datetime.strptime(rental["rental_end"], "%Y-%m-%d").date()
        - datetime.strptime(rental["rental_start"], "%Y-%m-%d").date()
    ).days)
    for item in rental.get("supplements") or []:
        unit_cents = _money_cents(item.get("unit_price_usd"))
        quantity = int(item["quantity"])
        basis = item["billing_basis"]
        multiplier = quantity * rental_days if basis == "per_day" else quantity
        calculation = f"{quantity} × USD {_money_text(unit_cents)} {supplement_labels[basis]}"
        if basis == "per_day":
            calculation += f" × {rental_days} {supplement_labels['days']}"
        supplement_lines.append(
            f"{item['name']}: {calculation} = USD {_money_text(unit_cents * multiplier)}"
        )
    supplement_text = ""
    if supplement_lines:
        supplement_text = f"\n{supplement_labels['heading']}:\n" + "\n".join(supplement_lines)
    detail_labels = SUMMARY_DETAIL_LABELS[rental["conversation_language"]]
    detail_lines = [f"{detail_labels['driver_age']}: {rental['driver_age']}"]
    if rental.get("passenger_count") not in (None, ""):
        detail_lines.append(f"{detail_labels['passengers']}: {rental['passenger_count']}")
    if rental.get("luggage_count") not in (None, ""):
        detail_lines.append(f"{detail_labels['luggage']}: {rental['luggage_count']}")
    if str(rental.get("comments") or "").strip():
        detail_lines.append(f"{detail_labels['comments']}: {str(rental['comments']).strip()}")
    detail_text = "\n" + "\n".join(detail_lines)
    return (
        f"{labels[0]}\n\n{labels[1]}: {customer.get('name', '')}\n"
        f"{labels[2]}: {customer.get('whatsapp', '')}\n"
        f"{labels[3]}: {period}\n"
        f"{labels[4]}: {rental['pickup_location']}\n{labels[5]}: {rental['return_location']}\n"
        f"{labels[6]}: {vehicle}{detail_text}{supplement_text}\n\n{labels[7]}"
    )


def _process_production(public_id: str) -> None:
    from agents.social.ali_quote_delivery import production_adapters
    try:
        client = AliQuoteClient(
            os.environ.get("ALI_QUOTE_API_BASE_URL", "https://alicarrental.com"),
            os.environ.get("ALI_QUOTE_API_TOKEN", ""),
        )
        process_quote(
            public_id, client, production_adapters(),
            output_root=os.environ.get("ALI_QUOTE_DATA_ROOT", "/app/data/ali-quotes"),
        )
    except AliQuoteError:
        quote = get_quote(public_id)
        if quote:
            production_adapters().escalate(quote, "processor_unconfigured")


def _turn_action_id(
    conversation_id: str,
    message_text: str,
    supplied_action_id: str,
) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", str(supplied_action_id or "")):
        return str(supplied_action_id)
    return hashlib.sha256(
        f"{conversation_id}\x1f{message_text}".encode("utf-8")
    ).hexdigest()


def _legacy_or_explicit_phase(flags: dict, current_summary_hash: str) -> str:
    phase = str(flags.get("ali_phase") or "")
    if phase in ALI_PHASES:
        return phase
    if (
        flags.get("awaiting_quote_confirmation")
        and hmac.compare_digest(
            str(flags.get("ali_summary_hash") or ""), current_summary_hash,
        )
    ):
        return "SUMMARY_PRESENTED"
    if flags.get("ali_active_quote_public_id") or flags.get("ali_quote_public_id"):
        return "QUOTE_PROCESSING"
    return "DISCOVERY"


def _log_turn_plan(plan: AliTurnPlan, changed_fields: tuple[str, ...]) -> None:
    bm_logger.log(
        "ali_turn_planned",
        phase=plan.phase,
        primary_intent=plan.primary_intent,
        route=plan.outbound_kind,
        reason_code=plan.reason_code,
        changed_fields=list(changed_fields),
        draft_hash_prefix=plan.draft_hash[:12],
        action_id_prefix=plan.action_id[:12],
    )


def fail_closed_turn_plan(
    conversation_id: str,
    message_text: str,
    conversation_language: object,
    supplied_action_id: str = "",
) -> AliTurnPlan:
    """Return a delivered-state-safe response when planning crashes."""
    locale = str(conversation_language or "en")
    if locale not in _INTAKE_SAFETY_FALLBACK:
        locale = "en"
    plan = AliTurnPlan(
        "agent_reply",
        _INTAKE_SAFETY_FALLBACK[locale],
        "DISCOVERY",
        "other",
        "turn_planner_failed_closed",
        _turn_action_id(conversation_id, message_text, supplied_action_id),
    )
    _log_turn_plan(plan, ())
    return plan


def plan_ali_quote_turn(
    conversation_id: str,
    zernio_account_id: str,
    whatsapp_number: str,
    message_text: str,
    fields: dict,
    flags: dict,
    model_reply: str,
    *,
    from_name: str = "",
    raw_config: dict | None = None,
    processor: Callable[[str], None] | None = None,
    primary_intent: object = None,
    requires_human: bool = False,
    recommendation_requested: bool = False,
    summary_action: object = None,
    change_outcome: str = "not_applicable",
    changed_fields: tuple[str, ...] = (),
    supplied_action_id: str = "",
) -> AliTurnPlan:
    """Build exactly one Ali outbound action without marking it delivered."""
    raw = raw_config if raw_config is not None else (config_loader.get_raw() or {})
    if not tenant_enabled(raw):
        raise AliQuoteError("wrong_tenant_or_workflow")
    action_id = _turn_action_id(
        conversation_id, message_text, supplied_action_id,
    )

    try:
        catalog = get_intake_catalog()
        resolved_fields = resolve_catalog_selection(fields, catalog)
        resolved_fields = resolve_catalog_supplements(resolved_fields, catalog)
    except AliQuoteError:
        plan = AliTurnPlan(
            "agent_reply", model_reply, "COLLECTING", "other",
            "catalog_validation_failed", action_id,
        )
        _log_turn_plan(plan, changed_fields)
        return plan
    for key in VEHICLE_STATE_FIELDS:
        if key in resolved_fields:
            fields[key] = resolved_fields[key]
        else:
            fields.pop(key, None)
    fields["supplements"] = resolved_fields.get("supplements") or []
    fields.pop("extra_ids", None)

    structured_intent = str(primary_intent or "")
    if structured_intent not in ALI_PRIMARY_INTENTS:
        if recommendation_requested:
            intent = "request_recommendation"
        elif isinstance(summary_action, dict) and summary_action.get("mode") == "repeat":
            intent = "repeat_summary"
        elif confirmation_decision(message_text)[0]:
            intent = "confirm_summary"
        elif change_outcome == "clarify":
            intent = "reject_or_hesitate"
        else:
            intent = "other"
    else:
        intent = structured_intent

    if recommendation_requested:
        intent = "request_recommendation"
    if change_outcome in {"changed", "clarify", "unchanged"} and intent == "confirm_summary":
        intent = "continue_intake" if change_outcome == "changed" else "other"

    rental = {key: fields.get(key) for key in (
        "rental_start", "rental_end", "pickup_location", "return_location",
        "vehicle_id", "vehicle_name", "vehicle_class_id", "vehicle_class_name",
        "driver_age", "passenger_count", "luggage_count", "supplements", "comments",
        "conversation_language",
    )}
    customer = {
        "name": fields.get("customer_name") or " ".join(
            value for value in (fields.get("first_name"), fields.get("surnames")) if value
        ) or from_name,
        "whatsapp": whatsapp_number,
    }
    try:
        _state_summary, state_hash = normalized_summary(customer, rental, version=0)
    except AliQuoteError:
        flags["ali_phase"] = "COLLECTING"
        flags.pop("ali_draft_hash", None)
        flags.pop("ali_presented_summary_hash", None)
        flags.pop("awaiting_quote_confirmation", None)
        if requires_human:
            plan = AliTurnPlan(
                "escalation", model_reply, "ESCALATED", intent,
                "required_fields_incomplete", action_id,
            )
            _log_turn_plan(plan, changed_fields)
            return plan
        if recommendation_requested and intent == "request_recommendation":
            plan = AliTurnPlan(
                "vehicle_recommendation", model_reply, "DISCOVERY", intent,
                "recommendation_requested_before_quote_complete", action_id,
            )
            _log_turn_plan(plan, changed_fields)
            return plan
        plan = AliTurnPlan(
            "agent_reply", model_reply, "COLLECTING", intent,
            "required_fields_incomplete",
            action_id,
        )
        _log_turn_plan(plan, changed_fields)
        return plan

    previous_draft_hash = str(flags.get("ali_draft_hash") or "")
    previous_version = int(
        flags.get("ali_draft_version")
        or flags.get("ali_summary_version")
        or 0
    )
    draft_changed = not hmac.compare_digest(previous_draft_hash, state_hash)
    summary_version = (
        max(1, previous_version + 1) if previous_draft_hash and draft_changed
        else max(1, previous_version)
    )
    summary, summary_hash = normalized_summary(
        customer, rental, version=summary_version,
    )
    phase = _legacy_or_explicit_phase(flags, summary_hash)
    flags["ali_draft_hash"] = state_hash
    flags["ali_draft_summary_hash"] = summary_hash
    flags["ali_draft_version"] = summary_version

    active_quote_id = str(
        flags.get("ali_active_quote_public_id")
        or flags.get("ali_quote_public_id")
        or ""
    )
    if change_outcome == "changed" or intent in {
        "reject_or_hesitate", "request_recommendation",
    }:
        superseded = supersede_pending_customer_delivery(
            conversation_id, state_hash,
        )
        if superseded:
            flags["ali_superseded_quote_public_id"] = superseded
            flags.pop("ali_active_quote_public_id", None)
            flags.pop("ali_quote_public_id", None)
            active_quote_id = ""
        elif active_quote_id:
            flags["ali_replaces_quote_public_id"] = active_quote_id
            flags.pop("ali_active_quote_public_id", None)
            flags.pop("ali_quote_public_id", None)
            active_quote_id = ""

    if requires_human:
        plan = AliTurnPlan(
            "escalation", model_reply, "ESCALATED", intent,
            "human_required", action_id, state_hash,
        )
        _log_turn_plan(plan, changed_fields)
        return plan

    if intent == "request_recommendation":
        plan = AliTurnPlan(
            "vehicle_recommendation", model_reply, "DISCOVERY", intent,
            "recommendation_requested", action_id, state_hash,
        )
        _log_turn_plan(plan, changed_fields)
        return plan

    if (
        change_outcome == "clarify"
        or (
            intent in {"ask_question", "reject_or_hesitate"}
            and change_outcome != "changed"
        )
    ):
        reason = "change_needs_clarification" if change_outcome == "clarify" else intent
        target_phase = (
            phase if intent == "ask_question" and phase in {
                "SUMMARY_PRESENTED", "QUOTE_PROCESSING", "QUOTED", "ESCALATED",
            }
            else "DISCOVERY"
        )
        plan = AliTurnPlan(
            "agent_reply", model_reply, target_phase, intent,
            reason, action_id, state_hash,
        )
        _log_turn_plan(plan, changed_fields)
        return plan

    if intent == "repeat_summary":
        if phase in {"QUOTE_PROCESSING", "QUOTED", "ESCALATED"}:
            plan = AliTurnPlan(
                "agent_reply", model_reply, phase, intent,
                "summary_repeat_blocked_by_terminal_phase", action_id,
                state_hash, quote_public_id=active_quote_id,
            )
            _log_turn_plan(plan, changed_fields)
            return plan
        plan = AliTurnPlan(
            "summary", _summary_text(summary), "SUMMARY_PRESENTED", intent,
            "explicit_summary_repeat", action_id, state_hash,
            summary_hash, summary_version,
        )
        _log_turn_plan(plan, changed_fields)
        return plan

    if intent == "confirm_summary":
        accepted, confirmation_reason = confirmation_decision(message_text)
        presented_hash = str(
            flags.get("ali_presented_summary_hash")
            or flags.get("ali_summary_hash")
            or ""
        )
        legacy_presented = (
            not flags.get("ali_phase")
            and bool(flags.get("awaiting_quote_confirmation"))
            and hmac.compare_digest(presented_hash, summary_hash)
        )
        delivery_anchored = bool(
            re.fullmatch(
                r"[0-9a-f]{64}",
                str(flags.get("ali_presented_summary_hash") or ""),
            )
            and flags.get("awaiting_quote_confirmation") is True
        ) or legacy_presented
        eligible = (
            accepted
            and phase == "SUMMARY_PRESENTED"
            and hmac.compare_digest(presented_hash, summary_hash)
            and delivery_anchored
            and change_outcome == "not_applicable"
            and not recommendation_requested
        )
        _log_confirmation_decision(
            eligible,
            confirmation_reason if eligible else "summary_not_delivery_eligible",
            summary_hash,
            summary_version,
        )
        if eligible:
            workflow = raw.get("workflow") or {}
            deposit_id = workflow.get("required_deposit_charge_id") or (
                raw.get("ali_quote") or {}
            ).get("required_deposit_charge_id")
            try:
                quote, created = create_confirmed_quote(
                    conversation_id, zernio_account_id, customer, rental,
                    summary_hash, message_text, deposit_id,
                    summary_version=summary_version, raw_config=raw,
                )
            except AliQuoteError as exc:
                state_registry.create_pending_notification(
                    "escalation", "whatsapp", conversation_id, customer["name"],
                    "[ALI QUOTE CONFIGURATION REQUIRED]",
                    f"Confirmed quote could not start safely. Code: {exc.code}.",
                    mode="hard",
                )
                plan = AliTurnPlan(
                    "escalation", FALLBACK[rental["conversation_language"]],
                    "ESCALATED", intent, exc.code, action_id, state_hash,
                )
                _log_turn_plan(plan, changed_fields)
                return plan
            flags["ali_phase"] = "QUOTE_PROCESSING"
            flags["ali_active_quote_public_id"] = quote["public_id"]
            flags["ali_quote_public_id"] = quote["public_id"]
            if created:
                import threading
                threading.Thread(
                    target=processor or _process_production,
                    args=(quote["public_id"],), daemon=True,
                ).start()
            plan = AliTurnPlan(
                "quote_preparing", PREPARING[rental["conversation_language"]],
                "QUOTE_PROCESSING", intent, "current_summary_confirmed",
                action_id, state_hash, summary_hash, summary_version,
                quote["public_id"],
            )
            _log_turn_plan(plan, changed_fields)
            return plan
        if accepted and phase not in {
            "QUOTE_PROCESSING", "QUOTED", "ESCALATED",
        }:
            plan = AliTurnPlan(
                "summary", _summary_text(summary), "SUMMARY_PRESENTED", intent,
                "confirmation_requires_current_summary", action_id, state_hash,
                summary_hash, summary_version,
            )
            _log_turn_plan(plan, changed_fields)
            return plan
        plan = AliTurnPlan(
            "agent_reply", model_reply,
            phase if phase in {"QUOTE_PROCESSING", "QUOTED", "ESCALATED"}
            else "DISCOVERY",
            intent,
            "confirmation_not_eligible", action_id, state_hash,
        )
        _log_turn_plan(plan, changed_fields)
        return plan

    if draft_changed and (
        not previous_draft_hash or change_outcome == "changed"
    ):
        plan = AliTurnPlan(
            "summary", _summary_text(summary), "SUMMARY_PRESENTED",
            intent, "initial_or_corrected_complete_draft", action_id,
            state_hash, summary_hash, summary_version,
        )
        _log_turn_plan(plan, changed_fields)
        return plan

    plan_phase = (
        phase if phase in {"QUOTE_PROCESSING", "QUOTED", "ESCALATED"}
        else "QUOTE_PROCESSING" if active_quote_id
        else "DISCOVERY"
    )
    plan = AliTurnPlan(
        "agent_reply", model_reply, plan_phase, intent,
        "preserve_agent_reply", action_id, state_hash,
        quote_public_id=active_quote_id,
    )
    _log_turn_plan(plan, changed_fields)
    return plan


def handle_ali_quote_turn(
    conversation_id: str,
    zernio_account_id: str,
    whatsapp_number: str,
    message_text: str,
    fields: dict,
    flags: dict,
    from_name: str = "",
    raw_config: dict | None = None,
    processor: Callable[[str], None] | None = None,
    summary_action: object = None,
) -> str | None:
    """Prepare or confirm exactly one deterministic Ali summary.

    Returning ``None`` means required fields are still missing and Marina's
    one-question-at-a-time reply should be used unchanged.
    """
    raw = raw_config if raw_config is not None else (config_loader.get_raw() or {})
    if not tenant_enabled(raw):
        return None
    try:
        catalog = get_intake_catalog()
        resolved_fields = resolve_catalog_selection(fields, catalog)
        resolved_fields = resolve_catalog_supplements(resolved_fields, catalog)
    except AliQuoteError:
        return None
    for key in VEHICLE_STATE_FIELDS:
        if key in resolved_fields:
            fields[key] = resolved_fields[key]
        else:
            fields.pop(key, None)
    fields["supplements"] = resolved_fields.get("supplements") or []
    fields.pop("extra_ids", None)
    rental = {key: fields.get(key) for key in (
        "rental_start", "rental_end", "pickup_location", "return_location",
        "vehicle_id", "vehicle_name", "vehicle_class_id", "vehicle_class_name",
        "driver_age", "passenger_count", "luggage_count", "supplements", "comments",
        "conversation_language",
    )}
    customer = {
        "name": fields.get("customer_name") or " ".join(value for value in (fields.get("first_name"), fields.get("surnames")) if value) or from_name,
        "whatsapp": whatsapp_number,
    }
    try:
        summary, digest = normalized_summary(customer, rental)
    except AliQuoteError:
        flags.pop("ali_summary_hash", None)
        flags.pop("awaiting_quote_confirmation", None)
        return None
    previous = flags.get("ali_summary_hash")
    awaiting = bool(flags.get("awaiting_quote_confirmation"))
    accepted = False
    reason_code = "not_awaiting"
    if awaiting and previous != digest:
        reason_code = "summary_changed"
        _log_confirmation_decision(False, reason_code, digest, 1)
    elif previous == digest and (awaiting or flags.get("ali_quote_public_id")):
        accepted, reason_code = confirmation_decision(message_text)
        if accepted and flags.get("ali_quote_public_id") and not awaiting:
            reason_code = "already_confirmed"
        _log_confirmation_decision(accepted, reason_code, digest, 1)

    if accepted and flags.get("ali_quote_public_id") and not awaiting:
        flags["awaiting_quote_confirmation"] = False
        return PREPARING[rental["conversation_language"]]

    if previous == digest and (awaiting or flags.get("ali_quote_public_id")) and not accepted:
        if (
            isinstance(summary_action, dict)
            and summary_action.get("mode") == "repeat"
        ):
            return _summary_text(summary)
        return None

    if awaiting and previous == digest and accepted:
        workflow = raw.get("workflow") or {}
        deposit_id = workflow.get("required_deposit_charge_id") or (raw.get("ali_quote") or {}).get("required_deposit_charge_id")
        try:
            quote, created = create_confirmed_quote(
                conversation_id, zernio_account_id, customer, rental, digest,
                message_text, deposit_id, raw_config=raw,
            )
        except AliQuoteError as exc:
            state_registry.create_pending_notification(
                "escalation", "whatsapp", conversation_id, customer["name"],
                "[ALI QUOTE CONFIGURATION REQUIRED]", f"Confirmed quote could not start safely. Code: {exc.code}.", mode="hard",
            )
            return FALLBACK[rental["conversation_language"]]
        flags["awaiting_quote_confirmation"] = False
        flags["ali_quote_public_id"] = quote["public_id"]
        if created:
            import threading
            threading.Thread(target=processor or _process_production, args=(quote["public_id"],), daemon=True).start()
        return PREPARING[rental["conversation_language"]]
    flags["ali_summary_hash"] = digest
    flags["ali_summary_version"] = 1
    flags["awaiting_quote_confirmation"] = True
    return _summary_text(summary)


def resume_pending_processing(processor: Callable[[str], None] | None = None) -> int:
    """Resume incomplete quotes only when Ali automation is explicitly on."""
    if not tenant_enabled() or not feature_switches().get("automation"):
        return 0
    import threading
    pending = resumable_quotes()
    for quote in pending:
        threading.Thread(target=processor or _process_production, args=(quote["public_id"],), daemon=True).start()
    return len(pending)
