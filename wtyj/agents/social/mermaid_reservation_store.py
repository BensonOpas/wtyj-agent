"""Durable reservation aggregate for Mermaid's no-money demonstration."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Iterable

from shared import mermaid_catalog, state_registry


class MermaidReservationError(RuntimeError):
    pass


TERMINAL_STATES = {"cancelled", "booked"}
TRANSITIONS = {
    "demo_availability_approved": {"quote_ready", "cancelled"},
    "quote_ready": {"demo_payment_pending", "cancelled"},
    "demo_payment_pending": {"demo_paid", "cancelled"},
    "demo_paid": {"booked"},
    "booked": set(),
    "cancelled": set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(state_registry.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mermaid_reservations (
            public_id TEXT PRIMARY KEY,
            tenant_slug TEXT NOT NULL CHECK (tenant_slug = 'mermaid'),
            conversation_id TEXT NOT NULL,
            summary_version TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            language TEXT NOT NULL,
            intake_json TEXT NOT NULL,
            catalog_version TEXT NOT NULL,
            monetary_snapshot_json TEXT NOT NULL,
            state TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            availability_source TEXT NOT NULL CHECK (availability_source = 'demo_assumed'),
            booking_code TEXT NOT NULL UNIQUE,
            quote_public_id TEXT,
            payment_reference TEXT,
            receipt_public_id TEXT,
            human_takeover INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_slug, conversation_id, summary_version)
        );
        CREATE INDEX IF NOT EXISTS idx_mermaid_reservation_conversation
          ON mermaid_reservations(tenant_slug, conversation_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS mermaid_reservation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reservation_public_id TEXT NOT NULL,
            tenant_slug TEXT NOT NULL,
            event_type TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT,
            actor TEXT NOT NULL,
            reason TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            revision INTEGER NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE (tenant_slug, idempotency_key),
            FOREIGN KEY (reservation_public_id) REFERENCES mermaid_reservations(public_id)
        );
        """
    )


def _row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    value = dict(row)
    for key in ("intake_json", "monetary_snapshot_json"):
        value[key.removesuffix("_json")] = json.loads(value.pop(key))
    value["human_takeover"] = bool(value["human_takeover"])
    return value


def _summary_version(intake: dict) -> str:
    owned = {
        key: intake.get(key)
        for key in (
            "trip_date", "adults", "children", "infants", "customer_name",
            "pickup_preference", "pickup_location", "dietary_requirements",
            "accessibility_notes", "special_requests", "language",
        )
    }
    encoded = json.dumps(owned, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _money_snapshot(intake: dict, catalog: dict) -> dict:
    currency = str(intake.get("currency") or catalog["pricing"]["default_currency"])
    prices = catalog["pricing"]["currencies"].get(currency)
    if not prices:
        raise MermaidReservationError("unsupported reservation currency")
    quantities = {
        "adult": int(intake.get("adults") or 0),
        "child_4_12": int(intake.get("children") or 0),
        "infant_0_3": int(intake.get("infants") or 0),
    }
    items = []
    total = 0
    for key, label in (
        ("adult", "Adult"),
        ("child_4_12", "Child age 4-12"),
        ("infant_0_3", "Child age 0-3"),
    ):
        unit = int(prices[key])
        quantity = quantities[key]
        line_total = unit * quantity
        total += line_total
        items.append({
            "key": key, "label": label, "quantity": quantity,
            "unit_amount": unit, "line_total": line_total,
        })
    return {
        "currency": currency,
        "items": items,
        "total": total,
        "pickup_amount": None,
        "catalog_version": catalog["version"],
    }


def _booking_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "MER-DEMO-" + "".join(secrets.choice(alphabet) for _ in range(8))


def confirm_reservation(
    conversation_id: str,
    intake: dict,
    *,
    idempotency_key: str,
    actor: str = "tracy",
) -> dict:
    """Create exactly one assumed-available reservation per confirmed summary."""
    required = {"trip_date", "adults", "children", "infants", "customer_name", "pickup_preference", "language"}
    if not required.issubset(intake):
        raise MermaidReservationError("confirmed intake is incomplete")
    if intake.get("phase") != "summary_confirmed":
        raise MermaidReservationError("summary is not confirmed")
    catalog = mermaid_catalog.get_catalog()
    version = _summary_version(intake)
    now = _now()
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM mermaid_reservations WHERE tenant_slug='mermaid' "
            "AND conversation_id=? AND summary_version=?",
            (conversation_id, version),
        ).fetchone()
        if existing:
            conn.commit()
            return _row(existing)
        public_id = "mer_" + uuid.uuid4().hex
        snapshot = _money_snapshot(intake, catalog)
        for _ in range(10):
            code = _booking_code()
            try:
                conn.execute(
                    "INSERT INTO mermaid_reservations (public_id, tenant_slug, conversation_id, "
                    "summary_version, customer_name, language, intake_json, catalog_version, "
                    "monetary_snapshot_json, state, revision, availability_source, booking_code, "
                    "created_at, updated_at) VALUES (?, 'mermaid', ?, ?, ?, ?, ?, ?, ?, "
                    "'demo_availability_approved', 1, 'demo_assumed', ?, ?, ?)",
                    (
                        public_id, conversation_id, version, intake["customer_name"], intake["language"],
                        json.dumps(intake, ensure_ascii=False, sort_keys=True), catalog["version"],
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True), code, now, now,
                    ),
                )
                break
            except sqlite3.IntegrityError as exc:
                if "booking_code" not in str(exc):
                    raise
        else:
            raise MermaidReservationError("unable to allocate unique booking code")
        conn.execute(
            "INSERT INTO mermaid_reservation_events (reservation_public_id, tenant_slug, event_type, "
            "from_state, to_state, actor, reason, idempotency_key, revision, payload_json, created_at) "
            "VALUES (?, 'mermaid', 'summary_confirmed', NULL, 'demo_availability_approved', ?, ?, ?, 1, ?, ?)",
            (
                public_id, actor, "Demo availability assumed; no inventory provider called",
                idempotency_key or f"confirm:{conversation_id}:{version}",
                json.dumps({"availability_source": "demo_assumed", "catalog_version": catalog["version"]}), now,
            ),
        )
        conn.commit()
        return get_reservation(public_id, connection=conn)
    except sqlite3.IntegrityError:
        conn.rollback()
        existing = conn.execute(
            "SELECT * FROM mermaid_reservations WHERE tenant_slug='mermaid' "
            "AND conversation_id=? AND summary_version=?",
            (conversation_id, version),
        ).fetchone()
        if existing:
            return _row(existing)
        raise
    finally:
        conn.close()


