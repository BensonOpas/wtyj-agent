"""Deterministic WhatsApp-first intake for Mermaid's reservation demo.

The language model is deliberately not trusted with money, availability,
booking codes, or payment state. This module extracts customer-supplied facts,
asks one question at a time, and persists progress in the existing WhatsApp
state store.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import dateparser

from shared import mermaid_catalog, state_registry
from agents.social import mermaid_guest_experience as guest


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
        "human": "I’ve passed this to Mermaid’s team for review. Your details are saved, and I can still help with general trip questions.",
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
        "human": "Ik heb dit ter beoordeling aan Mermaid’s team doorgegeven. Je gegevens zijn opgeslagen en ik kan algemene vragen over de trip blijven beantwoorden.",
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
        "human": "Ich habe dies zur Prüfung an Mermaids Team weitergegeben. Ihre Angaben sind gespeichert und ich kann weiterhin allgemeine Fragen zum Ausflug beantworten.",
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
        "human": "He pasado esto al equipo de Mermaid para que lo revise. Tus datos están guardados y puedo seguir respondiendo preguntas generales sobre la excursión.",
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
        "human": "Mi a pasa esaki pa tim di Mermaid revisá. Bo datonan ta wardá i mi por sigui yuda ku preguntanan general tokante e trip.",
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
        "human": "Encaminhei isso à equipe da Mermaid para análise. Seus dados estão salvos e posso continuar respondendo a perguntas gerais sobre o passeio.",
        "invalid_day": "Segundo as informações publicadas, a Mermaid opera segunda, terça, quarta, sexta, sábado e domingo. Escolha um desses dias.",
    },
}


SUMMARY_COPY = {
    "en": {"title": "Here is what I have", "date": "Date", "guests": "Guests", "name": "Reservation name", "transport": "Transport", "party": "{adults} adults, {children} children 4-12, {infants} children 0-3", "pier": "meeting at Fishermen’s Pier", "pickup": "hotel pickup requested ({location})"},
    "nl": {"title": "Dit heb ik genoteerd", "date": "Datum", "guests": "Gasten", "name": "Naam reservering", "transport": "Vervoer", "party": "{adults} volwassenen, {children} kinderen 4-12, {infants} kinderen 0-3", "pier": "ontmoeting bij Fishermen’s Pier", "pickup": "hoteltransfer aangevraagd ({location})"},
    "de": {"title": "Das habe ich notiert", "date": "Datum", "guests": "Gäste", "name": "Reservierungsname", "transport": "Transport", "party": "{adults} Erwachsene, {children} Kinder 4-12, {infants} Kinder 0-3", "pier": "Treffpunkt Fishermen’s Pier", "pickup": "Hotelabholung angefragt ({location})"},
    "es": {"title": "Esto es lo que anoté", "date": "Fecha", "guests": "Pasajeros", "name": "Nombre de reserva", "transport": "Transporte", "party": "{adults} adultos, {children} niños de 4-12, {infants} niños de 0-3", "pier": "encuentro en Fishermen’s Pier", "pickup": "recogida en hotel solicitada ({location})"},
    "pap": {"title": "Esaki ta loke mi a nota", "date": "Fecha", "guests": "Huéspednan", "name": "Nòmber di reservashon", "transport": "Transporte", "party": "{adults} adulto, {children} mucha di 4-12, {infants} mucha di 0-3", "pier": "topa na Fishermen’s Pier", "pickup": "pickup na hotel pidi ({location})"},
    "pt": {"title": "Isto é o que anotei", "date": "Data", "guests": "Passageiros", "name": "Nome da reserva", "transport": "Transporte", "party": "{adults} adultos, {children} crianças de 4-12, {infants} crianças de 0-3", "pier": "encontro no Fishermen’s Pier", "pickup": "traslado do hotel solicitado ({location})"},
}


FAQ_COPY = {
    "en": {"price": "Adult USD {adult}; child 4-12 USD {child}; age 0-3 free. Your itemized total will be in the quote.", "included": "Breakfast, soft drinks and juices, BBQ lunch, the beach house, facilities, snorkeling masks and beach chairs are included.", "bring": "Bring towels, sunscreen and swimwear. Mermaid takes care of the included food, drinks and island facilities."},
    "nl": {"price": "Volwassene USD {adult}; kind 4-12 USD {child}; 0-3 jaar gratis. De offerte bevat het volledige prijsoverzicht.", "included": "Ontbijt, frisdrank en sap, BBQ-lunch, het strandhuis, faciliteiten, snorkelmaskers en strandstoelen zijn inbegrepen.", "bring": "Neem handdoeken, zonnebrand en zwemkleding mee. Mermaid zorgt voor het inbegrepen eten, drinken en de eilandfaciliteiten."},
    "de": {"price": "Erwachsene USD {adult}; Kinder 4-12 USD {child}; 0-3 Jahre kostenlos. Die Einzelpreise stehen im Angebot.", "included": "Frühstück, alkoholfreie Getränke und Säfte, BBQ-Mittagessen, Strandhaus, Einrichtungen, Schnorchelmasken und Strandstühle sind inklusive.", "bring": "Bringen Sie Handtücher, Sonnencreme und Badesachen mit. Mermaid kümmert sich um inklusive Speisen, Getränke und Inseleinrichtungen."},
    "es": {"price": "Adulto USD {adult}; niño de 4-12 USD {child}; 0-3 años gratis. El total detallado estará en la cotización.", "included": "Incluye desayuno, refrescos y jugos, almuerzo BBQ, casa de playa, instalaciones, máscaras de snorkel y sillas de playa.", "bring": "Trae toallas, protector solar y traje de baño. Mermaid se encarga de la comida, bebidas e instalaciones incluidas."},
    "pap": {"price": "Adulto USD {adult}; mucha di 4-12 USD {child}; 0-3 aña grátis. Bo oferta lo tin e total detaya.", "included": "Desayuno, refresko i djus, BBQ, beach house, fasilidatnan, maskara di snorkel i stul di playa ta inkluí.", "bring": "Hiba handuk, krema solar i paña di landa. Mermaid ta sòru pa kuminda, bebida i fasilidatnan inkluí."},
    "pt": {"price": "Adulto USD {adult}; criança de 4-12 USD {child}; 0-3 anos grátis. O total detalhado estará na cotação.", "included": "Inclui café da manhã, refrigerantes e sucos, almoço BBQ, casa de praia, instalações, máscaras de snorkel e cadeiras de praia.", "bring": "Leve toalhas, protetor solar e roupa de banho. A Mermaid cuida da comida, bebidas e instalações incluídas."},
}


PAYMENT_COPY = {
    "en": ("For this demo, seats are available. No live inventory system was checked.", "Complete the no-money demo payment here:"),
    "nl": ("Voor deze demo zijn er plaatsen beschikbaar. Er is geen live beschikbaarheidssysteem gecontroleerd.", "Voltooi hier de demo-betaling zonder echt geld:"),
    "de": ("Für diese Demo sind Plätze verfügbar. Es wurde kein Live-Verfügbarkeitssystem geprüft.", "Schließen Sie hier die Demo-Zahlung ohne echtes Geld ab:"),
    "es": ("Para esta demo hay plazas disponibles. No se consultó un sistema de disponibilidad en vivo.", "Completa aquí el pago demo sin dinero real:"),
    "pap": ("Pa e demo aki tin lugá disponibel. No a kontrolá ningun sistema live di disponibilidat.", "Kompletá e pago demo sin plaka real aki:"),
    "pt": ("Para esta demo há lugares disponíveis. Nenhum sistema de disponibilidade ao vivo foi consultado.", "Conclua aqui o pagamento demo sem dinheiro real:"),
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
    labels = SUMMARY_COPY[locale]
    pickup = guest.transport_text(fields, locale)
    party = guest.party_text(fields, locale)
    return (
        f"*{labels['title']}*\n"
        f"{labels['date']}: {guest.guest_date(fields['trip_date'], locale)}\n"
        f"{labels['guests']}: {party}\n"
        f"{labels['name']}: {fields['customer_name']}\n"
        f"{guest.price_text(guest.intake_money(fields), fields, locale)}\n"
        f"{labels['transport']}: {pickup}\n\n{guest.guest_copy(locale)['confirm']}"
    )


def _next_question(fields: dict, locale: str) -> str | None:
    if all(key in fields for key in ("adults", "children", "infants")) and sum(
        fields[key] for key in ("adults", "children", "infants")
    ) <= 0:
        return COPY[locale]["composition"]
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
    answers = FAQ_COPY[locale]
    if any(word in lower for word in ("price", "cost", "prijs", "kosten", "precio", "preço", "kuantu")):
        return answers["price"].format(adult=prices["adult"], child=prices["child_4_12"])
    if any(word in lower for word in ("include", "included", "inbegrepen", "inklusive", "incluye", "incluído", "inklui")):
        return answers["included"]
    if any(word in lower for word in ("bring", "meenemen", "mitbringen", "llevar", "levar", "hiba")):
        return answers["bring"]
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
        state_registry.create_pending_notification(
            "escalation", "whatsapp", phone, from_name or fields.get("customer_name") or "Mermaid guest",
            "Mermaid reservation: human requested",
            "The guest requested a person. Intake progress is saved.", mode="soft",
            preserve_hard_mode=True,
        )
        action = "human_takeover"
        response = COPY[locale]["human"]
    elif state_registry.get_active_escalation_mode(phone) in {"soft", "hard"}:
        fields["phase"] = "human_takeover"
        action = None
        response = _question_answer(text, locale) or COPY[locale]["human"]
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


def process_model_turn(message: dict, reservation: dict | None) -> IntakeResult:
    """The single model call understands language; Python validates and owns state."""
    from agents.marina import marina_agent

    phone = str(message.get("from") or "")
    message_id = str(message.get("message_id") or "")
    state = state_registry.wa_get_booking_state(phone)
    root_fields = dict(state.get("fields") or {})
    flags = dict(state.get("flags") or {})
    fields = dict(root_fields.get("mermaid_intake") or {})
    seen = list(flags.get("mermaid_seen_message_ids") or [])
    if message_id and message_id in seen:
        return IntakeResult("", fields.get("language", "en"), fields.get("phase", "collecting"), duplicate=True)
    history = state_registry.dm_get_history(phone, "whatsapp", limit=16)
    review_pending = (
        state_registry.get_active_escalation_mode(phone) in {"soft", "hard"}
        or bool((reservation or {}).get("human_takeover"))
    )
    context = dict(fields)
    context["human_review_pending"] = review_pending
    context["reservation_state"] = (reservation or {}).get("state")
    if reservation:
        context["reservation_intake"] = reservation["intake"]
        context["authoritative_pricing"] = reservation["monetary_snapshot"]
        context["booking_code"] = reservation["booking_code"]
    elif all(key in fields for key in ("adults", "children", "infants")):
        context["authoritative_pricing"] = guest.intake_money(fields)
    context["pickup_status"] = "requested_unconfirmed" if fields.get("pickup_preference") == "pickup_requested" else "not_requested"
    understood = marina_agent.process_message(
        from_email=phone, subject="Mermaid WhatsApp reservation demo",
        body=str(message.get("text") or ""), thread_fields=context,
        thread_flags={"phase": fields.get("phase", "collecting")},
        action_context=json.dumps({"required_fields": REQUIRED_FIELDS}),
        channel="whatsapp", messages=history,
        response_contract="mermaid_reservation_demo",
    )
    locale = understood.get("language")
    if locale not in SUPPORTED_LOCALES:
        locale = fields.get("language", "en")
    action = understood.get("mermaid_action")
    if action not in {"details", "question", "confirm_summary", "cancel", "request_human", "payment_status", "new_booking", "acknowledge"}:
        return IntakeResult(str(understood.get("reply") or COPY[locale]["trip_date"]), locale, fields.get("phase", "collecting"))
    if not review_pending and action == "new_booking" and (reservation or {}).get("state") in {"booked", "cancelled"}:
        fields = {}
    old_phase = fields.get("phase", "collecting")
    fields["language"] = locale
    changes = {}
    for key, value in (understood.get("fields") or {}).items():
        if key in {"adults", "children", "infants"}:
            if type(value) is int and 0 <= value <= 100:
                changes[key] = value
        elif key == "trip_date" and isinstance(value, str):
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d")
                if parsed.date() >= datetime.now(timezone(timedelta(hours=-4))).date():
                    changes[key] = parsed.date().isoformat()
            except ValueError:
                pass
        elif key == "pickup_preference" and value in {"pier", "pickup_requested"}:
            changes[key] = value
        elif key in {"customer_name", "pickup_location", "dietary_requirements", "accessibility_notes", "special_requests"} and isinstance(value, str):
            cleaned = " ".join(value.split())[:160]
            if cleaned:
                changes[key] = cleaned
    changes = {key: value for key, value in changes.items() if fields.get(key) != value}
    fields.update(changes)
    if fields.get("pickup_preference") == "pier":
        fields.pop("pickup_location", None)
    response = str(understood.get("reply") or "").strip()
    has_question = understood.get("has_open_question") is True or action == "question"
    result_action = None
    if understood.get("requires_human") or action == "request_human" or (
        action == "cancel" and (reservation or {}).get("state") in {"booked", "demo_paid"}
    ):
        state_registry.create_pending_notification(
            "escalation", "whatsapp", phone,
            str(message.get("from_name") or fields.get("customer_name") or "Mermaid guest"),
            "Mermaid reservation: human review", "Reservation progress is saved for the team.", mode="soft",
            preserve_hard_mode=True,
        )
        fields["phase"] = "human_takeover"
        if action in {"confirm_summary", "new_booking", "cancel"}:
            response = COPY[locale]["human"]
        else:
            response = response or COPY[locale]["human"]
        result_action = "human_takeover"
    elif review_pending:
        # Human review freezes booking decisions, not safe conversation. Only
        # an operator resolves the work item; an existing reservation stays
        # frozen independently even after that conversation item is resolved.
        fields["phase"] = "human_takeover"
        if action in {"confirm_summary", "new_booking", "cancel"} or not response:
            response = COPY[locale]["human"]
    elif action == "cancel":
        fields["phase"] = "cancelled"
        response = COPY[locale]["cancelled"]
        result_action = "cancel"
    elif reservation and reservation["state"] in {"demo_payment_pending", "booked"} and action != "new_booking":
        # Answers after a quote never reopen intake or change the immutable quote.
        fields = dict(root_fields.get("mermaid_intake") or fields)
        fields["language"] = locale
        fields["phase"] = reservation["state"]
        result_action = "payment_status" if action == "payment_status" else None
    else:
        if fields.get("trip_date"):
            day = datetime.strptime(fields["trip_date"], "%Y-%m-%d").strftime("%A").casefold()
            if day not in mermaid_catalog.get_catalog()["service"]["operating_weekdays"]:
                fields.pop("trip_date")
                response = COPY[locale]["invalid_day"] + "\n\n" + COPY[locale]["trip_date"]
        question = _next_question(fields, locale)
        if question:
            fields["phase"] = "collecting"
            if not response:
                response = question
        elif has_question:
            # A mixed detail/question turn must keep its answer. Changed facts
            # require a fresh summary before any later approval can book them.
            fields["phase"] = old_phase if old_phase == "awaiting_summary_confirmation" and not changes else "collecting"
        elif action == "confirm_summary" and old_phase == "awaiting_summary_confirmation" and not changes:
            fields["phase"] = "summary_confirmed"
            response = COPY[locale]["confirmed"]
            result_action = "summary_confirmed"
        else:
            fields["phase"] = "awaiting_summary_confirmation"
            response = _summary(fields, locale)
    root_fields["mermaid_intake"] = fields
    if message_id:
        flags["mermaid_seen_message_ids"] = (seen + [message_id])[-100:]
    state_registry.wa_save_booking_state(phone, root_fields, flags, state.get("completed_bookings") or [])
    return IntakeResult(response, locale, fields["phase"], action=result_action)


def handle_demo_message(message: dict, include_media: bool = False, *, use_model: bool = False) -> str | dict:
    # Customer prose is never payment evidence. Only the signed callback below
    # can mutate payment state.
    from agents.social import mermaid_reservation_store as _reservation_store
    phone = str(message.get("from") or "")
    current = _reservation_store.latest_for_conversation(phone)
    if use_model:
        state = state_registry.wa_get_booking_state(phone)
        flags = state.get("flags") or {}
        cached = (flags.get("mermaid_cached_replies") or {}).get(str(message.get("message_id") or "")) or flags.get("mermaid_cached_reply") or {}
        if message.get("message_id") and cached.get("message_id") == message["message_id"]:
            reply = dict(cached.get("reply") or {})
            commit = reply.get("mermaid_delivery_commit") or {}
            if commit:
                from agents.social.mermaid_documents import delivery_job
                if (delivery_job(commit["job_id"]) or {}).get("status") == "delivered":
                    return IntakeResult("", current["language"] if current else "en", "duplicate", duplicate=True).as_reply() if include_media else ""
            reply["duplicate"] = True
            return reply if include_media else str(reply.get("text") or "")
    lower = str(message.get("text") or "").casefold()
    if not use_model and current and current["state"] == "demo_payment_pending" and any(
        phrase in lower for phrase in ("i paid", "paid", "betaald", "bezahlt", "pagué", "paguei", "mi a paga")
    ):
        text = (
            "Thanks. A WhatsApp message cannot verify payment. Please complete the no-money demo link; "
            "only its signed success callback can finish this demo booking."
        )
        if include_media:
            return IntakeResult(text, current["language"], "demo_payment_pending").as_reply()
        return text
    result = process_model_turn(message, current) if use_model else process_intake_turn(
        str(message.get("from") or ""),
        str(message.get("text") or ""),
        message_id=str(message.get("message_id") or ""),
        from_name=str(message.get("from_name") or ""),
    )
    if result.action == "summary_confirmed":
        from agents.social import (
            mermaid_demo_payment, mermaid_documents, mermaid_reservation_store,
        )

        state = state_registry.wa_get_booking_state(str(message.get("from") or ""))
        intake = (state.get("fields") or {}).get("mermaid_intake") or {}
        reservation = mermaid_reservation_store.confirm_reservation(
            str(message.get("from") or ""),
            intake,
            idempotency_key=(
                "confirm:" + str(message.get("message_id") or "")
                if message.get("message_id") else "confirm:" + str(message.get("from") or "")
            ),
            zernio_account_id=str(message.get("_zernio_account_id") or ""),
        )
        document, job = mermaid_documents.create_quote(reservation)
        reservation = mermaid_reservation_store.transition(
            reservation["public_id"], "quote_ready",
            idempotency_key=f"quote-ready:{reservation['public_id']}",
            actor="system", reason="Localized demo quote rendered",
            updates={"quote_public_id": document["public_id"]},
        )
        base_url = __import__("os").environ.get("UNBOKS_PUBLIC_BASE_URL", "http://localhost:8001")
        secret = __import__("os").environ.get("MERMAID_DEMO_SIGNING_SECRET", "")
        media = {
            "url": mermaid_documents.build_signed_url(base_url, document["public_id"], secret),
            "type": "file", "filename": document["filename"], "id": document["public_id"],
        }
        reservation = mermaid_reservation_store.transition(
            reservation["public_id"], "demo_payment_pending",
            idempotency_key=f"payment-pending:{reservation['public_id']}",
            actor="system", reason="No-money demo checkout created",
        )
        payment_url = mermaid_demo_payment.build_payment_url(
            mermaid_catalog.get_catalog().get("links", {}).get("checkout_base_url") or base_url,
            reservation["public_id"], secret
        )
        availability_copy = PAYMENT_COPY[result.locale][0]
        payment_copy = guest.guest_copy(result.locale)["checkout_link"]
        result = IntakeResult(
            mermaid_documents.quote_message(reservation) + "\n\n" + availability_copy + "\n\n" + payment_copy + "\n" + payment_url,
            result.locale,
            result.phase,
            action=f"reservation:{reservation['public_id']}",
        )
        if include_media:
            reply = result.as_reply()
            reply["media"] = media
            reply["mermaid_delivery_commit"] = {"job_id": job["public_id"]}
            if use_model:
                _cache_reply(message, reply)
            return reply
    elif result.action == "payment_status" and current and current["state"] == "demo_payment_pending":
        from agents.social import mermaid_demo_payment
        import os
        url = mermaid_demo_payment.build_payment_url(
            mermaid_catalog.get_catalog().get("links", {}).get("checkout_base_url") or os.environ.get("UNBOKS_PUBLIC_BASE_URL", "http://localhost:8001"),
            current["public_id"], os.environ.get("MERMAID_DEMO_SIGNING_SECRET", ""),
        )
        result = IntakeResult(result.text + "\n\n" + guest.guest_copy(result.locale)["checkout_link"] + "\n" + url, result.locale, result.phase)
    elif result.action == "cancel":
        from agents.social import mermaid_reservation_store

        current = mermaid_reservation_store.latest_for_conversation(str(message.get("from") or ""))
        if current and current["state"] not in {"cancelled", "booked", "demo_paid"}:
            mermaid_reservation_store.cancel(
                current["public_id"],
                idempotency_key="cancel:" + str(message.get("message_id") or current["public_id"]),
            )
    elif result.action == "human_takeover":
        from agents.social import mermaid_reservation_store

        current = mermaid_reservation_store.latest_for_conversation(str(message.get("from") or ""))
        if current:
            mermaid_reservation_store.freeze_for_human(current["public_id"])
    if use_model:
        _cache_reply(message, result.as_reply())
    return result.as_reply() if include_media else result.text


def _cache_reply(message: dict, reply: dict) -> None:
    """Keep the exact payload for the provider's stable idempotent retry."""
    if not message.get("message_id"):
        return
    phone = str(message.get("from") or "")
    state = state_registry.wa_get_booking_state(phone)
    flags = dict(state.get("flags") or {})
    flags["mermaid_cached_reply"] = {"message_id": message["message_id"], "reply": reply}
    cached = dict(flags.get("mermaid_cached_replies") or {})
    cached[str(message["message_id"])] = flags["mermaid_cached_reply"]
    flags["mermaid_cached_replies"] = dict(list(cached.items())[-10:])
    state_registry.wa_save_booking_state(phone, state.get("fields") or {}, flags, state.get("completed_bookings") or [])
