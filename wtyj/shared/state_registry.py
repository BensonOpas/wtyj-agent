# bluemarlin/shared/state_registry.py
# Last modified: Brief 098
# Purpose: SQLite WAL deduplication, capacity, manifests, bookings
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "state_registry.db"
)

# Brief 217: optional callback set by dashboard.api at module-import time.
# `dashboard.api` registers `_fire_escalation_alerts` here so that
# create_pending_notification can fire alerts WITHOUT state_registry
# having to import dashboard.api (would create a circular import).
# When None, alert dispatch is silently skipped (e.g., state_registry
# helper unit tests that don't load the dashboard router).
_alert_dispatcher = None

# Brief 227: dashboard.api registers a summary generator here. Mirrors the
# Brief 217 alert-dispatcher pattern — one global, set once at module-load,
# called best-effort with try/except gating so a Claude failure never blocks
# escalation row creation.
_summary_dispatcher = None


def set_summary_dispatcher(fn):
    """Brief 227: register the summary generator (typically dashboard.api's
    _generate_escalation_summary)."""
    global _summary_dispatcher
    _summary_dispatcher = fn


def set_alert_dispatcher(fn):
    """Brief 217: dashboard.api registers _fire_escalation_alerts here at
    import time. Decoupled callback so state_registry doesn't import
    dashboard."""
    global _alert_dispatcher
    _alert_dispatcher = fn


# Brief 241: optional callback set by dashboard.api at module-import time.
# dashboard.api registers _fire_appointment_alerts here so that
# appointment_upsert can fire alerts WITHOUT state_registry having to
# import dashboard.api (would create a circular import). When None,
# appointment alert dispatch is silently skipped.
_appointment_alert_dispatcher = None


def set_appointment_alert_dispatcher(fn):
    """Brief 241: dashboard.api registers _fire_appointment_alerts here at
    import time. Decoupled callback so state_registry doesn't import
    dashboard."""
    global _appointment_alert_dispatcher
    _appointment_alert_dispatcher = fn


def _summaries_materially_differ(old: dict, new: dict) -> bool:
    """Brief 239: compare two escalation_summary dicts; return True only
    if operator-relevant content has changed (proposed times, latest
    customer message, or what the customer wants). Used to suppress
    duplicate update alert emails when the summary regenerated but the
    situation didn't actually change for the operator.

    Returns True when the dicts differ on customerWants OR
    latestCustomerMessage OR extractedDetails.proposedTimes. Returns
    False when all three match. Returns True (defensive: fire alert) if
    either input is not a dict."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return True
    if old.get("customerWants") != new.get("customerWants"):
        return True
    if old.get("latestCustomerMessage") != new.get("latestCustomerMessage"):
        return True
    _o = (old.get("extractedDetails") or {}).get("proposedTimes") or []
    _n = (new.get("extractedDetails") or {}).get("proposedTimes") or []
    if list(_o) != list(_n):
        return True
    return False


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    # Schema migration: rename trip_bookings → service_bookings + columns
    try:
        conn.execute("ALTER TABLE trip_bookings RENAME TO service_bookings")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE service_bookings RENAME COLUMN trip_key TO service_key")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE service_bookings RENAME COLUMN departure_time TO slot_time")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE manifest_events RENAME COLUMN trip_key TO service_key")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE manifest_events RENAME COLUMN departure_time TO slot_time")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE bookings RENAME COLUMN trip_key TO service_key")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE bookings RENAME COLUMN departure_time TO slot_time")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE photo_library RENAME COLUMN trip_key TO service_key")
    except sqlite3.OperationalError:
        pass
    conn.execute(
        "CREATE TABLE IF NOT EXISTS processed_hashes ("
        "hash TEXT PRIMARY KEY, "
        "created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS service_bookings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "service_key TEXT NOT NULL, "
        "date TEXT NOT NULL, "
        "slot_time TEXT NOT NULL, "
        "guests INTEGER NOT NULL, "
        "booking_ref TEXT, "
        "status TEXT DEFAULT 'soft_hold', "
        "expires_at TEXT, "
        "created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_service_bookings_lookup "
        "ON service_bookings(service_key, date, slot_time, status)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS manifest_events ("
        "service_key TEXT NOT NULL, "
        "date TEXT NOT NULL, "
        "slot_time TEXT NOT NULL, "
        "calendar_id TEXT NOT NULL, "
        "event_id TEXT NOT NULL, "
        "html_link TEXT DEFAULT '', "
        "created_at TEXT NOT NULL, "
        "PRIMARY KEY (service_key, date, slot_time)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bookings ("
        "booking_ref TEXT PRIMARY KEY, "
        "service_key TEXT, "
        "customer_name TEXT, "
        "customer_email TEXT, "
        "date TEXT, "
        "slot_time TEXT, "
        "guests INTEGER, "
        "special_requests TEXT, "
        "payment_link TEXT, "
        "event_link TEXT, "
        "status TEXT DEFAULT 'pending_payment', "
        "created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS whatsapp_processed ("
        "message_id TEXT PRIMARY KEY, "
        "created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS whatsapp_threads ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "phone TEXT NOT NULL, "
        "role TEXT NOT NULL, "
        "text TEXT NOT NULL, "
        "created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_whatsapp_threads_phone "
        "ON whatsapp_threads(phone, created_at)"
    )
    # Schema migration: add channel + sender_name columns to whatsapp_threads
    try:
        conn.execute("ALTER TABLE whatsapp_threads ADD COLUMN channel TEXT DEFAULT 'whatsapp'")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        conn.execute("ALTER TABLE whatsapp_threads ADD COLUMN sender_name TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_whatsapp_threads_channel "
        "ON whatsapp_threads(channel, phone, created_at)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS whatsapp_booking_state ("
        "phone TEXT PRIMARY KEY, "
        "fields_json TEXT DEFAULT '{}', "
        "flags_json TEXT DEFAULT '{}', "
        "completed_bookings_json TEXT DEFAULT '[]', "
        "last_activity TEXT NOT NULL, "
        "created_at TEXT NOT NULL"
        ")"
    )
    # Schema migration: rename field names in whatsapp_booking_state JSON blobs
    try:
        _rows = conn.execute("SELECT phone, fields_json, flags_json FROM whatsapp_booking_state").fetchall()
        _renames = {"trip_key": "service_key", "experience": "service_name", "departure_time": "slot_time"}
        _flag_renames = {"hold_trip_key": "hold_service_key", "hold_departure_time": "hold_slot_time"}
        for _phone, _fj, _flj in _rows:
            _fields = json.loads(_fj or "{}")
            _flags = json.loads(_flj or "{}")
            _changed = False
            for _old, _new in _renames.items():
                if _old in _fields:
                    _fields[_new] = _fields.pop(_old)
                    _changed = True
            for _old, _new in _flag_renames.items():
                if _old in _flags:
                    _flags[_new] = _flags.pop(_old)
                    _changed = True
            if _changed:
                conn.execute("UPDATE whatsapp_booking_state SET fields_json = ?, flags_json = ? WHERE phone = ?",
                             (json.dumps(_fields), json.dumps(_flags), _phone))
        if _rows:
            conn.commit()
    except Exception:
        pass  # Table might not exist yet on fresh DB
    # Brief 166: cross-channel customer file
    conn.execute(
        "CREATE TABLE IF NOT EXISTS customers ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "display_name TEXT DEFAULT '', "
        "summary TEXT DEFAULT '', "
        "notes TEXT DEFAULT '', "
        "first_seen TEXT NOT NULL, "
        "last_seen TEXT NOT NULL, "
        "active INTEGER DEFAULT 1"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS customer_identifiers ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "customer_id INTEGER NOT NULL, "
        "type TEXT NOT NULL, "
        "value TEXT NOT NULL, "
        "first_seen TEXT NOT NULL, "
        "FOREIGN KEY (customer_id) REFERENCES customers(id)"
        ")"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_identifiers_type_value "
        "ON customer_identifiers(type, value)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_customer_identifiers_customer "
        "ON customer_identifiers(customer_id)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS customer_interactions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "customer_id INTEGER NOT NULL, "
        "channel TEXT NOT NULL, "
        "summary TEXT NOT NULL, "
        "created_at TEXT NOT NULL, "
        "FOREIGN KEY (customer_id) REFERENCES customers(id)"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_customer_interactions_customer "
        "ON customer_interactions(customer_id, created_at)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS customer_merges ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "surviving_id INTEGER NOT NULL, "
        "absorbed_id INTEGER NOT NULL, "
        "merged_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS pending_notifications ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "notification_type TEXT NOT NULL, "
        "relay_token TEXT UNIQUE, "
        "channel TEXT NOT NULL, "
        "customer_id TEXT NOT NULL, "
        "customer_name TEXT DEFAULT '', "
        "subject TEXT NOT NULL, "
        "body TEXT NOT NULL, "
        "status TEXT DEFAULT 'pending', "
        "created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS conversation_status ("
        "conversation_id TEXT PRIMARY KEY, "
        "channel TEXT NOT NULL DEFAULT 'whatsapp', "
        "status TEXT NOT NULL DEFAULT 'pending', "
        "updated_at TEXT NOT NULL"
        ")"
    )
    # Brief 213: pending_notifications.mode (per-escalation soft/hard)
    try:
        conn.execute("ALTER TABLE pending_notifications ADD COLUMN mode TEXT")
    except sqlite3.OperationalError:
        pass
    # Brief 227: structured escalation summary as JSON. Generated by Claude
    # at escalation-create time (best-effort — null if generation fails).
    try:
        conn.execute(
            "ALTER TABLE pending_notifications "
            "ADD COLUMN escalation_summary TEXT"
        )
    except sqlite3.OperationalError:
        pass
    # Brief 213: conversation_status.ai_muted (per-conversation human takeover flag)
    try:
        conn.execute("ALTER TABLE conversation_status ADD COLUMN ai_muted INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # Brief 213: conversation_status.human_takeover_at (ISO timestamp when muted)
    try:
        conn.execute("ALTER TABLE conversation_status ADD COLUMN human_takeover_at TEXT")
    except sqlite3.OperationalError:
        pass
    # Brief 220: conversation_status.blocked (per-conversation drop flag,
    # operator-controlled via dashboard). Different from ai_muted: blocked
    # drops the inbound BEFORE any storage so the conversation doesn't
    # appear in the inbox at all; ai_muted stores then skips Marina so
    # operator still sees it.
    try:
        conn.execute("ALTER TABLE conversation_status ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # Brief 249: conversation_status.deleted (archived state for the
    # WhatsApp/IG/FB inbox). Brief 237 introduced read+write of this
    # column without a migration -- silently broken since it shipped.
    # Brief 249 adds the missing migration so manual archive endpoints
    # AND Brief 237's bulk archive sweep both work.
    try:
        conn.execute("ALTER TABLE conversation_status ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # Brief 207: tasks shared between Calvin and Jr (operator-side workflow,
    # not customer-facing). Per-tenant SQLite isolation matches existing tables.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tasks ("
        "id TEXT PRIMARY KEY, "
        "body_html TEXT NOT NULL DEFAULT '', "
        "body_text TEXT NOT NULL DEFAULT '', "
        "created_by TEXT NOT NULL, "
        "assigned_to TEXT NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'open', "
        "completed_at TEXT, "
        "completed_by TEXT, "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS task_attachments ("
        "id TEXT PRIMARY KEY, "
        "task_id TEXT NOT NULL, "
        "file_name TEXT NOT NULL, "
        "mime_type TEXT NOT NULL, "
        "size_bytes INTEGER NOT NULL, "
        "stored_filename TEXT NOT NULL, "
        "created_at TEXT NOT NULL, "
        "FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE"
        ")"
    )
    # Brief 223: tasks.task_number (per-workspace stable integer for the
    # TASK-### badge SR's frontend displays). Idempotent ALTER + backfill
    # of pre-existing rows in chronological order so the oldest task is
    # TASK-001. Placed AFTER the CREATE TABLE tasks block so the ALTER
    # has a target on first init. Backfill runs on every _get_conn() call
    # (matching the existing per-connection schema-init pattern); after
    # the first run the SELECT returns zero rows and the if-guard
    # short-circuits.
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN task_number INTEGER")
    except sqlite3.OperationalError:
        pass
    to_backfill = conn.execute(
        "SELECT id FROM tasks WHERE task_number IS NULL ORDER BY created_at ASC"
    ).fetchall()
    if to_backfill:
        cur_max = conn.execute(
            "SELECT COALESCE(MAX(task_number), 0) FROM tasks"
        ).fetchone()[0]
        for offset, (row_id,) in enumerate(to_backfill, start=1):
            conn.execute(
                "UPDATE tasks SET task_number = ? WHERE id = ?",
                (cur_max + offset, row_id))
        conn.commit()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS content_drafts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "content_class TEXT NOT NULL, "
        "instagram_caption TEXT, "
        "facebook_caption TEXT, "
        "twitter_caption TEXT DEFAULT '', "
        "hashtags_json TEXT DEFAULT '[]', "
        "visual_suggestion TEXT DEFAULT '', "
        "reasoning TEXT DEFAULT '', "
        "status TEXT DEFAULT 'pending', "
        "rejection_reason TEXT DEFAULT '', "
        "created_at TEXT NOT NULL, "
        "approved_at TEXT, "
        "published_at TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS content_learnings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "rule TEXT NOT NULL, "
        "source_draft_ids TEXT DEFAULT '[]', "
        "active INTEGER DEFAULT 1, "
        "created_at TEXT NOT NULL"
        ")"
    )
    # Brief 215: escalation-derived learning entries (operator answers stored
    # as approved knowledge for Marina to reuse in future similar replies).
    # Distinct from content_learnings (content_agent's draft rules).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS escalation_learnings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "conversation_id TEXT NOT NULL, "
        "channel TEXT NOT NULL, "
        "source_question TEXT NOT NULL DEFAULT '', "
        "human_answer TEXT NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'approved', "
        "ai_may_use_automatically INTEGER NOT NULL DEFAULT 1, "
        "category TEXT, "
        "created_by TEXT, "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL"
        ")"
    )
    # Brief 216: per-tenant temporary/permanent business updates that Marina
    # injects into her prompt. Two flavors: permanent (no dates → always
    # active) and scheduled (start_date + end_date → active only within
    # the window). Type enum matches SR's product contract Section 5.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS info_updates ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "type TEXT NOT NULL DEFAULT 'general', "
        "text TEXT NOT NULL, "
        "active INTEGER NOT NULL DEFAULT 1, "
        "start_date TEXT, "
        "end_date TEXT, "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL"
        ")"
    )
    # Brief 217: per-tenant alert settings (singleton row, fixed id=1).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS alert_settings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "email_enabled INTEGER NOT NULL DEFAULT 1, "
        "email_destination TEXT NOT NULL DEFAULT '', "
        "whatsapp_enabled INTEGER NOT NULL DEFAULT 0, "
        "whatsapp_destination TEXT NOT NULL DEFAULT '', "
        "telegram_enabled INTEGER NOT NULL DEFAULT 0, "
        "telegram_destination TEXT NOT NULL DEFAULT '', "
        "messenger_enabled INTEGER NOT NULL DEFAULT 0, "
        "messenger_destination TEXT NOT NULL DEFAULT '', "
        "updated_at TEXT NOT NULL DEFAULT ''"
        ")"
    )
    # Brief 226: alternative email destination for escalation alerts. Optional
    # second recipient that receives a copy of every email alert. ALTER instead
    # of expanding CREATE TABLE so existing tenant DBs migrate without a drop.
    try:
        conn.execute(
            "ALTER TABLE alert_settings "
            "ADD COLUMN email_alternative_destination TEXT NOT NULL DEFAULT ''"
        )
    except sqlite3.OperationalError:
        pass  # column already exists
    # Brief 240: Zernio-route fields for operator WhatsApp alerts. The
    # user-facing whatsapp_destination stays as the displayed phone (e.g.,
    # "+351963618003"); these three columns capture the Zernio
    # conversation_id + account_id needed for outbound delivery, populated
    # automatically by the auto-resolve hook in webhook_server when the
    # operator sends a bootstrap inbound from that number.
    for _coldef in (
        "ADD COLUMN whatsapp_zernio_conversation_id TEXT",
        "ADD COLUMN whatsapp_zernio_account_id TEXT",
        "ADD COLUMN whatsapp_zernio_resolved_at TEXT",
    ):
        try:
            conn.execute(f"ALTER TABLE alert_settings {_coldef}")
        except sqlite3.OperationalError:
            pass  # column already exists
    # Brief 241: alert_type + appointment_id columns on alert_deliveries.
    # Existing rows (Brief 217-240 era) get retro-labeled as 'escalation'
    # via the DEFAULT - semantically correct since they were all
    # escalation-alert deliveries. appointment_id stays NULL for those rows.
    for _coldef in (
        "ADD COLUMN alert_type TEXT NOT NULL DEFAULT 'escalation'",
        "ADD COLUMN appointment_id INTEGER",
    ):
        try:
            conn.execute(f"ALTER TABLE alert_deliveries {_coldef}")
        except sqlite3.OperationalError:
            pass  # column already exists
    # Brief 241: per-alert-type enable flags on alert_settings. Both
    # default ON for backward compat - existing tenants continue to receive
    # escalation alerts; appointment alerts begin firing once the trigger
    # (appointment_upsert transition-to-confirmed) is reached.
    for _coldef in (
        "ADD COLUMN alert_type_escalation_enabled INTEGER NOT NULL DEFAULT 1",
        "ADD COLUMN alert_type_appointment_enabled INTEGER NOT NULL DEFAULT 1",
    ):
        try:
            conn.execute(f"ALTER TABLE alert_settings {_coldef}")
        except sqlite3.OperationalError:
            pass  # column already exists
    # Brief 217: append-only audit log of alert delivery attempts.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS alert_deliveries ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "escalation_id INTEGER, "
        "channel TEXT NOT NULL, "
        "destination TEXT NOT NULL DEFAULT '', "
        "status TEXT NOT NULL, "
        "error TEXT, "
        "sent_at TEXT NOT NULL"
        ")"
    )
    # Brief 228: appointments — derived from escalation summaries when
    # intent=='scheduling'. One row per conversation_id (upsert on duplicate).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS appointments ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "conversation_id TEXT NOT NULL UNIQUE, "
        "channel TEXT NOT NULL, "
        "customer_name TEXT NOT NULL DEFAULT '', "
        "title TEXT NOT NULL DEFAULT '', "
        "date_time_label TEXT NOT NULL DEFAULT '', "
        "proposed_times_json TEXT NOT NULL DEFAULT '[]', "
        "location TEXT NOT NULL DEFAULT '', "
        "status TEXT NOT NULL DEFAULT 'detected', "
        "source TEXT NOT NULL DEFAULT 'conversation', "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL"
        ")"
    )
    # Brief 229: data retention settings (singleton row, fixed id=1).
    # Active inbox archive threshold + archive retention + end-of-retention
    # action + keep-approved-learnings + audit log retention.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS data_retention_settings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "active_inbox_archive_after_days INTEGER, "
        "archive_retention_months INTEGER, "
        "end_of_retention_action TEXT NOT NULL DEFAULT 'anonymize', "
        "keep_approved_learnings INTEGER NOT NULL DEFAULT 1, "
        "audit_log_retention_months INTEGER NOT NULL DEFAULT 24, "
        "updated_at TEXT NOT NULL DEFAULT ''"
        ")"
    )
    # Brief 237: data retention audit log. Records every archive-now /
    # export / delete-customer-data attempt (success AND blocked). Rule 10
    # of SR's task ab7d8f1eb97c: "Do not silently delete — log retention
    # actions."
    conn.execute(
        "CREATE TABLE IF NOT EXISTS data_retention_audit_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "action TEXT NOT NULL, "
        "identifier_type TEXT, "
        "identifier_value TEXT, "
        "affected_counts_json TEXT, "
        "actor TEXT, "
        "created_at TEXT NOT NULL"
        ")"
    )
    # Brief 230: knowledge files (uploaded reference docs Marina reads when
    # features.knowledge_files_in_prompt is true). One row per file. Text is
    # extracted synchronously at upload time and stored here; the actual
    # uploaded file lives on disk under wtyj/data/knowledge/.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS knowledge_files ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "filename TEXT NOT NULL, "
        "stored_filename TEXT NOT NULL, "
        "mime_type TEXT NOT NULL DEFAULT '', "
        "size_bytes INTEGER NOT NULL DEFAULT 0, "
        "status TEXT NOT NULL DEFAULT 'pending', "
        "extracted_text TEXT NOT NULL DEFAULT '', "
        "failure_reason TEXT NOT NULL DEFAULT '', "
        "uploaded_at TEXT NOT NULL, "
        "last_used_at TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS photo_library ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "filename TEXT NOT NULL, "
        "original_filename TEXT NOT NULL, "
        "tags_json TEXT DEFAULT '[]', "
        "service_key TEXT DEFAULT '', "
        "source TEXT DEFAULT 'upload', "
        "source_id TEXT DEFAULT '', "
        "width INTEGER DEFAULT 0, "
        "height INTEGER DEFAULT 0, "
        "file_size INTEGER DEFAULT 0, "
        "used_count INTEGER DEFAULT 0, "
        "uploaded_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS oauth_tokens ("
        "provider TEXT PRIMARY KEY, "
        "access_token TEXT NOT NULL, "
        "refresh_token TEXT NOT NULL, "
        "expires_at TEXT, "
        "folder_id TEXT DEFAULT '', "
        "updated_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS training_examples ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "caption_text TEXT NOT NULL, "
        "image_path TEXT DEFAULT '', "
        "platform TEXT DEFAULT '', "
        "created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS brand_profile ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "category TEXT NOT NULL, "
        "rule TEXT NOT NULL, "
        "source TEXT DEFAULT 'analysis', "
        "active INTEGER DEFAULT 1, "
        "created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS system_settings ("
        "key TEXT PRIMARY KEY, "
        "value TEXT NOT NULL"
        ")"
    )
    try:
        conn.execute("ALTER TABLE content_drafts ADD COLUMN image_path TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE content_drafts ADD COLUMN late_post_id TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE content_drafts ADD COLUMN instagram_url TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE content_drafts ADD COLUMN photo_id INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schedule_slots ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "day_of_week TEXT NOT NULL, "
        "time_utc TEXT NOT NULL, "
        "active INTEGER DEFAULT 1, "
        "created_at TEXT NOT NULL"
        ")"
    )
    try:
        conn.execute("ALTER TABLE content_drafts ADD COLUMN scheduled_at TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE content_drafts ADD COLUMN platforms_json TEXT DEFAULT '[\"instagram\"]'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE content_drafts ADD COLUMN facebook_url TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE content_drafts ADD COLUMN late_facebook_post_id TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE content_drafts ADD COLUMN twitter_caption TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE service_bookings ADD COLUMN customer_name TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    # Brief 168: payment hold state machine
    try:
        conn.execute("ALTER TABLE service_bookings ADD COLUMN payment_expires_at TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE service_bookings ADD COLUMN payment_reminder_sent_at TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE service_bookings ADD COLUMN customer_phone TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE service_bookings ADD COLUMN customer_email TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    return conn


def generate_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def has_been_processed(content: str) -> bool:
    content_hash = generate_content_hash(content)
    conn = _get_conn()
    row = conn.execute(
        "SELECT count(*) FROM processed_hashes WHERE hash = ?",
        (content_hash,)
    ).fetchone()
    conn.close()
    return row[0] > 0


def mark_as_processed(content: str):
    content_hash = generate_content_hash(content)
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO processed_hashes (hash, created_at) VALUES (?, ?)",
        (content_hash, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()


def expire_stale_holds() -> int:
    """Set status='expired' for soft_hold rows past their expires_at. Returns count updated."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "UPDATE service_bookings SET status='expired' "
        "WHERE status='soft_hold' AND expires_at < ?",
        (now,)
    )
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def get_spots_remaining(service_key: str, date: str, slot_time: str, capacity: int) -> int:
    """Return capacity minus guests already in soft_hold (non-expired) or confirmed for this slot."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute(
        "SELECT COALESCE(SUM(guests), 0) FROM service_bookings "
        "WHERE service_key=? AND date=? AND slot_time=? "
        "AND status IN ('soft_hold', 'confirmed') "
        "AND (status='confirmed' OR expires_at > ?)",
        (service_key, date, slot_time, now)
    ).fetchone()
    conn.close()
    used = row[0] if row else 0
    return max(0, capacity - used)


def create_soft_hold(
    service_key: str, date: str, slot_time: str, guests: int, capacity: int,
    customer_name: str = "", customer_email: str = ""
) -> "int | None":
    """
    Atomic: expire stale holds, check remaining capacity, insert soft_hold with 24h TTL.
    Returns the new row id (hold_id) on success, None if at capacity or on error.
    Uses BEGIN IMMEDIATE to serialise concurrent inserts.
    """
    conn = _get_conn()
    conn.isolation_level = None  # switch to manual commit/rollback for BEGIN IMMEDIATE
    now = datetime.now(timezone.utc).isoformat()
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE service_bookings SET status='expired' "
            "WHERE status='soft_hold' AND expires_at < ?",
            (now,)
        )
        row = conn.execute(
            "SELECT COALESCE(SUM(guests), 0) FROM service_bookings "
            "WHERE service_key=? AND date=? AND slot_time=? "
            "AND status IN ('soft_hold', 'confirmed') "
            "AND (status='confirmed' OR expires_at > ?)",
            (service_key, date, slot_time, now)
        ).fetchone()
        used = row[0] if row else 0
        if used + guests > capacity:
            conn.execute("COMMIT")
            conn.close()
            return None
        cur = conn.execute(
            "INSERT INTO service_bookings "
            "(service_key, date, slot_time, guests, status, expires_at, created_at, "
            "customer_name, customer_email) "
            "VALUES (?, ?, ?, ?, 'soft_hold', ?, ?, ?, ?)",
            (service_key, date, slot_time, guests, expires_at, now,
             customer_name, customer_email)
        )
        hold_id = cur.lastrowid
        conn.execute("COMMIT")
        conn.close()
        return hold_id
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        conn.close()
        return None


def confirm_hold(hold_id: int) -> bool:
    """Upgrade a soft_hold to confirmed. Clears expires_at. Returns True if row was updated."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE service_bookings SET status='confirmed', expires_at=NULL "
        "WHERE id=? AND status='soft_hold'",
        (hold_id,)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def cancel_hold(hold_id: int) -> bool:
    """Mark a hold as cancelled. Returns True if row was updated."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE service_bookings SET status='cancelled' WHERE id=?",
        (hold_id,)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def set_booking_ref(hold_id: int, booking_ref: str) -> bool:
    """Set booking_ref on a service_bookings row. Returns True if row was updated."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE service_bookings SET booking_ref=? WHERE id=?",
        (booking_ref, hold_id)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def get_manifest_event(service_key: str, date: str, slot_time: str):
    """Returns dict {service_key, date, slot_time, calendar_id, event_id, html_link} or None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT service_key, date, slot_time, calendar_id, event_id, html_link "
        "FROM manifest_events WHERE service_key=? AND date=? AND slot_time=?",
        (service_key, date, slot_time)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "service_key": row[0], "date": row[1], "slot_time": row[2],
        "calendar_id": row[3], "event_id": row[4], "html_link": row[5],
    }


def save_manifest_event(service_key: str, date: str, slot_time: str,
                        calendar_id: str, event_id: str, html_link: str) -> None:
    """INSERT OR REPLACE into manifest_events."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO manifest_events "
        "(service_key, date, slot_time, calendar_id, event_id, html_link, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (service_key, date, slot_time, calendar_id, event_id, html_link,
         datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()


