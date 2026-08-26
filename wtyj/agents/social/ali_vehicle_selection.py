"""Deterministic Ali vehicle selection from native WhatsApp taps."""

from __future__ import annotations

import re

from agents.social.ali_vehicle_recommendations import (
    parse_vehicle_selection_payload,
)


_SUPPORTED_INTERACTIVE_TYPES = {"buttonreply", "listreply"}


class AliVehicleSelectionError(ValueError):
    """A vehicle picker payload failed active tenant-catalog validation."""


def _interactive_type(value: object) -> str:
    return re.sub(r"[^a-z]", "", str(value or "").strip().lower())


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
        return None
    if vehicle_id is None:
        return None

    vehicles = {
        str(item.get("id") or "").strip(): item
        for item in catalog.get("vehicles") or []
        if isinstance(item, dict)
        and str(item.get("id") or "").strip()
        and item.get("active", True) is not False
    }
    vehicle = vehicles.get(vehicle_id)
    if vehicle is None:
        raise AliVehicleSelectionError("vehicle_selection_not_active")

    classes = {
        str(item.get("id") or "").strip(): item
        for item in catalog.get("vehicleClasses") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    class_id = str(vehicle.get("classId") or "").strip()
    vehicle_class = classes.get(class_id)
    vehicle_name = str(vehicle.get("name") or "").strip()
    class_name = str((vehicle_class or {}).get("name") or "").strip()
    if not vehicle_name or not class_id or not class_name:
        raise AliVehicleSelectionError("vehicle_selection_catalog_invalid")

    return {
        "vehicle_id": vehicle_id,
        "vehicle_name": vehicle_name,
        "vehicle_class_id": class_id,
        "vehicle_class_name": class_name,
    }
