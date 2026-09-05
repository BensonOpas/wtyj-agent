"""Private, durable crew-assistance notes for Mermaid reservations.

These records are operational attention only. They never create an escalation,
mute Tracy, freeze a reservation, or appear in customer-facing documents.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone

from shared import state_registry


KIND_WHEELCHAIR = "wheelchair"
KIND_BOARDING_ASSISTANCE = "boarding_assistance"
KINDS = {KIND_WHEELCHAIR, KIND_BOARDING_ASSISTANCE}
STATUSES = {"unacknowledged", "acknowledged", "withdrawn"}
_schema_lock = threading.Lock()


class CrewAssistanceError(RuntimeError):
    pass


class CrewAssistanceNotFound(CrewAssistanceError):
    pass


class CrewAssistanceConflict(CrewAssistanceError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    conn = state_registry._get_conn()
    conn.row_factory = sqlite3.Row
    with _schema_lock:
        _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mermaid_crew_assistance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_slug TEXT NOT NULL DEFAULT 'mermaid'
                CHECK (tenant_slug = 'mermaid'),
            conversation_id TEXT NOT NULL,
            customer_name TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL
                CHECK (kind IN ('wheelchair','boarding_assistance')),
            note_text TEXT NOT NULL,
            relationship TEXT NOT NULL DEFAULT '',
            trip_date TEXT,
            reservation_public_id TEXT,
            status TEXT NOT NULL DEFAULT 'unacknowledged'
                CHECK (status IN ('unacknowledged','acknowledged','withdrawn')),
            revision INTEGER NOT NULL DEFAULT 1,
            source_message_id TEXT NOT NULL DEFAULT '',
            material_hash TEXT NOT NULL,
            acknowledged_at TEXT,
            acknowledged_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            session_started_at TEXT NOT NULL DEFAULT '',
            UNIQUE (tenant_slug, conversation_id, kind)
        );
        CREATE INDEX IF NOT EXISTS idx_mermaid_crew_assistance_queue
          ON mermaid_crew_assistance(tenant_slug, status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_mermaid_crew_assistance_reservation
          ON mermaid_crew_assistance(tenant_slug, reservation_public_id);
        CREATE TABLE IF NOT EXISTS mermaid_crew_assistance_reservations (
            assistance_id INTEGER NOT NULL,
            tenant_slug TEXT NOT NULL DEFAULT 'mermaid'
                CHECK (tenant_slug = 'mermaid'),
            reservation_public_id TEXT NOT NULL,
            customer_name TEXT NOT NULL DEFAULT '',
            note_text TEXT NOT NULL DEFAULT '',
            relationship TEXT NOT NULL DEFAULT '',
            trip_date TEXT,
            status TEXT NOT NULL DEFAULT 'unacknowledged',
            revision INTEGER NOT NULL DEFAULT 1,
            acknowledged_at TEXT,
            acknowledged_by TEXT,
            session_started_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            PRIMARY KEY (reservation_public_id, assistance_id),
            FOREIGN KEY (assistance_id) REFERENCES mermaid_crew_assistance(id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_mermaid_crew_assistance_link_reservation
          ON mermaid_crew_assistance_reservations(tenant_slug, reservation_public_id);
        CREATE TABLE IF NOT EXISTS mermaid_crew_assistance_sources (
            tenant_slug TEXT NOT NULL DEFAULT 'mermaid'
                CHECK (tenant_slug = 'mermaid'),
            conversation_id TEXT NOT NULL,
            source_message_id TEXT NOT NULL,
            assistance_id INTEGER,
            operation TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (tenant_slug, conversation_id, source_message_id),
            FOREIGN KEY (assistance_id) REFERENCES mermaid_crew_assistance(id)
                ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS mermaid_crew_assistance_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assistance_id INTEGER NOT NULL,
            tenant_slug TEXT NOT NULL DEFAULT 'mermaid'
                CHECK (tenant_slug = 'mermaid'),
            event_type TEXT NOT NULL,
            revision INTEGER NOT NULL,
            actor TEXT NOT NULL DEFAULT '',
            source_message_id TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL UNIQUE,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (assistance_id) REFERENCES mermaid_crew_assistance(id)
        );
        """
    )
    for column in (
        "customer_name TEXT NOT NULL DEFAULT ''",
        "note_text TEXT NOT NULL DEFAULT ''",
        "relationship TEXT NOT NULL DEFAULT ''",
        "trip_date TEXT",
        "status TEXT NOT NULL DEFAULT 'unacknowledged'",
        "revision INTEGER NOT NULL DEFAULT 1",
        "acknowledged_at TEXT",
        "acknowledged_by TEXT",
        "session_started_at TEXT NOT NULL DEFAULT ''",
    ):
        try:
            conn.execute(
                f"ALTER TABLE mermaid_crew_assistance_reservations ADD COLUMN {column}"
            )
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).casefold():
                raise
    try:
        conn.execute(
            "ALTER TABLE mermaid_crew_assistance "
            "ADD COLUMN session_started_at TEXT NOT NULL DEFAULT ''"
        )
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).casefold():
            raise
    # The first released link schema enforced one assistance row per
    # reservation. A conversation may now have both a wheelchair note and a
    # general boarding-help note, so rebuild that old SQLite table in place.
    # The explicit transaction makes the rename/copy/drop atomic and the
    # constraint check makes initialization safe to repeat.
    conn.commit()
    _migrate_singular_reservation_links(conn)
    # Rows created by an older release contain only the relationship table's
    # keys. Freeze the best available snapshot once during migration so later
    # edits to the current conversation note cannot keep rewriting history.
    conn.execute(
        "UPDATE mermaid_crew_assistance_reservations AS r SET "
        "customer_name=(SELECT a.customer_name FROM mermaid_crew_assistance a WHERE a.id=r.assistance_id),"
        "note_text=(SELECT a.note_text FROM mermaid_crew_assistance a WHERE a.id=r.assistance_id),"
        "relationship=(SELECT a.relationship FROM mermaid_crew_assistance a WHERE a.id=r.assistance_id),"
        "trip_date=(SELECT a.trip_date FROM mermaid_crew_assistance a WHERE a.id=r.assistance_id),"
        "status=(SELECT a.status FROM mermaid_crew_assistance a WHERE a.id=r.assistance_id),"
        "revision=(SELECT a.revision FROM mermaid_crew_assistance a WHERE a.id=r.assistance_id),"
        "acknowledged_at=(SELECT a.acknowledged_at FROM mermaid_crew_assistance a WHERE a.id=r.assistance_id),"
        "acknowledged_by=(SELECT a.acknowledged_by FROM mermaid_crew_assistance a WHERE a.id=r.assistance_id) "
        "WHERE r.note_text='' AND EXISTS ("
        "SELECT 1 FROM mermaid_crew_assistance a WHERE a.id=r.assistance_id)"
    )
    # Schema initialization always runs before the caller's explicit write
    # transaction. Commit the one-time migration so BEGIN IMMEDIATE remains
    # valid on this connection.
    conn.commit()