def delete_manifest_event(service_key: str, date: str, slot_time: str) -> bool:
    """Delete manifest_events row for this slot. Returns True if row existed."""
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM manifest_events WHERE service_key=? AND date=? AND slot_time=?",
        (service_key, date, slot_time)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def get_slot_passengers(service_key: str, date: str, slot_time: str) -> list:
    """Return all active bookings for this slot (soft_hold non-expired + confirmed).
    Each item: {id, guests, booking_ref, status, customer_name, customer_email, created_at}."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT id, guests, booking_ref, status, customer_name, customer_email, created_at "
        "FROM service_bookings "
        "WHERE service_key=? AND date=? AND slot_time=? "
        "AND status IN ('soft_hold', 'confirmed') "
        "AND (status='confirmed' OR expires_at > ?) "
        "ORDER BY created_at ASC",
        (service_key, date, slot_time, now)
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "guests": r[1], "booking_ref": r[2] or "",
            "status": r[3], "customer_name": r[4] or "", "customer_email": r[5] or "",
            "created_at": r[6],
        }
        for r in rows
    ]


def save_booking(booking_ref: str, fields: dict, flags: dict,
                 customer_email: str = "") -> None:
    """Upsert a booking record after hold creation success."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO bookings "
        "(booking_ref, service_key, customer_name, customer_email, date, "
        "slot_time, guests, special_requests, payment_link, event_link, "
        "status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            booking_ref,
            fields.get("service_key", ""),
            fields.get("customer_name", ""),
            customer_email.strip().lower() if customer_email else "",
            fields.get("date", ""),
            fields.get("slot_time", ""),
            int(fields.get("guests") or 0),
            fields.get("special_requests", ""),
            flags.get("payment_link", ""),
            flags.get("event_link", ""),
            "confirmed",
            datetime.now(timezone.utc).isoformat(),
        )
    )
    conn.commit()
    conn.close()


def get_bookings_by_email(customer_email: str) -> list:
    """Return all bookings for a customer email, newest first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT booking_ref, service_key, customer_name, customer_email, date, "
        "slot_time, guests, special_requests, payment_link, event_link, "
        "status, created_at "
        "FROM bookings WHERE customer_email = ? ORDER BY created_at DESC",
        (customer_email.strip().lower(),)
    ).fetchall()
    conn.close()
    return [{"booking_ref": r[0], "service_key": r[1], "customer_name": r[2],
             "customer_email": r[3], "date": r[4], "slot_time": r[5],
             "guests": r[6], "special_requests": r[7], "payment_link": r[8],
             "event_link": r[9], "status": r[10], "created_at": r[11]} for r in rows]


def get_booking(booking_ref: str) -> "dict | None":
    """Return full booking dict by ref, or None if not found."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT booking_ref, service_key, customer_name, customer_email, date, "
        "slot_time, guests, special_requests, payment_link, event_link, "
        "status, created_at "
        "FROM bookings WHERE booking_ref = ?",
        (booking_ref,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "booking_ref": row[0], "service_key": row[1], "customer_name": row[2],
        "customer_email": row[3], "date": row[4], "slot_time": row[5],
        "guests": row[6], "special_requests": row[7], "payment_link": row[8],
        "event_link": row[9], "status": row[10], "created_at": row[11],
    }


def wa_has_been_processed(message_id: str) -> bool:
    """Check if a WhatsApp message ID has already been processed."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM whatsapp_processed WHERE message_id = ?",
        (message_id,)
    ).fetchone()
    conn.close()
    return row is not None


def wa_mark_as_processed(message_id: str):
    """Record a WhatsApp message ID as processed."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO whatsapp_processed (message_id, created_at) VALUES (?, ?)",
        (message_id, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()


def wa_store_message(phone: str, role: str, text: str):
    """Store a WhatsApp message in conversation history."""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO whatsapp_threads (phone, role, text, created_at) VALUES (?, ?, ?, ?)",
        (phone, role, text, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()


def wa_get_history(phone: str, limit: int = 10) -> list:
    """Get recent conversation history for a phone number (last 24h, oldest first)."""
    conn = _get_conn()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    rows = conn.execute(
        "SELECT role, text, created_at FROM whatsapp_threads "
        "WHERE phone = ? AND created_at > ? "
        "ORDER BY created_at DESC LIMIT ?",
        (phone, cutoff, limit)
    ).fetchall()
    conn.close()
    return [{"role": r[0], "text": r[1], "created_at": r[2]} for r in reversed(rows)]


def wa_get_booking_state(phone: str) -> dict:
    """Get booking state for a phone number. Returns {fields, flags, completed_bookings, last_activity}."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT fields_json, flags_json, completed_bookings_json, last_activity "
        "FROM whatsapp_booking_state WHERE phone = ?",
        (phone,)
    ).fetchone()
    conn.close()
    if not row:
        return {"fields": {}, "flags": {}, "completed_bookings": [], "last_activity": None}
    return {
        "fields": json.loads(row[0] or "{}"),
        "flags": json.loads(row[1] or "{}"),
        "completed_bookings": json.loads(row[2] or "[]"),
        "last_activity": row[3],
    }


def wa_save_booking_state(phone: str, fields: dict, flags: dict,
                          completed_bookings: list = None):
    """Save/update booking state for a phone number."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    cb = json.dumps(completed_bookings or [], ensure_ascii=False)
    conn.execute(
        "INSERT OR REPLACE INTO whatsapp_booking_state "
        "(phone, fields_json, flags_json, completed_bookings_json, last_activity, created_at) "
        "VALUES (?, ?, ?, ?, ?, COALESCE("
        "(SELECT created_at FROM whatsapp_booking_state WHERE phone = ?), ?))",
        (phone, json.dumps(fields, ensure_ascii=False),
         json.dumps(flags, ensure_ascii=False), cb, now, phone, now)
    )
    conn.commit()
    conn.close()


def _get_email_state_path() -> str:
    """Brief 171: resolve the email_thread_state.json path the email_poller uses."""
    # email_poller stores it at /app/config/email_thread_state.json inside the container.
    # Fall back to the source-tree clients/bluemarlin path for local dev.
    _cfg = os.environ.get("CLIENT_CONFIG_PATH", "")
    candidates = [
        "/app/config/email_thread_state.json",
    ]
    if _cfg:
        candidates.insert(0, os.path.join(os.path.dirname(_cfg), "email_thread_state.json"))
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]


def email_list_conversations() -> list:
    """Brief 171: return email threads in the same shape as wa_list_conversations
    (phone, customer_name, last_message, last_message_role, last_message_at,
    status, message_count, channel) so the dashboard Messages page can merge them.

    The `phone` field carries an `email::` prefix to disambiguate from WhatsApp
    rows and make the URL unambiguous for the detail endpoint."""
    path = _get_email_state_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            state = json.load(f)
    except Exception:
        return []
    threads = state.get("threads", {})
    result = []
    for thread_key, th in threads.items():
        messages = th.get("messages", []) or []
        if not messages:
            continue
        last = messages[-1]
        last_ts = last.get("ts") or last.get("timestamp") or ""
        last_role = last.get("role", "")
        last_body = (last.get("body") or last.get("text") or "")[:200]
        # Normalize role: customer -> user, marina -> assistant.
        # Brief 233: 'operator' passes through unchanged so the inbox
        # list can show a distinct indicator for operator-typed replies.
        if last_role == "customer":
            last_role = "user"
        elif last_role == "marina":
            last_role = "assistant"
        fields = th.get("fields", {}) or {}
        flags = th.get("flags", {}) or {}
        customer_name = fields.get("customer_name") or ""
        if not customer_name:
            # derive from thread_key like "subj:alice@x.com:..." → alice@x.com
            parts = thread_key.split(":", 2)
            if len(parts) >= 2:
                customer_name = parts[1]
        # Brief 218: skip threads marked deleted (the dashboard hides them
        # from the active inbox; provider-side cleanup is a follow-up).
        if flags.get("deleted"):
            continue
        status = "escalated" if flags.get("fully_escalated") or flags.get("awaiting_relay") else "active"
        result.append({
            "phone": f"email::{thread_key}",
            "customer_name": customer_name or "(email customer)",
            "last_message": last_body,
            "last_message_role": last_role,
            "last_message_at": last_ts,
            "status": status,
            "message_count": len(messages),
            "channel": "email",
        })
    # Sort newest first
    result.sort(key=lambda r: r["last_message_at"] or "", reverse=True)
    return result


def email_set_archived(thread_key: str, archived: bool) -> bool:
    """Brief 249: toggle the archive state on an email thread. Sets/clears
    flags.deleted in email_thread_state.json (the existing Brief 218 +
    Brief 237 'archived' semantic - the flag is named 'deleted' for
    historical reasons but semantically means 'hidden from active inbox',
    NOT hard-removed from storage). Returns True if the thread was found
    and updated; False if no matching thread_key in state."""
    path = _get_email_state_path()
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r") as f:
            state = json.load(f)
    except Exception:
        return False
    threads = state.get("threads") or {}
    th = threads.get(thread_key)
    if not th:
        return False
    flags = th.setdefault("flags", {})
    if archived:
        flags["deleted"] = True
    else:
        # Unarchive -- remove the key entirely so a future re-read sees
        # the thread as never-archived (clean shape).
        flags.pop("deleted", None)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def wa_set_archived(conversation_id: str, archived: bool) -> bool:
    """Brief 249: toggle the archive state on a WhatsApp/IG/FB
    conversation. Sets/clears conversation_status.deleted (the existing
    Brief 218 + Brief 237 'archived' semantic). UPSERTs the
    conversation_status row when missing so manual archive works for
    conversations that have no prior status entry. Returns True; raises
    on DB error (caller wraps if it cares)."""
    if not conversation_id:
        return False
    now = datetime.now(timezone.utc).isoformat()
    deleted_int = 1 if archived else 0
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO conversation_status "
            "(conversation_id, channel, status, updated_at, deleted) "
            "VALUES (?, 'whatsapp', ?, ?, ?) "
            "ON CONFLICT(conversation_id) DO UPDATE SET "
            "deleted = excluded.deleted, updated_at = excluded.updated_at",
            (conversation_id, "archived" if archived else "active",
             now, deleted_int))
        conn.commit()
    finally:
        conn.close()
    return True


