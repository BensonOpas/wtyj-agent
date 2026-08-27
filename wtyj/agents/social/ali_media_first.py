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
_LOWEST_PRICE_REQUEST = re.compile(
    r"\b(?:cheapest|lowest[- ]price(?:d)?|least expensive|most affordable|"
    r"most economic(?:al)?|"
    r"goedkoopste|laagste prijs|voordeligste|"
    r"mas barata|mas barato|preis mas abou|mas ekonomiko|"
    r"g[uü]nstig(?:ste|sten|ster|stes)|billigste|niedrigste[nr]? preis|"
    r"preiswerteste)\b",
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
_BROWSE_REQUEST = re.compile(
    r"(?:\bshow\s+me\s+(?:what|which(?:\s+kinds?\s+of)?\s+(?:cars?|vehicles?|options?))"
    r"|\bshow\s+(?:me\s+)?(?:the\s+)?(?:cars?|vehicles?|options?|fleet)\b"
    r"|\bwhat\s+(?:(?:kinds?\s+of)\s+)?(?:cars?|vehicles?|options?)?\s*"
    r"(?:do\s+)?(?:you|ya)\s+have\b"
    r"|\bwhich\s+(?:cars?|vehicles?|options?)\s+(?:do\s+)?you\s+have\b"
    r"|\bmore\s+(?:cars?|vehicles?|options?)\b"
    r"|\bwat\s+(?:voor\s+)?(?:auto['’]?s|wagens|opties)\s+heb(?:ben)?\s+(?:je|jullie)\b"
    r"|\bwat\s+heb(?:ben)?\s+(?:je|jullie)\b"
    r"|\blaat\s+(?:me|mij)\s+zien\s+wat\b"
    r"|\bkiko\s+bo\s+tin\b"
    r"|\bkua\s+outo(?:nan)?\s+bo\s+tin\b"
    r"|\bmustra\s+mi\s+(?:kiko|loke|e\s+outo(?:nan)?)\b"
    r"|\bwas\s+haben\s+(?:sie|ihr)\b"
    r"|\bwelche\s+(?:autos?|fahrzeuge?|optionen)\s+haben\s+(?:sie|ihr)\b"
    r"|\bzeigen\s+sie\s+mir\s+(?:was|die\s+(?:autos?|fahrzeuge?))\b)",
    re.IGNORECASE,
)
_SMALLER_REQUEST = re.compile(
    r"\b(?:smaller|small|compact|economy|kleiner|kleine|kleines|compacte|"
    r"mas\s+chik[ií]|chik[ií]|kleinere|kompakt)\b"
    r"(?:\s+(?:car|cars|vehicle|vehicles|one|option|auto|auto['’]?s|outo|"
    r"outonan|wagen|fahrzeug))?",
    re.IGNORECASE,
)
_NEGATED_SMALLER_REQUEST = re.compile(
    r"\b(?:don['’]?t|do\s+not|not|no|niet|geen|mi\s+no\s+ke|nicht|kein|keine|keinen)\b"
    r".{0,32}\b(?:smaller|small|compact|economy|kleiner|kleine|kleines|compacte|"
    r"mas\s+chik[ií]|chik[ií]|kleinere|kompakt)\b",
    re.IGNORECASE,
)
_NO_PREFERENCE_REQUEST = re.compile(
    r"^(?:whatever|anything|any(?:\s+car)?|no\s+preference|"
    r"doesn['’]?t\s+matter|maakt\s+niet\s+uit|geen\s+voorkeur|"
    r"kualke|no\s+tin\s+preferensia|egal|keine\s+präferenz)[.!?\s]*$",
    re.IGNORECASE,
)
_PERSONAL_DETAIL_REQUEST = re.compile(
    r"(?:\b(?:what(?:'s|\s+is)|tell\s+me|may\s+i\s+have|can\s+i\s+have)\s+"
    r"(?:your\s+)?(?:full\s+)?name\b"
    r"|\bhow\s+old\s+are\s+you\b|\bdriver(?:'s)?\s+age\b|\byour\s+email\b"
    r"|\bwat\s+is\s+(?:je|uw)\s+(?:volledige\s+)?naam\b|\bhoe\s+oud\s+ben\s+(?:je|u)\b"
    r"|\bkiko\s+ta\s+bo\s+n[òo]mber\b|\bkuantu\s+a[ñn]a\s+bo\s+tin\b"
    r"|\bwie\s+hei(?:ß|ss)t\s+(?:du|sie)\b|\bwie\s+ist\s+(?:ihr|dein)\s+(?:vollst[aä]ndiger\s+)?name\b"
    r"|\bwie\s+alt\s+sind\s+sie\b)",
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
        "lowest_price_many": "{vehicle} is the lowest-priced suitable option at USD {price} per day. I’ve included the closest alternatives so you can compare.",
        "lowest_price_one": "{vehicle} is the lowest-priced suitable option at USD {price} per day.",
        "browse_many": "Here are a few cars from our current fleet. Swipe through them and tell me which one you prefer.",
        "browse_capacity": "Here are a few cars from our current fleet. Seat capacity is shown on each card; cars with fewer than {passengers} seats will not fit your full group. Which one would you like to compare?",
        "smaller_many": "Here are the smaller cars. Which one would you like to look at?",
        "smaller_capacity": "Here are the smaller cars. They seat up to {max_seats}, so if {passengers} people are travelling, you’ll need a larger option. Which one would you like to look at?",
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
        "lowest_price_many": "{vehicle} is de voordeligste passende optie voor USD {price} per dag. Ik heb de dichtstbijzijnde alternatieven toegevoegd zodat je kunt vergelijken.",
        "lowest_price_one": "{vehicle} is de voordeligste passende optie voor USD {price} per dag.",
        "browse_many": "Hier zijn een paar auto's uit ons huidige wagenpark. Bekijk ze en laat me weten welke je voorkeur heeft.",
        "browse_capacity": "Hier zijn een paar auto's uit ons huidige wagenpark. Op elke kaart staat het aantal zitplaatsen; auto's met minder dan {passengers} zitplaatsen zijn te klein voor je hele groep. Welke wil je vergelijken?",
        "smaller_many": "Hier zijn de kleinere auto's. Welke wil je bekijken?",
        "smaller_capacity": "Hier zijn de kleinere auto's. Ze hebben maximaal {max_seats} zitplaatsen, dus als er {passengers} personen reizen, heb je een grotere optie nodig. Welke wil je bekijken?",
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
        "lowest_price_many": "{vehicle} ta e opshon adekuá ku preis mas abou: USD {price} pa dia. Mi a agregá e alternativanan mas serka pa bo por kompará.",
        "lowest_price_one": "{vehicle} ta e opshon adekuá ku preis mas abou: USD {price} pa dia.",
        "browse_many": "Aki tin algun outo for di nos flota aktual. Mira nan i laga mi sa kua bo ta preferá.",
        "browse_capacity": "Aki tin algun outo for di nos flota aktual. Kada karta ta mustra e kantidat di asiento; outonan ku ménos ku {passengers} asiento ta chikí pa henter bo grupo. Kua bo ke kompará?",
        "smaller_many": "Aki tin e outonan mas chikí. Kua bo ke mira?",
        "smaller_capacity": "Aki tin e outonan mas chikí. Nan tin te ku {max_seats} asiento, pues si {passengers} persona ta biaha, bo tin mester di un opshon mas grandi. Kua bo ke mira?",
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
        "lowest_price_many": "{vehicle} ist mit USD {price} pro Tag die günstigste passende Option. Ich habe die nächstgelegenen Alternativen zum Vergleichen hinzugefügt.",
        "lowest_price_one": "{vehicle} ist mit USD {price} pro Tag die günstigste passende Option.",
        "browse_many": "Hier sind einige Autos aus unserer aktuellen Flotte. Sehen Sie sie durch und sagen Sie mir, welches Sie bevorzugen.",
        "browse_capacity": "Hier sind einige Autos aus unserer aktuellen Flotte. Die Sitzplatzanzahl steht auf jeder Karte; Fahrzeuge mit weniger als {passengers} Sitzen sind für Ihre gesamte Gruppe zu klein. Welches möchten Sie vergleichen?",
        "smaller_many": "Hier sind die kleineren Autos. Welches möchten Sie ansehen?",
        "smaller_capacity": "Hier sind die kleineren Autos. Sie haben bis zu {max_seats} Sitzplätze. Wenn {passengers} Personen mitfahren, benötigen Sie eine größere Option. Welches möchten Sie ansehen?",
    },
}