def _has_singular_reservation_link_constraint(conn: sqlite3.Connection) -> bool:
    for index in conn.execute(
        "PRAGMA index_list(mermaid_crew_assistance_reservations)"
    ).fetchall():
        if not int(index[2]):
            continue
        name = str(index[1]).replace('"', '""')
        columns = tuple(
            str(column[2])
            for column in conn.execute(f'PRAGMA index_info("{name}")').fetchall()
        )
        if columns == ("tenant_slug", "reservation_public_id"):
            return True
    return False


def _migrate_singular_reservation_links(conn: sqlite3.Connection) -> None:
    """Remove the legacy one-assistance-per-reservation constraint safely."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Check after taking the writer lock because another process may have
        # completed the same lazy migration while this connection was waiting.
        if not _has_singular_reservation_link_constraint(conn):
            conn.commit()
            return
        conn.execute(
            "ALTER TABLE mermaid_crew_assistance_reservations "
            "RENAME TO mermaid_crew_assistance_reservations_singular"
        )
        conn.execute(
            """
            CREATE TABLE mermaid_crew_assistance_reservations (
                assistance_id INTEGER NOT NULL,
                tenant_slug TEXT NOT NULL DEFAULT 'mermaid'
                    CHECK (tenant_slug = 'mermaid'),
                reservation_public_id TEXT NOT NULL,
                customer_name TEXT NOT NULL DEFAULT '',
                note_text TEXT NOT NULL DEFAULT '',
                relationship TEXT NOT NULL DEFAULT '',
                trip_date TEXT,
                status TEXT NOT NULL DEFAULT 'unacknowledged',
                revision INTEGER NOT NULL DEFAULT 1,
                acknowledged_at TEXT,
                acknowledged_by TEXT,
                session_started_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                PRIMARY KEY (reservation_public_id, assistance_id),
                FOREIGN KEY (assistance_id) REFERENCES mermaid_crew_assistance(id)
                    ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "INSERT INTO mermaid_crew_assistance_reservations "
            "(assistance_id,tenant_slug,reservation_public_id,customer_name,"
            "note_text,relationship,trip_date,status,revision,acknowledged_at,"
            "acknowledged_by,session_started_at,created_at) SELECT assistance_id,tenant_slug,"
            "reservation_public_id,customer_name,note_text,relationship,trip_date,"
            "status,revision,acknowledged_at,acknowledged_by,session_started_at,created_at FROM "
            "mermaid_crew_assistance_reservations_singular"
        )
        conn.execute("DROP TABLE mermaid_crew_assistance_reservations_singular")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mermaid_crew_assistance_link_reservation "
            "ON mermaid_crew_assistance_reservations(tenant_slug, reservation_public_id)"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _clean(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _conversation_session_started_at(conversation_id: str) -> str:
    try:
        state = state_registry.wa_get_booking_state(conversation_id)
    except Exception:
        return ""
    return _clean(
        (state.get("flags") or {}).get("mermaid_session_started_at"), 64
    )


def _material_hash(note: str, relationship: str, trip_date: str) -> str:
    encoded = json.dumps(
        {"note": note, "relationship": relationship, "trip_date": trip_date},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _projection(row: sqlite3.Row | dict | None) -> dict | None:
    if row is None:
        return None
    value = dict(row)
    return {
        "id": value["id"],
        "conversationId": value["conversation_id"],
        "customerName": value["customer_name"],
        "kind": value["kind"],
        "note": value["note_text"],
        "relationship": value["relationship"] or None,
        "tripDate": value["trip_date"],
        "reservationPublicId": value["reservation_public_id"],
        "status": value["status"],
        "revision": value["revision"],
        "createdAt": value["created_at"],
        "updatedAt": value["updated_at"],
        "acknowledgedAt": value["acknowledged_at"],
        "acknowledgedBy": value["acknowledged_by"],
    }


def _linked_projection(row: sqlite3.Row | None) -> dict | None:
    item = _projection(row)
    if item is None:
        return None
    value = dict(row)
    if value.get("linked_public_id"):
        item.update(
            customerName=value.get("linked_customer_name") or "",
            note=value["linked_note_text"],
            relationship=value.get("linked_relationship") or None,
            tripDate=value.get("linked_trip_date"),
            reservationPublicId=value.get("linked_public_id"),
            status=value.get("linked_status") or "unacknowledged",
            revision=int(value.get("linked_revision") or 1),
            acknowledgedAt=value.get("linked_acknowledged_at"),
            acknowledgedBy=value.get("linked_acknowledged_by"),
        )
    return item


def _update_current_link_snapshot(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    customer_name: str,
    note: str,
    relationship: str,
    trip_date: str,
    status: str,
    revision: int,
    acknowledged_at: str | None = None,
    acknowledged_by: str | None = None,
) -> None:
    """Update only the reservation whose saved trip date still matches."""
    public_id = str(row["reservation_public_id"] or "")
    if not public_id:
        return
    linked = conn.execute(
        "SELECT trip_date FROM mermaid_crew_assistance_reservations "
        "WHERE assistance_id=? AND reservation_public_id=?",
        (row["id"], public_id),
    ).fetchone()
    if linked is None or (linked[0] or "") != (trip_date or ""):
        return
    conn.execute(
        "UPDATE mermaid_crew_assistance_reservations SET "
        "customer_name=?,note_text=?,relationship=?,status=?,revision=?,"
        "acknowledged_at=?,acknowledged_by=? "
        "WHERE assistance_id=? AND reservation_public_id=?",
        (
            customer_name,
            note,
            relationship,
            status,
            revision,
            acknowledged_at,
            acknowledged_by,
            row["id"],
            public_id,
        ),
    )


def _reservation_pointer_for_trip(
    conn: sqlite3.Connection, row: sqlite3.Row, trip_date: str
) -> str | None:
    """Keep a current pointer only when it belongs to the updated trip."""
    public_id = str(row["reservation_public_id"] or "")
    if not public_id:
        return None
    linked = conn.execute(
        "SELECT trip_date FROM mermaid_crew_assistance_reservations "
        "WHERE assistance_id=? AND reservation_public_id=?",
        (row["id"], public_id),
    ).fetchone()
    if linked is not None:
        return public_id if (linked[0] or "") == (trip_date or "") else None
    # Compatibility for a pre-link-table row: its own saved date is the only
    # evidence available until the next confirmation creates a link snapshot.
    return public_id if (row["trip_date"] or "") == (trip_date or "") else None


def _event_key(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(str(part or "") for part in parts).encode()).hexdigest()


def _record_event(
    conn: sqlite3.Connection,
    assistance_id: int,
    event_type: str,
    revision: int,
    *,
    actor: str = "",
    source_message_id: str = "",
    idempotency_key: str,
    payload: dict | None = None,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO mermaid_crew_assistance_events "
        "(assistance_id,tenant_slug,event_type,revision,actor,source_message_id,"
        "idempotency_key,payload_json,created_at) VALUES (?,'mermaid',?,?,?,?,?,?,?)",
        (
            assistance_id,
            event_type,
            revision,
            _clean(actor, 80),
            _clean(source_message_id, 200),
            idempotency_key,
            json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
            _now(),
        ),
    )


def _source_seen(
    conn: sqlite3.Connection,
    conversation_id: str,
    source_message_id: str,
    assistance_id: int | None = None,
) -> bool:
    if not source_message_id:
        return False
    if conn.execute(
        "SELECT 1 FROM mermaid_crew_assistance_sources "
        "WHERE tenant_slug='mermaid' AND conversation_id=? "
        "AND source_message_id=? LIMIT 1",
        (conversation_id, source_message_id),
    ).fetchone():
        return True
    # Events predate the source ledger. Preserve replay safety during an
    # in-place upgrade and let the caller backfill the ledger on new work.
    return bool(
        assistance_id
        and conn.execute(
            "SELECT 1 FROM mermaid_crew_assistance_events "
            "WHERE assistance_id=? AND source_message_id=? LIMIT 1",
            (assistance_id, source_message_id),
        ).fetchone()
    )


def _record_source(
    conn: sqlite3.Connection,
    conversation_id: str,
    source_message_id: str,
    assistance_id: int | None,
    operation: str,
) -> None:
    if not source_message_id:
        return
    conn.execute(
        "INSERT OR IGNORE INTO mermaid_crew_assistance_sources "
        "(tenant_slug,conversation_id,source_message_id,assistance_id,operation,created_at) "
        "VALUES ('mermaid',?,?,?,?,?)",
        (
            conversation_id,
            source_message_id,
            assistance_id,
            _clean(operation, 40),
            _now(),
        ),
    )


def _record_assistance_note(
    conversation_id: str,
    *,
    kind: str,
    note: str,
    relationship: str = "",
    trip_date: str = "",
    customer_name: str = "",
    source_message_id: str = "",
    session_started_at: str = "",
    reservation_public_id: str = "",
) -> tuple[dict, str]:
    """Create/update one current note; return ``(projection, outcome)``.

    ``outcome`` is ``created``, ``updated``, ``replayed`` or ``unchanged``.
    Material corrections reopen an acknowledged item. A provider replay with
    the same source id remains distinguishable so the exact cached reply can be
    reproduced after a failed outbound send.
    """
    conversation_id = _clean(conversation_id, 240)
    note = _clean(note, 320)
    relationship = _clean(relationship, 80)
    trip_date = _clean(trip_date, 10)
    customer_name = _clean(customer_name, 160)
    source_message_id = _clean(source_message_id, 200)
    reservation_public_id = _clean(reservation_public_id, 80)
    session_started_at = _clean(session_started_at, 64) or (
        _conversation_session_started_at(conversation_id)
    )
    if not conversation_id or not note or kind not in KINDS:
        raise CrewAssistanceError("conversation, kind and assistance note are required")
    material_hash = _material_hash(note, relationship, trip_date)
    now = _now()
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM mermaid_crew_assistance WHERE tenant_slug='mermaid' "
            "AND conversation_id=? AND kind=?",
            (conversation_id, kind),
        ).fetchone()
        if _source_seen(
            conn,
            conversation_id,
            source_message_id,
            int(row["id"]) if row is not None else None,
        ):
            conn.commit()
            return _projection(row), "replayed"
        linked_reassertion = bool(
            row is not None
            and source_message_id
            and row["reservation_public_id"]
            and row["reservation_public_id"] != reservation_public_id
        )
        if row is None:
            cur = conn.execute(
                "INSERT INTO mermaid_crew_assistance "
                "(tenant_slug,conversation_id,customer_name,kind,note_text,relationship,"
                "trip_date,status,revision,source_message_id,material_hash,created_at,updated_at,"
                "session_started_at) "
                "VALUES ('mermaid',?,?,?,?,?,?,'unacknowledged',1,?,?,?,?,?)",
                (
                    conversation_id,
                    customer_name,
                    kind,
                    note,
                    relationship,
                    trip_date or None,
                    source_message_id,
                    material_hash,
                    now,
                    now,
                    session_started_at,
                ),
            )
            assistance_id, revision, outcome = int(cur.lastrowid), 1, "created"
            _record_event(
                conn,
                assistance_id,
                "created",
                revision,
                source_message_id=source_message_id,
                idempotency_key=_event_key("created", conversation_id, source_message_id, material_hash),
                payload={"kind": kind},
            )
        elif (
            row["material_hash"] == material_hash
            and row["status"] != "withdrawn"
            and row["session_started_at"] == session_started_at
            and not linked_reassertion
        ):
            outcome = "replayed" if source_message_id and row["source_message_id"] == source_message_id else "unchanged"
            if customer_name and customer_name != row["customer_name"]:
                conn.execute(
                    "UPDATE mermaid_crew_assistance SET customer_name=?,updated_at=? WHERE id=?",
                    (customer_name, now, row["id"]),
                )
            assistance_id, revision = int(row["id"]), int(row["revision"])
        else:
            assistance_id = int(row["id"])
            revision = int(row["revision"]) + 1
            outcome = "updated"
            reservation_public_id = _reservation_pointer_for_trip(
                conn, row, trip_date
            )
            if (
                row["session_started_at"] != session_started_at
                or linked_reassertion
            ):
                reservation_public_id = None
            conn.execute(
                "UPDATE mermaid_crew_assistance SET customer_name=?,note_text=?,relationship=?,"
                "trip_date=?,reservation_public_id=?,status='unacknowledged',revision=?,"
                "source_message_id=?,material_hash=?,session_started_at=?,"
                "acknowledged_at=NULL,acknowledged_by=NULL,updated_at=? WHERE id=?",
                (
                    customer_name or row["customer_name"],
                    note,
                    relationship,
                    trip_date or None,
                    reservation_public_id,
                    revision,
                    source_message_id,
                    material_hash,
                    session_started_at,
                    now,
                    assistance_id,
                ),
            )
            _record_event(
                conn,
                assistance_id,
                "updated",
                revision,
                source_message_id=source_message_id,
                idempotency_key=_event_key("updated", assistance_id, revision, source_message_id, material_hash),
                payload={"reopened": row["status"] == "acknowledged"},
            )
        _record_source(
            conn,
            conversation_id,
            source_message_id,
            assistance_id,
            "record",
        )
        current = conn.execute(
            "SELECT * FROM mermaid_crew_assistance WHERE id=?", (assistance_id,)
        ).fetchone()
        if (
            row is not None
            and current["reservation_public_id"]
            and current["reservation_public_id"] == row["reservation_public_id"]
        ):
            _update_current_link_snapshot(
                conn,
                row,
                customer_name=current["customer_name"],
                note=current["note_text"],
                relationship=current["relationship"],
                trip_date=current["trip_date"] or "",
                status=current["status"],
                revision=int(current["revision"]),
                acknowledged_at=current["acknowledged_at"],
                acknowledged_by=current["acknowledged_by"],
            )
        conn.commit()
        return _projection(current), outcome
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_wheelchair_note(
    conversation_id: str,
    *,
    note: str,
    relationship: str = "",
    trip_date: str = "",
    customer_name: str = "",
    source_message_id: str = "",
    session_started_at: str = "",
    reservation_public_id: str = "",
) -> tuple[dict, str]:
    return _record_assistance_note(
        conversation_id,
        kind=KIND_WHEELCHAIR,
        note=note,
        relationship=relationship,
        trip_date=trip_date,
        customer_name=customer_name,
        source_message_id=source_message_id,
        session_started_at=session_started_at,
        reservation_public_id=reservation_public_id,
    )


def record_boarding_assistance_note(
    conversation_id: str,
    *,
    note: str,
    relationship: str = "",
    trip_date: str = "",
    customer_name: str = "",
    source_message_id: str = "",
    session_started_at: str = "",
    reservation_public_id: str = "",
) -> tuple[dict, str]:
    """Record a supported general-help request without inventing a wheelchair."""
    return _record_assistance_note(
        conversation_id,
        kind=KIND_BOARDING_ASSISTANCE,
        note=note,
        relationship=relationship,
        trip_date=trip_date,
        customer_name=customer_name,
        source_message_id=source_message_id,
        session_started_at=session_started_at,
        reservation_public_id=reservation_public_id,
    )


def sync_existing(
    conversation_id: str,
    *,
    kind: str = KIND_WHEELCHAIR,
    note: str | None = None,
    relationship: str | None = None,
    trip_date: str | None = None,
    customer_name: str = "",
    source_message_id: str = "",
) -> dict | None:
    """Atomically merge later corrections into one active assistance kind."""
    conversation_id = _clean(conversation_id, 240)
    if kind not in KINDS:
        raise CrewAssistanceError("invalid crew-assistance kind")
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM mermaid_crew_assistance WHERE tenant_slug='mermaid' "
            "AND conversation_id=? AND kind=? AND status!='withdrawn' "
            "ORDER BY updated_at DESC,id DESC LIMIT 1",
            (conversation_id, kind),
        ).fetchone()
        source_message_id = _clean(source_message_id, 200)
        if _source_seen(
            conn,
            conversation_id,
            source_message_id,
            int(row["id"]) if row is not None else None,
        ):
            conn.commit()
            return _projection(row)
        if row is None or row["status"] == "withdrawn":
            _record_source(
                conn,
                conversation_id,
                source_message_id,
                int(row["id"]) if row is not None else None,
                "sync",
            )
            conn.commit()
            return _projection(row)

        merged_note = _clean(note, 320) if note is not None else row["note_text"]
        merged_relationship = (
            _clean(relationship, 80)
            if relationship is not None
            else row["relationship"]
        )
        merged_trip_date = (
            _clean(trip_date, 10) if trip_date is not None else (row["trip_date"] or "")
        )
        merged_customer_name = _clean(customer_name, 160) or row["customer_name"]
        if not merged_note:
            raise CrewAssistanceError("crew-assistance note cannot be empty")
        material_hash = _material_hash(
            merged_note, merged_relationship, merged_trip_date
        )
        now = _now()
        if material_hash != row["material_hash"]:
            revision = int(row["revision"]) + 1
            reservation_public_id = _reservation_pointer_for_trip(
                conn, row, merged_trip_date
            )
            conn.execute(
                "UPDATE mermaid_crew_assistance SET customer_name=?,note_text=?,"
                "relationship=?,trip_date=?,reservation_public_id=?,"
                "status='unacknowledged',revision=?,"
                "source_message_id=?,material_hash=?,acknowledged_at=NULL,"
                "acknowledged_by=NULL,updated_at=? WHERE id=?",
                (
                    merged_customer_name,
                    merged_note,
                    merged_relationship,
                    merged_trip_date or None,
                    reservation_public_id,
                    revision,
                    source_message_id,
                    material_hash,
                    now,
                    row["id"],
                ),
            )
            _record_event(
                conn,
                int(row["id"]),
                "updated",
                revision,
                source_message_id=source_message_id,
                idempotency_key=_event_key(
                    "updated",
                    row["id"],
                    revision,
                    source_message_id,
                    material_hash,
                ),
                payload={"reopened": row["status"] == "acknowledged"},
            )
        elif merged_customer_name != row["customer_name"]:
            conn.execute(
                "UPDATE mermaid_crew_assistance SET customer_name=?,updated_at=? WHERE id=?",
                (merged_customer_name, now, row["id"]),
            )
        _record_source(
            conn,
            conversation_id,
            source_message_id,
            int(row["id"]),
            "sync",
        )
        current = conn.execute(
            "SELECT * FROM mermaid_crew_assistance WHERE id=?", (row["id"],)
        ).fetchone()
        _update_current_link_snapshot(
            conn,
            row,
            customer_name=current["customer_name"],
            note=current["note_text"],
            relationship=current["relationship"],
            trip_date=current["trip_date"] or "",
            status=current["status"],
            revision=int(current["revision"]),
            acknowledged_at=current["acknowledged_at"],
            acknowledged_by=current["acknowledged_by"],
        )
        conn.commit()
        return _projection(current)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def withdraw(
    conversation_id: str,
    *,
    source_message_id: str = "",
    actor: str = "guest_correction",
) -> dict | None:
    """Withdraw a stale note after an explicit guest correction."""
    conversation_id = _clean(conversation_id, 240)
    source_message_id = _clean(source_message_id, 200)
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM mermaid_crew_assistance WHERE tenant_slug='mermaid' "
            "AND conversation_id=? AND kind=?",
            (conversation_id, KIND_WHEELCHAIR),
        ).fetchone()
        if _source_seen(
            conn,
            conversation_id,
            source_message_id,
            int(row["id"]) if row is not None else None,
        ):
            conn.commit()
            return _projection(row)
        if row is None or row["status"] == "withdrawn":
            _record_source(
                conn,
                conversation_id,
                source_message_id,
                int(row["id"]) if row is not None else None,
                "withdraw",
            )
            conn.commit()
            return _projection(row)
        revision = int(row["revision"]) + 1
        now = _now()
        withdrawn_note = "Wheelchair note withdrawn after a guest correction."
        conn.execute(
            "UPDATE mermaid_crew_assistance SET note_text=?,relationship='',"
            "trip_date=NULL,status='withdrawn',revision=?,source_message_id=?,"
            "material_hash=?,acknowledged_at=NULL,acknowledged_by=NULL,"
            "updated_at=? WHERE id=?",
            (
                withdrawn_note,
                revision,
                source_message_id,
                _material_hash(withdrawn_note, "", ""),
                now,
                row["id"],
            ),
        )
        _record_event(
            conn,
            int(row["id"]),
            "withdrawn",
            revision,
            actor=actor,
            source_message_id=source_message_id,
            idempotency_key=_event_key(
                "withdrawn", row["id"], revision, source_message_id
            ),
        )
        _record_source(
            conn,
            conversation_id,
            source_message_id,
            int(row["id"]),
            "withdraw",
        )
        _update_current_link_snapshot(
            conn,
            row,
            customer_name=row["customer_name"],
            note=withdrawn_note,
            relationship="",
            trip_date=row["trip_date"] or "",
            status="withdrawn",
            revision=revision,
        )
        current = conn.execute(
            "SELECT * FROM mermaid_crew_assistance WHERE id=?", (row["id"],)
        ).fetchone()
        conn.commit()
        return _projection(current)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def link_reservation(
    conn: sqlite3.Connection,
    conversation_id: str,
    reservation_public_id: str,
    *,
    idempotency_key: str,
    trip_date: str = "",
    session_started_at: str | None = None,
    reassign_kinds: tuple[str, ...] = (),
    allow_session_reassignment: bool = False,
) -> None:
    """Link every active assistance kind inside the reservation transaction."""
    trip_date = _clean(trip_date, 10)
    session_filter = (
        _clean(session_started_at, 64)
        if session_started_at is not None
        else None
    )
    rows = conn.execute(
        "SELECT * FROM mermaid_crew_assistance WHERE tenant_slug='mermaid' "
        "AND conversation_id=? AND status!='withdrawn' "
        "ORDER BY id",
        (conversation_id,),
    ).fetchall()
    if not rows:
        return
    now = _now()
    for row in rows:
        if session_filter is not None and row["session_started_at"] != session_filter:
            continue
        session_owned = bool(
            allow_session_reassignment
            and session_filter is not None
            and row["session_started_at"] == session_filter
        )
        explicitly_owned = row["kind"] in reassign_kinds
        row_trip_date = str(row["trip_date"] or "")
        if trip_date and row_trip_date and row_trip_date != trip_date:
            target_link = conn.execute(
                "SELECT 1 FROM mermaid_crew_assistance_reservations "
                "WHERE assistance_id=? AND reservation_public_id=?",
                (row["id"], reservation_public_id),
            ).fetchone()
            if not (session_owned or explicitly_owned) or target_link is not None:
                # A workflow-owned correction may advance an item to a new
                # reservation date. A replay for an older linked reservation
                # cannot roll the current trip back.
                continue
            row = dict(row)
            reopened = row["status"] == "acknowledged"
            row["revision"] = int(row["revision"]) + 1
            row["trip_date"] = trip_date
            row["reservation_public_id"] = None
            row["status"] = "unacknowledged"
            row["acknowledged_at"] = None
            row["acknowledged_by"] = None
            row["material_hash"] = _material_hash(
                row["note_text"], row["relationship"], trip_date
            )
            row["updated_at"] = now
            conn.execute(
                "UPDATE mermaid_crew_assistance SET trip_date=?,"
                "reservation_public_id=NULL,status='unacknowledged',revision=?,"
                "material_hash=?,acknowledged_at=NULL,acknowledged_by=NULL,"
                "updated_at=? WHERE id=?",
                (
                    trip_date,
                    row["revision"],
                    row["material_hash"],
                    now,
                    row["id"],
                ),
            )
            _record_event(
                conn,
                int(row["id"]),
                "updated",
                int(row["revision"]),
                idempotency_key=_event_key(
                    "reservation_date_updated",
                    idempotency_key,
                    row["id"],
                    trip_date,
                ),
                payload={"tripDate": trip_date, "reopened": reopened},
            )
            row_trip_date = trip_date
        if (
            row["reservation_public_id"]
            and row["reservation_public_id"] != reservation_public_id
            and row["kind"] not in reassign_kinds
            and not session_owned
        ):
            # A current assistance intent belongs to at most one reservation.
            # A new provider source explicitly reasserting the same request
            # clears this pointer before another reservation may link it.
            continue
        inserted = conn.execute(
            "INSERT OR IGNORE INTO mermaid_crew_assistance_reservations "
            "(assistance_id,tenant_slug,reservation_public_id,customer_name,note_text,"
            "relationship,trip_date,status,revision,acknowledged_at,acknowledged_by,"
            "session_started_at,created_at) VALUES (?,'mermaid',?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["id"],
                reservation_public_id,
                row["customer_name"],
                row["note_text"],
                row["relationship"],
                row["trip_date"],
                row["status"],
                row["revision"],
                row["acknowledged_at"],
                row["acknowledged_by"],
                row["session_started_at"],
                now,
            ),
        )
        if inserted.rowcount == 0:
            linked = conn.execute(
                "SELECT revision,session_started_at FROM "
                "mermaid_crew_assistance_reservations WHERE assistance_id=? "
                "AND reservation_public_id=?",
                (row["id"], reservation_public_id),
            ).fetchone()
            if (
                not row["reservation_public_id"]
                and linked is not None
                and row["session_started_at"] == linked["session_started_at"]
                and int(row["revision"]) > int(linked["revision"])
            ):
                # A current correction can return to an earlier trip in the
                # same booking generation. Refresh that frozen snapshot and
                # restore its pointer; a stale/new-session replay cannot pass
                # the session and revision checks.
                conn.execute(
                    "UPDATE mermaid_crew_assistance_reservations SET "
                    "customer_name=?,note_text=?,relationship=?,trip_date=?,"
                    "status=?,revision=?,acknowledged_at=?,acknowledged_by=? "
                    "WHERE assistance_id=? AND reservation_public_id=?",
                    (
                        row["customer_name"],
                        row["note_text"],
                        row["relationship"],
                        row["trip_date"],
                        row["status"],
                        row["revision"],
                        row["acknowledged_at"],
                        row["acknowledged_by"],
                        row["id"],
                        reservation_public_id,
                    ),
                )
                conn.execute(
                    "UPDATE mermaid_crew_assistance SET reservation_public_id=?,"
                    "updated_at=? WHERE id=?",
                    (reservation_public_id, now, row["id"]),
                )
            continue
        if row["reservation_public_id"] == reservation_public_id:
            continue
        conn.execute(
            "UPDATE mermaid_crew_assistance SET reservation_public_id=?,updated_at=? "
            "WHERE id=?",
            (reservation_public_id, now, row["id"]),
        )
        _record_event(
            conn,
            int(row["id"]),
            "reservation_linked",
            int(row["revision"]),
            idempotency_key=_event_key(
                "reservation_linked",
                idempotency_key,
                row["id"],
                reservation_public_id,
            ),
            payload={"reservationPublicId": reservation_public_id},
        )