def email_list_archived_conversations() -> list:
    """Brief 249: return email threads with flags.deleted=true (the
    inverse of email_list_conversations' filter). Same response shape
    as email_list_conversations so the frontend can swap the data
    source by URL without re-mapping fields."""
    path = _get_email_state_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            state = json.load(f)
    except Exception:
        return []
    threads = state.get("threads", {})
    result = []
    for thread_key, th in threads.items():
        messages = th.get("messages", []) or []
        if not messages:
            continue
        flags = th.get("flags", {}) or {}
        # Inverse filter: only archived (deleted=true) rows.
        if not flags.get("deleted"):
            continue
        last = messages[-1]
        last_ts = last.get("ts") or last.get("timestamp") or ""
        last_role = last.get("role", "")
        last_body = (last.get("body") or last.get("text") or "")[:200]
        if last_role == "customer":
            last_role = "user"
        elif last_role == "marina":
            last_role = "assistant"
        fields = th.get("fields", {}) or {}
        customer_name = fields.get("customer_name") or ""
        if not customer_name:
            parts = thread_key.split(":", 2)
            if len(parts) >= 2:
                customer_name = parts[1]
        result.append({
            "phone": f"email::{thread_key}",
            "customer_name": customer_name or "(email customer)",
            "last_message": last_body,
            "last_message_role": last_role,
            "last_message_at": last_ts,
            "status": "archived",
            "message_count": len(messages),
            "channel": "email",
        })
    result.sort(key=lambda r: r["last_message_at"] or "", reverse=True)
    return result


def wa_list_archived_conversations() -> list:
    """Brief 249: return WhatsApp/IG/FB conversations with
    conversation_status.deleted=1 (the inverse of wa_list_conversations'
    new Brief 249 filter). Same response shape as wa_list_conversations."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT t.phone, t.text, t.created_at, t.role, t.channel "
        "FROM whatsapp_threads t "
        "INNER JOIN ("
        "  SELECT phone, MAX(created_at) as max_ts "
        "  FROM whatsapp_threads GROUP BY phone"
        ") latest ON t.phone = latest.phone AND t.created_at = latest.max_ts "
        "INNER JOIN conversation_status cs ON t.phone = cs.conversation_id "
        "WHERE cs.deleted = 1 "
        "ORDER BY t.created_at DESC"
    ).fetchall()
    conversations = []
    for r in rows:
        phone = r[0]
        state_row = conn.execute(
            "SELECT fields_json, flags_json FROM whatsapp_booking_state "
            "WHERE phone = ?", (phone,)
        ).fetchone()
        fields = json.loads(state_row[0] or "{}") if state_row else {}
        name = (fields.get("customer_name") or fields.get("name") or "")
        if not name:
            sender_row = conn.execute(
                "SELECT sender_name FROM whatsapp_threads WHERE phone = ? "
                "AND role = 'user' AND sender_name != '' "
                "ORDER BY created_at DESC LIMIT 1", (phone,)
            ).fetchone()
            if sender_row and sender_row[0]:
                name = sender_row[0]
        if not name:
            name = phone
        count_row = conn.execute(
            "SELECT COUNT(*) FROM whatsapp_threads WHERE phone = ?", (phone,)
        ).fetchone()
        conversations.append({
            "phone": phone,
            "customer_name": name,
            "last_message": (r[1] or "")[:200],
            "last_message_role": r[3] or "",
            "last_message_at": r[2] or "",
            "status": "archived",
            "message_count": count_row[0] if count_row else 0,
            "channel": r[4] if len(r) > 4 and r[4] else "whatsapp",
        })
    conn.close()
    return conversations


def email_get_conversation(thread_key: str) -> dict:
    """Brief 171: return full message history + fields for an email thread.
    Messages are normalized to the WhatsApp shape: {role, text, created_at}."""
    path = _get_email_state_path()
    if not os.path.exists(path):
        return {"phone": f"email::{thread_key}", "messages": [], "booking_state": {}}
    try:
        with open(path, "r") as f:
            state = json.load(f)
    except Exception:
        return {"phone": f"email::{thread_key}", "messages": [], "booking_state": {}}
    th = state.get("threads", {}).get(thread_key, {})
    raw_messages = th.get("messages", []) or []
    out_messages = []
    for m in raw_messages:
        role = m.get("role", "")
        if role == "customer":
            role = "user"
        elif role == "marina":
            role = "assistant"
        # Brief 233: 'operator' passes through unchanged so the frontend
        # can render verbatim operator replies distinctly from Marina-
        # generated ones. SR's existing mapper falls back to "assistant"
        # for unknown values, so this is a graceful no-op until the
        # frontend opts into the new value.
        text = m.get("body") or m.get("text") or ""
        ts = m.get("ts") or m.get("timestamp") or ""
        out_messages.append({"role": role, "text": text, "created_at": ts})
    return {
        "phone": f"email::{thread_key}",
        "messages": out_messages,
        "booking_state": {
            "fields": th.get("fields", {}) or {},
            "flags": th.get("flags", {}) or {},
            "completed_bookings": th.get("completed_bookings", []) or [],
            "last_activity": th.get("last_activity"),
        },
    }


def _find_email_thread_key_for(customer_email: str):
    """Brief 211: locate the email_thread_state.json thread_key for a given
    customer email. Used by /escalations to expose a routable conversation
    key for email rows, and by email_append_assistant_message to find the
    thread for an outbound reply. Returns the thread_key string or None
    if no thread exists yet for this customer."""
    if not customer_email:
        return None
    path = _get_email_state_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            state = json.load(f)
    except Exception:
        return None
    needle = customer_email.lower()
    for thread_key in (state.get("threads") or {}).keys():
        if needle in thread_key.lower():
            return thread_key
    return None


def email_mark_deleted(thread_key: str) -> bool:
    """Brief 218: mark an email thread as deleted in our local state.
    The thread is filtered out of email_list_conversations. Provider-side
    IMAP MOVE to trash is deferred — local-state only for v1.
    Returns True on success, False if no such thread."""
    path = _get_email_state_path()
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r") as f:
            state = json.load(f)
    except Exception:
        return False
    threads = state.get("threads", {})
    if thread_key not in threads:
        return False
    th = threads[thread_key]
    th.setdefault("flags", {})["deleted"] = True
    th["last_activity"] = datetime.now(timezone.utc).isoformat()
    state["threads"][thread_key] = th
    try:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        return False
    return True


def email_get_latest_customer_message(thread_key: str) -> dict:
    """Brief 218: return the most recent customer-role message in this
    email thread, or empty dict if none. Used by /forward to pick what
    to forward when the frontend doesn't specify a message id."""
    if not thread_key:
        return {}
    path = _get_email_state_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            state = json.load(f)
    except Exception:
        return {}
    th = state.get("threads", {}).get(thread_key, {}) or {}
    for m in reversed(th.get("messages", []) or []):
        if m.get("role") == "customer":
            return m
    return {}


def email_append_assistant_message(customer_email: str, body: str,
                                    role: str = "marina"):
    """Brief 210: append an outbound reply to the email thread state.
    Brief 233: `role` distinguishes Marina-generated replies (`"marina"`,
    the default) from verbatim operator replies (`"operator"`). The
    /escalations/{id}/guidance path keeps the default because Marina
    reformulates the operator's coaching there. /escalations/{id}/reply
    (hard escalation) and /messages/conversations/{id}/email/reply pass
    `role="operator"` because the operator's text is sent verbatim.
    Returns the matched thread_key string, or None if no thread exists
    for this email yet."""
    matched_key = _find_email_thread_key_for(customer_email)
    if not matched_key:
        return None

    path = _get_email_state_path()
    try:
        with open(path, "r") as f:
            state = json.load(f)
    except Exception:
        return None

    th = state["threads"][matched_key]
    th.setdefault("messages", []).append({
        "role": role,
        "ts": datetime.now(timezone.utc).isoformat(),
        "body": body,
    })
    th["last_activity"] = datetime.now(timezone.utc).isoformat()
    state["threads"][matched_key] = th

    try:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        return None

    return matched_key


def wa_delete_conversation(phone: str) -> int:
    """Brief 165: hard-delete all messages + booking state for a phone number.
    Returns the total number of rows deleted across whatsapp_threads and
    whatsapp_booking_state. Used by the dashboard delete-conversation endpoint.
    No audit trail — destructive operation meant for removing test pollution
    and unwanted threads from the Messages view.
    """
    conn = _get_conn()
    total = 0
    for sql in (
        "DELETE FROM whatsapp_threads WHERE phone = ?",
        "DELETE FROM whatsapp_booking_state WHERE phone = ?",
    ):
        cur = conn.execute(sql, (phone,))
        total += cur.rowcount
    conn.commit()
    conn.close()
    return total


def wa_list_conversations() -> list:
    """List all WhatsApp conversations with latest message and booking state.
    Returns list of dicts sorted by most recent activity."""
    conn = _get_conn()
    # Get unique phones with latest message
    rows = conn.execute(
        "SELECT t.phone, t.text, t.created_at, t.role, t.channel "
        "FROM whatsapp_threads t "
        "INNER JOIN ("
        "  SELECT phone, MAX(created_at) as max_ts "
        "  FROM whatsapp_threads GROUP BY phone"
        ") latest ON t.phone = latest.phone AND t.created_at = latest.max_ts "
        # Brief 249: exclude conversations marked archived
        # (conversation_status.deleted=1 set by Brief 237's bulk sweep
        # OR by Brief 249's manual archive endpoint).
        "LEFT JOIN conversation_status cs ON t.phone = cs.conversation_id "
        "WHERE cs.deleted IS NULL OR cs.deleted = 0 "
        "ORDER BY t.created_at DESC"
    ).fetchall()

    conversations = []
    for r in rows:
        phone = r[0]
        # Get booking state for name + status
        state_row = conn.execute(
            "SELECT fields_json, flags_json, last_activity "
            "FROM whatsapp_booking_state WHERE phone = ?", (phone,)
        ).fetchone()
        fields = json.loads(state_row[0] or "{}") if state_row else {}
        flags = json.loads(state_row[1] or "{}") if state_row else {}
        # Brief 202: when booking_state has no customer_name (the dm_agent path
        # for booking_flow:false tenants like unboks doesn't populate it), fall
        # back to the most recent user-role sender_name from whatsapp_threads.
        # Marina's path (booking_flow:true) is unaffected — booking_state's
        # customer_name takes priority.
        name = fields.get("customer_name") or fields.get("name") or ""
        if not name:
            sender_row = conn.execute(
                "SELECT sender_name FROM whatsapp_threads "
                "WHERE phone = ? AND role = 'user' AND sender_name != '' "
                "ORDER BY created_at DESC LIMIT 1",
                (phone,)
            ).fetchone()
            if sender_row and sender_row[0]:
                name = sender_row[0]
        if not name:
            name = phone  # final fallback to hex/phone if no name source at all
        status = "escalated" if flags.get("fully_escalated") else "active"
        # Count messages
        count_row = conn.execute(
            "SELECT COUNT(*) FROM whatsapp_threads WHERE phone = ?", (phone,)
        ).fetchone()
        channel = r[4] if len(r) > 4 and r[4] else "whatsapp"
        conversations.append({
            "phone": phone,
            "customer_name": name,
            "last_message": r[1],
            "last_message_role": r[3],
            "last_message_at": r[2],
            "status": status,
            "message_count": count_row[0] if count_row else 0,
            "channel": channel,
        })
    conn.close()
    return conversations


def wa_get_full_history(phone: str, limit: int = 100) -> list:
    """Get the most-recent conversation history for a phone number
    (no 24h cutoff). Returns the most recent `limit` messages, ordered
    oldest-first in the output (callers iterate forward through time).

    Brief 201: also returns row id (SQLite autoincrement) so frontends can use it
    as a stable React key.

    Brief 250: SELECT changed from `ORDER BY ASC LIMIT ?` to `ORDER BY
    DESC LIMIT ? ... reversed()`. Pre-Brief-250 the function returned
    the OLDEST N messages when total > limit -- silently truncating the
    most recent ones. This broke escalation summary generation for any
    conversation > 20 messages (escalation_dispatcher.py:37 calls with
    limit=20) because Claude only saw stale history. Output order
    contract preserved: still oldest-first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, role, text, created_at FROM whatsapp_threads "
        "WHERE phone = ? ORDER BY created_at DESC LIMIT ?",
        (phone, limit)
    ).fetchall()
    conn.close()
    # Brief 250: reversed() to keep the documented oldest-first output
    # contract; SELECT picks the most-recent N rows.
    return [{"id": r[0], "role": r[1], "text": r[2], "created_at": r[3]} for r in reversed(rows)]


def wa_cleanup_stale_data() -> dict:
    """Clean up old WhatsApp data. Returns counts of cleaned rows."""
    conn = _get_conn()
    now = datetime.now(timezone.utc)
    # Conversation messages >30 days
    cutoff_30d = (now - timedelta(days=30)).isoformat()
    cur = conn.execute("DELETE FROM whatsapp_threads WHERE created_at < ?", (cutoff_30d,))
    threads_cleaned = cur.rowcount
    # Processed message IDs >7 days
    cutoff_7d = (now - timedelta(days=7)).isoformat()
    cur = conn.execute("DELETE FROM whatsapp_processed WHERE created_at < ?", (cutoff_7d,))
    processed_cleaned = cur.rowcount
    conn.commit()
    conn.close()
    return {"threads_cleaned": threads_cleaned, "processed_cleaned": processed_cleaned}


def dm_store_message(conversation_id: str, channel: str, role: str, text: str,
                     sender_name: str = ""):
    """Store a DM message (IG/FB) in conversation history."""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO whatsapp_threads (phone, role, text, created_at, channel, sender_name) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (conversation_id, role, text, datetime.now(timezone.utc).isoformat(),
         channel, sender_name)
    )
    conn.commit()
    conn.close()


def dm_get_history(conversation_id: str, channel: str, limit: int = 10) -> list:
    """Get recent DM conversation history (last 24h, oldest first)."""
    conn = _get_conn()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    rows = conn.execute(
        "SELECT role, text, created_at FROM whatsapp_threads "
        "WHERE phone = ? AND channel = ? AND created_at > ? "
        "ORDER BY created_at DESC LIMIT ?",
        (conversation_id, channel, cutoff, limit)
    ).fetchall()
    conn.close()
    return [{"role": r[0], "text": r[1], "created_at": r[2]} for r in reversed(rows)]


def create_pending_notification(notification_type: str, channel: str,
                                 customer_id: str, customer_name: str,
                                 subject: str, body: str,
                                 relay_token: str = None,
                                 mode: str = None) -> int:
    """Insert (or, for an unresolved escalation, UPDATE) a pending
    notification. Brief 227: dedup unresolved escalations + structured
    summary persisted on the same row. Brief 239: optional `mode` param
    ('soft'/'hard') sets pending_notifications.mode at insert time and
    drives the alert email's Mode line. None preserves existing value
    on UPDATE (COALESCE)."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()

    # Brief 239: gate-safe initialization so non-escalation paths can
    # still compute is_update without NameError.
    existing = None
    row_id = None

    # Brief 227: dedup unresolved escalations. If a 'pending' row already
    # exists for this customer_id (escalation only), UPDATE it instead of
    # inserting a new one. Keeps the row id stable so any outstanding
    # alert thread / learning entry stays attached.
    if notification_type == "escalation":
        existing = conn.execute(
            "SELECT id FROM pending_notifications "
            "WHERE customer_id = ? AND notification_type = 'escalation' "
            "AND status IN ('pending', 'sent') "
            "ORDER BY created_at DESC LIMIT 1",
            (customer_id,)).fetchone()
        if existing:
            row_id = existing[0]

    if row_id is None:
        cur = conn.execute(
            "INSERT INTO pending_notifications "
            "(notification_type, relay_token, channel, customer_id, customer_name, "
            "subject, body, status, created_at, mode) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (notification_type, relay_token, channel, customer_id, customer_name,
             subject, body, now, mode)
        )
        row_id = cur.lastrowid
    else:
        conn.execute(
            "UPDATE pending_notifications "
            "SET subject = ?, body = ?, customer_name = ?, created_at = ?, "
            "mode = COALESCE(?, mode) "
            "WHERE id = ?",
            (subject, body, customer_name, now, mode, row_id))
    conn.commit()
    conn.close()

    # Brief 188: escalation/relay created → conversation is now "open"
    set_conversation_status(customer_id, "open", channel)

    # Brief 239: read previous summary BEFORE the new one is generated, so
    # the suppression check has both versions to compare.
    is_update = (existing is not None) and (notification_type == "escalation")
    prev_summary = None
    if is_update:
        try:
            conn = _get_conn()
            _row = conn.execute(
                "SELECT escalation_summary FROM pending_notifications "
                "WHERE id = ?", (row_id,)).fetchone()
            conn.close()
            if _row and _row[0]:
                prev_summary = json.loads(_row[0])
        except Exception:
            prev_summary = None

    # Brief 227 + 239: generate fresh structured summary BEFORE the alert
    # fires so the alert body can use it. Persisted regardless of whether
    # the alert ends up firing.
    summary_dict = None
    if notification_type == "escalation" and _summary_dispatcher is not None:
        try:
            summary_dict = _summary_dispatcher(
                row_id, channel, customer_id, customer_name)
            if summary_dict:
                conn = _get_conn()
                conn.execute(
                    "UPDATE pending_notifications SET escalation_summary = ? "
                    "WHERE id = ?",
                    (json.dumps(summary_dict), row_id))
                conn.commit()
                conn.close()
        except Exception:
            summary_dict = None

    # Brief 217 + 239: alert dispatch — suppress duplicate updates with
    # an unchanged summary. Wrapped in try/except so a dispatcher failure
    # NEVER blocks the escalation row from being saved.
    if notification_type == "escalation" and _alert_dispatcher is not None:
        should_fire = True
        if is_update and prev_summary is not None and summary_dict is not None:
            should_fire = _summaries_materially_differ(
                prev_summary, summary_dict)
        if should_fire:
            try:
                conn = _get_conn()
                _r = conn.execute(
                    "SELECT mode FROM pending_notifications WHERE id = ?",
                    (row_id,)).fetchone()
                conn.close()
                actual_mode = _r[0] if _r else None
            except Exception:
                actual_mode = None
            try:
                _alert_dispatcher(row_id, customer_name, channel, subject,
                                  mode=actual_mode,
                                  summary_dict=summary_dict,
                                  is_update=is_update)
            except Exception:
                pass

    return row_id


