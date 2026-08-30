"""Meta-safe Ali pre-reservation WhatsApp follow-ups (Brief 317).

Only customer-initiated conversations created after feature activation are
eligible.  Every reminder is anchored to the latest inbound message and is
fail-closed before WhatsApp's 24-hour customer-service window ends.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from shared import config_loader, state_registry


TENANT_SLUG = "ali-car-rental"
DEFAULT_TIMEZONE = "America/Curacao"
DEFAULT_QUIET_START = "20:30"
DEFAULT_QUIET_END = "08:30"
MAX_FREE_FORM_WINDOW_SECONDS = 24 * 60 * 60
WINDOW_SAFETY_SECONDS = 10 * 60
SUPPORTED_LOCALES = {"en", "nl", "pap", "de"}
TERMINAL_DELIVERY_STATUSES = {"sent", "skipped_window", "cancelled"}
_SCHEMA_READY_PATHS: set[str] = set()


def _now(value: datetime | None = None) -> datetime:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return _now(value).isoformat()


def _dt(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(
            str(value or "").replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(state_registry.DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def enabled(raw: dict | None = None) -> bool:
    raw = raw if raw is not None else (config_loader.get_raw() or {})
    features = raw.get("features") if isinstance(raw, dict) else {}
    return bool(
        isinstance(features, dict)
        and features.get("ali_pre_reservation_reminders_enabled", False)
        and str(raw.get("slug") or "").strip().lower() == TENANT_SLUG
        and str((raw.get("workflow") or {}).get("type") or "") == "ali_quote"
    )


def _settings(raw: dict | None = None) -> dict:
    raw = raw if raw is not None else (config_loader.get_raw() or {})
    workflow = raw.get("workflow") if isinstance(raw, dict) else {}
    value = (workflow or {}).get("pre_reservation_follow_up") or {}
    value = value if isinstance(value, dict) else {}
    raw_hours = value.get("reminder_hours") or [3, 8, 22]
    milestones = sorted({
        int(float(item) * 3600)
        for item in raw_hours
        if not isinstance(item, bool)
        and isinstance(item, (int, float))
        and 0 < float(item) < 24
    })[:3]
    copies = value.get("messages") or {}
    copies = copies if isinstance(copies, dict) else {}
    return {
        "milestones": tuple(milestones),
        "quiet_start": str(value.get("quiet_hours_start") or DEFAULT_QUIET_START),
        "quiet_end": str(value.get("quiet_hours_end") or DEFAULT_QUIET_END),
        "default_timezone": str(value.get("default_timezone") or DEFAULT_TIMEZONE),
        "messages": copies,
    }


def ensure_schema(*, now: datetime | None = None) -> None:
    schema_path = str(state_registry.DB_PATH)
    if schema_path in _SCHEMA_READY_PATHS:
        return
    from agents.social import ali_reservation_workflow

    ali_reservation_workflow.ensure_schema()
    timestamp = _iso(now)
    conn = _connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ali_lead_follow_up_policy (
                tenant_slug TEXT PRIMARY KEY,
                activated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ali_lead_follow_up_deliveries (
                tenant_slug TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                anchor_message_id TEXT NOT NULL,
                milestone_seconds INTEGER NOT NULL,
                status TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                due_at TEXT NOT NULL,
                window_expires_at TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 1,
                provider_message_ids_json TEXT NOT NULL DEFAULT '[]',
                sent_at TEXT,
                last_error_code TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (
                    tenant_slug, conversation_id,
                    anchor_message_id, milestone_seconds
                )
            );
            CREATE INDEX IF NOT EXISTS idx_ali_lead_follow_up_status
                ON ali_lead_follow_up_deliveries (
                    tenant_slug, status, due_at
                );
            CREATE TABLE IF NOT EXISTS ali_lead_follow_up_preferences (
                tenant_slug TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                do_not_contact INTEGER NOT NULL DEFAULT 0,
                opted_out_at TEXT,
                source TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_slug, conversation_id)
            );
            CREATE TABLE IF NOT EXISTS ali_lead_follow_up_actions (
                tenant_slug TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                anchor_message_id TEXT NOT NULL,
                action TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (
                    tenant_slug, conversation_id, anchor_message_id
                )
            );
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO ali_lead_follow_up_policy "
            "(tenant_slug, activated_at) VALUES (?, ?)",
            (TENANT_SLUG, timestamp),
        )
        conn.commit()
        _SCHEMA_READY_PATHS.add(schema_path)
    finally:
        conn.close()


def _timezone(value: object) -> ZoneInfo:
    try:
        return ZoneInfo(str(value or DEFAULT_TIMEZONE))
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TIMEZONE)


def _clock(value: object, fallback: str) -> time:
    try:
        return datetime.strptime(str(value or fallback), "%H:%M").time()
    except ValueError:
        return datetime.strptime(fallback, "%H:%M").time()


def _in_quiet_hours(current: datetime, timezone_name: object, settings: dict) -> bool:
    local_time = current.astimezone(_timezone(timezone_name)).time().replace(tzinfo=None)
    start = _clock(settings["quiet_start"], DEFAULT_QUIET_START)
    end = _clock(settings["quiet_end"], DEFAULT_QUIET_END)
    if start == end:
        return False
    if start < end:
        return start <= local_time < end
    return local_time >= start or local_time < end


def _message_for(settings: dict, locale: object, milestone: int) -> str:
    language = str(locale or "en").lower().split("-", 1)[0]
    language = language if language in SUPPORTED_LOCALES else "en"
    messages = settings.get("messages") or {}
    localized = messages.get(language) or messages.get("en") or {}
    localized = localized if isinstance(localized, dict) else {}
    hour_key = str(int(milestone / 3600))
    return str(localized.get(hour_key) or "").strip()


def _event_context(conn: sqlite3.Connection, conversation_id: str, user_created_at: str) -> dict:
    row = conn.execute(
        "SELECT message_id, payload_json, created_at FROM inbound_processing_events "
        "WHERE conversation_id = ? AND channel = 'whatsapp' AND created_at <= ? "
        "ORDER BY created_at DESC LIMIT 1",
        (conversation_id, user_created_at),
    ).fetchone()
    if not row:
        return {}
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    provider_time = _dt(payload.get("sent_at"))
    received_time = _dt(row["created_at"])
    user_time = _dt(user_created_at)
    safe_anchor = min(
        (item for item in (provider_time, received_time, user_time) if item),
        default=None,
    )
    return {
        "message_id": str(payload.get("message_id") or row["message_id"] or ""),
        "account_id": str(payload.get("account_id") or ""),
        "sender_id": str(payload.get("sender_id") or ""),
        "anchor_at": safe_anchor,
        "provider_sent_at": str(payload.get("sent_at") or ""),
    }


def _latest_candidates(conn: sqlite3.Connection, activated_at: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT user.id AS user_row_id, user.phone, user.created_at, "
        "user.source_message_key, state.fields_json, state.flags_json "
        "FROM whatsapp_threads AS user "
        "JOIN whatsapp_booking_state AS state ON state.phone = user.phone "
        "WHERE user.role = 'user' AND user.channel = 'whatsapp' "
        "AND user.created_at >= ? "
        "AND user.id = (SELECT MAX(latest_user.id) FROM whatsapp_threads latest_user "
        " WHERE latest_user.phone = user.phone AND latest_user.role = 'user' "
        " AND latest_user.channel = 'whatsapp') "
        "AND 'assistant' = (SELECT latest.role FROM whatsapp_threads latest "
        " WHERE latest.phone = user.phone ORDER BY latest.id DESC LIMIT 1) "
        "AND NOT EXISTS (SELECT 1 FROM ali_reservations reservation "
        " WHERE reservation.conversation_id = user.phone) "
        "AND NOT EXISTS (SELECT 1 FROM ali_lead_follow_up_preferences preference "
        " WHERE preference.tenant_slug = ? AND preference.conversation_id = user.phone "
        " AND preference.do_not_contact = 1) "
        "AND NOT EXISTS (SELECT 1 FROM inbound_processing_events inbound "
        " WHERE inbound.conversation_id = user.phone "
        " AND inbound.status IN ('received','processing','recovering'))",
        (activated_at, TENANT_SLUG),
    ).fetchall()


def _record_terminal_skip(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    anchor_message_id: str,
    milestone: int,
    due_at: datetime,
    expires_at: datetime,
    status: str,
    now: datetime,
) -> None:
    key = hashlib.sha256(
        f"{TENANT_SLUG}:{conversation_id}:{anchor_message_id}:{milestone}".encode()
    ).hexdigest()
    conn.execute(
        "INSERT INTO ali_lead_follow_up_deliveries "
        "(tenant_slug, conversation_id, anchor_message_id, milestone_seconds, "
        "status, idempotency_key, due_at, window_expires_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(tenant_slug, conversation_id, anchor_message_id, milestone_seconds) "
        "DO UPDATE SET status=excluded.status, last_error_code='', "
        "updated_at=excluded.updated_at WHERE status != 'sent'",
        (
            TENANT_SLUG, conversation_id, anchor_message_id, milestone,
            status, key, _iso(due_at), _iso(expires_at), _iso(now), _iso(now),
        ),
    )


def claim_due_follow_ups(*, now: datetime | None = None) -> list[dict]:
    """Claim at most one due reminder per eligible conversation."""
    if not enabled():
        return []
    current = _now(now)
    settings = _settings()
    if not settings["milestones"]:
        return []
    ensure_schema(now=current)
    conn = _connection()
    plans = []
    try:
        conn.execute("BEGIN IMMEDIATE")
        stale_before = current - timedelta(minutes=5)
        conn.execute(
            "UPDATE ali_lead_follow_up_deliveries SET status='failed', "
            "last_error_code='stale_claim', updated_at=? "
            "WHERE tenant_slug=? AND status='sending' AND updated_at < ? "
            "AND attempt_count < 3",
            (_iso(current), TENANT_SLUG, _iso(stale_before)),
        )
        policy = conn.execute(
            "SELECT activated_at FROM ali_lead_follow_up_policy WHERE tenant_slug = ?",
            (TENANT_SLUG,),
        ).fetchone()
        activated_at = str(policy["activated_at"])
        for row in _latest_candidates(conn, activated_at):
            conversation_id = str(row["phone"])
            if state_registry.get_ai_muted(conversation_id) or state_registry.get_blocked(conversation_id):
                continue
            try:
                fields = json.loads(row["fields_json"] or "{}")
                flags = json.loads(row["flags_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if flags.get("fully_escalated") or flags.get("awaiting_relay"):
                continue
            event = _event_context(conn, conversation_id, str(row["created_at"]))
            anchor_at = event.get("anchor_at")
            account_id = str(event.get("account_id") or "")
            anchor_message_id = str(event.get("message_id") or row["source_message_key"] or row["user_row_id"])
            if not anchor_at or not account_id:
                continue
            expires_at = anchor_at + timedelta(
                seconds=MAX_FREE_FORM_WINDOW_SECONDS - WINDOW_SAFETY_SECONDS
            )
            existing = {
                int(item["milestone_seconds"]): str(item["status"])
                for item in conn.execute(
                    "SELECT milestone_seconds, status FROM ali_lead_follow_up_deliveries "
                    "WHERE tenant_slug = ? AND conversation_id = ? AND anchor_message_id = ?",
                    (TENANT_SLUG, conversation_id, anchor_message_id),
                ).fetchall()
            }
            due = [
                milestone for milestone in settings["milestones"]
                if anchor_at + timedelta(seconds=milestone) <= current
                and existing.get(milestone) not in TERMINAL_DELIVERY_STATUSES
                and existing.get(milestone) != "sending"
            ]
            if not due:
                continue
            if current > expires_at:
                for milestone in due:
                    _record_terminal_skip(
                        conn,
                        conversation_id=conversation_id,
                        anchor_message_id=anchor_message_id,
                        milestone=milestone,
                        due_at=anchor_at + timedelta(seconds=milestone),
                        expires_at=expires_at,
                        status="skipped_window",
                        now=current,
                    )
                continue
            timezone_name = DEFAULT_TIMEZONE
            try:
                from agents.social import ali_reservation_v2
                timezone_name = ali_reservation_v2.infer_client_timezone(
                    event.get("sender_id"), settings["default_timezone"],
                )
            except Exception:
                timezone_name = settings["default_timezone"]
            if _in_quiet_hours(current, timezone_name, settings):
                continue
            milestone = max(due)
            for superseded in (item for item in due if item < milestone):
                _record_terminal_skip(
                    conn,
                    conversation_id=conversation_id,
                    anchor_message_id=anchor_message_id,
                    milestone=superseded,
                    due_at=anchor_at + timedelta(seconds=superseded),
                    expires_at=expires_at,
                    status="cancelled",
                    now=current,
                )
            message = _message_for(
                settings, fields.get("conversation_language"), milestone,
            )
            if not message:
                continue
            key = hashlib.sha256(
                f"{TENANT_SLUG}:{conversation_id}:{anchor_message_id}:{milestone}".encode()
            ).hexdigest()
            due_at = anchor_at + timedelta(seconds=milestone)
            conn.execute(
                "INSERT INTO ali_lead_follow_up_deliveries "
                "(tenant_slug, conversation_id, anchor_message_id, milestone_seconds, "
                "status, idempotency_key, due_at, window_expires_at, attempt_count, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, 'sending', ?, ?, ?, 1, ?, ?) "
                "ON CONFLICT(tenant_slug, conversation_id, anchor_message_id, milestone_seconds) "
                "DO UPDATE SET status='sending', attempt_count=attempt_count+1, "
                "updated_at=excluded.updated_at WHERE status='failed' AND attempt_count < 3",
                (
                    TENANT_SLUG, conversation_id, anchor_message_id, milestone,
                    key, _iso(due_at), _iso(expires_at), _iso(current), _iso(current),
                ),
            )
            claimed = conn.execute(
                "SELECT status, attempt_count FROM ali_lead_follow_up_deliveries "
                "WHERE tenant_slug = ? AND conversation_id = ? "
                "AND anchor_message_id = ? AND milestone_seconds = ?",
                (TENANT_SLUG, conversation_id, anchor_message_id, milestone),
            ).fetchone()
            if claimed and claimed["status"] == "sending":
                plans.append({
                    "conversationId": conversation_id,
                    "accountId": account_id,
                    "anchorMessageId": anchor_message_id,
                    "latestInboundAt": event.get("provider_sent_at") or _iso(anchor_at),
                    "milestoneSeconds": milestone,
                    "message": message,
                    "idempotencyKey": f"ali-lead-follow-up:{key}",
                    "windowExpiresAt": _iso(expires_at),
                })
        conn.commit()
        return plans
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_delivery_result(
    plan: dict,
    *,
    status: str,
    error_code: str = "",
    provider_message_ids: list[str] | None = None,
    now: datetime | None = None,
) -> None:
    if status not in {"sent", "failed", "skipped_window"}:
        raise ValueError("invalid lead follow-up delivery status")
    conn = _connection()
    try:
        conn.execute(
            "UPDATE ali_lead_follow_up_deliveries SET status = ?, "
            "provider_message_ids_json = ?, sent_at = ?, last_error_code = ?, "
            "updated_at = ? WHERE tenant_slug = ? AND conversation_id = ? "
            "AND anchor_message_id = ? AND milestone_seconds = ?",
            (
                status,
                json.dumps([str(item) for item in (provider_message_ids or [])[:10]]),
                _iso(now) if status == "sent" else None,
                str(error_code or "")[:120], _iso(now), TENANT_SLUG,
                str(plan.get("conversationId") or ""),
                str(plan.get("anchorMessageId") or ""),
                int(plan.get("milestoneSeconds") or 0),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def pending_reply_context(conversation_id: str) -> dict | None:
    if not enabled():
        return None
    ensure_schema()
    conn = _connection()
    try:
        row = conn.execute(
            "SELECT anchor_message_id, milestone_seconds, sent_at FROM "
            "ali_lead_follow_up_deliveries WHERE tenant_slug = ? "
            "AND conversation_id = ? AND status = 'sent' "
            "ORDER BY sent_at DESC LIMIT 1",
            (TENANT_SLUG, str(conversation_id)),
        ).fetchone()
        if not row:
            return None
        latest_user = conn.execute(
            "SELECT created_at FROM whatsapp_threads WHERE phone = ? "
            "AND role = 'user' ORDER BY id DESC LIMIT 1",
            (str(conversation_id),),
        ).fetchone()
        latest_user_at = _dt(latest_user["created_at"]) if latest_user else None
        sent_at = _dt(row["sent_at"])
        if not latest_user_at or not sent_at or latest_user_at <= sent_at:
            return None
        action_exists = conn.execute(
            "SELECT 1 FROM ali_lead_follow_up_actions WHERE tenant_slug = ? "
            "AND conversation_id = ? AND anchor_message_id = ?",
            (TENANT_SLUG, str(conversation_id), str(row["anchor_message_id"])),
        ).fetchone()
        if action_exists:
            return None
        return {
            "anchor_message_id": str(row["anchor_message_id"]),
            "milestone_hours": int(row["milestone_seconds"]) / 3600,
        }
    finally:
        conn.close()


def record_customer_action(
    conversation_id: str,
    context: dict,
    action: object,
    *,
    now: datetime | None = None,
) -> None:
    value = str(action or "none").strip().lower()
    if value not in {"continue", "stop", "none"}:
        return
    ensure_schema(now=now)
    timestamp = _iso(now)
    anchor = str((context or {}).get("anchor_message_id") or "")
    if not anchor:
        return
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO ali_lead_follow_up_actions "
            "(tenant_slug, conversation_id, anchor_message_id, action, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (TENANT_SLUG, str(conversation_id), anchor, value, timestamp),
        )
        if value == "stop":
            conn.execute(
                "INSERT INTO ali_lead_follow_up_preferences "
                "(tenant_slug, conversation_id, do_not_contact, opted_out_at, source, updated_at) "
                "VALUES (?, ?, 1, ?, 'customer_reply', ?) "
                "ON CONFLICT(tenant_slug, conversation_id) DO UPDATE SET "
                "do_not_contact=1, opted_out_at=excluded.opted_out_at, "
                "source=excluded.source, updated_at=excluded.updated_at",
                (TENANT_SLUG, str(conversation_id), timestamp, timestamp),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
