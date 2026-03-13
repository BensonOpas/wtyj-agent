# bluemarlin/shared/state_registry.py
# Last modified: Brief 077
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
    conn.execute(
        "CREATE TABLE IF NOT EXISTS processed_hashes ("
        "hash TEXT PRIMARY KEY, "
        "created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS trip_bookings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "trip_key TEXT NOT NULL, "
        "date TEXT NOT NULL, "
        "departure_time TEXT NOT NULL, "
        "guests INTEGER NOT NULL, "
        "booking_ref TEXT, "
        "status TEXT DEFAULT 'soft_hold', "
        "expires_at TEXT, "
        "created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_trip_bookings_lookup "
        "ON trip_bookings(trip_key, date, departure_time, status)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS manifest_events ("
        "trip_key TEXT NOT NULL, "
        "date TEXT NOT NULL, "
        "departure_time TEXT NOT NULL, "
        "calendar_id TEXT NOT NULL, "
        "event_id TEXT NOT NULL, "
        "html_link TEXT DEFAULT '', "
        "created_at TEXT NOT NULL, "
        "PRIMARY KEY (trip_key, date, departure_time)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bookings ("
        "booking_ref TEXT PRIMARY KEY, "
        "trip_key TEXT, "
        "customer_name TEXT, "
        "customer_email TEXT, "
        "date TEXT, "
        "departure_time TEXT, "
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
    try:
        conn.execute("ALTER TABLE trip_bookings ADD COLUMN customer_name TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE trip_bookings ADD COLUMN customer_email TEXT DEFAULT ''")
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
        "UPDATE trip_bookings SET status='expired' "
        "WHERE status='soft_hold' AND expires_at < ?",
        (now,)
    )
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def get_spots_remaining(trip_key: str, date: str, departure_time: str, capacity: int) -> int:
    """Return capacity minus guests already in soft_hold (non-expired) or confirmed for this slot."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute(
        "SELECT COALESCE(SUM(guests), 0) FROM trip_bookings "
        "WHERE trip_key=? AND date=? AND departure_time=? "
        "AND status IN ('soft_hold', 'confirmed') "
        "AND (status='confirmed' OR expires_at > ?)",
        (trip_key, date, departure_time, now)
    ).fetchone()
    conn.close()
    used = row[0] if row else 0
    return max(0, capacity - used)


def create_soft_hold(
    trip_key: str, date: str, departure_time: str, guests: int, capacity: int,
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
            "UPDATE trip_bookings SET status='expired' "
            "WHERE status='soft_hold' AND expires_at < ?",
            (now,)
        )
        row = conn.execute(
            "SELECT COALESCE(SUM(guests), 0) FROM trip_bookings "
            "WHERE trip_key=? AND date=? AND departure_time=? "
            "AND status IN ('soft_hold', 'confirmed') "
            "AND (status='confirmed' OR expires_at > ?)",
            (trip_key, date, departure_time, now)
        ).fetchone()
        used = row[0] if row else 0
        if used + guests > capacity:
            conn.execute("COMMIT")
            conn.close()
            return None
        cur = conn.execute(
            "INSERT INTO trip_bookings "
            "(trip_key, date, departure_time, guests, status, expires_at, created_at, "
            "customer_name, customer_email) "
            "VALUES (?, ?, ?, ?, 'soft_hold', ?, ?, ?, ?)",
            (trip_key, date, departure_time, guests, expires_at, now,
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
        "UPDATE trip_bookings SET status='confirmed', expires_at=NULL "
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
        "UPDATE trip_bookings SET status='cancelled' WHERE id=?",
        (hold_id,)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def set_booking_ref(hold_id: int, booking_ref: str) -> bool:
    """Set booking_ref on a trip_bookings row. Returns True if row was updated."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE trip_bookings SET booking_ref=? WHERE id=?",
        (booking_ref, hold_id)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def get_manifest_event(trip_key: str, date: str, departure_time: str):
    """Returns dict {trip_key, date, departure_time, calendar_id, event_id, html_link} or None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT trip_key, date, departure_time, calendar_id, event_id, html_link "
        "FROM manifest_events WHERE trip_key=? AND date=? AND departure_time=?",
        (trip_key, date, departure_time)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "trip_key": row[0], "date": row[1], "departure_time": row[2],
        "calendar_id": row[3], "event_id": row[4], "html_link": row[5],
    }


def save_manifest_event(trip_key: str, date: str, departure_time: str,
                        calendar_id: str, event_id: str, html_link: str) -> None:
    """INSERT OR REPLACE into manifest_events."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO manifest_events "
        "(trip_key, date, departure_time, calendar_id, event_id, html_link, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (trip_key, date, departure_time, calendar_id, event_id, html_link,
         datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()


def delete_manifest_event(trip_key: str, date: str, departure_time: str) -> bool:
    """Delete manifest_events row for this slot. Returns True if row existed."""
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM manifest_events WHERE trip_key=? AND date=? AND departure_time=?",
        (trip_key, date, departure_time)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def get_slot_passengers(trip_key: str, date: str, departure_time: str) -> list:
    """Return all active bookings for this slot (soft_hold non-expired + confirmed).
    Each item: {id, guests, booking_ref, status, customer_name, customer_email, created_at}."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT id, guests, booking_ref, status, customer_name, customer_email, created_at "
        "FROM trip_bookings "
        "WHERE trip_key=? AND date=? AND departure_time=? "
        "AND status IN ('soft_hold', 'confirmed') "
        "AND (status='confirmed' OR expires_at > ?) "
        "ORDER BY created_at ASC",
        (trip_key, date, departure_time, now)
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
        "(booking_ref, trip_key, customer_name, customer_email, date, "
        "departure_time, guests, special_requests, payment_link, event_link, "
        "status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            booking_ref,
            fields.get("trip_key", ""),
            fields.get("customer_name", ""),
            customer_email.strip().lower() if customer_email else "",
            fields.get("date", ""),
            fields.get("departure_time", ""),
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
        "SELECT booking_ref, trip_key, customer_name, customer_email, date, "
        "departure_time, guests, special_requests, payment_link, event_link, "
        "status, created_at "
        "FROM bookings WHERE customer_email = ? ORDER BY created_at DESC",
        (customer_email.strip().lower(),)
    ).fetchall()
    conn.close()
    return [{"booking_ref": r[0], "trip_key": r[1], "customer_name": r[2],
             "customer_email": r[3], "date": r[4], "departure_time": r[5],
             "guests": r[6], "special_requests": r[7], "payment_link": r[8],
             "event_link": r[9], "status": r[10], "created_at": r[11]} for r in rows]


def get_booking(booking_ref: str) -> "dict | None":
    """Return full booking dict by ref, or None if not found."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT booking_ref, trip_key, customer_name, customer_email, date, "
        "departure_time, guests, special_requests, payment_link, event_link, "
        "status, created_at "
        "FROM bookings WHERE booking_ref = ?",
        (booking_ref,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "booking_ref": row[0], "trip_key": row[1], "customer_name": row[2],
        "customer_email": row[3], "date": row[4], "departure_time": row[5],
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
    """Look up a pending relay notification by token. Returns dict or None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, notification_type, relay_token, channel, customer_id, "
        "customer_name, subject, body, status, created_at "
        "FROM pending_notifications WHERE relay_token = ? AND status = 'pending'",
        (relay_token,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "notification_type": row[1], "relay_token": row[2],
            "channel": row[3], "customer_id": row[4], "customer_name": row[5],
            "subject": row[6], "body": row[7], "status": row[8], "created_at": row[9]}


# Initialise database on module load so the file exists as soon as the module is imported
_get_conn().close()