def get_reservation(public_id: str, *, connection: sqlite3.Connection | None = None) -> dict | None:
    owns = connection is None
    conn = connection or _conn()
    try:
        return _row(conn.execute(
            "SELECT * FROM mermaid_reservations WHERE tenant_slug='mermaid' AND public_id=?",
            (public_id,),
        ).fetchone())
    finally:
        if owns:
            conn.close()


def latest_for_conversation(conversation_id: str) -> dict | None:
    conn = _conn()
    try:
        return _row(conn.execute(
            "SELECT * FROM mermaid_reservations WHERE tenant_slug='mermaid' AND conversation_id=? "
            "ORDER BY created_at DESC LIMIT 1",
            (conversation_id,),
        ).fetchone())
    finally:
        conn.close()


def list_reservations(limit: int = 100) -> list[dict]:
    conn = _conn()
    try:
        return [_row(row) for row in conn.execute(
            "SELECT * FROM mermaid_reservations WHERE tenant_slug='mermaid' "
            "ORDER BY updated_at DESC LIMIT ?", (max(1, min(int(limit), 500)),)
        ).fetchall()]
    finally:
        conn.close()


def transition(
    public_id: str,
    to_state: str,
    *,
    idempotency_key: str,
    actor: str,
    reason: str,
    updates: dict | None = None,
) -> dict:
    """Apply one optimistic, replay-safe transition with an audit event."""
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        replay = conn.execute(
            "SELECT reservation_public_id FROM mermaid_reservation_events "
            "WHERE tenant_slug='mermaid' AND idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if replay:
            conn.commit()
            return get_reservation(replay[0], connection=conn)
        row = conn.execute(
            "SELECT * FROM mermaid_reservations WHERE tenant_slug='mermaid' AND public_id=?",
            (public_id,),
        ).fetchone()
        if row is None:
            raise MermaidReservationError("reservation not found")
        current = _row(row)
        if current["human_takeover"]:
            raise MermaidReservationError("reservation is frozen for human takeover")
        from_state = current["state"]
        if to_state not in TRANSITIONS.get(from_state, set()):
            raise MermaidReservationError(f"invalid transition {from_state} -> {to_state}")
        allowed_updates = {"quote_public_id", "payment_reference", "receipt_public_id"}
        clean_updates = {k: v for k, v in (updates or {}).items() if k in allowed_updates}
        revision = int(current["revision"]) + 1
        now = _now()
        assignments = ["state=?", "revision=?", "updated_at=?"]
        values: list = [to_state, revision, now]
        for key, value in clean_updates.items():
            assignments.append(f"{key}=?")
            values.append(value)
        values.extend([public_id, int(current["revision"])])
        changed = conn.execute(
            f"UPDATE mermaid_reservations SET {', '.join(assignments)} "
            "WHERE tenant_slug='mermaid' AND public_id=? AND revision=?",
            values,
        ).rowcount
        if changed != 1:
            raise MermaidReservationError("concurrent reservation update")
        conn.execute(
            "INSERT INTO mermaid_reservation_events (reservation_public_id, tenant_slug, event_type, "
            "from_state, to_state, actor, reason, idempotency_key, revision, payload_json, created_at) "
            "VALUES (?, 'mermaid', 'state_transition', ?, ?, ?, ?, ?, ?, ?, ?)",
            (public_id, from_state, to_state, actor, reason, idempotency_key, revision,
             json.dumps(clean_updates, ensure_ascii=False, sort_keys=True), now),
        )
        conn.commit()
        return get_reservation(public_id, connection=conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cancel(public_id: str, *, idempotency_key: str, actor: str = "customer") -> dict:
    current = get_reservation(public_id)
    if current is None:
        raise MermaidReservationError("reservation not found")
    if current["state"] == "cancelled":
        return current
    if current["state"] in {"demo_paid", "booked"}:
        raise MermaidReservationError("paid demo reservation cannot be cancelled automatically")
    return transition(
        public_id, "cancelled", idempotency_key=idempotency_key,
        actor=actor, reason="Cancelled before simulated payment",
    )


def freeze_for_human(public_id: str) -> dict:
    conn = _conn()
    try:
        conn.execute(
            "UPDATE mermaid_reservations SET human_takeover=1, updated_at=? "
            "WHERE tenant_slug='mermaid' AND public_id=?", (_now(), public_id)
        )
        conn.commit()
        result = get_reservation(public_id, connection=conn)
        if result is None:
            raise MermaidReservationError("reservation not found")
        return result
    finally:
        conn.close()


def events(public_id: str) -> list[dict]:
    conn = _conn()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM mermaid_reservation_events WHERE tenant_slug='mermaid' "
            "AND reservation_public_id=? ORDER BY id", (public_id,)
        ).fetchall()]
    finally:
        conn.close()