def set_conversation_status(conversation_id: str, status: str,
                            channel: str = "whatsapp") -> None:
    """Set or update the conversation status (pending/open/resolved).
    Uses UPSERT so the first call creates the row and subsequent calls update it."""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO conversation_status (conversation_id, channel, status, updated_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(conversation_id) DO UPDATE SET status = excluded.status, "
        "channel = excluded.channel, updated_at = excluded.updated_at",
        (conversation_id, channel, status,
         datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()


def get_conversation_status(conversation_id: str) -> str:
    """Get the current conversation status. Returns 'pending' if no record exists."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT status FROM conversation_status WHERE conversation_id = ?",
        (conversation_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else "pending"


def set_escalation_mode(escalation_id: int, mode: str) -> bool:
    """Brief 213: set the mode of a pending_notifications row. `mode` must
    be 'soft' or 'hard' (caller validates). Returns True if a row was
    updated, False if no row matched."""
    if mode not in ("soft", "hard"):
        return False
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE pending_notifications SET mode = ? WHERE id = ?",
        (mode, escalation_id))
    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def get_ai_muted(conversation_id: str) -> bool:
    """Brief 213: read the ai_muted flag from conversation_status. Returns
    False when no row exists for the conversation (default behavior is
    not muted)."""
    if not conversation_id:
        return False
    conn = _get_conn()
    row = conn.execute(
        "SELECT ai_muted FROM conversation_status WHERE conversation_id = ?",
        (conversation_id,)).fetchone()
    conn.close()
    return bool(row and row[0])


def set_ai_muted(conversation_id: str, muted: bool, channel: str = "whatsapp") -> None:
    """Brief 213: takeover/handback. UPSERTs conversation_status with
    ai_muted set, and stamps human_takeover_at when muting (NULL when
    unmuting). Preserves whatever `status` value the row already had —
    escalation status is independent from mute state."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    takeover_at = now if muted else None
    conn.execute(
        "INSERT INTO conversation_status "
        "(conversation_id, channel, status, ai_muted, human_takeover_at, updated_at) "
        "VALUES (?, ?, 'pending', ?, ?, ?) "
        "ON CONFLICT(conversation_id) DO UPDATE SET "
        "ai_muted = excluded.ai_muted, "
        "human_takeover_at = excluded.human_takeover_at, "
        "updated_at = excluded.updated_at",
        (conversation_id, channel, 1 if muted else 0, takeover_at, now))
    conn.commit()
    conn.close()


def set_blocked(conversation_id: str, blocked: bool, channel: str = ""):
    """Brief 220: flip the per-conversation blocked flag. Different from
    ai_muted: blocked drops inbound messages BEFORE any storage so the
    conversation doesn't appear in the dashboard inbox at all.
    UPSERT pattern matching set_ai_muted; channel is required for INSERT
    but ignored on UPDATE (existing rows keep their channel)."""
    if not conversation_id:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO conversation_status "
        "(conversation_id, channel, status, blocked, updated_at) "
        "VALUES (?, ?, 'pending', ?, ?) "
        "ON CONFLICT(conversation_id) DO UPDATE SET "
        "blocked = excluded.blocked, updated_at = excluded.updated_at",
        (conversation_id, channel or "", 1 if blocked else 0, now))
    conn.commit()
    conn.close()


def get_blocked(conversation_id: str) -> bool:
    """Brief 220: return True if this conversation is blocked. Hot path,
    called on every customer-message ingestion. Single-row PK lookup."""
    if not conversation_id:
        return False
    conn = _get_conn()
    row = conn.execute(
        "SELECT blocked FROM conversation_status WHERE conversation_id = ?",
        (conversation_id,)).fetchone()
    conn.close()
    return bool(row[0]) if row else False


def list_blocked_conversations() -> list:
    """Brief 220: return all currently-blocked conversations for the
    dashboard's Settings → Blocked Conversations management list.
    Each row carries camelCase keys: conversationId, channel, updatedAt."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT conversation_id, channel, updated_at FROM conversation_status "
        "WHERE blocked = 1 ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [
        {"conversationId": r[0], "channel": r[1] or "", "updatedAt": r[2]}
        for r in rows
    ]


def get_active_escalation_mode(conversation_id: str):
    """Brief 213: return the mode ('soft' / 'hard') of the most recent
    non-resolved escalation for this conversation, or None if none exist
    or the most recent has no mode set (legacy rows)."""
    if not conversation_id:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT mode FROM pending_notifications "
        "WHERE customer_id = ? AND status != 'resolved' "
        "ORDER BY created_at DESC LIMIT 1",
        (conversation_id,)).fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def get_human_takeover_at(conversation_id: str):
    """Brief 222: ISO timestamp of when the operator took over this
    conversation, or None if no active takeover. Reads
    conversation_status.human_takeover_at (set by set_ai_muted(..., True)
    in Brief 213's takeover flow, cleared to NULL on handback)."""
    if not conversation_id:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT human_takeover_at FROM conversation_status "
        "WHERE conversation_id = ?",
        (conversation_id,)).fetchone()
    conn.close()
    return row[0] if row and row[0] else None


# ── Brief 217: Alert settings + delivery audit ──

def get_resolved_operator_whatsapp_route() -> dict | None:
    """Brief 240: return the Zernio route resolved for the operator
    WhatsApp alert destination, or None if not yet bootstrapped.

    Shape: {"conversation_id": str, "account_id": str, "resolved_at": str}.
    Both conversation_id and account_id must be non-empty for the route
    to count as resolved; otherwise returns None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT whatsapp_zernio_conversation_id, "
        "whatsapp_zernio_account_id, whatsapp_zernio_resolved_at "
        "FROM alert_settings WHERE id = 1").fetchone()
    conn.close()
    if not row or not row[0] or not row[1]:
        return None
    return {
        "conversation_id": row[0],
        "account_id": row[1],
        "resolved_at": row[2] or "",
    }


def set_resolved_operator_whatsapp_route(conversation_id: str,
                                          account_id: str) -> None:
    """Brief 240: persist the Zernio route for operator WhatsApp alerts.
    UPSERTs into alert_settings - preserves the user-controlled
    whatsapp_destination + enabled flags + email columns. Idempotent:
    re-running with the same conv_id + account_id refreshes resolved_at
    only."""
    if not conversation_id or not account_id:
        return  # defensive: never persist a half-resolved route
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO alert_settings (id, whatsapp_zernio_conversation_id, "
        "whatsapp_zernio_account_id, whatsapp_zernio_resolved_at, "
        "updated_at) VALUES (1, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "whatsapp_zernio_conversation_id = excluded.whatsapp_zernio_conversation_id, "
        "whatsapp_zernio_account_id = excluded.whatsapp_zernio_account_id, "
        "whatsapp_zernio_resolved_at = excluded.whatsapp_zernio_resolved_at, "
        "updated_at = excluded.updated_at",
        (conversation_id, account_id, now, now))
    conn.commit()
    conn.close()


def get_alert_settings(default_email_destination: str = "") -> dict:
    """Brief 217 + 226: return the alert config in SR's frontend shape.
    Channels.email always carries an `alternativeDestination` field (empty
    string when not configured). If no row exists yet, synthesize a default
    with email enabled + the given default destination (typically
    business.support_email from client.json).

    The `"default"` sentinel is RESOLVED in the response — i.e., GET
    returns the actual support_email value, not the literal string
    "default" — so the frontend renders the real destination.

    Brief 241: response gains a top-level `alertTypes` block
    (`{escalations: bool, appointments: bool}`) read from the new
    alert_type_*_enabled columns. Both default True for backward compat."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT email_enabled, email_destination, whatsapp_enabled, "
        "whatsapp_destination, telegram_enabled, telegram_destination, "
        "messenger_enabled, messenger_destination, "
        "email_alternative_destination, "
        "alert_type_escalation_enabled, alert_type_appointment_enabled "
        "FROM alert_settings WHERE id = 1").fetchone()
    conn.close()
    if not row:
        return {
            "alertTypes": {"escalations": True, "appointments": True},
            "channels": {
                "email":     {"enabled": True,  "destination": default_email_destination or "",
                              "alternativeDestination": ""},
                "whatsapp":  {"enabled": False, "destination": "",
                              "zernioResolved": False},
                "telegram":  {"enabled": False, "destination": ""},
                "messenger": {"enabled": False, "destination": ""},
            }
        }
    email_dest = row[1] or ""
    if email_dest in ("", "default"):
        email_dest = default_email_destination or ""
    return {
        "alertTypes": {
            "escalations": bool(row[9]),
            "appointments": bool(row[10]),
        },
        "channels": {
            "email":     {
                "enabled": bool(row[0]),
                "destination": email_dest,
                "alternativeDestination": row[8] or "",
            },
            "whatsapp":  {
                "enabled": bool(row[2]),
                "destination": row[3] or "",
                "zernioResolved": bool(get_resolved_operator_whatsapp_route()),
            },
            "telegram":  {"enabled": bool(row[4]), "destination": row[5] or ""},
            "messenger": {"enabled": bool(row[6]), "destination": row[7] or ""},
        }
    }


def save_alert_settings(channels: dict, alert_types: dict = None) -> None:
    """Brief 217 + 226 + 241: upsert the singleton alert_settings row using
    INSERT ... ON CONFLICT(id) DO UPDATE on a fixed id=1. Brief 240:
    switched from INSERT OR REPLACE to ON CONFLICT DO UPDATE so the
    bootstrap-only whatsapp_zernio_* columns survive a Settings save.
    Brief 241: alert_types is optional ({escalations: bool, appointments:
    bool}); both default True when not supplied or missing keys."""
    now = datetime.now(timezone.utc).isoformat()
    em = channels.get("email", {}) or {}
    wa = channels.get("whatsapp", {}) or {}
    tg = channels.get("telegram", {}) or {}
    ms = channels.get("messenger", {}) or {}
    at = alert_types or {}
    ate = 1 if at.get("escalations", True) else 0
    ata = 1 if at.get("appointments", True) else 0
    conn = _get_conn()
    conn.execute(
        "INSERT INTO alert_settings "
        "(id, email_enabled, email_destination, whatsapp_enabled, whatsapp_destination, "
        "telegram_enabled, telegram_destination, messenger_enabled, messenger_destination, "
        "email_alternative_destination, "
        "alert_type_escalation_enabled, alert_type_appointment_enabled, "
        "updated_at) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "email_enabled = excluded.email_enabled, "
        "email_destination = excluded.email_destination, "
        "whatsapp_enabled = excluded.whatsapp_enabled, "
        "whatsapp_destination = excluded.whatsapp_destination, "
        "telegram_enabled = excluded.telegram_enabled, "
        "telegram_destination = excluded.telegram_destination, "
        "messenger_enabled = excluded.messenger_enabled, "
        "messenger_destination = excluded.messenger_destination, "
        "email_alternative_destination = excluded.email_alternative_destination, "
        "alert_type_escalation_enabled = excluded.alert_type_escalation_enabled, "
        "alert_type_appointment_enabled = excluded.alert_type_appointment_enabled, "
        "updated_at = excluded.updated_at",
        (1 if em.get("enabled") else 0, em.get("destination", ""),
         1 if wa.get("enabled") else 0, wa.get("destination", ""),
         1 if tg.get("enabled") else 0, tg.get("destination", ""),
         1 if ms.get("enabled") else 0, ms.get("destination", ""),
         em.get("alternativeDestination", "") or "",
         ate, ata, now))
    conn.commit()
    conn.close()


def record_alert_delivery(escalation_id, channel: str, destination: str,
                           status: str, error: str = None,
                           alert_type: str = "escalation",
                           appointment_id: int = None) -> int:
    """Brief 217 + 241: append a row to alert_deliveries. status one of
    'sent', 'failed', 'skipped'. alert_type is 'escalation' (default,
    backward compat) or 'appointment'. For appointment rows, pass
    escalation_id=None and appointment_id=<row_id>; for escalation rows,
    pass appointment_id=None (default). Returns row id."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO alert_deliveries "
        "(escalation_id, channel, destination, status, error, sent_at, "
        "alert_type, appointment_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (escalation_id, channel, destination or "", status, error, now,
         alert_type, appointment_id))
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def appointment_alert_already_sent(appointment_id: int, channel: str,
                                    destination: str) -> bool:
    """Brief 241: layer-2 dedup for appointment alerts. Returns True when
    a previous appointment-alert delivery has already been recorded for
    this exact (appointment_id, channel, destination) tuple with a
    terminal status ('sent' or 'failed'). 'skipped' rows do NOT count -
    they reflect 'we couldn't send' (e.g., Zernio route not bootstrapped
    yet) and SHOULD retry on the next confirmation event if the
    configuration changes. Layer 1 dedup is the transition-aware trigger
    inside appointment_upsert."""
    if not appointment_id:
        return False
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM alert_deliveries "
        "WHERE alert_type = 'appointment' AND appointment_id = ? "
        "AND channel = ? AND destination = ? "
        "AND status IN ('sent', 'failed') LIMIT 1",
        (appointment_id, channel, destination or "")).fetchone()
    conn.close()
    return row is not None


def email_clear_fully_escalated_flag(customer_email: str) -> int:
    """Brief 254: clear flags.fully_escalated AND flags.awaiting_relay
    on ALL email_thread_state.json threads matching this customer email.
    Used by resolve_conversation_from_escalation + delete_escalation to
    prevent orphan escalation flags after the underlying pending_notifications
    row is resolved/deleted.

    Without this cleanup, email_list_conversations derives status='escalated'
    forever from flags.get('fully_escalated') OR flags.get('awaiting_relay')
    (state_registry.py:1156-1159) and the Inbox row shows an escalation
    badge with no matching row in /escalations -- the symptom Calvin
    reported in issue #23.

    Returns the count of threads whose flags were cleared (0 if no
    matching threads OR if email_thread_state.json could not be loaded;
    callers should treat this as best-effort cleanup, not a critical
    failure path)."""
    if not customer_email:
        return 0
    path = _get_email_state_path()
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r") as f:
            state = json.load(f)
    except Exception:
        return 0
    threads = state.get("threads") or {}
    cleared = 0
    for thread_key, th in threads.items():
        # thread_key shape: "subj:{customer_email}:{normalized_subject}"
        parts = thread_key.split(":", 2)
        if len(parts) < 3 or parts[0] != "subj":
            continue
        if parts[1] != customer_email:
            continue
        flags = th.setdefault("flags", {})
        if flags.get("fully_escalated") or flags.get("awaiting_relay"):
            flags["fully_escalated"] = False
            flags.pop("awaiting_relay", None)
            cleared += 1
    if cleared == 0:
        return 0
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        return 0
    return cleared


def resolve_conversation_from_escalation(escalation_id: int) -> None:
    """Brief 188: when operator resolves an escalation, set conversation status
    to 'resolved' AND clear fully_escalated from booking state flags so the
    conversation returns to AI mode on the next customer message.

    Uses json_set() to avoid a read-modify-write cycle within this function.
    Note: a concurrent message thread that already loaded flags before this call
    may overwrite the clear via wa_save_booking_state — low severity, see brief.

    Brief 254: ALSO clears flags.fully_escalated in email_thread_state.json
    for the customer's email threads when esc_channel == 'email'. Pre-Brief-254
    the resolve path only cleared WA flags; email-channel escalations left
    orphan flags driving the Inbox status='escalated' forever (issue #23 root
    cause per Sonia's audit at issue #24)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT customer_id, channel FROM pending_notifications WHERE id = ?",
        (escalation_id,)
    ).fetchone()
    if not row:
        conn.close()
        return
    customer_id, esc_channel = row

    # Set conversation status to resolved
    conn.execute(
        "INSERT INTO conversation_status (conversation_id, channel, status, updated_at) "
        "VALUES (?, ?, 'resolved', ?) "
        "ON CONFLICT(conversation_id) DO UPDATE SET status = 'resolved', "
        "updated_at = excluded.updated_at",
        (customer_id, esc_channel or "whatsapp",
         datetime.now(timezone.utc).isoformat())
    )

    # Atomically clear fully_escalated in booking state flags
    conn.execute(
        "UPDATE whatsapp_booking_state "
        "SET flags_json = json_set(COALESCE(flags_json, '{}'), '$.fully_escalated', json('false')) "
        "WHERE phone = ?",
        (customer_id,)
    )

    conn.commit()
    conn.close()

    # Brief 254: also clear email flags when channel=email. Done OUTSIDE the
    # DB connection because email_thread_state.json is a file write.
    if esc_channel == "email" and customer_id:
        email_clear_fully_escalated_flag(customer_id)


def _lookup_customer_contact(customer_id: str, contact_type: str) -> dict:
    """Brief 183: look up the customer's real email and phone from customer_identifiers
    via the customer_id stored in the escalation. Returns {'email': ..., 'phone': ...}
    with None for any identifier not found."""
    if not customer_id:
        return {"email": None, "phone": None}

    # Determine the identifier type from contact_type
    id_type = "email" if contact_type == "email" else "wa_conversation_id" if contact_type == "whatsapp" else "phone"

    conn = _get_conn()
    # Find the customer row via their identifier
    cust_row = conn.execute(
        "SELECT customer_id FROM customer_identifiers WHERE type = ? AND value = ? LIMIT 1",
        (id_type, customer_id)
    ).fetchone()

    if not cust_row:
        conn.close()
        # If customer_id IS an email, return it directly
        if contact_type == "email":
            return {"email": customer_id, "phone": None}
        return {"email": None, "phone": None}

    cust_id = cust_row[0]

    # Get all identifiers for this customer
    idents = conn.execute(
        "SELECT type, value FROM customer_identifiers WHERE customer_id = ?",
        (cust_id,)
    ).fetchall()
    conn.close()

    email = None
    phone = None
    for ident in idents:
        if ident[0] == "email" and not email:
            email = ident[1]
        elif ident[0] == "phone" and not phone:
            phone = ident[1]

    return {"email": email, "phone": phone}


def _infer_contact_type(customer_id: str) -> str:
    """Brief 181: infer the type of contact identifier for display purposes.
    Replicates the 24-char hex check from whatsapp_client._is_zernio_conversation_id
    (duplicated here to avoid circular import between state_registry and whatsapp_client)."""
    if not customer_id:
        return "unknown"
    if "@" in customer_id:
        return "email"
    if len(customer_id) == 24:
        try:
            int(customer_id, 16)
            return "whatsapp"
        except ValueError:
            pass
    return "phone"


