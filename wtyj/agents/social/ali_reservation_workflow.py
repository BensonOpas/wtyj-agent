"""Durable, tenant-bound Ali post-quote reservation workflow.

Ali Reservation V2 starts customer document collection immediately after the
customer chooses to reserve. Legacy workflows retain their manual availability
decision. No documents, payment evidence, signatures, URLs, or customer
message content are stored here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from agents.social.ali_reservation_confirmation_pdf import (
    render_reservation_confirmation_pdf,
)
from shared import bm_logger, config_loader, state_registry


TENANT_SLUG = "ali-car-rental"
CONTROL_VERSION = 1
POST_QUOTE_PREFIX = "ali_post_quote:v1:"
ACTIONS = {"reserve", "change", "question"}
INTERACTIVE_TYPES = {"buttonreply", "listreply"}
RESERVATION_STATES = {
    "availability_pending",
    "requirements_pending",
    "alternative_required",
    "declined",
    "ready_to_confirm",
    "confirmed",
    "cancelled",
    "superseded",
}
AVAILABILITY_STATES = {"pending", "approved", "alternative", "declined"}
IDENTITY_STATES = {
    "awaiting_external_check", "not_requested", "requested",
    "partially_received", "received", "replacement_requested",
    "verified", "rejected", "not_required",
}
AGREEMENT_STATES = {
    "not_sent", "sent_external", "sent", "viewed", "signed",
    "verified", "rejected", "not_required",
}
PAYMENT_STATES = {
    "not_requested", "not_sent", "link_sent", "customer_reports_paid",
    "awaiting_manual_verification", "verified", "rejected", "not_required",
}
CHECKLIST_FINAL = {"verified", "signed", "not_required"}
DELIVERY_STATES = {"pending", "accepted", "confirmed", "failed", "skipped"}
_BOUND_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

_CONTROL_COPY = {
    "en": {
        "text": "How would you like to proceed?",
        "reserve": "Reserve This Car",
        "change": "Change Something",
        "question": "Ask A Question",
        "reserve_reply": (
            "I have your reservation request. I am asking our team to check "
            "the vehicle availability now. I will update you when they have reviewed it."
        ),
        "reserve_reply_auto": (
            "Great — I’ll guide you through the remaining steps one at a time. "
            "Will you use a passport or an ID card for your reservation?"
        ),
        "reserve_reply_in_progress": (
            "Your reservation request is already in progress. Please continue "
            "with the latest step I sent."
        ),
        "change_reply": "Of course. What would you like me to change in your quote?",
    },
    "nl": {
        "text": "Hoe wil je verdergaan?",
        "reserve": "Reserveer Auto",
        "change": "Iets Wijzigen",
        "question": "Stel Een Vraag",
        "reserve_reply": (
            "Ik heb je reserveringsaanvraag. Ik vraag ons team nu om de "
            "beschikbaarheid van de auto te controleren. Daarna laat ik je het weten."
        ),
        "reserve_reply_auto": (
            "Prima — ik begeleid je stap voor stap door het vervolg. Gebruik je "
            "een paspoort of identiteitskaart voor je reservering?"
        ),
        "reserve_reply_in_progress": (
            "Je reserveringsaanvraag loopt al. Ga verder met de laatste stap die "
            "ik heb gestuurd."
        ),
        "change_reply": "Natuurlijk. Wat wil je in je offerte wijzigen?",
    },
    "pap": {
        "text": "Kon bo ke sigui?",
        "reserve": "Reserva E Outo Aki",
        "change": "Kambia Algu",
        "question": "Hasi Pregunta",
        "reserve_reply": (
            "Mi tin bo petishon di reservashon. Mi ta pidi nos tim pa kontrola "
            "disponibilidat di e outo awor. Mi ta laga bo sa despues di nan revision."
        ),
        "reserve_reply_auto": (
            "Hopi bon — mi ta guia bo paso pa paso. Bo ta usa pasport òf karta "
            "di identidat pa bo reservashon?"
        ),
        "reserve_reply_in_progress": (
            "Bo petishon di reservashon ta andando kaba. Sigui ku e último paso "
            "ku mi a manda bo."
        ),
        "change_reply": "Naturalmente. Kiko bo ke pa mi kambia den bo oferta?",
    },
    "de": {
        "text": "Wie möchten Sie fortfahren?",
        "reserve": "Auto Reservieren",
        "change": "Etwas Ändern",
        "question": "Frage Stellen",
        "reserve_reply": (
            "Ich habe Ihre Reservierungsanfrage. Unser Team pruft jetzt die "
            "Fahrzeugverfugbarkeit. Danach melde ich mich bei Ihnen."
        ),
        "reserve_reply_auto": (
            "Sehr gut — ich begleite Sie Schritt für Schritt. Verwenden Sie für "
            "Ihre Reservierung einen Reisepass oder Personalausweis?"
        ),
        "reserve_reply_in_progress": (
            "Ihre Reservierungsanfrage wird bereits bearbeitet. Fahren Sie bitte "
            "mit dem zuletzt gesendeten Schritt fort."
        ),
        "change_reply": "Gerne. Was mochten Sie in Ihrem Angebot andern?",
    },
}


class AliReservationError(RuntimeError):
    """Machine-readable workflow error suitable for dashboard HTTP mapping."""

    def __init__(self, code: str, status_code: int = 422):
        super().__init__(code)
        self.code = code
        self.status_code = int(status_code)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _tenant_slug() -> str:
    raw = config_loader.get_raw() or {}
    slug = str(raw.get("slug") or (raw.get("business") or {}).get("slug") or "").strip().lower()
    if slug != TENANT_SLUG or str((raw.get("workflow") or {}).get("type") or "") != "ali_quote":
        raise AliReservationError("wrong_tenant_or_workflow", 404)
    return slug


def customer_dossier_enabled(raw: dict | None = None) -> bool:
    """Return the separately reversible Brief 241 activation flag."""
    raw = raw if raw is not None else (config_loader.get_raw() or {})
    features = raw.get("features") if isinstance(raw, dict) else {}
    return bool(
        isinstance(features, dict)
        and features.get("ali_customer_dossier_enabled", False)
    )


def _requirements_complete(identity: str, agreement: str, payment: str) -> bool:
    return (
        identity in {"verified", "not_required"}
        and agreement in {"signed", "verified", "not_required"}
        and payment in {"verified", "not_required"}
    )


def _secret(secret: str | None = None) -> str:
    value = str(
        secret
        or os.environ.get("ALI_QUOTE_CONFIRMATION_SECRET")
        or os.environ.get("ZERNIO_WEBHOOK_SECRET")
        or os.environ.get("ALI_QUOTE_DOWNLOAD_SECRET")
        or ""
    )
    if len(value) < 16:
        raise AliReservationError("post_quote_secret_missing", 422)
    return value


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(state_registry.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema() -> None:
    """Create the durable case and immutable event tables."""
    from agents.social import ali_quote_workflow

    ali_quote_workflow.ensure_schema()
    conn = _connection()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ali_reservations ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "public_id TEXT NOT NULL UNIQUE, tenant_slug TEXT NOT NULL, "
            "quote_public_id TEXT NOT NULL UNIQUE, quote_snapshot_id TEXT NOT NULL, "
            "quote_reference TEXT NOT NULL, conversation_id TEXT NOT NULL, "
            "zernio_account_id TEXT NOT NULL, status TEXT NOT NULL, "
            "availability_status TEXT NOT NULL, identity_status TEXT NOT NULL, "
            "agreement_status TEXT NOT NULL, payment_status TEXT NOT NULL, "
            "alternative_vehicle_json TEXT NOT NULL DEFAULT '{}', "
            "confirmation_reference TEXT UNIQUE, confirmation_pdf_path TEXT, "
            "confirmation_pdf_sha256 TEXT, "
            "confirmation_delivery_status TEXT NOT NULL DEFAULT 'pending', "
            "confirmation_provider_ids_json TEXT NOT NULL DEFAULT '[]', "
            "confirmation_delivery_error_code TEXT, "
            "reminder_status TEXT NOT NULL DEFAULT 'not_scheduled', reminder_due_at TEXT, "
            "last_staff_actor TEXT, last_staff_action_at TEXT, "
            "final_notes TEXT NOT NULL DEFAULT '', "
            "dossier_version INTEGER NOT NULL DEFAULT 0, "
            "original_license_inspected_at TEXT, original_license_inspected_by TEXT, "
            "original_identity_inspected_at TEXT, original_identity_inspected_by TEXT, "
            "confirmed_at TEXT, revision INTEGER NOT NULL DEFAULT 1, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ali_reservations_queue "
            "ON ali_reservations(tenant_slug, status, updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ali_reservations_conversation "
            "ON ali_reservations(tenant_slug, conversation_id, id DESC)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ali_reservation_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, event_public_id TEXT NOT NULL UNIQUE, "
            "reservation_public_id TEXT NOT NULL, tenant_slug TEXT NOT NULL, "
            "event_type TEXT NOT NULL, from_status TEXT NOT NULL, to_status TEXT NOT NULL, "
            "actor_type TEXT NOT NULL, actor_id TEXT NOT NULL, metadata_json TEXT NOT NULL, "
            "created_at TEXT NOT NULL, "
            "FOREIGN KEY(reservation_public_id) REFERENCES ali_reservations(public_id) ON DELETE RESTRICT)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ali_reservation_events_case "
            "ON ali_reservation_events(reservation_public_id, id)"
        )
        columns = {
            str(item["name"])
            for item in conn.execute("PRAGMA table_info(ali_reservations)").fetchall()
        }
        for name, definition in {
            "final_notes": "TEXT NOT NULL DEFAULT ''",
            "dossier_version": "INTEGER NOT NULL DEFAULT 0",
            "original_license_inspected_at": "TEXT",
            "original_license_inspected_by": "TEXT",
            "original_identity_inspected_at": "TEXT",
            "original_identity_inspected_by": "TEXT",
        }.items():
            if name not in columns:
                conn.execute(
                    f"ALTER TABLE ali_reservations ADD COLUMN {name} {definition}"
                )
        conn.execute(
            "CREATE TRIGGER IF NOT EXISTS ali_reservation_events_no_update "
            "BEFORE UPDATE ON ali_reservation_events BEGIN "
            "SELECT RAISE(ABORT, 'ali_reservation_events are append-only'); END"
        )
        conn.execute(
            "CREATE TRIGGER IF NOT EXISTS ali_reservation_events_no_delete "
            "BEFORE DELETE ON ali_reservation_events BEGIN "
            "SELECT RAISE(ABORT, 'ali_reservation_events are append-only'); END"
        )
        conn.commit()
    finally:
        conn.close()


def _normalized_interactive_type(value: object) -> str:
    return re.sub(r"[^a-z]", "", str(value or "").strip().lower())


def _bound_id(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not _BOUND_ID.fullmatch(text):
        raise AliReservationError(code, 422)
    return text


def _action_material(
    action: str,
    conversation_id: str,
    account_id: str,
    quote_public_id: str,
    quote_snapshot_id: str,
) -> str:
    return "\x1f".join((
        TENANT_SLUG,
        str(CONTROL_VERSION),
        action,
        conversation_id,
        account_id,
        quote_public_id,
        quote_snapshot_id,
    ))


def post_quote_action_payload(
    action: str,
    conversation_id: str,
    account_id: str,
    quote_public_id: str,
    quote_snapshot_id: str,
    *,
    secret: str | None = None,
) -> str:
    """Return a compact HMAC action bound to one exact quote snapshot."""
    if action not in ACTIONS or not conversation_id or not account_id:
        raise AliReservationError("invalid_post_quote_action_anchor", 422)
    quote_id = _bound_id(quote_public_id, "invalid_quote_public_id")
    snapshot_id = _bound_id(quote_snapshot_id, "invalid_quote_snapshot_id")
    signature = hmac.new(
        _secret(secret).encode("utf-8"),
        _action_material(action, conversation_id, account_id, quote_id, snapshot_id).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{POST_QUOTE_PREFIX}{action}:{quote_id}:{snapshot_id}:{signature}"


def _quote_by_public_id(conn: sqlite3.Connection, public_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM ali_quotes WHERE public_id = ?", (public_id,)).fetchone()


def _newest_delivered_quote(
    conn: sqlite3.Connection,
    conversation_id: str,
    account_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM ali_quotes WHERE conversation_id = ? AND zernio_account_id = ? "
        "AND whatsapp_status = 'accepted' AND customer_delivery_superseded_at IS NULL "
        "AND quote_snapshot_id IS NOT NULL ORDER BY id DESC LIMIT 1",
        (conversation_id, account_id),
    ).fetchone()


def _quote_expired(quote: sqlite3.Row | dict) -> bool:
    value = str(quote["expires_at"] or "")
    if not value:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) <= _now()
    except ValueError:
        return True


def build_post_quote_control(quote: dict, secret: str | None = None) -> dict:
    """Build one three-button customer control for a provider-confirmed quote."""
    _tenant_slug()
    if not isinstance(quote, dict):
        raise AliReservationError("invalid_quote", 422)
    conversation_id = str(quote.get("conversation_id") or "")
    account_id = str(quote.get("zernio_account_id") or "")
    quote_public_id = _bound_id(quote.get("public_id"), "invalid_quote_public_id")
    snapshot_id = _bound_id(quote.get("quote_snapshot_id"), "invalid_quote_snapshot_id")
    if not conversation_id or not account_id or quote.get("whatsapp_status") != "accepted":
        raise AliReservationError("quote_not_delivered", 409)
    if quote.get("customer_delivery_superseded_at"):
        raise AliReservationError("stale_or_superseded_quote", 409)
    locale = str(quote.get("locale") or "en").lower()
    copy = _CONTROL_COPY.get(locale, _CONTROL_COPY["en"])
    buttons = []
    for action in ("reserve", "change", "question"):
        buttons.append({
            "type": "postback",
            "title": copy[action],
            "payload": post_quote_action_payload(
                action, conversation_id, account_id, quote_public_id, snapshot_id, secret=secret,
            ),
        })
    state_hash = hashlib.sha256(_json(buttons).encode("utf-8")).hexdigest()
    return {
        "state_hash": state_hash,
        "idempotency_key": f"ali-post-quote-control-{state_hash}",
        "text": copy["text"],
        "buttons": buttons,
        "quote_public_id": quote_public_id,
        "quote_snapshot_id": snapshot_id,
        "control_version": CONTROL_VERSION,
    }


def resolve_post_quote_interaction(
    interactive_type: object,
    interactive_id: object,
    conversation_id: str,
    account_id: str,
    secret: str | None = None,
) -> dict | None:
    """Validate and classify a post-quote control before the Claude call."""
    payload = str(interactive_id or "").strip()
    if not payload.startswith(POST_QUOTE_PREFIX):
        return None
    _tenant_slug()
    tail = payload[len(POST_QUOTE_PREFIX):]
    parts = tail.split(":")
    if len(parts) != 4:
        return {"status": "invalid", "action": None, "quote_public_id": ""}
    action, quote_public_id, snapshot_id, supplied_signature = parts
    if (
        action not in ACTIONS
        or _normalized_interactive_type(interactive_type) not in INTERACTIVE_TYPES
        or not _BOUND_ID.fullmatch(quote_public_id)
        or not _BOUND_ID.fullmatch(snapshot_id)
        or not re.fullmatch(r"[0-9a-f]{64}", supplied_signature)
    ):
        return {"status": "invalid", "action": action if action in ACTIONS else None, "quote_public_id": quote_public_id}
    try:
        expected = post_quote_action_payload(
            action, conversation_id, account_id, quote_public_id, snapshot_id, secret=secret,
        )
    except AliReservationError:
        expected = ""
    if not expected or not hmac.compare_digest(payload, expected):
        return {"status": "invalid", "action": action, "quote_public_id": quote_public_id}

    ensure_schema()
    conn = _connection()
    try:
        quote = _quote_by_public_id(conn, quote_public_id)
        if not quote:
            return {"status": "invalid", "action": action, "quote_public_id": quote_public_id}
        strict_match = (
            str(quote["conversation_id"]) == str(conversation_id)
            and str(quote["zernio_account_id"]) == str(account_id)
            and str(quote["quote_snapshot_id"] or "") == snapshot_id
        )
        if not strict_match:
            return {"status": "invalid", "action": action, "quote_public_id": quote_public_id}
        newest = _newest_delivered_quote(conn, conversation_id, account_id)
        stale = (
            quote["whatsapp_status"] != "accepted"
            or bool(quote["customer_delivery_superseded_at"])
            or newest is None
            or str(newest["public_id"]) != quote_public_id
            or _quote_expired(quote)
        )
        reservation = conn.execute(
            "SELECT * FROM ali_reservations WHERE tenant_slug = ? AND quote_public_id = ?",
            (TENANT_SLUG, quote_public_id),
        ).fetchone()
        if reservation and reservation["status"] in {"cancelled", "superseded"}:
            stale = True
        status = "stale" if stale else "current"
        if not stale and action == "reserve" and reservation:
            status = "repeated"
        return {
            "status": status,
            "action": action,
            "quote_public_id": quote_public_id,
            "quote_snapshot_id": snapshot_id,
            "conversation_id": conversation_id,
            "account_id": account_id,
            "control_version": CONTROL_VERSION,
            "verified": True,
        }
    finally:
        conn.close()


def _checklist_defaults() -> tuple[str, str, str]:
    raw = config_loader.get_raw() or {}
    post_quote = (raw.get("workflow") or {}).get("post_quote") or {}
    requirements = post_quote.get("required_checks") or {}
    modern = customer_dossier_enabled(raw)
    return (
        ("not_requested" if modern else "awaiting_external_check")
        if requirements.get("identity", True) else "not_required",
        "not_sent" if requirements.get("agreement", True) else "not_required",
        ("not_sent" if modern else "not_requested")
        if requirements.get("payment", True) else "not_required",
    )


def _event(
    conn: sqlite3.Connection,
    reservation_public_id: str,
    event_type: str,
    from_status: str,
    to_status: str,
    actor_type: str,
    actor_id: str,
    metadata: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO ali_reservation_events ("
        "event_public_id, reservation_public_id, tenant_slug, event_type, "
        "from_status, to_status, actor_type, actor_id, metadata_json, created_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()), reservation_public_id, TENANT_SLUG, event_type,
            from_status, to_status, actor_type, actor_id, _json(metadata or {}), _iso(),
        ),
    )


def _next_action(status: str) -> str:
    return {
        "availability_pending": "review_availability",
        "requirements_pending": "complete_requirements",
        "alternative_required": "contact_customer_with_alternative",
        "ready_to_confirm": "confirm_reservation",
        "confirmed": "none",
        "declined": "none",
        "cancelled": "none",
        "superseded": "none",
    }.get(status, "review")


def _public_row(row: sqlite3.Row | dict | None) -> dict | None:
    if row is None:
        return None
    value = dict(row)
    try:
        value["alternative_vehicle"] = json.loads(value.pop("alternative_vehicle_json") or "{}")
    except (ValueError, TypeError, json.JSONDecodeError):
        value["alternative_vehicle"] = {}
    try:
        value["confirmation_provider_ids"] = json.loads(
            value.pop("confirmation_provider_ids_json") or "[]"
        )
    except (ValueError, TypeError, json.JSONDecodeError):
        value["confirmation_provider_ids"] = []
    value["checklist"] = {
        "identity": value.get("identity_status"),
        "agreement": value.get("agreement_status"),
        "payment": value.get("payment_status"),
    }
    value["documents_status"] = value.get("identity_status")
    value["checklist_complete"] = _requirements_complete(
        str(value.get("identity_status") or ""),
        str(value.get("agreement_status") or ""),
        str(value.get("payment_status") or ""),
    )
    value["dossier_status"] = (
        "approved" if value.get("status") == "confirmed"
        else "ready_for_review"
        if value.get("availability_status") == "approved" and value["checklist_complete"]
        else "incomplete"
    )
    value["pickup_checklist"] = {
        "original_license_inspected": bool(value.get("original_license_inspected_at")),
        "original_license_inspected_at": value.get("original_license_inspected_at"),
        "original_license_inspected_by": value.get("original_license_inspected_by"),
        "original_identity_inspected": bool(value.get("original_identity_inspected_at")),
        "original_identity_inspected_at": value.get("original_identity_inspected_at"),
        "original_identity_inspected_by": value.get("original_identity_inspected_by"),
    }
    value["next_action"] = _next_action(str(value.get("status") or ""))
    return value


def _validate_actor(actor: object) -> str:
    value = str(actor or "").strip()
    if not value or len(value) > 120:
        raise AliReservationError("invalid_staff_actor", 422)
    return value


def _note_marker(note: object) -> bool:
    if note is None or str(note).strip() == "":
        return False
    if len(str(note)) > 1000:
        raise AliReservationError("invalid_staff_note", 422)
    return True


def _create_reservation_for_quote(
    quote: sqlite3.Row,
    *,
    actor_type: str,
    actor_id: str,
    action_id: str = "",
) -> tuple[dict, bool]:
    identity, agreement, payment = _checklist_defaults()
    from agents.social import ali_reservation_v2

    automatic_document_collection = (
        customer_dossier_enabled() and ali_reservation_v2.enabled()
    )
    initial_status = (
        "requirements_pending"
        if automatic_document_collection
        else "availability_pending"
    )
    initial_availability = (
        "approved" if automatic_document_collection else "pending"
    )
    initial_identity = (
        "requested"
        if automatic_document_collection and identity == "not_requested"
        else identity
    )
    created_at = _iso()
    public_id = str(uuid.uuid4())
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        current_quote = _quote_by_public_id(conn, str(quote["public_id"]))
        newest = _newest_delivered_quote(
            conn, str(quote["conversation_id"]), str(quote["zernio_account_id"]),
        )
        if (
            not current_quote
            or newest is None
            or str(newest["public_id"]) != str(quote["public_id"])
            or current_quote["whatsapp_status"] != "accepted"
            or current_quote["customer_delivery_superseded_at"]
            or _quote_expired(current_quote)
        ):
            raise AliReservationError("stale_or_superseded_quote", 409)
        existing = conn.execute(
            "SELECT * FROM ali_reservations WHERE tenant_slug = ? AND quote_public_id = ?",
            (TENANT_SLUG, quote["public_id"]),
        ).fetchone()
        if existing:
            if existing["status"] in {"cancelled", "superseded"}:
                raise AliReservationError("stale_or_superseded_quote", 409)
            conn.commit()
            public = _public_row(existing)
            if ali_reservation_v2.enabled():
                ali_reservation_v2.initialize_reservation(str(existing["public_id"]))
                public["workflow_v2"] = ali_reservation_v2.get_case(
                    str(existing["public_id"])
                )
            return public, False
        conn.execute(
            "INSERT INTO ali_reservations ("
            "public_id, tenant_slug, quote_public_id, quote_snapshot_id, quote_reference, "
            "conversation_id, zernio_account_id, status, availability_status, "
            "identity_status, agreement_status, payment_status, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                public_id, TENANT_SLUG, quote["public_id"], quote["quote_snapshot_id"],
                quote["quote_reference"], quote["conversation_id"], quote["zernio_account_id"],
                initial_status, initial_availability, initial_identity,
                agreement, payment, created_at, created_at,
            ),
        )
        metadata = {
            "action": "reserve",
            "availability_mode": (
                "automatic" if automatic_document_collection else "manual"
            ),
        }
        if action_id:
            metadata["action_id_hash"] = hashlib.sha256(str(action_id).encode("utf-8")).hexdigest()
        _event(
            conn, public_id, "reservation_requested", "none", "availability_pending",
            actor_type, actor_id, metadata,
        )
        if automatic_document_collection:
            _event(
                conn, public_id, "availability_auto_approved",
                "availability_pending", "requirements_pending", "system",
                "reservation_v2_system", {"workflow_version": 2},
            )
            _event(
                conn, public_id, "direct_whatsapp_document_intake_requested",
                "requirements_pending", "requirements_pending", "system",
                "reservation_v2_system",
                {"workflow_version": 2, "public_upload_links": 0},
            )
        row = conn.execute(
            "SELECT * FROM ali_reservations WHERE public_id = ?", (public_id,),
        ).fetchone()
        conn.commit()
        public = _public_row(row)
        if ali_reservation_v2.enabled():
            public["workflow_v2"] = ali_reservation_v2.initialize_reservation(
                public_id
            )
        if automatic_document_collection:
            bm_logger.log(
                "ali_reservation_automatic_document_collection_started",
                reservation_public_id_prefix=public_id[:12],
                quote_reference=str(quote["quote_reference"] or "")[:40],
            )
        return public, True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _reserve_reply(copy: dict, reservation: dict, created: bool) -> str:
    workflow_case = reservation.get("workflow_v2") or {}
    if reservation.get("availability_status") != "approved":
        return str(copy["reserve_reply"])
    if created or (
        workflow_case.get("state") == "documents_collecting"
        and not workflow_case.get("identityType")
    ):
        return str(copy["reserve_reply_auto"])
    return str(copy["reserve_reply_in_progress"])


def handle_post_quote_action(interaction: dict, action_id: str = "") -> dict:
    """Apply a verified customer control without a second model call."""
    _tenant_slug()
    if not isinstance(interaction, dict) or not interaction.get("verified"):
        raise AliReservationError("unverified_post_quote_action", 422)
    action = str(interaction.get("action") or "")
    status = str(interaction.get("status") or "")
    quote_public_id = str(interaction.get("quote_public_id") or "")
    if action not in ACTIONS or status not in {"current", "repeated"}:
        return {"text": "", "action": action or None, "status": status or "invalid", "reservation": None}
    ensure_schema()
    conn = _connection()
    quote = _quote_by_public_id(conn, quote_public_id)
    conn.close()
    if not quote:
        raise AliReservationError("quote_not_found", 404)
    if (
        str(quote["conversation_id"]) != str(interaction.get("conversation_id") or "")
        or str(quote["zernio_account_id"]) != str(interaction.get("account_id") or "")
        or str(quote["quote_snapshot_id"] or "") != str(interaction.get("quote_snapshot_id") or "")
    ):
        raise AliReservationError("post_quote_binding_mismatch", 409)
    copy = _CONTROL_COPY.get(str(quote["locale"] or "en").lower(), _CONTROL_COPY["en"])
    if action == "reserve":
        reservation, created = _create_reservation_for_quote(
            quote,
            actor_type="customer",
            actor_id="signed_postback",
            action_id=action_id,
        )
        return {
            "text": _reserve_reply(copy, reservation, created),
            "action": action,
            "status": "created" if created else "repeated",
            "reservation": reservation,
        }
    if action == "change":
        return {"text": copy["change_reply"], "action": action, "status": "change_requested", "reservation": None}
    return {"text": "", "action": action, "status": "question", "reservation": None}


def is_exact_reserve_fallback(text: object) -> bool:
    """The sole approved text fallback is the exact token RESERVE."""
    return str(text or "").strip() == "RESERVE"


def handle_exact_reserve(
    conversation_id: str,
    account_id: str,
    action_id: str = "",
) -> dict:
    """Reserve the newest eligible quote for the exact RESERVE fallback."""
    _tenant_slug()
    if not conversation_id or not account_id:
        raise AliReservationError("invalid_post_quote_action_anchor", 422)
    ensure_schema()
    conn = _connection()
    quote = _newest_delivered_quote(conn, conversation_id, account_id)
    conn.close()
    if not quote or _quote_expired(quote):
        raise AliReservationError("eligible_quote_not_found", 404)
    reservation, created = _create_reservation_for_quote(
        quote, actor_type="customer", actor_id="exact_reserve_fallback", action_id=action_id,
    )
    copy = _CONTROL_COPY.get(str(quote["locale"] or "en").lower(), _CONTROL_COPY["en"])
    return {
        "text": _reserve_reply(copy, reservation, created),
        "action": "reserve",
        "status": "created" if created else "repeated",
        "reservation": reservation,
    }


def list_reservations(status: str | None = None) -> list[dict]:
    _tenant_slug()
    if status is not None and status not in RESERVATION_STATES:
        raise AliReservationError("invalid_reservation_status", 422)
    ensure_schema()
    conn = _connection()
    try:
        if status is None:
            rows = conn.execute(
                "SELECT * FROM ali_reservations WHERE tenant_slug = ? ORDER BY updated_at DESC, id DESC",
                (TENANT_SLUG,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ali_reservations WHERE tenant_slug = ? AND status = ? "
                "ORDER BY updated_at DESC, id DESC",
                (TENANT_SLUG, status),
            ).fetchall()
        items = []
        from agents.social import ali_reservation_v2
        use_v2 = ali_reservation_v2.enabled()
        for row in rows:
            item = _public_row(row)
            item.pop("confirmation_pdf_path", None)
            item.pop("final_notes", None)
            if use_v2:
                try:
                    item["workflow_v2"] = ali_reservation_v2.get_case(
                        str(row["public_id"])
                    )
                except AliReservationError as exc:
                    if exc.code != "reservation_v2_not_found":
                        raise
            items.append(item)
        return items
    finally:
        conn.close()


def get_reservation(public_id: str) -> dict | None:
    _tenant_slug()
    ensure_schema()
    conn = _connection()
    row = conn.execute(
        "SELECT * FROM ali_reservations WHERE tenant_slug = ? AND public_id = ?",
        (TENANT_SLUG, public_id),
    ).fetchone()
    conn.close()
    item = _public_row(row)
    if item is not None:
        from agents.social import ali_reservation_v2
        if ali_reservation_v2.enabled():
            try:
                item["workflow_v2"] = ali_reservation_v2.get_case(public_id)
            except AliReservationError as exc:
                if exc.code != "reservation_v2_not_found":
                    raise
    return item


def list_reservation_events(public_id: str) -> list[dict]:
    _tenant_slug()
    ensure_schema()
    conn = _connection()
    try:
        exists = conn.execute(
            "SELECT 1 FROM ali_reservations WHERE tenant_slug = ? AND public_id = ?",
            (TENANT_SLUG, public_id),
        ).fetchone()
        if not exists:
            raise AliReservationError("reservation_not_found", 404)
        rows = conn.execute(
            "SELECT * FROM ali_reservation_events WHERE tenant_slug = ? "
            "AND reservation_public_id = ? ORDER BY id",
            (TENANT_SLUG, public_id),
        ).fetchall()
        result = []
        for row in rows:
            value = dict(row)
            value["metadata"] = json.loads(value.pop("metadata_json") or "{}")
            result.append(value)
        return result
    finally:
        conn.close()


def _require_case(conn: sqlite3.Connection, public_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM ali_reservations WHERE tenant_slug = ? AND public_id = ?",
        (TENANT_SLUG, public_id),
    ).fetchone()
    if not row:
        raise AliReservationError("reservation_not_found", 404)
    return row


def _check_revision(row: sqlite3.Row, expected_revision: int | None) -> None:
    if expected_revision is None:
        return
    if isinstance(expected_revision, bool) or int(expected_revision) != int(row["revision"]):
        raise AliReservationError("stale_revision", 409)


def _alternative_vehicle(value: object) -> dict:
    if not isinstance(value, dict):
        raise AliReservationError("alternative_vehicle_required", 422)
    allowed = {
        "vehicle_id", "vehicle_name", "vehicle_class_id", "vehicle_class_name",
        "daily_rate_usd", "currency",
    }
    if set(value) - allowed:
        raise AliReservationError("invalid_alternative_vehicle", 422)
    result = {}
    for key, item in value.items():
        if item is None or str(item).strip() == "":
            continue
        text = str(item).strip()
        if len(text) > (12 if key == "daily_rate_usd" else 120):
            raise AliReservationError("invalid_alternative_vehicle", 422)
        result[key] = text
    if not any(result.get(key) for key in (
        "vehicle_id", "vehicle_name", "vehicle_class_id", "vehicle_class_name",
    )):
        raise AliReservationError("alternative_vehicle_required", 422)
    if "currency" in result:
        result["currency"] = result["currency"].upper()
        if not re.fullmatch(r"[A-Z]{3}", result["currency"]):
            raise AliReservationError("invalid_alternative_vehicle", 422)
    if "daily_rate_usd" in result:
        try:
            amount = Decimal(result["daily_rate_usd"])
        except InvalidOperation as exc:
            raise AliReservationError("invalid_alternative_vehicle", 422) from exc
        if amount < 0 or amount > Decimal("100000") or amount.as_tuple().exponent < -2:
            raise AliReservationError("invalid_alternative_vehicle", 422)
        result["daily_rate_usd"] = f"{amount:.2f}"
    return result


def apply_staff_decision(
    public_id: str,
    decision: str,
    actor: str,
    note: object = None,
    alternative_vehicle: dict | None = None,
    expected_revision: int | None = None,
) -> dict:
    _tenant_slug()
    if decision not in {"approve", "alternative", "decline"}:
        raise AliReservationError("invalid_availability_decision", 422)
    actor_id = _validate_actor(actor)
    note_provided = _note_marker(note)
    alternative = _alternative_vehicle(alternative_vehicle) if decision == "alternative" else {}
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _require_case(conn, public_id)
        if decision == "approve" and row["availability_status"] == "approved":
            conn.commit()
            result = _public_row(row)
            from agents.social import ali_reservation_v2
            if ali_reservation_v2.enabled():
                result["workflow_v2"] = ali_reservation_v2.sync_availability_decision(
                    public_id, decision, actor=actor_id,
                    legacy_revision=int(row["revision"]),
                )
            return result
        if decision == "decline" and row["status"] == "declined":
            conn.commit()
            result = _public_row(row)
            from agents.social import ali_reservation_v2
            if ali_reservation_v2.enabled():
                result["workflow_v2"] = ali_reservation_v2.sync_availability_decision(
                    public_id, decision, actor=actor_id,
                    legacy_revision=int(row["revision"]),
                )
            return result
        if decision == "alternative" and row["status"] == "alternative_required":
            current = json.loads(row["alternative_vehicle_json"] or "{}")
            if current == alternative:
                conn.commit()
                return _public_row(row)
        _check_revision(row, expected_revision)
        if row["status"] in {"confirmed", "cancelled", "superseded", "declined"}:
            raise AliReservationError("invalid_transition", 409)
        if decision == "approve" and row["status"] != "availability_pending":
            raise AliReservationError("invalid_transition", 409)

        from_status = str(row["status"])
        if decision == "approve":
            complete = _requirements_complete(
                row["identity_status"], row["agreement_status"], row["payment_status"],
            )
            to_status = "ready_to_confirm" if complete else "requirements_pending"
            availability = "approved"
            event_type = "availability_approved"
            alternative_json = row["alternative_vehicle_json"]
        elif decision == "alternative":
            to_status = "alternative_required"
            availability = "alternative"
            event_type = "alternative_required"
            alternative_json = _json(alternative)
        else:
            to_status = "declined"
            availability = "declined"
            event_type = "availability_declined"
            alternative_json = row["alternative_vehicle_json"]
        timestamp = _iso()
        conn.execute(
            "UPDATE ali_reservations SET status = ?, availability_status = ?, "
            "alternative_vehicle_json = ?, last_staff_actor = ?, last_staff_action_at = ?, "
            "revision = revision + 1, updated_at = ? WHERE public_id = ? AND tenant_slug = ?",
            (
                to_status, availability, alternative_json, actor_id, timestamp,
                timestamp, public_id, TENANT_SLUG,
            ),
        )
        metadata = {"decision": decision, "note_provided": note_provided}
        if alternative:
            metadata["alternative_vehicle"] = alternative
        _event(conn, public_id, event_type, from_status, to_status, "staff", actor_id, metadata)
        updated = _require_case(conn, public_id)
        conn.commit()
        result = _public_row(updated)
        from agents.social import ali_reservation_v2
        if ali_reservation_v2.enabled() and decision in {"approve", "decline"}:
            result["workflow_v2"] = ali_reservation_v2.sync_availability_decision(
                public_id, decision, actor=actor_id,
                legacy_revision=int(updated["revision"]),
            )
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_checklist(
    public_id: str,
    *,
    actor: str,
    identity: str | None = None,
    agreement: str | None = None,
    payment: str | None = None,
    note: object = None,
    expected_revision: int | None = None,
) -> dict:
    _tenant_slug()
    if customer_dossier_enabled():
        raise AliReservationError("customer_file_controls_required", 409)
    actor_id = _validate_actor(actor)
    note_provided = _note_marker(note)
    supplied = {"identity": identity, "agreement": agreement, "payment": payment}
    if all(value is None for value in supplied.values()):
        raise AliReservationError("empty_checklist_update", 422)
    allowed = {
        "identity": IDENTITY_STATES,
        "agreement": AGREEMENT_STATES,
        "payment": PAYMENT_STATES,
    }
    for key, value in supplied.items():
        if value is not None and value not in allowed[key]:
            raise AliReservationError(f"invalid_{key}_status", 422)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _require_case(conn, public_id)
        if row["status"] not in {"requirements_pending", "ready_to_confirm"}:
            raise AliReservationError("invalid_transition", 409)
        desired = {
            "identity": identity if identity is not None else row["identity_status"],
            "agreement": agreement if agreement is not None else row["agreement_status"],
            "payment": payment if payment is not None else row["payment_status"],
        }
        to_status = (
            "ready_to_confirm"
            if row["availability_status"] == "approved"
            and _requirements_complete(
                desired["identity"], desired["agreement"], desired["payment"],
            )
            else "requirements_pending"
        )
        changed = {
            key: value for key, value in desired.items()
            if value != row[f"{key}_status"]
        }
        if not changed and to_status == row["status"]:
            conn.commit()
            return _public_row(row)
        _check_revision(row, expected_revision)
        timestamp = _iso()
        conn.execute(
            "UPDATE ali_reservations SET identity_status = ?, agreement_status = ?, "
            "payment_status = ?, status = ?, last_staff_actor = ?, last_staff_action_at = ?, "
            "revision = revision + 1, updated_at = ? WHERE public_id = ? AND tenant_slug = ?",
            (
                desired["identity"], desired["agreement"], desired["payment"],
                to_status, actor_id, timestamp, timestamp, public_id, TENANT_SLUG,
            ),
        )
        _event(
            conn, public_id, "checklist_updated", str(row["status"]), to_status,
            "staff", actor_id,
            {"changed": changed, "note_provided": note_provided},
        )
        updated = _require_case(conn, public_id)
        conn.commit()
        return _public_row(updated)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _confirmation_reference(public_id: str, quote_snapshot_id: str, confirmed_at: str) -> str:
    date = confirmed_at[:10].replace("-", "")
    token = hashlib.sha256(f"{public_id}\x1f{quote_snapshot_id}".encode("utf-8")).hexdigest()[:8].upper()
    return f"ALI-RSV-{date}-{token}"


def confirm_reservation(
    public_id: str,
    actor: str,
    note: object = None,
    expected_revision: int | None = None,
    output_root: str = "/app/data/ali-reservations",
    logo_path: str | None = None,
) -> dict:
    """Confirm atomically after availability and all checks are complete."""
    _tenant_slug()
    actor_id = _validate_actor(actor)
    note_provided = _note_marker(note)
    ensure_schema()
    if customer_dossier_enabled():
        from agents.social import ali_customer_dossier
        ali_customer_dossier.ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _require_case(conn, public_id)
        if row["status"] == "confirmed":
            conn.commit()
            result = _public_row(row)
            from agents.social import ali_reservation_v2
            if ali_reservation_v2.enabled():
                current_v2 = ali_reservation_v2.get_case(public_id)
                if current_v2["state"] == "final_approval_pending":
                    current_v2 = ali_reservation_v2.transition(
                        public_id,
                        "confirmed",
                        actor_type="staff",
                        actor_id=actor_id,
                        idempotency_key="final-reservation-approved",
                        reason="staff_final_approval",
                        expected_revision=current_v2["revision"],
                    )
                result["workflow_v2"] = current_v2
            return result
        _check_revision(row, expected_revision)
        if (
            row["status"] != "ready_to_confirm"
            or row["availability_status"] != "approved"
            or not _requirements_complete(
                row["identity_status"], row["agreement_status"], row["payment_status"],
            )
        ):
            raise AliReservationError("confirmation_preconditions_not_met", 409)
        if customer_dossier_enabled():
            audit = conn.execute(
                "SELECT status FROM ali_reservation_dossier_audits "
                "WHERE tenant_slug = ? AND reservation_public_id = ? "
                "ORDER BY version DESC LIMIT 1",
                (TENANT_SLUG, public_id),
            ).fetchone()
            if not audit or audit["status"] != "ready_for_review":
                raise AliReservationError("dossier_review_required", 409)
        quote = _quote_by_public_id(conn, str(row["quote_public_id"]))
        if not quote or str(quote["quote_snapshot_id"] or "") != str(row["quote_snapshot_id"]):
            raise AliReservationError("quote_snapshot_not_found", 409)
        confirmed_at = _iso()
        reference = _confirmation_reference(public_id, str(row["quote_snapshot_id"]), confirmed_at)
        rendering_row = dict(row)
        rendering_row.update({
            "confirmation_reference": reference,
            "confirmed_at": confirmed_at,
            "updated_at": confirmed_at,
        })
        pdf_path, pdf_sha256 = render_reservation_confirmation_pdf(
            rendering_row, dict(quote), output_root=output_root, logo_path=logo_path,
        )
        conn.execute(
            "UPDATE ali_reservations SET status = 'confirmed', confirmation_reference = ?, "
            "confirmation_pdf_path = ?, confirmation_pdf_sha256 = ?, "
            "confirmation_delivery_status = 'pending', confirmed_at = ?, "
            "last_staff_actor = ?, last_staff_action_at = ?, final_notes = ?, "
            "revision = revision + 1, "
            "updated_at = ? WHERE public_id = ? AND tenant_slug = ?",
            (
                reference, pdf_path, pdf_sha256, confirmed_at, actor_id, confirmed_at,
                str(note or "").strip(), confirmed_at, public_id, TENANT_SLUG,
            ),
        )
        _event(
            conn, public_id, "reservation_confirmed", str(row["status"]), "confirmed",
            "staff", actor_id,
            {"confirmation_reference": reference, "note_provided": note_provided},
        )
        updated = _require_case(conn, public_id)
        conn.commit()
        result = _public_row(updated)
        from agents.social import ali_reservation_v2
        if ali_reservation_v2.enabled():
            current_v2 = ali_reservation_v2.get_case(public_id)
            if current_v2["state"] == "final_approval_pending":
                current_v2 = ali_reservation_v2.transition(
                    public_id,
                    "confirmed",
                    actor_type="staff",
                    actor_id=actor_id,
                    idempotency_key="final-reservation-approved",
                    reason="staff_final_approval",
                    expected_revision=current_v2["revision"],
                )
            result["workflow_v2"] = current_v2
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_original_document_inspection(
    public_id: str,
    item: str,
    actor: str,
    expected_revision: int | None = None,
) -> dict:
    """Record the irreversible pickup inspection of one original document."""
    _tenant_slug()
    if item not in {"license", "identity"}:
        raise AliReservationError("invalid_pickup_inspection_item", 422)
    actor_id = _validate_actor(actor)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _require_case(conn, public_id)
        if row["status"] != "confirmed":
            raise AliReservationError("confirmed_reservation_required", 409)
        timestamp_column = f"original_{item}_inspected_at"
        actor_column = f"original_{item}_inspected_by"
        if row[timestamp_column]:
            conn.commit()
            return _public_row(row)
        _check_revision(row, expected_revision)
        timestamp = _iso()
        conn.execute(
            f"UPDATE ali_reservations SET {timestamp_column} = ?, {actor_column} = ?, "
            "revision = revision + 1, updated_at = ? WHERE tenant_slug = ? AND public_id = ?",
            (timestamp, actor_id, timestamp, TENANT_SLUG, public_id),
        )
        _event(
            conn,
            public_id,
            f"original_{item}_inspected",
            "confirmed",
            "confirmed",
            "staff",
            actor_id,
            {"pickup_check": item},
        )
        updated = _require_case(conn, public_id)
        conn.commit()
        return _public_row(updated)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_confirmation_delivery(
    public_id: str,
    status: str,
    *,
    actor: str = "system",
    provider_message_ids: list[str] | None = None,
    error_code: str | None = None,
    expected_revision: int | None = None,
) -> dict:
    """Record delivery separately; failure never rolls confirmation back."""
    _tenant_slug()
    if status not in DELIVERY_STATES:
        raise AliReservationError("invalid_confirmation_delivery_status", 422)
    actor_id = _validate_actor(actor)
    ids = [str(item)[:160] for item in (provider_message_ids or []) if str(item).strip()]
    if len(ids) > 20:
        raise AliReservationError("invalid_provider_message_ids", 422)
    safe_error = str(error_code or "")[:120] or None
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _require_case(conn, public_id)
        if row["status"] != "confirmed":
            raise AliReservationError("invalid_transition", 409)
        if (
            row["confirmation_delivery_status"] == status
            and json.loads(row["confirmation_provider_ids_json"] or "[]") == ids
            and (row["confirmation_delivery_error_code"] or None) == safe_error
        ):
            conn.commit()
            return _public_row(row)
        _check_revision(row, expected_revision)
        timestamp = _iso()
        conn.execute(
            "UPDATE ali_reservations SET confirmation_delivery_status = ?, "
            "confirmation_provider_ids_json = ?, confirmation_delivery_error_code = ?, "
            "revision = revision + 1, updated_at = ? WHERE public_id = ? AND tenant_slug = ?",
            (status, _json(ids), safe_error, timestamp, public_id, TENANT_SLUG),
        )
        _event(
            conn, public_id, "confirmation_delivery_updated", "confirmed", "confirmed",
            "system", actor_id, {"delivery_status": status, "provider_message_count": len(ids), "error_code": safe_error},
        )
        updated = _require_case(conn, public_id)
        conn.commit()
        return _public_row(updated)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _terminal_transition(
    public_id: str,
    target: str,
    actor: str,
    expected_revision: int | None = None,
) -> dict:
    _tenant_slug()
    if target not in {"cancelled", "superseded"}:
        raise AliReservationError("invalid_terminal_state", 422)
    actor_id = _validate_actor(actor)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _require_case(conn, public_id)
        if row["status"] == target:
            conn.commit()
            return _public_row(row)
        _check_revision(row, expected_revision)
        if row["status"] == "confirmed":
            raise AliReservationError("invalid_transition", 409)
        timestamp = _iso()
        conn.execute(
            "UPDATE ali_reservations SET status = ?, revision = revision + 1, "
            "last_staff_actor = ?, last_staff_action_at = ?, updated_at = ? "
            "WHERE public_id = ? AND tenant_slug = ?",
            (target, actor_id, timestamp, timestamp, public_id, TENANT_SLUG),
        )
        _event(
            conn, public_id, f"reservation_{target}", str(row["status"]), target,
            "staff", actor_id,
        )
        updated = _require_case(conn, public_id)
        conn.commit()
        return _public_row(updated)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cancel_reservation(public_id: str, actor: str, expected_revision: int | None = None) -> dict:
    return _terminal_transition(public_id, "cancelled", actor, expected_revision)


def supersede_reservation(public_id: str, actor: str, expected_revision: int | None = None) -> dict:
    return _terminal_transition(public_id, "superseded", actor, expected_revision)


def get_reservation_context(conversation_id: str, account_id: str | None = None) -> dict | None:
    """Return safe persisted truth for Nick's ordinary post-quote prompt."""
    _tenant_slug()
    ensure_schema()
    conn = _connection()
    try:
        query = (
            "SELECT * FROM ali_reservations WHERE tenant_slug = ? AND conversation_id = ?"
        )
        params: list[object] = [TENANT_SLUG, conversation_id]
        if account_id is not None:
            query += " AND zernio_account_id = ?"
            params.append(account_id)
        query += " ORDER BY id DESC LIMIT 1"
        row = conn.execute(query, params).fetchone()
        value = _public_row(row)
        if not value:
            return None
        allowed = {
            "public_id", "quote_public_id", "quote_snapshot_id", "quote_reference",
            "status", "availability_status", "checklist", "checklist_complete",
            "alternative_vehicle", "confirmation_reference", "confirmation_delivery_status",
            "reminder_status", "confirmed_at", "revision", "next_action",
        }
        return {key: value.get(key) for key in allowed}
    finally:
        conn.close()


