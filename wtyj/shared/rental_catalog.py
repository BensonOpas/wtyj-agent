"""Tenant-scoped draft and immutable published rental catalogs.

FRD-005 deliberately keeps the commercial catalog as one validated document.
The tenant container remains the storage boundary, while every row also carries
the effective tenant slug as a defence-in-depth guard.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import unicodedata
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from shared import state_registry


_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


class _StrictModel(BaseModel):
    model_config = {"extra": "forbid", "strict": True}


def _validate_id(value: str) -> str:
    if not _ID_PATTERN.fullmatch(value):
        raise ValueError("must be a stable opaque identifier")
    return value


class RentalSettings(_StrictModel):
    currency: str
    quoteValidityHours: int = Field(ge=1, le=720)
    staffQuoteEmail: str
    customerDeliveryDelaySeconds: int = Field(ge=0, le=1800)
    availabilityMode: Literal["request_only"] = "request_only"
    availabilityCopy: str = Field(min_length=1, max_length=240)
    quoteFooter: str = Field(default="", max_length=500)
    pdfLogoAssetId: str | None = None
    refundableSecurityDepositId: str = "refundable-security-deposit"
    refundableSecurityDepositCents: int = Field(ge=0)
    reservationDepositPercent: int = Field(default=0, ge=0, le=100)

    @field_validator("currency")
    @classmethod
    def currency_is_iso_code(cls, value: str) -> str:
        if not _CURRENCY_PATTERN.fullmatch(value):
            raise ValueError("must be an uppercase ISO 4217 code")
        return value

    @field_validator("staffQuoteEmail")
    @classmethod
    def email_is_valid(cls, value: str) -> str:
        if not _EMAIL_PATTERN.fullmatch(value):
            raise ValueError("must be a valid email address")
        return value

    @field_validator("pdfLogoAssetId")
    @classmethod
    def logo_id_is_valid(cls, value: str | None) -> str | None:
        return _validate_id(value) if value is not None else None

    _deposit_id_is_valid = field_validator("refundableSecurityDepositId")(_validate_id)


class VehicleCategory(_StrictModel):
    id: str
    name: str = Field(min_length=1, max_length=80)
    dailyRateCents: int = Field(ge=0)
    active: bool
    displayOrder: int = Field(ge=0)
    archivedAt: str | None = None

    _id_is_valid = field_validator("id")(_validate_id)


class RentalCar(_StrictModel):
    id: str
    displayName: str = Field(min_length=1, max_length=120)
    categoryId: str
    seats: int = Field(ge=1, le=20)
    luggageCapacity: int = Field(default=0, ge=0, le=20)
    transmission: Literal["automatic", "manual"]
    primaryImageAssetId: str | None = None
    active: bool
    displayOrder: int = Field(ge=0)
    archivedAt: str | None = None

    _id_is_valid = field_validator("id")(_validate_id)
    _category_id_is_valid = field_validator("categoryId")(_validate_id)

    @field_validator("primaryImageAssetId")
    @classmethod
    def image_id_is_valid(cls, value: str | None) -> str | None:
        return _validate_id(value) if value is not None else None


class RentalSupplement(_StrictModel):
    id: str
    name: str = Field(min_length=1, max_length=80)
    priceCents: int = Field(ge=0)
    billingBasis: Literal["per_day", "per_rental"]
    quantitySelectable: bool
    maxQuantity: int = Field(ge=1, le=20)
    active: bool
    displayOrder: int = Field(ge=0)
    archivedAt: str | None = None

    _id_is_valid = field_validator("id")(_validate_id)

    @model_validator(mode="after")
    def fixed_quantity_has_limit_one(self):
        if not self.quantitySelectable and self.maxQuantity != 1:
            raise ValueError("maxQuantity must be 1 when quantity is not selectable")
        return self


class RentalCatalogDocument(_StrictModel):
    settings: RentalSettings
    categories: list[VehicleCategory]
    cars: list[RentalCar]
    supplements: list[RentalSupplement]


class PreviewSupplementSelection(_StrictModel):
    id: str
    quantity: int = Field(ge=1, le=20)

    _id_is_valid = field_validator("id")(_validate_id)


class PreviewScenario(_StrictModel):
    rentalStart: str
    rentalEnd: str
    carId: str | None = None
    categoryId: str | None = None
    supplements: list[PreviewSupplementSelection] = Field(default_factory=list)
    locale: Literal["en", "nl", "pap", "de"] = "en"

    @field_validator("carId", "categoryId")
    @classmethod
    def selection_id_is_valid(cls, value: str | None) -> str | None:
        return _validate_id(value) if value is not None else None

    @field_validator("rentalStart", "rentalEnd")
    @classmethod
    def date_is_iso(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("must be an ISO date") from exc
        if parsed.isoformat() != value:
            raise ValueError("must be an ISO date")
        return value

    @model_validator(mode="after")
    def exactly_one_selection(self):
        if (self.carId is None) == (self.categoryId is None):
            raise ValueError("exactly one of carId or categoryId is required")
        if date.fromisoformat(self.rentalEnd) < date.fromisoformat(self.rentalStart):
            raise ValueError("rentalEnd must be on or after rentalStart")
        return self


@dataclass(frozen=True)
class ValidationResult:
    document: dict | None
    errors: list[dict]
    warnings: list[dict]

    @property
    def valid(self) -> bool:
        return not self.errors


class RentalCatalogError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 422, errors: list[dict] | None = None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.errors = errors or []


def empty_document() -> dict:
    return {
        "settings": {
            "currency": "USD",
            "quoteValidityHours": 72,
            "staffQuoteEmail": "operator@example.invalid",
            "customerDeliveryDelaySeconds": 180,
            "availabilityMode": "request_only",
            "availabilityCopy": "Availability requires staff confirmation.",
            "quoteFooter": "",
            "pdfLogoAssetId": None,
            "refundableSecurityDepositId": "refundable-security-deposit",
            "refundableSecurityDepositCents": 0,
            "reservationDepositPercent": 0,
        },
        "categories": [],
        "cars": [],
        "supplements": [],
    }


def _error(path: str, code: str, message: str) -> dict:
    return {"path": path, "code": code, "message": message}


def validate_document(
    raw: object,
    *,
    for_publish: bool = False,
    media_exists: Callable[[str], bool] | None = None,
) -> ValidationResult:
    try:
        model = RentalCatalogDocument.model_validate(raw)
    except ValidationError as exc:
        errors = []
        for issue in exc.errors(include_url=False, include_input=False):
            location = ".".join(str(part) for part in issue.get("loc", ()))
            errors.append(_error(location, str(issue.get("type") or "invalid"), issue["msg"]))
        return ValidationResult(None, errors, [])

    document = model.model_dump(mode="json")
    errors: list[dict] = []
    warnings: list[dict] = []
    category_ids: set[str] = set()
    car_ids: set[str] = set()
    supplement_ids: set[str] = set()

    for index, category in enumerate(model.categories):
        if category.id in category_ids:
            errors.append(_error(f"categories.{index}.id", "duplicate_id", "category ID must be unique"))
        category_ids.add(category.id)

    categories = {item.id: item for item in model.categories}
    for index, car in enumerate(model.cars):
        if car.id in car_ids:
            errors.append(_error(f"cars.{index}.id", "duplicate_id", "car ID must be unique"))
        car_ids.add(car.id)
        category = categories.get(car.categoryId)
        if category is None:
            errors.append(_error(f"cars.{index}.categoryId", "unknown_category", "category does not exist"))
        elif car.active and (not category.active or category.archivedAt is not None):
            errors.append(_error(f"cars.{index}.categoryId", "inactive_category", "active car requires an active category"))
        if car.active and car.archivedAt is not None:
            errors.append(_error(f"cars.{index}.active", "archived_active", "archived car cannot be active"))

    for index, category in enumerate(model.categories):
        if category.archivedAt is not None and any(
            car.active and car.categoryId == category.id for car in model.cars
        ):
            errors.append(_error(f"categories.{index}.archivedAt", "category_in_use", "category is used by an active car"))

    for index, supplement in enumerate(model.supplements):
        if supplement.id in supplement_ids:
            errors.append(_error(f"supplements.{index}.id", "duplicate_id", "supplement ID must be unique"))
        supplement_ids.add(supplement.id)
        if supplement.active and supplement.archivedAt is not None:
            errors.append(_error(f"supplements.{index}.active", "archived_active", "archived supplement cannot be active"))

    referenced_media = [
        (f"cars.{index}.primaryImageAssetId", car.primaryImageAssetId)
        for index, car in enumerate(model.cars)
        if car.primaryImageAssetId is not None
    ]
    if model.settings.pdfLogoAssetId is not None:
        referenced_media.append(("settings.pdfLogoAssetId", model.settings.pdfLogoAssetId))
    if media_exists is not None:
        for path, asset_id in referenced_media:
            if not media_exists(str(asset_id)):
                errors.append(_error(path, "missing_media", "referenced tenant media is unavailable"))

    if for_publish:
        if not any(item.active and item.archivedAt is None for item in model.categories):
            errors.append(_error("categories", "no_active_categories", "at least one active category is required"))
        if not any(item.active and item.archivedAt is None for item in model.cars):
            errors.append(_error("cars", "no_active_cars", "at least one active car is required"))
    elif not model.cars:
        warnings.append(_error("cars", "empty_fleet", "add a car before publishing"))

    return ValidationResult(document, errors, warnings)


def canonical_json(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(document: dict) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path or state_registry.DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def ensure_schema(db_path: str | None = None) -> None:
    connection = _connect(db_path)
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS rental_catalog_drafts (
            tenant_slug TEXT PRIMARY KEY,
            revision INTEGER NOT NULL,
            document_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rental_catalog_versions (
            tenant_slug TEXT NOT NULL,
            version INTEGER NOT NULL,
            document_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('publish', 'rollback')),
            actor TEXT NOT NULL,
            created_at TEXT NOT NULL,
            source_version INTEGER,
            idempotency_key TEXT NOT NULL,
            PRIMARY KEY (tenant_slug, version),
            UNIQUE (tenant_slug, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS rental_catalog_current (
            tenant_slug TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            FOREIGN KEY (tenant_slug, version)
                REFERENCES rental_catalog_versions(tenant_slug, version)
        );
        CREATE TABLE IF NOT EXISTS rental_quote_snapshots (
            tenant_slug TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            catalog_version INTEGER NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (tenant_slug, idempotency_key),
            FOREIGN KEY (tenant_slug, catalog_version)
                REFERENCES rental_catalog_versions(tenant_slug, version)
        );
        """
    )
    connection.commit()
    connection.close()