def link_current(conversation_id: str, reservation_public_id: str, *, idempotency_key: str) -> dict | None:
    """Link an item to an already-created reservation without changing its status."""
    conversation_id = _clean(conversation_id, 240)
    session_started_at = _conversation_session_started_at(conversation_id)
    conn = _conn()
    try:
        reservation = None
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='mermaid_reservations'"
        ).fetchone():
            reservation = conn.execute(
                "SELECT intake_json FROM mermaid_reservations "
                "WHERE tenant_slug='mermaid' AND public_id=?",
                (reservation_public_id,),
            ).fetchone()
        reservation_trip_date = ""
        if reservation is not None and reservation[0]:
            try:
                reservation_trip_date = str(
                    (json.loads(reservation[0]) or {}).get("trip_date") or ""
                )
            except (TypeError, ValueError):
                reservation_trip_date = ""
        conn.execute("BEGIN IMMEDIATE")
        link_reservation(
            conn,
            conversation_id,
            reservation_public_id,
            idempotency_key=idempotency_key,
            trip_date=reservation_trip_date,
            session_started_at=session_started_at,
        )
        row = conn.execute(
            "SELECT * FROM mermaid_crew_assistance WHERE tenant_slug='mermaid' "
            "AND conversation_id=? ORDER BY "
            "CASE status WHEN 'unacknowledged' THEN 0 "
            "WHEN 'acknowledged' THEN 1 ELSE 2 END,updated_at DESC,id DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        linked = bool(
            row is not None
            and conn.execute(
                "SELECT 1 FROM mermaid_crew_assistance_reservations "
                "WHERE assistance_id=? AND reservation_public_id=?",
                (row["id"], reservation_public_id),
            ).fetchone()
        )
        conn.commit()
        item = _projection(row)
        if item is not None and linked:
            item["reservationPublicId"] = reservation_public_id
        return item
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def for_conversation(
    conversation_id: str,
    *,
    kind: str | None = None,
    session_started_at: str | None = None,
) -> dict | None:
    if kind is not None and kind not in KINDS:
        raise CrewAssistanceError("invalid crew-assistance kind")
    conn = _conn()
    try:
        clauses = []
        args = [_clean(conversation_id, 240)]
        if kind is not None:
            clauses.append("kind=?")
            args.append(kind)
        if session_started_at is not None:
            clauses.append("session_started_at=?")
            args.append(_clean(session_started_at, 64))
        filters = "".join(f" AND {clause}" for clause in clauses)
        return _projection(conn.execute(
            "SELECT * FROM mermaid_crew_assistance WHERE tenant_slug='mermaid' "
            f"AND conversation_id=?{filters} ORDER BY "
            "CASE status WHEN 'unacknowledged' THEN 0 "
            "WHEN 'acknowledged' THEN 1 ELSE 2 END,updated_at DESC,id DESC LIMIT 1",
            tuple(args),
        ).fetchone())
    finally:
        conn.close()


