"""Deterministic media-first policy for Ali vehicle discovery turns."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


_DISCOVERY_INTENTS = {"request_recommendation", "reject_or_hesitate"}
_COPY = {
    "en": {
        "intro_one": "Here is the car we discussed. Does this one feel right for your trip?",
        "intro_many": "Here are a few options that may suit your trip. Which one do you prefer?",
        "availability": "Final vehicle availability still needs confirmation.",
        "cta": "View car",
        "needs_passengers": "How many people will be travelling in the car?",
        "needs_luggage": "How much luggage will you be bringing?",
    },
    "nl": {
        "intro_one": "Hier is de auto die we bespraken. Past deze bij je reis?",
        "intro_many": "Hier zijn een paar opties die bij je reis kunnen passen. Welke heeft je voorkeur?",
        "availability": "De definitieve voertuigbeschikbaarheid moet nog worden bevestigd.",
        "cta": "Bekijk auto",
        "needs_passengers": "Met hoeveel personen reizen jullie in de auto?",
        "needs_luggage": "Hoeveel bagage nemen jullie mee?",
    },
    "pap": {
        "intro_one": "Aki ta e outo ku nos a papia di dje. E ta pas ku bo biahe?",
        "intro_many": "Aki tin algun opshon ku por pas ku bo biahe. Kua bo ta preferá?",
        "availability": "Disponibilidat final di e outo mester wordu konfirmá ainda.",
        "cta": "Mira outo",
        "needs_passengers": "Kuantu persona lo biaha den e outo?",
        "needs_luggage": "Kuantu ekipahe boso lo hiba?",
    },
    "de": {
        "intro_one": "Hier ist das besprochene Auto. Passt es zu Ihrer Reise?",
        "intro_many": "Hier sind einige passende Optionen. Welches Auto bevorzugen Sie?",
        "availability": "Die endgültige Fahrzeugverfügbarkeit muss noch bestätigt werden.",
        "cta": "Auto ansehen",
        "needs_passengers": "Wie viele Personen fahren im Auto mit?",
        "needs_luggage": "Wie viel Gepäck bringen Sie mit?",
    },
}


def _locale(fields: dict) -> str:
    value = str(fields.get("conversation_language") or "en").strip().lower()
    return value if value in _COPY else "en"


def _active_visual_vehicles(catalog: dict) -> list[dict]:
    return [
        item
        for item in catalog.get("vehicles") or []
        if isinstance(item, dict)
        and str(item.get("id") or "").strip()
        and str(item.get("name") or "").strip()
        and item.get("active", True) is not False
        and any(
            isinstance(image, dict) and str(image.get("url") or "").strip()
            for image in item.get("images") or []
        )
    ]


def _amount(vehicle: dict) -> Decimal:
    try:
        return Decimal(str((vehicle.get("dailyRate") or {}).get("amount") or "999999"))
    except InvalidOperation:
        return Decimal("999999")


def _catalog_order(vehicle: dict) -> tuple:
    order = vehicle.get("displayOrder")
    if isinstance(order, bool) or not isinstance(order, int):
        order = 999999
    return order, _amount(vehicle), str(vehicle.get("name") or "").casefold()


def _mentioned_vehicles(reply_text: str, vehicles: list[dict]) -> list[dict]:
    haystack = str(reply_text or "").casefold()
    return [
        vehicle
        for vehicle in vehicles
        if str(vehicle.get("name") or "").strip().casefold() in haystack
    ]


def _ids(flags: dict, key: str) -> set[str]:
    values = flags.get(key) or []
    return {
        str(value).strip()
        for value in values
        if isinstance(value, str) and str(value).strip()
    }


def _structured_names(action: object) -> list[str]:
    if not isinstance(action, dict):
        return []
    names = action.get("vehicle_names")
    if not isinstance(names, list):
        return []
    return [str(name).strip() for name in names if str(name).strip()]


def derive_media_first_action(
    primary_intent: object,
    structured_action: object,
    reply_text: str,
    fields: dict,
    flags: dict,
    catalog: dict,
) -> dict:
    """Return one deterministic media-first action decision.

    This policy never parses arbitrary customer prose. It consumes #195's
    structured primary intent, the model's catalog names when supplied, and
    canonical server-owned catalog/state fields.
    """
    intent = str(primary_intent or "").strip().lower()
    explicit_names = _structured_names(structured_action)
    if intent not in _DISCOVERY_INTENTS and not explicit_names:
        return {"status": "not_discovery", "action": None}

    locale = _locale(fields)
    copy = _COPY[locale]
    vehicles = _active_visual_vehicles(catalog)
    vehicles_by_name = {
        str(vehicle["name"]).strip().casefold(): vehicle
        for vehicle in vehicles
    }

    candidates = [
        vehicles_by_name[name.casefold()]
        for name in explicit_names
        if name.casefold() in vehicles_by_name
    ]
    reason = "structured_action" if candidates else ""
    if not candidates:
        candidates = _mentioned_vehicles(reply_text, vehicles)
        reason = "catalog_names_in_reply" if candidates else ""

    selected_id = str(fields.get("vehicle_id") or "").strip()
    last_ids = _ids(flags, "ali_last_recommendation_ids")
    rejected_ids = _ids(flags, "ali_rejected_vehicle_ids")
    shown_ids = _ids(flags, "ali_shown_vehicle_ids")
    excluded_ids = set(rejected_ids)
    if intent == "reject_or_hesitate":
        excluded_ids.update(last_ids)
        if selected_id:
            excluded_ids.add(selected_id)

    if not candidates and intent == "request_recommendation" and selected_id:
        candidates = [
            vehicle
            for vehicle in vehicles
            if str(vehicle.get("id") or "") == selected_id
        ]
        reason = "selected_vehicle_picture" if candidates else ""

    class_id = str(fields.get("vehicle_class_id") or "").strip()
    class_name = str(fields.get("vehicle_class_name") or "").strip().casefold()
    classes = {
        str(item.get("id") or "").strip(): str(item.get("name") or "").strip()
        for item in catalog.get("vehicleClasses") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    if not class_id and class_name:
        class_id = next(
            (
                item_id
                for item_id, name in classes.items()
                if name.casefold() == class_name
            ),
            "",
        )
    if not candidates and class_id:
        candidates = [
            vehicle
            for vehicle in vehicles
            if str(vehicle.get("classId") or "") == class_id
        ]
        reason = "selected_category" if candidates else ""

    passenger_count = fields.get("passenger_count")
    luggage_count = fields.get("luggage_count")
    if not candidates:
        if (
            isinstance(passenger_count, bool)
            or not isinstance(passenger_count, int)
            or passenger_count < 1
        ):
            return {
                "status": "needs_context",
                "action": None,
                "reply_text": copy["needs_passengers"],
                "reason": "missing_passenger_count",
            }
        if (
            isinstance(luggage_count, bool)
            or not isinstance(luggage_count, int)
            or luggage_count < 0
        ):
            return {
                "status": "needs_context",
                "action": None,
                "reply_text": copy["needs_luggage"],
                "reason": "missing_luggage_count",
            }
        candidates = [
            vehicle
            for vehicle in vehicles
            if vehicle.get("seats") is None
            or (
                isinstance(vehicle.get("seats"), int)
                and not isinstance(vehicle.get("seats"), bool)
                and vehicle["seats"] >= passenger_count
            )
        ]
        reason = "capacity_curated"

    unique = {}
    for vehicle in candidates:
        vehicle_id = str(vehicle.get("id") or "").strip()
        if vehicle_id and vehicle_id not in excluded_ids:
            unique.setdefault(vehicle_id, vehicle)
    candidates = sorted(unique.values(), key=_catalog_order)

    if not explicit_names and intent == "reject_or_hesitate":
        unshown = [
            vehicle
            for vehicle in candidates
            if str(vehicle.get("id") or "") not in shown_ids
        ]
        if unshown:
            candidates = unshown
    candidates = candidates[:5]
    if not candidates:
        return {
            "status": "needs_context",
            "action": None,
            "reply_text": copy["needs_luggage"],
            "reason": "no_unseen_suitable_options",
        }

    mode = "specific" if len(candidates) == 1 else "curated"
    intro = copy["intro_one"] if mode == "specific" else copy["intro_many"]
    return {
        "status": "planned",
        "action": {
            "mode": mode,
            "vehicle_names": [str(vehicle["name"]).strip() for vehicle in candidates],
            "availability_note": copy["availability"],
            "cta_label": copy["cta"],
        },
        "reply_text": str(reply_text or "").strip() if explicit_names else intro,
        "vehicle_ids": [str(vehicle["id"]).strip() for vehicle in candidates],
        "reason": reason,
    }