def _tenant(value: str) -> str:
    tenant = str(value or "").strip().lower()
    if not _ID_PATTERN.fullmatch(tenant):
        raise RentalCatalogError("invalid_tenant", status_code=404)
    return tenant


def _published_version(connection: sqlite3.Connection, tenant: str) -> int | None:
    row = connection.execute(
        "SELECT version FROM rental_catalog_current WHERE tenant_slug = ?", (tenant,)
    ).fetchone()
    return int(row["version"]) if row else None


def get_draft(tenant_slug: str, *, db_path: str | None = None) -> dict:
    tenant = _tenant(tenant_slug)
    ensure_schema(db_path)
    connection = _connect(db_path)
    row = connection.execute(
        "SELECT revision, document_json, updated_at, updated_by "
        "FROM rental_catalog_drafts WHERE tenant_slug = ?",
        (tenant,),
    ).fetchone()
    published_version = _published_version(connection, tenant)
    connection.close()
    if row is None:
        return {
            "tenantSlug": tenant,
            "revision": 0,
            "currentPublishedVersion": published_version,
            "document": empty_document(),
            "updatedAt": None,
            "updatedBy": None,
        }
    return {
        "tenantSlug": tenant,
        "revision": int(row["revision"]),
        "currentPublishedVersion": published_version,
        "document": json.loads(row["document_json"]),
        "updatedAt": row["updated_at"],
        "updatedBy": row["updated_by"],
    }