def for_conversations(conversation_ids) -> dict[str, dict]:
    values = sorted(
        {
            _clean(value, 240)
            for value in conversation_ids
            if _clean(value, 240)
        }
    )
    if not values:
        return {}
    placeholders = ",".join("?" for _ in values)
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM mermaid_crew_assistance WHERE tenant_slug='mermaid' "
            f"AND conversation_id IN ({placeholders}) "
            "ORDER BY conversation_id,"
            "CASE status WHEN 'unacknowledged' THEN 0 "
            "WHEN 'acknowledged' THEN 1 ELSE 2 END,updated_at DESC,id DESC",
            values,
        ).fetchall()
        result = {}
        for row in rows:
            item = _projection(row)
            result.setdefault(item["conversationId"], item)
        return result
    finally:
        conn.close()


def for_reservation(public_id: str, *, kind: str | None = None) -> dict | None:
    if kind is not None and kind not in KINDS:
        raise CrewAssistanceError("invalid crew-assistance kind")
    conn = _conn()
    try:
        public_id = _clean(public_id, 80)
        kind_clause = " AND a.kind=?" if kind is not None else ""
        args = (public_id, kind) if kind is not None else (public_id,)
        row = conn.execute(
            "SELECT a.*,r.reservation_public_id AS linked_public_id,"
            "r.customer_name AS linked_customer_name,r.note_text AS linked_note_text,"
            "r.relationship AS linked_relationship,r.trip_date AS linked_trip_date,"
            "r.status AS linked_status,r.revision AS linked_revision,"
            "r.acknowledged_at AS linked_acknowledged_at,"
            "r.acknowledged_by AS linked_acknowledged_by "
            "FROM mermaid_crew_assistance a "
            "JOIN mermaid_crew_assistance_reservations r ON r.assistance_id=a.id "
            "WHERE r.tenant_slug='mermaid' AND r.reservation_public_id=? "
            f"{kind_clause} "
            "ORDER BY CASE r.status WHEN 'unacknowledged' THEN 0 "
            "WHEN 'acknowledged' THEN 1 ELSE 2 END,a.updated_at DESC,a.id DESC LIMIT 1",
            args,
        ).fetchone()
        if row is None:
            legacy_kind_clause = " AND kind=?" if kind is not None else ""
            row = conn.execute(
                "SELECT * FROM mermaid_crew_assistance WHERE tenant_slug='mermaid' "
                f"AND reservation_public_id=?{legacy_kind_clause} "
                "ORDER BY CASE status WHEN 'unacknowledged' THEN 0 "
                "WHEN 'acknowledged' THEN 1 ELSE 2 END,updated_at DESC,id DESC LIMIT 1",
                args,
            ).fetchone()
        item = _linked_projection(row)
        if item is not None:
            item["reservationPublicId"] = public_id
        return item
    finally:
        conn.close()


