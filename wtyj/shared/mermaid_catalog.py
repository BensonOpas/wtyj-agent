"""Validated, immutable catalog access for Mermaid's reservation demo."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from shared import config_loader


class MermaidCatalogError(ValueError):
    """Raised when the tenant catalog is absent or unsafe for the demo."""


_SUPPORTED_CURRENCIES = {"USD", "EUR", "XCG"}
_REQUIRED_PRICE_KEYS = {"adult", "child_4_12", "infant_0_3", "sedula"}
_WEEKDAYS = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
}
_DEMO_MARKER = "DEMO POLICY - REPLACE BEFORE GO-LIVE"


def _catalog_path() -> Path:
    configured = Path(str(getattr(config_loader, "_CONFIG_PATH", "")))
    if configured.name == "client.json":
        return configured.with_name("reservation_catalog.json")
    return Path(__file__).resolve().parents[2] / "clients" / "mermaid" / "config" / "reservation_catalog.json"


def validate_catalog(catalog: dict) -> dict:
    """Validate the authoritative demo facts and return a defensive copy."""
    if not isinstance(catalog, dict):
        raise MermaidCatalogError("catalog must be an object")
    if catalog.get("tenant_slug") != "mermaid":
        raise MermaidCatalogError("catalog tenant must be mermaid")
    version = str(catalog.get("version") or "").strip()
    if not version:
        raise MermaidCatalogError("catalog version is required")

    pricing = catalog.get("pricing") or {}
    if not isinstance(pricing, dict):
        raise MermaidCatalogError("pricing must be an object")
    currencies = pricing.get("currencies") or {}
    if not isinstance(currencies, dict) or set(currencies) != _SUPPORTED_CURRENCIES:
        raise MermaidCatalogError("catalog currencies must be USD, EUR and XCG")
    for currency, values in currencies.items():
        if not isinstance(values, dict) or set(values) != _REQUIRED_PRICE_KEYS:
            raise MermaidCatalogError(f"{currency} price bands are incomplete")
        for band, amount in values.items():
            if type(amount) is not int or not 0 <= amount <= 100000:
                raise MermaidCatalogError(f"{currency} {band} price must be a non-negative integer")
    if not isinstance(pricing.get("default_currency"), str) or pricing["default_currency"] not in _SUPPORTED_CURRENCIES:
        raise MermaidCatalogError("default currency is unsupported")
    vehicles = pricing.get("pickup_vehicles")
    pickup = pricing.get("pickup_price")
    if vehicles is None and pricing.get("pickup_basis") == "per_vehicle":
        raise MermaidCatalogError("pickup vehicles are required for per-vehicle pricing")
    if vehicles is not None:
        if not isinstance(vehicles, list) or len(vehicles) != 2 or [v.get("key") for v in vehicles if isinstance(v, dict)] != ["car", "van"]:
            raise MermaidCatalogError("pickup vehicles must define car and van")
        previous_capacity = 0
        for vehicle in vehicles:
            capacity = vehicle.get("capacity")
            amount = vehicle.get("price")
            if type(capacity) is not int or not previous_capacity < capacity <= 100:
                raise MermaidCatalogError("pickup vehicle capacities must be positive and increasing")
            if type(amount) is not int or not 0 <= amount <= 100000:
                raise MermaidCatalogError("pickup price must be a non-negative integer")
            previous_capacity = capacity
        if pricing.get("pickup_basis") != "per_vehicle" or pricing.get("pickup_coverage") != "island_wide":
            raise MermaidCatalogError("pickup must be priced per vehicle island-wide")
        if not isinstance(pricing.get("pickup_overflow"), str) or pricing["pickup_overflow"] not in {"team_review", "multiple_vans"}:
            raise MermaidCatalogError("pickup overflow policy is required")
        if pickup is not None:
            raise MermaidCatalogError("flat pickup price conflicts with vehicle pricing")
    elif pickup is not None:
        if type(pickup) is not int or not 0 <= pickup <= 100000:
            raise MermaidCatalogError("pickup price must be a non-negative integer")
        if pricing.get("pickup_basis") != "per_booking" or pricing.get("pickup_coverage") != "island_wide":
            raise MermaidCatalogError("pickup must be a flat island-wide charge per booking")
    if (vehicles is not None or pickup is not None) and (not isinstance(pricing.get("pickup_currency"), str) or pricing["pickup_currency"] not in _SUPPORTED_CURRENCIES):
        raise MermaidCatalogError("pickup currency is unsupported")

    service = catalog.get("service") or {}
    if not isinstance(service, dict):
        raise MermaidCatalogError("service must be an object")
    weekdays = service.get("operating_weekdays")
    if (not isinstance(weekdays, list) or not weekdays or
            any(not isinstance(day, str) or day not in _WEEKDAYS for day in weekdays) or
            len(set(weekdays)) != len(weekdays)):
        raise MermaidCatalogError("operating weekdays are malformed")
    for key in ("arrival_time", "island_departure_time"):
        if not isinstance(service.get(key), str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", service[key]):
            raise MermaidCatalogError("trip times must use HH:MM in Curaçao local time")
    if service["arrival_time"] >= service["island_departure_time"]:
        raise MermaidCatalogError("return boarding must be after arrival/check-in")
    arrival = datetime.strptime(service["arrival_time"], "%H:%M")
    lead = service.get("pickup_minutes_before_arrival")
    if type(lead) is not int or not 0 < lead <= arrival.hour * 60 + arrival.minute:
        raise MermaidCatalogError("pickup lead time must be positive and on the same day as check-in")
    for key in ("name", "meeting_point"):
        _text(service.get(key), key, 300)
    for key in ("included", "bring", "extras"):
        values = catalog.get(key, [])
        if not isinstance(values, list) or len(values) > 50:
            raise MermaidCatalogError(f"{key} must contain at most 50 items")
        for value in values:
            _text(value, key, 1000)

    policies = catalog.get("policies") or {}
    if not isinstance(policies, dict):
        raise MermaidCatalogError("policies must be an object")
    for key in ("cancellation", "safety", "insurance"):
        _text(policies.get(key), key, 5000)
    for key in ("cancellation", "safety"):
        if _DEMO_MARKER not in str(policies.get(key) or ""):
            raise MermaidCatalogError(f"{key} policy is not marked as demo content")
    insurance = str(policies.get("insurance") or "").lower()
    if "not verified" not in insurance:
        raise MermaidCatalogError("insurance wording must remain neutral")
    return copy.deepcopy(catalog)


def _text(value, label: str, maximum: int):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise MermaidCatalogError(f"{label} must be non-empty text (maximum {maximum} characters)")


def catalog_revision(catalog: dict) -> str:
    """Content fingerprint also detects edits made outside the dashboard."""
    return hashlib.sha256(json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class MermaidCatalogConflict(MermaidCatalogError):
    pass


_EDITABLE = {
    "service": {"name", "meeting_point", "operating_weekdays", "arrival_time", "island_departure_time", "pickup_minutes_before_arrival"},
    "pricing": {"currencies", "default_currency", "pickup_price", "pickup_currency", "pickup_vehicles", "pickup_overflow"},
    "policies": {"cancellation", "safety", "insurance"},
}


def publish_catalog(changes: dict, expected_revision: str) -> dict:
    """Publish one validated version under a process-safe compare-and-set lock.

    Only this tenant's existing catalog is replaced. A durable prior version is
    retained first; reservations and their monetary snapshots are never written.
    Templates, checkout links, tenant identity and feature flags are not editable.
    """
    if not isinstance(changes, dict) or not changes or set(changes) - {*_EDITABLE, "included", "bring", "extras"}:
        raise MermaidCatalogError("unsupported catalog fields")
    for group, allowed in _EDITABLE.items():
        if group in changes and (not isinstance(changes[group], dict) or set(changes[group]) - allowed):
            raise MermaidCatalogError(f"unsupported {group} fields")
    path = _catalog_path()
    with path.with_name(".reservation_catalog.lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = get_catalog()
        if expected_revision != catalog_revision(current):
            raise MermaidCatalogConflict("Trip settings changed since you opened them. Reload the published version before trying again.")
        candidate = copy.deepcopy(current)
        for key, value in changes.items():
            if key in _EDITABLE:
                candidate[key].update(copy.deepcopy(value))
            else:
                candidate[key] = copy.deepcopy(value)
        # Transport prose must not keep old prices/capacities after publishing.
        # This legacy generated line is derived; operator-written extras remain.
        extras = candidate.get("extras", [])
        if isinstance(extras, list):
            candidate["extras"] = [item for item in extras if not isinstance(item, str) or not item.startswith(("Optional island-wide pickup:", "Optional pickup:"))]
        validate_catalog(candidate)
        if (candidate["pricing"].get("pickup_vehicles") or candidate["pricing"].get("pickup_price") is not None) and candidate["pricing"]["default_currency"] != candidate["pricing"].get("pickup_currency"):
            raise MermaidCatalogError("Default quote currency and pickup currency must match; pickup conversion rates are not configured.")
        if candidate == current:
            return current
        candidate["version"] = "mermaid-settings-" + uuid.uuid4().hex
        history = path.with_name("reservation_catalog_history")
        history.mkdir(mode=0o700, exist_ok=True)
        prior = history / (catalog_revision(current) + ".json")
        if not prior.exists():
            _atomic_catalog_write(prior, current)
        _atomic_catalog_write(path, candidate)
        return candidate


def _atomic_catalog_write(path: Path, catalog: dict):
    fd, temporary = tempfile.mkstemp(prefix=".mermaid-catalog-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(catalog, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def get_catalog() -> dict:
    """Load and validate the Mermaid catalog without returning mutable cache state."""
    path = _catalog_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MermaidCatalogError(f"unable to load Mermaid catalog: {exc}") from exc
    return validate_catalog(payload)


def pickup_time(catalog: dict | None = None) -> str:
    """Derive the current demo pickup time in Curaçao local time."""
    service = (get_catalog() if catalog is None else catalog)["service"]
    arrival = datetime.strptime(service["arrival_time"], "%H:%M")
    return (arrival - timedelta(minutes=service["pickup_minutes_before_arrival"])).strftime("%H:%M")


def pickup_quote(passengers: int, catalog: dict | None = None) -> dict:
    """Choose configured transport; passenger count includes every age band."""
    pricing = (get_catalog() if catalog is None else catalog)["pricing"]
    if type(passengers) is not int or passengers <= 0:
        return {"status": "awaiting_guest_count"}
    base = {"passenger_count": passengers, "currency": pricing.get("pickup_currency")}
    vehicles = pricing.get("pickup_vehicles")
    if not vehicles:
        amount = pricing.get("pickup_price")
        return {**base, "status": "unpriced" if amount is None else "quoted",
                "quantity": 1, "unit_amount": amount, "amount": amount}
    selected = next((v for v in vehicles if passengers <= v["capacity"]), None)
    quantity = 1
    if selected is None:
        if pricing["pickup_overflow"] == "team_review":
            return {**base, "status": "requires_review"}
        selected = vehicles[-1]
        quantity = (passengers + selected["capacity"] - 1) // selected["capacity"]
    return {**base, "status": "quoted", "vehicle_key": selected["key"],
            "vehicle_capacity": selected["capacity"], "quantity": quantity,
            "unit_amount": selected["price"], "amount": quantity * selected["price"]}


def reservation_demo_enabled() -> bool:
    raw = config_loader.get_raw() or {}
    return raw.get("slug") == "mermaid" and bool(
        (raw.get("features") or {}).get("mermaid_reservation_demo", False)
    )


def demo_features() -> dict:
    """Return Mermaid-only feature controls and force reminders off."""
    raw = config_loader.get_raw() or {}
    features = raw.get("features") or {}
    return {
        "intake": bool(features.get("mermaid_reservation_demo", False)),
        "quote_delivery": bool(features.get("mermaid_quote_delivery", False)),
        "demo_payment": bool(features.get("mermaid_demo_payment", False)),
        "dashboard_projection": bool(features.get("mermaid_dashboard_projection", False)),
        "reminders": False,
    }
