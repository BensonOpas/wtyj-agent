"""Tenant-isolated Ali WhatsApp-to-quote workflow.

This module owns only the confirmed-summary to delivery path. Ali receives a
strict pricing request with no customer or conversation data.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx

from agents.social.ali_quote_pdf import render_quote_pdf
from agents.social.ali_quote_presentation import format_rental_period
from shared import config_loader, state_registry

TENANT_SLUG = "ali-car-rental"
WORKFLOW_TYPE = "ali_quote"
LOCALES = {"en", "nl", "pap", "de"}
PENDING_STATUSES = ("confirmed", "pricing", "quoted", "pdf_ready", "delivering")
REQUIRED_RENTAL_FIELDS = {
    "rental_start", "rental_end", "pickup_location", "return_location",
    "driver_age", "conversation_language",
}
SELECTION_FIELDS = ("vehicle_id", "vehicle_class_id")
ALI_REQUEST_KEYS = {"rentalStart", "rentalEnd", "selection", "extraSelections", "chargeSelections"}
AFFIRMATIVE = {
    "yes", "correct", "looks good", "go ahead", "ja", "klopt", "akkoord",
    "ta bon", "correcto", "si", "stimmt", "passt", "ja stimmt",
}
NEGATION = {"no", "not", "nee", "niet", "no ta", "kein", "nicht", "aber", "but", "ma"}
_CATALOG_CACHE = {"expires_at": 0.0, "value": None}
_CATALOG_CACHE_SECONDS = 60.0
QUOTE_PROCESSING_DELAY_SECONDS = 3 * 60
_FORBIDDEN_CONTACT_REDIRECT = re.compile(
    r"(?:https?://)?wa\.me/|mailto:|tel:|[\w.+-]+@[\w.-]+\.[a-z]{2,}",
    flags=re.IGNORECASE,
)
_INTAKE_SAFETY_FALLBACK = {
    "en": "I couldn't complete that step safely. Please try again here in a moment.",
    "nl": "Ik kon die stap niet veilig afronden. Probeer het hier over een moment opnieuw.",
    "pap": "Mi no por a kompletá e paso ei na un manera sigur. Purba atrobe aki den un momentu.",
    "de": "Ich konnte diesen Schritt nicht sicher abschließen. Bitte versuchen Sie es gleich hier erneut.",
}


class AliQuoteError(RuntimeError):
    """Safe workflow error carrying only a machine-readable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def seconds_until_quote_processing(
    quote: dict,
    *,
    now: datetime | None = None,
    delay_seconds: int = QUOTE_PROCESSING_DELAY_SECONDS,
) -> float:
    """Return the remaining durable delay from the stored confirmation time."""
    try:
        confirmed_at = datetime.fromisoformat(
            str(quote["confirmed_at"]).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise AliQuoteError("invalid_confirmation_timestamp") from exc
    current = (now or _now()).astimezone(timezone.utc)
    eligible_at = confirmed_at + timedelta(seconds=max(0, int(delay_seconds)))
    return max(0.0, (eligible_at - current).total_seconds())


def tenant_configured(raw: dict | None = None) -> bool:
    raw = raw if raw is not None else (config_loader.get_raw() or {})
    slug = str(raw.get("slug") or (raw.get("business") or {}).get("slug") or "").strip().lower()
    return slug == TENANT_SLUG and (raw.get("workflow") or {}).get("type") == WORKFLOW_TYPE


def tenant_enabled(raw: dict | None = None) -> bool:
    """Master kill switch for Ali intake and quote processing."""
    raw = raw if raw is not None else (config_loader.get_raw() or {})
    return tenant_configured(raw) and feature_switches(raw)["automation"]


def feature_switches(raw: dict | None = None) -> dict[str, bool]:
    raw = raw if raw is not None else (config_loader.get_raw() or {})
    features = raw.get("features") or {}
    return {
        "automation": bool(features.get("ali_quote_automation", False)),
        "customer_delivery": bool(features.get("ali_quote_customer_delivery", False)),
        "staff_email": bool(features.get("ali_quote_staff_email", False)),
        "operator_alerts": bool(features.get("ali_quote_operator_alerts", False)),
    }


def validate_rental_fields(rental: dict) -> dict:
    if not isinstance(rental, dict):
        raise AliQuoteError("invalid_rental_fields")
    missing = [key for key in REQUIRED_RENTAL_FIELDS if rental.get(key) in (None, "")]
    selections = [key for key in SELECTION_FIELDS if rental.get(key)]
    if missing or len(selections) != 1:
        raise AliQuoteError("incomplete_rental_fields")
    try:
        start = datetime.strptime(str(rental["rental_start"]), "%Y-%m-%d").date()
        end = datetime.strptime(str(rental["rental_end"]), "%Y-%m-%d").date()
    except ValueError as exc:
        raise AliQuoteError("invalid_rental_period") from exc
    days = max(1, (end - start).days)
    if end < start or days > 365:
        raise AliQuoteError("invalid_rental_period")
    try:
        age = int(rental["driver_age"])
    except (TypeError, ValueError) as exc:
        raise AliQuoteError("invalid_driver_age") from exc
    if age < 15 or age > 110:
        raise AliQuoteError("invalid_driver_age")
    locale = str(rental["conversation_language"]).lower()
    if locale not in LOCALES:
        raise AliQuoteError("unsupported_locale")
    normalized = dict(rental)
    normalized["driver_age"] = age
    normalized["conversation_language"] = locale
    normalized["extra_ids"] = sorted(set(normalized.get("extra_ids") or []))
    return normalized


def normalized_summary(customer: dict, rental: dict, version: int = 1) -> tuple[dict, str]:
    if not isinstance(customer, dict) or not str(customer.get("name") or "").strip():
        raise AliQuoteError("missing_customer_name")
    if not str(customer.get("whatsapp") or "").strip():
        raise AliQuoteError("missing_conversation_whatsapp")
    rental = validate_rental_fields(rental)
    summary = {"version": version, "customer": customer, "rental": rental}
    return summary, hashlib.sha256(_json(summary).encode("utf-8")).hexdigest()


def is_unambiguous_confirmation(text: str) -> bool:
    normalized = " ".join(re.sub(r"[^\w\s]", " ", str(text or "").lower(), flags=re.UNICODE).split())
    if not normalized or "?" in str(text or ""):
        return False
    words = set(normalized.split())
    if words & NEGATION:
        return False
    return normalized in AFFIRMATIVE


def build_ali_request(rental: dict, required_deposit_id: str) -> dict:
    rental = validate_rental_fields(rental)
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", str(required_deposit_id or "")):
        raise AliQuoteError("missing_deposit_charge")
    selection = (
        {"vehicleId": rental["vehicle_id"]}
        if rental.get("vehicle_id") else {"classId": rental["vehicle_class_id"]}
    )
    request = {
        "rentalStart": rental["rental_start"],
        "rentalEnd": rental["rental_end"],
        "selection": selection,
        "extraSelections": rental.get("extra_ids") or [],
        "chargeSelections": [required_deposit_id],
    }
    if set(request) != ALI_REQUEST_KEYS:
        raise AliQuoteError("ali_request_boundary_failed")
    serialized = _json(request).lower()
    if any(term in serialized for term in ("customer", "whatsapp", "phone", "email", "location", "comment", "conversation", "name")):
        raise AliQuoteError("ali_request_contains_pii")
    return request


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(state_registry.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema() -> None:
    conn = _connection()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ali_quotes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, public_id TEXT NOT NULL UNIQUE, "
        "conversation_id TEXT NOT NULL, zernio_account_id TEXT NOT NULL, "
        "summary_hash TEXT NOT NULL, summary_version INTEGER NOT NULL, locale TEXT NOT NULL, "
        "customer_json TEXT NOT NULL, rental_json TEXT NOT NULL, ali_request_json TEXT NOT NULL, "
        "idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL, "
        "confirmed_at TEXT NOT NULL, sla_due_at TEXT NOT NULL, "
        "quote_reference TEXT, quote_snapshot_id TEXT, pricing_json TEXT, expires_at TEXT, "
        "pdf_path TEXT, pdf_sha256 TEXT, whatsapp_status TEXT NOT NULL DEFAULT 'pending', "
        "staff_email_status TEXT NOT NULL DEFAULT 'pending', "
        "notification_status_json TEXT NOT NULL DEFAULT '{}', "
        "attempt_count INTEGER NOT NULL DEFAULT 0, last_error_code TEXT, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "UNIQUE(conversation_id, summary_hash))"
    )
    conn.commit()
    conn.close()


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def create_confirmed_quote(
    conversation_id: str,
    zernio_account_id: str,
    customer: dict,
    rental: dict,
    stored_summary_hash: str,
    confirmation_text: str,
    required_deposit_id: str,
    summary_version: int = 1,
    raw_config: dict | None = None,
) -> tuple[dict, bool]:
    if not tenant_enabled(raw_config):
        raise AliQuoteError("wrong_tenant_or_workflow")
    if not is_unambiguous_confirmation(confirmation_text):
        raise AliQuoteError("ambiguous_confirmation")
    summary, current_hash = normalized_summary(customer, rental, summary_version)
    if not hmac.compare_digest(current_hash, str(stored_summary_hash or "")):
        raise AliQuoteError("stale_summary")
    ali_request = build_ali_request(rental, required_deposit_id)
    confirmed = _now()
    values = {
        "public_id": str(uuid.uuid4()),
        "conversation_id": conversation_id,
        "zernio_account_id": zernio_account_id,
        "summary_hash": current_hash,
        "summary_version": summary_version,
        "locale": summary["rental"]["conversation_language"],
        "customer_json": _json(customer),
        "rental_json": _json(summary["rental"]),
        "ali_request_json": _json(ali_request),
        "idempotency_key": secrets.token_urlsafe(24).replace("-", "_")[:40],
        "status": "confirmed",
        "confirmed_at": _iso(confirmed),
        "sla_due_at": _iso(confirmed + timedelta(minutes=30)),
        "created_at": _iso(confirmed),
        "updated_at": _iso(confirmed),
    }
    ensure_schema()
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM ali_quotes WHERE conversation_id = ? AND summary_hash = ?",
            (conversation_id, current_hash),
        ).fetchone()
        if existing:
            conn.commit()
            return _row(existing), False
        columns = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        conn.execute(f"INSERT INTO ali_quotes ({columns}) VALUES ({placeholders})", tuple(values.values()))
        created = conn.execute("SELECT * FROM ali_quotes WHERE public_id = ?", (values["public_id"],)).fetchone()
        conn.commit()
        return _row(created), True
    finally:
        conn.close()