def get_all_escalations() -> list:
    """Return all escalation notifications, newest first.
    Brief 181: contact_type. Brief 183: customer_contact. Brief 188:
    conversation_status. Brief 213: mode. Brief 211: routable phone field.
    Brief 227: escalation_summary parsed and surfaced as escalationSummary +
    recommendedOptions + extractedDetails.
    Brief 253: excludes escalations whose WhatsApp/IG/FB conversation has
    been archived via Brief 249's archive endpoint
    (conversation_status.deleted=1). Email-channel archives use a
    different mechanism (flags.deleted in email_thread_state.json) and
    are NOT filtered by this JOIN -- see Brief 253 out-of-scope notes."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT pn.id, pn.notification_type, pn.relay_token, pn.channel, "
        "pn.customer_id, pn.customer_name, pn.subject, pn.body, pn.status, "
        "pn.created_at, pn.mode, pn.escalation_summary "
        "FROM pending_notifications pn "
        # Brief 253: LEFT JOIN to drop escalations on archived conversations.
        # LEFT JOIN preserves rows whose conversation has no
        # conversation_status entry at all (most active conversations).
        "LEFT JOIN conversation_status cs ON pn.customer_id = cs.conversation_id "
        "WHERE cs.deleted IS NULL OR cs.deleted = 0 "
        "ORDER BY pn.created_at DESC"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        ct = _infer_contact_type(r[4] or "")
        contact = _lookup_customer_contact(r[4] or "", ct)
        customer_contact = contact["email"] or contact["phone"] or r[4] or ""
        if r[3] == "email":
            _email_thread_key = _find_email_thread_key_for(r[4])
            _phone_routing_key = f"email::{_email_thread_key}" if _email_thread_key else (r[4] or "")
        else:
            _phone_routing_key = r[4] or ""

        # Brief 227: parse the JSON summary blob into structured fields.
        summary_obj = None
        if r[11]:
            try:
                summary_obj = json.loads(r[11])
            except (json.JSONDecodeError, TypeError):
                summary_obj = None

        result.append({
            "id": r[0], "notification_type": r[1], "relay_token": r[2],
            "channel": r[3], "customer_id": r[4], "customer_name": r[5],
            "subject": r[6], "body": r[7], "status": r[8], "created_at": r[9],
            "mode": r[10],
            "contact_type": ct,
            "customer_contact": customer_contact,
            "customer_email": contact["email"],
            "customer_phone": contact["phone"],
            "conversation_status": get_conversation_status(r[4]),
            "phone": _phone_routing_key,
            "escalationSummary": summary_obj,
            "recommendedOptions": (
                (summary_obj or {}).get("recommendedOptions") or []),
            "extractedDetails": (
                (summary_obj or {}).get("extractedDetails") or None),
        })
    return result


def get_active_escalation_summary_for(customer_id: str) -> Optional[dict]:
    """Brief 227: return the parsed escalation_summary dict for the most
    recent unresolved escalation on this conversation, or None.

    Used by GET /messages/conversations/:phone to enrich the response
    with escalationSummary so the frontend's EscalationReasonPanel can
    render without a second fetch."""
    if not customer_id:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT escalation_summary FROM pending_notifications "
        "WHERE customer_id = ? AND notification_type = 'escalation' "
        "AND status IN ('pending', 'sent') "
        "ORDER BY created_at DESC LIMIT 1",
        (customer_id,)).fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return None


def appointment_upsert(conversation_id: str, channel: str, customer_name: str,
                       title: str, proposed_times: list, location: str = "",
                       status: str = "detected",
                       date_time_label: str = None) -> int:
    """Brief 228: upsert an appointment row keyed on conversation_id.
    proposed_times is a list of strings; we store JSON.

    Brief 248: date_time_label is the headline time string the frontend
    displays. When supplied (e.g., the customer's explicit confirmation
    extracted by the Brief 248 confirmedTime schema field), use it
    verbatim. When None (legacy callers like Brief 242's
    appointment_confirm_by_id), fall back to the first proposed_time -
    preserves pre-Brief-248 behavior so existing callers don't change.

    Brief 241: when this call transitions the appointment INTO 'confirmed'
    (insert with status='confirmed', OR update from a non-confirmed status
    to 'confirmed'), fire the registered _appointment_alert_dispatcher
    best-effort. Re-saves of the same 'confirmed' status do NOT fire
    (transition detection)."""
    if not conversation_id:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    pt = proposed_times or []
    # Brief 248: explicit override wins; otherwise fall back to first
    # proposed time (pre-Brief-248 behavior preserved for callers that
    # don't supply date_time_label, e.g. appointment_confirm_by_id).
    label = date_time_label if date_time_label is not None else (pt[0] if pt else "")
    conn = _get_conn()
    existing = conn.execute(
        "SELECT id, status FROM appointments WHERE conversation_id = ?",
        (conversation_id,)).fetchone()
    transitioned_to_confirmed = False
    if existing:
        old_status = existing[1] or ""
        conn.execute(
            "UPDATE appointments SET channel = ?, customer_name = ?, "
            "title = ?, date_time_label = ?, proposed_times_json = ?, "
            "location = ?, status = ?, updated_at = ? "
            "WHERE id = ?",
            (channel, customer_name, title, label, json.dumps(pt),
             location, status, now, existing[0]))
        row_id = existing[0]
        if old_status != "confirmed" and status == "confirmed":
            transitioned_to_confirmed = True
    else:
        cur = conn.execute(
            "INSERT INTO appointments "
            "(conversation_id, channel, customer_name, title, date_time_label, "
            "proposed_times_json, location, status, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'conversation', ?, ?)",
            (conversation_id, channel, customer_name, title, label,
             json.dumps(pt), location, status, now, now))
        row_id = cur.lastrowid
        if status == "confirmed":
            transitioned_to_confirmed = True
    conn.commit()
    conn.close()

    # Brief 241: best-effort appointment alert dispatch on transition.
    # Wrapped in try/except so a dispatcher failure NEVER blocks the
    # appointment row from being saved. Tenant gate: alertTypes.appointments
    # in alert_settings; default True (on).
    if transitioned_to_confirmed and _appointment_alert_dispatcher is not None:
        try:
            settings = get_alert_settings(default_email_destination="")
            alert_types = (settings or {}).get("alertTypes") or {}
            if alert_types.get("appointments", True):
                appointment_dict = {
                    "id": row_id,
                    "conversation_id": conversation_id,
                    "channel": channel,
                    "customer_name": customer_name,
                    "title": title,
                    "date_time_label": label,
                    "proposed_times": pt,
                    "location": location,
                    "status": "confirmed",
                }
                _appointment_alert_dispatcher(
                    row_id, customer_name, channel, appointment_dict)
        except Exception:
            pass

    return row_id


def appointment_confirm_by_id(appointment_id: int,
                               confirmed_by: str = "operator",
                               note: str | None = None) -> dict | None:
    """Brief 242: flip an appointment's status to 'confirmed' by id.
    Re-uses appointment_upsert (keyed on conversation_id) so the Brief
    241 transition detection fires the appointment alert dispatcher
    exactly once - second/duplicate confirm calls find old_status ==
    'confirmed' and the transition guard correctly classifies them as
    no-fire.

    Returns:
        {"id": int, "status": "confirmed", "confirmedAt": iso_str,
         "alreadyConfirmed": bool} on success.
        None when no appointment row matches the given id (caller
        surfaces 404).

    confirmed_by + note are accepted for forward API compat (frontend
    can pass operator identity / note text) but are NOT persisted in
    this brief - no schema column for them yet. A future brief can
    ALTER ADD COLUMN if an audit trail of WHO confirmed is needed.

    Soft coupling note: the confirmedAt timestamp is read from the
    appointments.updated_at column AFTER the upsert - this works
    because appointment_upsert always bumps updated_at (even on
    no-op confirmed->confirmed re-saves at line 2152). If a future
    refactor makes appointment_upsert skip the UPDATE on no-op,
    confirmedAt for alreadyConfirmed=True callers would become
    stale and need explicit recomputation here."""
    if not appointment_id:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, conversation_id, channel, customer_name, title, "
        "proposed_times_json, location, status "
        "FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
    conn.close()
    if not row:
        return None
    (rid, conv_id, channel, customer_name, title, ptj, location,
     old_status) = row
    already_confirmed = (old_status == "confirmed")
    try:
        proposed_times = json.loads(ptj) if ptj else []
    except (json.JSONDecodeError, TypeError):
        proposed_times = []
    appointment_upsert(
        conversation_id=conv_id,
        channel=channel,
        customer_name=customer_name or "",
        title=title or "",
        proposed_times=proposed_times,
        location=location or "",
        status="confirmed",
    )
    conn = _get_conn()
    ts_row = conn.execute(
        "SELECT updated_at FROM appointments WHERE id = ?",
        (appointment_id,)).fetchone()
    conn.close()
    confirmed_at = ts_row[0] if ts_row else datetime.now(
        timezone.utc).isoformat()
    return {
        "id": rid,
        "status": "confirmed",
        "confirmedAt": confirmed_at,
        "alreadyConfirmed": already_confirmed,
    }


def appointments_list() -> list:
    """Brief 228: return all appointments newest-updated first, in the
    shape SR's frontend expects (camelCase, ISO timestamps).
    proposed_times_json is parsed and surfaced as proposedTimes for
    detail views; date_time_label is the headline string."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, conversation_id, channel, customer_name, title, "
        "date_time_label, proposed_times_json, location, status, source, "
        "created_at, updated_at "
        "FROM appointments ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            proposed = json.loads(r[6]) if r[6] else []
        except (json.JSONDecodeError, TypeError):
            proposed = []
        out.append({
            "id": str(r[0]),
            "conversationId": r[1],
            "channel": r[2],
            "customerName": r[3] or "",
            "title": r[4] or "Appointment",
            "dateTimeLabel": r[5] or "",
            "proposedTimes": proposed,
            "location": r[7] or None,
            "status": r[8],
            "source": r[9] or "conversation",
            "createdAt": r[10],
            "updatedAt": r[11],
        })
    return out


def get_data_retention_settings() -> dict:
    """Brief 229: return retention settings in SR's frontend shape
    (camelCase, status.policyActive=false until cleanup is implemented).
    Synthesizes a default row when none exists yet — defaults match
    SR's `DEFAULT_DATA_RETENTION` constant verbatim."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT active_inbox_archive_after_days, archive_retention_months, "
        "end_of_retention_action, keep_approved_learnings, "
        "audit_log_retention_months FROM data_retention_settings WHERE id = 1"
    ).fetchone()
    conn.close()
    # Brief 237: policyActive stays False until automatic cron ships in
    # a future brief. manualActionsAvailable=True signals the 3 action
    # endpoints (archive-now / export / delete-customer-data) are live.
    _STATUS = {
        "policyActive": False,
        "manualActionsAvailable": True,
        "nextCleanupAt": None,
    }
    if not row:
        return {
            "activeInboxArchiveAfterDays": 90,
            "archiveRetentionMonths": 24,
            "endOfRetentionAction": "anonymize",
            "keepApprovedLearnings": True,
            "auditLogRetentionMonths": 24,
            "status": dict(_STATUS),
        }
    return {
        "activeInboxArchiveAfterDays": row[0],
        "archiveRetentionMonths": row[1],
        "endOfRetentionAction": row[2] or "anonymize",
        "keepApprovedLearnings": bool(row[3]),
        "auditLogRetentionMonths": row[4] or 24,
        "status": dict(_STATUS),
    }


def save_data_retention_settings(active_inbox_archive_after_days,
                                  archive_retention_months,
                                  end_of_retention_action: str,
                                  keep_approved_learnings: bool,
                                  audit_log_retention_months: int) -> None:
    """Brief 229: upsert the singleton retention settings row at id=1
    (mirrors Brief 217's INSERT OR REPLACE pattern). Caller is
    responsible for validating discrete value sets — this helper trusts
    its inputs."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO data_retention_settings "
        "(id, active_inbox_archive_after_days, archive_retention_months, "
        "end_of_retention_action, keep_approved_learnings, "
        "audit_log_retention_months, updated_at) "
        "VALUES (1, ?, ?, ?, ?, ?, ?)",
        (active_inbox_archive_after_days, archive_retention_months,
         end_of_retention_action,
         1 if keep_approved_learnings else 0,
         audit_log_retention_months, now))
    conn.commit()
    conn.close()


def data_retention_audit_write(action: str, identifier_type, identifier_value,
                                affected_counts: dict, actor: str = "dashboard") -> int:
    """Brief 237: record a retention action attempt to data_retention_audit_log.
    Called for archive-now / export / delete-customer-data (success AND blocked).
    Rule 10 of SR's task ab7d8f1eb97c."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO data_retention_audit_log "
        "(action, identifier_type, identifier_value, affected_counts_json, "
        "actor, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (action, identifier_type, identifier_value,
         json.dumps(affected_counts or {}, default=str),
         actor, now))
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def archive_inactive_conversations(active_inbox_archive_after_days: int) -> dict:
    """Brief 237: archive-now sweep. Sets flags.deleted on email threads
    inactive longer than N days; upserts conversation_status.deleted=1 on
    WhatsApp/IG/FB. Skips active escalations (Brief 235's pending|sent
    filter) and human takeover (ai_muted / fully_escalated). Returns
    counts."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=active_inbox_archive_after_days)
    archived = 0
    skipped_escalation = 0
    skipped_takeover = 0
    already_archived = 0

    # Email side — load JSON, mutate, atomic replace.
    email_path = _get_email_state_path()
    if os.path.exists(email_path):
        try:
            with open(email_path, "r") as f:
                state = json.load(f)
        except Exception:
            state = None
        if state:
            now_iso = datetime.now(timezone.utc).isoformat()
            for thread_key, th in state.get("threads", {}).items():
                flags = th.setdefault("flags", {})
                if flags.get("deleted"):
                    already_archived += 1
                    continue
                if flags.get("fully_escalated"):
                    skipped_escalation += 1
                    continue
                if flags.get("ai_muted"):
                    skipped_takeover += 1
                    continue
                last_raw = th.get("last_activity")
                if last_raw is None:
                    continue
                if isinstance(last_raw, str):
                    try:
                        last_dt = datetime.fromisoformat(last_raw)
                    except ValueError:
                        continue
                else:
                    last_dt = datetime.fromtimestamp(float(last_raw), tz=timezone.utc)
                if last_dt < cutoff:
                    flags["deleted"] = True
                    th["last_activity"] = now_iso
                    archived += 1
            try:
                tmp = email_path + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
                os.replace(tmp, email_path)
            except OSError:
                pass

    # WA/IG/FB side — group by phone, find max(created_at), check active escalations.
    conn = _get_conn()
    rows = conn.execute(
        "SELECT phone, MAX(created_at) FROM whatsapp_threads GROUP BY phone"
    ).fetchall()
    now_iso = datetime.now(timezone.utc).isoformat()
    for phone, max_created in rows:
        if not max_created:
            continue
        try:
            last_dt = datetime.fromisoformat(max_created)
        except ValueError:
            continue
        if last_dt >= cutoff:
            continue
        cs = conn.execute(
            "SELECT deleted, blocked, ai_muted FROM conversation_status "
            "WHERE conversation_id = ?", (phone,)
        ).fetchone()
        if cs:
            deleted_flag, blocked_flag, ai_muted_flag = cs
            if deleted_flag:
                already_archived += 1
                continue
            if blocked_flag:
                already_archived += 1
                continue
            if ai_muted_flag:
                skipped_takeover += 1
                continue
        active_esc = conn.execute(
            "SELECT 1 FROM pending_notifications WHERE customer_id = ? "
            "AND status IN ('pending', 'sent') LIMIT 1", (phone,)
        ).fetchone()
        if active_esc:
            skipped_escalation += 1
            continue
        conn.execute(
            "INSERT INTO conversation_status "
            "(conversation_id, channel, status, updated_at, deleted) "
            "VALUES (?, 'whatsapp', 'archived', ?, 1) "
            "ON CONFLICT(conversation_id) DO UPDATE SET deleted = 1, "
            "updated_at = excluded.updated_at",
            (phone, now_iso))
        archived += 1
    conn.commit()
    conn.close()
    return {
        "archivedCount": archived,
        "skippedActiveEscalation": skipped_escalation,
        "skippedHumanTakeover": skipped_takeover,
        "alreadyArchived": already_archived,
    }


def export_all_customer_data(export_dir: str, tenant: str) -> dict:
    """Brief 237: dump all customer-side data to a JSON file under
    export_dir. Returns the path + per-table counts. Approved learnings
    and tasks are intentionally excluded — those are operator-curated."""
    now_iso = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(export_dir, f"{tenant}-{now_iso}.json")
    conn = _get_conn()

    def _rows(sql):
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    payload = {
        "tenant": tenant,
        "exportedAt": now_iso,
        "customers": _rows("SELECT * FROM customers"),
        "customer_identifiers": _rows("SELECT * FROM customer_identifiers"),
        "customer_interactions": _rows("SELECT * FROM customer_interactions"),
        "whatsapp_threads": _rows("SELECT * FROM whatsapp_threads"),
        "pending_notifications": _rows("SELECT * FROM pending_notifications"),
        "appointments": _rows("SELECT * FROM appointments"),
        "bookings": _rows("SELECT * FROM bookings"),
        "service_bookings": _rows("SELECT * FROM service_bookings"),
        "conversation_status": _rows("SELECT * FROM conversation_status"),
    }
    conn.close()

    # Email JSON state (no DB table).
    email_path = _get_email_state_path()
    if os.path.exists(email_path):
        try:
            with open(email_path, "r") as f:
                payload["email_threads"] = json.load(f)
        except Exception:
            payload["email_threads"] = {}
    else:
        payload["email_threads"] = {}

    counts = {k: len(v) if isinstance(v, list) else 1
              for k, v in payload.items() if k not in ("tenant", "exportedAt")}

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)

    return {
        "exportPath": path,
        "recordCounts": counts,
        "exportedAt": now_iso,
    }


