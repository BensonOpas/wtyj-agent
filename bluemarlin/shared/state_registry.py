# bluemarlin/shared/state_registry.py
# Last modified: Brief 092
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
    conn.execute(
        "CREATE TABLE IF NOT EXISTS content_drafts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "content_class TEXT NOT NULL, "
        "instagram_caption TEXT, "
        "facebook_caption TEXT, "
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
                       visual_suggestion: str, reasoning: str) -> int:
    """Save a content draft. Returns row id."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO content_drafts "
        "(content_class, instagram_caption, facebook_caption, hashtags_json, "
        "visual_suggestion, reasoning, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
        (content_class, instagram_caption, facebook_caption,
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
            "SELECT id, content_class, instagram_caption, facebook_caption, "
            "hashtags_json, visual_suggestion, reasoning, status, rejection_reason, "
            "created_at, approved_at, published_at "
            "FROM content_drafts WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, content_class, instagram_caption, facebook_caption, "
            "hashtags_json, visual_suggestion, reasoning, status, rejection_reason, "
            "created_at, approved_at, published_at "
            "FROM content_drafts ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "content_class": r[1], "instagram_caption": r[2],
            "facebook_caption": r[3], "hashtags": json.loads(r[4] or "[]"),
            "visual_suggestion": r[5], "reasoning": r[6], "status": r[7],
            "rejection_reason": r[8], "created_at": r[9], "approved_at": r[10],
            "published_at": r[11],
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


def get_availability_summary(days_ahead: int = 7) -> list:
    """Get booking counts for all trip slots in the next N days.
    Returns list of {trip_key, date, departure_time, booked_guests, capacity, spots_remaining}.
    Used by content_agent to generate operationally-aware posts."""
    from shared import config_loader

    expire_stale_holds()
    trips = config_loader.get_trips()
    now_curacao = datetime.now(timezone(timedelta(hours=-4)))
    today = now_curacao.date()

    day_name_map = {
        0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
        4: "Friday", 5: "Saturday", 6: "Sunday"
    }

    results = []
    conn = _get_conn()

    for trip_key, trip_data in trips.items():
        capacity = trip_data.get("capacity", 0)
        days_available = trip_data.get("days_available", "daily")
        departures = trip_data.get("departures", [])

        # Parse which days this trip operates
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

            for dep in departures:
                dep_time = dep.get("time", "")
                now_utc = datetime.now(timezone.utc).isoformat()
                row = conn.execute(
                    "SELECT COALESCE(SUM(guests), 0) FROM trip_bookings "
                    "WHERE trip_key=? AND date=? AND departure_time=? "
                    "AND status IN ('soft_hold', 'confirmed') "
                    "AND (status='confirmed' OR expires_at > ?)",
                    (trip_key, date_str, dep_time, now_utc)
                ).fetchone()
                booked = row[0] if row else 0
                results.append({
                    "trip_key": trip_key,
                    "date": date_str,
                    "departure_time": dep_time,
                    "booked_guests": booked,
                    "capacity": capacity,
                    "spots_remaining": max(0, capacity - booked),
                })

    conn.close()
    return results


# Initialise database on module load so the file exists as soon as the module is imported
_get_conn().close()
