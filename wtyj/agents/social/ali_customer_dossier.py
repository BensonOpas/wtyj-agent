"""Secure post-availability customer file for Ali reservations.

This module extends Brief 290's reservation/event model.  It deliberately
keeps binary identity material outside SQLite and outside the public web root;
only opaque identifiers and safe verification metadata are persisted.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import io
import json
import os
import re
import secrets
import sqlite3
import tempfile
import urllib.parse
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from textwrap import wrap
from xml.etree import ElementTree

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    CondPageBreak,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

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
    "replaced", "deleted", "not_required", "unclassified", "quarantined",
}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_TEMPLATE_BYTES = 2 * 1024 * 1024
MAX_PDF_PAGES = 20
MAX_IMAGE_PIXELS = 40_000_000
TOKEN_PURPOSES = {"document_upload", "contract_sign"}
COMPACT_TOKEN_BYTES = 24
PAYMENT_MODES = {"fixed_link", "per_reservation"}
DEFAULT_DOCUMENT_RETENTION_DAYS = 90
PAYMENT_WINDOW_HOURS = 24
DEFAULT_PAPER_SHREDDING_POLICY = (
    "Securely shred paper copies after the 90-day retention period."
)
CONTRACT_RENDER_VERSION = 2
CONTRACT_PLACEHOLDERS = {
    "reservation_reference",
    "quote_reference",
    "customer_name",
    "rental_start",
    "rental_end",
    "pickup_location",
    "return_location",
    "vehicle",
    "rental_total",
    "refundable_deposit",
    "grand_total",
}
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_CONTRACT_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,79}$")
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


def _runtime_config(raw: dict | None = None) -> dict:
    """Merge immutable file config with tenant-managed dashboard settings."""
    settings = dict(_config(raw))
    settings.setdefault("document_retention_days", DEFAULT_DOCUMENT_RETENTION_DAYS)
    settings.setdefault("paper_shredding_policy", DEFAULT_PAPER_SHREDDING_POLICY)
    settings.setdefault("payment_mode", "per_reservation")
    ensure_schema()
    conn = _connection()
    try:
        row = conn.execute(
            "SELECT * FROM ali_customer_dossier_settings WHERE tenant_slug = ?",
            (TENANT_SLUG,),
        ).fetchone()
        if not row:
            return settings
        try:
            domains = json.loads(row["payment_allowed_domains_json"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            domains = []
        settings.update({
            "payment_mode": str(row["payment_mode"] or "per_reservation"),
            "payment_provider_name": str(row["payment_provider_name"] or ""),
            "default_payment_url": str(row["default_payment_url"] or ""),
            "default_payment_domain": str(row["default_payment_domain"] or ""),
            "payment_allowed_domains": domains if isinstance(domains, list) else [],
            "document_retention_days": int(
                row["document_retention_days"] or DEFAULT_DOCUMENT_RETENTION_DAYS
            ),
            "paper_shredding_policy": str(
                row["paper_shredding_policy"] or DEFAULT_PAPER_SHREDDING_POLICY
            ),
        })
        template_id = str(row["active_contract_template_public_id"] or "")
        if template_id:
            template = conn.execute(
                "SELECT * FROM ali_contract_templates WHERE tenant_slug = ? "
                "AND public_id = ?",
                (TENANT_SLUG, template_id),
            ).fetchone()
            if template:
                root = (_private_root(settings) / TENANT_SLUG).resolve()
                target = (root / str(template["canonical_storage_name"])).resolve()
                if root in target.parents:
                    settings["contract_template_path"] = str(target)
                    settings["contract_template_version"] = str(
                        template["version_name"]
                    )
                    settings["contract_template_public_id"] = template_id
        return settings
    finally:
        conn.close()


def configuration_status(raw: dict | None = None) -> dict:
    """Return non-secret activation gates for staff diagnostics."""
    raw = raw if raw is not None else (config_loader.get_raw() or {})
    settings = _runtime_config(raw)
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
    if (
        settings.get("payment_mode") == "fixed_link"
        and not str(settings.get("default_payment_url") or "").strip()
    ):
        blockers.append("default_payment_link_missing")
    elif settings.get("payment_mode") == "fixed_link":
        try:
            _validated_payment_url(
                str(settings.get("default_payment_url") or ""),
                _normalize_payment_domains(domains),
            )
        except reservation.AliReservationError:
            blockers.append("default_payment_link_not_allowed")
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
        "configurationReady": not [
            blocker for blocker in blockers if blocker != "feature_disabled"
        ],
        "blockers": blockers,
    }


def _require_ready() -> dict:
    status = configuration_status()
    if not status["ready"]:
        raise reservation.AliReservationError("customer_dossier_not_configured", 409)
    return _runtime_config()


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
                expires_at TEXT,
                customer_reported_at TEXT,
                verified_at TEXT,
                verified_by TEXT,
                review_reason TEXT,
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
                storage_name TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY(reservation_public_id, version),
                FOREIGN KEY(reservation_public_id)
                    REFERENCES ali_reservations(public_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS ali_contract_templates (
                public_id TEXT PRIMARY KEY,
                tenant_slug TEXT NOT NULL,
                version_name TEXT NOT NULL,
                source_filename TEXT NOT NULL,
                source_mime TEXT NOT NULL,
                canonical_storage_name TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                UNIQUE(tenant_slug, version_name)
            );

            CREATE TABLE IF NOT EXISTS ali_customer_dossier_settings (
                tenant_slug TEXT PRIMARY KEY,
                active_contract_template_public_id TEXT,
                payment_mode TEXT NOT NULL DEFAULT 'per_reservation',
                payment_provider_name TEXT NOT NULL DEFAULT '',
                default_payment_url TEXT,
                default_payment_domain TEXT,
                payment_allowed_domains_json TEXT NOT NULL DEFAULT '[]',
                document_retention_days INTEGER NOT NULL DEFAULT 90,
                paper_shredding_policy TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                FOREIGN KEY(active_contract_template_public_id)
                    REFERENCES ali_contract_templates(public_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS ali_customer_dossier_settings_audit (
                public_id TEXT PRIMARY KEY,
                tenant_slug TEXT NOT NULL,
                action TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )
        dossier_columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(ali_reservation_dossier_audits)"
            ).fetchall()
        }
        if "storage_name" not in dossier_columns:
            conn.execute(
                "ALTER TABLE ali_reservation_dossier_audits ADD COLUMN storage_name TEXT"
            )
        document_columns = {
            str(item["name"])
            for item in conn.execute(
                "PRAGMA table_info(ali_reservation_documents)"
            ).fetchall()
        }
        for name, definition in {
            "provider_message_id_hash": "TEXT",
            "provider_attachment_id_hash": "TEXT",
            "original_filename": "TEXT",
            "quarantine_status": "TEXT NOT NULL DEFAULT 'legacy'",
            "classification_source": "TEXT NOT NULL DEFAULT 'legacy_upload_link'",
            "unclassified_expires_at": "TEXT",
            "review_reason": "TEXT",
        }.items():
            if name not in document_columns:
                conn.execute(
                    f"ALTER TABLE ali_reservation_documents ADD COLUMN {name} {definition}"
                )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_ali_documents_provider_attachment "
            "ON ali_reservation_documents(tenant_slug, provider_attachment_id_hash) "
            "WHERE provider_attachment_id_hash IS NOT NULL"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ali_documents_unclassified_expiry "
            "ON ali_reservation_documents(tenant_slug, status, unclassified_expires_at)"
        )
        payment_columns = {
            str(item["name"])
            for item in conn.execute(
                "PRAGMA table_info(ali_reservation_payments)"
            ).fetchall()
        }
        if "review_reason" not in payment_columns:
            conn.execute(
                "ALTER TABLE ali_reservation_payments ADD COLUMN review_reason TEXT"
            )
        if "expires_at" not in payment_columns:
            conn.execute(
                "ALTER TABLE ali_reservation_payments ADD COLUMN expires_at TEXT"
            )
            conn.execute(
                "UPDATE ali_reservation_payments SET expires_at = "
                "strftime('%Y-%m-%dT%H:%M:%fZ', link_sent_at, '+24 hours') "
                "WHERE link_sent_at IS NOT NULL AND expires_at IS NULL"
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
        "original_filename", "quarantine_status", "classification_source",
        "unclassified_expires_at", "review_reason",
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


def _normalize_payment_domains(values: object) -> list[str]:
    if not isinstance(values, list):
        raise reservation.AliReservationError("invalid_payment_domains", 422)
    domains: list[str] = []
    for value in values:
        candidate = str(value or "").strip().lower().rstrip(".")
        if not candidate:
            continue
        if (
            len(candidate) > 253
            or "://" in candidate
            or "/" in candidate
            or ":" in candidate
            or not re.fullmatch(
                r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
                r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
                candidate,
            )
        ):
            raise reservation.AliReservationError("invalid_payment_domain", 422)
        if candidate not in domains:
            domains.append(candidate)
    return domains


def _validated_payment_url(value: str, allowed_domains: list[str]) -> tuple[str, str]:
    try:
        parsed = urllib.parse.urlsplit(str(value or "").strip())
    except ValueError as exc:
        raise reservation.AliReservationError("invalid_payment_url", 422) from exc
    host = str(parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or host not in set(allowed_domains)
        or parsed.fragment
    ):
        raise reservation.AliReservationError("payment_url_not_allowed", 422)
    return urllib.parse.urlunsplit(parsed), host


def _contract_template_text(payload: bytes, filename: str, content_type: str) -> str:
    if not payload or len(payload) > MAX_TEMPLATE_BYTES:
        raise reservation.AliReservationError("invalid_contract_template_size", 422)
    suffix = Path(str(filename or "")).suffix.casefold()
    text = ""
    if suffix in {".txt", ".md"}:
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise reservation.AliReservationError(
                "contract_template_must_be_utf8", 422
            ) from exc
    elif suffix == ".pdf" and payload.startswith(b"%PDF-"):
        if any(marker in payload for marker in _ACTIVE_PDF_MARKERS):
            raise reservation.AliReservationError("unsafe_contract_template", 422)
        try:
            reader = PdfReader(io.BytesIO(payload), strict=True)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
                raise reservation.AliReservationError("invalid_contract_template", 422)
            text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
        except reservation.AliReservationError:
            raise
        except Exception as exc:
            raise reservation.AliReservationError("invalid_contract_template", 422) from exc
    elif suffix == ".docx" and payload.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = archive.namelist()
                if (
                    "word/document.xml" not in names
                    or len(names) > 250
                    or sum(item.file_size for item in archive.infolist()) > 8 * 1024 * 1024
                    or any("vbaProject.bin" in name for name in names)
                    or any(name.startswith("/") or ".." in Path(name).parts for name in names)
                ):
                    raise reservation.AliReservationError("unsafe_contract_template", 422)
                root = ElementTree.fromstring(archive.read("word/document.xml"))
                paragraphs = []
                for paragraph in root.iter():
                    if paragraph.tag.rsplit("}", 1)[-1] != "p":
                        continue
                    parts = [
                        str(node.text or "")
                        for node in paragraph.iter()
                        if node.tag.rsplit("}", 1)[-1] == "t"
                    ]
                    if parts:
                        paragraphs.append("".join(parts))
                text = "\n".join(paragraphs)
        except reservation.AliReservationError:
            raise
        except Exception as exc:
            raise reservation.AliReservationError("invalid_contract_template", 422) from exc
    else:
        raise reservation.AliReservationError("unsupported_contract_template_type", 422)
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    fields = set(re.findall(r"\{([a-z_]+)\}", normalized))
    if not normalized or len(normalized) > 250_000 or fields - CONTRACT_PLACEHOLDERS:
        raise reservation.AliReservationError("contract_template_placeholder_invalid", 422)
    return normalized + "\n"


def upload_contract_template(
    version_name: str,
    filename: str,
    content_type: str,
    payload: bytes,
    actor: str,
) -> dict:
    actor_id = reservation._validate_actor(actor)
    version = " ".join(str(version_name or "").split())
    if not _CONTRACT_VERSION.fullmatch(version):
        raise reservation.AliReservationError("invalid_contract_template_version", 422)
    canonical = _contract_template_text(payload, filename, content_type)
    canonical_bytes = canonical.encode("utf-8")
    digest = hashlib.sha256(canonical_bytes).hexdigest()
    safe_filename = Path(str(filename or "contract-template")).name[:180]
    baseline = _runtime_config()
    baseline_domains = _normalize_payment_domains(
        baseline.get("payment_allowed_domains") or []
    )
    ensure_schema()
    conn = _connection()
    storage_name = ""
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM ali_contract_templates WHERE tenant_slug = ? "
            "AND version_name = ?",
            (TENANT_SLUG, version),
        ).fetchone()
        if existing:
            if existing["content_sha256"] != digest:
                raise reservation.AliReservationError(
                    "contract_template_version_already_exists", 409
                )
            template_id = str(existing["public_id"])
            storage_name = str(existing["canonical_storage_name"])
        else:
            template_id = str(uuid.uuid4())
            storage_name = _write_private(canonical_bytes, ".txt", "_templates")
            conn.execute(
                "INSERT INTO ali_contract_templates (public_id, tenant_slug, "
                "version_name, source_filename, source_mime, canonical_storage_name, "
                "content_sha256, created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    template_id,
                    TENANT_SLUG,
                    version,
                    safe_filename,
                    str(content_type or "application/octet-stream")[:120],
                    storage_name,
                    digest,
                    _iso(),
                    actor_id,
                ),
            )
        timestamp = _iso()
        conn.execute(
            "INSERT INTO ali_customer_dossier_settings (tenant_slug, "
            "active_contract_template_public_id, payment_mode, payment_provider_name, "
            "default_payment_url, default_payment_domain, payment_allowed_domains_json, "
            "document_retention_days, paper_shredding_policy, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(tenant_slug) DO UPDATE SET "
            "active_contract_template_public_id=excluded.active_contract_template_public_id, "
            "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (
                TENANT_SLUG,
                template_id,
                str(baseline.get("payment_mode") or "per_reservation"),
                str(baseline.get("payment_provider_name") or ""),
                str(baseline.get("default_payment_url") or "") or None,
                str(baseline.get("default_payment_domain") or "") or None,
                json.dumps(baseline_domains, separators=(",", ":")),
                int(
                    baseline.get("document_retention_days")
                    or DEFAULT_DOCUMENT_RETENTION_DAYS
                ),
                str(
                    baseline.get("paper_shredding_policy")
                    or DEFAULT_PAPER_SHREDDING_POLICY
                ),
                timestamp,
                actor_id,
            ),
        )
        conn.execute(
            "INSERT INTO ali_customer_dossier_settings_audit "
            "(public_id, tenant_slug, action, actor_id, metadata_json, created_at) "
            "VALUES (?, ?, 'contract_template_activated', ?, ?, ?)",
            (
                str(uuid.uuid4()),
                TENANT_SLUG,
                actor_id,
                json.dumps(
                    {"template_id": template_id, "version": version, "sha256": digest},
                    sort_keys=True,
                ),
                timestamp,
            ),
        )
        conn.commit()
        return tenant_settings()
    except Exception:
        conn.rollback()
        if storage_name:
            stored = _stored_path(storage_name)
            if stored.is_file() and not conn.execute(
                "SELECT 1 FROM ali_contract_templates WHERE canonical_storage_name = ?",
                (storage_name,),
            ).fetchone():
                stored.unlink()
        raise
    finally:
        conn.close()


def save_tenant_settings(
    *,
    payment_mode: str,
    payment_provider_name: str,
    payment_url: str | None,
    clear_payment_url: bool,
    payment_allowed_domains: list[str],
    document_retention_days: int,
    paper_shredding_policy: str,
    actor: str,
) -> dict:
    actor_id = reservation._validate_actor(actor)
    mode = str(payment_mode or "")
    if mode not in PAYMENT_MODES:
        raise reservation.AliReservationError("invalid_payment_mode", 422)
    provider = " ".join(str(payment_provider_name or "").split())
    if len(provider) > 80:
        raise reservation.AliReservationError("invalid_payment_provider_name", 422)
    if (
        isinstance(document_retention_days, bool)
        or not isinstance(document_retention_days, int)
        or not 1 <= document_retention_days <= 3650
    ):
        raise reservation.AliReservationError("invalid_document_retention_days", 422)
    shredding = " ".join(str(paper_shredding_policy or "").split())
    if not 10 <= len(shredding) <= 500:
        raise reservation.AliReservationError("invalid_paper_shredding_policy", 422)
    domains = _normalize_payment_domains(payment_allowed_domains)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT * FROM ali_customer_dossier_settings WHERE tenant_slug = ?",
            (TENANT_SLUG,),
        ).fetchone()
        active_template = (
            str(current["active_contract_template_public_id"] or "")
            if current else ""
        )
        current_url = str(current["default_payment_url"] or "") if current else ""
        next_url = "" if clear_payment_url or mode == "per_reservation" else current_url
        if payment_url is not None and str(payment_url).strip():
            raw_url = str(payment_url).strip()
            try:
                candidate_host = str(urllib.parse.urlsplit(raw_url).hostname or "").lower().rstrip(".")
            except ValueError as exc:
                raise reservation.AliReservationError("invalid_payment_url", 422) from exc
            if candidate_host and candidate_host not in domains:
                domains.append(candidate_host)
                domains = _normalize_payment_domains(domains)
            next_url, _ = _validated_payment_url(raw_url, domains)
        if mode == "fixed_link" and not next_url:
            raise reservation.AliReservationError("default_payment_link_required", 422)
        if next_url:
            next_url, default_domain = _validated_payment_url(next_url, domains)
        else:
            default_domain = ""
        timestamp = _iso()
        conn.execute(
            "INSERT INTO ali_customer_dossier_settings (tenant_slug, "
            "active_contract_template_public_id, payment_mode, payment_provider_name, "
            "default_payment_url, default_payment_domain, payment_allowed_domains_json, "
            "document_retention_days, paper_shredding_policy, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(tenant_slug) DO UPDATE SET "
            "payment_mode=excluded.payment_mode, payment_provider_name=excluded.payment_provider_name, "
            "default_payment_url=excluded.default_payment_url, "
            "default_payment_domain=excluded.default_payment_domain, "
            "payment_allowed_domains_json=excluded.payment_allowed_domains_json, "
            "document_retention_days=excluded.document_retention_days, "
            "paper_shredding_policy=excluded.paper_shredding_policy, "
            "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (
                TENANT_SLUG,
                active_template or None,
                mode,
                provider,
                next_url or None,
                default_domain or None,
                json.dumps(domains, separators=(",", ":")),
                document_retention_days,
                shredding,
                timestamp,
                actor_id,
            ),
        )
        conn.execute(
            "INSERT INTO ali_customer_dossier_settings_audit "
            "(public_id, tenant_slug, action, actor_id, metadata_json, created_at) "
            "VALUES (?, ?, 'settings_updated', ?, ?, ?)",
            (
                str(uuid.uuid4()),
                TENANT_SLUG,
                actor_id,
                json.dumps(
                    {
                        "payment_mode": mode,
                        "provider_present": bool(provider),
                        "default_link_configured": bool(next_url),
                        "payment_domains": domains,
                        "document_retention_days": document_retention_days,
                        "paper_shredding_policy_configured": bool(shredding),
                    },
                    sort_keys=True,
                ),
                timestamp,
            ),
        )
        conn.commit()
        return tenant_settings()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_tenant_activation(enabled: bool, actor: str) -> dict:
    """Enable or disable the tenant-owned customer dossier workflow.

    Enabling is fail-closed: every non-feature configuration gate must already
    pass. Disabling remains available even if a later configuration problem is
    detected, so the tenant always has a safe kill switch.
    """
    actor_id = reservation._validate_actor(actor)
    if not isinstance(enabled, bool):
        raise reservation.AliReservationError("invalid_dossier_activation", 422)
    before = configuration_status()
    if enabled and not before["configurationReady"]:
        raise reservation.AliReservationError(
            "customer_dossier_activation_requirements_incomplete", 409,
        )
    previous = bool(before["enabled"])
    if previous == enabled:
        return tenant_settings()
    if not config_loader.update_ali_customer_dossier_enabled(enabled):
        raise reservation.AliReservationError(
            "customer_dossier_activation_write_failed", 500,
        )
    after = configuration_status()
    if enabled and not after["ready"]:
        config_loader.update_ali_customer_dossier_enabled(previous)
        raise reservation.AliReservationError(
            "customer_dossier_activation_requirements_incomplete", 409,
        )
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO ali_customer_dossier_settings_audit "
            "(public_id, tenant_slug, action, actor_id, metadata_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                TENANT_SLUG,
                "dossier_activated" if enabled else "dossier_deactivated",
                actor_id,
                json.dumps(
                    {
                        "enabled": enabled,
                        "configuration_ready": bool(after["configurationReady"]),
                    },
                    sort_keys=True,
                ),
                _iso(),
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        config_loader.update_ali_customer_dossier_enabled(previous)
        raise
    finally:
        conn.close()
    return tenant_settings()


def tenant_settings() -> dict:
    """Return tenant configuration without paths, secrets, or payment URLs."""
    settings = _runtime_config()
    ensure_schema()
    conn = _connection()
    try:
        template = None
        template_id = str(settings.get("contract_template_public_id") or "")
        if template_id:
            row = conn.execute(
                "SELECT version_name, source_filename, content_sha256, created_at "
                "FROM ali_contract_templates WHERE tenant_slug = ? AND public_id = ?",
                (TENANT_SLUG, template_id),
            ).fetchone()
            if row:
                template = {
                    "publicId": template_id,
                    "version": row["version_name"],
                    "sourceFilename": row["source_filename"],
                    "sha256": row["content_sha256"],
                    "uploadedAt": row["created_at"],
                }
        if template is None and settings.get("contract_template_version"):
            path = Path(str(settings.get("contract_template_path") or ""))
            template = {
                "publicId": None,
                "version": str(settings["contract_template_version"]),
                "sourceFilename": path.name if path.name else "configured template",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
                "uploadedAt": None,
            }
        return {
            "status": configuration_status(),
            "contractTemplate": template,
            "payment": {
                "mode": str(settings.get("payment_mode") or "per_reservation"),
                "providerName": str(settings.get("payment_provider_name") or ""),
                "defaultLinkConfigured": bool(settings.get("default_payment_url")),
                "defaultDomain": str(settings.get("default_payment_domain") or "") or None,
                "allowedDomains": _normalize_payment_domains(
                    settings.get("payment_allowed_domains") or []
                ),
            },
            "retention": {
                "documentRetentionDays": int(
                    settings.get("document_retention_days")
                    or DEFAULT_DOCUMENT_RETENTION_DAYS
                ),
                "paperShreddingPolicy": str(
                    settings.get("paper_shredding_policy")
                    or DEFAULT_PAPER_SHREDDING_POLICY
                ),
            },
        }
    finally:
        conn.close()


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
    # The database hash is the verifier for this opaque bearer credential.
    # Twenty-four random bytes provide 192 bits of entropy while keeping the
    # customer-facing URL compact enough for WhatsApp. Legacy nonce.signature
    # tokens remain accepted by _verify_token until their normal expiry.
    token = secrets.token_urlsafe(COMPACT_TOKEN_BYTES)
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
    value = str(token or "")
    parts = value.split(".")
    compact = bool(re.fullmatch(r"[A-Za-z0-9_-]{32}", value))
    legacy = (
        len(parts) == 2
        and bool(parts[0])
        and bool(parts[1])
        and hmac.compare_digest(parts[1], _token_signature(parts[0]))
    )
    if not compact and not legacy:
        raise reservation.AliReservationError("invalid_or_expired_token", 404)
    ensure_schema()
    conn = _connection()
    row = conn.execute(
        "SELECT * FROM ali_reservation_tokens WHERE token_hash = ? "
        "AND tenant_slug = ? AND purpose = ?",
        (hashlib.sha256(value.encode("ascii")).hexdigest(), TENANT_SLUG, purpose),
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
    from agents.social import ali_reservation_v2
    if ali_reservation_v2.enabled():
        workflow_case = ali_reservation_v2.get_case(public_id)
        if workflow_case["state"] != "documents_collecting":
            raise reservation.AliReservationError("document_intake_not_ready", 409)
        ensure_schema()
        conn = _connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = _available_case(conn, public_id)
            reservation._check_revision(row, expected_revision)
            if row["identity_status"] != "requested":
                timestamp = _iso()
                conn.execute(
                    "UPDATE ali_reservations SET identity_status = 'requested', "
                    "status = 'requirements_pending', last_staff_actor = ?, "
                    "last_staff_action_at = ?, revision = revision + 1, updated_at = ? "
                    "WHERE tenant_slug = ? AND public_id = ?",
                    (actor_id, timestamp, timestamp, TENANT_SLUG, public_id),
                )
                reservation._event(
                    conn, public_id, "direct_whatsapp_document_intake_requested",
                    str(row["status"]), "requirements_pending", "staff", actor_id,
                    {"workflow_version": 2, "public_upload_links": 0},
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return {
            "reservationPublicId": public_id,
            "mode": "direct_whatsapp",
            "identityTypes": ["passport", "id_card"],
            "links": [],
        }
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
    from agents.social import ali_reservation_v2
    if ali_reservation_v2.enabled():
        raise reservation.AliReservationError("public_document_upload_disabled", 404)
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
    required_slots = DOCUMENT_SLOTS
    try:
        from agents.social import ali_reservation_v2
        workflow = conn.execute(
            "SELECT identity_type FROM ali_reservation_v2_cases "
            "WHERE tenant_slug = ? AND reservation_public_id = ?",
            (TENANT_SLUG, public_id),
        ).fetchone()
        if workflow and workflow["identity_type"]:
            required_slots = ali_reservation_v2.required_document_slots(
                str(workflow["identity_type"]),
            ) or DOCUMENT_SLOTS
    except sqlite3.OperationalError:
        required_slots = DOCUMENT_SLOTS
    values = [statuses.get(slot) for slot in required_slots]
    if all(value in {"verified", "not_required"} for value in values):
        return "verified"
    if any(value == "replacement_requested" for value in values):
        return "replacement_requested"
    if any(value == "rejected" for value in values):
        return "rejected"
    received = sum(value in {"received", "verified", "not_required"} for value in values)
    if received == len(required_slots):
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
    from agents.social import ali_reservation_v2
    if ali_reservation_v2.enabled():
        raise reservation.AliReservationError("public_document_upload_disabled", 404)
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


def store_whatsapp_document(
    public_id: str,
    *,
    slot: str,
    payload: bytes,
    claimed_mime: str,
    provider_message_id: str,
    provider_attachment_id: str,
    filename: str = "",
    classification_source: str = "expected_slot",
) -> dict:
    """Persist one authenticated inbound WhatsApp attachment privately.

    Provider URLs are intentionally absent from the API and schema.  Only
    deterministic hashes of provider identifiers are retained for replay
    protection.  The caller must already have verified the signed Zernio
    webhook and tenant/account/conversation binding.
    """
    from agents.social import ali_reservation_v2

    if not ali_reservation_v2.enabled():
        raise reservation.AliReservationError("reservation_v2_not_enabled", 409)
    if classification_source not in {"expected_slot", "customer_classified", "unclassified"}:
        raise reservation.AliReservationError("invalid_document_classification", 422)
    workflow_case = ali_reservation_v2.get_case(public_id)
    collecting = workflow_case["state"] in {
        "documents_collecting", "document_replacement_required",
    }
    if slot != "unclassified" and not collecting:
        raise reservation.AliReservationError("document_not_expected", 409)
    expected = str(workflow_case.get("expectedDocumentSlot") or "")
    if slot != "unclassified" and slot != expected:
        raise reservation.AliReservationError("unexpected_document_slot", 409)
    if slot == "unclassified" and classification_source != "unclassified":
        raise reservation.AliReservationError("invalid_document_classification", 422)
    if not str(provider_message_id or "").strip() or not str(provider_attachment_id or "").strip():
        raise reservation.AliReservationError("provider_attachment_identity_missing", 422)

    mime, extension = _validated_upload(payload, claimed_mime)
    digest = hashlib.sha256(payload).hexdigest()
    message_hash = hashlib.sha256(str(provider_message_id).encode("utf-8")).hexdigest()
    attachment_hash = hashlib.sha256(str(provider_attachment_id).encode("utf-8")).hexdigest()
    safe_filename = Path(str(filename or "")).name.replace("\x00", "")[:180]
    ensure_schema()
    conn = _connection()
    storage_name = ""
    try:
        conn.execute("BEGIN IMMEDIATE")
        _available_case(conn, public_id)
        replay = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? "
            "AND provider_attachment_id_hash = ?",
            (TENANT_SLUG, attachment_hash),
        ).fetchone()
        if replay:
            if replay["reservation_public_id"] != public_id or replay["sha256"] != digest:
                raise reservation.AliReservationError("provider_attachment_replay_mismatch", 409)
            if str(replay["slot"] or "") != str(slot):
                # A provider may deliver the same attachment again under a new
                # message after the checklist has advanced.  Treating that as
                # success makes Nick acknowledge the new slot even though no
                # new document was stored, trapping the customer in a loop.
                raise reservation.AliReservationError("duplicate_document_content", 422)
            conn.commit()
            result = _safe_document(replay)
            result["replayed"] = True
            result["workflowV2"] = ali_reservation_v2.get_case(public_id)
            return result
        duplicate_content = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? "
            "AND reservation_public_id = ? AND sha256 = ? AND status NOT IN "
            "('deleted','replaced') ORDER BY version DESC LIMIT 1",
            (TENANT_SLUG, public_id, digest),
        ).fetchone()
        if duplicate_content:
            # A byte-identical upload with a new provider attachment id is a
            # customer resend, not a transport replay.  It cannot satisfy a
            # different checklist slot (or replace a rejected copy), so fail
            # explicitly and let the inbound layer explain what is wrong.
            raise reservation.AliReservationError("duplicate_document_content", 422)

        storage_name = _write_private(payload, extension, public_id)
        current = None
        if slot != "unclassified":
            current = conn.execute(
                "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? "
                "AND reservation_public_id = ? AND slot = ? "
                "ORDER BY version DESC LIMIT 1",
                (TENANT_SLUG, public_id, slot),
            ).fetchone()
        version_row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM ali_reservation_documents "
            "WHERE tenant_slug = ? AND reservation_public_id = ? AND slot = ?",
            (TENANT_SLUG, public_id, slot),
        ).fetchone()
        version = int(version_row[0])
        document_id = str(uuid.uuid4())
        timestamp = _iso()
        if current and current["status"] not in {"deleted", "replaced"}:
            conn.execute(
                "UPDATE ali_reservation_documents SET status = 'replaced', "
                "updated_at = ? WHERE tenant_slug = ? AND public_id = ?",
                (timestamp, TENANT_SLUG, current["public_id"]),
            )
        status = "unclassified" if slot == "unclassified" else "received"
        unclassified_expiry = (
            _iso(_now() + timedelta(days=7)) if status == "unclassified" else None
        )
        conn.execute(
            "INSERT INTO ali_reservation_documents (public_id, tenant_slug, "
            "reservation_public_id, slot, version, mime_type, size_bytes, sha256, "
            "storage_name, status, previous_document_public_id, created_at, updated_at, "
            "provider_message_id_hash, provider_attachment_id_hash, original_filename, "
            "quarantine_status, classification_source, unclassified_expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'validated', ?, ?)",
            (
                document_id, TENANT_SLUG, public_id, slot, version, mime,
                len(payload), digest, storage_name, status,
                str(current["public_id"]) if current else None, timestamp, timestamp,
                message_hash, attachment_hash, safe_filename or None,
                classification_source, unclassified_expiry,
            ),
        )
        if status != "unclassified":
            # V2 treats a securely stored and validated upload as sufficient
            # to continue the customer checklist. Human review is performed
            # once on the complete pre-payment file, so the legacy roll-up
            # must reflect receipt without pretending an individual document
            # was verified.
            conn.execute(
                "UPDATE ali_reservations SET identity_status = ?, updated_at = ? "
                "WHERE tenant_slug = ? AND public_id = ?",
                (_document_rollup(conn, public_id), timestamp, TENANT_SLUG, public_id),
            )
        case = _case(conn, public_id)
        reservation._event(
            conn, public_id,
            "whatsapp_document_unclassified" if status == "unclassified" else "whatsapp_document_received",
            str(case["status"]), str(case["status"]), "customer", "zernio_whatsapp",
            {
                "document_id": document_id,
                "slot": slot,
                "version": version,
                "mime_type": mime,
                "size_bytes": len(payload),
                "digest_prefix": digest[:12],
                "provider_message_hash": message_hash,
                "provider_attachment_hash": attachment_hash,
                "classification_source": classification_source,
            },
        )
        created = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? AND public_id = ?",
            (TENANT_SLUG, document_id),
        ).fetchone()
        conn.commit()
        result = _safe_document(created)
        result["replayed"] = False
    except Exception:
        conn.rollback()
        if storage_name:
            try:
                stored = _stored_path(storage_name)
                if stored.is_file():
                    stored.unlink()
            except reservation.AliReservationError:
                pass
        raise
    finally:
        conn.close()

    if slot != "unclassified":
        result["workflowV2"] = ali_reservation_v2.record_document_received(
            public_id, slot, provider_message_id=provider_message_id,
        )
    else:
        result["workflowV2"] = ali_reservation_v2.get_case(public_id)
    return result


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


def prepayment_review_summary(public_id: str) -> dict:
    """Return the server-derived readiness for the one pre-payment review.

    Secure receipt is enough to include a document in this bundle. Individual
    verification remains available as an exception tool, but it is not a gate
    in the normal customer journey.
    """
    from agents.social import ali_reservation_v2

    ensure_schema()
    settings = _runtime_config()
    conn = _connection()
    try:
        case = _case(conn, public_id)
        workflow_case = ali_reservation_v2.get_case(public_id)
        rows = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? "
            "AND reservation_public_id = ? ORDER BY slot, version DESC",
            (TENANT_SLUG, public_id),
        ).fetchall()
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            slot = str(row["slot"] or "")
            if slot and slot not in latest:
                latest[slot] = row
        required = ali_reservation_v2.required_document_slots(
            str(workflow_case.get("identityType") or ""),
        )
        accepted = {"received", "verified", "not_required"}
        missing_documents = [
            slot
            for slot in required
            if slot not in latest or str(latest[slot]["status"] or "") not in accepted
        ]
        contract = conn.execute(
            "SELECT status FROM ali_reservation_contracts WHERE tenant_slug = ? "
            "AND reservation_public_id = ? ORDER BY version DESC LIMIT 1",
            (TENANT_SLUG, public_id),
        ).fetchone()
        signed = bool(contract and str(contract["status"] or "") == "signed")
        payment = conn.execute(
            "SELECT payment_url FROM ali_reservation_payments WHERE tenant_slug = ? "
            "AND reservation_public_id = ?",
            (TENANT_SLUG, public_id),
        ).fetchone()
        fixed_payment = (
            str(settings.get("payment_mode") or "per_reservation") == "fixed_link"
            and bool(settings.get("default_payment_url"))
        )
        payment_ready = fixed_payment or bool(payment and payment["payment_url"])
        missing = [f"document:{slot}" for slot in missing_documents]
        if not signed:
            missing.append("signed_pre_contract")
        if str(case["availability_status"] or "") != "approved":
            missing.append("availability_approval")
        return {
            "status": str(workflow_case.get("state") or ""),
            "approvalRequired": workflow_case.get("state") == "prepayment_approval_pending",
            "approved": workflow_case.get("state") in {
                "prepayment_approved", "payment_link_sent", "customer_reports_paid",
                "payment_verified", "dossier_ready", "final_approval_pending", "confirmed",
            },
            "readyForApproval": not missing,
            "paymentReady": payment_ready,
            "canApproveAndSend": not missing and payment_ready,
            "requiredDocumentCount": len(required),
            "receivedDocumentCount": len(required) - len(missing_documents),
            "missingRequirements": missing,
        }
    finally:
        conn.close()


def record_prepayment_file_approval(public_id: str, actor: str) -> dict:
    """Project the one file approval into the legacy checklist roll-up.

    Individual V2 documents intentionally remain ``received``. The legacy
    reservation and dossier code still needs one checklist value after staff
    approves the complete bundle, so only that aggregate value is advanced.
    """
    actor_id = reservation._validate_actor(actor)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        case = _available_case(conn, public_id)
        if str(case["identity_status"] or "") == "verified":
            conn.commit()
            return reservation._public_row(case)
        if str(case["identity_status"] or "") != "received":
            raise reservation.AliReservationError(
                "prepayment_documents_incomplete", 409,
            )
        from_status = str(case["status"] or "")
        conn.execute(
            "UPDATE ali_reservations SET identity_status = 'verified' "
            "WHERE tenant_slug = ? AND public_id = ?",
            (TENANT_SLUG, public_id),
        )
        updated = _refresh_case(conn, public_id, actor_id)
        reservation._event(
            conn,
            public_id,
            "prepayment_file_approved",
            from_status,
            str(updated["status"]),
            "staff",
            actor_id,
            {"document_statuses_changed": False},
        )
        conn.commit()
        return reservation._public_row(updated)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def review_document(
    public_id: str,
    document_id: str,
    decision: str,
    actor: str,
    expected_revision: int | None = None,
    reason: str = "",
) -> dict:
    if decision not in {"verified", "rejected", "replacement_requested", "not_required"}:
        raise reservation.AliReservationError("invalid_document_decision", 422)
    actor_id = reservation._validate_actor(actor)
    review_reason = str(reason or "").strip()
    if len(review_reason) > 500:
        raise reservation.AliReservationError("invalid_document_review_reason", 422)
    from agents.social import ali_reservation_v2
    if decision == "not_required" and ali_reservation_v2.enabled():
        raise reservation.AliReservationError("document_slot_required", 409)
    if (
        ali_reservation_v2.enabled()
        and decision in {"rejected", "replacement_requested"}
        and not review_reason
    ):
        raise reservation.AliReservationError("document_review_reason_required", 422)
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
            result = _safe_document(row)
            from agents.social import ali_reservation_v2_automation
            result["automationV2"] = (
                ali_reservation_v2_automation.after_document_review(public_id)
            )
            return result
        timestamp = _iso()
        conn.execute(
            "UPDATE ali_reservation_documents SET status = ?, updated_at = ?, "
            "verified_at = ?, verified_by = ?, review_reason = ? "
            "WHERE public_id = ? AND tenant_slug = ?",
            (
                decision, timestamp,
                timestamp if decision in {"verified", "not_required"} else None,
                actor_id if decision in {"verified", "not_required"} else None,
                review_reason or None,
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
            {
                "document_id": document_id,
                "slot": row["slot"],
                "decision": decision,
                "reason_present": bool(review_reason),
            },
        )
        updated = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE public_id = ?", (document_id,),
        ).fetchone()
        conn.commit()
        result = _safe_document(updated)
        from agents.social import ali_reservation_v2_automation
        result["automationV2"] = (
            ali_reservation_v2_automation.after_document_review(public_id)
        )
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def request_document_replacement(
    public_id: str,
    document_id: str,
    actor: str,
    expected_revision: int | None = None,
    reason: str = "",
) -> dict:
    """Request one exact replacement through the active delivery channel."""
    actor_id = reservation._validate_actor(actor)
    review_reason = str(reason or "").strip()
    if len(review_reason) > 500:
        raise reservation.AliReservationError("invalid_document_review_reason", 422)
    from agents.social import ali_reservation_v2
    if ali_reservation_v2.enabled() and not review_reason:
        raise reservation.AliReservationError("document_review_reason_required", 422)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        case = _available_case(conn, public_id)
        reservation._check_revision(case, expected_revision)
        document = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? "
            "AND reservation_public_id = ? AND public_id = ?",
            (TENANT_SLUG, public_id, document_id),
        ).fetchone()
        if not document or document["status"] in {"deleted", "replaced", "not_required"}:
            raise reservation.AliReservationError("document_not_found", 404)
        timestamp = _iso()
        conn.execute(
            "UPDATE ali_reservation_documents SET status = 'replacement_requested', "
            "updated_at = ?, verified_at = NULL, verified_by = NULL, "
            "review_reason = ? "
            "WHERE tenant_slug = ? AND public_id = ?",
            (timestamp, review_reason or None, TENANT_SLUG, document_id),
        )
        conn.execute(
            "UPDATE ali_reservations SET identity_status = 'replacement_requested', "
            "status = 'requirements_pending', last_staff_actor = ?, "
            "last_staff_action_at = ?, revision = revision + 1, updated_at = ? "
            "WHERE tenant_slug = ? AND public_id = ?",
            (actor_id, timestamp, timestamp, TENANT_SLUG, public_id),
        )
        direct_whatsapp = ali_reservation_v2.enabled()
        token = ""
        expires = ""
        if not direct_whatsapp:
            token, expires = _new_token(
                conn,
                public_id,
                "document_upload",
                slot=str(document["slot"]),
            )
        reservation._event(
            conn,
            public_id,
            "document_replacement_requested",
            str(case["status"]),
            "requirements_pending",
            "staff",
            actor_id,
            {
                "document_id": document_id,
                "slot": document["slot"],
                "version": document["version"],
                "reason_present": bool(review_reason),
            },
        )
        conn.commit()
        result = {
            "document": _safe_document(conn.execute(
                "SELECT * FROM ali_reservation_documents WHERE public_id = ?",
                (document_id,),
            ).fetchone()),
            "mode": "direct_whatsapp" if direct_whatsapp else "signed_upload_link",
            "replacementSlot": str(document["slot"]) if direct_whatsapp else None,
            "links": [] if direct_whatsapp else [{
                "slot": document["slot"],
                "url": f"{_public_base_url()}/dashboard/api/ali-reservations/public/documents/{token}",
                "expiresAt": expires,
            }],
        }
        if direct_whatsapp:
            result["workflowV2"] = ali_reservation_v2.request_document_replacement(
                public_id,
                str(document["slot"]),
                actor_id=actor_id,
                idempotency_key=(
                    f"replacement:{document['public_id']}:{document['version']}"
                ),
            )
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reclassify_whatsapp_document(
    public_id: str,
    document_id: str,
    slot: str,
    actor: str,
    expected_revision: int | None = None,
) -> dict:
    """Assign one validated, unclassified WhatsApp file to the expected slot."""
    from agents.social import ali_reservation_v2

    if not ali_reservation_v2.enabled():
        raise reservation.AliReservationError("reservation_v2_not_enabled", 409)
    actor_id = reservation._validate_actor(actor)
    target_slot = str(slot or "").strip()
    current_v2 = ali_reservation_v2.get_case(public_id)
    if target_slot != str(current_v2.get("expectedDocumentSlot") or ""):
        raise reservation.AliReservationError("unexpected_document_slot", 409)
    if target_slot not in ali_reservation_v2.required_document_slots(
        str(current_v2.get("identityType") or "")
    ):
        raise reservation.AliReservationError("invalid_document_slot", 422)

    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        case = _available_case(conn, public_id)
        reservation._check_revision(case, expected_revision)
        document = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? "
            "AND reservation_public_id = ? AND public_id = ?",
            (TENANT_SLUG, public_id, document_id),
        ).fetchone()
        if not document or document["status"] != "unclassified":
            raise reservation.AliReservationError("unclassified_document_not_found", 404)
        prior = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? "
            "AND reservation_public_id = ? AND slot = ? AND status NOT IN "
            "('deleted','replaced') ORDER BY version DESC LIMIT 1",
            (TENANT_SLUG, public_id, target_slot),
        ).fetchone()
        timestamp = _iso()
        if prior:
            conn.execute(
                "UPDATE ali_reservation_documents SET status = 'replaced', "
                "updated_at = ? WHERE tenant_slug = ? AND public_id = ?",
                (timestamp, TENANT_SLUG, prior["public_id"]),
            )
        version = int(conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM ali_reservation_documents "
            "WHERE tenant_slug = ? AND reservation_public_id = ? AND slot = ?",
            (TENANT_SLUG, public_id, target_slot),
        ).fetchone()[0])
        conn.execute(
            "UPDATE ali_reservation_documents SET slot = ?, version = ?, "
            "status = 'received', classification_source = 'staff_reclassified', "
            "unclassified_expires_at = NULL, previous_document_public_id = ?, "
            "updated_at = ? WHERE tenant_slug = ? AND public_id = ?",
            (
                target_slot, version,
                str(prior["public_id"]) if prior else None,
                timestamp, TENANT_SLUG, document_id,
            ),
        )
        reservation._event(
            conn, public_id, "whatsapp_document_reclassified",
            str(case["status"]), str(case["status"]), "staff", actor_id,
            {
                "document_id": document_id,
                "slot": target_slot,
                "version": version,
            },
        )
        updated = conn.execute(
            "SELECT * FROM ali_reservation_documents WHERE tenant_slug = ? "
            "AND public_id = ?",
            (TENANT_SLUG, document_id),
        ).fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    result = _safe_document(updated)
    result["workflowV2"] = ali_reservation_v2.record_document_received(
        public_id,
        target_slot,
        provider_message_id=f"reclassify:{document_id}",
    )
    return result


def mark_document_slot_not_required(
    public_id: str,
    slot: str,
    actor: str,
    expected_revision: int | None = None,
) -> dict:
    """Mark only the optional licence-back slot as not required."""
    if slot != "license_back":
        raise reservation.AliReservationError("document_slot_required", 409)
    from agents.social import ali_reservation_v2
    if ali_reservation_v2.enabled():
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


def purge_expired_documents(now: datetime | None = None) -> dict:
    """Delete private identity bytes after the tenant's post-rental window."""
    settings = _runtime_config()
    retention_days = int(
        settings.get("document_retention_days") or DEFAULT_DOCUMENT_RETENTION_DAYS
    )
    current = (now or _now()).astimezone(timezone.utc)
    ensure_schema()
    conn = _connection()
    deleted = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT d.*, r.status AS reservation_status, r.updated_at AS reservation_updated_at, "
            "q.rental_json FROM ali_reservation_documents d "
            "JOIN ali_reservations r ON r.public_id = d.reservation_public_id "
            "LEFT JOIN ali_quotes q ON q.public_id = r.quote_public_id "
            "AND q.quote_snapshot_id = r.quote_snapshot_id "
            "WHERE d.tenant_slug = ? AND d.status NOT IN ('deleted','replaced') "
            "AND r.status IN ('confirmed','cancelled','declined')",
            (TENANT_SLUG,),
        ).fetchall()
        for row in rows:
            anchor: datetime | None = None
            if row["reservation_status"] == "confirmed":
                try:
                    rental = json.loads(row["rental_json"] or "{}")
                    rental_end = str(rental.get("rental_end") or "")[:10]
                    anchor = datetime.fromisoformat(rental_end).replace(
                        hour=23, minute=59, second=59, tzinfo=timezone.utc
                    )
                except (TypeError, ValueError, json.JSONDecodeError):
                    anchor = None
            if anchor is None:
                try:
                    anchor = datetime.fromisoformat(
                        str(row["reservation_updated_at"]).replace("Z", "+00:00")
                    ).astimezone(timezone.utc)
                except (TypeError, ValueError):
                    continue
            if anchor + timedelta(days=retention_days) > current:
                continue
            storage_name = str(row["storage_name"] or "")
            if storage_name:
                path = _stored_path(storage_name)
                if path.is_file():
                    path.unlink()
            timestamp = _iso(current)
            conn.execute(
                "UPDATE ali_reservation_documents SET status = 'deleted', mime_type = NULL, "
                "size_bytes = 0, sha256 = NULL, storage_name = NULL, deleted_at = ?, "
                "deleted_by = 'retention_policy', updated_at = ? WHERE tenant_slug = ? "
                "AND public_id = ?",
                (timestamp, timestamp, TENANT_SLUG, row["public_id"]),
            )
            reservation._event(
                conn,
                str(row["reservation_public_id"]),
                "document_retention_deleted",
                str(row["reservation_status"]),
                str(row["reservation_status"]),
                "system",
                "retention_policy",
                {
                    "document_id": row["public_id"],
                    "slot": row["slot"],
                    "version": row["version"],
                    "retention_days": retention_days,
                },
            )
            deleted += 1
        conn.commit()
        return {"documentsDeleted": deleted, "retentionDays": retention_days}
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