def explicit_visual_request(message_text: object) -> bool:
    """Return true only when the customer explicitly asks to see vehicle media."""
    return bool(_VISUAL_REQUEST.search(str(message_text or "")))


def explicit_catalog_browse_request(message_text: object) -> bool:
    """Recognize a clear request to browse the current fleet in four locales."""
    return bool(_BROWSE_REQUEST.search(str(message_text or "")))


def explicit_smaller_vehicle_request(message_text: object) -> bool:
    """Recognize a positive smaller-car preference without accepting negation."""
    text = str(message_text or "")
    return bool(
        _SMALLER_REQUEST.search(text)
        and not _NEGATED_SMALLER_REQUEST.search(text)
    )


def explicit_no_preference_request(message_text: object) -> bool:
    """Recognize a concise request to choose from any suitable current car."""
    return bool(_NO_PREFERENCE_REQUEST.fullmatch(str(message_text or "").strip()))


def enforce_vehicle_first_reply(reply_text: object, fields: dict) -> str:
    """Block personal-detail collection until a vehicle direction is chosen."""
    text = str(reply_text or "").strip()
    has_selection = bool(
        fields.get("vehicle_id")
        or fields.get("vehicle_name")
        or fields.get("vehicle_class_id")
        or fields.get("vehicle_class_name")
    )
    if has_selection or not _PERSONAL_DETAIL_REQUEST.search(text):
        return text
    return media_first_clarification(fields)


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