def delete_customer_data(identifier_value: str, identifier_type: str,
                          action: str, keep_approved_learnings: bool) -> dict:
    """Brief 237: apply endOfRetentionAction (delete | anonymize) to a
    specific customer's data. Active-escalation guard: refuses if the
    customer has any pending/sent notification. keep_approved_learnings
    preserves escalation_learnings (info_updates is tenant-wide
    business announcements with no per-customer FK, so it is never
    touched by this helper regardless of the flag)."""
    if action not in ("delete", "anonymize"):
        return {"ok": False, "reason": f"invalid_action:{action}"}

    conn = _get_conn()
    # Resolve the customer's integer PK + every text identifier they were
    # ever filed under (per-table FKs are inconsistent: pending_notifications
    # uses TEXT, customer_interactions uses INTEGER FK).
    row = conn.execute(
        "SELECT customer_id FROM customer_identifiers WHERE type = ? AND value = ? LIMIT 1",
        (identifier_type, identifier_value)
    ).fetchone()
    if not row:
        conn.close()
        return {"ok": True, "action": action, "deletedCount": 0,
                "anonymizedCount": 0, "reason": "no_such_customer"}
    cust_pk = row[0]
    ident_rows = conn.execute(
        "SELECT type, value FROM customer_identifiers WHERE customer_id = ?",
        (cust_pk,)).fetchall()
    phones = {v for t, v in ident_rows if t in ("phone", "wa_conversation_id")}
    emails = {v for t, v in ident_rows if t == "email"}
    conv_ids = phones | {v for t, v in ident_rows if t == "conversation_id"}
    text_keys = list(conv_ids | emails)

    # Active-escalation guard (Rule 8). Filter status IN ('pending','sent')
    # per Brief 235 — production transitions pending→sent on insert.
    if text_keys:
        placeholders = ",".join("?" for _ in text_keys)
        active = conn.execute(
            f"SELECT 1 FROM pending_notifications WHERE customer_id IN ({placeholders}) "
            f"AND status IN ('pending', 'sent') LIMIT 1",
            text_keys
        ).fetchone()
        if active:
            conn.close()
            return {"ok": False, "reason": "active_escalation"}

    deleted = 0
    anonymized = 0
    skipped_learnings = 0

    if action == "delete":
        # WA/IG/FB messages by phone identifiers
        if phones:
            ph = list(phones)
            placeholders = ",".join("?" for _ in ph)
            cur = conn.execute(
                f"DELETE FROM whatsapp_threads WHERE phone IN ({placeholders})", ph)
            deleted += cur.rowcount
        # pending_notifications (only resolved — active was already guarded)
        if text_keys:
            placeholders = ",".join("?" for _ in text_keys)
            cur = conn.execute(
                f"DELETE FROM pending_notifications WHERE customer_id IN "
                f"({placeholders}) AND status NOT IN ('pending', 'sent')",
                text_keys)
            deleted += cur.rowcount
            cur = conn.execute(
                f"DELETE FROM appointments WHERE conversation_id IN ({placeholders})",
                text_keys)
            deleted += cur.rowcount
            cur = conn.execute(
                f"DELETE FROM conversation_status WHERE conversation_id IN ({placeholders})",
                text_keys)
            deleted += cur.rowcount
        # customer_interactions uses INTEGER FK
        cur = conn.execute(
            "DELETE FROM customer_interactions WHERE customer_id = ?", (cust_pk,))
        deleted += cur.rowcount
        # bookings/service_bookings use INTEGER FK (best-effort — schema may differ)
        try:
            cur = conn.execute("DELETE FROM bookings WHERE customer_id = ?", (cust_pk,))
            deleted += cur.rowcount
        except sqlite3.OperationalError:
            pass
        try:
            cur = conn.execute("DELETE FROM service_bookings WHERE customer_id = ?", (cust_pk,))
            deleted += cur.rowcount
        except sqlite3.OperationalError:
            pass
        # Approved learnings — preserve if flag is set
        if not keep_approved_learnings and text_keys:
            placeholders = ",".join("?" for _ in text_keys)
            try:
                cur = conn.execute(
                    f"DELETE FROM escalation_learnings WHERE conversation_id IN ({placeholders})",
                    text_keys)
                deleted += cur.rowcount
            except sqlite3.OperationalError:
                pass
        else:
            # count what we skipped, for reporting
            if text_keys:
                placeholders = ",".join("?" for _ in text_keys)
                try:
                    cnt = conn.execute(
                        f"SELECT COUNT(*) FROM escalation_learnings WHERE conversation_id IN ({placeholders})",
                        text_keys).fetchone()[0]
                    skipped_learnings = cnt or 0
                except sqlite3.OperationalError:
                    pass
        # Drop identifiers + customer row last
        cur = conn.execute(
            "DELETE FROM customer_identifiers WHERE customer_id = ?", (cust_pk,))
        deleted += cur.rowcount
        cur = conn.execute("DELETE FROM customers WHERE id = ?", (cust_pk,))
        deleted += cur.rowcount

    else:  # anonymize
        REDACTED = "[redacted]"
        REDACTED_MSG = "[redacted message]"
        cur = conn.execute(
            "UPDATE customers SET display_name = ? WHERE id = ?",
            (REDACTED, cust_pk))
        anonymized += cur.rowcount
        cur = conn.execute(
            "UPDATE customer_identifiers SET value = ? WHERE customer_id = ?",
            (REDACTED, cust_pk))
        anonymized += cur.rowcount
        if phones:
            ph = list(phones)
            placeholders = ",".join("?" for _ in ph)
            cur = conn.execute(
                f"UPDATE whatsapp_threads SET text = ?, sender_name = ? "
                f"WHERE phone IN ({placeholders})",
                [REDACTED_MSG, REDACTED] + ph)
            anonymized += cur.rowcount
        if not keep_approved_learnings and text_keys:
            placeholders = ",".join("?" for _ in text_keys)
            try:
                cur = conn.execute(
                    f"UPDATE escalation_learnings SET human_answer = ? "
                    f"WHERE conversation_id IN ({placeholders})",
                    [REDACTED] + text_keys)
                anonymized += cur.rowcount
            except sqlite3.OperationalError:
                pass
        else:
            if text_keys:
                placeholders = ",".join("?" for _ in text_keys)
                try:
                    cnt = conn.execute(
                        f"SELECT COUNT(*) FROM escalation_learnings WHERE conversation_id IN ({placeholders})",
                        text_keys).fetchone()[0]
                    skipped_learnings = cnt or 0
                except sqlite3.OperationalError:
                    pass

    conn.commit()
    conn.close()

    # Email JSON state — both delete and anonymize touch it.
    email_path = _get_email_state_path()
    if os.path.exists(email_path) and emails:
        try:
            with open(email_path, "r") as f:
                state = json.load(f)
        except Exception:
            state = None
        if state:
            threads = state.get("threads", {})
            to_drop = []
            for tk, th in threads.items():
                from_email = (th.get("from_email") or "").lower()
                if from_email in {e.lower() for e in emails}:
                    if action == "delete":
                        to_drop.append(tk)
                    else:
                        th["from_email"] = "[redacted]"
                        for m in th.get("messages", []) or []:
                            m["text"] = "[redacted message]"
                            if "from_email" in m:
                                m["from_email"] = "[redacted]"
            if action == "delete":
                for tk in to_drop:
                    threads.pop(tk, None)
                    if action == "delete":
                        deleted += 1
            else:
                anonymized += len([1 for tk, th in threads.items()
                                   if (th.get("from_email") or "") == "[redacted]"])
            try:
                tmp = email_path + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
                os.replace(tmp, email_path)
            except OSError:
                pass

    return {
        "ok": True,
        "action": action,
        "deletedCount": deleted,
        "anonymizedCount": anonymized,
        "skippedLearnings": skipped_learnings,
    }


def knowledge_file_create(filename: str, stored_filename: str, mime_type: str,
                           size_bytes: int, status: str, extracted_text: str,
                           failure_reason: str = "") -> int:
    """Brief 230: insert a knowledge_files row at upload time. Returns id."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO knowledge_files "
        "(filename, stored_filename, mime_type, size_bytes, status, "
        "extracted_text, failure_reason, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (filename, stored_filename, mime_type, size_bytes, status,
         extracted_text, failure_reason, now))
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def knowledge_files_list() -> list:
    """Brief 230: return all knowledge files in SR's frontend shape
    (camelCase, ISO timestamps). extracted_text + failure_reason are NOT
    surfaced — operator UI doesn't need to render them."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, filename, mime_type, size_bytes, status, uploaded_at, "
        "last_used_at FROM knowledge_files ORDER BY uploaded_at DESC"
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "id": str(r[0]),
            "filename": r[1],
            "mimeType": r[2] or "",
            "sizeBytes": r[3],
            "status": r[4],
            "uploadedAt": r[5],
            "lastUsedAt": r[6],
        })
    return out


def knowledge_file_delete(file_id: int) -> Optional[str]:
    """Brief 230: hard-delete a knowledge_files row. Returns the
    stored_filename so the caller can also unlink the file from disk
    (registry stays disk-agnostic). Returns None if the id doesn't exist."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT stored_filename FROM knowledge_files WHERE id = ?",
        (file_id,)).fetchone()
    if not row:
        conn.close()
        return None
    stored = row[0]
    conn.execute("DELETE FROM knowledge_files WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()
    return stored


def get_knowledge_files_for_prompt(limit: int = 5) -> list:
    """Brief 230: return up to `limit` ready knowledge files with their
    extracted text, newest first. Used by Marina's _build_knowledge_files_block."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT filename, extracted_text FROM knowledge_files "
        "WHERE status = 'ready' AND extracted_text != '' "
        "ORDER BY uploaded_at DESC LIMIT ?",
        (limit,)).fetchall()
    conn.close()
    return [{"filename": r[0], "text": r[1]} for r in rows]


def get_pending_notifications(status: str = "pending") -> list:
    """Return all notifications with the given status.
    Brief 183: enriched with customer_contact, customer_email, customer_phone."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, notification_type, relay_token, channel, customer_id, "
        "customer_name, subject, body, status, created_at "
        "FROM pending_notifications WHERE status = ? ORDER BY created_at ASC",
        (status,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        ct = _infer_contact_type(r[4] or "")
        contact = _lookup_customer_contact(r[4] or "", ct)
        customer_contact = contact["email"] or contact["phone"] or r[4] or ""
        result.append({
            "id": r[0], "notification_type": r[1], "relay_token": r[2],
            "channel": r[3], "customer_id": r[4], "customer_name": r[5],
            "subject": r[6], "body": r[7], "status": r[8], "created_at": r[9],
            "contact_type": ct,
            "customer_contact": customer_contact,
            "customer_email": contact["email"],
            "customer_phone": contact["phone"],
        })
    return result


def delete_escalation(escalation_id: int) -> bool:
    """Brief 172: hard-delete a pending_notifications row. Returns True if a
    row was deleted. Used by the dashboard Escalations page trash button (SR's
    UX — archive first, then from archive view you can delete permanently).

    Brief 254: BEFORE the DELETE, clear orphan escalation state via
    resolve_conversation_from_escalation so:
      - conversation_status.status flips to 'resolved' (drives email detail's
        escalated=false), and
      - whatsapp_booking_state.flags_json.fully_escalated cleared (drives WA),
      - email_thread_state.json.flags.fully_escalated cleared (drives email list).
    Without this cleanup the dashboard shows escalated=true forever with
    no matching /escalations row -- issue #23 root cause."""
    # Brief 254: clear orphan flags BEFORE the DELETE.
    # resolve_conversation_from_escalation reads customer_id + channel from
    # the row, so it must run while the row still exists.
    resolve_conversation_from_escalation(escalation_id)

    conn = _get_conn()
    cur = conn.execute("DELETE FROM pending_notifications WHERE id = ?", (escalation_id,))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def update_notification_status(notification_id: int, status: str) -> bool:
    """Update the status of a pending notification. Returns True if row updated."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE pending_notifications SET status = ? WHERE id = ?",
        (status, notification_id)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def get_relay_by_token(relay_token: str) -> "dict | None":
    """Look up an actionable relay notification by token. Returns dict or None.
    Matches 'pending' (not yet emailed) and 'sent' (emailed, awaiting reply).
    Excludes 'replied' to prevent double-fire."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, notification_type, relay_token, channel, customer_id, "
        "customer_name, subject, body, status, created_at "
        "FROM pending_notifications WHERE relay_token = ? AND status IN ('pending', 'sent')",
        (relay_token,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "notification_type": row[1], "relay_token": row[2],
            "channel": row[3], "customer_id": row[4], "customer_name": row[5],
            "subject": row[6], "body": row[7], "status": row[8], "created_at": row[9]}


def save_content_draft(content_class: str, instagram_caption: str,
                       facebook_caption: str, hashtags: list,
                       visual_suggestion: str, reasoning: str,
                       twitter_caption: str = "") -> int:
    """Save a content draft. Returns row id."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO content_drafts "
        "(content_class, instagram_caption, facebook_caption, twitter_caption, "
        "hashtags_json, visual_suggestion, reasoning, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
        (content_class, instagram_caption, facebook_caption, twitter_caption,
         json.dumps(hashtags, ensure_ascii=False), visual_suggestion, reasoning,
         datetime.now(timezone.utc).isoformat())
    )
    draft_id = cur.lastrowid
    conn.commit()
    conn.close()
    return draft_id


def get_content_drafts(status: str = None, limit: int = 50) -> list:
    """Get content drafts, optionally filtered by status. Newest first."""
    conn = _get_conn()
    if status:
        rows = conn.execute(
            "SELECT id, content_class, instagram_caption, facebook_caption, twitter_caption, "
            "hashtags_json, visual_suggestion, reasoning, status, rejection_reason, "
            "created_at, approved_at, published_at, image_path, late_post_id, instagram_url, photo_id, "
            "platforms_json, facebook_url, late_facebook_post_id, scheduled_at "
            "FROM content_drafts WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, content_class, instagram_caption, facebook_caption, twitter_caption, "
            "hashtags_json, visual_suggestion, reasoning, status, rejection_reason, "
            "created_at, approved_at, published_at, image_path, late_post_id, instagram_url, photo_id, "
            "platforms_json, facebook_url, late_facebook_post_id, scheduled_at "
            "FROM content_drafts ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "content_class": r[1], "instagram_caption": r[2],
            "facebook_caption": r[3], "twitter_caption": r[4] or "",
            "hashtags": json.loads(r[5] or "[]"),
            "visual_suggestion": r[6], "reasoning": r[7], "status": r[8],
            "rejection_reason": r[9], "created_at": r[10], "approved_at": r[11],
            "published_at": r[12], "image_path": r[13],
            "late_post_id": r[14], "instagram_url": r[15],
            "photo_id": r[16] if len(r) > 16 else 0,
            "platforms": json.loads(r[17]) if len(r) > 17 and r[17] else ["instagram"],
            "facebook_url": r[18] if len(r) > 18 else "",
            "late_facebook_post_id": r[19] if len(r) > 19 else "",
            "scheduled_at": r[20] if len(r) > 20 else None,
        }
        for r in rows
    ]


def update_draft_status(draft_id: int, status: str,
                        rejection_reason: str = "") -> bool:
    """Update draft status. For 'approved', sets approved_at. For 'published', sets published_at.
    For 'rejected', stores rejection_reason. Returns True if row updated."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    if status == "approved":
        cur = conn.execute(
            "UPDATE content_drafts SET status = ?, approved_at = ? WHERE id = ?",
            (status, now, draft_id)
        )
    elif status == "published":
        cur = conn.execute(
            "UPDATE content_drafts SET status = ?, published_at = ? WHERE id = ?",
            (status, now, draft_id)
        )
    elif status == "rejected":
        cur = conn.execute(
            "UPDATE content_drafts SET status = ?, rejection_reason = ? WHERE id = ?",
            (status, rejection_reason, draft_id)
        )
    else:
        cur = conn.execute(
            "UPDATE content_drafts SET status = ? WHERE id = ?",
            (status, draft_id)
        )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def update_draft_content(draft_id: int, instagram_caption: str = None,
                         facebook_caption: str = None, hashtags: list = None,
                         twitter_caption: str = None) -> bool:
    """Update draft content fields. Only works on pending drafts.
    Only updates non-None params. Returns True if row updated."""
    sets = []
    params = []
    if instagram_caption is not None:
        sets.append("instagram_caption = ?")
        params.append(instagram_caption)
    if facebook_caption is not None:
        sets.append("facebook_caption = ?")
        params.append(facebook_caption)
    if twitter_caption is not None:
        sets.append("twitter_caption = ?")
        params.append(twitter_caption)
    if hashtags is not None:
        sets.append("hashtags_json = ?")
        params.append(json.dumps(hashtags, ensure_ascii=False))
    if not sets:
        return False
    params.append(draft_id)
    conn = _get_conn()
    cur = conn.execute(
        f"UPDATE content_drafts SET {', '.join(sets)} WHERE id = ? AND status = 'pending'",
        tuple(params)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


# --- Photo Library ---


def save_photo(filename: str, original_filename: str, tags: list,
               service_key: str = "", source: str = "upload",
               source_id: str = "", width: int = 0, height: int = 0,
               file_size: int = 0) -> int:
    """Save a photo record. Returns row id."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO photo_library "
        "(filename, original_filename, tags_json, service_key, source, source_id, "
        "width, height, file_size, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (filename, original_filename, json.dumps(tags, ensure_ascii=False),
         service_key, source, source_id, width, height, file_size,
         datetime.now(timezone.utc).isoformat())
    )
    photo_id = cur.lastrowid
    conn.commit()
    conn.close()
    return photo_id


def get_photos(service_key: str = None, limit: int = 50) -> list:
    """Get photos, optionally filtered by service_key. Newest first."""
    conn = _get_conn()
    if service_key:
        rows = conn.execute(
            "SELECT id, filename, original_filename, tags_json, service_key, "
            "source, source_id, width, height, file_size, used_count, uploaded_at "
            "FROM photo_library WHERE service_key = ? ORDER BY uploaded_at DESC LIMIT ?",
            (service_key, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, filename, original_filename, tags_json, service_key, "
            "source, source_id, width, height, file_size, used_count, uploaded_at "
            "FROM photo_library ORDER BY uploaded_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "filename": r[1], "original_filename": r[2],
            "tags": json.loads(r[3] or "[]"), "service_key": r[4],
            "source": r[5], "source_id": r[6], "width": r[7],
            "height": r[8], "file_size": r[9], "used_count": r[10],
            "uploaded_at": r[11],
        }
        for r in rows
    ]


def get_photo_by_id(photo_id: int) -> dict | None:
    """Get a single photo by ID."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, filename, original_filename, tags_json, service_key, "
        "source, source_id, width, height, file_size, used_count, uploaded_at "
        "FROM photo_library WHERE id = ?",
        (photo_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "filename": row[1], "original_filename": row[2],
        "tags": json.loads(row[3] or "[]"), "service_key": row[4],
        "source": row[5], "source_id": row[6], "width": row[7],
        "height": row[8], "file_size": row[9], "used_count": row[10],
        "uploaded_at": row[11],
    }


def get_photo_by_source_id(source_id: str) -> dict | None:
    """Get a photo by external source ID (e.g. Google Drive file ID)."""
    if not source_id:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, filename, original_filename, tags_json, service_key, "
        "source, source_id, width, height, file_size, used_count, uploaded_at "
        "FROM photo_library WHERE source_id = ?",
        (source_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "filename": row[1], "original_filename": row[2],
        "tags": json.loads(row[3] or "[]"), "service_key": row[4],
        "source": row[5], "source_id": row[6], "width": row[7],
        "height": row[8], "file_size": row[9], "used_count": row[10],
        "uploaded_at": row[11],
    }


def update_photo(photo_id: int, tags: list = None, service_key: str = None) -> bool:
    """Update photo tags and/or service_key. Returns True if row updated."""
    sets = []
    params = []
    if tags is not None:
        sets.append("tags_json = ?")
        params.append(json.dumps(tags, ensure_ascii=False))
    if service_key is not None:
        sets.append("service_key = ?")
        params.append(service_key)
    if not sets:
        return False
    params.append(photo_id)
    conn = _get_conn()
    cur = conn.execute(
        f"UPDATE photo_library SET {', '.join(sets)} WHERE id = ?",
        tuple(params)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def update_photo_filename(photo_id: int, filename: str) -> bool:
    """Update photo filename (used after processing upload). Returns True if row updated."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE photo_library SET filename = ? WHERE id = ?",
        (filename, photo_id)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def delete_photo(photo_id: int) -> str | None:
    """Delete a photo record. Returns filename (caller deletes file) or None if not found."""
    conn = _get_conn()
    row = conn.execute("SELECT filename FROM photo_library WHERE id = ?", (photo_id,)).fetchone()
    if not row:
        conn.close()
        return None
    conn.execute("DELETE FROM photo_library WHERE id = ?", (photo_id,))
    conn.commit()
    conn.close()
    return row[0]


def get_photo_stats() -> dict:
    """Get photo count total and grouped by service_key."""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM photo_library").fetchone()[0]
    rows = conn.execute(
        "SELECT COALESCE(NULLIF(service_key, ''), 'untagged'), COUNT(*) "
        "FROM photo_library GROUP BY COALESCE(NULLIF(service_key, ''), 'untagged')"
    ).fetchall()
    conn.close()
    return {"total": total, "by_trip": {r[0]: r[1] for r in rows}}


# --- Training Examples ---


def save_training_example(caption_text: str, image_path: str = "",
                          platform: str = "") -> int:
    """Save a training example. Returns row id."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO training_examples (caption_text, image_path, platform, created_at) "
        "VALUES (?, ?, ?, ?)",
        (caption_text, image_path, platform,
         datetime.now(timezone.utc).isoformat())
    )
    example_id = cur.lastrowid
    conn.commit()
    conn.close()
    return example_id


def get_training_examples() -> list:
    """Get all training examples."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, caption_text, image_path, platform, created_at "
        "FROM training_examples ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "caption_text": r[1], "image_path": r[2],
         "platform": r[3], "created_at": r[4]}
        for r in rows
    ]


def delete_training_example(example_id: int) -> str:
    """Delete a training example. Returns image_path (caller deletes file) or empty string."""
    conn = _get_conn()
    row = conn.execute("SELECT image_path FROM training_examples WHERE id = ?",
                       (example_id,)).fetchone()
    if not row:
        conn.close()
        return ""
    conn.execute("DELETE FROM training_examples WHERE id = ?", (example_id,))
    conn.commit()
    conn.close()
    return row[0] or ""


# --- Brand Profile ---


def save_brand_rule(category: str, rule: str, source: str = "manual") -> int:
    """Save a brand profile rule. Returns row id."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO brand_profile (category, rule, source, created_at) "
        "VALUES (?, ?, ?, ?)",
        (category, rule, source, datetime.now(timezone.utc).isoformat())
    )
    rule_id = cur.lastrowid
    conn.commit()
    conn.close()
    return rule_id


