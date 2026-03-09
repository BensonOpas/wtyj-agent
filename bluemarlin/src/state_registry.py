# FILE: state_registry.py
# CREATED: Before Brief 001 (original codebase)
# LAST MODIFIED: Brief 050
# DEPENDS ON: nothing
# IMPORTS FROM: nothing
# CALLERS: email_poller.py, gws_calendar.py
import hashlib
import os
import sqlite3
from datetime import datetime, timezone, timedelta

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "state_registry.db"
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


# Initialise database on module load so the file exists as soon as the module is imported
_get_conn().close()