def get_quote_context(conversation_id: str, account_id: str | None = None) -> dict | None:
    """Return the newest delivered quote without contact data or customer URLs."""
    _tenant_slug()
    ensure_schema()
    conn = _connection()
    try:
        query = (
            "SELECT * FROM ali_quotes WHERE conversation_id = ? AND whatsapp_status = 'accepted' "
            "AND customer_delivery_superseded_at IS NULL"
        )
        params: list[object] = [conversation_id]
        if account_id is not None:
            query += " AND zernio_account_id = ?"
            params.append(account_id)
        query += " ORDER BY id DESC LIMIT 1"
        row = conn.execute(query, params).fetchone()
        if not row:
            return None
        quote = dict(row)
        try:
            customer = json.loads(quote.get("customer_json") or "{}")
            rental = json.loads(quote.get("rental_json") or "{}")
            pricing = json.loads(quote.get("pricing_json") or "{}")
        except (ValueError, TypeError, json.JSONDecodeError):
            return None
        return {
            "public_id": quote.get("public_id"),
            "quote_snapshot_id": quote.get("quote_snapshot_id"),
            "quote_reference": quote.get("quote_reference"),
            "locale": quote.get("locale"),
            "expires_at": quote.get("expires_at"),
            "customer": {"name": customer.get("name")},
            "rental": rental,
            "pricing": pricing,
        }
    finally:
        conn.close()
