"""Deterministic media-first policy for Ali vehicle discovery turns."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
import unicodedata


_DISCOVERY_INTENTS = {"request_recommendation", "reject_or_hesitate"}
_VISUAL_REQUEST = re.compile(
    r"\b(?:photo|photos|picture|pictures|image|images|foto|foto['’]?s|"
    r"afbeelding|afbeeldingen|bild|bilder|potr[eè]t|potr[eè]tnan|"
    r"show|see|view|toon|mira|mustra|zeigen|ansehen)\b",
    re.IGNORECASE,
)
_VEHICLE_CONTEXT = re.compile(
    r"\b(?:car|cars|vehicle|vehicles|auto|auto['’]?s|outo|outonan|wagen|"
    r"suv|van|economy|compact)\b",
    re.IGNORECASE,
)
_ALTERNATIVE_REQUEST = re.compile(
    r"\b(?:what else|anything else|other|another|alternative|alternatives|"
    r"option|options|smaller|larger|kleiner|groter|andere|alternatief|"
    r"opshon|otro|mas chik[ií]|m[aá]s grandi|anders|kleiner|gr[oö][sß]er)\b",
    re.IGNORECASE,
)
_RECOMMENDATION_REQUEST = re.compile(
    r"\b(?:recommend|recommendation|suggest|suggestion|suitable|best car|"
    r"aanraden|advies|geschikt|rekomend[aá]|sugerensia|"
    r"empfehlen|empfehlung|geeignet)\b",
    re.IGNORECASE,
)
_REJECTION = re.compile(
    r"\b(?:don['’]?t like|do not like|doesn['’]?t work|does not work|"
    r"not right|nope|nee|niet goed|no ta bon|mi no ke|gef[aä]llt nicht|"
    r"passt nicht|changed? my mind|reconsider|bedacht|van gedachten|"
    r"kambia di idea|cambié de idea|anders entschieden)\b",
    re.IGNORECASE,
)
_NEGATIVE_CLASS_PREFIX = re.compile(
    r"(?:don t|do not|not|no|niet|geen|no ke|nicht|kein|keinen|keine)\s+"
    r"(?:want|prefer|need|wil|ke|möchte|will|bevorzuge|suche)?\s*"
    r"(?:(?:a|an|the|een|un|e|ein|eine|einen)\s+)?$",
    re.IGNORECASE,
)
_POSITIVE_CLASS_PREFIX = re.compile(
    r"(?:want|prefer|need|choose|select|wil|wilt|kies|zoek|ke|skohe|"
    r"möchte|will|wähle|suche|bevorzuge)\s+"
    r"(?:(?:a|an|the|een|un|e|ein|eine|einen)\s+)?$",
    re.IGNORECASE,
)
_PUNCTUATION_ONLY_REPAIR = re.compile(r"^[\s?!.,;:\-–—…¡¿]+$")
_REENGAGEMENT = re.compile(
    r"^(?:hi|hello|hey|hallo|hoi|bon\s+(?:dia|tardi|nochi)|guten\s+tag)[!.?\s]*$",
    re.IGNORECASE,
)
_COPY = {
    "en": {
        "intro_one": "Here is a car that matches what you asked for. Does this one feel right for your trip?",
        "intro_many": "Here are a few options that may suit your trip. Which one do you prefer?",
        "availability": "Final vehicle availability still needs confirmation.",
        "cta": "Car details",
        "needs_passengers": "How many people will be travelling in the car?",
        "needs_luggage": "How much luggage will you be bringing?",
        "clarify_preference": "Would you prefer a smaller car, an SUV, or a van?",
        "repair_category": "Sorry, I wasn't clear. I have {category} as your preferred category, but you haven't selected a specific car yet. How many people will be travelling in the car?",
        "resume_category": "Hi! I have {category} as your preferred category. How many people will be travelling in the car?",
        "repair_vehicle": "Sorry, I wasn't clear. I have {vehicle} as your selected car. What rental dates do you need?",
        "resume_vehicle": "Hi! I have {vehicle} as your selected car. What rental dates do you need?",
        "repair_general": "Sorry, I wasn't clear. What would you like me to explain?",
    },
    "nl": {
        "intro_one": "Hier is een auto die past bij wat je zoekt. Past deze bij je reis?",
        "intro_many": "Hier zijn een paar opties die bij je reis kunnen passen. Welke heeft je voorkeur?",
        "availability": "De definitieve voertuigbeschikbaarheid moet nog worden bevestigd.",
        "cta": "Autodetails",
        "needs_passengers": "Met hoeveel personen reizen jullie in de auto?",
        "needs_luggage": "Hoeveel bagage nemen jullie mee?",
        "clarify_preference": "Heb je liever een kleinere auto, een SUV of een busje?",
        "repair_category": "Sorry, ik was niet duidelijk. Ik heb {category} als je voorkeurscategorie, maar je hebt nog geen specifieke auto gekozen. Met hoeveel personen reizen jullie?",
        "resume_category": "Hallo! Ik heb {category} als je voorkeurscategorie. Met hoeveel personen reizen jullie?",
        "repair_vehicle": "Sorry, ik was niet duidelijk. Ik heb {vehicle} als je gekozen auto. Voor welke data wil je huren?",
        "resume_vehicle": "Hallo! Ik heb {vehicle} als je gekozen auto. Voor welke data wil je huren?",
        "repair_general": "Sorry, ik was niet duidelijk. Wat wil je dat ik uitleg?",
    },
    "pap": {
        "intro_one": "Aki tin un outo ku ta pas ku loke bo ta buska. E ta pas ku bo biahe?",
        "intro_many": "Aki tin algun opshon ku por pas ku bo biahe. Kua bo ta preferá?",
        "availability": "Disponibilidat final di e outo mester wordu konfirmá ainda.",
        "cta": "Detayenan di outo",
        "needs_passengers": "Kuantu persona lo biaha den e outo?",
        "needs_luggage": "Kuantu ekipahe boso lo hiba?",
        "clarify_preference": "Bo ta preferá un outo mas chikí, un SUV òf un van?",
        "repair_category": "Pordon, mi no tabata kla. Mi tin {category} komo bo preferensia, pero bo no a skohe un outo spesífiko ainda. Kuantu persona lo biaha den e outo?",
        "resume_category": "Bon dia! Mi tin {category} komo bo preferensia. Kuantu persona lo biaha den e outo?",
        "repair_vehicle": "Pordon, mi no tabata kla. Mi tin {vehicle} komo e outo ku bo a skohe. Pa kua fechanan bo ke huur'é?",
        "resume_vehicle": "Bon dia! Mi tin {vehicle} komo e outo ku bo a skohe. Pa kua fechanan bo ke huur'é?",
        "repair_general": "Pordon, mi no tabata kla. Kiko bo ke pa mi splika?",
    },
    "de": {
        "intro_one": "Hier ist ein Auto, das zu Ihrer Anfrage passt. Passt es zu Ihrer Reise?",
        "intro_many": "Hier sind einige passende Optionen. Welches Auto bevorzugen Sie?",
        "availability": "Die endgültige Fahrzeugverfügbarkeit muss noch bestätigt werden.",
        "cta": "Fahrzeugdetails",
        "needs_passengers": "Wie viele Personen fahren im Auto mit?",
        "needs_luggage": "Wie viel Gepäck bringen Sie mit?",
        "clarify_preference": "Bevorzugen Sie einen kleineren Wagen, einen SUV oder einen Van?",
        "repair_category": "Entschuldigung, ich war nicht klar. Ich habe {category} als Ihre bevorzugte Kategorie, aber noch kein bestimmtes Auto. Wie viele Personen fahren mit?",
        "resume_category": "Hallo! Ich habe {category} als Ihre bevorzugte Kategorie. Wie viele Personen fahren mit?",
        "repair_vehicle": "Entschuldigung, ich war nicht klar. Ich habe {vehicle} als Ihr gewähltes Auto. Für welche Daten möchten Sie mieten?",
        "resume_vehicle": "Hallo! Ich habe {vehicle} als Ihr gewähltes Auto. Für welche Daten möchten Sie mieten?",
        "repair_general": "Entschuldigung, ich war nicht klar. Was soll ich erklären?",
    },
}


def explicit_visual_request(message_text: object) -> bool:
    """Return true only when the customer explicitly asks to see vehicle media."""
    return bool(_VISUAL_REQUEST.search(str(message_text or "")))


def conversation_repair_reply(
    message_text: object,
    fields: dict,
    flags: dict,
) -> str:
    """Own a confused/nudging turn without mutating selection or sending media."""
    text = str(message_text or "").strip()
    punctuation_only = bool(text and _PUNCTUATION_ONLY_REPAIR.fullmatch(text))
    has_vehicle_context = bool(
        fields.get("vehicle_id")
        or fields.get("vehicle_class_id")
        or fields.get("vehicle_class_name")
        or _ids(flags, "ali_last_recommendation_ids")
    )
    reengagement = bool(has_vehicle_context and _REENGAGEMENT.fullmatch(text))
    if not punctuation_only and not reengagement:
        return ""

    copy = _COPY[_locale(fields)]
    category = str(fields.get("vehicle_class_name") or "").strip()
    vehicle = str(fields.get("vehicle_name") or "").strip()
    if category:
        key = "resume_category" if reengagement else "repair_category"
        return copy[key].format(category=category)
    if vehicle:
        key = "resume_vehicle" if reengagement else "repair_vehicle"
        return copy[key].format(vehicle=vehicle)
    return copy["repair_general"]


def _locale(fields: dict) -> str:
    value = str(fields.get("conversation_language") or "en").strip().lower()
    return value if value in _COPY else "en"


def media_first_clarification(fields: dict) -> str:
    """Return one safe question when a discovery plan cannot be rendered."""
    copy = _COPY[_locale(fields)]
    passenger_count = fields.get("passenger_count")
    if (
        isinstance(passenger_count, bool)
        or not isinstance(passenger_count, int)
        or passenger_count < 1
    ):
        return copy["needs_passengers"]
    luggage_count = fields.get("luggage_count")
    if (
        isinstance(luggage_count, bool)
        or not isinstance(luggage_count, int)
        or luggage_count < 0
    ):
        return copy["needs_luggage"]
    return copy["clarify_preference"]


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


def infer_media_first_intent(
    message_text: str,
    reply_text: str,
    structured_action: object,
    fields: dict,
    flags: dict,
    catalog: dict,
) -> str:
    """Provide a deterministic fallback until #195 supplies primary intent."""
    customer_text = str(message_text or "")
    has_vehicle_context = bool(
        _VEHICLE_CONTEXT.search(customer_text)
        or fields.get("vehicle_id")
        or fields.get("vehicle_class_id")
        or fields.get("vehicle_class_name")
        or _ids(flags, "ali_last_recommendation_ids")
    )
    reopens_comparison = bool(
        _ALTERNATIVE_REQUEST.search(customer_text)
        or _RECOMMENDATION_REQUEST.search(customer_text)
    )
    if (
        _REJECTION.search(customer_text)
        and (
            _ids(flags, "ali_last_recommendation_ids")
            or fields.get("vehicle_id")
            or fields.get("vehicle_class_id")
        )
    ):
        return "reject_or_hesitate"
    if (
        has_vehicle_context
        and reopens_comparison
        and (
            fields.get("vehicle_id")
            or fields.get("vehicle_class_id")
            or _ids(flags, "ali_last_recommendation_ids")
        )
    ):
        return "reject_or_hesitate"
    if _structured_names(structured_action):
        return "request_recommendation"
    if _RECOMMENDATION_REQUEST.search(customer_text):
        return "request_recommendation"
    vehicles = _active_visual_vehicles(catalog)
    mentioned = _mentioned_vehicles(reply_text, vehicles)
    if len(mentioned) >= 2:
        return "request_recommendation"

    if has_vehicle_context and _VISUAL_REQUEST.search(customer_text):
        return "request_recommendation"
    if has_vehicle_context and reopens_comparison:
        return "request_recommendation"
    return ""