def save_draft(
    tenant_slug: str,
    raw_document: object,
    *,
    expected_revision: int,
    actor: str,
    db_path: str | None = None,
) -> dict:
    tenant = _tenant(tenant_slug)
    validation = validate_document(raw_document)
    if not validation.valid:
        raise RentalCatalogError("invalid_draft", errors=validation.errors)
    ensure_schema(db_path)
    connection = _connect(db_path)
    connection.isolation_level = None
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT revision FROM rental_catalog_drafts WHERE tenant_slug = ?", (tenant,)
        ).fetchone()
        current_revision = int(row["revision"]) if row else 0
        if expected_revision != current_revision:
            raise RentalCatalogError("stale_revision", status_code=409)
        revision = current_revision + 1
        connection.execute(
            "INSERT INTO rental_catalog_drafts "
            "(tenant_slug, revision, document_json, updated_at, updated_by) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(tenant_slug) DO UPDATE SET revision=excluded.revision, "
            "document_json=excluded.document_json, updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (tenant, revision, canonical_json(validation.document), now, actor),
        )
        connection.execute("COMMIT")
        return {
            "tenantSlug": tenant,
            "revision": revision,
            "currentPublishedVersion": _published_version(connection, tenant),
            "document": validation.document,
            "updatedAt": now,
            "updatedBy": actor,
        }
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def _version_result(row: sqlite3.Row, *, current: bool = True) -> dict:
    return {
        "tenantSlug": row["tenant_slug"],
        "version": int(row["version"]),
        "contentHash": row["content_hash"],
        "action": row["action"],
        "actor": row["actor"],
        "createdAt": row["created_at"],
        "sourceVersion": row["source_version"],
        "current": current,
        "document": json.loads(row["document_json"]),
    }


def _version_idempotency_key(action: str, key: str) -> str:
    """Namespace new catalog-version operations without breaking old replays."""
    # Slash is deliberately outside the accepted caller-key alphabet, so an
    # older raw key can never masquerade as a newly scoped operation key.
    return f"rental-version/v1/{action}/{key}"


def _find_version_replay(
    connection: sqlite3.Connection,
    tenant: str,
    action: str,
    key: str,
) -> sqlite3.Row | None:
    scoped_key = _version_idempotency_key(action, key)
    existing = connection.execute(
        "SELECT * FROM rental_catalog_versions "
        "WHERE tenant_slug = ? AND idempotency_key = ?",
        (tenant, scoped_key),
    ).fetchone()
    if existing is not None:
        return existing
    legacy = connection.execute(
        "SELECT * FROM rental_catalog_versions "
        "WHERE tenant_slug = ? AND idempotency_key = ?",
        (tenant, key),
    ).fetchone()
    if legacy is not None and legacy["action"] == action:
        return legacy
    return None