def for_reservations(public_ids, *, kind: str | None = None) -> dict[str, dict]:
    if kind is not None and kind not in KINDS:
        raise CrewAssistanceError("invalid crew-assistance kind")
    values = sorted(
        {_clean(value, 80) for value in public_ids if _clean(value, 80)}
    )
    if not values:
        return {}
    placeholders = ",".join("?" for _ in values)
    conn = _conn()
    try:
        kind_clause = " AND a.kind=?" if kind is not None else ""
        args = values + ([kind] if kind is not None else [])
        rows = conn.execute(
            "SELECT r.reservation_public_id AS linked_public_id,"
            "r.customer_name AS linked_customer_name,r.note_text AS linked_note_text,"
            "r.relationship AS linked_relationship,r.trip_date AS linked_trip_date,"
            "r.status AS linked_status,r.revision AS linked_revision,"
            "r.acknowledged_at AS linked_acknowledged_at,"
            "r.acknowledged_by AS linked_acknowledged_by,a.* FROM "
            "mermaid_crew_assistance_reservations r "
            "JOIN mermaid_crew_assistance a ON a.id=r.assistance_id "
            "WHERE r.tenant_slug='mermaid' "
            f"AND r.reservation_public_id IN ({placeholders}){kind_clause} "
            "ORDER BY r.reservation_public_id,"
            "CASE r.status WHEN 'unacknowledged' THEN 0 "
            "WHEN 'acknowledged' THEN 1 ELSE 2 END,a.updated_at DESC,a.id DESC",
            args,
        ).fetchall()
        result = {}
        for row in rows:
            item = _linked_projection(row)
            result.setdefault(row["linked_public_id"], item)
        missing = [value for value in values if value not in result]
        if missing:
            legacy_placeholders = ",".join("?" for _ in missing)
            legacy_kind_clause = " AND kind=?" if kind is not None else ""
            legacy_args = missing + ([kind] if kind is not None else [])
            legacy = conn.execute(
                "SELECT * FROM mermaid_crew_assistance WHERE tenant_slug='mermaid' "
                f"AND reservation_public_id IN ({legacy_placeholders})"
                f"{legacy_kind_clause} "
                "ORDER BY reservation_public_id,"
                "CASE status WHEN 'unacknowledged' THEN 0 "
                "WHEN 'acknowledged' THEN 1 ELSE 2 END,updated_at DESC,id DESC",
                legacy_args,
            ).fetchall()
            for row in legacy:
                result.setdefault(row["reservation_public_id"], _projection(row))
        return result
    finally:
        conn.close()