def get_brand_rules(category: str = None) -> list:
    """Get active brand profile rules, optionally filtered by category."""
    conn = _get_conn()
    if category:
        rows = conn.execute(
            "SELECT id, category, rule, source, created_at "
            "FROM brand_profile WHERE active = 1 AND category = ? ORDER BY created_at",
            (category,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, category, rule, source, created_at "
            "FROM brand_profile WHERE active = 1 ORDER BY category, created_at"
        ).fetchall()
    conn.close()
    return [
        {"id": r[0], "category": r[1], "rule": r[2], "source": r[3], "created_at": r[4]}
        for r in rows
    ]


def update_brand_rule(rule_id: int, rule: str = None, category: str = None) -> bool:
    """Update a brand rule's text or category."""
    sets = []
    params = []
    if rule is not None:
        sets.append("rule = ?")
        params.append(rule)
    if category is not None:
        sets.append("category = ?")
        params.append(category)
    if not sets:
        return False
    params.append(rule_id)
    conn = _get_conn()
    cur = conn.execute(
        f"UPDATE brand_profile SET {', '.join(sets)} WHERE id = ? AND active = 1",
        tuple(params)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def delete_brand_rule(rule_id: int) -> bool:
    """Deactivate a brand rule."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE brand_profile SET active = 0 WHERE id = ? AND active = 1",
        (rule_id,)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def replace_brand_rules(category: str, rules: list, source: str = "analysis") -> list:
    """Replace all analysis-sourced rules in a category with new ones.
    Preserves manually-added rules. Returns list of new rule IDs."""
    conn = _get_conn()
    # Deactivate old analysis rules in this category
    conn.execute(
        "UPDATE brand_profile SET active = 0 WHERE category = ? AND source = 'analysis' AND active = 1",
        (category,)
    )
    # Insert new rules
    now = datetime.now(timezone.utc).isoformat()
    new_ids = []
    for rule_text in rules:
        cur = conn.execute(
            "INSERT INTO brand_profile (category, rule, source, created_at) VALUES (?, ?, ?, ?)",
            (category, rule_text, source, now)
        )
        new_ids.append(cur.lastrowid)
    conn.commit()
    conn.close()
    return new_ids


# --- System Settings ---


def get_setting(key: str, default: str = "") -> str:
    """Get a system setting value."""
    conn = _get_conn()
    row = conn.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    """Set a system setting value."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
        (key, value)
    )
    conn.commit()
    conn.close()


def is_dry_run() -> bool:
    """Check if dry run mode is enabled."""
    return get_setting("dry_run", "false") == "true"


# --- Scheduling ---


def schedule_draft(draft_id: int, scheduled_at: str) -> bool:
    """Set a draft to scheduled status with a publish time."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE content_drafts SET status = 'scheduled', scheduled_at = ? WHERE id = ? AND status = 'approved'",
        (scheduled_at, draft_id)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def unschedule_draft(draft_id: int) -> bool:
    """Revert a scheduled draft back to approved."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE content_drafts SET status = 'approved', scheduled_at = NULL WHERE id = ? AND status = 'scheduled'",
        (draft_id,)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def get_scheduled_due() -> list:
    """Get all drafts that are scheduled and due for publishing (scheduled_at <= now)."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT id, content_class, instagram_caption, facebook_caption, "
        "hashtags_json, visual_suggestion, reasoning, status, rejection_reason, "
        "created_at, approved_at, published_at, image_path, late_post_id, instagram_url, photo_id, "
        "platforms_json, facebook_url, late_facebook_post_id, scheduled_at "
        "FROM content_drafts WHERE status = 'scheduled' AND scheduled_at <= ? "
        "ORDER BY scheduled_at",
        (now,)
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "content_class": r[1], "instagram_caption": r[2],
            "facebook_caption": r[3], "hashtags": json.loads(r[4] or "[]"),
            "visual_suggestion": r[5], "reasoning": r[6], "status": r[7],
            "rejection_reason": r[8], "created_at": r[9], "approved_at": r[10],
            "published_at": r[11], "image_path": r[12],
            "late_post_id": r[13], "instagram_url": r[14],
            "photo_id": r[15] if r[15] else 0,
            "platforms": json.loads(r[16]) if r[16] else ["instagram"],
            "facebook_url": r[17] or "", "late_facebook_post_id": r[18] or "",
            "scheduled_at": r[19],
        }
        for r in rows
    ]


def save_schedule_slots(slots: list) -> None:
    """Replace all schedule slots. slots = [{"day_of_week": "Tuesday", "time_utc": "16:00"}, ...]"""
    conn = _get_conn()
    conn.execute("UPDATE schedule_slots SET active = 0")
    now = datetime.now(timezone.utc).isoformat()
    for slot in slots:
        conn.execute(
            "INSERT INTO schedule_slots (day_of_week, time_utc, active, created_at) VALUES (?, ?, 1, ?)",
            (slot["day_of_week"], slot["time_utc"], now)
        )
    conn.commit()
    conn.close()


def get_schedule_slots() -> list:
    """Get active schedule slots."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, day_of_week, time_utc FROM schedule_slots WHERE active = 1 ORDER BY id"
    ).fetchall()
    conn.close()
    return [{"id": r[0], "day_of_week": r[1], "time_utc": r[2]} for r in rows]


def get_next_open_slot() -> str:
    """Compute the next available schedule slot that doesn't have a draft assigned.
    Returns ISO 8601 timestamp or empty string."""
    slots = get_schedule_slots()
    if not slots:
        return ""
    # Get all future scheduled drafts
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT scheduled_at FROM content_drafts WHERE status = 'scheduled' AND scheduled_at > ?",
        (now,)
    ).fetchall()
    conn.close()
    taken = {r[0][:16] for r in rows if r[0]}  # Compare up to minute precision

    day_map = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
               "Friday": 4, "Saturday": 5, "Sunday": 6}
    today = datetime.now(timezone.utc)

    # Check next 14 days of slots
    for day_offset in range(14):
        check_date = today + timedelta(days=day_offset)
        for slot in slots:
            slot_day = day_map.get(slot["day_of_week"], -1)
            if check_date.weekday() != slot_day:
                continue
            hour, minute = slot["time_utc"].split(":")
            candidate = check_date.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
            if candidate <= today:
                continue
            candidate_key = candidate.isoformat()[:16]
            if candidate_key not in taken:
                return candidate.isoformat()
    return ""


def update_draft_platforms(draft_id: int, platforms: list) -> bool:
    """Update which platforms a draft publishes to."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE content_drafts SET platforms_json = ? WHERE id = ?",
        (json.dumps(platforms), draft_id)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def set_draft_facebook_info(draft_id: int, late_post_id: str = "",
                            facebook_url: str = "") -> None:
    """Store Facebook post info after publishing."""
    conn = _get_conn()
    conn.execute(
        "UPDATE content_drafts SET late_facebook_post_id = ?, facebook_url = ? WHERE id = ?",
        (late_post_id, facebook_url, draft_id)
    )
    conn.commit()
    conn.close()


def set_draft_photo_id(draft_id: int, photo_id: int) -> bool:
    """Set the photo_id on a content draft."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE content_drafts SET photo_id = ? WHERE id = ?",
        (photo_id, draft_id)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def increment_photo_used_count(photo_id: int) -> None:
    """Increment the used_count on a photo."""
    conn = _get_conn()
    conn.execute(
        "UPDATE photo_library SET used_count = used_count + 1 WHERE id = ?",
        (photo_id,)
    )
    conn.commit()
    conn.close()


# --- OAuth Tokens ---


def save_oauth_tokens(provider: str, access_token: str, refresh_token: str,
                      expires_at: str = "") -> None:
    """Insert or replace OAuth tokens for a provider."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO oauth_tokens "
        "(provider, access_token, refresh_token, expires_at, folder_id, updated_at) "
        "VALUES (?, ?, ?, ?, COALESCE((SELECT folder_id FROM oauth_tokens WHERE provider = ?), ''), ?)",
        (provider, access_token, refresh_token, expires_at, provider,
         datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()


def get_oauth_tokens(provider: str) -> dict | None:
    """Get OAuth tokens for a provider."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT provider, access_token, refresh_token, expires_at, folder_id, updated_at "
        "FROM oauth_tokens WHERE provider = ?",
        (provider,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "provider": row[0], "access_token": row[1], "refresh_token": row[2],
        "expires_at": row[3], "folder_id": row[4], "updated_at": row[5],
    }


def set_oauth_folder(provider: str, folder_id: str) -> bool:
    """Set the sync folder for a provider."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE oauth_tokens SET folder_id = ? WHERE provider = ?",
        (folder_id, provider)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def delete_oauth_tokens(provider: str) -> bool:
    """Remove OAuth tokens for a provider."""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM oauth_tokens WHERE provider = ?", (provider,))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def get_availability_summary(days_ahead: int = 7) -> list:
    """Get booking counts for all service slots in the next N days.
    Returns list of {service_key, date, slot_time, booked_guests, capacity, spots_remaining}.
    Used by content_agent to generate operationally-aware posts."""
    from shared import config_loader

    expire_stale_holds()
    trips = config_loader.get_services()
    now_curacao = datetime.now(timezone(timedelta(hours=-4)))
    today = now_curacao.date()

    day_name_map = {
        0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
        4: "Friday", 5: "Saturday", 6: "Sunday"
    }

    results = []
    conn = _get_conn()

    for service_key, trip_data in trips.items():
        capacity = trip_data.get("capacity", 0)
        days_available = trip_data.get("days_available", "daily")
        slots = trip_data.get("slots", [])

        # Parse which days this service operates
        if days_available.lower() == "daily":
            valid_days = set(range(7))
        else:
            valid_days = set()
            for d_idx, d_name in day_name_map.items():
                if d_name.lower() in days_available.lower():
                    valid_days.add(d_idx)
            # Handle plural forms: "Fridays" → "Friday"
            if not valid_days:
                for d_idx, d_name in day_name_map.items():
                    if d_name.lower() + "s" in days_available.lower():
                        valid_days.add(d_idx)

        for day_offset in range(days_ahead):
            check_date = today + timedelta(days=day_offset)
            if check_date.weekday() not in valid_days:
                continue
            date_str = check_date.isoformat()

            for dep in slots:
                dep_time = dep.get("time", "")
                now_utc = datetime.now(timezone.utc).isoformat()
                row = conn.execute(
                    "SELECT COALESCE(SUM(guests), 0) FROM service_bookings "
                    "WHERE service_key=? AND date=? AND slot_time=? "
                    "AND status IN ('soft_hold', 'confirmed') "
                    "AND (status='confirmed' OR expires_at > ?)",
                    (service_key, date_str, dep_time, now_utc)
                ).fetchone()
                booked = row[0] if row else 0
                results.append({
                    "service_key": service_key,
                    "date": date_str,
                    "slot_time": dep_time,
                    "booked_guests": booked,
                    "capacity": capacity,
                    "spots_remaining": max(0, capacity - booked),
                })

    conn.close()
    return results


def set_draft_image_path(draft_id: int, image_path: str) -> bool:
    """Set the generated image path for a content draft."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE content_drafts SET image_path = ? WHERE id = ?",
        (image_path, draft_id)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def set_draft_published_info(draft_id: int, late_post_id: str, instagram_url: str) -> bool:
    """Store the Late post ID and Instagram URL after publishing."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE content_drafts SET late_post_id = ?, instagram_url = ? WHERE id = ?",
        (late_post_id, instagram_url, draft_id)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def save_content_learning(rule: str, source_draft_ids: list = None) -> int:
    """Save a brand learning rule. Returns row id."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO content_learnings (rule, source_draft_ids, active, created_at) "
        "VALUES (?, ?, 1, ?)",
        (rule, json.dumps(source_draft_ids or [], ensure_ascii=False),
         datetime.now(timezone.utc).isoformat())
    )
    learning_id = cur.lastrowid
    conn.commit()
    conn.close()
    return learning_id


def get_active_learnings() -> list:
    """Get all active brand learning rules. Oldest first (chronological order)."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, rule, source_draft_ids, created_at "
        "FROM content_learnings WHERE active = 1 ORDER BY created_at ASC"
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "rule": r[1],
         "source_draft_ids": json.loads(r[2] or "[]"), "created_at": r[3]}
        for r in rows
    ]


def deactivate_learning(learning_id: int) -> bool:
    """Deactivate a brand learning rule. Returns True if row updated."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE content_learnings SET active = 0 WHERE id = ? AND active = 1",
        (learning_id,)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


# ── Brief 215: Escalation learnings (operator answers as approved knowledge) ──

def save_escalation_learning(conversation_id: str, channel: str,
                              source_question: str, human_answer: str,
                              status: str = "approved",
                              ai_may_use: bool = True,
                              category: str = None,
                              created_by: str = None) -> int:
    """Brief 215: persist an operator answer as an approved learning entry.
    Default status='approved' + ai_may_use=True per SR's contract Section 3.
    Returns the new row id."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO escalation_learnings "
        "(conversation_id, channel, source_question, human_answer, status, "
        "ai_may_use_automatically, category, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (conversation_id, channel, source_question or "", human_answer,
         status, 1 if ai_may_use else 0, category, created_by, now, now))
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def list_escalation_learnings(status: str = None) -> list:
    """Brief 215: return escalation learning entries newest-first.
    Skip rows with status='deleted'. Optional status filter."""
    conn = _get_conn()
    if status:
        rows = conn.execute(
            "SELECT id, conversation_id, channel, source_question, human_answer, "
            "status, ai_may_use_automatically, category, created_by, "
            "created_at, updated_at FROM escalation_learnings "
            "WHERE status = ? ORDER BY created_at DESC",
            (status,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, conversation_id, channel, source_question, human_answer, "
            "status, ai_may_use_automatically, category, created_by, "
            "created_at, updated_at FROM escalation_learnings "
            "WHERE status != 'deleted' ORDER BY created_at DESC").fetchall()
    conn.close()
    return [{
        "id": r[0], "conversationId": r[1], "channel": r[2],
        "sourceQuestion": r[3], "humanAnswer": r[4],
        "status": r[5], "aiMayUseAutomatically": bool(r[6]),
        "category": r[7], "createdBy": r[8],
        "createdAt": r[9], "updatedAt": r[10],
    } for r in rows]


def update_escalation_learning_status(learning_id: int, new_status: str) -> bool:
    """Brief 215: flip status. Allowed: suggested|approved|saved|deleted."""
    if new_status not in ("suggested", "approved", "saved", "deleted"):
        return False
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE escalation_learnings SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, now, learning_id))
    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def delete_escalation_learning(learning_id: int) -> bool:
    """Brief 215: hard-delete an escalation learning row."""
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM escalation_learnings WHERE id = ?", (learning_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_learning_status_for_conversation(conversation_id: str) -> str:
    """Brief 222: highest-precedence escalation_learning status for this
    conversation. Powers the `learningStatus` field on the conversation
    detail response. Precedence: saved > approved > suggested > none.
    Skip deleted rows."""
    if not conversation_id:
        return "none"
    conn = _get_conn()
    rows = conn.execute(
        "SELECT status FROM escalation_learnings "
        "WHERE conversation_id = ? AND status != 'deleted'",
        (conversation_id,)).fetchall()
    conn.close()
    statuses = {r[0] for r in rows}
    for s in ("saved", "approved", "suggested"):
        if s in statuses:
            return s
    return "none"


def get_approved_learnings_for_prompt(channel: str, limit: int = 20) -> list:
    """Brief 219: return the N most-recent approved escalation learnings
    that Marina is allowed to use automatically. Filters: channel match,
    status IN ('approved', 'saved'), ai_may_use_automatically=1.
    Returns newest first. Used by marina_agent._build_system_prompt to
    inject an APPROVED ANSWERS block when the tenant opts in via
    client.json::features.approved_learnings_in_prompt."""
    if not channel or limit <= 0:
        return []
    conn = _get_conn()
    rows = conn.execute(
        "SELECT source_question, human_answer FROM escalation_learnings "
        "WHERE channel = ? "
        "AND status IN ('approved', 'saved') "
        "AND ai_may_use_automatically = 1 "
        "ORDER BY created_at DESC LIMIT ?",
        (channel, limit)).fetchall()
    conn.close()
    return [{"question": r[0] or "", "answer": r[1] or ""} for r in rows]


# ── Brief 216: Your Info Updates (per-tenant temporary/permanent updates) ─────

_INFO_UPDATE_TYPES = {"general", "offer", "holiday", "hours", "pricing", "other"}


def info_update_create(text: str, type_: str = "general",
                       active: bool = True,
                       start_date: str = None,
                       end_date: str = None) -> int:
    """Brief 216: insert a new info_update row. Permanent rows omit
    start_date + end_date; scheduled rows include both. Returns row id."""
    if type_ not in _INFO_UPDATE_TYPES:
        type_ = "other"
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO info_updates "
        "(type, text, active, start_date, end_date, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (type_, text, 1 if active else 0, start_date, end_date, now, now))
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def info_updates_list_all() -> list:
    """Brief 216: return ALL info_updates (active + inactive, in-window
    + out-of-window) for the dashboard's Settings → Your Info Updates
    management list. camelCase keys for SR's frontend."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, type, text, active, start_date, end_date, "
        "created_at, updated_at FROM info_updates "
        "ORDER BY created_at DESC").fetchall()
    conn.close()
    return [{
        "id": r[0], "type": r[1], "text": r[2],
        "active": bool(r[3]),
        "startDate": r[4], "endDate": r[5],
        "createdAt": r[6], "updatedAt": r[7],
    } for r in rows]


