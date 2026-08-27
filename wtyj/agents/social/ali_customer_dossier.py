"""Secure post-availability customer file for Ali reservations.

This module extends Brief 290's reservation/event model.  It deliberately
keeps binary identity material outside SQLite and outside the public web root;
only opaque identifiers and safe verification metadata are persisted.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import tempfile
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from textwrap import wrap

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from agents.social import ali_reservation_workflow as reservation
from shared import config_loader, state_registry


TENANT_SLUG = "ali-car-rental"
DOCUMENT_SLOTS = ("license_front", "license_back", "identity")
DOCUMENT_MIMES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}
DOCUMENT_STATUSES = {
    "received", "verified", "rejected", "replacement_requested",
    "replaced", "deleted", "not_required",
}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 20
MAX_IMAGE_PIXELS = 40_000_000
TOKEN_PURPOSES = {"document_upload", "contract_sign"}
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_ACTIVE_PDF_MARKERS = (
    b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile",
    b"/RichMedia", b"/OpenAction", b"/AA",
)
_PAYMENT_REPORT_PATTERNS = (
    re.compile(r"^(?:i(?:'ve| have)? paid(?: the (?:deposit|payment))?|payment (?:is )?(?:done|sent)|paid)$", re.I),
    re.compile(r"^(?:ik heb betaald|betaling (?:is )?(?:gedaan|verzonden)|betaald)$", re.I),
    re.compile(r"^(?:mi a paga(?: e deposito)?|mi paga kaba|pago kaba)$", re.I),
    re.compile(r"^(?:ich habe bezahlt|zahlung (?:ist )?(?:erledigt|gesendet)|bezahlt)$", re.I),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def is_customer_payment_report(text: object) -> bool:
    """Recognize only clear standalone payment reports, never questions."""
    normalized = " ".join(str(text or "").strip().rstrip(".! ").split())
    return bool(normalized) and any(
        pattern.fullmatch(normalized) for pattern in _PAYMENT_REPORT_PATTERNS
    )


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(state_registry.DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _config(raw: dict | None = None) -> dict:
    raw = raw if raw is not None else (config_loader.get_raw() or {})
    value = raw.get("ali_customer_dossier") if isinstance(raw, dict) else {}
    return value if isinstance(value, dict) else {}


def configuration_status(raw: dict | None = None) -> dict:
    """Return non-secret activation gates for staff diagnostics."""
    raw = raw if raw is not None else (config_loader.get_raw() or {})
    settings = _config(raw)
    template = Path(str(settings.get("contract_template_path") or ""))
    domains = settings.get("payment_allowed_domains") or []
    retention = settings.get("document_retention_days")
    blockers = []
    if not reservation.customer_dossier_enabled(raw):
        blockers.append("feature_disabled")
    if not template.is_absolute() or not template.is_file():
        blockers.append("approved_contract_template_missing")
    if not str(settings.get("contract_template_version") or "").strip():
        blockers.append("contract_template_version_missing")
    if not isinstance(domains, list) or not any(str(item).strip() for item in domains):
        blockers.append("payment_domain_allowlist_missing")
    if isinstance(retention, bool) or not isinstance(retention, int) or retention < 1:
        blockers.append("document_retention_policy_missing")
    if not str(settings.get("paper_shredding_policy") or "").strip():
        blockers.append("paper_shredding_policy_missing")
    if len(_token_secret(allow_missing=True)) < 32:
        blockers.append("token_secret_missing")
    try:
        _private_root(settings)
    except reservation.AliReservationError:
        blockers.append("private_storage_invalid")
    return {
        "enabled": reservation.customer_dossier_enabled(raw),
        "ready": not blockers,
        "blockers": blockers,
    }


def _require_ready() -> dict:
    status = configuration_status()
    if not status["ready"]:
        raise reservation.AliReservationError("customer_dossier_not_configured", 409)
    return _config()


def _private_root(settings: dict | None = None) -> Path:
    settings = settings if settings is not None else _config()
    raw = str(
        os.environ.get("ALI_RESERVATION_PRIVATE_ROOT")
        or settings.get("private_storage_root")
        or "/app/data/ali-reservation-private"
    )
    root = Path(raw).expanduser().resolve()
    if not root.is_absolute() or "public" in {part.casefold() for part in root.parts}:
        raise reservation.AliReservationError("invalid_private_storage_root", 409)
    return root


def _token_secret(*, allow_missing: bool = False) -> str:
    value = str(
        os.environ.get("ALI_RESERVATION_TOKEN_SECRET")
        or os.environ.get("ALI_QUOTE_DOWNLOAD_SECRET")
        or ""
    )
    if not allow_missing and len(value) < 32:
        raise reservation.AliReservationError("reservation_token_secret_missing", 409)
    return value


def _public_base_url() -> str:
    value = str(os.environ.get("UNBOKS_PUBLIC_BASE_URL") or "").rstrip("/")
    if not value.startswith("https://"):
        raise reservation.AliReservationError("public_base_url_missing", 409)
    return value


def ensure_schema() -> None:
    reservation.ensure_schema()
    conn = _connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ali_reservation_tokens (
                token_hash TEXT PRIMARY KEY,
                tenant_slug TEXT NOT NULL,
                reservation_public_id TEXT NOT NULL,
                purpose TEXT NOT NULL,
                slot TEXT NOT NULL DEFAULT '',
                target_public_id TEXT NOT NULL DEFAULT '',
                expires_at TEXT NOT NULL,
                used_at TEXT,
                result_public_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(reservation_public_id)
                    REFERENCES ali_reservations(public_id) ON DELETE RESTRICT
            );
            CREATE INDEX IF NOT EXISTS idx_ali_reservation_tokens_case
                ON ali_reservation_tokens(tenant_slug, reservation_public_id, purpose, slot);

            CREATE TABLE IF NOT EXISTS ali_reservation_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                public_id TEXT NOT NULL UNIQUE,
                tenant_slug TEXT NOT NULL,
                reservation_public_id TEXT NOT NULL,
                slot TEXT NOT NULL,
                version INTEGER NOT NULL,
                mime_type TEXT,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT,
                storage_name TEXT,
                status TEXT NOT NULL,
                previous_document_public_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                verified_at TEXT,
                verified_by TEXT,
                deleted_at TEXT,
                deleted_by TEXT,
                UNIQUE(reservation_public_id, slot, version),
                FOREIGN KEY(reservation_public_id)
                    REFERENCES ali_reservations(public_id) ON DELETE RESTRICT
            );
            CREATE INDEX IF NOT EXISTS idx_ali_reservation_documents_case
                ON ali_reservation_documents(tenant_slug, reservation_public_id, slot, version DESC);

            CREATE TABLE IF NOT EXISTS ali_reservation_contracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                public_id TEXT NOT NULL UNIQUE,
                tenant_slug TEXT NOT NULL,
                reservation_public_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                template_version TEXT NOT NULL,
                template_sha256 TEXT NOT NULL,
                snapshot_sha256 TEXT NOT NULL,
                status TEXT NOT NULL,
                unsigned_storage_name TEXT NOT NULL,
                signed_storage_name TEXT,
                signed_pdf_sha256 TEXT,
                legal_name TEXT,
                signature_sha256 TEXT,
                sent_at TEXT,
                viewed_at TEXT,
                signed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(reservation_public_id, version),
                FOREIGN KEY(reservation_public_id)
                    REFERENCES ali_reservations(public_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS ali_reservation_payments (
                reservation_public_id TEXT PRIMARY KEY,
                tenant_slug TEXT NOT NULL,
                payment_url TEXT,
                payment_domain TEXT,
                payment_reference TEXT,
                link_sent_at TEXT,
                customer_reported_at TEXT,
                verified_at TEXT,
                verified_by TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(reservation_public_id)
                    REFERENCES ali_reservations(public_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS ali_reservation_dossier_audits (
                reservation_public_id TEXT NOT NULL,
                tenant_slug TEXT NOT NULL,
                version INTEGER NOT NULL,
                status TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                page_count INTEGER NOT NULL,
                page_size TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(reservation_public_id, version),
                FOREIGN KEY(reservation_public_id)
                    REFERENCES ali_reservations(public_id) ON DELETE RESTRICT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _case(conn: sqlite3.Connection, public_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM ali_reservations WHERE tenant_slug = ? AND public_id = ?",
        (TENANT_SLUG, str(public_id)),
    ).fetchone()
    if not row:
        raise reservation.AliReservationError("reservation_not_found", 404)
    return row


def customer_delivery_context(public_id: str) -> dict:
    """Return the non-document routing anchor for one tenant-bound case."""
    ensure_schema()
    conn = _connection()
    try:
        case = _case(conn, public_id)
        quote = conn.execute(
            "SELECT locale FROM ali_quotes WHERE public_id = ? AND quote_snapshot_id = ?",
            (case["quote_public_id"], case["quote_snapshot_id"]),
        ).fetchone()
        return {
            "conversation_id": str(case["conversation_id"]),
            "account_id": str(case["zernio_account_id"]),
            "locale": str(quote["locale"] if quote else "en").lower(),
        }
    finally:
        conn.close()


def record_requirement_delivery(
    public_id: str,
    requirement: str,
    delivered: bool,
    actor: str,
) -> None:
    """Append safe provider-delivery evidence without storing customer URLs."""
    if requirement not in {"documents", "contract", "payment"}:
        raise reservation.AliReservationError("invalid_requirement_delivery", 422)
    actor_id = reservation._validate_actor(actor)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        case = _case(conn, public_id)
        reservation._event(
            conn,
            public_id,
            f"{requirement}_customer_delivery_{'accepted' if delivered else 'failed'}",
            str(case["status"]),
            str(case["status"]),
            "system",
            actor_id,
            {"provider_confirmed": bool(delivered)},
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _available_case(conn: sqlite3.Connection, public_id: str) -> sqlite3.Row:
    row = _case(conn, public_id)
    if row["availability_status"] != "approved" or row["status"] in {
        "declined", "cancelled", "superseded",
    }:
        raise reservation.AliReservationError("availability_approval_required", 409)
    return row


def _safe_document(row: sqlite3.Row | dict) -> dict:
    value = dict(row)
    return {key: value.get(key) for key in (
        "public_id", "slot", "version", "mime_type", "size_bytes", "sha256",
        "status", "previous_document_public_id", "created_at", "updated_at",
        "verified_at", "verified_by", "deleted_at", "deleted_by",
    )}


def _safe_contract(row: sqlite3.Row | dict | None) -> dict | None:
    if row is None:
        return None
    value = dict(row)
    return {key: value.get(key) for key in (
        "public_id", "version", "template_version", "template_sha256",
        "snapshot_sha256", "status", "signed_pdf_sha256", "sent_at",
        "viewed_at", "signed_at", "created_at", "updated_at",
    )}


def _write_private(data: bytes, extension: str, reservation_public_id: str) -> str:
    root = _private_root()
    directory = root / TENANT_SLUG / reservation_public_id
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    name = f"{uuid.uuid4().hex}{extension}"
    target = (directory / name).resolve()
    if directory not in target.parents:
        raise reservation.AliReservationError("invalid_private_storage_path", 500)
    fd, temporary = tempfile.mkstemp(prefix="upload-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return f"{reservation_public_id}/{name}"


def _stored_path(storage_name: str) -> Path:
    if not storage_name or ".." in storage_name or storage_name.startswith("/"):
        raise reservation.AliReservationError("invalid_private_storage_path", 500)
    root = (_private_root() / TENANT_SLUG).resolve()
    target = (root / storage_name).resolve()
    if root not in target.parents:
        raise reservation.AliReservationError("invalid_private_storage_path", 500)
    return target


def _token_signature(nonce: str) -> str:
    digest = hmac.new(
        _token_secret().encode("utf-8"), nonce.encode("ascii"), hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _new_token(
    conn: sqlite3.Connection,
    reservation_public_id: str,
    purpose: str,
    *,
    slot: str = "",
    target_public_id: str = "",
) -> tuple[str, str]:
    if purpose not in TOKEN_PURPOSES:
        raise reservation.AliReservationError("invalid_token_purpose", 422)
    settings = _require_ready()
    ttl = settings.get("link_ttl_seconds", 1800)
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not 300 <= ttl <= 86400:
        raise reservation.AliReservationError("invalid_link_ttl", 409)
    nonce = secrets.token_urlsafe(32)
    token = f"{nonce}.{_token_signature(nonce)}"
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    expires_at = _iso(_now() + timedelta(seconds=ttl))
    conn.execute(
        "UPDATE ali_reservation_tokens SET used_at = COALESCE(used_at, ?) "
        "WHERE tenant_slug = ? AND reservation_public_id = ? AND purpose = ? "
        "AND slot = ? AND used_at IS NULL",
        (_iso(), TENANT_SLUG, reservation_public_id, purpose, slot),
    )
    conn.execute(
        "INSERT INTO ali_reservation_tokens (token_hash, tenant_slug, "
        "reservation_public_id, purpose, slot, target_public_id, expires_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            token_hash, TENANT_SLUG, reservation_public_id, purpose, slot,
            target_public_id, expires_at, _iso(),
        ),
    )
    return token, expires_at


def _verify_token(
    token: str,
    purpose: str,
    *,
    allow_used: bool = False,
) -> tuple[sqlite3.Connection, sqlite3.Row]:
    parts = str(token or "").split(".")
    if len(parts) != 2 or not parts[0] or not hmac.compare_digest(
        parts[1], _token_signature(parts[0]),
    ):
        raise reservation.AliReservationError("invalid_or_expired_token", 404)
    ensure_schema()
    conn = _connection()
    row = conn.execute(
        "SELECT * FROM ali_reservation_tokens WHERE token_hash = ? "
        "AND tenant_slug = ? AND purpose = ?",
        (hashlib.sha256(token.encode("ascii")).hexdigest(), TENANT_SLUG, purpose),
    ).fetchone()
    if not row or (row["used_at"] and not allow_used):
        conn.close()
        raise reservation.AliReservationError("invalid_or_expired_token", 404)
    try:
        expires = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
    except ValueError:
        conn.close()
        raise reservation.AliReservationError("invalid_or_expired_token", 404)
    if expires <= _now():
        conn.close()
        raise reservation.AliReservationError("invalid_or_expired_token", 404)
    _available_case(conn, str(row["reservation_public_id"]))
    return conn, row


def issue_document_links(
    public_id: str,
    actor: str,
    expected_revision: int | None = None,
) -> dict:
    actor_id = reservation._validate_actor(actor)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _available_case(conn, public_id)
        reservation._check_revision(row, expected_revision)
        links = []
        for slot in DOCUMENT_SLOTS:
            token, expires = _new_token(conn, public_id, "document_upload", slot=slot)
            links.append({
                "slot": slot,
                "url": f"{_public_base_url()}/dashboard/api/ali-reservations/public/documents/{token}",
                "expiresAt": expires,
            })
        timestamp = _iso()
        conn.execute(
            "UPDATE ali_reservations SET identity_status = 'requested', "
            "status = 'requirements_pending', last_staff_actor = ?, "
            "last_staff_action_at = ?, revision = revision + 1, updated_at = ? "
            "WHERE tenant_slug = ? AND public_id = ?",
            (actor_id, timestamp, timestamp, TENANT_SLUG, public_id),
        )
        reservation._event(
            conn, public_id, "document_intake_requested", str(row["status"]),
            "requirements_pending", "staff", actor_id,
            {"slots": list(DOCUMENT_SLOTS), "link_count": len(links)},
        )
        conn.commit()
        return {"reservationPublicId": public_id, "links": links}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def document_upload_context(token: str) -> dict:
    conn, row = _verify_token(token, "document_upload")
    try:
        return {
            "slot": row["slot"],
            "accept": list(DOCUMENT_MIMES),
            "maxBytes": MAX_UPLOAD_BYTES,
            "expiresAt": row["expires_at"],
        }
    finally:
        conn.close()


def _validated_upload(payload: bytes, claimed_mime: str) -> tuple[str, str]:
    if not payload or len(payload) > MAX_UPLOAD_BYTES:
        raise reservation.AliReservationError("invalid_document_size", 422)
    mime = str(claimed_mime or "").split(";", 1)[0].strip().lower()
    actual = ""
    if payload.startswith(b"%PDF-"):
        actual = "application/pdf"
    elif payload.startswith(b"\x89PNG\r\n\x1a\n"):
        actual = "image/png"
    elif payload.startswith(b"\xff\xd8\xff"):
        actual = "image/jpeg"
    if actual not in DOCUMENT_MIMES or mime != actual:
        raise reservation.AliReservationError("document_content_type_mismatch", 422)
    if actual == "application/pdf":
        if any(marker in payload for marker in _ACTIVE_PDF_MARKERS):
            raise reservation.AliReservationError("active_pdf_rejected", 422)
        try:
            reader = PdfReader(io.BytesIO(payload), strict=True)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
                raise reservation.AliReservationError("invalid_pdf_document", 422)
            for page in reader.pages:
                _ = page.mediabox
        except reservation.AliReservationError:
            raise
        except Exception as exc:
            raise reservation.AliReservationError("invalid_pdf_document", 422) from exc
    else:
        try:
            with Image.open(io.BytesIO(payload)) as image:
                width, height = image.size
                if width < 16 or height < 16 or width * height > MAX_IMAGE_PIXELS:
                    raise reservation.AliReservationError("invalid_image_dimensions", 422)
                image.verify()
        except reservation.AliReservationError:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise reservation.AliReservationError("invalid_image_document", 422) from exc
    return actual, DOCUMENT_MIMES[actual]


def _document_rollup(conn: sqlite3.Connection, public_id: str) -> str:
    statuses = {}
    for row in conn.execute(
        "SELECT slot, status FROM ali_reservation_documents WHERE tenant_slug = ? "
        "AND reservation_public_id = ? ORDER BY version",
        (TENANT_SLUG, public_id),
    ).fetchall():
        statuses[str(row["slot"])] = str(row["status"])
    values = [statuses.get(slot) for slot in DOCUMENT_SLOTS]
    if all(value in {"verified", "not_required"} for value in values):
        return "verified"
    if any(value == "replacement_requested" for value in values):
        return "replacement_requested"
    if any(value == "rejected" for value in values):
        return "rejected"
    received = sum(value in {"received", "verified", "not_required"} for value in values)
    if received == len(DOCUMENT_SLOTS):
        return "received"
    if received:
        return "partially_received"
    return "requested"


def _refresh_case(conn: sqlite3.Connection, public_id: str, actor: str) -> sqlite3.Row:
    row = _case(conn, public_id)
    complete = reservation._requirements_complete(
        row["identity_status"], row["agreement_status"], row["payment_status"],
    )
    status = (
        "ready_to_confirm"
        if row["availability_status"] == "approved" and complete
        else "requirements_pending"
    )
    timestamp = _iso()
    conn.execute(
        "UPDATE ali_reservations SET status = ?, last_staff_actor = ?, "
        "last_staff_action_at = ?, revision = revision + 1, updated_at = ? "
        "WHERE tenant_slug = ? AND public_id = ?",
        (status, actor, timestamp, timestamp, TENANT_SLUG, public_id),
    )
    return _case(conn, public_id)


def store_document_upload(token: str, payload: bytes, claimed_mime: str) -> dict:
    conn, token_row = _verify_token(token, "document_upload", allow_used=True)
    try:
        if token_row["used_at"]:
            existing = conn.execute(
                "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? "
                "AND reservation_public_id = ? AND public_id = ?",
                (
                    TENANT_SLUG,
                    token_row["reservation_public_id"],
                    token_row["result_public_id"],
                ),
            ).fetchone()
            if not existing:
                raise reservation.AliReservationError("invalid_or_expired_token", 404)
            digest = hashlib.sha256(payload).hexdigest()
            if existing["sha256"] != digest:
                raise reservation.AliReservationError("upload_replay_mismatch", 409)
            return _safe_document(existing)
        mime, extension = _validated_upload(payload, claimed_mime)
        digest = hashlib.sha256(payload).hexdigest()
        conn.execute("BEGIN IMMEDIATE")
        public_id = str(token_row["reservation_public_id"])
        slot = str(token_row["slot"])
        current = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? "
            "AND reservation_public_id = ? AND slot = ? "
            "ORDER BY version DESC LIMIT 1",
            (TENANT_SLUG, public_id, slot),
        ).fetchone()
        if current and current["sha256"] == digest and current["status"] not in {"deleted", "replaced"}:
            conn.execute(
                "UPDATE ali_reservation_tokens SET used_at = ?, result_public_id = ? "
                "WHERE token_hash = ?",
                (_iso(), current["public_id"], token_row["token_hash"]),
            )
            conn.commit()
            return _safe_document(current)
        storage_name = _write_private(payload, extension, public_id)
        version = int(current["version"]) + 1 if current else 1
        document_id = str(uuid.uuid4())
        timestamp = _iso()
        if current and current["status"] not in {"deleted", "replaced"}:
            conn.execute(
                "UPDATE ali_reservation_documents SET status = 'replaced', updated_at = ? "
                "WHERE public_id = ? AND tenant_slug = ?",
                (timestamp, current["public_id"], TENANT_SLUG),
            )
        conn.execute(
            "INSERT INTO ali_reservation_documents (public_id, tenant_slug, "
            "reservation_public_id, slot, version, mime_type, size_bytes, sha256, "
            "storage_name, status, previous_document_public_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'received', ?, ?, ?)",
            (
                document_id, TENANT_SLUG, public_id, slot, version, mime,
                len(payload), digest, storage_name,
                str(current["public_id"]) if current else None, timestamp, timestamp,
            ),
        )
        rollup = _document_rollup(conn, public_id)
        row = _case(conn, public_id)
        conn.execute(
            "UPDATE ali_reservations SET identity_status = ?, status = 'requirements_pending', "
            "revision = revision + 1, updated_at = ? WHERE tenant_slug = ? AND public_id = ?",
            (rollup, timestamp, TENANT_SLUG, public_id),
        )
        conn.execute(
            "UPDATE ali_reservation_tokens SET used_at = ?, result_public_id = ? "
            "WHERE token_hash = ?",
            (timestamp, document_id, token_row["token_hash"]),
        )
        reservation._event(
            conn, public_id, "document_received", str(row["status"]),
            "requirements_pending", "customer", "signed_upload_link",
            {"slot": slot, "version": version, "mime_type": mime, "size_bytes": len(payload), "digest_prefix": digest[:12]},
        )
        result = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE public_id = ?", (document_id,),
        ).fetchone()
        conn.commit()
        return _safe_document(result)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_documents(public_id: str) -> list[dict]:
    ensure_schema()
    conn = _connection()
    try:
        _case(conn, public_id)
        rows = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? "
            "AND reservation_public_id = ? ORDER BY slot, version DESC",
            (TENANT_SLUG, public_id),
        ).fetchall()
        return [_safe_document(row) for row in rows]
    finally:
        conn.close()


def review_document(
    public_id: str,
    document_id: str,
    decision: str,
    actor: str,
    expected_revision: int | None = None,
) -> dict:
    if decision not in {"verified", "rejected", "replacement_requested", "not_required"}:
        raise reservation.AliReservationError("invalid_document_decision", 422)
    actor_id = reservation._validate_actor(actor)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        case = _available_case(conn, public_id)
        reservation._check_revision(case, expected_revision)
        row = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? "
            "AND reservation_public_id = ? AND public_id = ?",
            (TENANT_SLUG, public_id, document_id),
        ).fetchone()
        if not row or row["status"] in {"deleted", "replaced"}:
            raise reservation.AliReservationError("document_not_found", 404)
        if decision == "not_required" and row["slot"] != "license_back":
            raise reservation.AliReservationError("document_slot_required", 409)
        if row["status"] == decision:
            conn.commit()
            return _safe_document(row)
        timestamp = _iso()
        conn.execute(
            "UPDATE ali_reservation_documents SET status = ?, updated_at = ?, "
            "verified_at = ?, verified_by = ? WHERE public_id = ? AND tenant_slug = ?",
            (
                decision, timestamp,
                timestamp if decision in {"verified", "not_required"} else None,
                actor_id if decision in {"verified", "not_required"} else None,
                document_id, TENANT_SLUG,
            ),
        )
        rollup = _document_rollup(conn, public_id)
        conn.execute(
            "UPDATE ali_reservations SET identity_status = ? WHERE tenant_slug = ? AND public_id = ?",
            (rollup, TENANT_SLUG, public_id),
        )
        updated_case = _refresh_case(conn, public_id, actor_id)
        reservation._event(
            conn, public_id, "document_reviewed", str(case["status"]),
            str(updated_case["status"]), "staff", actor_id,
            {"document_id": document_id, "slot": row["slot"], "decision": decision},
        )
        updated = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE public_id = ?", (document_id,),
        ).fetchone()
        conn.commit()
        return _safe_document(updated)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_document_slot_not_required(
    public_id: str,
    slot: str,
    actor: str,
    expected_revision: int | None = None,
) -> dict:
    """Mark only the optional licence-back slot as not required."""
    if slot != "license_back":
        raise reservation.AliReservationError("document_slot_required", 409)
    actor_id = reservation._validate_actor(actor)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        case = _available_case(conn, public_id)
        reservation._check_revision(case, expected_revision)
        current = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? "
            "AND reservation_public_id = ? AND slot = ? "
            "ORDER BY version DESC LIMIT 1",
            (TENANT_SLUG, public_id, slot),
        ).fetchone()
        if current and current["status"] == "not_required":
            conn.commit()
            return _safe_document(current)
        timestamp = _iso()
        version = int(current["version"]) + 1 if current else 1
        document_id = str(uuid.uuid4())
        if current and current["status"] not in {"deleted", "replaced"}:
            conn.execute(
                "UPDATE ali_reservation_documents SET status = 'replaced', "
                "updated_at = ? WHERE public_id = ? AND tenant_slug = ?",
                (timestamp, current["public_id"], TENANT_SLUG),
            )
        conn.execute(
            "INSERT INTO ali_reservation_documents (public_id, tenant_slug, "
            "reservation_public_id, slot, version, size_bytes, status, "
            "previous_document_public_id, created_at, updated_at, verified_at, "
            "verified_by) VALUES (?, ?, ?, ?, ?, 0, 'not_required', ?, ?, ?, ?, ?)",
            (
                document_id,
                TENANT_SLUG,
                public_id,
                slot,
                version,
                str(current["public_id"]) if current else None,
                timestamp,
                timestamp,
                timestamp,
                actor_id,
            ),
        )
        rollup = _document_rollup(conn, public_id)
        conn.execute(
            "UPDATE ali_reservations SET identity_status = ? WHERE tenant_slug = ? "
            "AND public_id = ?",
            (rollup, TENANT_SLUG, public_id),
        )
        updated_case = _refresh_case(conn, public_id, actor_id)
        reservation._event(
            conn,
            public_id,
            "document_slot_not_required",
            str(case["status"]),
            str(updated_case["status"]),
            "staff",
            actor_id,
            {"slot": slot, "version": version},
        )
        result = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE public_id = ?",
            (document_id,),
        ).fetchone()
        conn.commit()
        return _safe_document(result)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_document(
    public_id: str,
    document_id: str,
    actor: str,
    expected_revision: int | None = None,
) -> dict:
    actor_id = reservation._validate_actor(actor)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        case = _case(conn, public_id)
        reservation._check_revision(case, expected_revision)
        row = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? "
            "AND reservation_public_id = ? AND public_id = ?",
            (TENANT_SLUG, public_id, document_id),
        ).fetchone()
        if not row:
            raise reservation.AliReservationError("document_not_found", 404)
        if row["status"] == "deleted":
            conn.commit()
            return _safe_document(row)
        path = _stored_path(str(row["storage_name"] or ""))
        if path.is_file():
            path.unlink()
        timestamp = _iso()
        conn.execute(
            "UPDATE ali_reservation_documents SET status = 'deleted', storage_name = NULL, "
            "deleted_at = ?, deleted_by = ?, updated_at = ? WHERE public_id = ? AND tenant_slug = ?",
            (timestamp, actor_id, timestamp, document_id, TENANT_SLUG),
        )
        rollup = _document_rollup(conn, public_id)
        conn.execute(
            "UPDATE ali_reservations SET identity_status = ? WHERE tenant_slug = ? AND public_id = ?",
            (rollup, TENANT_SLUG, public_id),
        )
        updated_case = _refresh_case(conn, public_id, actor_id)
        reservation._event(
            conn, public_id, "document_deleted", str(case["status"]),
            str(updated_case["status"]), "staff", actor_id,
            {"document_id": document_id, "slot": row["slot"], "version": row["version"]},
        )
        updated = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE public_id = ?", (document_id,),
        ).fetchone()
        conn.commit()
        return _safe_document(updated)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def document_bytes(public_id: str, document_id: str) -> tuple[bytes, str]:
    ensure_schema()
    conn = _connection()
    try:
        _case(conn, public_id)
        row = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? "
            "AND reservation_public_id = ? AND public_id = ? AND status NOT IN ('deleted','replaced')",
            (TENANT_SLUG, public_id, document_id),
        ).fetchone()
        if not row:
            raise reservation.AliReservationError("document_not_found", 404)
        path = _stored_path(str(row["storage_name"] or ""))
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise reservation.AliReservationError("document_integrity_failed", 500)
        return data, str(row["mime_type"])
    finally:
        conn.close()


def _quote_snapshot(conn: sqlite3.Connection, case: sqlite3.Row) -> dict:
    quote = conn.execute(
        "SELECT * FROM ali_quotes WHERE public_id = ? AND quote_snapshot_id = ?",
        (case["quote_public_id"], case["quote_snapshot_id"]),
    ).fetchone()
    if not quote:
        raise reservation.AliReservationError("quote_snapshot_not_found", 409)
    try:
        customer = json.loads(quote["customer_json"] or "{}")
        rental = json.loads(quote["rental_json"] or "{}")
        pricing = json.loads(quote["pricing_json"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise reservation.AliReservationError("quote_snapshot_invalid", 500) from exc
    return {"quote": dict(quote), "customer": customer, "rental": rental, "pricing": pricing}


def _template_values(case: sqlite3.Row, snapshot: dict) -> dict[str, str]:
    rental = snapshot["rental"]
    pricing = snapshot["pricing"]
    selection = rental.get("vehicle_name") or rental.get("vehicle_class_name") or ""
    return {
        "reservation_reference": str(case["public_id"]),
        "quote_reference": str(case["quote_reference"]),
        "customer_name": str(snapshot["customer"].get("name") or ""),
        "rental_start": str(rental.get("rental_start") or ""),
        "rental_end": str(rental.get("rental_end") or ""),
        "pickup_location": str(rental.get("pickup_location") or ""),
        "return_location": str(rental.get("return_location") or ""),
        "vehicle": str(selection),
        "rental_total": str((pricing.get("rentalTotal") or {}).get("amount") or ""),
        "refundable_deposit": str((pricing.get("refundableSecurityDeposit") or {}).get("amount") or ""),
        "grand_total": str((pricing.get("total") or {}).get("amount") or ""),
    }


def _contract_text(template: str, values: dict[str, str]) -> str:
    fields = set(re.findall(r"\{([a-z_]+)\}", template))
    if fields - set(values):
        raise reservation.AliReservationError("contract_template_placeholder_invalid", 409)
    result = template
    for key, value in values.items():
        result = result.replace("{" + key + "}", value)
    return result


def _text_pdf(title: str, paragraphs: list[str], *, signature: bytes | None = None) -> bytes:
    output = io.BytesIO()
    page = canvas.Canvas(output, pagesize=A4)
    width, height = A4
    y = height - 55
    page.setTitle(title)
    page.setFont("Helvetica-Bold", 18)
    page.drawString(50, y, title)
    y -= 34
    page.setFont("Helvetica", 10)
    for paragraph in paragraphs:
        lines = wrap(str(paragraph), 102) or [""]
        for line in lines:
            if y < 70:
                page.showPage(); y = height - 55; page.setFont("Helvetica", 10)
            page.drawString(50, y, line)
            y -= 14
        y -= 8
    if signature:
        try:
            if y < 150:
                page.showPage(); y = height - 55
            page.setFont("Helvetica-Bold", 10)
            page.drawString(50, y, "Customer signature")
            y -= 90
            page.drawImage(ImageReader(io.BytesIO(signature)), 50, y, width=220, height=75, preserveAspectRatio=True, mask="auto")
        except Exception as exc:
            raise reservation.AliReservationError("invalid_signature_image", 422) from exc
    page.save()
    return output.getvalue()


def issue_contract_link(
    public_id: str,
    actor: str,
    expected_revision: int | None = None,
) -> dict:
    actor_id = reservation._validate_actor(actor)
    settings = _require_ready()
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        case = _available_case(conn, public_id)
        reservation._check_revision(case, expected_revision)
        current = conn.execute(
            "SELECT * FROM ali_reservation_contracts WHERE tenant_slug = ? "
            "AND reservation_public_id = ? ORDER BY version DESC LIMIT 1",
            (TENANT_SLUG, public_id),
        ).fetchone()
        if current and current["status"] == "signed":
            raise reservation.AliReservationError("signed_contract_is_immutable", 409)
        template_path = Path(str(settings["contract_template_path"])).resolve()
        template_bytes = template_path.read_bytes()
        try:
            template = template_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise reservation.AliReservationError("contract_template_invalid", 409) from exc
        snapshot = _quote_snapshot(conn, case)
        contract_text = _contract_text(template, _template_values(case, snapshot))
        snapshot_hash = hashlib.sha256(
            json.dumps(
                {"quote_snapshot_id": case["quote_snapshot_id"], "text": contract_text},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if current and current["snapshot_sha256"] == snapshot_hash:
            contract_id = str(current["public_id"])
            version = int(current["version"])
        else:
            if current:
                conn.execute(
                    "UPDATE ali_reservation_contracts SET status = 'superseded', updated_at = ? "
                    "WHERE public_id = ?",
                    (_iso(), current["public_id"]),
                )
            contract_id = str(uuid.uuid4())
            version = int(current["version"]) + 1 if current else 1
            unsigned = _text_pdf(
                "Ali Car Rental pre-contract",
                [contract_text, f"Contract version: {settings['contract_template_version']}", f"Snapshot hash: {snapshot_hash}"],
            )
            storage = _write_private(unsigned, ".pdf", public_id)
            timestamp = _iso()
            conn.execute(
                "INSERT INTO ali_reservation_contracts (public_id, tenant_slug, "
                "reservation_public_id, version, template_version, template_sha256, "
                "snapshot_sha256, status, unsigned_storage_name, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'not_sent', ?, ?, ?)",
                (
                    contract_id, TENANT_SLUG, public_id, version,
                    str(settings["contract_template_version"]),
                    hashlib.sha256(template_bytes).hexdigest(), snapshot_hash,
                    storage, timestamp, timestamp,
                ),
            )
        token, expires = _new_token(
            conn, public_id, "contract_sign", target_public_id=contract_id,
        )
        timestamp = _iso()
        conn.execute(
            "UPDATE ali_reservation_contracts SET status = 'not_sent', "
            "updated_at = ? WHERE public_id = ?",
            (timestamp, contract_id),
        )
        conn.execute(
            "UPDATE ali_reservations SET agreement_status = 'not_sent', "
            "status = 'requirements_pending', last_staff_actor = ?, last_staff_action_at = ?, "
            "revision = revision + 1, updated_at = ? WHERE tenant_slug = ? AND public_id = ?",
            (actor_id, timestamp, timestamp, TENANT_SLUG, public_id),
        )
        reservation._event(
            conn, public_id, "contract_link_issued", str(case["status"]),
            "requirements_pending", "staff", actor_id,
            {"contract_id": contract_id, "version": version, "template_version": str(settings["contract_template_version"])},
        )
        conn.commit()
        return {
            "contract": _safe_contract(conn.execute("SELECT * FROM ali_reservation_contracts WHERE public_id = ?", (contract_id,)).fetchone()),
            "url": f"{_public_base_url()}/dashboard/api/ali-reservations/public/contracts/{token}",
            "expiresAt": expires,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_contract_link_sent(public_id: str, contract_id: str, actor: str) -> dict:
    actor_id = reservation._validate_actor(actor)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        case = _available_case(conn, public_id)
        contract = conn.execute(
            "SELECT * FROM ali_reservation_contracts WHERE tenant_slug = ? "
            "AND reservation_public_id = ? AND public_id = ?",
            (TENANT_SLUG, public_id, contract_id),
        ).fetchone()
        if not contract or contract["status"] not in {"not_sent", "sent", "viewed"}:
            raise reservation.AliReservationError("contract_not_found", 404)
        if contract["status"] in {"sent", "viewed"}:
            conn.commit()
            return _safe_contract(contract)
        timestamp = _iso()
        conn.execute(
            "UPDATE ali_reservation_contracts SET status = 'sent', sent_at = ?, "
            "updated_at = ? WHERE tenant_slug = ? AND public_id = ?",
            (timestamp, timestamp, TENANT_SLUG, contract_id),
        )
        conn.execute(
            "UPDATE ali_reservations SET agreement_status = 'sent', revision = revision + 1, "
            "updated_at = ? WHERE tenant_slug = ? AND public_id = ?",
            (timestamp, TENANT_SLUG, public_id),
        )
        result = conn.execute(
            "SELECT * FROM ali_reservation_contracts WHERE public_id = ?",
            (contract_id,),
        ).fetchone()
        conn.commit()
        return _safe_contract(result)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def contract_review_context(token: str, *, mark_viewed: bool = True) -> dict:
    conn, token_row = _verify_token(token, "contract_sign")
    try:
        conn.execute("BEGIN IMMEDIATE")
        contract = conn.execute(
            "SELECT * FROM ali_reservation_contracts WHERE tenant_slug = ? "
            "AND reservation_public_id = ? AND public_id = ?",
            (TENANT_SLUG, token_row["reservation_public_id"], token_row["target_public_id"]),
        ).fetchone()
        if not contract or contract["status"] in {"signed", "rejected", "superseded"}:
            raise reservation.AliReservationError("contract_not_signable", 409)
        if mark_viewed and contract["status"] != "viewed":
            timestamp = _iso()
            conn.execute(
                "UPDATE ali_reservation_contracts SET status = 'viewed', viewed_at = ?, updated_at = ? WHERE public_id = ?",
                (timestamp, timestamp, contract["public_id"]),
            )
            conn.execute(
                "UPDATE ali_reservations SET agreement_status = 'viewed', revision = revision + 1, updated_at = ? "
                "WHERE tenant_slug = ? AND public_id = ?",
                (timestamp, TENANT_SLUG, token_row["reservation_public_id"]),
            )
            reservation._event(
                conn, token_row["reservation_public_id"], "contract_viewed",
                "requirements_pending", "requirements_pending", "customer",
                "signed_contract_link", {"contract_id": contract["public_id"], "version": contract["version"]},
            )
            contract = conn.execute(
                "SELECT * FROM ali_reservation_contracts WHERE public_id = ?", (contract["public_id"],),
            ).fetchone()
        unsigned = _stored_path(str(contract["unsigned_storage_name"])).read_bytes()
        conn.commit()
        return {
            "contract": _safe_contract(contract),
            "pdfBase64": base64.b64encode(unsigned).decode("ascii"),
            "consentRequired": True,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _signature_png(value: str) -> bytes:
    raw = str(value or "")
    prefix = "data:image/png;base64,"
    if not raw.startswith(prefix):
        raise reservation.AliReservationError("invalid_signature_image", 422)
    try:
        data = base64.b64decode(raw[len(prefix):], validate=True)
    except Exception as exc:
        raise reservation.AliReservationError("invalid_signature_image", 422) from exc
    if len(data) > 1024 * 1024:
        raise reservation.AliReservationError("invalid_signature_image", 422)
    mime, _ = _validated_upload(data, "image/png")
    if mime != "image/png":
        raise reservation.AliReservationError("invalid_signature_image", 422)
    return data


def sign_contract(token: str, *, consent: bool, legal_name: str, signature_data: str) -> dict:
    name = str(legal_name or "").strip()
    if consent is not True or not name or len(name) > 120:
        raise reservation.AliReservationError("explicit_contract_consent_required", 422)
    signature = _signature_png(signature_data)
    conn, token_row = _verify_token(token, "contract_sign", allow_used=True)
    try:
        conn.execute("BEGIN IMMEDIATE")
        contract = conn.execute(
            "SELECT * FROM ali_reservation_contracts WHERE tenant_slug = ? AND public_id = ? "
            "AND reservation_public_id = ?",
            (TENANT_SLUG, token_row["target_public_id"], token_row["reservation_public_id"]),
        ).fetchone()
        if not contract:
            raise reservation.AliReservationError("contract_not_found", 404)
        if contract["status"] == "signed":
            conn.execute(
                "UPDATE ali_reservation_tokens SET used_at = COALESCE(used_at, ?), result_public_id = ? WHERE token_hash = ?",
                (_iso(), contract["public_id"], token_row["token_hash"]),
            )
            conn.commit()
            return _safe_contract(contract)
        if token_row["used_at"]:
            raise reservation.AliReservationError("invalid_or_expired_token", 404)
        if contract["status"] not in {"sent", "viewed"}:
            raise reservation.AliReservationError("contract_not_signable", 409)
        unsigned = _stored_path(str(contract["unsigned_storage_name"])).read_bytes()
        signed_at = _iso()
        signed_pdf = _text_pdf(
            "Ali Car Rental signed pre-contract",
            [
                f"Contract version: {contract['template_version']}",
                f"Contract snapshot hash: {contract['snapshot_sha256']}",
                f"Customer legal name: {name}",
                f"Signed at: {signed_at}",
                "The complete pre-contract reviewed by the customer is appended after this signature page.",
            ],
            signature=signature,
        )
        writer = PdfWriter()
        for source in (signed_pdf, unsigned):
            reader = PdfReader(io.BytesIO(source))
            for page in reader.pages:
                writer.add_page(page)
        output = io.BytesIO(); writer.write(output); signed_pdf = output.getvalue()
        storage = _write_private(signed_pdf, ".pdf", token_row["reservation_public_id"])
        digest = hashlib.sha256(signed_pdf).hexdigest()
        signature_digest = hashlib.sha256(signature).hexdigest()
        conn.execute(
            "UPDATE ali_reservation_contracts SET status = 'signed', signed_storage_name = ?, "
            "signed_pdf_sha256 = ?, legal_name = ?, signature_sha256 = ?, signed_at = ?, "
            "updated_at = ? WHERE public_id = ?",
            (storage, digest, name, signature_digest, signed_at, signed_at, contract["public_id"]),
        )
        conn.execute(
            "UPDATE ali_reservation_tokens SET used_at = ?, result_public_id = ? WHERE token_hash = ?",
            (signed_at, contract["public_id"], token_row["token_hash"]),
        )
        case = _case(conn, token_row["reservation_public_id"])
        conn.execute(
            "UPDATE ali_reservations SET agreement_status = 'signed' WHERE tenant_slug = ? AND public_id = ?",
            (TENANT_SLUG, token_row["reservation_public_id"]),
        )
        updated = _refresh_case(conn, token_row["reservation_public_id"], "customer_signature")
        reservation._event(
            conn, token_row["reservation_public_id"], "contract_signed",
            str(case["status"]), str(updated["status"]), "customer", "signed_contract_link",
            {"contract_id": contract["public_id"], "version": contract["version"], "signed_pdf_digest_prefix": digest[:12]},
        )
        result = conn.execute(
            "SELECT * FROM ali_reservation_contracts WHERE public_id = ?", (contract["public_id"],),
        ).fetchone()
        conn.commit()
        return _safe_contract(result)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def signed_contract_bytes(public_id: str) -> bytes:
    ensure_schema()
    conn = _connection()
    try:
        _case(conn, public_id)
        row = conn.execute(
            "SELECT * FROM ali_reservation_contracts WHERE tenant_slug = ? "
            "AND reservation_public_id = ? AND status = 'signed' ORDER BY version DESC LIMIT 1",
            (TENANT_SLUG, public_id),
        ).fetchone()
        if not row:
            raise reservation.AliReservationError("signed_contract_not_found", 404)
        data = _stored_path(str(row["signed_storage_name"])).read_bytes()
        if hashlib.sha256(data).hexdigest() != row["signed_pdf_sha256"]:
            raise reservation.AliReservationError("signed_contract_integrity_failed", 500)
        return data
    finally:
        conn.close()


def _allowed_payment_url(value: str) -> tuple[str, str]:
    settings = _require_ready()
    try:
        parsed = urllib.parse.urlsplit(str(value or "").strip())
    except ValueError as exc:
        raise reservation.AliReservationError("invalid_payment_url", 422) from exc
    host = str(parsed.hostname or "").lower().rstrip(".")
    allowed = {str(item).strip().lower().rstrip(".") for item in settings.get("payment_allowed_domains") or []}
    if (
        parsed.scheme != "https" or not host or parsed.username or parsed.password
        or parsed.port not in {None, 443} or host not in allowed
        or parsed.fragment
    ):
        raise reservation.AliReservationError("payment_url_not_allowed", 422)
    return urllib.parse.urlunsplit(parsed), host


def set_payment_link(
    public_id: str,
    url: str,
    reference: str,
    actor: str,
    expected_revision: int | None = None,
) -> dict:
    actor_id = reservation._validate_actor(actor)
    payment_url, domain = _allowed_payment_url(url)
    payment_reference = str(reference or "").strip()
    if len(payment_reference) > 120:
        raise reservation.AliReservationError("invalid_payment_reference", 422)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        case = _available_case(conn, public_id)
        reservation._check_revision(case, expected_revision)
        timestamp = _iso()
        conn.execute(
            "INSERT INTO ali_reservation_payments (reservation_public_id, tenant_slug, "
            "payment_url, payment_domain, payment_reference, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(reservation_public_id) DO UPDATE SET payment_url=excluded.payment_url, "
            "payment_domain=excluded.payment_domain, payment_reference=excluded.payment_reference, "
            "link_sent_at=NULL, customer_reported_at=NULL, verified_at=NULL, verified_by=NULL, updated_at=excluded.updated_at",
            (public_id, TENANT_SLUG, payment_url, domain, payment_reference, timestamp),
        )
        conn.execute(
            "UPDATE ali_reservations SET payment_status = 'not_sent', status = 'requirements_pending', "
            "last_staff_actor = ?, last_staff_action_at = ?, revision = revision + 1, updated_at = ? "
            "WHERE tenant_slug = ? AND public_id = ?",
            (actor_id, timestamp, timestamp, TENANT_SLUG, public_id),
        )
        reservation._event(
            conn, public_id, "payment_link_configured", str(case["status"]),
            "requirements_pending", "staff", actor_id,
            {"payment_domain": domain, "reference_present": bool(payment_reference)},
        )
        conn.commit()
        return {"paymentDomain": domain, "paymentReference": payment_reference, "status": "not_sent"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_payment_link_sent(public_id: str, actor: str) -> dict:
    actor_id = reservation._validate_actor(actor)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        case = _available_case(conn, public_id)
        payment = conn.execute(
            "SELECT * FROM ali_reservation_payments WHERE tenant_slug = ? AND reservation_public_id = ?",
            (TENANT_SLUG, public_id),
        ).fetchone()
        if not payment or not payment["payment_url"]:
            raise reservation.AliReservationError("payment_link_not_configured", 409)
        if case["payment_status"] == "link_sent":
            conn.commit()
            return {"url": payment["payment_url"], "status": "link_sent"}
        timestamp = _iso()
        conn.execute(
            "UPDATE ali_reservation_payments SET link_sent_at = ?, updated_at = ? WHERE reservation_public_id = ?",
            (timestamp, timestamp, public_id),
        )
        conn.execute(
            "UPDATE ali_reservations SET payment_status = 'link_sent', revision = revision + 1, updated_at = ? "
            "WHERE tenant_slug = ? AND public_id = ?",
            (timestamp, TENANT_SLUG, public_id),
        )
        reservation._event(
            conn, public_id, "payment_link_sent", str(case["status"]),
            "requirements_pending", "staff", actor_id,
            {"payment_domain": payment["payment_domain"]},
        )
        conn.commit()
        return {"url": payment["payment_url"], "status": "link_sent"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_customer_payment_report(conversation_id: str, account_id: str, action_id: str = "") -> dict:
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM ali_reservations WHERE tenant_slug = ? AND conversation_id = ? "
            "AND zernio_account_id = ? ORDER BY id DESC LIMIT 1",
            (TENANT_SLUG, conversation_id, account_id),
        ).fetchone()
        if not row or row["payment_status"] not in {"link_sent", "customer_reports_paid"}:
            raise reservation.AliReservationError("payment_report_not_expected", 409)
        if row["payment_status"] == "customer_reports_paid":
            conn.commit()
            return reservation._public_row(row)
        timestamp = _iso()
        conn.execute(
            "UPDATE ali_reservations SET payment_status = 'customer_reports_paid', revision = revision + 1, updated_at = ? "
            "WHERE tenant_slug = ? AND public_id = ?",
            (timestamp, TENANT_SLUG, row["public_id"]),
        )
        conn.execute(
            "UPDATE ali_reservation_payments SET customer_reported_at = ?, updated_at = ? WHERE reservation_public_id = ?",
            (timestamp, timestamp, row["public_id"]),
        )
        reservation._event(
            conn, row["public_id"], "customer_reports_payment", str(row["status"]),
            "requirements_pending", "customer", "whatsapp",
            {"action_id_hash": hashlib.sha256(str(action_id).encode()).hexdigest() if action_id else ""},
        )
        updated = _case(conn, row["public_id"])
        conn.commit()
        return reservation._public_row(updated)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def review_payment(
    public_id: str,
    decision: str,
    actor: str,
    expected_revision: int | None = None,
) -> dict:
    if decision not in {"verified", "rejected", "not_required"}:
        raise reservation.AliReservationError("invalid_payment_decision", 422)
    actor_id = reservation._validate_actor(actor)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        case = _available_case(conn, public_id)
        reservation._check_revision(case, expected_revision)
        if decision == "verified" and case["payment_status"] not in {"customer_reports_paid", "link_sent"}:
            raise reservation.AliReservationError("payment_verification_not_expected", 409)
        timestamp = _iso()
        conn.execute(
            "UPDATE ali_reservations SET payment_status = ? WHERE tenant_slug = ? AND public_id = ?",
            (decision, TENANT_SLUG, public_id),
        )
        conn.execute(
            "INSERT INTO ali_reservation_payments (reservation_public_id, tenant_slug, updated_at) "
            "VALUES (?, ?, ?) ON CONFLICT(reservation_public_id) DO UPDATE SET "
            "verified_at=excluded.updated_at, verified_by=?, updated_at=excluded.updated_at",
            (public_id, TENANT_SLUG, timestamp, actor_id),
        )
        updated = _refresh_case(conn, public_id, actor_id)
        reservation._event(
            conn, public_id, "payment_reviewed", str(case["status"]),
            str(updated["status"]), "staff", actor_id, {"decision": decision},
        )
        conn.commit()
        return reservation._public_row(updated)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_final_notes(
    public_id: str,
    notes: str,
    actor: str,
    expected_revision: int | None = None,
) -> dict:
    actor_id = reservation._validate_actor(actor)
    value = str(notes or "").strip()
    if len(value) > 2000:
        raise reservation.AliReservationError("invalid_final_notes", 422)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        case = _case(conn, public_id)
        reservation._check_revision(case, expected_revision)
        timestamp = _iso()
        conn.execute(
            "UPDATE ali_reservations SET final_notes = ?, last_staff_actor = ?, "
            "last_staff_action_at = ?, revision = revision + 1, updated_at = ? "
            "WHERE tenant_slug = ? AND public_id = ?",
            (value, actor_id, timestamp, timestamp, TENANT_SLUG, public_id),
        )
        reservation._event(
            conn, public_id, "final_notes_updated", str(case["status"]),
            str(case["status"]), "staff", actor_id, {"notes_present": bool(value)},
        )
        updated = _case(conn, public_id); conn.commit(); return reservation._public_row(updated)
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def get_customer_file(public_id: str) -> dict:
    ensure_schema()
    conn = _connection()
    try:
        case = _case(conn, public_id)
        snapshot = _quote_snapshot(conn, case)
        contract = conn.execute(
            "SELECT * FROM ali_reservation_contracts WHERE tenant_slug = ? "
            "AND reservation_public_id = ? ORDER BY version DESC LIMIT 1",
            (TENANT_SLUG, public_id),
        ).fetchone()
        payment = conn.execute(
            "SELECT * FROM ali_reservation_payments WHERE tenant_slug = ? AND reservation_public_id = ?",
            (TENANT_SLUG, public_id),
        ).fetchone()
        value = reservation._public_row(case)
        value["customer"] = snapshot["customer"]
        value["rental"] = snapshot["rental"]
        value["pricing"] = snapshot["pricing"]
        value["documents"] = list_documents(public_id)
        value["contract"] = _safe_contract(contract)
        value["payment"] = {
            "status": case["payment_status"],
            "url": payment["payment_url"] if payment else None,
            "domain": payment["payment_domain"] if payment else None,
            "reference": payment["payment_reference"] if payment else None,
            "linkSentAt": payment["link_sent_at"] if payment else None,
            "customerReportedAt": payment["customer_reported_at"] if payment else None,
            "verifiedAt": payment["verified_at"] if payment else None,
            "verifiedBy": payment["verified_by"] if payment else None,
        }
        value["events"] = reservation.list_reservation_events(public_id)
        value["final_notes"] = case["final_notes"]
        missing = []
        if case["identity_status"] not in {"verified", "not_required"}:
            missing.append("documents")
        if case["agreement_status"] not in {"signed", "verified", "not_required"}:
            missing.append("signed_contract")
        if case["payment_status"] not in {"verified", "not_required"}:
            missing.append("payment_verification")
        value["missing_requirements"] = missing
        value["can_confirm"] = (
            case["status"] == "ready_to_confirm"
            and case["availability_status"] == "approved"
            and not missing
        )
        return value
    finally:
        conn.close()


def _section_pdf(title: str, lines: list[str], page_size: tuple[float, float]) -> bytes:
    output = io.BytesIO(); page = canvas.Canvas(output, pagesize=page_size); width, height = page_size
    page.setFont("Helvetica-Bold", 18); page.drawString(46, height - 52, title)
    y = height - 82; page.setFont("Helvetica", 9)
    for value in lines:
        for line in wrap(str(value), 112) or [""]:
            if y < 48:
                page.showPage(); y = height - 52; page.setFont("Helvetica", 9)
            page.drawString(46, y, line); y -= 13
        y -= 3
    page.save(); return output.getvalue()


def _image_pdf(data: bytes, title: str, page_size: tuple[float, float]) -> bytes:
    output = io.BytesIO(); page = canvas.Canvas(output, pagesize=page_size); width, height = page_size
    page.setFont("Helvetica-Bold", 12); page.drawString(36, height - 36, title)
    with Image.open(io.BytesIO(data)) as image:
        image.thumbnail((int(width - 72), int(height - 100)))
        iw, ih = image.size; scale = min((width - 72) / iw, (height - 100) / ih)
        dw, dh = iw * scale, ih * scale
        page.drawImage(ImageReader(image.copy()), (width - dw) / 2, (height - dh) / 2 - 10, width=dw, height=dh, preserveAspectRatio=True)
    page.save(); return output.getvalue()


def _watermark_page(page, page_size: tuple[float, float]) -> None:
    overlay_bytes = io.BytesIO(); overlay = canvas.Canvas(overlay_bytes, pagesize=page_size)
    width, height = page_size; overlay.saveState(); overlay.setFillAlpha(0.16)
    overlay.setFont("Helvetica-Bold", 28); overlay.translate(width / 2, height / 2); overlay.rotate(35)
    overlay.drawCentredString(0, 0, "INCOMPLETE — NOT APPROVED"); overlay.restoreState(); overlay.save()
    overlay_page = PdfReader(io.BytesIO(overlay_bytes.getvalue())).pages[0]
    page.merge_page(overlay_page)


def generate_dossier(
    public_id: str,
    actor: str,
    *,
    allow_incomplete: bool = False,
    page_size: str = "A4",
    expected_revision: int | None = None,
) -> dict:
    actor_id = reservation._validate_actor(actor)
    if page_size not in {"A4", "LETTER"}:
        raise reservation.AliReservationError("invalid_dossier_page_size", 422)
    ensure_schema(); dimensions = A4 if page_size == "A4" else LETTER
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        case = _case(conn, public_id)
        reservation._check_revision(case, expected_revision)
        snapshot = _quote_snapshot(conn, case)
        dossier_status = (
            "approved" if case["status"] == "confirmed"
            else "ready_for_review"
            if case["availability_status"] == "approved" and reservation._requirements_complete(
                case["identity_status"], case["agreement_status"], case["payment_status"],
            )
            else "incomplete"
        )
        if dossier_status == "incomplete" and not allow_incomplete:
            raise reservation.AliReservationError("explicit_incomplete_print_required", 409)
        payment = conn.execute(
            "SELECT * FROM ali_reservation_payments WHERE tenant_slug = ? AND reservation_public_id = ?",
            (TENANT_SLUG, public_id),
        ).fetchone()
        contract = conn.execute(
            "SELECT * FROM ali_reservation_contracts WHERE tenant_slug = ? AND reservation_public_id = ? "
            "AND status = 'signed' ORDER BY version DESC LIMIT 1",
            (TENANT_SLUG, public_id),
        ).fetchone()
        documents = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? AND reservation_public_id = ? "
            "AND status NOT IN ('deleted','replaced') ORDER BY slot, version DESC",
            (TENANT_SLUG, public_id),
        ).fetchall()
        writer = PdfWriter()
        rental = snapshot["rental"]; pricing = snapshot["pricing"]; customer = snapshot["customer"]
        lines = [
            f"Status: {dossier_status.upper().replace('_', ' ')}",
            f"Reservation: {case['confirmation_reference'] or case['public_id']}",
            f"Quote: {case['quote_reference']}", f"Generated: {_iso()}",
            f"Customer: {customer.get('name','')}", f"WhatsApp: {customer.get('whatsapp','')}",
            f"Rental period: {rental.get('rental_start','')} to {rental.get('rental_end','')}",
            f"Pickup: {rental.get('pickup_location','')}", f"Return: {rental.get('return_location','')}",
            f"Vehicle: {rental.get('vehicle_name') or rental.get('vehicle_class_name') or ''}",
            f"Rental total: USD {(pricing.get('rentalTotal') or {}).get('amount','')}",
            f"Refundable security deposit: USD {(pricing.get('refundableSecurityDeposit') or {}).get('amount','')}",
            f"Total quote amount: USD {(pricing.get('total') or {}).get('amount','')}",
            f"Documents: {case['identity_status']}", f"Agreement: {case['agreement_status']}",
            f"Deposit: {case['payment_status']}",
            f"Payment reference: {payment['payment_reference'] if payment else ''}",
            f"Final notes: {case['final_notes']}", "Pickup checklist:",
            "[ ] Original licence inspected", "[ ] Original ID inspected",
        ]
        for data in (_section_pdf("Ali Car Rental — Customer dossier", lines, dimensions),):
            for page in PdfReader(io.BytesIO(data)).pages: writer.add_page(page)
        quote_path = str(snapshot["quote"].get("pdf_path") or "")
        if quote_path and Path(quote_path).is_file():
            for page in PdfReader(quote_path).pages: writer.add_page(page)
        if contract and contract["signed_storage_name"]:
            for page in PdfReader(str(_stored_path(contract["signed_storage_name"]))).pages: writer.add_page(page)
        for document in documents:
            if not document["storage_name"]:
                continue
            data = _stored_path(document["storage_name"]).read_bytes()
            source = (
                data if document["mime_type"] == "application/pdf"
                else _image_pdf(data, str(document["slot"]).replace("_", " ").title(), dimensions)
            )
            for page in PdfReader(io.BytesIO(source)).pages: writer.add_page(page)
        if dossier_status == "incomplete":
            for page in writer.pages: _watermark_page(page, dimensions)
        output = io.BytesIO(); writer.write(output); data = output.getvalue(); digest = hashlib.sha256(data).hexdigest()
        version_row = conn.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM ali_reservation_dossier_audits "
            "WHERE tenant_slug = ? AND reservation_public_id = ?",
            (TENANT_SLUG, public_id),
        ).fetchone(); version = int(version_row[0])
        created = _iso()
        conn.execute(
            "INSERT INTO ali_reservation_dossier_audits (reservation_public_id, tenant_slug, version, "
            "status, content_sha256, page_count, page_size, actor_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (public_id, TENANT_SLUG, version, dossier_status, digest, len(writer.pages), page_size, actor_id, created),
        )
        conn.execute(
            "UPDATE ali_reservations SET dossier_version = ?, revision = revision + 1, updated_at = ? "
            "WHERE tenant_slug = ? AND public_id = ?",
            (version, created, TENANT_SLUG, public_id),
        )
        reservation._event(
            conn, public_id, "dossier_generated", str(case["status"]), str(case["status"]),
            "staff", actor_id,
            {"version": version, "status": dossier_status, "content_hash_prefix": digest[:12], "page_count": len(writer.pages), "page_size": page_size},
        )
        conn.commit()
        return {
            "bytes": data, "sha256": digest, "version": version,
            "status": dossier_status, "pageCount": len(writer.pages),
            "filename": f"ALI-Dossier-{case['quote_reference']}-v{version}.pdf",
        }
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()