def publish(
    tenant_slug: str,
    *,
    expected_revision: int,
    idempotency_key: str,
    actor: str,
    media_exists: Callable[[str], bool] | None = None,
    db_path: str | None = None,
) -> dict:
    tenant = _tenant(tenant_slug)
    key = _validate_id(idempotency_key)
    ensure_schema(db_path)
    connection = _connect(db_path)
    connection.isolation_level = None
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = _find_version_replay(connection, tenant, "publish", key)
        if existing is not None:
            connection.execute("COMMIT")
            return _version_result(existing, current=_published_version(connection, tenant) == int(existing["version"]))
        draft = connection.execute(
            "SELECT revision, document_json FROM rental_catalog_drafts WHERE tenant_slug = ?", (tenant,)
        ).fetchone()
        if draft is None:
            raise RentalCatalogError("draft_not_found", status_code=404)
        if int(draft["revision"]) != expected_revision:
            raise RentalCatalogError("stale_revision", status_code=409)
        validation = validate_document(
            json.loads(draft["document_json"]), for_publish=True, media_exists=media_exists
        )
        if not validation.valid:
            raise RentalCatalogError("invalid_publish", errors=validation.errors)
        next_version_row = connection.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS value FROM rental_catalog_versions WHERE tenant_slug = ?",
            (tenant,),
        ).fetchone()
        version = int(next_version_row["value"])
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        serialized = canonical_json(validation.document)
        digest = content_hash(validation.document)
        connection.execute(
            "INSERT INTO rental_catalog_versions "
            "(tenant_slug, version, document_json, content_hash, action, actor, created_at, source_version, idempotency_key) "
            "VALUES (?, ?, ?, ?, 'publish', ?, ?, NULL, ?)",
            (
                tenant,
                version,
                serialized,
                digest,
                actor,
                now,
                _version_idempotency_key("publish", key),
            ),
        )
        connection.execute(
            "INSERT INTO rental_catalog_current (tenant_slug, version) VALUES (?, ?) "
            "ON CONFLICT(tenant_slug) DO UPDATE SET version=excluded.version",
            (tenant, version),
        )
        row = connection.execute(
            "SELECT * FROM rental_catalog_versions WHERE tenant_slug = ? AND version = ?",
            (tenant, version),
        ).fetchone()
        connection.execute("COMMIT")
        return _version_result(row)
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def rollback(
    tenant_slug: str,
    *,
    expected_current_version: int,
    idempotency_key: str,
    actor: str,
    db_path: str | None = None,
) -> dict:
    tenant = _tenant(tenant_slug)
    key = _validate_id(idempotency_key)
    ensure_schema(db_path)
    connection = _connect(db_path)
    connection.isolation_level = None
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = _find_version_replay(connection, tenant, "rollback", key)
        if existing is not None:
            connection.execute("COMMIT")
            return _version_result(existing, current=_published_version(connection, tenant) == int(existing["version"]))
        current = _published_version(connection, tenant)
        if current is None:
            raise RentalCatalogError("published_catalog_not_found", status_code=404)
        if current != expected_current_version:
            raise RentalCatalogError("stale_published_version", status_code=409)
        source = connection.execute(
            "SELECT * FROM rental_catalog_versions WHERE tenant_slug = ? AND version < ? "
            "ORDER BY version DESC LIMIT 1",
            (tenant, current),
        ).fetchone()
        if source is None:
            raise RentalCatalogError("rollback_version_not_found", status_code=409)
        next_version = int(connection.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS value FROM rental_catalog_versions WHERE tenant_slug = ?",
            (tenant,),
        ).fetchone()["value"])
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        connection.execute(
            "INSERT INTO rental_catalog_versions "
            "(tenant_slug, version, document_json, content_hash, action, actor, created_at, source_version, idempotency_key) "
            "VALUES (?, ?, ?, ?, 'rollback', ?, ?, ?, ?)",
            (
                tenant,
                next_version,
                source["document_json"],
                source["content_hash"],
                actor,
                now,
                int(source["version"]),
                _version_idempotency_key("rollback", key),
            ),
        )
        connection.execute(
            "UPDATE rental_catalog_current SET version = ? WHERE tenant_slug = ?",
            (next_version, tenant),
        )
        draft_row = connection.execute(
            "SELECT revision FROM rental_catalog_drafts WHERE tenant_slug = ?", (tenant,)
        ).fetchone()
        new_revision = (int(draft_row["revision"]) if draft_row else 0) + 1
        connection.execute(
            "INSERT INTO rental_catalog_drafts "
            "(tenant_slug, revision, document_json, updated_at, updated_by) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(tenant_slug) DO UPDATE SET revision=excluded.revision, "
            "document_json=excluded.document_json, updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (tenant, new_revision, source["document_json"], now, actor),
        )
        row = connection.execute(
            "SELECT * FROM rental_catalog_versions WHERE tenant_slug = ? AND version = ?",
            (tenant, next_version),
        ).fetchone()
        connection.execute("COMMIT")
        result = _version_result(row)
        result["draftRevision"] = new_revision
        return result
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def get_published(tenant_slug: str, *, db_path: str | None = None) -> dict | None:
    tenant = _tenant(tenant_slug)
    ensure_schema(db_path)
    connection = _connect(db_path)
    row = connection.execute(
        "SELECT versions.* FROM rental_catalog_current current "
        "JOIN rental_catalog_versions versions ON versions.tenant_slug = current.tenant_slug "
        "AND versions.version = current.version WHERE current.tenant_slug = ?",
        (tenant,),
    ).fetchone()
    connection.close()
    return _version_result(row) if row is not None else None