def get_quote(public_id: str) -> dict | None:
    ensure_schema()
    conn = _connection()
    row = conn.execute("SELECT * FROM ali_quotes WHERE public_id = ?", (public_id,)).fetchone()
    conn.close()
    return _row(row)


def update_quote(public_id: str, **changes) -> dict:
    allowed = {
        "status", "quote_reference", "quote_snapshot_id", "pricing_json", "expires_at",
        "pdf_path", "pdf_sha256", "whatsapp_status", "staff_email_status",
        "notification_status_json", "attempt_count", "last_error_code",
    }
    if not changes or set(changes) - allowed:
        raise AliQuoteError("invalid_quote_update")
    changes["updated_at"] = _iso(_now())
    conn = _connection()
    assignments = ", ".join(f"{key} = ?" for key in changes)
    conn.execute(f"UPDATE ali_quotes SET {assignments} WHERE public_id = ?", (*changes.values(), public_id))
    conn.commit()
    row = conn.execute("SELECT * FROM ali_quotes WHERE public_id = ?", (public_id,)).fetchone()
    conn.close()
    if not row:
        raise AliQuoteError("quote_not_found")
    return _row(row)


def resumable_quotes() -> list[dict]:
    ensure_schema()
    conn = _connection()
    placeholders = ",".join("?" for _ in PENDING_STATUSES)
    rows = conn.execute(f"SELECT * FROM ali_quotes WHERE status IN ({placeholders}) ORDER BY id", PENDING_STATUSES).fetchall()
    conn.close()
    return [dict(row) for row in rows]