def info_update_delete(update_id: int) -> bool:
    """Brief 216: hard-delete an info_update row."""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM info_updates WHERE id = ?", (update_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_active_info_updates() -> list:
    """Brief 216: return currently-active info_updates ready for prompt
    injection. Active iff active=1 AND (no dates OR within [start, end]).
    Half-open windows allowed: one of start/end set, the other null,
    means 'active from X' or 'active until Y'. ISO YYYY-MM-DD format
    expected for date columns; lexicographic comparison works because
    the format is fixed-width."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = _get_conn()
    rows = conn.execute(
        "SELECT type, text, start_date, end_date FROM info_updates "
        "WHERE active = 1 ORDER BY created_at DESC").fetchall()
    conn.close()
    out = []
    for type_, text, start_date, end_date in rows:
        if not start_date and not end_date:
            out.append({"type": type_, "text": text})
            continue
        if start_date and today < start_date:
            continue
        if end_date and today > end_date:
            continue
        out.append({"type": type_, "text": text})
    return out


def _last_customer_message_for(conversation_id: str, channel: str) -> str:
    """Brief 215: look up the most recent customer-role message text for
    this conversation, used as `source_question` when auto-creating a
    learning entry from an operator answer. Returns '' on miss."""
    if not conversation_id:
        return ""
    if channel == "email":
        thread_key = _find_email_thread_key_for(conversation_id)
        if not thread_key:
            return ""
        conv = email_get_conversation(thread_key)
        for m in reversed(conv.get("messages", []) or []):
            if m.get("role") in ("user", "customer"):
                return (m.get("text") or m.get("body") or "")[:1000]
        return ""
    history = wa_get_full_history(conversation_id, limit=10)
    for m in reversed(history):
        if m.get("role") == "user":
            return (m.get("text") or "")[:1000]
    return ""


# ==================== Brief 168: Payment hold state machine ====================

def set_payment_window(hold_id: int, payment_expires_at: str, customer_phone: str = "") -> bool:
    """Brief 168: set a payment expiry timestamp on a confirmed hold.
    Called right after confirm_hold() in the orchestrator when payment.timing
    is upfront/deposit. The reaper (hold_reaper.py) will scan rows where
    payment_expires_at is set and fire reminders / expirations.

    customer_phone is stored so the reaper can route reminders back to the
    customer without re-looking-up the thread state.
    """
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE service_bookings SET payment_expires_at = ?, customer_phone = ? "
        "WHERE id = ? AND status = 'confirmed'",
        (payment_expires_at, customer_phone, hold_id)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def get_holds_needing_reminder(now_iso: str, reminder_before_minutes: int) -> list:
    """Brief 168: return confirmed holds where payment_expires_at is within the
    reminder window AND payment_reminder_sent_at IS NULL. The reaper uses this
    to decide which holds to remind."""
    if not reminder_before_minutes or reminder_before_minutes <= 0:
        return []
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, booking_ref, service_key, date, slot_time, guests, customer_name, "
        "customer_email, customer_phone, payment_expires_at "
        "FROM service_bookings "
        "WHERE status = 'confirmed' "
        "AND payment_expires_at IS NOT NULL "
        "AND payment_reminder_sent_at IS NULL "
        "AND datetime(?) >= datetime(payment_expires_at, ?) "
        "AND datetime(?) < datetime(payment_expires_at) "
        "ORDER BY payment_expires_at",
        (now_iso, f"-{int(reminder_before_minutes)} minutes", now_iso)
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "booking_ref": r[1], "service_key": r[2], "date": r[3],
         "slot_time": r[4], "guests": r[5], "customer_name": r[6],
         "customer_email": r[7], "customer_phone": r[8], "payment_expires_at": r[9]}
        for r in rows
    ]


def get_expired_payment_holds(now_iso: str) -> list:
    """Brief 168: return confirmed holds where payment_expires_at has passed.
    The reaper uses this to release slots + mark status."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, booking_ref, service_key, date, slot_time, guests, customer_name, "
        "customer_email, customer_phone, payment_expires_at "
        "FROM service_bookings "
        "WHERE status = 'confirmed' "
        "AND payment_expires_at IS NOT NULL "
        "AND datetime(?) >= datetime(payment_expires_at) "
        "ORDER BY payment_expires_at",
        (now_iso,)
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "booking_ref": r[1], "service_key": r[2], "date": r[3],
         "slot_time": r[4], "guests": r[5], "customer_name": r[6],
         "customer_email": r[7], "customer_phone": r[8], "payment_expires_at": r[9]}
        for r in rows
    ]


def mark_payment_reminder_sent(hold_id: int) -> bool:
    """Brief 168: stamp payment_reminder_sent_at for a booking row."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE service_bookings SET payment_reminder_sent_at = ? WHERE id = ?",
        (now, hold_id)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def expire_payment_hold(hold_id: int) -> bool:
    """Brief 168: mark a hold as payment-expired. Also clears payment_expires_at so
    the reaper stops scanning it. The actual slot release is done by the caller
    (reaper) via cancel_hold if needed — expire_payment_hold only flips the status."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE service_bookings SET status = 'payment_expired', "
        "payment_expires_at = NULL WHERE id = ? AND status = 'confirmed'",
        (hold_id,)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


# ==================== Brief 166: Cross-channel customer file ====================

def _normalize_identifier_value(type_: str, value: str) -> str:
    """Brief 178: normalize identifier values for storage and lookup so case
    variants don't create silos. Email is case-insensitive in practice
    (every real mail system normalizes for comparison). Other identifier
    types are stripped only. Returns the normalized value. Idempotent."""
    if not value:
        return ""
    normalized = value.strip()
    if type_ == "email":
        normalized = normalized.lower()
    return normalized


def customer_lookup(type_: str, value: str):
    """Brief 166: look up a customer by an identifier. Returns None if not found.
    Brief 178: normalizes value (e.g. lowercases email) before lookup."""
    if not type_ or not value:
        return None
    value = _normalize_identifier_value(type_, value)
    if not value:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT c.id, c.display_name, c.summary, c.notes, c.first_seen, c.last_seen "
        "FROM customers c "
        "INNER JOIN customer_identifiers ci ON ci.customer_id = c.id "
        "WHERE ci.type = ? AND ci.value = ? AND c.active = 1 "
        "LIMIT 1",
        (type_, value)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "display_name": row[1] or "", "summary": row[2] or "",
        "notes": row[3] or "", "first_seen": row[4], "last_seen": row[5],
    }


def customer_lookup_or_create(type_: str, value: str, display_name: str = "") -> dict:
    """Brief 166: look up a customer by identifier, or create a new row if not found.
    Idempotent — safe to call on every inbound message.
    Brief 178: normalizes value (e.g. lowercases email) before lookup/insert."""
    if not type_ or not value:
        raise ValueError("type and value required")
    value = _normalize_identifier_value(type_, value)
    if not value:
        raise ValueError("normalized value empty")
    existing = customer_lookup(type_, value)
    if existing:
        if display_name and not existing["display_name"]:
            conn = _get_conn()
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE customers SET display_name = ?, last_seen = ? WHERE id = ?",
                (display_name, now, existing["id"])
            )
            conn.commit()
            conn.close()
            existing["display_name"] = display_name
        return existing
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO customers (display_name, first_seen, last_seen) VALUES (?, ?, ?)",
            (display_name or "", now, now)
        )
        customer_id = cur.lastrowid
        conn.execute(
            "INSERT INTO customer_identifiers (customer_id, type, value, first_seen) "
            "VALUES (?, ?, ?, ?)",
            (customer_id, type_, value, now)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        existing = customer_lookup(type_, value)
        if existing:
            return existing
        raise
    conn.close()
    return {
        "id": customer_id, "display_name": display_name or "",
        "summary": "", "notes": "",
        "first_seen": now, "last_seen": now,
    }


def _customer_choose_merge_survivor(a_id: int, b_id: int):
    """Brief 166: pick the surviving customer. Earlier first_seen wins (older = canonical)."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, first_seen FROM customers WHERE id IN (?, ?)", (a_id, b_id)
    ).fetchall()
    conn.close()
    if len(rows) != 2:
        return (a_id, b_id)
    rows = sorted(rows, key=lambda r: r[1])
    return (rows[0][0], rows[1][0])


def customer_merge(surviving_id: int, absorbed_id: int) -> dict:
    """Brief 166: merge absorbed_id into surviving_id. Moves identifiers + interactions,
    writes an audit row, deactivates the absorbed row. Idempotent."""
    if surviving_id == absorbed_id:
        return {"action": "noop"}
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    # Remove duplicate identifiers from the absorbed row (UNIQUE constraint would
    # otherwise block the UPDATE below).
    conn.execute(
        "DELETE FROM customer_identifiers WHERE customer_id = ? AND (type, value) IN "
        "(SELECT type, value FROM customer_identifiers WHERE customer_id = ?)",
        (absorbed_id, surviving_id)
    )
    conn.execute(
        "UPDATE customer_identifiers SET customer_id = ? WHERE customer_id = ?",
        (surviving_id, absorbed_id)
    )
    conn.execute(
        "UPDATE customer_interactions SET customer_id = ? WHERE customer_id = ?",
        (surviving_id, absorbed_id)
    )
    # Fold display_name if surviving is empty
    conn.execute(
        "UPDATE customers SET display_name = COALESCE(NULLIF(display_name, ''), "
        "  (SELECT display_name FROM customers WHERE id = ?)), "
        "last_seen = ? WHERE id = ?",
        (absorbed_id, now, surviving_id)
    )
    conn.execute(
        "INSERT INTO customer_merges (surviving_id, absorbed_id, merged_at) VALUES (?, ?, ?)",
        (surviving_id, absorbed_id, now)
    )
    conn.execute("UPDATE customers SET active = 0 WHERE id = ?", (absorbed_id,))
    conn.commit()
    conn.close()
    return {"action": "merged", "surviving_id": surviving_id, "absorbed_id": absorbed_id}


def customer_add_identifier(customer_id: int, type_: str, value: str) -> dict:
    """Brief 166: add a new identifier to an existing customer. Handles the cross-channel
    merge case: if the (type, value) already belongs to a DIFFERENT customer, merge them.
    Brief 178: normalizes value (e.g. lowercases email) before lookup/insert.
    Returns {"action": "added" | "merged" | "already_linked" | "noop", "customer_id": int}."""
    if not customer_id or not type_ or not value:
        return {"action": "noop", "customer_id": customer_id}
    value = _normalize_identifier_value(type_, value)
    if not value:
        return {"action": "noop", "customer_id": customer_id}
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    existing_row = conn.execute(
        "SELECT customer_id FROM customer_identifiers WHERE type = ? AND value = ?",
        (type_, value)
    ).fetchone()
    if existing_row:
        existing_customer_id = existing_row[0]
        conn.close()
        if existing_customer_id == customer_id:
            return {"action": "already_linked", "customer_id": customer_id}
        surviving, absorbed = _customer_choose_merge_survivor(customer_id, existing_customer_id)
        customer_merge(surviving, absorbed)
        return {"action": "merged", "customer_id": surviving}
    try:
        conn.execute(
            "INSERT INTO customer_identifiers (customer_id, type, value, first_seen) "
            "VALUES (?, ?, ?, ?)",
            (customer_id, type_, value, now)
        )
        conn.execute(
            "UPDATE customers SET last_seen = ? WHERE id = ?",
            (now, customer_id)
        )
        conn.commit()
        conn.close()
        return {"action": "added", "customer_id": customer_id}
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return customer_add_identifier(customer_id, type_, value)


def customer_record_interaction(customer_id: int, channel: str, summary: str):
    """Brief 166: append a one-line interaction summary. Updates last_seen."""
    if not customer_id or not channel or not summary:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO customer_interactions (customer_id, channel, summary, created_at) "
        "VALUES (?, ?, ?, ?)",
        (customer_id, channel, summary[:500], now)
    )
    conn.execute("UPDATE customers SET last_seen = ? WHERE id = ?", (now, customer_id))
    conn.commit()
    conn.close()


def customer_update_display_name(customer_id: int, display_name: str):
    """Brief 181: update a customer's display_name when Marina extracts a different
    name from the conversation than what was set from the webhook sender_name."""
    if not customer_id or not display_name:
        return
    conn = _get_conn()
    conn.execute(
        "UPDATE customers SET display_name = ? WHERE id = ?",
        (display_name.strip(), customer_id)
    )
    conn.commit()
    conn.close()


def customer_get_full(customer_id: int) -> dict:
    """Brief 166: return the full customer file for marina_agent's prompt block.
    Caps identifiers to 20 and interactions to 5 (prompt-size safety)."""
    if not customer_id:
        return {}
    conn = _get_conn()
    c_row = conn.execute(
        "SELECT id, display_name, summary, notes, first_seen, last_seen "
        "FROM customers WHERE id = ? AND active = 1",
        (customer_id,)
    ).fetchone()
    if not c_row:
        conn.close()
        return {}
    id_rows = conn.execute(
        "SELECT type, value, first_seen FROM customer_identifiers "
        "WHERE customer_id = ? ORDER BY first_seen LIMIT 20",
        (customer_id,)
    ).fetchall()
    int_rows = conn.execute(
        "SELECT channel, summary, created_at FROM customer_interactions "
        "WHERE customer_id = ? ORDER BY created_at DESC LIMIT 5",
        (customer_id,)
    ).fetchall()
    conn.close()
    return {
        "id": c_row[0], "display_name": c_row[1] or "", "summary": c_row[2] or "",
        "notes": c_row[3] or "", "first_seen": c_row[4], "last_seen": c_row[5],
        "identifiers": [{"type": r[0], "value": r[1], "first_seen": r[2]} for r in id_rows],
        "recent_interactions": [
            {"channel": r[0], "summary": r[1], "created_at": r[2]} for r in int_rows
        ],
    }


# ── Brief 207: Tasks helpers (operator-side workflow) ──────────────────────

def tasks_create(task_id: str, body_html: str, body_text: str,
                 created_by: str, assigned_to: str) -> dict:
    """Insert a new task. Returns the task dict (with empty attachments).
    Brief 223: also allocates the next per-workspace task_number."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    next_num = conn.execute(
        "SELECT COALESCE(MAX(task_number), 0) + 1 FROM tasks"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO tasks (id, body_html, body_text, created_by, assigned_to, "
        "status, task_number, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)",
        (task_id, body_html, body_text, created_by, assigned_to,
         next_num, now, now)
    )
    conn.commit()
    conn.close()
    return tasks_get(task_id)


def tasks_get(task_id: str):
    """Fetch a single task with its attachments. Returns None if not found.
    Brief 223: response includes task_number."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, body_html, body_text, created_by, assigned_to, status, "
        "completed_at, completed_by, task_number, created_at, updated_at "
        "FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if not row:
        conn.close()
        return None
    attachments = conn.execute(
        "SELECT id, file_name, mime_type, size_bytes, stored_filename, created_at "
        "FROM task_attachments WHERE task_id = ? ORDER BY created_at ASC",
        (task_id,)
    ).fetchall()
    conn.close()
    return {
        "id": row[0], "body_html": row[1], "body_text": row[2],
        "created_by": row[3], "assigned_to": row[4], "status": row[5],
        "completed_at": row[6], "completed_by": row[7],
        "task_number": row[8],
        "created_at": row[9], "updated_at": row[10],
        "attachments": [
            {"id": a[0], "file_name": a[1], "mime_type": a[2],
             "size_bytes": a[3], "stored_filename": a[4], "created_at": a[5]}
            for a in attachments
        ],
    }


def tasks_list() -> list:
    """List all tasks newest first, with attachments."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id FROM tasks ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [tasks_get(r[0]) for r in rows]


def tasks_update_status(task_id: str, status: str,
                        completed_by: str = None):
    """Update task status. status='done' sets completed_at + completed_by;
    status='open' clears them. Returns updated task or None if not found."""
    if status not in ("open", "done"):
        raise ValueError(f"Invalid status: {status}")
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    if status == "done":
        conn.execute(
            "UPDATE tasks SET status = 'done', completed_at = ?, "
            "completed_by = ?, updated_at = ? WHERE id = ?",
            (now, completed_by, now, task_id)
        )
    else:
        conn.execute(
            "UPDATE tasks SET status = 'open', completed_at = NULL, "
            "completed_by = NULL, updated_at = ? WHERE id = ?",
            (now, task_id)
        )
    conn.commit()
    conn.close()
    return tasks_get(task_id)


def tasks_add_attachment(task_id: str, attachment_id: str, file_name: str,
                         mime_type: str, size_bytes: int,
                         stored_filename: str) -> dict:
    """Insert an attachment row for an existing task. Bumps task's updated_at."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO task_attachments (id, task_id, file_name, mime_type, "
        "size_bytes, stored_filename, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (attachment_id, task_id, file_name, mime_type, size_bytes,
         stored_filename, now)
    )
    conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (now, task_id))
    conn.commit()
    conn.close()
    return {
        "id": attachment_id, "file_name": file_name, "mime_type": mime_type,
        "size_bytes": size_bytes, "stored_filename": stored_filename,
        "created_at": now,
    }


# Initialise database on module load so the file exists as soon as the module is imported
_get_conn().close()