def infer_explicit_catalog_class_selection(
    message_text: object,
    catalog: dict,
) -> dict | None:
    """Resolve one explicit positive catalog-class discovery request.

    This is a narrow fallback for turns where the model omits its independent
    vehicle-change action. It accepts only an active server-owned class label
    that the customer mentions in a positive choice/discovery context. It
    never maps a display label to a vehicle and never guesses a category.
    """
    normalized = unicodedata.normalize(
        "NFKC", str(message_text or ""),
    ).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).strip()
    if not normalized:
        return None

    has_discovery_request = bool(
        _VISUAL_REQUEST.search(str(message_text or ""))
        or _RECOMMENDATION_REQUEST.search(str(message_text or ""))
        or _ALTERNATIVE_REQUEST.search(str(message_text or ""))
    )
    candidates = []
    for vehicle_class in catalog.get("vehicleClasses") or []:
        if not isinstance(vehicle_class, dict):
            continue
        class_id = str(vehicle_class.get("id") or "").strip()
        class_name = str(vehicle_class.get("name") or "").strip()
        if not class_id or not class_name or vehicle_class.get("active", True) is False:
            continue
        label = unicodedata.normalize("NFKC", class_name).casefold()
        label = re.sub(r"[^\w]+", " ", label, flags=re.UNICODE).strip()
        if not label:
            continue
        for match in re.finditer(rf"(?<!\w){re.escape(label)}(?!\w)", normalized):
            prefix = normalized[max(0, match.start() - 80):match.start()]
            if _NEGATIVE_CLASS_PREFIX.search(prefix):
                continue
            if (
                normalized == label
                or has_discovery_request
                or _POSITIVE_CLASS_PREFIX.search(prefix)
            ):
                candidates.append((len(label.split()), class_id, class_name))
                break

    if not candidates:
        return None
    longest = max(item[0] for item in candidates)
    matches = {(item[1], item[2]) for item in candidates if item[0] == longest}
    if len(matches) != 1:
        return None
    class_id, class_name = next(iter(matches))
    return {
        "vehicle_class_id": class_id,
        "vehicle_class_name": class_name,
    }


