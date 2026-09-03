"""Deterministic WhatsApp-first intake for Mermaid's reservation demo.

The language model is deliberately not trusted with money, availability,
booking codes, or payment state. This module extracts customer-supplied facts,
asks one question at a time, and persists progress in the existing WhatsApp
state store.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import dateparser

from shared import mermaid_catalog, state_registry


SUPPORTED_LOCALES = ("en", "nl", "de", "es", "pap", "pt")
REQUIRED_FIELDS = (
    "trip_date", "adults", "children", "infants", "customer_name", "pickup_preference"
)


COPY = {
    "en": {
        "intro": "Hi, I’m TRACY, Mermaid’s virtual reservation assistant. I’ll arrange your trip and prepare the full demo quote right here in WhatsApp.",
        "trip_date": "What date would you like to visit Klein Curaçao?",
        "adults": "How many adults are traveling?",
        "children": "How many children aged 4 to 12 are traveling? Reply 0 if none.",
        "infants": "How many children aged 0 to 3 are traveling? Reply 0 if none.",
        "name": "What full name should I put on the reservation?",
        "pickup": "Will you meet us at Fishermen’s Pier, or would you like to request hotel pickup?",
        "hotel": "Which hotel or pickup location should I include in the request?",
        "composition": "How many are adults, children aged 4 to 12, and children aged 0 to 3?",
        "confirm": "Please reply *YES* if everything is correct, or tell me exactly what to change.",
        "confirmed": "Perfect, I have your confirmed details. I’m preparing your demo reservation and quote now.",
        "cancelled": "Your demo reservation request is cancelled. No payment was taken.",
        "human": "Of course. I’ve paused TRACY and passed the conversation to Mermaid’s team with your progress saved.",
        "invalid_day": "Mermaid’s published trips run Monday, Tuesday, Wednesday, Friday, Saturday and Sunday. Please choose one of those days.",
    },
    "nl": {
        "intro": "Hoi, ik ben TRACY, Mermaid’s virtuele reserveringsassistent. Ik regel je trip en maak de volledige demo-offerte hier in WhatsApp.",
        "trip_date": "Welke datum wil je Klein Curaçao bezoeken?",
        "adults": "Met hoeveel volwassenen reizen jullie?",
        "children": "Hoeveel kinderen van 4 tot en met 12 jaar reizen mee? Antwoord 0 als er geen zijn.",
        "infants": "Hoeveel kinderen van 0 tot en met 3 jaar reizen mee? Antwoord 0 als er geen zijn.",
        "name": "Welke volledige naam mag ik op de reservering zetten?",
        "pickup": "Komen jullie naar Fishermen’s Pier of willen jullie hoteltransfer aanvragen?",
        "hotel": "Welk hotel of welke ophaallocatie mag ik in de aanvraag zetten?",
        "composition": "Hoeveel volwassenen, kinderen van 4 tot en met 12 en kinderen van 0 tot en met 3 zijn het?",
        "confirm": "Antwoord met *JA* als alles klopt, of zeg precies wat ik moet aanpassen.",
        "confirmed": "Perfect, ik heb je gegevens bevestigd. Ik maak nu je demo-reservering en offerte.",
        "cancelled": "Je demo-reserveringsaanvraag is geannuleerd. Er is niets betaald.",
        "human": "Natuurlijk. Ik heb TRACY gepauzeerd en het gesprek met de opgeslagen gegevens doorgegeven aan Mermaid’s team.",
        "invalid_day": "Mermaid vaart volgens de publicatie op maandag, dinsdag, woensdag, vrijdag, zaterdag en zondag. Kies een van die dagen.",
    },
    "de": {
        "intro": "Hallo, ich bin TRACY, Mermaids virtuelle Reservierungsassistentin. Ich organisiere Ihren Ausflug und erstelle das vollständige Demo-Angebot hier in WhatsApp.",
        "trip_date": "An welchem Datum möchten Sie Klein Curaçao besuchen?",
        "adults": "Wie viele Erwachsene reisen mit?",
        "children": "Wie viele Kinder von 4 bis 12 Jahren reisen mit? Antworten Sie 0, wenn keine mitreisen.",
        "infants": "Wie viele Kinder von 0 bis 3 Jahren reisen mit? Antworten Sie 0, wenn keine mitreisen.",
        "name": "Auf welchen vollständigen Namen soll ich reservieren?",
        "pickup": "Treffen Sie uns am Fishermen’s Pier oder möchten Sie eine Hotelabholung anfragen?",
        "hotel": "Welches Hotel oder welchen Abholort soll ich in die Anfrage aufnehmen?",
        "composition": "Wie viele Erwachsene, Kinder von 4 bis 12 und Kinder von 0 bis 3 Jahren sind es?",
        "confirm": "Antworten Sie mit *JA*, wenn alles stimmt, oder nennen Sie genau die gewünschte Änderung.",
        "confirmed": "Perfekt, Ihre Angaben sind bestätigt. Ich erstelle jetzt Ihre Demo-Reservierung und Ihr Angebot.",
        "cancelled": "Ihre Demo-Reservierungsanfrage wurde storniert. Es wurde nichts bezahlt.",
        "human": "Natürlich. Ich habe TRACY pausiert und das Gespräch mit dem gespeicherten Stand an Mermaids Team übergeben.",
        "invalid_day": "Mermaid fährt laut Veröffentlichung Montag, Dienstag, Mittwoch, Freitag, Samstag und Sonntag. Bitte wählen Sie einen dieser Tage.",
    },
    "es": {
        "intro": "Hola, soy TRACY, la asistente virtual de reservas de Mermaid. Organizaré tu paseo y prepararé la cotización demo completa aquí en WhatsApp.",
        "trip_date": "¿Qué fecha quieres visitar Klein Curaçao?",
        "adults": "¿Cuántos adultos viajan?",
        "children": "¿Cuántos niños de 4 a 12 años viajan? Responde 0 si no hay.",
        "infants": "¿Cuántos niños de 0 a 3 años viajan? Responde 0 si no hay.",
        "name": "¿Qué nombre completo debo poner en la reserva?",
        "pickup": "¿Se encontrarán con nosotros en Fishermen’s Pier o desean solicitar recogida en el hotel?",
        "hotel": "¿Qué hotel o lugar de recogida debo incluir en la solicitud?",
        "composition": "¿Cuántos son adultos, niños de 4 a 12 y niños de 0 a 3 años?",
        "confirm": "Responde *SÍ* si todo está correcto o dime exactamente qué debo cambiar.",
        "confirmed": "Perfecto, tus datos están confirmados. Ahora preparo tu reserva demo y cotización.",
        "cancelled": "Tu solicitud de reserva demo está cancelada. No se realizó ningún pago.",
        "human": "Claro. He pausado a TRACY y pasé la conversación al equipo de Mermaid con tu progreso guardado.",
        "invalid_day": "Según la información publicada, Mermaid opera lunes, martes, miércoles, viernes, sábado y domingo. Elige uno de esos días.",
    },
    "pap": {
        "intro": "Bon dia, mi ta TRACY, asistente virtual di reservashon di Mermaid. Mi ta regla bo trip i prepara e oferta demo kompleto aki mes den WhatsApp.",
        "trip_date": "Ki fecha bo ke bishitá Klein Curaçao?",
        "adults": "Kuantu adulto ta bai?",
        "children": "Kuantu mucha di 4 te ku 12 aña ta bai? Kontestá 0 si no tin.",
        "infants": "Kuantu mucha di 0 te ku 3 aña ta bai? Kontestá 0 si no tin.",
        "name": "Ki nòmber kompleto mi por pone riba e reservashon?",
        "pickup": "Boso ta bini Fishermen’s Pier òf boso ke pidi pickup na hotel?",
        "hotel": "Ki hotel òf lugá di pickup mi mester pone den e petishon?",
        "composition": "Kuantu ta adulto, mucha di 4 te ku 12 i mucha di 0 te ku 3 aña?",
        "confirm": "Kontestá *SI* si tur kos ta korekto, òf bisa mi eksaktamente kiko mester kambia.",
        "confirmed": "Perfekto, bo datonan ta konfirmá. Awor mi ta prepara bo reservashon demo i oferta.",
        "cancelled": "Bo petishon di reservashon demo ta kanselá. No a tuma ningun pago.",
        "human": "Sigur. Mi a pone TRACY na pausa i pasa e kombersashon ku bo progreso wardá pa tim di Mermaid.",
        "invalid_day": "Segun e informashon publiká, Mermaid ta bai djaluna, djamars, djarason, djabièrnè, djasabra i djadumingu. Skohe un di e dianan ei.",
    },
    "pt": {
        "intro": "Olá, sou a TRACY, assistente virtual de reservas da Mermaid. Vou organizar seu passeio e preparar a cotação demo completa aqui no WhatsApp.",
        "trip_date": "Em que data você quer visitar Klein Curaçao?",
        "adults": "Quantos adultos vão viajar?",
        "children": "Quantas crianças de 4 a 12 anos vão viajar? Responda 0 se não houver.",
        "infants": "Quantas crianças de 0 a 3 anos vão viajar? Responda 0 se não houver.",
        "name": "Qual nome completo devo colocar na reserva?",
        "pickup": "Vocês irão ao Fishermen’s Pier ou desejam solicitar traslado do hotel?",
        "hotel": "Qual hotel ou local de embarque devo incluir no pedido?",
        "composition": "Quantos são adultos, crianças de 4 a 12 e crianças de 0 a 3 anos?",
        "confirm": "Responda *SIM* se estiver tudo correto ou diga exatamente o que devo alterar.",
        "confirmed": "Perfeito, seus dados estão confirmados. Agora vou preparar sua reserva demo e cotação.",
        "cancelled": "Seu pedido de reserva demo foi cancelado. Nenhum pagamento foi realizado.",
        "human": "Claro. Pausei a TRACY e encaminhei a conversa para a equipe da Mermaid com seu progresso salvo.",
        "invalid_day": "Segundo as informações publicadas, a Mermaid opera segunda, terça, quarta, sexta, sábado e domingo. Escolha um desses dias.",
    },
}


LANGUAGE_MARKERS = {
    "nl": ("graag", "hoeveel", "volwassen", "kinderen", "ophalen", "datum"),
    "de": ("möchte", "erwachsene", "kinder", "abholung", "datum", "bitte"),
    "es": ("quiero", "adultos", "niños", "recogida", "fecha", "somos"),
    "pap": ("mi ke", "kuantu", "mucha", "hende", "fecha", "por fabor", "reservashon"),
    "pt": ("quero", "adultos", "crianças", "traslado", "data", "somos"),
}

YES = {
    "en": {"yes", "yes correct", "correct", "confirmed", "confirm"},
    "nl": {"ja", "ja klopt", "klopt", "bevestigd", "bevestigen"},
    "de": {"ja", "ja korrekt", "korrekt", "bestätigt", "bestätigen"},
    "es": {"sí", "si", "sí correcto", "correcto", "confirmar", "confirmado"},
    "pap": {"si", "ta korekto", "korekto", "konfirmá"},
    "pt": {"sim", "sim correto", "correto", "confirmar", "confirmado"},
}


@dataclass(frozen=True)
class IntakeResult:
    text: str
    locale: str
    phase: str
    action: str | None = None
    duplicate: bool = False

    def as_reply(self) -> dict:
        return {
            "text": self.text,
            "media": None,
            "vehicle_recommendation": None,
            "quote_confirmation": None,
            "ali_turn_commit": None,
            "mermaid_action": self.action,
            "duplicate": self.duplicate,
        }


def detect_language(text: str, existing: str | None = None) -> str:
    value = str(text or "").casefold()
    explicit = {
        "english": "en", "nederlands": "nl", "dutch": "nl", "deutsch": "de",
        "español": "es", "spanish": "es", "papiamentu": "pap", "papiamento": "pap",
        "português": "pt", "portuguese": "pt",
    }
    for marker, locale in explicit.items():
        if marker in value:
            return locale
    scores = {
        locale: sum(1 for marker in markers if marker in value)
        for locale, markers in LANGUAGE_MARKERS.items()
    }
    best = max(scores, key=scores.get, default="en")
    if scores.get(best, 0) > 0 and list(scores.values()).count(scores[best]) == 1:
        return best
    return existing if existing in SUPPORTED_LOCALES else "en"


def _extract_date(text: str) -> str | None:
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    parsed = None
    if match:
        try:
            parsed = datetime.strptime(match.group(1), "%Y-%m-%d")
        except ValueError:
            return None
    elif re.search(r"\b(?:date|datum|fecha|data|on|op|am|el|dia|dja)\b", text.casefold()):
        parsed = dateparser.parse(
            text,
            settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
        )
    return parsed.date().isoformat() if parsed else None


def _number_after(patterns: tuple[str, ...], text: str) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _extract_fields(text: str, locale: str, current: dict) -> tuple[dict, bool]:
    value = str(text or "").strip()
    lower = value.casefold()
    number_words = {
        "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
        "een": "1", "twee": "2", "drie": "3", "vier": "4", "vijf": "5",
        "uno": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5",
        "um": "1", "dois": "2", "três": "3", "quatro": "4", "cinco": "5",
    }
    numeric_value = value
    for word, number in number_words.items():
        numeric_value = re.sub(rf"\b{re.escape(word)}\b", number, numeric_value, flags=re.IGNORECASE)
    updates: dict[str, Any] = {}
    ambiguous_party = False

    trip_date = _extract_date(value)
    if trip_date:
        updates["trip_date"] = trip_date

    count_patterns = {
        "adults": (r"(\d+)\s*(?:adults?|volwassenen?|erwachsene|adultos?|adulto)",),
        "children": (r"(\d+)\s*(?:children|child|kids?|kinderen|kind|kinder|niños?|crianças?|mucha)(?:\s*(?:aged?|age|van|von|de|di)\s*4)?",),
        "infants": (r"(\d+)\s*(?:infants?|bab(?:y|ies)|peuters?|baby['’]?s?|kleinkinder|bebés?|bebês?|mucha\s*(?:di)?\s*0)",),
    }
    for field, patterns in count_patterns.items():
        count = _number_after(patterns, value)
        if count is not None:
            updates[field] = count

    if not any(field in updates for field in ("adults", "children", "infants")):
        party = _number_after(
            (r"(?:we are|we're|party of|somos|wir sind|wij zijn|nos ta|somos)\s*(\d+)",
             r"(\d+)\s*(?:people|personen|personen|personen|personas|pessoas|hende)"),
            numeric_value,
        )
        if party is not None:
            updates["party_size_hint"] = party
            ambiguous_party = True

    name_patterns = (
        r"(?:my name is|name is|naam is|ich hei(?:ß|ss)e|me llamo|mi n[oò]mber ta|meu nome [ée])\s+([\p{L}][\p{L}'’-]+(?:\s+[\p{L}][\p{L}'’-]+){1,4})(?=[.,!?]|$)",
    )
    import regex as regex_module
    for pattern in name_patterns:
        match = regex_module.search(pattern, value, flags=regex_module.IGNORECASE)
        if match:
            updates["customer_name"] = match.group(1).strip()
            break

    if any(word in lower for word in ("fishermen", "pier", "own transport", "eigen vervoer", "selbst", "muelle", "porto")):
        updates["pickup_preference"] = "pier"
        updates.pop("pickup_location", None)
    if any(word in lower for word in ("pickup", "pick up", "hoteltransfer", "ophalen", "abholung", "recogida", "traslado")):
        updates["pickup_preference"] = "pickup_requested"
        hotel = re.search(r"(?:hotel|from|van|vom|desde|do)\s+([\wÀ-ž'’ .-]{3,60})", value, re.IGNORECASE)
        if hotel:
            updates["pickup_location"] = hotel.group(1).strip(" .,?!")

    if any(word in lower for word in ("vegetarian", "vegetarisch", "vegetariano", "vegetári", "halal", "gluten")):
        updates["dietary_requirements"] = value
    return updates, ambiguous_party


def _summary(fields: dict, locale: str) -> str:
    pickup = (
        f"hotel pickup requested ({fields.get('pickup_location')})"
        if fields.get("pickup_preference") == "pickup_requested"
        else "meeting at Fishermen’s Pier"
    )
    labels = {
        "en": ("Here is what I have", "Date", "Guests", "Reservation name", "Transport"),
        "nl": ("Dit heb ik genoteerd", "Datum", "Gasten", "Naam reservering", "Vervoer"),
        "de": ("Das habe ich notiert", "Datum", "Gäste", "Reservierungsname", "Transport"),
        "es": ("Esto es lo que anoté", "Fecha", "Pasajeros", "Nombre de reserva", "Transporte"),
        "pap": ("Esaki ta loke mi a nota", "Fecha", "Huéspednan", "Nòmber di reservashon", "Transporte"),
        "pt": ("Isto é o que anotei", "Data", "Passageiros", "Nome da reserva", "Transporte"),
    }[locale]
    return (
        f"*{labels[0]}*\n"
        f"{labels[1]}: {fields['trip_date']}\n"
        f"{labels[2]}: {fields['adults']} adults, {fields['children']} children 4-12, {fields['infants']} children 0-3\n"
        f"{labels[3]}: {fields['customer_name']}\n"
        f"{labels[4]}: {pickup}\n\n{COPY[locale]['confirm']}"
    )


def _next_question(fields: dict, locale: str) -> str | None:
    if fields.get("party_size_hint") is not None and not any(
        field in fields for field in ("adults", "children", "infants")
    ):
        return COPY[locale]["composition"]
    prompt_keys = {
        "trip_date": "trip_date", "adults": "adults", "children": "children",
        "infants": "infants", "customer_name": "name", "pickup_preference": "pickup",
    }
    for field in REQUIRED_FIELDS:
        if field not in fields:
            return COPY[locale][prompt_keys[field]]
    if fields.get("pickup_preference") == "pickup_requested" and not fields.get("pickup_location"):
        return COPY[locale]["hotel"]
    return None


def _question_answer(text: str, locale: str) -> str:
    lower = str(text or "").casefold()
    catalog = mermaid_catalog.get_catalog()
    prices = catalog["pricing"]["currencies"]["USD"]
    if any(word in lower for word in ("price", "cost", "prijs", "kosten", "precio", "preço", "kuantu")):
        return f"Adult USD {prices['adult']}; child 4-12 USD {prices['child_4_12']}; age 0-3 free. Your itemized total will be in the quote."
    if any(word in lower for word in ("include", "included", "inbegrepen", "inklusive", "incluye", "incluído", "inklui")):
        return "Breakfast, soft drinks and juices, BBQ lunch, the beach house, facilities, snorkeling masks and beach chairs are included."
    if any(word in lower for word in ("bring", "meenemen", "mitbringen", "llevar", "levar", "hiba")):
        return "Bring towels, sunscreen and swimwear. Mermaid takes care of the included food, drinks and island facilities."
    return ""


def process_intake_turn(
    phone: str,
    text: str,
    *,
    message_id: str = "",
    from_name: str = "",
) -> IntakeResult:
    """Apply one customer turn and persist only customer-owned intake facts."""
    state = state_registry.wa_get_booking_state(phone)
    root_fields = dict(state.get("fields") or {})
    flags = dict(state.get("flags") or {})
    completed = list(state.get("completed_bookings") or [])
    fields = dict(root_fields.get("mermaid_intake") or {})
    seen = list(flags.get("mermaid_seen_message_ids") or [])
    if message_id and message_id in seen:
        return IntakeResult("", fields.get("language", "en"), fields.get("phase", "collecting"), duplicate=True)

    locale = detect_language(text, fields.get("language"))
    fields["language"] = locale
    lower = str(text or "").strip().casefold()
    if any(phrase in lower for phrase in ("human", "person", "real person", "medewerker", "mitarbeiter", "persona", "humano", "un hende")):
        fields["phase"] = "human_takeover"
        state_registry.set_ai_muted(phone, True, channel="whatsapp")
        state_registry.create_pending_notification(
            "escalation", "whatsapp", phone, from_name or fields.get("customer_name") or "Mermaid guest",
            "Mermaid reservation: human requested",
            "The guest requested a person. Intake progress is saved.", mode="soft",
        )
        action = "human_takeover"
        response = COPY[locale]["human"]
    elif any(phrase in lower for phrase in ("cancel", "annuleer", "stornieren", "cancelar", "kanselá")):
        fields["phase"] = "cancelled"
        action = "cancel"
        response = COPY[locale]["cancelled"]
    else:
        updates, ambiguous_party = _extract_fields(text, locale, fields)
        for key, value in updates.items():
            fields[key] = value
        if any(key in updates for key in ("adults", "children", "infants")):
            fields.pop("party_size_hint", None)

        if fields.get("trip_date"):
            trip_day = datetime.strptime(fields["trip_date"], "%Y-%m-%d").strftime("%A").casefold()
            operating_days = set(mermaid_catalog.get_catalog()["service"]["operating_weekdays"])
            if trip_day not in operating_days:
                fields.pop("trip_date", None)
                response = COPY[locale]["invalid_day"] + "\n\n" + COPY[locale]["trip_date"]
                action = None
                fields["phase"] = "collecting"
            else:
                response = ""
                action = None
        else:
            response = ""
            action = None

        if not response:
            question_answer = _question_answer(text, locale)
            if fields.get("phase") == "awaiting_summary_confirmation" and lower in YES[locale] and not updates:
                fields["phase"] = "summary_confirmed"
                action = "summary_confirmed"
                response = COPY[locale]["confirmed"]
            else:
                next_question = _next_question(fields, locale)
                if next_question:
                    fields["phase"] = "collecting"
                    response = "\n\n".join(part for part in (question_answer, next_question) if part)
                else:
                    fields["phase"] = "awaiting_summary_confirmation"
                    response = "\n\n".join(part for part in (question_answer, _summary(fields, locale)) if part)
                if ambiguous_party:
                    response = "\n\n".join(part for part in (question_answer, COPY[locale]["composition"]) if part)

        if not fields.get("introduced") and fields.get("phase") == "collecting":
            response = COPY[locale]["intro"] + "\n\n" + response
            fields["introduced"] = True

    root_fields["mermaid_intake"] = fields
    if message_id:
        seen.append(message_id)
        flags["mermaid_seen_message_ids"] = seen[-100:]
    state_registry.wa_save_booking_state(phone, root_fields, flags, completed)
    return IntakeResult(response, locale, fields.get("phase", "collecting"), action=action)


def handle_demo_message(message: dict, include_media: bool = False) -> str | dict:
    result = process_intake_turn(
        str(message.get("from") or ""),
        str(message.get("text") or ""),
        message_id=str(message.get("message_id") or ""),
        from_name=str(message.get("from_name") or ""),
    )
    return result.as_reply() if include_media else result.text
