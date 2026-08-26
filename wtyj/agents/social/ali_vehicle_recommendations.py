"""Catalog-grounded presentation plans for Ali vehicle discovery.

Claude chooses the conversational action in its existing response. This module
only validates that structured action against Ali's authenticated catalog and
renders factual presentation data for the WhatsApp transport.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import urllib.parse

from shared import bm_logger


SUPPORTED_LOCALES = {"en", "nl", "pap", "de"}
_MONEY = re.compile(r"(?:0|[1-9]\d*)\.\d{2}")
_CARD_LABELS = {
    "en": {
        "seats": "seats",
        "choose_in_chat": "Choose in chat",
        "carousel_intro": "Swipe through the cars, then choose one in the chat.",
        "handoff_message": "I choose the {vehicle_name}.",
        "choose_one": "Choose this car",
        "choose_many": "Choose a car",
        "picker_body": "Choose your car below.",
        "picker_section": "Cars",
        "picker_fallback": "Reply with the number of the car you prefer:",
    },
    "nl": {
        "seats": "zitplaatsen",
        "choose_in_chat": "Kies in de chat",
        "carousel_intro": "Veeg door de auto's en kies er daarna één in de chat.",
        "handoff_message": "Ik kies voor de {vehicle_name}.",
        "choose_one": "Kies deze auto",
        "choose_many": "Kies een auto",
        "picker_body": "Kies hieronder je auto.",
        "picker_section": "Auto's",
        "picker_fallback": "Antwoord met het nummer van je gekozen auto:",
    },
    "pap": {
        "seats": "lugá",
        "choose_in_chat": "Skoge den chat",
        "carousel_intro": "Pasa dor di e outonan, despues skoge un den e chat.",
        "handoff_message": "Mi ta skoge e {vehicle_name}.",
        "choose_one": "Skoge e outo aki",
        "choose_many": "Skoge un outo",
        "picker_body": "Skoge bo outo aki bou.",
        "picker_section": "Outonan",
        "picker_fallback": "Kontestá ku e number di e outo ku bo ta preferá:",
    },
    "de": {
        "seats": "Sitzplätze",
        "choose_in_chat": "Im Chat wählen",
        "carousel_intro": (
            "Wischen Sie durch die Autos und wählen Sie dann eines im Chat aus."
        ),
        "handoff_message": "Ich wähle den {vehicle_name}.",
        "choose_one": "Dieses Auto wählen",
        "choose_many": "Auto auswählen",
        "picker_body": "Wählen Sie unten Ihr Auto aus.",
        "picker_section": "Autos",
        "picker_fallback": "Antworten Sie mit der Nummer Ihres gewünschten Autos:",
    },
}
_TRANSMISSIONS = {
    "automatic": {
        "en": "Automatic",
        "nl": "Automaat",
        "pap": "Outomátiko",
        "de": "Automatik",
    },
    "manual": {
        "en": "Manual",
        "nl": "Handgeschakeld",
        "pap": "Manual",
        "de": "Schaltung",
    },
}
_SELECTION_PREFIX = "ali_vehicle_select:v1:"


class AliVehicleRecommendationError(ValueError):
    """Structured recommendation failed safe catalog validation."""


def vehicle_selection_payload(vehicle_id: object) -> str:
    """Return a bounded opaque picker payload for one server-owned vehicle ID."""
    value = str(vehicle_id or "").strip()
    if (
        not value
        or len(value) > 160
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value)
    ):
        raise AliVehicleRecommendationError("invalid_vehicle_id")
    payload = f"{_SELECTION_PREFIX}{value}"
    if len(payload) > 200:
        raise AliVehicleRecommendationError("vehicle_selection_payload_too_long")
    return payload


def parse_vehicle_selection_payload(payload: object) -> str | None:
    """Extract an untrusted catalog ID candidate from a native picker payload.

    Callers must still validate the returned ID against the active tenant catalog.
    """
    value = str(payload or "").strip()
    if not value.startswith(_SELECTION_PREFIX):
        return None
    vehicle_id = value[len(_SELECTION_PREFIX):]
    try:
        expected = vehicle_selection_payload(vehicle_id)
    except AliVehicleRecommendationError:
        return None
    return vehicle_id if hmac.compare_digest(value, expected) else None


def _absolute_https_url(value: object, base_url: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise AliVehicleRecommendationError("missing_vehicle_url")
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", raw)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise AliVehicleRecommendationError("unsafe_vehicle_url")
    return url


def _whatsapp_handoff_url(
    destination: object,
    vehicle_name: str,
    locale: str,
) -> str:
    """Build a pure click-to-chat URL from tenant-owned configuration.

    Opening this URL cannot mutate rental state. WhatsApp only submits the
    human-readable choice after the customer explicitly taps Send, at which
    point the normal inbound webhook validates it against the active catalog.
    """
    raw_destination = str(destination or "").strip()
    digits = re.sub(r"\D", "", raw_destination)
    if not 7 <= len(digits) <= 15:
        raise AliVehicleRecommendationError("invalid_whatsapp_destination")
    message = _CARD_LABELS[locale]["handoff_message"].format(
        vehicle_name=vehicle_name,
    )
    encoded = urllib.parse.quote(message, safe="")
    return f"https://wa.me/{digits}?text={encoded}"


def _vehicle_image(vehicle: dict, base_url: str) -> tuple[str, str]:
    for image in vehicle.get("images") or []:
        if not isinstance(image, dict) or not str(image.get("url") or "").strip():
            continue
        return (
            _absolute_https_url(image.get("url"), base_url),
            str(image.get("alt") or vehicle.get("name") or "").strip(),
        )
    raise AliVehicleRecommendationError("missing_vehicle_image")


def _delivery_hashes(flags: dict) -> set[str]:
    hashes = set()
    for item in flags.get("ali_vehicle_recommendation_deliveries") or []:
        value = item.get("hash") if isinstance(item, dict) else item
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
            hashes.add(value)
    return hashes


def _catalog_vehicle(
    vehicle: dict,
    classes: dict[str, dict],
    locale: str,
    base_url: str,
) -> dict:
    public_id = str(vehicle.get("id") or "").strip()
    name = str(vehicle.get("name") or "").strip()
    slug = str(vehicle.get("slug") or "").strip()
    vehicle_class = classes.get(str(vehicle.get("classId") or ""))
    category = str((vehicle_class or {}).get("name") or "").strip()
    rate = vehicle.get("dailyRate") or {}
    amount = str(rate.get("amount") or "")
    if (
        not public_id
        or not name
        or not slug
        or not category
        or rate.get("currency") != "USD"
        or not _MONEY.fullmatch(amount)
    ):
        raise AliVehicleRecommendationError("invalid_catalog_vehicle")
    image_url, image_alt = _vehicle_image(vehicle, base_url)
    seats = vehicle.get("seats")
    if isinstance(seats, bool) or (seats is not None and not isinstance(seats, int)):
        raise AliVehicleRecommendationError("invalid_vehicle_capacity")
    transmission = str(vehicle.get("transmission") or "").strip().lower()
    if transmission and transmission not in _TRANSMISSIONS:
        raise AliVehicleRecommendationError("invalid_vehicle_transmission")
    detail_url = _absolute_https_url(f"/{locale}/fleet/{slug}", base_url)
    return {
        "id": public_id,
        "name": name,
        "category": category,
        "seats": seats,
        "transmission": transmission or None,
        "daily_usd": amount,
        "image_url": image_url,
        "image_alt": image_alt,
        "detail_url": detail_url,
        "selection_id": vehicle_selection_payload(public_id),
    }


def _card_body(option: dict, locale: str) -> str:
    lines = [option["name"], option["category"]]
    if option.get("seats") is not None:
        lines.append(f"{option['seats']} {_CARD_LABELS[locale]['seats']}")
    if option.get("transmission"):
        lines.append(_TRANSMISSIONS[option["transmission"]][locale])
    amount = option["daily_usd"]
    displayed_amount = amount[:-3] if amount.endswith(".00") else amount
    lines.append(f"USD ${displayed_amount}/day")
    return "\n".join(lines)


def _picker_description(option: dict, locale: str) -> str:
    details = [option["category"]]
    if option.get("seats") is not None:
        details.append(f"{option['seats']} {_CARD_LABELS[locale]['seats']}")
    displayed_amount = (
        option["daily_usd"][:-3]
        if option["daily_usd"].endswith(".00")
        else option["daily_usd"]
    )
    details.append(f"USD {displayed_amount}/day")
    return " · ".join(details)[:72]


def _picker_plan(options: list[dict], locale: str) -> dict:
    labels = _CARD_LABELS[locale]
    numbered_options = "\n".join(
        f"{index}. {option['name']}"
        for index, option in enumerate(options, start=1)
    )
    return {
        "text": labels["picker_body"],
        "button": labels["choose_many"],
        "sections": [{
            "title": labels["picker_section"],
            "rows": [{
                "id": option["selection_id"],
                "title": option["name"][:24],
                "description": _picker_description(option, locale),
            } for option in options],
        }],
        "fallback_text": f"{labels['picker_fallback']}\n{numbered_options}",
    }


def build_vehicle_picker_recovery(
    catalog: dict,
    fields: dict,
    flags: dict,
    reply_text: str,
    *,
    public_base_url: str | None = None,
    turn_id: str | None = None,
) -> dict | None:
    """Rebuild only the last safe native picker from the current catalog.

    Invalid, stale, or cross-tenant action payloads never select by label. The
    recovery branch revalidates the exact previously offered server IDs against
    the active catalog and preserves their order. If no safe branch remains,
    the caller sends only its clarification instead of inventing options.
    """
    locale = str(fields.get("conversation_language") or "en").lower()
    if locale not in SUPPORTED_LOCALES:
        locale = "en"
    base_url = str(
        public_base_url
        or os.environ.get("ALI_QUOTE_API_BASE_URL")
        or "https://alicarrental.com"
    ).strip()
    classes = {
        str(item.get("id")): item
        for item in catalog.get("vehicleClasses") or []
        if isinstance(item, dict)
        and item.get("id")
        and item.get("active", True) is not False
    }
    vehicles = {
        str(item.get("id") or "").strip(): item
        for item in catalog.get("vehicles") or []
        if isinstance(item, dict)
        and str(item.get("id") or "").strip()
        and item.get("active", True) is not False
    }
    ordered_ids = []
    for value in flags.get("ali_last_recommendation_ids") or []:
        vehicle_id = str(value or "").strip()
        if vehicle_id and vehicle_id not in ordered_ids:
            ordered_ids.append(vehicle_id)
    options = []
    for vehicle_id in ordered_ids[:5]:
        vehicle = vehicles.get(vehicle_id)
        if vehicle is None:
            continue
        try:
            options.append(_catalog_vehicle(vehicle, classes, locale, base_url))
        except AliVehicleRecommendationError:
            continue
    if not options:
        return None

    fingerprint = {
        "catalog_version": catalog.get("catalogVersion"),
        "mode": "picker_recovery",
        "vehicle_ids": [option["id"] for option in options],
        "turn_id": str(turn_id or "")[:200],
    }
    state_hash = hashlib.sha256(
        json.dumps(
            fingerprint,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    plan = {
        "kind": "picker",
        "mode": "recovery",
        "state_hash": state_hash,
        "idempotency_key": f"ali-vehicle-{state_hash}",
        "text": str(reply_text or "").strip(),
        "options": options,
    }
    if len(options) == 1:
        plan["buttons"] = [{
            "type": "postback",
            "title": _CARD_LABELS[locale]["choose_one"],
            "payload": options[0]["selection_id"],
        }]
        plan["fallback_text"] = (
            f"{_CARD_LABELS[locale]['picker_fallback']}\n1. {options[0]['name']}"
        )
    else:
        picker = _picker_plan(options, locale)
        picker["text"] = str(reply_text or "").strip()
        plan["picker"] = picker
    return plan


def build_vehicle_recommendation(
    action: object,
    catalog: dict,
    fields: dict,
    flags: dict,
    reply_text: str,
    *,
    public_base_url: str | None = None,
    whatsapp_destination: str | None = None,
    turn_id: str | None = None,
) -> dict | None:
    """Return one validated image/carousel delivery plan or ``None``.

    The function never reads customer prose. It routes only on Claude's
    structured action and server-owned catalog fields.
    """
    if not isinstance(action, dict):
        return None
    mode = str(action.get("mode") or "").strip().lower()
    if mode not in {"specific", "curated"}:
        return None
    names = action.get("vehicle_names")
    expected_count = 1 if mode == "specific" else None
    if (
        not isinstance(names, list)
        or (expected_count is not None and len(names) != expected_count)
        or (mode == "curated" and not 2 <= len(names) <= 5)
        or any(not isinstance(name, str) or not name.strip() for name in names)
    ):
        raise AliVehicleRecommendationError("invalid_recommendation_count")
    if len({name.strip().casefold() for name in names}) != len(names):
        raise AliVehicleRecommendationError("duplicate_recommendation")

    locale = str(fields.get("conversation_language") or "en").lower()
    if locale not in SUPPORTED_LOCALES:
        raise AliVehicleRecommendationError("unsupported_locale")
    availability_note = str(action.get("availability_note") or "").strip()
    cta_label = str(action.get("cta_label") or "").strip()
    if not availability_note or len(availability_note) > 160:
        raise AliVehicleRecommendationError("invalid_availability_note")
    if not cta_label or len(cta_label) > 24 or "\n" in cta_label:
        raise AliVehicleRecommendationError("invalid_cta_label")
    conversational_text = str(reply_text or "").strip()
    if not conversational_text:
        raise AliVehicleRecommendationError("missing_recommendation_reply")

    base_url = str(
        public_base_url
        or os.environ.get("ALI_QUOTE_API_BASE_URL")
        or "https://alicarrental.com"
    ).strip()
    classes = {
        str(item.get("id")): item
        for item in catalog.get("vehicleClasses") or []
        if isinstance(item, dict) and item.get("id")
    }
    vehicles_by_name = {
        str(item.get("name") or "").strip().casefold(): item
        for item in catalog.get("vehicles") or []
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    options = []
    for requested_name in names:
        vehicle = vehicles_by_name.get(requested_name.strip().casefold())
        if vehicle is None:
            raise AliVehicleRecommendationError("vehicle_not_in_catalog")
        options.append(_catalog_vehicle(vehicle, classes, locale, base_url))

    passenger_count = fields.get("passenger_count")
    if mode == "curated":
        if (
            isinstance(passenger_count, bool)
            or not isinstance(passenger_count, int)
            or passenger_count < 1
        ):
            raise AliVehicleRecommendationError("missing_passenger_count")
        if any(
            option.get("seats") is not None and option["seats"] < passenger_count
            for option in options
        ):
            raise AliVehicleRecommendationError("unsuitable_vehicle_capacity")

    fingerprint = {
        "catalog_version": catalog.get("catalogVersion"),
        "mode": mode,
        "vehicle_ids": [option["id"] for option in options],
        "passenger_count": passenger_count,
        "luggage_count": fields.get("luggage_count"),
    }
    normalized_turn_id = str(turn_id or "").strip()
    if normalized_turn_id:
        fingerprint["turn_id"] = normalized_turn_id[:200]
    state_hash = hashlib.sha256(
        json.dumps(
            fingerprint,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if state_hash in _delivery_hashes(flags):
        bm_logger.log(
            "ali_vehicle_recommendation_suppressed",
            mode=mode,
            recommendation_hash=state_hash[:12],
            reason="already_delivered",
        )
        return None

    text = f"{conversational_text}\n\n{availability_note}"
    plan = {
        "kind": "image" if mode == "specific" else "carousel",
        "mode": mode,
        "state_hash": state_hash,
        "idempotency_key": f"ali-vehicle-{state_hash}",
        "text": text,
        "options": options,
    }
    if mode == "specific":
        option = options[0]
        plan["text"] = f"{conversational_text}\n\n{_card_body(option, locale)}\n\n{availability_note}"
        plan["buttons"] = [{
            "type": "postback",
            "title": _CARD_LABELS[locale]["choose_one"],
            "payload": option["selection_id"],
        }]
    else:
        carousel_text = (
            f"{_CARD_LABELS[locale]['carousel_intro']}\n\n{availability_note}"
        )
        plan["text"] = carousel_text
        plan["cards"] = [{
            "card_index": index,
            "type": "cta_url",
            "header": {
                "type": "image",
                "image": {"link": option["image_url"]},
            },
            "body": {"text": _card_body(option, locale)},
            "action": {
                "name": "cta_url",
                "parameters": {
                    # Zernio cards expose URL CTAs, not per-card postbacks.
                    # The link only opens the tenant's WhatsApp chat with a
                    # draft. The customer must Send before selection occurs.
                    "display_text": _CARD_LABELS[locale]["choose_in_chat"],
                    "url": _whatsapp_handoff_url(
                        whatsapp_destination,
                        option["name"],
                        locale,
                    ),
                },
            },
        } for index, option in enumerate(options)]
        plan["picker"] = _picker_plan(options, locale)
    bm_logger.log(
        "ali_vehicle_recommendation_planned",
        mode=mode,
        option_count=len(options),
        catalog_version=catalog.get("catalogVersion"),
        recommendation_hash=state_hash[:12],
    )
    return plan
