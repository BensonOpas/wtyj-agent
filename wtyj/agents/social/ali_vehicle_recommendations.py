"""Catalog-grounded presentation plans for Ali vehicle discovery.

Claude chooses the conversational action in its existing response. This module
only validates that structured action against Ali's authenticated catalog and
renders factual presentation data for the WhatsApp transport.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse

from shared import bm_logger


SUPPORTED_LOCALES = {"en", "nl", "pap", "de"}
_MONEY = re.compile(r"(?:0|[1-9]\d*)\.\d{2}")
_CARD_LABELS = {
    "en": {"seats": "seats"},
    "nl": {"seats": "zitplaatsen"},
    "pap": {"seats": "lugá"},
    "de": {"seats": "Sitzplätze"},
}


class AliVehicleRecommendationError(ValueError):
    """Structured recommendation failed safe catalog validation."""


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
    detail_url = _absolute_https_url(f"/{locale}/fleet/{slug}", base_url)
    return {
        "id": public_id,
        "name": name,
        "category": category,
        "seats": seats,
        "daily_usd": amount,
        "image_url": image_url,
        "image_alt": image_alt,
        "detail_url": detail_url,
    }


def _card_body(option: dict, locale: str) -> str:
    lines = [option["name"], option["category"]]
    if option.get("seats") is not None:
        lines.append(f"{option['seats']} {_CARD_LABELS[locale]['seats']}")
    amount = option["daily_usd"]
    displayed_amount = amount[:-3] if amount.endswith(".00") else amount
    lines.append(f"USD ${displayed_amount}/day")
    return "\n".join(lines)


def build_vehicle_recommendation(
    action: object,
    catalog: dict,
    fields: dict,
    flags: dict,
    reply_text: str,
    *,
    public_base_url: str | None = None,
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
        or (mode == "curated" and not 2 <= len(names) <= 3)
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
    else:
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
                    "display_text": cta_label,
                    "url": option["detail_url"],
                },
            },
        } for index, option in enumerate(options)]
    bm_logger.log(
        "ali_vehicle_recommendation_planned",
        mode=mode,
        option_count=len(options),
        catalog_version=catalog.get("catalogVersion"),
        recommendation_hash=state_hash[:12],
    )
    return plan