def media_reference_count(
    tenant_slug: str,
    asset_id: str,
    *,
    db_path: str | None = None,
) -> int:
    """Count draft/version references so immutable media cannot be deleted."""
    tenant = _tenant(tenant_slug)
    target = _validate_id(asset_id)
    ensure_schema(db_path)
    connection = _connect(db_path)
    rows = connection.execute(
        "SELECT document_json FROM rental_catalog_drafts WHERE tenant_slug = ? "
        "UNION ALL SELECT document_json FROM rental_catalog_versions WHERE tenant_slug = ?",
        (tenant, tenant),
    ).fetchall()
    connection.close()
    count = 0
    for row in rows:
        try:
            document = json.loads(row["document_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        settings = document.get("settings") if isinstance(document, dict) else {}
        if isinstance(settings, dict) and settings.get("pdfLogoAssetId") == target:
            count += 1
        for car in document.get("cars") or [] if isinstance(document, dict) else []:
            if isinstance(car, dict) and car.get("primaryImageAssetId") == target:
                count += 1
    return count


def _money(cents: int, currency: str) -> dict:
    whole, fraction = divmod(cents, 100)
    return {"currency": currency, "amount": f"{whole}.{fraction:02d}"}


def _public_slug(value: str, fallback: str) -> str:
    """Return the stable ASCII route slug expected by fleet consumers."""
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    candidate = normalized.encode("ascii", "ignore").decode("ascii").lower()
    candidate = re.sub(r"[^a-z0-9]+", "-", candidate).strip("-")
    if candidate:
        return candidate
    return re.sub(r"[^a-z0-9]+", "-", str(fallback).lower()).strip("-")


def _published_media(asset_id: str, tenant_slug: str) -> dict | None:
    """Resolve tenant-owned catalog media into the existing consumer shape."""
    try:
        photo = state_registry.get_photo_by_id(int(asset_id))
    except (TypeError, ValueError):
        return None
    if not isinstance(photo, dict):
        return None
    if not str(photo.get("service_key") or "").startswith("knowledge:rental_catalog:"):
        return None
    filename = str(photo.get("filename") or "")
    if not filename or filename != os.path.basename(filename):
        return None
    base = os.environ.get("PUBLIC_API_BASE_URL", "https://api.unboks.org").rstrip("/")
    url = (
        f"{base}/api/{urllib.parse.quote(tenant_slug)}/dashboard/api/public/media/"
        f"{urllib.parse.quote(filename)}"
    )
    tags = photo.get("tags") if isinstance(photo.get("tags"), list) else []
    alt = str(tags[0]).strip() if tags else ""
    return {"assetId": str(asset_id), "primary": True, "url": url, "alt": alt}


def consumer_catalog(tenant_slug: str, *, db_path: str | None = None) -> dict | None:
    """Project the current version into the existing Carlos catalog contract."""
    published = get_published(tenant_slug, db_path=db_path)
    if published is None:
        return None
    return _consumer_catalog_from_published(published, include_media_urls=True)


def _consumer_catalog_from_published(
    published: dict,
    *,
    include_media_urls: bool = False,
) -> dict:
    document = published["document"]
    settings = document["settings"]
    currency = settings["currency"]
    categories = {
        item["id"]: item for item in document["categories"]
        if item["active"] and item["archivedAt"] is None
    }
    vehicle_classes = []
    for item in sorted(categories.values(), key=lambda value: (value["displayOrder"], value["id"])):
        daily = int(item["dailyRateCents"])
        vehicle_classes.append({
            "id": item["id"],
            "name": item["name"],
            "dailyRate": _money(daily, currency),
            "weeklyRate": _money(daily * 7, currency),
            "displayOrder": item["displayOrder"],
        })
    vehicles = []
    for item in sorted(document["cars"], key=lambda value: (value["displayOrder"], value["id"])):
        category = categories.get(item["categoryId"])
        if not item["active"] or item["archivedAt"] is not None or category is None:
            continue
        daily = int(category["dailyRateCents"])
        image = None
        if item["primaryImageAssetId"] is not None:
            image = (
                _published_media(item["primaryImageAssetId"], published["tenantSlug"])
                if include_media_urls
                else {"assetId": item["primaryImageAssetId"], "primary": True}
            )
        vehicles.append({
            "id": item["id"],
            "classId": category["id"],
            "name": item["displayName"],
            "slug": _public_slug(item["displayName"], item["id"]),
            "seats": item["seats"],
            "luggageCapacity": item["luggageCapacity"],
            "transmission": item["transmission"],
            "dailyRate": _money(daily, currency),
            "weeklyRate": _money(daily * 7, currency),
            "images": [image] if image else [],
            "displayOrder": item["displayOrder"],
        })
    extras = []
    for item in sorted(document["supplements"], key=lambda value: (value["displayOrder"], value["id"])):
        if not item["active"] or item["archivedAt"] is not None:
            continue
        extras.append({
            "id": item["id"],
            "name": item["name"],
            "pricingUnit": "daily" if item["billingBasis"] == "per_day" else "rental",
            "billingBasis": item["billingBasis"],
            "price": _money(int(item["priceCents"]), currency),
            "quantitySelectable": item["quantitySelectable"],
            "maxQuantity": item["maxQuantity"],
            "displayOrder": item["displayOrder"],
        })
    deposit = int(settings["refundableSecurityDepositCents"])
    return {
        "tenantSlug": published["tenantSlug"],
        "catalogVersion": published["version"],
        "contentHash": published["contentHash"],
        "currency": currency,
        "availabilityMode": "request_only",
        "quoteValidityHours": settings["quoteValidityHours"],
        "customerDeliveryDelaySeconds": settings["customerDeliveryDelaySeconds"],
        "availabilityCopy": settings["availabilityCopy"],
        "quoteFooter": settings["quoteFooter"],
        "pdfLogoAssetId": settings["pdfLogoAssetId"],
        "reservationDepositPercent": settings["reservationDepositPercent"],
        "vehicleClasses": vehicle_classes,
        "vehicles": vehicles,
        "extras": extras,
        "charges": [{
            "id": settings["refundableSecurityDepositId"],
            "kind": "deposit",
            "name": "Refundable security deposit",
            "price": _money(deposit, currency),
            "refundable": True,
        }],
    }


def _validate_quote_request(raw: object) -> dict:
    if not isinstance(raw, dict) or set(raw) != {
        "rentalStart", "rentalEnd", "selection", "extraSelections", "chargeSelections",
    }:
        raise RentalCatalogError("invalid_quote_request")
    try:
        start = date.fromisoformat(raw["rentalStart"])
        end = date.fromisoformat(raw["rentalEnd"])
    except (TypeError, ValueError) as exc:
        raise RentalCatalogError("invalid_quote_dates") from exc
    rental_days = max(1, (end - start).days)
    if end < start or rental_days > 365:
        raise RentalCatalogError("invalid_quote_dates")
    selection = raw["selection"]
    if not isinstance(selection, dict) or len(selection) != 1:
        raise RentalCatalogError("invalid_quote_selection")
    selection_key = next(iter(selection), "")
    if selection_key not in {"vehicleId", "classId"}:
        raise RentalCatalogError("invalid_quote_selection")
    try:
        selection_id = _validate_id(selection[selection_key])
    except (TypeError, ValueError) as exc:
        raise RentalCatalogError("invalid_quote_selection") from exc
    extras = raw["extraSelections"]
    if not isinstance(extras, list) or len(extras) > 50:
        raise RentalCatalogError("invalid_quote_extras")
    normalized_extras = []
    seen_extras: set[str] = set()
    for item in extras:
        if isinstance(item, str):
            extra_id, quantity = item, 1
        elif isinstance(item, dict) and set(item) == {"id", "quantity"}:
            extra_id, quantity = item["id"], item["quantity"]
        else:
            raise RentalCatalogError("invalid_quote_extras")
        try:
            extra_id = _validate_id(extra_id)
        except (TypeError, ValueError) as exc:
            raise RentalCatalogError("invalid_quote_extras") from exc
        if (
            not isinstance(quantity, int) or isinstance(quantity, bool)
            or quantity < 1 or quantity > 20 or extra_id in seen_extras
        ):
            raise RentalCatalogError("invalid_quote_extras")
        seen_extras.add(extra_id)
        normalized_extras.append({"id": extra_id, "quantity": quantity})
    charges = raw["chargeSelections"]
    if not isinstance(charges, list) or len(charges) > 50:
        raise RentalCatalogError("invalid_quote_charges")
    try:
        normalized_charges = [_validate_id(item) for item in charges]
    except (TypeError, ValueError) as exc:
        raise RentalCatalogError("invalid_quote_charges") from exc
    if len(set(normalized_charges)) != len(normalized_charges):
        raise RentalCatalogError("invalid_quote_charges")
    return {
        "rentalStart": start.isoformat(),
        "rentalEnd": end.isoformat(),
        "rentalDays": rental_days,
        "selectionKey": selection_key,
        "selectionId": selection_id,
        "extraSelections": normalized_extras,
        "chargeSelections": normalized_charges,
    }


def _calculate_quote_response(
    contract: dict,
    request: dict,
    *,
    idempotency_key: str,
    created_at: datetime,
) -> dict:
    vehicles = contract["vehicles"]
    if request["selectionKey"] == "vehicleId":
        candidates = [item for item in vehicles if item["id"] == request["selectionId"]]
    else:
        candidates = [item for item in vehicles if item["classId"] == request["selectionId"]]
    if not candidates:
        raise RentalCatalogError("quote_selection_unavailable")
    vehicle = sorted(candidates, key=lambda item: item["id"])[0]
    rental_days = request["rentalDays"]
    daily_cents = int(vehicle["dailyRate"]["amount"].replace(".", ""))
    vehicle_total = daily_cents * rental_days
    items = [{
        "code": "vehicle.daily",
        "category": "vehicle",
        "description": f"{vehicle['name']} — daily rate",
        "quantity": rental_days,
        "refundable": False,
        "unitPrice": _money(daily_cents, contract["currency"]),
        "total": _money(vehicle_total, contract["currency"]),
    }]
    rental_total = vehicle_total
    extras = {item["id"]: item for item in contract["extras"]}
    for selection in request["extraSelections"]:
        extra = extras.get(selection["id"])
        if extra is None or selection["quantity"] > int(extra["maxQuantity"]):
            raise RentalCatalogError("quote_extra_unavailable")
        if not extra["quantitySelectable"] and selection["quantity"] != 1:
            raise RentalCatalogError("quote_extra_quantity_invalid")
        price_cents = int(extra["price"]["amount"].replace(".", ""))
        multiplier = selection["quantity"] * (
            rental_days if extra["billingBasis"] == "per_day" else 1
        )
        subtotal = price_cents * multiplier
        rental_total += subtotal
        items.append({
            "code": f"extra.{extra['billingBasis']}",
            "category": "extra",
            "description": extra["name"],
            "quantity": selection["quantity"],
            "refundable": False,
            "billingBasis": extra["billingBasis"],
            **({"rentalDays": rental_days} if extra["billingBasis"] == "per_day" else {}),
            "unitPrice": _money(price_cents, contract["currency"]),
            "total": _money(subtotal, contract["currency"]),
        })
    charges = {item["id"]: item for item in contract["charges"]}
    refundable_deposit = 0
    for charge_id in request["chargeSelections"]:
        charge = charges.get(charge_id)
        if charge is None:
            raise RentalCatalogError("quote_charge_unavailable")
        price_cents = int(charge["price"]["amount"].replace(".", ""))
        if charge["refundable"]:
            refundable_deposit += price_cents
        items.append({
            "code": f"charge.{charge['kind']}",
            "category": "security_deposit" if charge["refundable"] else "charge",
            "description": charge["name"],
            "quantity": 1,
            "refundable": charge["refundable"],
            "unitPrice": _money(price_cents, contract["currency"]),
            "total": _money(price_cents, contract["currency"]),
        })
    reservation_deposit = (
        rental_total * int(contract["reservationDepositPercent"]) + 50
    ) // 100
    reference_digest = hashlib.sha256(
        f"{contract['tenantSlug']}:{idempotency_key}".encode("utf-8")
    ).hexdigest()[:8].upper()
    reference_prefix = "ALI" if contract["tenantSlug"] == "ali-car-rental" else "RENTAL"
    created = created_at.astimezone(timezone.utc)
    quote_snapshot_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"unboks:rental:{contract['tenantSlug']}:{idempotency_key}",
    ))
    return {
        "quoteSnapshotId": quote_snapshot_id,
        "quoteReference": f"{reference_prefix}-{created:%Y%m%d}-{reference_digest}",
        "catalogVersion": contract["catalogVersion"],
        "catalogContentHash": contract["contentHash"],
        "availabilityMode": "request_only",
        "availabilityCopy": contract["availabilityCopy"],
        "quoteFooter": contract["quoteFooter"],
        "quoteValidityHours": contract["quoteValidityHours"],
        "currency": contract["currency"],
        "resolvedVehicleId": vehicle["id"],
        "rentalDays": rental_days,
        "items": items,
        "subtotal": _money(rental_total + refundable_deposit, contract["currency"]),
        "total": _money(rental_total + refundable_deposit, contract["currency"]),
        "rentalTotal": _money(rental_total, contract["currency"]),
        "refundableSecurityDeposit": _money(refundable_deposit, contract["currency"]),
        "reservationDeposit": _money(reservation_deposit, contract["currency"]),
        "reservationDepositPercent": int(contract["reservationDepositPercent"]),
        "createdAt": created.isoformat().replace("+00:00", "Z"),
        "expiresAt": (
            created + timedelta(hours=int(contract["quoteValidityHours"]))
        ).isoformat().replace("+00:00", "Z"),
    }