class AliQuoteClient:
    def __init__(self, base_url: str, service_token: str, client: httpx.Client | None = None):
        if not base_url.startswith("https://") or not service_token:
            raise AliQuoteError("ali_client_unconfigured")
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token
        self.client = client or httpx.Client(timeout=12.0)

    def get_catalog(self) -> dict:
        for attempt in range(2):
            try:
                response = self.client.get(
                    f"{self.base_url}/api/v1/catalog",
                    headers={
                        "Authorization": f"Bearer {self.service_token}",
                        "Accept": "application/json",
                    },
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == 0:
                    continue
                raise AliQuoteError("ali_catalog_temporary_failure") from exc
            if response.status_code == 200:
                payload = response.json()
                required = {
                    "catalogVersion", "currency", "availabilityMode",
                    "vehicleClasses", "vehicles", "extras",
                }
                if (
                    not required.issubset(payload)
                    or payload.get("currency") != "USD"
                    or payload.get("availabilityMode") != "request_only"
                    or not isinstance(payload.get("vehicleClasses"), list)
                    or not isinstance(payload.get("vehicles"), list)
                    or not isinstance(payload.get("extras"), list)
                ):
                    raise AliQuoteError("ali_catalog_invalid")
                for item in [*payload["vehicleClasses"], *payload["vehicles"]]:
                    if not isinstance(item, dict) or not str(item.get("id") or "").strip() or not str(item.get("name") or "").strip():
                        raise AliQuoteError("ali_catalog_invalid")
                return payload
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 0:
                    continue
                raise AliQuoteError("ali_catalog_temporary_failure")
            raise AliQuoteError(f"ali_catalog_http_{response.status_code}")
        raise AliQuoteError("ali_catalog_temporary_failure")

    def create_quote(self, request: dict, idempotency_key: str) -> dict:
        if set(request) != ALI_REQUEST_KEYS:
            raise AliQuoteError("ali_request_boundary_failed")
        for attempt in range(2):
            try:
                response = self.client.post(
                    f"{self.base_url}/api/v1/quotes",
                    headers={"Authorization": f"Bearer {self.service_token}", "Idempotency-Key": idempotency_key},
                    json=request,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == 0:
                    continue
                raise AliQuoteError("ali_temporary_failure") from exc
            if response.status_code in (200, 201):
                payload = response.json()
                required = {"quoteSnapshotId", "quoteReference", "catalogVersion", "availabilityMode", "currency", "rentalDays", "items", "rentalTotal", "refundableSecurityDeposit", "reservationDeposit", "createdAt", "expiresAt"}
                if not required.issubset(payload) or payload.get("availabilityMode") != "request_only" or payload.get("currency") != "USD":
                    raise AliQuoteError("ali_response_invalid")
                created = datetime.fromisoformat(payload["createdAt"].replace("Z", "+00:00"))
                expires = datetime.fromisoformat(payload["expiresAt"].replace("Z", "+00:00"))
                if expires - created != timedelta(hours=72):
                    raise AliQuoteError("ali_expiry_invalid")
                return payload
            if response.status_code in (429,) or response.status_code >= 500:
                if attempt == 0:
                    continue
                raise AliQuoteError("ali_temporary_failure")
            raise AliQuoteError(f"ali_http_{response.status_code}")
        raise AliQuoteError("ali_temporary_failure")


def get_intake_catalog(
    client: AliQuoteClient | None = None,
    *,
    force_refresh: bool = False,
) -> dict:
    """Return the current published Ali catalog without customer data."""
    now = time.monotonic()
    cached = _CATALOG_CACHE.get("value")
    if not force_refresh and cached is not None and now < float(_CATALOG_CACHE["expires_at"]):
        return cached
    active_client = client or AliQuoteClient(
        os.environ.get("ALI_QUOTE_API_BASE_URL", "https://alicarrental.com"),
        os.environ.get("ALI_QUOTE_API_TOKEN", ""),
    )
    catalog = active_client.get_catalog()
    _CATALOG_CACHE["value"] = catalog
    _CATALOG_CACHE["expires_at"] = now + _CATALOG_CACHE_SECONDS
    return catalog


def catalog_prompt_context(catalog: dict) -> dict:
    """Expose only current public names and fixed rates to the intake prompt."""
    rates_by_class: dict[str, set[str]] = {}
    vehicles = []
    for vehicle in catalog.get("vehicles") or []:
        class_id = str(vehicle.get("classId") or "")
        amount = str((vehicle.get("dailyRate") or {}).get("amount") or "")
        if class_id and amount:
            rates_by_class.setdefault(class_id, set()).add(amount)
        vehicles.append({
            "name": str(vehicle.get("name") or ""),
            "category": next((
                str(item.get("name") or "")
                for item in catalog.get("vehicleClasses") or []
                if item.get("id") == class_id
            ), ""),
        })
    categories = []
    for item in catalog.get("vehicleClasses") or []:
        rates = sorted(rates_by_class.get(str(item.get("id") or ""), set()))
        categories.append({
            "name": str(item.get("name") or ""),
            "daily_usd": rates[0] if len(rates) == 1 else None,
        })
    return {
        "catalog_version": catalog.get("catalogVersion"),
        "availability_mode": "request_only",
        "currency": "USD",
        "categories": categories,
        "vehicles": vehicles,
    }


def sanitize_intake_reply(reply: str, locale: str | None = None) -> str:
    """Fail closed if Marina tries to redirect an Ali WhatsApp customer."""
    text = str(reply or "").strip()
    if not _FORBIDDEN_CONTACT_REDIRECT.search(text):
        return text
    selected_locale = str(locale or "en").lower()
    return _INTAKE_SAFETY_FALLBACK.get(selected_locale, _INTAKE_SAFETY_FALLBACK["en"])


def _normalize_catalog_label(value: object) -> str:
    normalized = str(value or "").casefold()
    normalized = re.sub(r"\bor\s+similar\b", " ", normalized)
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    ignored = {"car", "cars", "vehicle", "vehicles", "category", "class", "rental"}
    return " ".join(part for part in normalized.split() if part not in ignored)


def resolve_catalog_selection(fields: dict, catalog: dict) -> dict:
    """Map a customer-facing selection to one current server-owned ID."""
    resolved = dict(fields or {})
    classes = [item for item in catalog.get("vehicleClasses") or [] if isinstance(item, dict)]
    vehicles = [item for item in catalog.get("vehicles") or [] if isinstance(item, dict)]
    class_by_id = {str(item.get("id")): item for item in classes if item.get("id")}
    vehicle_by_id = {str(item.get("id")): item for item in vehicles if item.get("id")}

    def unique_name_match(items: list[dict], value: object) -> dict | None:
        target = _normalize_catalog_label(value)
        if not target:
            return None
        matches = [item for item in items if _normalize_catalog_label(item.get("name")) == target]
        return matches[0] if len(matches) == 1 else None

    vehicle = vehicle_by_id.get(str(resolved.get("vehicle_id") or ""))
    vehicle = vehicle or unique_name_match(vehicles, resolved.get("vehicle_name"))
    vehicle_class = class_by_id.get(str(resolved.get("vehicle_class_id") or ""))
    vehicle_class = vehicle_class or unique_name_match(classes, resolved.get("vehicle_class_name"))

    for key in ("vehicle_id", "vehicle_name", "vehicle_class_id", "vehicle_class_name"):
        resolved.pop(key, None)
    if vehicle:
        resolved["vehicle_id"] = str(vehicle["id"])
        resolved["vehicle_name"] = str(vehicle["name"])
    elif vehicle_class:
        resolved["vehicle_class_id"] = str(vehicle_class["id"])
        resolved["vehicle_class_name"] = str(vehicle_class["name"])
    return resolved


@dataclass
class DeliveryAdapters:
    send_whatsapp: Callable[[dict, str], bool]
    send_staff_email: Callable[[dict, bytes], bool]
    send_operator_alerts: Callable[[dict], dict]
    escalate: Callable[[dict, str], None]


def _attempt_twice(operation: Callable, *args) -> bool:
    for attempt in range(2):
        try:
            if operation(*args):
                return True
        except (TimeoutError, ConnectionError, OSError):
            pass
        if attempt == 0:
            continue
    return False


def process_quote(
    public_id: str,
    ali_client: AliQuoteClient,
    adapters: DeliveryAdapters,
    switches: dict[str, bool] | None = None,
    output_root: str = "/app/data/ali-quotes",
    logo_path: str | None = None,
    delay_seconds: int = QUOTE_PROCESSING_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = _now,
) -> dict:
    quote = get_quote(public_id)
    if not quote:
        raise AliQuoteError("quote_not_found")
    switches = switches or feature_switches()
    if not switches.get("automation"):
        adapters.escalate(quote, "automation_disabled")
        return update_quote(public_id, status="attention_required", last_error_code="automation_disabled")
    try:
        remaining_delay = seconds_until_quote_processing(
            quote, now=now(), delay_seconds=delay_seconds,
        )
        if remaining_delay:
            sleep(remaining_delay)
        pricing = json.loads(quote["pricing_json"]) if quote.get("pricing_json") else None
        if pricing is None:
            update_quote(public_id, status="pricing")
            pricing = ali_client.create_quote(json.loads(quote["ali_request_json"]), quote["idempotency_key"])
            quote = update_quote(
                public_id, status="quoted", quote_reference=pricing["quoteReference"],
                quote_snapshot_id=pricing["quoteSnapshotId"], pricing_json=_json(pricing),
                expires_at=pricing["expiresAt"],
            )
        if not quote.get("pdf_path"):
            path, digest = render_quote_pdf(
                public_id, quote["locale"], json.loads(quote["customer_json"]),
                json.loads(quote["rental_json"]), pricing, output_root=output_root,
                logo_path=logo_path,
            )
            quote = update_quote(public_id, status="pdf_ready", pdf_path=path, pdf_sha256=digest)
        pdf_bytes = open(quote["pdf_path"], "rb").read()
        if hashlib.sha256(pdf_bytes).hexdigest() != quote["pdf_sha256"]:
            raise AliQuoteError("pdf_integrity_failed")
        quote = update_quote(public_id, status="delivering")
        delivery_errors = []
        if switches.get("customer_delivery") and quote["whatsapp_status"] != "accepted":
            ok = _attempt_twice(adapters.send_whatsapp, quote, quote["pdf_path"])
            quote = update_quote(public_id, whatsapp_status="accepted" if ok else "failed")
            if not ok:
                delivery_errors.append("whatsapp_delivery_failed")
        if switches.get("staff_email") and quote["staff_email_status"] != "sent":
            ok = _attempt_twice(adapters.send_staff_email, quote, pdf_bytes)
            quote = update_quote(public_id, staff_email_status="sent" if ok else "failed")
            if not ok:
                delivery_errors.append("staff_email_failed")
        if delivery_errors:
            raise AliQuoteError(delivery_errors[0])
        if switches.get("operator_alerts") and quote.get("notification_status_json") in (None, "", "{}"):
            outcomes = adapters.send_operator_alerts(quote)
            quote = update_quote(public_id, notification_status_json=_json(outcomes))
        complete = quote["staff_email_status"] == "sent" and quote["whatsapp_status"] == "accepted"
        return update_quote(public_id, status="complete" if complete else "pdf_ready")
    except AliQuoteError as exc:
        attempts = int(quote.get("attempt_count") or 0) + 1
        failed = update_quote(public_id, status="attention_required", attempt_count=attempts, last_error_code=exc.code)
        adapters.escalate(failed, exc.code)
        return failed


SUMMARY_LABELS = {
    "en": ("Just checking I’ve got everything right:", "Name", "Rental period", "Pickup", "Return", "Car", "Does that all look right?"),
    "nl": ("Even controleren of ik alles goed heb:", "Naam", "Huurperiode", "Ophalen", "Terugbrengen", "Auto", "Klopt dit zo?"),
    "pap": ("Laga mi wak si mi tin tur kos korekto:", "Nòmber", "Periodo di huur", "Busca", "Devolvé", "Outo", "Tur kos ta bon asina?"),
    "de": ("Ich prüfe kurz, ob ich alles richtig verstanden habe:", "Name", "Mietzeitraum", "Abholung", "Rückgabe", "Fahrzeug", "Passt das so?"),
}

PREPARING = {
    "en": "Great, I have everything I need. I’ll prepare your official quote and send it here on WhatsApp within 30 minutes.",
    "nl": "Prima, ik heb alles wat ik nodig heb. Ik maak je officiële offerte en stuur die binnen 30 minuten hier via WhatsApp.",
    "pap": "Bon, mi tin tur loke mi mester. Mi ta prepara bo oferta ofisial i lo manda esaki aki via WhatsApp denter di 30 minüt.",
    "de": "Alles klar, ich habe alle Angaben. Ich erstelle jetzt Ihr offizielles Angebot und sende es innerhalb von 30 Minuten hier per WhatsApp.",
}

FALLBACK = {
    "en": "I've passed your confirmed request to our team so they can finish your quote. They'll continue with you here on WhatsApp.",
    "nl": "Ik heb je bevestigde aanvraag aan ons team doorgegeven. Zij ronden je offerte af en helpen je hier verder via WhatsApp.",
    "pap": "Mi a pasa bo petishon konfirmá pa nos tim. Nan lo kaba ku bo oferta i sigui ku bo aki via WhatsApp.",
    "de": "Ich habe Ihre bestätigte Anfrage an unser Team weitergegeben. Es erstellt Ihr Angebot und meldet sich hier in WhatsApp.",
}


def _summary_text(summary: dict) -> str:
    rental = summary["rental"]
    customer = summary["customer"]
    labels = SUMMARY_LABELS[rental["conversation_language"]]
    vehicle = rental.get("vehicle_name") or rental.get("vehicle_class_name") or "-"
    period = format_rental_period(
        rental["rental_start"], rental["rental_end"],
        rental["conversation_language"],
    )
    return (
        f"{labels[0]}\n\n{labels[1]}: {customer.get('name', '')}\n"
        f"{labels[2]}: {period}\n"
        f"{labels[3]}: {rental['pickup_location']}\n{labels[4]}: {rental['return_location']}\n"
        f"{labels[5]}: {vehicle}\n\n{labels[6]}"
    )


def _process_production(public_id: str) -> None:
    from agents.social.ali_quote_delivery import production_adapters
    try:
        client = AliQuoteClient(
            os.environ.get("ALI_QUOTE_API_BASE_URL", "https://alicarrental.com"),
            os.environ.get("ALI_QUOTE_API_TOKEN", ""),
        )
        process_quote(
            public_id, client, production_adapters(),
            output_root=os.environ.get("ALI_QUOTE_DATA_ROOT", "/app/data/ali-quotes"),
        )
    except AliQuoteError:
        quote = get_quote(public_id)
        if quote:
            production_adapters().escalate(quote, "processor_unconfigured")


def handle_ali_quote_turn(
    conversation_id: str,
    zernio_account_id: str,
    whatsapp_number: str,
    message_text: str,
    fields: dict,
    flags: dict,
    from_name: str = "",
    raw_config: dict | None = None,
    processor: Callable[[str], None] | None = None,
) -> str | None:
    """Prepare or confirm exactly one deterministic Ali summary.

    Returning ``None`` means required fields are still missing and Marina's
    one-question-at-a-time reply should be used unchanged.
    """
    raw = raw_config if raw_config is not None else (config_loader.get_raw() or {})
    if not tenant_enabled(raw):
        return None
    try:
        resolved_fields = resolve_catalog_selection(fields, get_intake_catalog())
    except AliQuoteError:
        return None
    for key in ("vehicle_id", "vehicle_name", "vehicle_class_id", "vehicle_class_name"):
        if key in resolved_fields:
            fields[key] = resolved_fields[key]
        else:
            fields.pop(key, None)
    rental = {key: fields.get(key) for key in (
        "rental_start", "rental_end", "pickup_location", "return_location",
        "vehicle_id", "vehicle_name", "vehicle_class_id", "vehicle_class_name",
        "driver_age", "passenger_count", "luggage_count", "extra_ids", "comments",
        "conversation_language",
    )}
    customer = {
        "name": fields.get("customer_name") or " ".join(value for value in (fields.get("first_name"), fields.get("surnames")) if value) or from_name,
        "whatsapp": whatsapp_number,
    }
    try:
        summary, digest = normalized_summary(customer, rental)
    except AliQuoteError:
        flags.pop("ali_summary_hash", None)
        flags.pop("awaiting_quote_confirmation", None)
        return None
    previous = flags.get("ali_summary_hash")
    awaiting = bool(flags.get("awaiting_quote_confirmation"))
    if awaiting and previous == digest and is_unambiguous_confirmation(message_text):
        workflow = raw.get("workflow") or {}
        deposit_id = workflow.get("required_deposit_charge_id") or (raw.get("ali_quote") or {}).get("required_deposit_charge_id")
        try:
            quote, created = create_confirmed_quote(
                conversation_id, zernio_account_id, customer, rental, digest,
                message_text, deposit_id, raw_config=raw,
            )
        except AliQuoteError as exc:
            state_registry.create_pending_notification(
                "escalation", "whatsapp", conversation_id, customer["name"],
                "[ALI QUOTE CONFIGURATION REQUIRED]", f"Confirmed quote could not start safely. Code: {exc.code}.", mode="hard",
            )
            return FALLBACK[rental["conversation_language"]]
        flags["awaiting_quote_confirmation"] = False
        flags["ali_quote_public_id"] = quote["public_id"]
        if created:
            import threading
            threading.Thread(target=processor or _process_production, args=(quote["public_id"],), daemon=True).start()
        return PREPARING[rental["conversation_language"]]
    flags["ali_summary_hash"] = digest
    flags["ali_summary_version"] = 1
    flags["awaiting_quote_confirmation"] = True
    return _summary_text(summary)


def resume_pending_processing(processor: Callable[[str], None] | None = None) -> int:
    """Resume incomplete quotes only when Ali automation is explicitly on."""
    if not tenant_enabled() or not feature_switches().get("automation"):
        return 0
    import threading
    pending = resumable_quotes()
    for quote in pending:
        threading.Thread(target=processor or _process_production, args=(quote["public_id"],), daemon=True).start()
    return len(pending)
