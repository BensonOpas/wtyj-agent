"""Deterministic Ali vehicle selection from native WhatsApp taps."""

from __future__ import annotations

import re
import unicodedata

from agents.social.ali_vehicle_recommendations import (
    parse_vehicle_selection_payload,
)


_SUPPORTED_INTERACTIVE_TYPES = {"buttonreply", "listreply"}
_SELECTION_NAMESPACE = "ali_vehicle_select:"
_MONEY = re.compile(r"(?:0|[1-9]\d*)\.\d{2}")
_CLEAR_TYPED_CHOICE = re.compile(
    r"^(?:(?:i\s+)?(?:choose|chose|want|prefer|take|select)|"
    r"(?:ik\s+)?(?:kies|wil|neem)|"
    r"(?:mi\s+)?(?:ke|skohe)|"
    r"(?:ich\s+)?(?:w[aä]hle|m[oö]chte|nehme))\s+",
    re.IGNORECASE,
)


class AliVehicleSelectionError(ValueError):
    """A vehicle picker payload failed active tenant-catalog validation."""


def _interactive_type(value: object) -> str:
    return re.sub(r"[^a-z]", "", str(value or "").strip().lower())


def _catalog_label(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"\bor\s+similar\b", " ", normalized)
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def _canonical_vehicle(vehicle: dict, classes: dict[str, dict]) -> dict:
    vehicle_id = str(vehicle.get("id") or "").strip()
    vehicle_name = str(vehicle.get("name") or "").strip()
    class_id = str(vehicle.get("classId") or "").strip()
    vehicle_class = classes.get(class_id)
    class_name = str((vehicle_class or {}).get("name") or "").strip()
    rate = vehicle.get("dailyRate") or {}
    rate_amount = str(rate.get("amount") or "").strip()
    rate_currency = str(rate.get("currency") or "").strip().upper()
    if (
        not vehicle_id
        or not vehicle_name
        or not class_id
        or not class_name
        or rate_currency != "USD"
        or not _MONEY.fullmatch(rate_amount)
    ):
        raise AliVehicleSelectionError("vehicle_selection_catalog_invalid")
    return {
        "vehicle_id": vehicle_id,
        "vehicle_name": vehicle_name,
        "vehicle_class_id": class_id,
        "vehicle_class_name": class_name,
        "vehicle_catalog_class_id": class_id,
        "vehicle_catalog_class_name": class_name,
        "vehicle_daily_rate_usd": rate_amount,
        "vehicle_rate_currency": rate_currency,
    }


def _active_catalog(catalog: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    vehicles = {
        str(item.get("id") or "").strip(): item
        for item in catalog.get("vehicles") or []
        if isinstance(item, dict)
        and str(item.get("id") or "").strip()
        and item.get("active", True) is not False
    }
    classes = {
        str(item.get("id") or "").strip(): item
        for item in catalog.get("vehicleClasses") or []
        if isinstance(item, dict)
        and str(item.get("id") or "").strip()
        and item.get("active", True) is not False
    }
    return vehicles, classes


def resolve_vehicle_selection(
    interactive_type: object,
    interactive_id: object,
    catalog: dict,
) -> dict | None:
    """Resolve one native picker tap to canonical active catalog fields.

    Returns ``None`` for unrelated interactive replies. A payload using Ali's
    vehicle-selection namespace fails closed when its vehicle is no longer in
    this tenant's active catalog.
    """
    normalized_type = _interactive_type(interactive_type)
    vehicle_id = parse_vehicle_selection_payload(interactive_id)
    if normalized_type not in _SUPPORTED_INTERACTIVE_TYPES:
        if str(interactive_id or "").strip().startswith(_SELECTION_NAMESPACE):
            raise AliVehicleSelectionError("vehicle_selection_type_invalid")
        return None
    if vehicle_id is None:
        if str(interactive_id or "").strip().startswith(_SELECTION_NAMESPACE):
            raise AliVehicleSelectionError("vehicle_selection_payload_invalid")
        return None

    vehicles, classes = _active_catalog(catalog)
    vehicle = vehicles.get(vehicle_id)
    if vehicle is None:
        raise AliVehicleSelectionError("vehicle_selection_not_active")
    return _canonical_vehicle(vehicle, classes)


def resolve_typed_vehicle_selection(message_text: object, catalog: dict) -> dict | None:
    """Resolve only an unambiguous, clearly typed exact catalog choice.

    Questions which merely mention a car are intentionally ignored. A customer
    may type either the exact catalog label or a short choice phrase followed by
    that exact label; ``or similar`` remains optional for convenience.
    """
    raw_message = str(message_text or "").strip()
    if raw_message.endswith("?") and not _CLEAR_TYPED_CHOICE.match(raw_message):
        return None
    raw = raw_message.rstrip(".!")
    if not raw:
        return None
    candidate = _CLEAR_TYPED_CHOICE.sub("", raw, count=1).strip()
    candidate_label = _catalog_label(candidate)
    if not candidate_label:
        return None
    vehicles, classes = _active_catalog(catalog)
    matches = [
        vehicle
        for vehicle in vehicles.values()
        if _catalog_label(vehicle.get("name")) == candidate_label
    ]
    if len(matches) != 1:
        return None
    return _canonical_vehicle(matches[0], classes)


def invalid_vehicle_selection_reply(locale: object) -> str:
    """Return one concise, localized fail-closed picker clarification."""
    language = str(locale or "en").strip().lower()
    return {
        "en": "That car option is no longer valid. Please choose from the latest car options I send you.",
        "nl": "Die auto-optie is niet meer geldig. Kies alsjeblieft uit de nieuwste auto-opties die ik stuur.",
        "pap": "E opshon di outo ei no ta válido mas. Skohe for di e último opshonnan di outo ku mi manda bo.",
        "de": "Diese Fahrzeugoption ist nicht mehr gültig. Bitte wählen Sie aus den neuesten Fahrzeugoptionen, die ich Ihnen sende.",
    }.get(language, "That car option is no longer valid. Please choose from the latest car options I send you.")