def catalog_class_recommendation_action(
    selection: object,
    catalog: dict,
) -> dict | None:
    """Build a recommendation action from one validated active class."""
    if not isinstance(selection, dict):
        return None
    class_id = str(selection.get("vehicle_class_id") or "").strip()
    class_name = str(selection.get("vehicle_class_name") or "").strip()
    active_class = next(
        (
            item
            for item in catalog.get("vehicleClasses") or []
            if isinstance(item, dict)
            and str(item.get("id") or "").strip() == class_id
            and str(item.get("name") or "").strip() == class_name
            and item.get("active", True) is not False
        ),
        None,
    )
    if active_class is None:
        return None
    vehicles = sorted(
        (
            vehicle
            for vehicle in _active_visual_vehicles(catalog)
            if str(vehicle.get("classId") or "").strip() == class_id
        ),
        key=_catalog_order,
    )[:5]
    if not vehicles:
        return None
    return {
        "mode": "specific" if len(vehicles) == 1 else "curated",
        "vehicle_names": [str(vehicle["name"]).strip() for vehicle in vehicles],
        "selection_context": "category",
    }


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
    if not candidates and intent in _DISCOVERY_INTENTS:
        mentioned = _mentioned_vehicles(reply_text, vehicles)
        # One car name in Nick's own prose is not proof that the customer
        # selected or requested that car. Preserve only the multi-car safety
        # net that converts an accidental text dump into visual options.
        if len(mentioned) >= 2:
            candidates = mentioned
            reason = "catalog_names_in_reply"

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
            "reply_text": media_first_clarification(fields),
            "reason": "no_unseen_suitable_options",
        }

    if len(candidates) >= 2:
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
        "reply_text": (
            intro
            if not explicit_names
            or (
                isinstance(structured_action, dict)
                and structured_action.get("selection_context") == "category"
            )
            else str(reply_text or "").strip()
        ),
        "vehicle_ids": [str(vehicle["id"]).strip() for vehicle in candidates],
        "reason": reason,
    }