def list_items(
    status: str = "unacknowledged", *, limit: int = 100, offset: int = 0
) -> list[dict]:
    if status not in STATUSES | {"all"}:
        raise CrewAssistanceError("invalid crew-assistance status")
    if type(limit) is not int or not 1 <= limit <= 500:
        raise CrewAssistanceError("invalid crew-assistance limit")
    if type(offset) is not int or offset < 0:
        raise CrewAssistanceError("invalid crew-assistance offset")
    conn = _conn()
    try:
        sql = "SELECT * FROM mermaid_crew_assistance WHERE tenant_slug='mermaid'"
        args: tuple = ()
        if status != "all":
            sql += " AND status=?"
            args = (status,)
        rows = conn.execute(
            sql + " ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?",
            args + (limit, offset),
        ).fetchall()
        return [_projection(row) for row in rows]
    finally:
        conn.close()


def acknowledge(attention_id: int, *, expected_revision: int, acknowledged_by: str) -> dict:
    actor = _clean(acknowledged_by, 80)
    if not actor:
        raise CrewAssistanceError("acknowledgedBy is required")
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM mermaid_crew_assistance WHERE tenant_slug='mermaid' AND id=?",
            (int(attention_id),),
        ).fetchone()
        if row is None:
            raise CrewAssistanceNotFound("crew-assistance item not found")
        if int(row["revision"]) != int(expected_revision):
            raise CrewAssistanceConflict("crew-assistance item changed; reload before acknowledging")
        if row["status"] == "withdrawn":
            raise CrewAssistanceConflict("withdrawn crew-assistance item cannot be acknowledged")
        if row["status"] != "acknowledged":
            now = _now()
            conn.execute(
                "UPDATE mermaid_crew_assistance SET status='acknowledged',acknowledged_at=?,"
                "acknowledged_by=?,updated_at=? WHERE id=? AND revision=?",
                (now, actor, now, int(attention_id), int(expected_revision)),
            )
            _record_event(
                conn,
                int(attention_id),
                "acknowledged",
                int(expected_revision),
                actor=actor,
                idempotency_key=_event_key("acknowledged", attention_id, expected_revision),
            )
        current = conn.execute(
            "SELECT * FROM mermaid_crew_assistance WHERE id=?", (int(attention_id),)
        ).fetchone()
        _update_current_link_snapshot(
            conn,
            row,
            customer_name=current["customer_name"],
            note=current["note_text"],
            relationship=current["relationship"],
            trip_date=current["trip_date"] or "",
            status=current["status"],
            revision=int(current["revision"]),
            acknowledged_at=current["acknowledged_at"],
            acknowledged_by=current["acknowledged_by"],
        )
        # One queue item represents the same private assistance instruction
        # across linked reservations. Acknowledging that item clears any older
        # unread reservation marker while preserving a prior acknowledgement.
        conn.execute(
            "UPDATE mermaid_crew_assistance_reservations SET "
            "status='acknowledged',acknowledged_at=?,acknowledged_by=? "
            "WHERE assistance_id=? AND status='unacknowledged'",
            (
                current["acknowledged_at"],
                current["acknowledged_by"],
                int(attention_id),
            ),
        )
        conn.commit()
        return _projection(current)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def events(attention_id: int) -> list[dict]:
    conn = _conn()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT id,event_type,revision,actor,source_message_id,payload_json,created_at "
            "FROM mermaid_crew_assistance_events WHERE assistance_id=? ORDER BY id",
            (int(attention_id),),
        ).fetchall()]
    finally:
        conn.close()
