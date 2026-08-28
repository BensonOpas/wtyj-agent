"""Durable recovery for abandoned Ali official-quote jobs.

A confirmed ``ali_quotes`` row is the durable queue record.  The normal inbound
path starts a fast daemon worker, while this supervised process reclaims only
rows that have stopped making progress.  Recovery uses a SQLite lease so two
recovery processes can never work the same quote at the same time.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

from agents.social import ali_quote_workflow as workflow
from shared import bm_logger, config_loader, state_registry


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


POLL_SECONDS = _env_int("ALI_QUOTE_RECOVERY_POLL_SECONDS", 5, 1, 60)
STARTUP_GRACE_SECONDS = _env_int(
    "ALI_QUOTE_RECOVERY_STARTUP_GRACE_SECONDS", 90, 0, 600,
)
LEASE_SECONDS = _env_int("ALI_QUOTE_RECOVERY_LEASE_SECONDS", 600, 120, 3600)
HEARTBEAT_SECONDS = _env_int(
    "ALI_QUOTE_RECOVERY_HEARTBEAT_SECONDS", 30, 5, 300,
)
MAX_CONCURRENCY = _env_int("ALI_QUOTE_RECOVERY_MAX_CONCURRENCY", 4, 1, 16)
MAX_ATTEMPTS = _env_int("ALI_QUOTE_RECOVERY_MAX_ATTEMPTS", 6, 1, 20)

# The normal inbound worker should update these states almost immediately.  The
# recovery process deliberately waits long enough to avoid racing that worker.
_STALE_AFTER_SECONDS = {
    "confirmed": 30,
    "pricing": 60,
    "quoted": 60,
    "pdf_ready": 60,
    # A healthy customer delivery intentionally waits up to three minutes.
    "delivering": 4 * 60,
}

_RETRYABLE_ERROR_CODES = {
    "staff_email_failed",
    "brand_image_delivery_failed",
    "whatsapp_delivery_failed",
    "unexpected_processor_failure",
    # Before issue #288 the outer processor collapsed every AliQuoteError into
    # this code.  Bounded recovery must reclaim those legacy rows once so a
    # confirmed replacement quote is not stranded forever.
    "processor_unconfigured",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(state_registry.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def feature_enabled(raw: dict | None = None) -> bool:
    """Enable only for Ali while retaining one emergency rollback switch."""
    raw = raw if raw is not None else (config_loader.get_raw() or {})
    features = raw.get("features") if isinstance(raw, dict) else {}
    return bool(
        workflow.tenant_enabled(raw)
        and isinstance(features, dict)
        and features.get("ali_quote_recovery_enabled", True) is not False
    )


def ensure_schema() -> None:
    """Create the additive lease table after the authoritative quote schema."""
    workflow.ensure_schema()
    conn = _connection()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ali_quote_processing_leases ("
            "public_id TEXT PRIMARY KEY, "
            "owner_token TEXT NOT NULL, "
            "claimed_at TEXT NOT NULL, "
            "heartbeat_at TEXT NOT NULL, "
            "lease_expires_at TEXT NOT NULL, "
            "FOREIGN KEY(public_id) REFERENCES ali_quotes(public_id) ON DELETE CASCADE"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ali_quote_lease_expiry "
            "ON ali_quote_processing_leases(lease_expires_at)"
        )
        conn.commit()
    finally:
        conn.close()


def _retryable_error(code: object) -> bool:
    value = str(code or "").strip()
    return bool(
        value in _RETRYABLE_ERROR_CODES
        or value.endswith("_temporary_failure")
        or value.startswith("ali_http_5")
        or value.startswith("rental_catalog_temporary_")
    )


def _attention_backoff_seconds(attempt_count: object) -> int:
    try:
        attempts = max(1, int(attempt_count or 1))
    except (TypeError, ValueError):
        attempts = 1
    return min(5 * 60, 15 * (2 ** min(attempts - 1, 5)))


def quote_is_recoverable(
    quote: dict,
    *,
    now: datetime | None = None,
    max_attempts: int = MAX_ATTEMPTS,
) -> bool:
    """Return whether one immutable quote row has stopped making progress."""
    if not isinstance(quote, dict) or quote.get("customer_delivery_superseded_at"):
        return False
    current = (now or _now()).astimezone(timezone.utc)
    updated = (
        _parse_timestamp(quote.get("updated_at"))
        or _parse_timestamp(quote.get("confirmed_at"))
    )
    if updated is None:
        return False

    status = str(quote.get("status") or "")
    if status in _STALE_AFTER_SECONDS:
        return (current - updated).total_seconds() >= _STALE_AFTER_SECONDS[status]

    if status != "attention_required":
        return False
    try:
        attempts = int(quote.get("attempt_count") or 0)
    except (TypeError, ValueError):
        return False
    if attempts >= max_attempts or not _retryable_error(quote.get("last_error_code")):
        return False
    return (current - updated).total_seconds() >= _attention_backoff_seconds(attempts)


def list_recoverable_quotes(
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> list[dict]:
    """List newest stale/retryable rows without exposing customer data.

    Newest-first is deliberate.  Old, terminal ``attention_required`` rows must
    never fill the bounded scan window and starve a newly confirmed replacement
    quote behind them.
    """
    ensure_schema()
    conn = _connection()
    try:
        rows = conn.execute(
            "SELECT * FROM ali_quotes WHERE customer_delivery_superseded_at IS NULL "
            "AND status IN ('confirmed','pricing','quoted','pdf_ready','delivering',"
            "'attention_required') ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows if quote_is_recoverable(dict(row), now=now)]


def acquire_lease(
    public_id: str,
    *,
    owner_token: str | None = None,
    now: datetime | None = None,
    lease_seconds: int = LEASE_SECONDS,
) -> str | None:
    """Atomically acquire or reclaim one expired recovery lease."""
    if not str(public_id or "").strip():
        return None
    ensure_schema()
    current = (now or _now()).astimezone(timezone.utc)
    token = str(owner_token or secrets.token_urlsafe(24))
    expires = current + timedelta(seconds=max(120, int(lease_seconds)))
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT owner_token, lease_expires_at FROM ali_quote_processing_leases "
            "WHERE public_id = ?",
            (public_id,),
        ).fetchone()
        if row:
            lease_expiry = _parse_timestamp(row["lease_expires_at"])
            if lease_expiry is not None and lease_expiry > current:
                conn.commit()
                return None
            conn.execute(
                "UPDATE ali_quote_processing_leases SET owner_token = ?, "
                "claimed_at = ?, heartbeat_at = ?, lease_expires_at = ? "
                "WHERE public_id = ?",
                (token, _iso(current), _iso(current), _iso(expires), public_id),
            )
        else:
            conn.execute(
                "INSERT INTO ali_quote_processing_leases "
                "(public_id, owner_token, claimed_at, heartbeat_at, lease_expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (public_id, token, _iso(current), _iso(current), _iso(expires)),
            )
        conn.commit()
        return token
    except sqlite3.IntegrityError:
        conn.rollback()
        return None
    finally:
        conn.close()


def renew_lease(
    public_id: str,
    owner_token: str,
    *,
    now: datetime | None = None,
    lease_seconds: int = LEASE_SECONDS,
) -> bool:
    current = (now or _now()).astimezone(timezone.utc)
    conn = _connection()
    try:
        cursor = conn.execute(
            "UPDATE ali_quote_processing_leases SET heartbeat_at = ?, "
            "lease_expires_at = ? WHERE public_id = ? AND owner_token = ?",
            (
                _iso(current),
                _iso(current + timedelta(seconds=max(120, int(lease_seconds)))),
                public_id,
                owner_token,
            ),
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def release_lease(public_id: str, owner_token: str) -> bool:
    conn = _connection()
    try:
        cursor = conn.execute(
            "DELETE FROM ali_quote_processing_leases "
            "WHERE public_id = ? AND owner_token = ?",
            (public_id, owner_token),
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def _lease_heartbeat(
    public_id: str,
    owner_token: str,
    stop_event: threading.Event,
) -> None:
    while not stop_event.wait(HEARTBEAT_SECONDS):
        try:
            if not renew_lease(public_id, owner_token):
                bm_logger.log(
                    "ali_quote_recovery_lease_lost",
                    quote_public_id=str(public_id)[:40],
                )
                return
        except Exception as exc:  # Lease expiry still permits later recovery.
            bm_logger.log(
                "ali_quote_recovery_heartbeat_failed",
                quote_public_id=str(public_id)[:40],
                error=type(exc).__name__,
            )


def recover_quote(
    quote: dict,
    *,
    processor: Callable[[str], None] | None = None,
    now: datetime | None = None,
) -> str:
    """Recover one stale quote exactly once across recovery processes."""
    public_id = str((quote or {}).get("public_id") or "")
    token = acquire_lease(public_id, now=now)
    if not token:
        return "lease_busy"
    heartbeat_stop = threading.Event()
    heartbeat = threading.Thread(
        target=_lease_heartbeat,
        args=(public_id, token, heartbeat_stop),
        name=f"ali-quote-lease-{public_id[:8]}",
        daemon=True,
    )
    try:
        current = workflow.get_quote(public_id)
        if not current or not quote_is_recoverable(current, now=now):
            return "no_longer_recoverable"
        bm_logger.log(
            "ali_quote_recovery_started",
            quote_public_id=public_id[:40],
            quote_status=str(current.get("status") or "")[:30],
            attempt_count=int(current.get("attempt_count") or 0),
            last_error_code=str(current.get("last_error_code") or "")[:80],
        )
        heartbeat.start()
        (processor or workflow._process_production)(public_id)
        result = workflow.get_quote(public_id) or {}
        bm_logger.log(
            "ali_quote_recovery_finished",
            quote_public_id=public_id[:40],
            quote_status=str(result.get("status") or "")[:30],
            attempt_count=int(result.get("attempt_count") or 0),
            last_error_code=str(result.get("last_error_code") or "")[:80],
        )
        return str(result.get("status") or "processed")
    except Exception as exc:
        bm_logger.log(
            "ali_quote_recovery_crashed",
            quote_public_id=public_id[:40],
            error=type(exc).__name__,
        )
        return "processor_crashed"
    finally:
        heartbeat_stop.set()
        if heartbeat.is_alive():
            heartbeat.join(timeout=2)
        try:
            release_lease(public_id, token)
        except Exception as exc:
            bm_logger.log(
                "ali_quote_recovery_release_failed",
                quote_public_id=public_id[:40],
                error=type(exc).__name__,
            )


def recover_once(
    *,
    processor: Callable[[str], None] | None = None,
    now: datetime | None = None,
    limit: int = 20,
) -> int:
    """Synchronously recover a bounded batch; useful at tests and operations."""
    if not feature_enabled():
        return 0
    recovered = 0
    for quote in list_recoverable_quotes(now=now, limit=limit):
        outcome = recover_quote(quote, processor=processor, now=now)
        if outcome not in {"lease_busy", "no_longer_recoverable"}:
            recovered += 1
    return recovered


def run_forever(stop_event: threading.Event | None = None) -> None:
    """Continuously reclaim abandoned quote jobs under supervisor."""
    stop = stop_event or threading.Event()
    if not feature_enabled():
        bm_logger.log("ali_quote_recovery_disabled")
        return
    ensure_schema()
    if STARTUP_GRACE_SECONDS and stop.wait(STARTUP_GRACE_SECONDS):
        return

    active: dict[str, threading.Thread] = {}
    bm_logger.log(
        "ali_quote_recovery_running",
        poll_seconds=POLL_SECONDS,
        startup_grace_seconds=STARTUP_GRACE_SECONDS,
        max_concurrency=MAX_CONCURRENCY,
    )
    while not stop.is_set():
        active = {key: thread for key, thread in active.items() if thread.is_alive()}
        slots = max(0, MAX_CONCURRENCY - len(active))
        if slots:
            try:
                candidates = list_recoverable_quotes(limit=max(20, slots * 4))
                for quote in candidates:
                    public_id = str(quote.get("public_id") or "")
                    if not public_id or public_id in active or len(active) >= MAX_CONCURRENCY:
                        continue
                    thread = threading.Thread(
                        target=recover_quote,
                        kwargs={"quote": quote},
                        name=f"ali-quote-recovery-{public_id[:8]}",
                        daemon=True,
                    )
                    active[public_id] = thread
                    thread.start()
            except Exception as exc:
                bm_logger.log(
                    "ali_quote_recovery_scan_failed",
                    error=type(exc).__name__,
                )
        stop.wait(POLL_SECONDS)


def main() -> int:
    run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