def create_quote_snapshot(
    tenant_slug: str,
    raw_request: object,
    *,
    idempotency_key: str,
    db_path: str | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict:
    tenant = _tenant(tenant_slug)
    key = _validate_id(idempotency_key)
    request = _validate_quote_request(raw_request)
    ensure_schema(db_path)
    connection = _connect(db_path)
    connection.isolation_level = None
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT response_json FROM rental_quote_snapshots "
            "WHERE tenant_slug = ? AND idempotency_key = ?",
            (tenant, key),
        ).fetchone()
        if existing is not None:
            connection.execute("COMMIT")
            return json.loads(existing["response_json"])
        current = connection.execute(
            "SELECT versions.* FROM rental_catalog_current current "
            "JOIN rental_catalog_versions versions ON versions.tenant_slug = current.tenant_slug "
            "AND versions.version = current.version WHERE current.tenant_slug = ?",
            (tenant,),
        ).fetchone()
        if current is None:
            raise RentalCatalogError("published_catalog_not_found", status_code=404)
        contract = _consumer_catalog_from_published(_version_result(current))
        created_at = (now or (lambda: datetime.now(timezone.utc)))()
        response = _calculate_quote_response(
            contract, request, idempotency_key=key, created_at=created_at
        )
        connection.execute(
            "INSERT INTO rental_quote_snapshots "
            "(tenant_slug, idempotency_key, catalog_version, response_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                tenant,
                key,
                int(response["catalogVersion"]),
                canonical_json(response),
                response["createdAt"],
            ),
        )
        connection.execute("COMMIT")
        return response
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def calculate_preview(raw_document: object, raw_scenario: object) -> dict:
    validation = validate_document(raw_document, for_publish=True)
    if not validation.valid:
        raise RentalCatalogError("invalid_preview_catalog", errors=validation.errors)
    try:
        scenario = PreviewScenario.model_validate(raw_scenario)
    except ValidationError as exc:
        errors = [
            _error(".".join(str(part) for part in issue.get("loc", ())), str(issue.get("type")), issue["msg"])
            for issue in exc.errors(include_url=False, include_input=False)
        ]
        raise RentalCatalogError("invalid_preview_scenario", errors=errors) from exc
    document = validation.document
    categories = {item["id"]: item for item in document["categories"] if item["active"] and item["archivedAt"] is None}
    cars = {item["id"]: item for item in document["cars"] if item["active"] and item["archivedAt"] is None}
    if scenario.carId is not None:
        car = cars.get(scenario.carId)
        if car is None:
            raise RentalCatalogError("inactive_or_unknown_car")
        category = categories.get(car["categoryId"])
        selection = {"carId": car["id"], "name": car["displayName"], "categoryId": category["id"]}
    else:
        category = categories.get(str(scenario.categoryId))
        if category is None:
            raise RentalCatalogError("inactive_or_unknown_category")
        selection = {"carId": None, "name": category["name"], "categoryId": category["id"]}
    rental_days = max(
        1,
        (date.fromisoformat(scenario.rentalEnd) - date.fromisoformat(scenario.rentalStart)).days,
    )
    rental_subtotal = int(category["dailyRateCents"]) * rental_days
    items = [{
        "kind": "rental",
        "id": category["id"],
        "name": selection["name"],
        "quantity": rental_days,
        "unitPriceCents": int(category["dailyRateCents"]),
        "subtotalCents": rental_subtotal,
    }]
    supplements_by_id = {
        item["id"]: item for item in document["supplements"]
        if item["active"] and item["archivedAt"] is None
    }
    seen: set[str] = set()
    supplement_total = 0
    for selected in scenario.supplements:
        if selected.id in seen:
            raise RentalCatalogError("duplicate_supplement_selection")
        seen.add(selected.id)
        supplement = supplements_by_id.get(selected.id)
        if supplement is None:
            raise RentalCatalogError("inactive_or_unknown_supplement")
        if selected.quantity > int(supplement["maxQuantity"]):
            raise RentalCatalogError("supplement_quantity_exceeded")
        if not supplement["quantitySelectable"] and selected.quantity != 1:
            raise RentalCatalogError("supplement_quantity_not_selectable")
        multiplier = rental_days if supplement["billingBasis"] == "per_day" else 1
        subtotal = int(supplement["priceCents"]) * selected.quantity * multiplier
        supplement_total += subtotal
        items.append({
            "kind": "supplement",
            "id": supplement["id"],
            "name": supplement["name"],
            "billingBasis": supplement["billingBasis"],
            "quantity": selected.quantity,
            "unitPriceCents": int(supplement["priceCents"]),
            "subtotalCents": subtotal,
        })
    deposit = int(document["settings"]["refundableSecurityDepositCents"])
    rental_total = rental_subtotal + supplement_total
    return {
        "currency": document["settings"]["currency"],
        "rentalDays": rental_days,
        "selection": selection,
        "items": items,
        "rentalTotalCents": rental_total,
        "refundableSecurityDepositCents": deposit,
        "grandTotalCents": rental_total + deposit,
        "availabilityMode": "request_only",
    }
