# bluemarlin/shared/state_registry.py
# Last modified: Brief 098
# Purpose: SQLite WAL deduplication, capacity, manifests, bookings
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "state_registry.db"
)


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
        name = fields.get("customer_name") or fields.get("name") or phone
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
    """Get full conversation history for a phone number (no 24h cutoff). Oldest first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, text, created_at FROM whatsapp_threads "
        "WHERE phone = ? ORDER BY created_at ASC LIMIT ?",
        (phone, limit)
    ).fetchall()
    conn.close()
    return [{"role": r[0], "text": r[1], "created_at": r[2]} for r in rows]


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
                                 relay_token: str = None) -> int:
    """Insert a pending notification for the email poller to send. Returns row id."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO pending_notifications "
        "(notification_type, relay_token, channel, customer_id, customer_name, "
        "subject, body, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
        (notification_type, relay_token, channel, customer_id, customer_name,
         subject, body, datetime.now(timezone.utc).isoformat())
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_all_escalations() -> list:
    """Return all escalation notifications, newest first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, notification_type, relay_token, channel, customer_id, "
        "customer_name, subject, body, status, created_at "
        "FROM pending_notifications ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [{"id": r[0], "notification_type": r[1], "relay_token": r[2],
             "channel": r[3], "customer_id": r[4], "customer_name": r[5],
             "subject": r[6], "body": r[7], "status": r[8], "created_at": r[9]}
            for r in rows]


def get_pending_notifications(status: str = "pending") -> list:
    """Return all notifications with the given status."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, notification_type, relay_token, channel, customer_id, "
        "customer_name, subject, body, status, created_at "
        "FROM pending_notifications WHERE status = ? ORDER BY created_at ASC",
        (status,)
    ).fetchall()
    conn.close()
    return [{"id": r[0], "notification_type": r[1], "relay_token": r[2],
             "channel": r[3], "customer_id": r[4], "customer_name": r[5],
             "subject": r[6], "body": r[7], "status": r[8], "created_at": r[9]}
            for r in rows]


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


# ==================== Brief 166: Cross-channel customer file ====================

def customer_lookup(type_: str, value: str):
    """Brief 166: look up a customer by an identifier. Returns None if not found."""
    if not type_ or not value:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT c.id, c.display_name, c.summary, c.notes, c.first_seen, c.last_seen "
        "FROM customers c "
        "INNER JOIN customer_identifiers ci ON ci.customer_id = c.id "
        "WHERE ci.type = ? AND ci.value = ? AND c.active = 1 "
        "LIMIT 1",
        (type_, value.strip())
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
    Idempotent — safe to call on every inbound message."""
    if not type_ or not value:
        raise ValueError("type and value required")
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
            (customer_id, type_, value.strip(), now)
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
    Returns {"action": "added" | "merged" | "already_linked" | "noop", "customer_id": int}."""
    if not customer_id or not type_ or not value:
        return {"action": "noop", "customer_id": customer_id}
    value = value.strip()
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


# Initialise database on module load so the file exists as soon as the module is imported
_get_conn().close()
