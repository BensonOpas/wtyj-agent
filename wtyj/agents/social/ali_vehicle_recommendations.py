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
_OR_SIMILAR_SUFFIX = re.compile(r"\s+or\s+similar\s*$", re.IGNORECASE)
_PICKER_TITLE_LIMIT = 24
_CARD_LABELS = {
    "en": {
        "seats": "seats",
        "luggage_one": "Cargo: approx. 1 medium suitcase",
        "luggage_many": "Cargo: approx. {count} medium suitcases",
        "bags_one": "1 suitcase",
        "bags_many": "{count} suitcases",
        "details": "Car Details",
        "choose_one": "Choose This Car",
        "choose_many": "Choose A Car",
        "picker_body": "Choose your car below.",
        "picker_section": "Cars",
        "picker_fallback": "Reply with the number of the car you prefer:",
    },
    "nl": {
        "seats": "zitplaatsen",
        "luggage_one": "Bagageruimte: ca. 1 middelgrote koffer",
        "luggage_many": "Bagageruimte: ca. {count} middelgrote koffers",
        "bags_one": "1 koffer",
        "bags_many": "{count} koffers",
        "details": "Autodetails",
        "choose_one": "Kies Deze Auto",
        "choose_many": "Kies Een Auto",
        "picker_body": "Kies hieronder je auto.",
        "picker_section": "Auto's",
        "picker_fallback": "Antwoord met het nummer van je gekozen auto:",
    },
    "pap": {
        "seats": "lugá",
        "luggage_one": "Espasio di ekipahe: aprox. 1 maleta mediano",
        "luggage_many": "Espasio di ekipahe: aprox. {count} maleta mediano",
        "bags_one": "1 maleta",
        "bags_many": "{count} maleta",
        "details": "Detayenan Di Outo",
        "choose_one": "Skoge E Outo Aki",
        "choose_many": "Skoge Un Outo",
        "picker_body": "Skoge bo outo aki bou.",
        "picker_section": "Outonan",
        "picker_fallback": "Kontestá ku e number di e outo ku bo ta preferá:",
    },
    "de": {
        "seats": "Sitzplätze",
        "luggage_one": "Gepäckraum: ca. 1 mittelgroßer Koffer",
        "luggage_many": "Gepäckraum: ca. {count} mittelgroße Koffer",
        "bags_one": "1 Koffer",
        "bags_many": "{count} Koffer",
        "details": "Fahrzeugdetails",
        "choose_one": "Dieses Auto Wählen",
        "choose_many": "Auto Auswählen",
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
    catalog_version: object,
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
    if (
        isinstance(catalog_version, bool)
        or not isinstance(catalog_version, int)
        or catalog_version < 1
    ):
        raise AliVehicleRecommendationError("invalid_catalog_version")
    whatsapp_image_url = _absolute_https_url(
        "/api/v1/vehicle-media/"
        f"{urllib.parse.quote(public_id, safe='')}?v={catalog_version}",
        base_url,
    )
    seats = vehicle.get("seats")
    if isinstance(seats, bool) or (seats is not None and not isinstance(seats, int)):
        raise AliVehicleRecommendationError("invalid_vehicle_capacity")
    luggage_capacity = vehicle.get("luggageCapacity")
    if (
        isinstance(luggage_capacity, bool)
        or (
            luggage_capacity is not None
            and (
                not isinstance(luggage_capacity, int)
                or luggage_capacity < 0
                or luggage_capacity > 20
            )
        )
    ):
        raise AliVehicleRecommendationError("invalid_vehicle_luggage_capacity")
    transmission = str(vehicle.get("transmission") or "").strip().lower()
    if transmission and transmission not in _TRANSMISSIONS:
        raise AliVehicleRecommendationError("invalid_vehicle_transmission")
    detail_url = _absolute_https_url(f"/{locale}/fleet/{slug}", base_url)
    return {
        "id": public_id,
        "name": name,
        "category": category,
        "seats": seats,
        "luggage_capacity": luggage_capacity,
        "transmission": transmission or None,
        "daily_usd": amount,
        "image_url": image_url,
        "whatsapp_image_url": whatsapp_image_url,
        "image_alt": image_alt,
        "detail_url": detail_url,
        "selection_id": vehicle_selection_payload(public_id),
    }


def _card_body(option: dict, locale: str) -> str:
    lines = [option["name"], option["category"]]
    if option.get("seats") is not None:
        lines.append(f"{option['seats']} {_CARD_LABELS[locale]['seats']}")
    luggage_capacity = option.get("luggage_capacity")
    if isinstance(luggage_capacity, int) and luggage_capacity > 0:
        key = "luggage_one" if luggage_capacity == 1 else "luggage_many"
        lines.append(
            _CARD_LABELS[locale][key].format(count=luggage_capacity)
        )
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
    luggage_capacity = option.get("luggage_capacity")
    if isinstance(luggage_capacity, int) and luggage_capacity > 0:
        key = "bags_one" if luggage_capacity == 1 else "bags_many"
        details.append(
            _CARD_LABELS[locale][key].format(count=luggage_capacity)
        )
    displayed_amount = (
        option["daily_usd"][:-3]
        if option["daily_usd"].endswith(".00")
        else option["daily_usd"]
    )
    details.append(f"USD {displayed_amount}/day")
    return " · ".join(details)[:72]


def _picker_title(value: object) -> str:
    """Return a complete, bounded vehicle label for a WhatsApp picker row.

    WhatsApp limits list-row titles to 24 characters. The full catalog name is
    retained everywhere else; only the redundant trailing category disclaimer
    is omitted in this compact control. Longer names are shortened at a word
    boundary instead of exposing a misleading fragment such as "simi".
    """
    name = " ".join(str(value or "").split())
    preferred = _OR_SIMILAR_SUFFIX.sub("", name).strip() or name
    if len(preferred) <= _PICKER_TITLE_LIMIT:
        return preferred

    ellipsis = "…"
    candidate = preferred[:_PICKER_TITLE_LIMIT - len(ellipsis)].rstrip()
    cut_index = _PICKER_TITLE_LIMIT - len(ellipsis)
    split_word = (
        candidate
        and not preferred[cut_index].isspace()
        and not preferred[:cut_index].endswith(" ")
    )
    if split_word and " " in candidate:
        candidate = candidate.rsplit(" ", 1)[0].rstrip()
    if not candidate:
        candidate = preferred[:_PICKER_TITLE_LIMIT - len(ellipsis)].rstrip()
    return f"{candidate}{ellipsis}"


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
                "title": _picker_title(option["name"]),
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
    trigger_message_id: str | None = None,
    trigger_sent_at: str | None = None,
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
            options.append(_catalog_vehicle(
                vehicle, classes, locale, base_url, catalog.get("catalogVersion"),
            ))
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
        "trigger_message_id": str(trigger_message_id or "").strip()[:240],
        "trigger_sent_at": str(trigger_sent_at or "").strip()[:80],
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


def rebuild_vehicle_recommendation(
    snapshot: dict,
    catalog: dict,
    *,
    public_base_url: str | None = None,
) -> dict | None:
    """Rebuild a persisted recommendation from the current public catalog.

    Only server-owned vehicle IDs and presentation text are reused. Vehicle
    facts, proxy URLs, picker rows, and cards are regenerated from the current
    catalog so a late provider retry cannot resurrect unpublished inventory.
    """
    if not isinstance(snapshot, dict):
        return None
    kind = str(snapshot.get("kind") or "")
    if kind not in {"image", "carousel"}:
        return None
    locale = str(snapshot.get("locale") or "en").lower()
    if locale not in SUPPORTED_LOCALES:
        return None
    vehicle_ids = [
        str(value or "").strip()
        for value in snapshot.get("vehicle_ids") or []
        if str(value or "").strip()
    ][:5]
    if not vehicle_ids or (kind == "image" and len(vehicle_ids) != 1):
        return None
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
    options = []
    try:
        for vehicle_id in vehicle_ids:
            vehicle = vehicles.get(vehicle_id)
            if vehicle is None:
                return None
            options.append(_catalog_vehicle(
                vehicle, classes, locale, base_url, catalog.get("catalogVersion"),
            ))
    except AliVehicleRecommendationError:
        return None
    text = str(snapshot.get("text") or "").strip()
    state_hash = str(snapshot.get("state_hash") or "")
    if not text or not re.fullmatch(r"[0-9a-f]{64}", state_hash):
        return None
    plan = {
        "kind": kind,
        "mode": str(snapshot.get("mode") or ""),
        "locale": locale,
        "state_hash": state_hash,
        "idempotency_key": f"ali-vehicle-{state_hash}",
        "text": text,
        "options": options,
        "trigger_message_id": str(
            snapshot.get("trigger_message_id") or ""
        ).strip()[:240],
        "trigger_sent_at": str(
            snapshot.get("trigger_sent_at") or ""
        ).strip()[:80],
    }
    if kind == "image":
        plan["buttons"] = [{
            "type": "postback",
            "title": _CARD_LABELS[locale]["choose_one"],
            "payload": options[0]["selection_id"],
        }]
    else:
        plan["cards"] = [{
            "card_index": index,
            "type": "cta_url",
            "header": {
                "type": "image",
                "image": {"link": option["whatsapp_image_url"]},
            },
            "body": {"text": _card_body(option, locale)},
            "action": {
                "name": "cta_url",
                "parameters": {
                    "display_text": _CARD_LABELS[locale]["details"],
                    "url": option["detail_url"],
                },
            },
        } for index, option in enumerate(options)]
        plan["picker"] = _picker_plan(options, locale)
    return plan


def build_vehicle_recommendation(
    action: object,
    catalog: dict,
    fields: dict,
    flags: dict,
    reply_text: str,
    *,
    public_base_url: str | None = None,
    turn_id: str | None = None,
    trigger_message_id: str | None = None,
    trigger_sent_at: str | None = None,
    allow_repeat: bool = False,
    capacity_advisory: bool = False,
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
        options.append(_catalog_vehicle(
            vehicle, classes, locale, base_url, catalog.get("catalogVersion"),
        ))

    passenger_count = fields.get("passenger_count")
    if mode == "curated":
        passenger_count_missing = bool(
            isinstance(passenger_count, bool)
            or not isinstance(passenger_count, int)
            or passenger_count < 1
        )
        # Passenger count is optional and never gates a carousel. When it is
        # unknown, cards communicate capacity without claiming group fit.
        if not passenger_count_missing and not capacity_advisory and any(
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
    if allow_repeat and normalized_turn_id:
        fingerprint["turn_id"] = normalized_turn_id[:200]
    if capacity_advisory:
        fingerprint["capacity_advisory"] = True
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
        "locale": locale,
        "state_hash": state_hash,
        "idempotency_key": f"ali-vehicle-{state_hash}",
        "text": text,
        "options": options,
        "trigger_message_id": str(trigger_message_id or "").strip()[:240],
        "trigger_sent_at": str(trigger_sent_at or "").strip()[:80],
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
        plan["cards"] = [{
            "card_index": index,
            "type": "cta_url",
            "header": {
                "type": "image",
                "image": {"link": option["whatsapp_image_url"]},
            },
            "body": {"text": _card_body(option, locale)},
            "action": {
                "name": "cta_url",
                "parameters": {
                    # Zernio media-carousel cards require a CTA URL button.
                    # It is a details link, never a selection control; the
                    # native picker sent immediately afterwards owns choice.
                    "display_text": _CARD_LABELS[locale]["details"],
                    "url": option["detail_url"],
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
