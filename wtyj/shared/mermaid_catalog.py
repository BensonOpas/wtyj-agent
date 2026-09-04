"""Validated, immutable catalog access for Mermaid's reservation demo."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from shared import config_loader


class MermaidCatalogError(ValueError):
    """Raised when the tenant catalog is absent or unsafe for the demo."""


_SUPPORTED_CURRENCIES = {"USD", "EUR", "XCG"}
_REQUIRED_PRICE_KEYS = {"adult", "child_4_12", "infant_0_3", "sedula"}
_REQUIRED_WEEKDAYS = {
    "monday", "tuesday", "wednesday", "friday", "saturday", "sunday"
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
    currencies = pricing.get("currencies") or {}
    if set(currencies) != _SUPPORTED_CURRENCIES:
        raise MermaidCatalogError("catalog currencies must be USD, EUR and XCG")
    for currency, values in currencies.items():
        if set(values or {}) != _REQUIRED_PRICE_KEYS:
            raise MermaidCatalogError(f"{currency} price bands are incomplete")
        for band, amount in values.items():
            if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
                raise MermaidCatalogError(f"{currency} {band} price must be a non-negative integer")
    if pricing.get("default_currency") not in _SUPPORTED_CURRENCIES:
        raise MermaidCatalogError("default currency is unsupported")
    pickup = pricing.get("pickup_price")
    if pickup is not None:
        if not isinstance(pickup, int) or isinstance(pickup, bool) or pickup < 0:
            raise MermaidCatalogError("pickup price must be a non-negative integer")
        if pricing.get("pickup_currency") not in _SUPPORTED_CURRENCIES:
            raise MermaidCatalogError("pickup currency is unsupported")
        if pricing.get("pickup_basis") != "per_booking" or pricing.get("pickup_coverage") != "island_wide":
            raise MermaidCatalogError("pickup must be a flat island-wide charge per booking")

    service = catalog.get("service") or {}
    if set(service.get("operating_weekdays") or []) != _REQUIRED_WEEKDAYS:
        raise MermaidCatalogError("operating weekdays are malformed")
    if service.get("arrival_time") != "06:45" or service.get("island_departure_time") != "15:20":
        raise MermaidCatalogError("published schedule is malformed")
    if "Fishermen's Pier" not in str(service.get("meeting_point") or ""):
        raise MermaidCatalogError("meeting point is missing")

    policies = catalog.get("policies") or {}
    for key in ("cancellation", "safety"):
        if _DEMO_MARKER not in str(policies.get(key) or ""):
            raise MermaidCatalogError(f"{key} policy is not marked as demo content")
    insurance = str(policies.get("insurance") or "").lower()
    if "not verified" not in insurance:
        raise MermaidCatalogError("insurance wording must remain neutral")
    return copy.deepcopy(catalog)


def get_catalog() -> dict:
    """Load and validate the Mermaid catalog without returning mutable cache state."""
    path = _catalog_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MermaidCatalogError(f"unable to load Mermaid catalog: {exc}") from exc
    return validate_catalog(payload)


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