def _lowest_price_order(vehicle: dict) -> tuple:
    return _amount(vehicle), _catalog_order(vehicle)


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
        explicit_catalog_browse_request(customer_text)
        or explicit_smaller_vehicle_request(customer_text)
        or explicit_no_preference_request(customer_text)
    ):
        return "request_recommendation"
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
    message_text: str = "",
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
    lowest_price_requested = bool(
        _LOWEST_PRICE_REQUEST.search(str(message_text or ""))
    )
    browse_requested = explicit_catalog_browse_request(message_text)
    smaller_requested = explicit_smaller_vehicle_request(message_text)
    no_preference_requested = explicit_no_preference_request(message_text)

    candidates = [
        vehicles_by_name[name.casefold()]
        for name in explicit_names
        if name.casefold() in vehicles_by_name
    ]
    if lowest_price_requested:
        # The model may suggest valid vehicles but it does not own price
        # ranking. For an explicit cheapest request, Python recomputes the
        # candidate set from the current server catalog.
        candidates = []
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
    # A clear "whatever / no preference" reopens suitable catalog choices,
    # including a previously rejected car. Without this reset a tenant with
    # only one capacity-suitable vehicle can fall back into clarification.
    excluded_ids = set() if no_preference_requested else set(rejected_ids)
    if intent == "reject_or_hesitate":
        excluded_ids.update(last_ids)
        if selected_id:
            excluded_ids.add(selected_id)
    elif intent == "request_recommendation" and _ALTERNATIVE_REQUEST.search(
        str(message_text or "")
    ):
        # Asking for another/smaller option reopens discovery without
        # permanently recording the previous car as rejected.
        excluded_ids.update(last_ids)

    if (
        not candidates
        and intent == "request_recommendation"
        and selected_id
        and not browse_requested
        and not smaller_requested
    ):
        candidates = [
            vehicle
            for vehicle in vehicles
            if str(vehicle.get("id") or "") == selected_id
        ]
        reason = "selected_vehicle_picture" if candidates else ""

    if not candidates and smaller_requested:
        class_names = {
            str(item.get("id") or "").strip(): str(item.get("name") or "").casefold()
            for item in catalog.get("vehicleClasses") or []
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
        candidates = [
            vehicle
            for vehicle in vehicles
            if isinstance(vehicle.get("seats"), int)
            and not isinstance(vehicle.get("seats"), bool)
            and vehicle["seats"] <= 5
            and not any(
                token in class_names.get(str(vehicle.get("classId") or ""), "")
                for token in ("suv", "van")
            )
        ]
        reason = "explicit_smaller_preference" if candidates else ""

    if not candidates and browse_requested:
        candidates = list(vehicles)
        reason = "explicit_catalog_browse"

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
    if lowest_price_requested:
        candidates = []
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
        reason = (
            "lowest_price_catalog"
            if lowest_price_requested else "capacity_curated"
        )

    unique = {}
    for vehicle in candidates:
        vehicle_id = str(vehicle.get("id") or "").strip()
        if vehicle_id and vehicle_id not in excluded_ids:
            unique.setdefault(vehicle_id, vehicle)
    if (
        browse_requested
        and isinstance(passenger_count, int)
        and not isinstance(passenger_count, bool)
        and passenger_count > 0
    ):
        candidates = sorted(
            unique.values(),
            key=lambda vehicle: (
                0
                if vehicle.get("seats") is None
                or (
                    isinstance(vehicle.get("seats"), int)
                    and not isinstance(vehicle.get("seats"), bool)
                    and vehicle["seats"] >= passenger_count
                )
                else 1,
                _catalog_order(vehicle),
            ),
        )
    else:
        candidates = sorted(
            unique.values(),
            key=_lowest_price_order if lowest_price_requested else _catalog_order,
        )

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
    if browse_requested:
        intro = copy["browse_many"]
        if (
            isinstance(passenger_count, int)
            and not isinstance(passenger_count, bool)
            and any(
                isinstance(vehicle.get("seats"), int)
                and not isinstance(vehicle.get("seats"), bool)
                and vehicle["seats"] < passenger_count
                for vehicle in candidates
            )
        ):
            intro = copy["browse_capacity"].format(
                passengers=passenger_count,
            )
    if smaller_requested and not explicit_names:
        max_seats = max(
            (
                int(vehicle["seats"])
                for vehicle in candidates
                if isinstance(vehicle.get("seats"), int)
                and not isinstance(vehicle.get("seats"), bool)
            ),
            default=0,
        )
        if (
            isinstance(passenger_count, int)
            and not isinstance(passenger_count, bool)
            and max_seats > 0
            and passenger_count > max_seats
        ):
            intro = copy["smaller_capacity"].format(
                max_seats=max_seats,
                passengers=passenger_count,
            )
        else:
            intro = copy["smaller_many"]
    if lowest_price_requested:
        cheapest = candidates[0]
        amount = _amount(cheapest)
        price = f"{amount:.2f}"
        intro = copy[
            "lowest_price_one" if mode == "specific" else "lowest_price_many"
        ].format(
            vehicle=str(cheapest.get("name") or "").strip(),
            price=price,
        )
    return {
        "status": "planned",
        "action": {
            "mode": mode,
            "vehicle_names": [str(vehicle["name"]).strip() for vehicle in candidates],
            "availability_note": copy["availability"],
            "cta_label": copy["cta"],
        },
        # Recommendations are deterministic product surfaces. Do not retain
        # a model-added personal-data question in the same message before the
        # customer has chosen one of the displayed options.
        "reply_text": intro,
        "vehicle_ids": [str(vehicle["id"]).strip() for vehicle in candidates],
        "reason": reason,
    }