_CONTRACT_REPEAT_HEADERS = {
    "VEHICLE RENTAL PRE-CONTRACT",
    "Reservation summary and customer acknowledgment",
    "ALI",
    "CAR RENTAL",
}


def _contract_pdf_text(value: object) -> str:
    """Escape tenant/customer values before ReportLab parses inline markup."""
    return html.escape(str(value or ""), quote=False)


def _contract_is_label(value: str) -> bool:
    letters = [character for character in value if character.isalpha()]
    return (
        bool(letters)
        and len(value) <= 48
        and value.upper() == value
        and not value.startswith("DRAFT TEMPLATE")
    )


def _contract_pdf(title: str, contract_text: str, audit_lines: list[str]) -> bytes:
    """Render approved template text as a legible agreement.

    Uploaded templates are canonicalized to text for deterministic snapshots.
    The old renderer passed the complete template to ``textwrap.wrap`` as one
    value, erasing every paragraph and section boundary. This renderer changes
    presentation only: source lines and substituted values remain unchanged.
    """
    navy = colors.HexColor("#08243C")
    blue_gray = colors.HexColor("#5F7180")
    gold = colors.HexColor("#F4B400")
    pale_gold = colors.HexColor("#FFF8DC")
    pale_blue = colors.HexColor("#F3F7FA")
    rule = colors.HexColor("#D9E3EA")

    styles = {
        "title": ParagraphStyle(
            "AliContractTitle", fontName="Helvetica-Bold", fontSize=20,
            leading=24, textColor=navy, spaceAfter=5 * mm,
        ),
        "subtitle": ParagraphStyle(
            "AliContractSubtitle", fontName="Helvetica", fontSize=10,
            leading=14, textColor=blue_gray, spaceAfter=5 * mm,
        ),
        "section_number": ParagraphStyle(
            "AliContractSectionNumber", fontName="Helvetica-Bold", fontSize=9,
            leading=11, textColor=navy, alignment=TA_CENTER,
        ),
        "section_title": ParagraphStyle(
            "AliContractSectionTitle", fontName="Helvetica-Bold", fontSize=13,
            leading=16, textColor=navy,
        ),
        "body": ParagraphStyle(
            "AliContractBody", fontName="Helvetica", fontSize=9.4,
            leading=13.5, textColor=colors.HexColor("#203341"),
            spaceAfter=3.2 * mm,
        ),
        "clause": ParagraphStyle(
            "AliContractClause", fontName="Helvetica-Bold", fontSize=10.2,
            leading=13, textColor=navy, spaceBefore=2.2 * mm,
            spaceAfter=1.2 * mm,
        ),
        "label": ParagraphStyle(
            "AliContractLabel", fontName="Helvetica-Bold", fontSize=7.7,
            leading=10, textColor=blue_gray,
        ),
        "label_light": ParagraphStyle(
            "AliContractLabelLight", fontName="Helvetica-Bold", fontSize=7.7,
            leading=10, textColor=colors.white,
        ),
        "value": ParagraphStyle(
            "AliContractValue", fontName="Helvetica-Bold", fontSize=9.6,
            leading=12, textColor=navy,
        ),
        "notice": ParagraphStyle(
            "AliContractNotice", fontName="Helvetica-Bold", fontSize=8.5,
            leading=12, textColor=colors.HexColor("#6B4E00"),
        ),
        "contact": ParagraphStyle(
            "AliContractContact", fontName="Helvetica", fontSize=8.5,
            leading=11, textColor=navy,
        ),
        "audit": ParagraphStyle(
            "AliContractAudit", fontName="Helvetica", fontSize=7.1,
            leading=10, textColor=blue_gray, wordWrap="CJK",
        ),
        "bullet": ParagraphStyle(
            "AliContractBullet", fontName="Helvetica", fontSize=9.2,
            leading=13, textColor=colors.HexColor("#203341"),
            leftIndent=5 * mm, firstLineIndent=-3.5 * mm, bulletIndent=0,
            spaceAfter=2 * mm,
        ),
    }

    output = io.BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=24 * mm, bottomMargin=18 * mm, title=title,
        author="Ali Car Rental Curacao", subject="Vehicle rental pre-contract",
    )
    usable_width = A4[0] - document.leftMargin - document.rightMargin
    story: list[object] = [
        Paragraph(_contract_pdf_text(title), styles["title"]),
        Paragraph(
            "Reservation summary and customer acknowledgment",
            styles["subtitle"],
        ),
    ]
    lines = [line.strip() for line in str(contract_text or "").splitlines()]
    body_buffer: list[str] = []
    summary_rows: list[tuple[str, str]] = []
    current_section = ""
    contact_rendered = False
    draft_rendered = False
    checklist_intro_rendered = False

    def flush_body() -> None:
        if body_buffer:
            story.append(Paragraph(
                _contract_pdf_text(" ".join(body_buffer)), styles["body"],
            ))
            body_buffer.clear()

    def flush_summary() -> None:
        if not summary_rows:
            return
        rows = [
            [
                Paragraph(_contract_pdf_text(label), styles["label"]),
                Paragraph(_contract_pdf_text(value), styles["value"]),
            ]
            for label, value in summary_rows
        ]
        table = Table(
            rows, colWidths=[54 * mm, usable_width - 54 * mm], hAlign="LEFT",
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), pale_blue),
            ("BOX", (0, 0), (-1, -1), 0.6, rule),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, rule),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.extend([table, Spacer(1, 4 * mm)])
        summary_rows.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        if not line:
            flush_body()
            flush_summary()
            index += 1
            continue
        if line in _CONTRACT_REPEAT_HEADERS:
            index += 1
            continue
        if line.startswith("Ali Car Rental Cura") and "WhatsApp" in line:
            if not contact_rendered:
                flush_body()
                contact = Table(
                    [[Paragraph(_contract_pdf_text(line), styles["contact"])]],
                    colWidths=[usable_width],
                )
                contact.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), pale_blue),
                    ("BOX", (0, 0), (-1, -1), 0.6, rule),
                    ("LEFTPADDING", (0, 0), (-1, -1), 9),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]))
                story.extend([contact, Spacer(1, 4 * mm)])
                contact_rendered = True
            index += 1
            continue
        if re.fullmatch(r"DRAFT V\d+\s*\|\s*PAGE\s+\d+", line):
            if not draft_rendered:
                version = line.split("|", 1)[0].strip()
                story.extend([
                    Paragraph(_contract_pdf_text(version), styles["label"]),
                    Spacer(1, 2 * mm),
                ])
                draft_rendered = True
            index += 1
            continue
        if line.startswith("DRAFT TEMPLATE"):
            flush_body()
            notice = Table(
                [[Paragraph(_contract_pdf_text(line), styles["notice"])]],
                colWidths=[usable_width],
            )
            notice.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), pale_gold),
                ("BOX", (0, 0), (-1, -1), 0.8, gold),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]))
            story.extend([notice, Spacer(1, 4 * mm)])
            index += 1
            continue
        if re.fullmatch(r"\d{2}", line) and index + 1 < len(lines):
            flush_body()
            flush_summary()
            current_section = line
            checklist_intro_rendered = False
            section_title = lines[index + 1]
            section = Table(
                [[
                    Paragraph(_contract_pdf_text(line), styles["section_number"]),
                    Paragraph(
                        _contract_pdf_text(section_title), styles["section_title"],
                    ),
                ]],
                colWidths=[13 * mm, usable_width - 13 * mm],
            )
            section.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, 0), gold),
                ("BACKGROUND", (1, 0), (1, 0), pale_blue),
                ("BOX", (0, 0), (-1, -1), 0.6, rule),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]))
            story.extend([
                Spacer(1, 2 * mm),
                CondPageBreak(22 * mm),
                section,
                Spacer(1, 3 * mm),
            ])
            index += 2
            continue
        if (
            current_section == "03"
            and line == "DESCRIPTION"
            and index + 1 < len(lines)
            and lines[index + 1] == "AMOUNT"
        ):
            flush_body()
            financial_rows: list[list[Paragraph]] = [[
                Paragraph("DESCRIPTION", styles["label_light"]),
                Paragraph("AMOUNT", styles["label_light"]),
            ]]
            index += 2
            while (
                index + 1 < len(lines)
                and lines[index + 1].startswith("USD ")
            ):
                financial_rows.append([
                    Paragraph(_contract_pdf_text(lines[index]), styles["body"]),
                    Paragraph(
                        _contract_pdf_text(lines[index + 1]), styles["value"],
                    ),
                ])
                index += 2
            table = Table(
                financial_rows,
                colWidths=[usable_width - 42 * mm, 42 * mm],
                repeatRows=1,
            )
            commands = [
                ("BACKGROUND", (0, 0), (-1, 0), navy),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.7, rule),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, rule),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
            if len(financial_rows) > 1:
                commands.append(("BACKGROUND", (0, -1), (-1, -1), pale_gold))
            table.setStyle(TableStyle(commands))
            story.extend([
                CondPageBreak(50 * mm),
                table,
                Spacer(1, 4 * mm),
            ])
            continue
        if (
            current_section == "06"
            and line == "CUSTOMER ELECTRONIC SIGNATURE"
            and index + 7 < len(lines)
            and lines[index + 1] == "ALI AUTHORIZED APPROVAL"
        ):
            flush_body()
            flush_summary()
            signature_rows = [
                [
                    Paragraph(
                        _contract_pdf_text(lines[index]), styles["label_light"],
                    ),
                    Paragraph(
                        _contract_pdf_text(lines[index + 1]),
                        styles["label_light"],
                    ),
                ],
                [
                    Paragraph(
                        _contract_pdf_text(lines[index + 2]), styles["body"],
                    ),
                    Paragraph(
                        _contract_pdf_text(lines[index + 3]), styles["body"],
                    ),
                ],
                [
                    Paragraph(
                        _contract_pdf_text(lines[index + 4]), styles["body"],
                    ),
                    Paragraph(
                        _contract_pdf_text(lines[index + 5]), styles["body"],
                    ),
                ],
                [
                    Paragraph(
                        _contract_pdf_text(lines[index + 6]), styles["body"],
                    ),
                    Paragraph(
                        _contract_pdf_text(lines[index + 7]), styles["body"],
                    ),
                ],
            ]
            signature_table = Table(
                signature_rows,
                colWidths=[usable_width / 2, usable_width / 2],
            )
            signature_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), navy),
                ("BOX", (0, 0), (-1, -1), 0.7, rule),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, rule),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]))
            story.extend([
                PageBreak(),
                Spacer(1, 20 * mm),
                signature_table,
                Spacer(1, 4 * mm),
            ])
            index += 8
            continue
        if (
            current_section == "07"
            and line == "VEHICLE ASSIGNED"
            and index + 11 < len(lines)
            and lines[index + 1] == "REGISTRATION"
            and lines[index + 2] == "HANDOVER DATE/TIME"
            and lines[index + 6] == "FINAL AGREEMENT / FILE NO."
            and lines[index + 7] == "APPROVED BY"
            and lines[index + 8] == "STATUS"
        ):
            flush_body()
            flush_summary()
            office_rows: list[list[Paragraph]] = []
            for row_index in (0, 3, 6, 9):
                row_style = "label" if row_index in {0, 6} else "body"
                office_rows.append([
                    Paragraph(
                        _contract_pdf_text(lines[index + row_index + column]),
                        styles[row_style],
                    )
                    for column in range(3)
                ])
            office_table = Table(
                office_rows,
                colWidths=[usable_width / 3] * 3,
            )
            office_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), pale_blue),
                ("BACKGROUND", (0, 2), (-1, 2), pale_blue),
                ("BOX", (0, 0), (-1, -1), 0.7, rule),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, rule),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]))
            story.extend([
                CondPageBreak(48 * mm),
                office_table,
                Spacer(1, 4 * mm),
            ])
            index += 12
            continue
        if current_section in {"01", "02"} and _contract_is_label(line):
            flush_body()
            if index + 1 < len(lines):
                summary_rows.append((line, lines[index + 1]))
                index += 2
                continue
        if re.match(r"^\d+\.\s+\S", line):
            flush_body()
            flush_summary()
            story.append(Paragraph(_contract_pdf_text(line), styles["clause"]))
            index += 1
            continue
        if _contract_is_label(line):
            flush_body()
            flush_summary()
            story.extend([
                Paragraph(_contract_pdf_text(line), styles["label"]),
                Spacer(1, 1.2 * mm),
            ])
            index += 1
            continue
        if current_section == "05":
            flush_body()
            flush_summary()
            if not checklist_intro_rendered:
                story.append(Paragraph(_contract_pdf_text(line), styles["body"]))
                checklist_intro_rendered = True
            else:
                story.append(Paragraph(
                    _contract_pdf_text(line), styles["bullet"], bulletText="•",
                ))
            index += 1
            continue
        body_buffer.append(line)
        index += 1

    flush_body()
    flush_summary()
    if audit_lines:
        audit_content = [
            Paragraph("Document audit", styles["label"]),
            *[
                Paragraph(_contract_pdf_text(line), styles["audit"])
                for line in audit_lines
            ],
        ]
        audit = Table([[audit_content]], colWidths=[usable_width])
        audit.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), pale_blue),
            ("BOX", (0, 0), (-1, -1), 0.5, rule),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.extend([Spacer(1, 4 * mm), audit])

    def decorate(page_canvas, doc) -> None:
        page_canvas.saveState()
        width, height = A4
        page_canvas.setStrokeColor(gold)
        page_canvas.setLineWidth(2)
        page_canvas.line(18 * mm, height - 15 * mm, 42 * mm, height - 15 * mm)
        page_canvas.setFillColor(navy)
        page_canvas.setFont("Helvetica-Bold", 8)
        page_canvas.drawString(
            18 * mm, height - 11.5 * mm, "ALI CAR RENTAL · CURAÇAO",
        )
        page_canvas.setFillColor(blue_gray)
        page_canvas.setFont("Helvetica", 7.5)
        page_canvas.drawRightString(
            width - 18 * mm, height - 11.5 * mm,
            "VEHICLE RENTAL PRE-CONTRACT",
        )
        page_canvas.setStrokeColor(rule)
        page_canvas.setLineWidth(0.5)
        page_canvas.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm)
        page_canvas.setFillColor(blue_gray)
        page_canvas.drawString(
            18 * mm, 8.5 * mm, "Confidential customer document",
        )
        page_canvas.drawRightString(
            width - 18 * mm, 8.5 * mm, f"Page {doc.page}",
        )
        page_canvas.restoreState()

    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return output.getvalue()


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
                {
                    "quote_snapshot_id": case["quote_snapshot_id"],
                    "text": contract_text,
                    "render_version": CONTRACT_RENDER_VERSION,
                },
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
            unsigned = _contract_pdf(
                "Ali Car Rental pre-contract",
                contract_text,
                [
                    f"Contract version: {settings['contract_template_version']}",
                    f"Snapshot hash: {snapshot_hash}",
                ],
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
            "url": f"{_public_base_url()}/r/{token}",
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
            result = _safe_contract(contract)
            from agents.social import ali_reservation_v2_automation
            result["automationV2"] = (
                ali_reservation_v2_automation.after_contract_signed(
                    str(token_row["reservation_public_id"])
                )
            )
            return result
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
        output = _safe_contract(result)
        from agents.social import ali_reservation_v2_automation
        output["automationV2"] = (
            ali_reservation_v2_automation.after_contract_signed(
                str(token_row["reservation_public_id"])
            )
        )
        return output
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
    candidate = str(value or "").strip()
    if not candidate and settings.get("payment_mode") == "fixed_link":
        candidate = str(settings.get("default_payment_url") or "")
    return _validated_payment_url(
        candidate,
        _normalize_payment_domains(settings.get("payment_allowed_domains") or []),
    )


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
            "link_sent_at=NULL, expires_at=NULL, customer_reported_at=NULL, verified_at=NULL, "
            "verified_by=NULL, review_reason=NULL, updated_at=excluded.updated_at",
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
            return {
                "url": payment["payment_url"],
                "status": "link_sent",
                "expiresAt": payment["expires_at"],
            }
        timestamp_dt = _now()
        timestamp = _iso(timestamp_dt)
        expires_at = _iso(timestamp_dt + timedelta(hours=PAYMENT_WINDOW_HOURS))
        conn.execute(
            "UPDATE ali_reservation_payments SET link_sent_at = ?, expires_at = ?, "
            "updated_at = ? WHERE reservation_public_id = ?",
            (timestamp, expires_at, timestamp, public_id),
        )
        conn.execute(
            "UPDATE ali_reservations SET payment_status = 'link_sent', revision = revision + 1, updated_at = ? "
            "WHERE tenant_slug = ? AND public_id = ?",
            (timestamp, TENANT_SLUG, public_id),
        )
        reservation._event(
            conn, public_id, "payment_link_sent", str(case["status"]),
            "requirements_pending", "staff", actor_id,
            {
                "payment_domain": payment["payment_domain"],
                "validity_hours": PAYMENT_WINDOW_HOURS,
            },
        )
        conn.commit()
        return {
            "url": payment["payment_url"],
            "status": "link_sent",
            "expiresAt": expires_at,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _money_cents(value: object) -> int:
    amount = str(value or "")
    if not re.fullmatch(r"\d+(?:\.\d{2})", amount):
        raise reservation.AliReservationError(
            "reservation_payment_amount_missing", 409,
        )
    major, minor = amount.split(".", 1)
    return int(major) * 100 + int(minor)


def _reservation_deposit_percent(pricing: dict) -> int:
    raw = pricing.get("reservationDepositPercent")
    if (
        isinstance(raw, int)
        and not isinstance(raw, bool)
        and 1 <= raw <= 100
    ):
        return raw
    rental_cents = _money_cents(
        (pricing.get("rentalTotal") or {}).get("amount"),
    )
    deposit_cents = _money_cents(
        (pricing.get("reservationDeposit") or {}).get("amount"),
    )
    matches = [
        percent
        for percent in range(1, 101)
        if (rental_cents * percent + 50) // 100 == deposit_cents
    ]
    if len(matches) != 1:
        raise reservation.AliReservationError(
            "reservation_payment_percent_missing", 409,
        )
    return matches[0]


def payment_delivery_payload(public_id: str) -> dict:
    """Return the configured URL only to the server-side delivery adapter."""
    ensure_schema()
    conn = _connection()
    try:
        case = _available_case(conn, public_id)
        payment = conn.execute(
            "SELECT payment_url FROM ali_reservation_payments WHERE tenant_slug = ? "
            "AND reservation_public_id = ?",
            (TENANT_SLUG, public_id),
        ).fetchone()
        if not payment or not payment["payment_url"]:
            raise reservation.AliReservationError("payment_link_not_configured", 409)
        snapshot = _quote_snapshot(conn, case)
        amount = str(
            (snapshot["pricing"].get("reservationDeposit") or {}).get("amount")
            or ""
        )
        if not re.fullmatch(r"\d+(?:\.\d{2})", amount):
            raise reservation.AliReservationError("reservation_payment_amount_missing", 409)
        return {
            "url": str(payment["payment_url"]),
            "amount": amount,
            "percent": _reservation_deposit_percent(snapshot["pricing"]),
            "validityHours": PAYMENT_WINDOW_HOURS,
        }
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
        payment = conn.execute(
            "SELECT expires_at FROM ali_reservation_payments WHERE tenant_slug = ? "
            "AND reservation_public_id = ?",
            (TENANT_SLUG, row["public_id"]),
        ).fetchone()
        expires_at = str(payment["expires_at"] or "") if payment else ""
        try:
            expired = bool(expires_at) and _now() >= datetime.fromisoformat(
                expires_at.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except ValueError:
            expired = True
        if expired:
            conn.execute(
                "UPDATE ali_reservations SET payment_status = 'expired', "
                "revision = revision + 1, updated_at = ? WHERE tenant_slug = ? "
                "AND public_id = ?",
                (timestamp, TENANT_SLUG, row["public_id"]),
            )
            reservation._event(
                conn, row["public_id"], "payment_window_expired",
                str(row["status"]), "requirements_pending", "system",
                "payment_window", {"validity_hours": PAYMENT_WINDOW_HOURS},
            )
            conn.commit()
            raise reservation.AliReservationError(
                "payment_window_expired", 409,
            )
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
    reason: str = "",
) -> dict:
    if decision not in {"verified", "rejected", "not_required"}:
        raise reservation.AliReservationError("invalid_payment_decision", 422)
    actor_id = reservation._validate_actor(actor)
    review_reason = str(reason or "").strip()
    if len(review_reason) > 500:
        raise reservation.AliReservationError("invalid_payment_review_reason", 422)
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        case = _available_case(conn, public_id)
        reservation._check_revision(case, expected_revision)
        if decision == "verified" and case["payment_status"] not in {"customer_reports_paid", "link_sent"}:
            raise reservation.AliReservationError("payment_verification_not_expected", 409)
        override = (
            decision in {"rejected", "not_required"}
            or (
                decision == "verified"
                and case["payment_status"] != "customer_reports_paid"
            )
        )
        from agents.social import ali_reservation_v2
        if ali_reservation_v2.enabled() and override and not review_reason:
            raise reservation.AliReservationError("payment_review_reason_required", 422)
        timestamp = _iso()
        conn.execute(
            "UPDATE ali_reservations SET payment_status = ? WHERE tenant_slug = ? AND public_id = ?",
            (decision, TENANT_SLUG, public_id),
        )
        conn.execute(
            "INSERT INTO ali_reservation_payments (reservation_public_id, tenant_slug, "
            "verified_at, verified_by, review_reason, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(reservation_public_id) DO UPDATE SET "
            "verified_at=excluded.verified_at, verified_by=excluded.verified_by, "
            "review_reason=excluded.review_reason, updated_at=excluded.updated_at",
            (
                public_id, TENANT_SLUG, timestamp, actor_id,
                review_reason or None, timestamp,
            ),
        )
        updated = _refresh_case(conn, public_id, actor_id)
        reservation._event(
            conn, public_id, "payment_reviewed", str(case["status"]),
            str(updated["status"]), "staff", actor_id,
            {
                "decision": decision,
                "override": override,
                "reason_present": bool(review_reason),
            },
        )
        conn.commit()
        result = reservation._public_row(updated)
        from agents.social import ali_reservation_v2_automation
        result["automationV2"] = ali_reservation_v2_automation.after_payment_review(
            public_id, decision,
        )
        return result
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
    settings = _runtime_config()
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
        dossier_audit = conn.execute(
            "SELECT status, version, created_at FROM ali_reservation_dossier_audits "
            "WHERE tenant_slug = ? AND reservation_public_id = ? "
            "ORDER BY version DESC LIMIT 1",
            (TENANT_SLUG, public_id),
        ).fetchone()
        value["dossier_review_status"] = (
            str(dossier_audit["status"]) if dossier_audit else "not_generated"
        )
        value["dossier_ready_for_approval"] = bool(
            dossier_audit and dossier_audit["status"] == "ready_for_review"
        )
        value["payment"] = {
            "status": case["payment_status"],
            "mode": str(settings.get("payment_mode") or "per_reservation"),
            "providerName": str(settings.get("payment_provider_name") or ""),
            "tenantDefaultAvailable": bool(settings.get("default_payment_url")),
            "tenantDefaultDomain": str(settings.get("default_payment_domain") or "") or None,
            "domain": payment["payment_domain"] if payment else None,
            "reference": payment["payment_reference"] if payment else None,
            "linkSentAt": payment["link_sent_at"] if payment else None,
            "expiresAt": payment["expires_at"] if payment else None,
            "customerReportedAt": payment["customer_reported_at"] if payment else None,
            "verifiedAt": payment["verified_at"] if payment else None,
            "verifiedBy": payment["verified_by"] if payment else None,
            "reviewReason": payment["review_reason"] if payment else None,
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
            and value["dossier_ready_for_approval"]
        )
        from agents.social import ali_reservation_v2
        if ali_reservation_v2.enabled():
            value["workflow_v2"] = ali_reservation_v2.get_case(public_id)
            value["prepayment_review"] = prepayment_review_summary(public_id)
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
            f"[{'x' if case['original_license_inspected_at'] else ' '}] Original licence inspected",
            f"[{'x' if case['original_identity_inspected_at'] else ' '}] Original ID inspected",
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
        storage_name = _write_private(data, ".pdf", public_id)
        version_row = conn.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM ali_reservation_dossier_audits "
            "WHERE tenant_slug = ? AND reservation_public_id = ?",
            (TENANT_SLUG, public_id),
        ).fetchone(); version = int(version_row[0])
        created = _iso()
        conn.execute(
            "INSERT INTO ali_reservation_dossier_audits (reservation_public_id, tenant_slug, version, "
            "status, content_sha256, page_count, page_size, actor_id, storage_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (public_id, TENANT_SLUG, version, dossier_status, digest, len(writer.pages), page_size, actor_id, storage_name, created),
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
