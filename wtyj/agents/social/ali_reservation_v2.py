"""Ali-only post-quote reservation state machine (Brief 291 / FRD-006).

The existing ``ali_reservations`` row remains the durable quote/reservation
anchor and rollback path.  This module adds one tenant-bound V2 projection
that owns ordering, active-client time, reminders, negative intent and the
single server-derived next action.  No customer document bytes live here.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agents.social import ali_reservation_workflow as legacy
from shared import config_loader, state_registry


TENANT_SLUG = "ali-car-rental"
WORKFLOW_VERSION = 2
DEFAULT_HOLD_SECONDS = 24 * 60 * 60
DEFAULT_REMINDER_MILESTONES = (3 * 60 * 60, 12 * 60 * 60, 21 * 60 * 60)
DEFAULT_QUIET_START = "20:30"
DEFAULT_QUIET_END = "08:30"
DEFAULT_TIMEZONE = "America/Curacao"

STATES = {
    "availability_pending",
    "availability_declined",
    "documents_collecting",
    "documents_collected",
    "document_review_pending",
    "document_replacement_required",
    "documents_approved",
    "contract_sent",
    "contract_signed",
    "prepayment_approval_pending",
    "prepayment_approved",
    "payment_link_sent",
    "customer_reports_paid",
    "payment_verified",
    "dossier_ready",
    "final_approval_pending",
    "confirmed",
    "hold_expired",
    "cancelled",
    "client_opted_out",
    "technical_attention_required",
}

TERMINAL_STATES = {
    "availability_declined",
    "confirmed",
    "hold_expired",
    "cancelled",
    "client_opted_out",
}

_ALLOWED_TRANSITIONS = {
    "availability_pending": {
        "availability_declined", "documents_collecting", "cancelled",
        "client_opted_out", "technical_attention_required",
    },
    "availability_declined": set(),
    "documents_collecting": {
        "documents_collected", "document_review_pending", "cancelled", "client_opted_out",
        "hold_expired", "technical_attention_required",
    },
    "documents_collected": {
        "contract_sent", "prepayment_approval_pending", "cancelled",
        "client_opted_out", "technical_attention_required",
    },
    "document_review_pending": {
        "documents_collected", "document_replacement_required", "documents_approved", "cancelled",
        "client_opted_out", "technical_attention_required",
    },
    "document_replacement_required": {
        "documents_collecting", "cancelled", "client_opted_out",
        "hold_expired", "technical_attention_required",
    },
    "documents_approved": {"contract_sent", "technical_attention_required"},
    "contract_sent": {
        "contract_signed", "cancelled", "client_opted_out", "hold_expired",
        "technical_attention_required",
    },
    "contract_signed": {
        "prepayment_approval_pending", "technical_attention_required",
    },
    "prepayment_approval_pending": {
        "prepayment_approved", "document_replacement_required", "cancelled",
        "client_opted_out", "technical_attention_required",
    },
    "prepayment_approved": {
        "payment_link_sent", "technical_attention_required",
    },
    "payment_link_sent": {
        "customer_reports_paid", "cancelled", "client_opted_out",
        "hold_expired", "technical_attention_required",
    },
    "customer_reports_paid": {
        "payment_verified", "payment_link_sent", "cancelled",
        "technical_attention_required",
    },
    "payment_verified": {"dossier_ready", "technical_attention_required"},
    "dossier_ready": {"final_approval_pending", "technical_attention_required"},
    "final_approval_pending": {
        "confirmed", "cancelled", "technical_attention_required",
    },
    "technical_attention_required": {
        "availability_pending", "documents_collecting",
        "documents_collected", "document_review_pending",
        "document_replacement_required", "documents_approved",
        "contract_sent", "contract_signed", "prepayment_approval_pending",
        "prepayment_approved",
        "payment_link_sent", "customer_reports_paid", "payment_verified",
        "dossier_ready", "final_approval_pending", "cancelled",
        "client_opted_out",
    },
    "confirmed": set(),
    "hold_expired": set(),
    "cancelled": set(),
    "client_opted_out": set(),
}

_STATE_RESPONSIBILITY = {
    "availability_pending": ("Staff", "paused", "availability_approval"),
    "availability_declined": ("Staff", "stopped", "availability_declined"),
    "documents_collecting": ("Client", "running", ""),
    "documents_collected": ("System", "paused", "contract_generation"),
    "document_review_pending": ("Staff", "paused", "document_review"),
    "document_replacement_required": ("Client", "running", ""),
    "documents_approved": ("System", "paused", "contract_generation"),
    "contract_sent": ("Client", "running", ""),
    "contract_signed": ("System", "paused", "prepayment_review_creation"),
    "prepayment_approval_pending": ("Staff", "paused", "prepayment_file_review"),
    "prepayment_approved": ("System", "paused", "payment_link_delivery"),
    "payment_link_sent": ("Client", "running", ""),
    "customer_reports_paid": ("Staff", "paused", "payment_verification"),
    "payment_verified": ("System", "paused", "dossier_generation"),
    "dossier_ready": ("System", "paused", "dossier_finalization"),
    "final_approval_pending": ("Staff", "paused", "final_approval"),
    "confirmed": ("System", "stopped", "confirmed"),
    "hold_expired": ("System", "stopped", "hold_expired"),
    "cancelled": ("System", "stopped", "cancelled"),
    "client_opted_out": ("System", "stopped", "client_opted_out"),
    "technical_attention_required": ("Staff", "paused", "technical_attention"),
}

_NEXT_ACTION = {
    "availability_pending": "approve_or_decline_availability",
    "availability_declined": "none",
    "documents_collecting": "send_next_document",
    "documents_collected": "generate_and_send_contract",
    "document_review_pending": "review_next_document",
    "document_replacement_required": "send_replacement_document",
    "documents_approved": "generate_and_send_contract",
    "contract_sent": "sign_contract",
    "contract_signed": "create_prepayment_review",
    "prepayment_approval_pending": "approve_prepayment_file",
    "prepayment_approved": "send_payment_link",
    "payment_link_sent": "report_payment",
    "customer_reports_paid": "verify_payment",
    "payment_verified": "generate_dossier",
    "dossier_ready": "prepare_final_approval",
    "final_approval_pending": "approve_reservation",
    "confirmed": "none",
    "hold_expired": "none",
    "cancelled": "none",
    "client_opted_out": "none",
    "technical_attention_required": "resolve_technical_attention",
}

_ID_TYPE_ALIASES = {
    "passport": {
        "passport", "my passport", "paspoort", "mein reisepass", "reisepass",
        "pasport", "mi pasport",
    },
    "id_card": {
        "id", "id card", "identity card", "national id", "identiteitskaart",
        "id kaart", "personalausweis", "ausweis", "karta di identidat",
    },
}

_GLOBAL_OPT_OUT = (
    re.compile(r"^(?:please\s+)?(?:stop messaging me|do not contact me|don't contact me|no more messages|unsubscribe|leave me alone)(?:\s+please)?$", re.I),
    re.compile(r"^(?:stop met berichten|neem geen contact meer op|geen berichten meer|uitschrijven|laat me met rust)$", re.I),
    re.compile(r"^(?:stòp manda mi mensahe|no tuma kontakto ku mi|no manda mi mas mensahe|laga mi ketu)$", re.I),
    re.compile(r"^(?:keine nachrichten mehr|kontaktieren sie mich nicht|schreib(?:en sie)? mir nicht mehr|abbestellen|lass(?:en sie)? mich in ruhe)$", re.I),
)

_RESERVATION_DECLINE = (
    re.compile(r"^(?:not interested|i(?:'m| am) not interested|i already rented (?:a car|one)|i found another car|cancel(?: it| this reservation)?|i don'?t want to continue)$", re.I),
    re.compile(r"^(?:niet geïnteresseerd|ik heb al een auto gehuurd|ik heb een andere auto gevonden|annuleer(?: dit)?|ik wil niet doorgaan)$", re.I),
    re.compile(r"^(?:mi no ta interesá|mi a huur un outo kaba|mi a haña otro outo|kanselá|mi no ke sigui)$", re.I),
    re.compile(r"^(?:nicht interessiert|ich habe bereits ein auto gemietet|ich habe ein anderes auto gefunden|stornieren|ich möchte nicht weitermachen)$", re.I),
)

_VEHICLE_REJECTION = (
    re.compile(r"^(?:i don'?t want this (?:car|vehicle)|show me (?:a |an )?(?:smaller|bigger|cheaper|different) (?:car|one)|this (?:car|suv) is too expensive)$", re.I),
    re.compile(r"^(?:ik wil deze auto niet|laat me een (?:kleinere|grotere|goedkopere|andere) auto zien|deze (?:auto|suv) is te duur)$", re.I),
    re.compile(r"^(?:mi no ke e outo aki|mustra mi un outo (?:mas chikí|mas grandi|mas barata|diferente)|e (?:outo|suv) aki ta muchu karu)$", re.I),
    re.compile(r"^(?:ich möchte dieses auto nicht|zeigen sie mir ein (?:kleineres|größeres|günstigeres|anderes) auto|dieser (?:wagen|suv) ist zu teuer)$", re.I),
)

_AMBIGUOUS_NEGATIVE = {
    "no", "not now", "i'm not sure", "i am not sure", "nee", "nu niet",
    "ik weet het niet zeker", "nò", "no awor", "mi no ta sigur", "nein",
    "nicht jetzt", "ich bin mir nicht sicher",
}

_AMBIGUOUS_MORE_TIME = {
    "give me more time", "more time", "keep it", "keep the hold",
    "geef me meer tijd", "meer tijd", "houd hem vast",
    "duna mi mas tempu", "mas tempu", "tene e reserva",
    "geben sie mir mehr zeit", "mehr zeit", "bitte weiter reservieren",
}

_AMBIGUOUS_RELEASE = {
    "release the car", "release it", "cancel the reservation",
    "geef de auto vrij", "laat hem vrij", "annuleer de reservering",
    "laga e outo liber", "laga e reserva", "kansela e reservashon",
    "auto freigeben", "geben sie das auto frei", "reservierung stornieren",
}

_TYPED_RESERVE = (
    re.compile(r"^(?:please\s+)?(?:book it|reserve it|i want this car|i(?:'d| would) like to reserve this car)(?:\s+please)?$", re.I),
    re.compile(r"^(?:boek hem|reserveer hem|ik wil deze auto|ik wil deze auto reserveren)$", re.I),
    re.compile(r"^(?:reserva e|mi ke e outo aki|mi ke reserva e outo aki)$", re.I),
    re.compile(r"^(?:buchen sie ihn|reservieren sie ihn|ich möchte dieses auto|ich möchte dieses auto reservieren)$", re.I),
)

_STRUCTURAL_PUNCTUATION = str.maketrans({
    "’": "'",
    "‘": "'",
    "ʼ": "'",
    "`": "'",
})


class AvailabilityProvider(Protocol):
    def check(self, category: str, pickup: str, return_at: str) -> dict: ...
    def hold(self, category: str, pickup: str, return_at: str, expires_at: str) -> dict: ...
    def confirm(self, hold_id: str, reservation_id: str) -> dict: ...
    def release(self, hold_id: str, reason: str) -> dict: ...
    def suggest_alternatives(self, category: str, pickup: str, return_at: str) -> list[dict]: ...


@dataclass(frozen=True)
class ManualAvailabilityProvider:
    """Provider-neutral manual adapter; staff remains the authority in V2."""

    provider_name: str = "manual"

    def check(self, category: str, pickup: str, return_at: str) -> dict:
        return {"status": "pending", "provider": self.provider_name}

    def hold(self, category: str, pickup: str, return_at: str, expires_at: str) -> dict:
        return {"status": "pending_staff_approval", "provider": self.provider_name}

    def confirm(self, hold_id: str, reservation_id: str) -> dict:
        return {"status": "approved", "provider": self.provider_name}

    def release(self, hold_id: str, reason: str) -> dict:
        return {"status": "released", "provider": self.provider_name, "reason": reason}

    def suggest_alternatives(self, category: str, pickup: str, return_at: str) -> list[dict]:
        return []


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _dt(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(state_registry.DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def enabled(raw: dict | None = None) -> bool:
    raw = raw if raw is not None else (config_loader.get_raw() or {})
    features = raw.get("features") if isinstance(raw, dict) else {}
    return bool(
        isinstance(features, dict)
        and features.get("ali_post_quote_reservation_v2_enabled", False)
        and str(raw.get("slug") or "").strip().lower() == TENANT_SLUG
        and str((raw.get("workflow") or {}).get("type") or "") == "ali_quote"
    )


def reminder_sends_enabled(raw: dict | None = None) -> bool:
    raw = raw if raw is not None else (config_loader.get_raw() or {})
    features = raw.get("features") if isinstance(raw, dict) else {}
    return bool(
        enabled(raw)
        and isinstance(features, dict)
        and features.get("ali_reservation_v2_reminders_enabled", False)
    )


def _configured_settings(raw: dict | None = None) -> dict:
    raw = raw if raw is not None else (config_loader.get_raw() or {})
    value = ((raw.get("workflow") or {}).get("post_quote") or {}).get("v2") or {}
    value = value if isinstance(value, dict) else {}
    hold_hours = value.get("hold_active_client_hours", 24)
    if isinstance(hold_hours, bool) or not isinstance(hold_hours, (int, float)):
        hold_hours = 24
    hold_seconds = max(3600, min(int(float(hold_hours) * 3600), 30 * 86400))
    raw_milestones = value.get("reminder_active_client_hours", [3, 12, 21])
    if not isinstance(raw_milestones, list):
        raw_milestones = [3, 12, 21]
    milestones = sorted({
        int(float(item) * 3600)
        for item in raw_milestones
        if not isinstance(item, bool) and isinstance(item, (int, float))
        and 0 < float(item) * 3600 < hold_seconds
    })[:3]
    return {
        "hold_seconds": hold_seconds,
        "reminder_milestones": tuple(milestones or DEFAULT_REMINDER_MILESTONES),
        "quiet_start": str(value.get("quiet_hours_start") or DEFAULT_QUIET_START),
        "quiet_end": str(value.get("quiet_hours_end") or DEFAULT_QUIET_END),
        "default_timezone": str(value.get("default_timezone") or DEFAULT_TIMEZONE),
    }


def _settings(raw: dict | None = None) -> dict:
    defaults = _configured_settings(raw)
    conn = _connection()
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='ali_reservation_v2_settings'",
        ).fetchone()
        if not exists:
            return defaults
        row = conn.execute(
            "SELECT * FROM ali_reservation_v2_settings WHERE tenant_slug = ?",
            (TENANT_SLUG,),
        ).fetchone()
        if not row:
            return defaults
        try:
            milestones = tuple(
                int(item) for item in json.loads(
                    row["reminder_milestones_json"] or "[]"
                )
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            milestones = defaults["reminder_milestones"]
        return {
            "hold_seconds": int(row["hold_seconds"]),
            "reminder_milestones": milestones,
            "quiet_start": str(row["quiet_start"]),
            "quiet_end": str(row["quiet_end"]),
            "default_timezone": str(row["default_timezone"]),
        }
    finally:
        conn.close()


def ensure_schema() -> None:
    legacy.ensure_schema()
    conn = _connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ali_reservation_v2_cases (
                reservation_public_id TEXT PRIMARY KEY,
                tenant_slug TEXT NOT NULL,
                workflow_version INTEGER NOT NULL DEFAULT 2,
                state TEXT NOT NULL,
                responsibility TEXT NOT NULL,
                clock_state TEXT NOT NULL,
                clock_pause_reason TEXT NOT NULL DEFAULT '',
                hold_started_at TEXT NOT NULL,
                client_active_seconds INTEGER NOT NULL DEFAULT 0,
                clock_started_at TEXT,
                client_timezone TEXT NOT NULL,
                reminder_milestones_json TEXT NOT NULL DEFAULT '[]',
                next_reminder_active_seconds INTEGER,
                last_client_activity_at TEXT,
                last_outbound_at TEXT,
                do_not_contact INTEGER NOT NULL DEFAULT 0,
                cancellation_reason TEXT NOT NULL DEFAULT '',
                negative_intent_pending INTEGER NOT NULL DEFAULT 0,
                identity_type TEXT NOT NULL DEFAULT '',
                expected_document_slot TEXT NOT NULL DEFAULT '',
                revision INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(reservation_public_id)
                    REFERENCES ali_reservations(public_id) ON DELETE RESTRICT
            );
            CREATE INDEX IF NOT EXISTS idx_ali_reservation_v2_state
                ON ali_reservation_v2_cases(tenant_slug, state, updated_at);

            CREATE TABLE IF NOT EXISTS ali_reservation_v2_actions (
                tenant_slug TEXT NOT NULL,
                reservation_public_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                action_type TEXT NOT NULL,
                result_state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(tenant_slug, reservation_public_id, idempotency_key),
                FOREIGN KEY(reservation_public_id)
                    REFERENCES ali_reservations(public_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS ali_reservation_v2_intents (
                public_id TEXT PRIMARY KEY,
                tenant_slug TEXT NOT NULL,
                reservation_public_id TEXT NOT NULL,
                source_message_hash TEXT NOT NULL,
                classification TEXT NOT NULL,
                decision_source TEXT NOT NULL,
                confidence TEXT NOT NULL,
                resulting_action TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(tenant_slug, reservation_public_id, source_message_hash),
                FOREIGN KEY(reservation_public_id)
                    REFERENCES ali_reservations(public_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS ali_reservation_v2_reminders (
                reservation_public_id TEXT NOT NULL,
                tenant_slug TEXT NOT NULL,
                milestone_seconds INTEGER NOT NULL,
                status TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                provider_message_ids_json TEXT NOT NULL DEFAULT '[]',
                due_at TEXT,
                sent_at TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(reservation_public_id, milestone_seconds),
                FOREIGN KEY(reservation_public_id)
                    REFERENCES ali_reservations(public_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS ali_reservation_v2_contact_preferences (
                tenant_slug TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                do_not_contact INTEGER NOT NULL DEFAULT 0,
                opted_out_at TEXT,
                source_message_hash TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(tenant_slug, conversation_id)
            );

            CREATE TABLE IF NOT EXISTS ali_reservation_v2_settings (
                tenant_slug TEXT PRIMARY KEY,
                hold_seconds INTEGER NOT NULL,
                reminder_milestones_json TEXT NOT NULL,
                quiet_start TEXT NOT NULL,
                quiet_end TEXT NOT NULL,
                default_timezone TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        configured = _configured_settings()
        timestamp = _iso()
        conn.execute(
            "INSERT OR IGNORE INTO ali_reservation_v2_settings (tenant_slug, "
            "hold_seconds, reminder_milestones_json, quiet_start, quiet_end, "
            "default_timezone, updated_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'configuration_default', ?, ?)",
            (
                TENANT_SLUG, configured["hold_seconds"],
                json.dumps(configured["reminder_milestones"]),
                configured["quiet_start"], configured["quiet_end"],
                configured["default_timezone"], timestamp, timestamp,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def tenant_settings() -> dict:
    ensure_schema()
    settings = _settings()
    return {
        "holdActiveClientHours": settings["hold_seconds"] / 3600,
        "reminderActiveClientHours": [
            seconds / 3600 for seconds in settings["reminder_milestones"]
        ],
        "quietHoursStart": settings["quiet_start"],
        "quietHoursEnd": settings["quiet_end"],
        "defaultTimezone": settings["default_timezone"],
        "reminderSendEnabled": reminder_sends_enabled(),
    }


def save_tenant_settings(
    *,
    hold_active_client_hours: object,
    reminder_active_client_hours: object,
    quiet_hours_start: object,
    quiet_hours_end: object,
    default_timezone: object,
    actor: str,
) -> dict:
    if not enabled():
        raise legacy.AliReservationError("reservation_v2_not_enabled", 409)
    actor_id = legacy._validate_actor(actor)
    if (
        isinstance(hold_active_client_hours, bool)
        or not isinstance(hold_active_client_hours, (int, float))
    ):
        raise legacy.AliReservationError("invalid_hold_hours", 422)
    hold_seconds = int(float(hold_active_client_hours) * 3600)
    if not 3600 <= hold_seconds <= 30 * 86400:
        raise legacy.AliReservationError("invalid_hold_hours", 422)
    if not isinstance(reminder_active_client_hours, list):
        raise legacy.AliReservationError("invalid_reminder_schedule", 422)
    milestones = sorted({
        int(float(item) * 3600)
        for item in reminder_active_client_hours
        if not isinstance(item, bool) and isinstance(item, (int, float))
    })
    if (
        not 1 <= len(milestones) <= 3
        or any(item <= 0 or item >= hold_seconds for item in milestones)
    ):
        raise legacy.AliReservationError("invalid_reminder_schedule", 422)
    clocks = []
    for candidate in (quiet_hours_start, quiet_hours_end):
        value = str(candidate or "").strip()
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            raise legacy.AliReservationError("invalid_quiet_hours", 422) from exc
        clocks.append(value)
    timezone_name = _validated_timezone(default_timezone)
    ensure_schema()
    timestamp = _iso()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE ali_reservation_v2_settings SET hold_seconds = ?, "
            "reminder_milestones_json = ?, quiet_start = ?, quiet_end = ?, "
            "default_timezone = ?, updated_by = ?, updated_at = ? "
            "WHERE tenant_slug = ?",
            (
                hold_seconds, json.dumps(milestones), clocks[0], clocks[1],
                timezone_name, actor_id, timestamp, TENANT_SLUG,
            ),
        )
        conn.execute(
            "UPDATE ali_reservation_v2_cases SET reminder_milestones_json = ?, "
            "next_reminder_active_seconds = ?, updated_at = ? "
            "WHERE tenant_slug = ? AND state NOT IN "
            "('confirmed','hold_expired','cancelled','client_opted_out',"
            "'availability_declined')",
            (json.dumps(milestones), milestones[0], timestamp, TENANT_SLUG),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return tenant_settings()


def _case(conn: sqlite3.Connection, public_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT v.*, r.conversation_id, r.zernio_account_id, r.quote_public_id, "
        "r.quote_snapshot_id, r.quote_reference FROM ali_reservation_v2_cases v "
        "JOIN ali_reservations r ON r.public_id = v.reservation_public_id "
        "WHERE v.tenant_slug = ? AND v.reservation_public_id = ?",
        (TENANT_SLUG, str(public_id)),
    ).fetchone()
    if not row:
        raise legacy.AliReservationError("reservation_v2_not_found", 404)
    return row


def _responsibility(state: str) -> tuple[str, str, str]:
    try:
        return _STATE_RESPONSIBILITY[state]
    except KeyError as exc:
        raise legacy.AliReservationError("invalid_v2_state", 422) from exc


def initialize_reservation(
    public_id: str,
    *,
    now: datetime | None = None,
    client_timezone: str | None = None,
) -> dict:
    """Idempotently attach the V2 state projection to an existing reservation."""
    ensure_schema()
    timestamp = _iso(now)
    settings = _settings()
    timezone_name = _validated_timezone(client_timezone or settings["default_timezone"])
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        reservation_row = conn.execute(
            "SELECT * FROM ali_reservations WHERE tenant_slug = ? AND public_id = ?",
            (TENANT_SLUG, str(public_id)),
        ).fetchone()
        if not reservation_row:
            raise legacy.AliReservationError("reservation_not_found", 404)
        existing = conn.execute(
            "SELECT 1 FROM ali_reservation_v2_cases WHERE tenant_slug = ? "
            "AND reservation_public_id = ?",
            (TENANT_SLUG, str(public_id)),
        ).fetchone()
        if not existing:
            initial_state = (
                "documents_collecting"
                if str(reservation_row["availability_status"] or "") == "approved"
                else "availability_pending"
            )
            responsibility, clock_state, pause_reason = _responsibility(initial_state)
            clock_started_at = timestamp if clock_state == "running" else None
            conn.execute(
                "INSERT INTO ali_reservation_v2_cases (reservation_public_id, "
                "tenant_slug, state, responsibility, clock_state, "
                "clock_pause_reason, hold_started_at, client_timezone, "
                "reminder_milestones_json, next_reminder_active_seconds, "
                "clock_started_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    public_id, TENANT_SLUG, initial_state, responsibility,
                    clock_state, pause_reason, timestamp, timezone_name,
                    json.dumps(settings["reminder_milestones"]),
                    settings["reminder_milestones"][0], clock_started_at,
                    timestamp, timestamp,
                ),
            )
            legacy._event(
                conn, public_id, "reservation_v2_initialized",
                initial_state, initial_state, "system",
                "reservation_v2_system",
                {
                    "workflow_version": WORKFLOW_VERSION,
                    "availability_gate": (
                        "skipped" if initial_state == "documents_collecting"
                        else "manual"
                    ),
                },
            )
        conn.commit()
        return get_case(public_id, now=now)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _validated_timezone(value: object) -> str:
    candidate = str(value or DEFAULT_TIMEZONE).strip()
    try:
        ZoneInfo(candidate)
    except ZoneInfoNotFoundError:
        return DEFAULT_TIMEZONE
    return candidate


def infer_client_timezone(phone: object, explicit: object = None) -> str:
    if explicit:
        return _validated_timezone(explicit)
    digits = re.sub(r"[^0-9]", "", str(phone or ""))
    if digits.startswith("351"):
        return "Europe/Lisbon"
    if digits.startswith("599"):
        return "America/Curacao"
    return _validated_timezone(_settings()["default_timezone"])


def _effective_active_seconds(row: sqlite3.Row | dict, now: datetime) -> int:
    value = int(row["client_active_seconds"] or 0)
    if str(row["clock_state"]) == "running":
        started = _dt(row["clock_started_at"])
        if started:
            value += max(0, int((now - started).total_seconds()))
    return value


def _public(
    row: sqlite3.Row | dict,
    now: datetime | None = None,
    settings: dict | None = None,
) -> dict:
    current = (now or _now()).astimezone(timezone.utc)
    value = dict(row)
    active = _effective_active_seconds(value, current)
    settings = settings or _settings()
    try:
        milestones = json.loads(value.get("reminder_milestones_json") or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        milestones = []
    remaining = max(0, settings["hold_seconds"] - active)
    return {
        "reservationPublicId": value["reservation_public_id"],
        "workflowVersion": int(value.get("workflow_version") or WORKFLOW_VERSION),
        "state": value["state"],
        "responsibleParty": value["responsibility"],
        "clock": {
            "state": value["clock_state"],
            "pauseReason": value["clock_pause_reason"] or None,
            "activeClientSeconds": active,
            "remainingSeconds": remaining,
            "holdSeconds": settings["hold_seconds"],
            "clientTimezone": value["client_timezone"],
        },
        "reminders": {
            "milestonesSeconds": milestones,
            "nextMilestoneSeconds": value.get("next_reminder_active_seconds"),
            "sendEnabled": reminder_sends_enabled(),
        },
        "nextAction": _NEXT_ACTION.get(str(value["state"]), "review"),
        "doNotContact": bool(value.get("do_not_contact")),
        "cancellationReason": value.get("cancellation_reason") or None,
        "negativeIntentPending": bool(value.get("negative_intent_pending")),
        "identityType": value.get("identity_type") or None,
        "expectedDocumentSlot": value.get("expected_document_slot") or None,
        "revision": int(value["revision"]),
        "lastClientActivityAt": value.get("last_client_activity_at"),
        "lastOutboundAt": value.get("last_outbound_at"),
        "createdAt": value["created_at"],
        "updatedAt": value["updated_at"],
    }


def get_case(public_id: str, *, now: datetime | None = None) -> dict:
    ensure_schema()
    conn = _connection()
    try:
        return _public(_case(conn, public_id), now)
    finally:
        conn.close()


def get_cases(
    public_ids: list[str] | set[str] | tuple[str, ...],
    *,
    now: datetime | None = None,
) -> dict[str, dict]:
    """Return tenant-scoped public cases in one read for dashboard queues."""
    normalized = sorted({str(item) for item in public_ids if str(item).strip()})
    if not normalized:
        return {}
    ensure_schema()
    placeholders = ",".join("?" for _ in normalized)
    conn = _connection()
    try:
        rows = conn.execute(
            "SELECT v.*, r.conversation_id, r.zernio_account_id, "
            "r.quote_public_id, r.quote_snapshot_id, r.quote_reference "
            "FROM ali_reservation_v2_cases v JOIN ali_reservations r "
            "ON r.public_id = v.reservation_public_id "
            f"WHERE v.tenant_slug = ? AND v.reservation_public_id IN ({placeholders})",
            (TENANT_SLUG, *normalized),
        ).fetchall()
    finally:
        conn.close()
    current = now or _now()
    settings = _settings()
    return {
        str(row["reservation_public_id"]): _public(row, current, settings)
        for row in rows
    }


def get_active_case(conversation_id: str, account_id: str) -> dict | None:
    ensure_schema()
    conn = _connection()
    try:
        row = conn.execute(
            "SELECT v.*, r.conversation_id, r.zernio_account_id, r.quote_public_id, "
            "r.quote_snapshot_id, r.quote_reference FROM ali_reservation_v2_cases v "
            "JOIN ali_reservations r ON r.public_id = v.reservation_public_id "
            "WHERE v.tenant_slug = ? AND r.conversation_id = ? "
            "AND r.zernio_account_id = ? AND v.state NOT IN "
            "('availability_declined','confirmed','hold_expired','cancelled','client_opted_out') "
            "ORDER BY v.created_at DESC LIMIT 1",
            (TENANT_SLUG, str(conversation_id), str(account_id)),
        ).fetchone()
        return _public(row) if row else None
    finally:
        conn.close()


def sync_availability_decision(
    public_id: str,
    decision: str,
    *,
    actor: str,
    legacy_revision: int,
) -> dict:
    """Reconcile an already-committed legacy staff decision into V2."""
    current = get_case(public_id)
    if decision == "approve" and current["state"] == "availability_pending":
        return transition(
            public_id,
            "documents_collecting",
            actor_type="staff",
            actor_id=actor,
            idempotency_key=f"availability:{decision}:{int(legacy_revision)}",
            reason="manual_availability_approved",
            expected_revision=current["revision"],
        )
    if decision == "decline" and current["state"] == "availability_pending":
        return transition(
            public_id,
            "availability_declined",
            actor_type="staff",
            actor_id=actor,
            idempotency_key=f"availability:{decision}:{int(legacy_revision)}",
            reason="manual_availability_declined",
            expected_revision=current["revision"],
        )
    return current


def transition(
    public_id: str,
    to_state: str,
    *,
    actor_type: str,
    actor_id: str,
    idempotency_key: str,
    reason: str = "",
    expected_revision: int | None = None,
    metadata: dict | None = None,
    now: datetime | None = None,
) -> dict:
    if to_state not in STATES:
        raise legacy.AliReservationError("invalid_v2_state", 422)
    actor = legacy._validate_actor(actor_id)
    action_key = str(idempotency_key or "").strip()
    if not action_key or len(action_key) > 240:
        raise legacy.AliReservationError("invalid_idempotency_key", 422)
    timestamp_dt = (now or _now()).astimezone(timezone.utc)
    timestamp = _iso(timestamp_dt)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _case(conn, public_id)
        receipt = conn.execute(
            "SELECT result_state FROM ali_reservation_v2_actions WHERE "
            "tenant_slug = ? AND reservation_public_id = ? AND idempotency_key = ?",
            (TENANT_SLUG, public_id, action_key),
        ).fetchone()
        if receipt:
            conn.commit()
            return _public(row, timestamp_dt)
        from_state = str(row["state"])
        if to_state == from_state:
            conn.execute(
                "INSERT INTO ali_reservation_v2_actions (idempotency_key, "
                "tenant_slug, reservation_public_id, action_type, result_state, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (action_key, TENANT_SLUG, public_id, "noop", to_state, timestamp),
            )
            conn.commit()
            return _public(row, timestamp_dt)
        if to_state not in _ALLOWED_TRANSITIONS.get(from_state, set()):
            raise legacy.AliReservationError("invalid_v2_transition", 409)
        if expected_revision is not None and int(row["revision"]) != int(expected_revision):
            raise legacy.AliReservationError("stale_reservation_revision", 409)
        active = _effective_active_seconds(row, timestamp_dt)
        responsibility, clock_state, pause_reason = _responsibility(to_state)
        clock_started_at = timestamp if clock_state == "running" else None
        hold_started_at = str(row["hold_started_at"])
        if to_state == "payment_link_sent":
            # The provider-confirmed payment link starts a fresh, full 24-hour
            # customer window. Earlier document/contract time must not reduce it.
            active = 0
            hold_started_at = timestamp
            conn.execute(
                "DELETE FROM ali_reservation_v2_reminders WHERE tenant_slug = ? "
                "AND reservation_public_id = ?",
                (TENANT_SLUG, public_id),
            )
        cancellation_reason = str(row["cancellation_reason"] or "")
        if to_state in {"cancelled", "hold_expired", "client_opted_out", "availability_declined"}:
            cancellation_reason = str(reason or to_state)[:240]
        dnc = 1 if to_state == "client_opted_out" else int(row["do_not_contact"] or 0)
        conn.execute(
            "UPDATE ali_reservation_v2_cases SET state = ?, responsibility = ?, "
            "clock_state = ?, clock_pause_reason = ?, client_active_seconds = ?, "
            "clock_started_at = ?, hold_started_at = ?, do_not_contact = ?, cancellation_reason = ?, "
            "revision = revision + 1, updated_at = ? WHERE tenant_slug = ? "
            "AND reservation_public_id = ?",
            (
                to_state, responsibility, clock_state, pause_reason, active,
                clock_started_at, hold_started_at, dnc, cancellation_reason,
                timestamp,
                TENANT_SLUG, public_id,
            ),
        )
        conn.execute(
            "INSERT INTO ali_reservation_v2_actions (idempotency_key, tenant_slug, "
            "reservation_public_id, action_type, result_state, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (action_key, TENANT_SLUG, public_id, f"transition:{to_state}", to_state, timestamp),
        )
        safe_metadata = dict(metadata or {})
        safe_metadata.update({"workflow_version": WORKFLOW_VERSION, "reason_code": str(reason or "")[:120]})
        legacy._event(
            conn, public_id, f"reservation_v2_{to_state}", from_state, to_state,
            actor_type, actor, safe_metadata,
        )
        updated = _case(conn, public_id)
        conn.commit()
        return _public(updated, timestamp_dt)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def note_client_activity(public_id: str, message_id: str, *, now: datetime | None = None) -> dict:
    timestamp = _iso(now)
    key = hashlib.sha256(str(message_id or "").encode("utf-8")).hexdigest()
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _case(conn, public_id)
        conn.execute(
            "UPDATE ali_reservation_v2_cases SET last_client_activity_at = ?, "
            "updated_at = ? WHERE tenant_slug = ? AND reservation_public_id = ?",
            (timestamp, timestamp, TENANT_SLUG, public_id),
        )
        legacy._event(
            conn, public_id, "reservation_v2_client_progress",
            str(row["state"]), str(row["state"]), "customer", "whatsapp",
            {"source_message_hash": key},
        )
        conn.commit()
        return get_case(public_id, now=now)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def note_outbound(public_id: str, *, now: datetime | None = None) -> dict:
    timestamp = _iso(now)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute(
            "UPDATE ali_reservation_v2_cases SET last_outbound_at = ?, updated_at = ? "
            "WHERE tenant_slug = ? AND reservation_public_id = ?",
            (timestamp, timestamp, TENANT_SLUG, public_id),
        )
        conn.commit()
        return get_case(public_id, now=now)
    finally:
        conn.close()


def set_identity_type(public_id: str, value: object, *, message_id: str) -> dict:
    normalized = " ".join(str(value or "").strip().casefold().split())
    identity_type = next(
        (kind for kind, aliases in _ID_TYPE_ALIASES.items() if normalized in aliases),
        "",
    )
    if not identity_type:
        raise legacy.AliReservationError("identity_type_not_recognized", 422)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _case(conn, public_id)
        if row["state"] != "documents_collecting":
            raise legacy.AliReservationError("identity_type_not_expected", 409)
        if row["identity_type"]:
            if row["identity_type"] != identity_type:
                raise legacy.AliReservationError(
                    "identity_type_change_requires_staff", 409,
                )
            # Same-choice replay is already applied. Never reset a partially
            # completed document checklist back to its first slot.
            conn.commit()
            return get_case(public_id)
        required_slots = required_document_slots(identity_type)
        if not required_slots:
            raise legacy.AliReservationError("identity_type_not_recognized", 422)
        first_slot = required_slots[0]
        conn.execute(
            "UPDATE ali_reservation_v2_cases SET identity_type = ?, "
            "expected_document_slot = ?, last_client_activity_at = ?, "
            "revision = revision + 1, updated_at = ? WHERE tenant_slug = ? "
            "AND reservation_public_id = ?",
            (identity_type, first_slot, _iso(), _iso(), TENANT_SLUG, public_id),
        )
        legacy._event(
            conn, public_id, "reservation_v2_identity_type_selected",
            str(row["state"]), str(row["state"]), "customer", "whatsapp",
            {
                "identity_type": identity_type,
                "expected_document_slot": first_slot,
                "source_message_hash": hashlib.sha256(str(message_id).encode()).hexdigest(),
            },
        )
        conn.commit()
        return get_case(public_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def required_document_slots(identity_type: str) -> tuple[str, ...]:
    if identity_type == "passport":
        return ("passport", "license_front", "license_back")
    if identity_type == "id_card":
        return ("identity_front", "identity_back", "license_front", "license_back")
    return ()


def record_document_received(
    public_id: str,
    slot: str,
    *,
    provider_message_id: str,
    now: datetime | None = None,
) -> dict:
    """Advance the one-at-a-time checklist only after durable private storage."""
    ensure_schema()
    current = (now or _now()).astimezone(timezone.utc)
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _case(conn, public_id)
        if row["state"] not in {"documents_collecting", "document_replacement_required"}:
            raise legacy.AliReservationError("document_not_expected", 409)
        if str(row["expected_document_slot"] or "") != str(slot):
            raise legacy.AliReservationError("unexpected_document_slot", 409)
        required = required_document_slots(str(row["identity_type"] or ""))
        if not required or slot not in required:
            raise legacy.AliReservationError("invalid_document_slot", 422)
        present = {
            str(item["slot"])
            for item in conn.execute(
                "SELECT slot FROM ali_reservation_documents WHERE tenant_slug = ? "
                "AND reservation_public_id = ? AND status IN ('received','verified','not_required')",
                (TENANT_SLUG, public_id),
            ).fetchall()
        }
        next_slot = next((candidate for candidate in required if candidate not in present), "")
        active = _effective_active_seconds(row, current)
        timestamp = _iso(current)
        if next_slot:
            next_state = "documents_collecting"
            responsibility, clock_state, pause_reason = _responsibility(next_state)
            clock_started_at = timestamp if clock_state == "running" else None
        else:
            reservation_row = conn.execute(
                "SELECT agreement_status FROM ali_reservations "
                "WHERE tenant_slug = ? AND public_id = ?",
                (TENANT_SLUG, public_id),
            ).fetchone()
            # A replacement requested during the consolidated review does not
            # invalidate an already signed immutable pre-contract. Once the
            # replacement is stored, return the complete file to the single
            # staff gate instead of sending or signing another contract.
            next_state = (
                "prepayment_approval_pending"
                if reservation_row
                and str(reservation_row["agreement_status"] or "") == "signed"
                else "documents_collected"
            )
            responsibility, clock_state, pause_reason = _responsibility(next_state)
            clock_started_at = None
        conn.execute(
            "UPDATE ali_reservation_v2_cases SET state = ?, responsibility = ?, "
            "clock_state = ?, clock_pause_reason = ?, client_active_seconds = ?, "
            "clock_started_at = ?, expected_document_slot = ?, "
            "last_client_activity_at = ?, revision = revision + 1, updated_at = ? "
            "WHERE tenant_slug = ? AND reservation_public_id = ?",
            (
                next_state, responsibility, clock_state, pause_reason, active,
                clock_started_at, next_slot, timestamp, timestamp,
                TENANT_SLUG, public_id,
            ),
        )
        legacy._event(
            conn, public_id, "reservation_v2_document_stored",
            str(row["state"]), next_state, "customer", "zernio_whatsapp",
            {
                "slot": slot,
                "next_slot": next_slot,
                "source_message_hash": hashlib.sha256(
                    str(provider_message_id).encode("utf-8")
                ).hexdigest(),
            },
        )
        updated = _case(conn, public_id)
        conn.commit()
        return _public(updated, current)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def request_document_replacement(
    public_id: str,
    slot: str,
    *,
    actor_id: str,
    idempotency_key: str,
) -> dict:
    """Move review back to one exact direct-WhatsApp replacement slot."""
    current = get_case(public_id)
    if current["state"] == "document_replacement_required":
        return current
    updated = transition(
        public_id,
        "document_replacement_required",
        actor_type="staff",
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        reason="document_replacement_requested",
        expected_revision=current["revision"],
        metadata={"slot": str(slot)},
    )
    ensure_schema()
    conn = _connection()
    try:
        conn.execute(
            "UPDATE ali_reservation_v2_cases SET expected_document_slot = ?, "
            "updated_at = ? WHERE tenant_slug = ? AND reservation_public_id = ?",
            (str(slot), _iso(), TENANT_SLUG, public_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_case(public_id)


def _normalize_structural_phrase(text: object) -> str:
    return " ".join(
        str(text or "")
        .translate(_STRUCTURAL_PUNCTUATION)
        .strip()
        .rstrip(".! ")
        .casefold()
        .split()
    )


def classify_structural_intent(text: object) -> dict:
    normalized = _normalize_structural_phrase(text)
    if not normalized:
        return {"classification": "none", "confidence": "none", "decisionSource": "deterministic"}
    if any(pattern.fullmatch(normalized) for pattern in _GLOBAL_OPT_OUT):
        classification = "global_opt_out"
    elif any(pattern.fullmatch(normalized) for pattern in _RESERVATION_DECLINE):
        classification = "reservation_decline"
    elif any(pattern.fullmatch(normalized) for pattern in _VEHICLE_REJECTION):
        classification = "vehicle_rejection"
    elif normalized in _AMBIGUOUS_NEGATIVE:
        classification = "ambiguous_negative"
    elif any(pattern.fullmatch(normalized) for pattern in _TYPED_RESERVE):
        classification = "typed_reserve"
    else:
        classification = "none"
    return {
        "classification": classification,
        "confidence": "high" if classification != "none" else "none",
        "decisionSource": "deterministic",
    }


def classify_ambiguous_resolution(text: object) -> str:
    normalized = _normalize_structural_phrase(text)
    if normalized in _AMBIGUOUS_MORE_TIME:
        return "more_time"
    if normalized in _AMBIGUOUS_RELEASE:
        return "release"
    return "none"


def resolve_ambiguous_negative(
    public_id: str,
    decision: str,
    *,
    source_message_id: str,
    now: datetime | None = None,
) -> dict:
    """Resolve the explicit ambiguity gate without resetting active time."""
    if decision not in {"more_time", "release"}:
        raise legacy.AliReservationError("invalid_ambiguous_resolution", 422)
    message_hash = hashlib.sha256(
        str(source_message_id or "").encode("utf-8")
    ).hexdigest()
    timestamp_dt = (now or _now()).astimezone(timezone.utc)
    timestamp = _iso(timestamp_dt)
    action_key = f"ambiguous-resolution:{message_hash}"
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _case(conn, public_id)
        receipt = conn.execute(
            "SELECT result_state FROM ali_reservation_v2_actions WHERE "
            "tenant_slug = ? AND reservation_public_id = ? AND idempotency_key = ?",
            (TENANT_SLUG, public_id, action_key),
        ).fetchone()
        if receipt:
            conn.commit()
            return {
                "case": _public(row, timestamp_dt),
                "decision": decision,
                "repeated": True,
            }
        if not bool(row["negative_intent_pending"]):
            raise legacy.AliReservationError(
                "ambiguous_resolution_not_expected", 409,
            )
        if decision == "release":
            to_state = "cancelled"
            responsibility, clock_state, pause_reason = _responsibility(to_state)
            conn.execute(
                "UPDATE ali_reservation_v2_cases SET state = ?, responsibility = ?, "
                "clock_state = ?, clock_pause_reason = ?, cancellation_reason = ?, "
                "negative_intent_pending = 0, revision = revision + 1, updated_at = ? "
                "WHERE tenant_slug = ? AND reservation_public_id = ?",
                (
                    to_state, responsibility, clock_state, pause_reason,
                    "customer_released_hold", timestamp, TENANT_SLUG, public_id,
                ),
            )
        else:
            to_state = str(row["state"])
            responsibility, clock_state, _ = _responsibility(to_state)
            if clock_state != "running":
                raise legacy.AliReservationError("more_time_not_available", 409)
            conn.execute(
                "UPDATE ali_reservation_v2_cases SET responsibility = ?, "
                "clock_state = 'running', clock_pause_reason = '', "
                "clock_started_at = ?, negative_intent_pending = 0, "
                "revision = revision + 1, updated_at = ? WHERE tenant_slug = ? "
                "AND reservation_public_id = ?",
                (responsibility, timestamp, timestamp, TENANT_SLUG, public_id),
            )
        conn.execute(
            "INSERT INTO ali_reservation_v2_actions (tenant_slug, "
            "reservation_public_id, idempotency_key, action_type, result_state, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                TENANT_SLUG, public_id, action_key,
                f"ambiguous_resolution:{decision}", to_state, timestamp,
            ),
        )
        legacy._event(
            conn, public_id, "reservation_v2_ambiguous_resolved",
            str(row["state"]), to_state, "customer", "whatsapp",
            {"decision": decision, "source_message_hash": message_hash},
        )
        updated = _case(conn, public_id)
        conn.commit()
        return {
            "case": _public(updated, timestamp_dt),
            "decision": decision,
            "repeated": False,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_negative_intent(
    public_id: str,
    classification: str,
    *,
    source_message_id: str,
    now: datetime | None = None,
) -> dict:
    if classification not in {
        "global_opt_out", "reservation_decline", "vehicle_rejection",
        "ambiguous_negative",
    }:
        raise legacy.AliReservationError("invalid_negative_intent", 422)
    source_hash = hashlib.sha256(str(source_message_id or "").encode("utf-8")).hexdigest()
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _case(conn, public_id)
        existing = conn.execute(
            "SELECT resulting_action FROM ali_reservation_v2_intents "
            "WHERE tenant_slug = ? AND reservation_public_id = ? "
            "AND source_message_hash = ?",
            (TENANT_SLUG, public_id, source_hash),
        ).fetchone()
        if existing:
            conn.commit()
            return {"case": _public(row, now), "action": existing["resulting_action"], "repeated": True}
        if classification == "global_opt_out":
            to_state, action = "client_opted_out", "acknowledge_opt_out_once"
        elif classification == "reservation_decline":
            to_state, action = "cancelled", "acknowledge_reservation_cancelled"
        elif classification == "vehicle_rejection":
            to_state, action = str(row["state"]), "route_to_change_something"
        else:
            to_state, action = str(row["state"]), "ask_release_or_more_time_once"
        current = (now or _now()).astimezone(timezone.utc)
        active = _effective_active_seconds(row, current)
        if classification in {"global_opt_out", "reservation_decline"}:
            responsibility, clock_state, pause_reason = _responsibility(to_state)
            conn.execute(
                "UPDATE ali_reservation_v2_cases SET state = ?, responsibility = ?, "
                "clock_state = ?, clock_pause_reason = ?, client_active_seconds = ?, "
                "clock_started_at = NULL, do_not_contact = ?, cancellation_reason = ?, "
                "negative_intent_pending = 0, revision = revision + 1, updated_at = ? "
                "WHERE tenant_slug = ? AND reservation_public_id = ?",
                (
                    to_state, responsibility, clock_state, pause_reason, active,
                    1 if classification == "global_opt_out" else int(row["do_not_contact"] or 0),
                    classification, _iso(current), TENANT_SLUG, public_id,
                ),
            )
        elif classification in {"vehicle_rejection", "ambiguous_negative"}:
            conn.execute(
                "UPDATE ali_reservation_v2_cases SET clock_state = 'paused', "
                "clock_pause_reason = ?, "
                "client_active_seconds = ?, clock_started_at = NULL, "
                "negative_intent_pending = 1, revision = revision + 1, "
                "updated_at = ? WHERE tenant_slug = ? AND reservation_public_id = ?",
                (
                    "vehicle_change" if classification == "vehicle_rejection"
                    else "ambiguous_negative_clarification",
                    active, _iso(current), TENANT_SLUG, public_id,
                ),
            )
        if classification == "global_opt_out":
            conn.execute(
                "INSERT INTO ali_reservation_v2_contact_preferences "
                "(tenant_slug, conversation_id, do_not_contact, opted_out_at, "
                "source_message_hash, updated_at) VALUES (?, ?, 1, ?, ?, ?) "
                "ON CONFLICT(tenant_slug, conversation_id) DO UPDATE SET "
                "do_not_contact=1, opted_out_at=excluded.opted_out_at, "
                "source_message_hash=excluded.source_message_hash, "
                "updated_at=excluded.updated_at",
                (TENANT_SLUG, row["conversation_id"], _iso(current), source_hash, _iso(current)),
            )
        conn.execute(
            "INSERT INTO ali_reservation_v2_intents (public_id, tenant_slug, "
            "reservation_public_id, source_message_hash, classification, "
            "decision_source, confidence, resulting_action, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'deterministic', 'high', ?, ?)",
            (str(uuid.uuid4()), TENANT_SLUG, public_id, source_hash, classification, action, _iso(current)),
        )
        legacy._event(
            conn, public_id, "reservation_v2_negative_intent",
            str(row["state"]), to_state, "customer", "whatsapp",
            {"classification": classification, "source_message_hash": source_hash, "resulting_action": action},
        )
        updated = _case(conn, public_id)
        conn.commit()
        return {"case": _public(updated, current), "action": action, "repeated": False}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _parse_clock(value: str) -> time:
    try:
        parsed = datetime.strptime(value, "%H:%M")
        return time(parsed.hour, parsed.minute)
    except ValueError:
        return time(20, 30) if value == _settings()["quiet_start"] else time(8, 30)


def in_quiet_hours(now: datetime, timezone_name: str, *, start: str | None = None, end: str | None = None) -> bool:
    settings = _settings()
    local = now.astimezone(ZoneInfo(_validated_timezone(timezone_name)))
    start_time = _parse_clock(start or settings["quiet_start"])
    end_time = _parse_clock(end or settings["quiet_end"])
    current = local.time().replace(tzinfo=None)
    return current >= start_time or current < end_time


def record_customer_delivery_result(
    public_id: str,
    delivery_type: str,
    *,
    sent: bool,
    now: datetime | None = None,
) -> dict:
    """Persist provider-confirmed V2 delivery without advancing workflow state."""
    if delivery_type not in {"documents_prompt"}:
        raise legacy.AliReservationError("invalid_v2_delivery_type", 422)
    timestamp = _iso(now)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _case(conn, public_id)
        if sent:
            conn.execute(
                "INSERT OR IGNORE INTO ali_reservation_v2_actions (tenant_slug, "
                "reservation_public_id, idempotency_key, action_type, "
                "result_state, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    TENANT_SLUG,
                    public_id,
                    f"ali-v2-{delivery_type}:{public_id}",
                    f"{delivery_type}:sent",
                    str(row["state"]),
                    timestamp,
                ),
            )
        legacy._event(
            conn,
            public_id,
            (
                f"reservation_v2_{delivery_type}_sent"
                if sent
                else f"reservation_v2_{delivery_type}_failed"
            ),
            str(row["state"]),
            str(row["state"]),
            "system",
            "customer_requirement_delivery",
            {"provider_confirmed": bool(sent)},
        )
        conn.commit()
        return get_case(public_id, now=now)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reminder_plan(*, now: datetime | None = None) -> list[dict]:
    """Return due plans without sending. Delivery is a separately claimed job."""
    current = (now or _now()).astimezone(timezone.utc)
    settings = _settings()
    ensure_schema()
    conn = _connection()
    plans: list[dict] = []
    try:
        document_prompts = conn.execute(
            "SELECT v.reservation_public_id FROM ali_reservation_v2_cases v "
            "JOIN ali_reservations r ON r.public_id = v.reservation_public_id "
            "WHERE v.tenant_slug = ? AND v.state = 'documents_collecting' "
            "AND r.identity_status = 'requested' AND v.identity_type = '' "
            "AND v.do_not_contact = 0 AND NOT EXISTS ("
            "SELECT 1 FROM ali_reservation_v2_actions a WHERE "
            "a.tenant_slug = v.tenant_slug AND "
            "a.reservation_public_id = v.reservation_public_id AND "
            "a.action_type = 'documents_prompt:sent')",
            (TENANT_SLUG,),
        ).fetchall()
        plans.extend({
            "kind": "documents_prompt",
            "reservationPublicId": row["reservation_public_id"],
            "idempotencyKey": (
                f"ali-v2-documents-prompt:{row['reservation_public_id']}"
            ),
        } for row in document_prompts)
        expired = conn.execute(
            "SELECT v.reservation_public_id FROM ali_reservation_v2_cases v "
            "WHERE v.tenant_slug = ? AND v.state = 'hold_expired' "
            "AND v.do_not_contact = 0 AND NOT EXISTS ("
            "SELECT 1 FROM ali_reservation_v2_actions a WHERE "
            "a.tenant_slug = v.tenant_slug AND "
            "a.reservation_public_id = v.reservation_public_id AND "
            "a.action_type = 'hold_expiry_closure:sent')",
            (TENANT_SLUG,),
        ).fetchall()
        plans.extend({
            "kind": "expiry_closure",
            "reservationPublicId": row["reservation_public_id"],
            "idempotencyKey": (
                f"ali-v2-expiry-closure:{row['reservation_public_id']}"
            ),
        } for row in expired)
        rows = conn.execute(
            "SELECT v.*, r.conversation_id, r.zernio_account_id, r.quote_public_id, "
            "r.quote_snapshot_id, r.quote_reference FROM ali_reservation_v2_cases v "
            "JOIN ali_reservations r ON r.public_id = v.reservation_public_id "
            "WHERE v.tenant_slug = ? AND v.clock_state = 'running' "
            "AND v.do_not_contact = 0 AND v.state NOT IN "
            "('confirmed','hold_expired','cancelled','client_opted_out','availability_declined')",
            (TENANT_SLUG,),
        ).fetchall()
        for row in rows:
            active = _effective_active_seconds(row, current)
            if active >= settings["hold_seconds"]:
                plans.append({
                    "kind": "expire", "reservationPublicId": row["reservation_public_id"],
                    "idempotencyKey": f"ali-v2-expire:{row['reservation_public_id']}",
                    "nextAction": _NEXT_ACTION.get(str(row["state"]), "review"),
                })
                continue
            if in_quiet_hours(current, str(row["client_timezone"])):
                continue
            try:
                milestones = [int(item) for item in json.loads(row["reminder_milestones_json"] or "[]")]
            except (TypeError, ValueError, json.JSONDecodeError):
                milestones = list(settings["reminder_milestones"])
            sent = {
                int(item[0]) for item in conn.execute(
                    "SELECT milestone_seconds FROM ali_reservation_v2_reminders "
                    "WHERE tenant_slug = ? AND reservation_public_id = ? AND status = 'sent'",
                    (TENANT_SLUG, row["reservation_public_id"]),
                ).fetchall()
            }
            due = [milestone for milestone in milestones if milestone <= active and milestone not in sent]
            if not due:
                continue
            milestone = max(due)
            last_sent = conn.execute(
                "SELECT sent_at FROM ali_reservation_v2_reminders WHERE tenant_slug = ? "
                "AND reservation_public_id = ? AND status = 'sent' ORDER BY sent_at DESC LIMIT 1",
                (TENANT_SLUG, row["reservation_public_id"]),
            ).fetchone()
            if last_sent and _dt(last_sent["sent_at"]) and current - _dt(last_sent["sent_at"]) < timedelta(hours=3):
                continue
            plans.append({
                "kind": "reminder",
                "reservationPublicId": row["reservation_public_id"],
                "milestoneSeconds": milestone,
                "idempotencyKey": f"ali-v2-reminder:{row['reservation_public_id']}:{milestone}",
                "nextAction": _NEXT_ACTION.get(str(row["state"]), "review"),
                "activeClientSeconds": active,
                "remainingSeconds": settings["hold_seconds"] - active,
            })
        return plans
    finally:
        conn.close()


def record_reminder_result(plan: dict, *, sent: bool, provider_ids: list[str] | None = None, now: datetime | None = None) -> dict:
    if plan.get("kind") != "reminder":
        raise legacy.AliReservationError("invalid_reminder_plan", 422)
    public_id = str(plan.get("reservationPublicId") or "")
    milestone = int(plan.get("milestoneSeconds") or 0)
    key = str(plan.get("idempotencyKey") or "")
    timestamp = _iso(now)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _case(conn, public_id)
        conn.execute(
            "INSERT INTO ali_reservation_v2_reminders (reservation_public_id, "
            "tenant_slug, milestone_seconds, status, idempotency_key, "
            "provider_message_ids_json, sent_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(reservation_public_id, milestone_seconds) DO UPDATE SET "
            "status=CASE WHEN ali_reservation_v2_reminders.status='sent' THEN 'sent' ELSE excluded.status END, "
            "provider_message_ids_json=CASE WHEN ali_reservation_v2_reminders.status='sent' "
            "THEN ali_reservation_v2_reminders.provider_message_ids_json ELSE excluded.provider_message_ids_json END, "
            "sent_at=COALESCE(ali_reservation_v2_reminders.sent_at, excluded.sent_at), "
            "updated_at=excluded.updated_at",
            (
                public_id, TENANT_SLUG, milestone, "sent" if sent else "failed", key,
                json.dumps([str(item) for item in (provider_ids or [])[:10]]),
                timestamp if sent else None, timestamp,
            ),
        )
        if sent:
            settings = _settings()
            next_milestone = next(
                (item for item in settings["reminder_milestones"] if item > milestone),
                None,
            )
            conn.execute(
                "UPDATE ali_reservation_v2_cases SET next_reminder_active_seconds = ?, "
                "last_outbound_at = ?, updated_at = ? WHERE tenant_slug = ? "
                "AND reservation_public_id = ?",
                (next_milestone, timestamp, timestamp, TENANT_SLUG, public_id),
            )
        legacy._event(
            conn, public_id,
            "reservation_v2_reminder_sent" if sent else "reservation_v2_reminder_failed",
            str(row["state"]), str(row["state"]), "system", "reminder_scheduler",
            {"milestone_seconds": milestone, "next_action": plan.get("nextAction")},
        )
        conn.commit()
        return get_case(public_id, now=now)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def expire_due_case(plan: dict, *, now: datetime | None = None) -> dict:
    if plan.get("kind") != "expire":
        raise legacy.AliReservationError("invalid_expiry_plan", 422)
    return transition(
        str(plan["reservationPublicId"]), "hold_expired", actor_type="system",
        actor_id="active_client_clock", idempotency_key=str(plan["idempotencyKey"]),
        reason="active_client_time_exhausted", now=now,
    )


def record_expiry_closure_result(
    plan: dict,
    *,
    sent: bool,
    now: datetime | None = None,
) -> dict:
    if plan.get("kind") not in {"expire", "expiry_closure"}:
        raise legacy.AliReservationError("invalid_expiry_closure_plan", 422)
    public_id = str(plan.get("reservationPublicId") or "")
    timestamp = _iso(now)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _case(conn, public_id)
        if row["state"] != "hold_expired":
            raise legacy.AliReservationError("hold_expiry_closure_not_expected", 409)
        if sent:
            conn.execute(
                "INSERT OR IGNORE INTO ali_reservation_v2_actions (tenant_slug, "
                "reservation_public_id, idempotency_key, action_type, "
                "result_state, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    TENANT_SLUG, public_id, str(plan["idempotencyKey"]),
                    "hold_expiry_closure:sent", "hold_expired", timestamp,
                ),
            )
        legacy._event(
            conn, public_id,
            (
                "reservation_v2_expiry_closure_sent"
                if sent else "reservation_v2_expiry_closure_failed"
            ),
            "hold_expired", "hold_expired", "system", "active_client_clock",
            {"provider_confirmed": bool(sent)},
        )
        conn.commit()
        return get_case(public_id, now=now)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
