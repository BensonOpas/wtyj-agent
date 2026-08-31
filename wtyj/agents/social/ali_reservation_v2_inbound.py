"""Deterministic Ali reservation V2 inbound document handling.

Media bytes are downloaded from Zernio's authenticated endpoint, validated and
stored privately before any customer acknowledgement.  Nothing in this path is
sent to Nick/Claude and no provider URL is retained.
"""

from __future__ import annotations

from agents.social import ali_customer_dossier, ali_reservation_v2
from agents.social.ali_reservation_workflow import AliReservationError
from agents.social.zernio_whatsapp_media import download_whatsapp_media
from shared import bm_logger, state_registry


_SLOT_LABELS = {
    "en": {
        "license_front": "the front of your driver's license",
        "license_back": "the back of your driver's license",
        "passport": "your passport",
        "identity_front": "the front of your ID card",
        "identity_back": "the back of your ID card",
    },
    "nl": {
        "license_front": "de voorkant van je rijbewijs",
        "license_back": "de achterkant van je rijbewijs",
        "passport": "je paspoort",
        "identity_front": "de voorkant van je identiteitskaart",
        "identity_back": "de achterkant van je identiteitskaart",
    },
    "pap": {
        "license_front": "e parti dilanti di bo reibeweis",
        "license_back": "e parti patras di bo reibeweis",
        "passport": "bo pasport",
        "identity_front": "e parti dilanti di bo karta di identidat",
        "identity_back": "e parti patras di bo karta di identidat",
    },
    "de": {
        "license_front": "die Vorderseite Ihres Führerscheins",
        "license_back": "die Rückseite Ihres Führerscheins",
        "passport": "Ihren Reisepass",
        "identity_front": "die Vorderseite Ihres Personalausweises",
        "identity_back": "die Rückseite Ihres Personalausweises",
    },
    "es": {
        "license_front": "el frente de tu permiso de conducir",
        "license_back": "el reverso de tu permiso de conducir",
        "passport": "tu pasaporte",
        "identity_front": "el frente de tu tarjeta de identidad",
        "identity_back": "el reverso de tu tarjeta de identidad",
    },
}

_COPY = {
    "en": {
        "next": "Got it — {stored} is stored securely. Please send {next} next.",
        "review": "Got it — all required documents are stored securely. I’ll send your pre-contract next so you can review and sign it.",
        "unclassified": "I stored the file securely, but I’m not expecting a document at this step. What document is it?",
        "extras": " I also stored {count} extra file(s) securely. Please tell me what they are.",
        "identity": "Thanks. Please send {document} here in WhatsApp.",
        "opt_out": "Understood. I won't send you any more messages.",
        "cancelled": "Understood. I’ve stopped this reservation request.",
        "ambiguous": "Would you like me to stop this reservation, or would you like more time?",
        "more_time": "No problem. I’ll keep the reservation on hold while you continue.",
        "payment": "Thanks — our team will verify the payment now.",
        "payment_expired": "The 24-hour payment window has expired, so the car was not secured. I’ve asked our team to review current availability before we continue.",
    },
    "nl": {
        "next": "Ontvangen — {stored} is veilig opgeslagen. Stuur nu {next}.",
        "review": "Ontvangen — alle vereiste documenten zijn veilig opgeslagen. Ik stuur nu je pre-contract zodat je het kunt bekijken en ondertekenen.",
        "unclassified": "Ik heb het bestand veilig opgeslagen, maar verwacht nu geen document. Welk document is het?",
        "extras": " Ik heb ook {count} extra bestand(en) veilig opgeslagen. Laat weten wat ze zijn.",
        "identity": "Bedankt. Stuur nu {document} hier in WhatsApp.",
        "opt_out": "Begrepen. Ik stuur je geen berichten meer.",
        "cancelled": "Begrepen. Ik heb deze reserveringsaanvraag gestopt.",
        "ambiguous": "Wil je dat ik deze reservering stop, of wil je meer tijd?",
        "more_time": "Geen probleem. Ik houd de reservering vast terwijl je verdergaat.",
        "payment": "Bedankt — ons team controleert de betaling nu.",
        "payment_expired": "De betalingstermijn van 24 uur is verstreken, dus de auto is niet vastgelegd. Ik heb ons team gevraagd de actuele beschikbaarheid te controleren voordat we verdergaan.",
    },
    "pap": {
        "next": "Risibí — {stored} ta warda sigur. Awor manda {next}.",
        "review": "Risibí — tur dokumento rekerí ta warda sigur. Awor mi ta manda bo pre-kontrato pa bo lesa i firma.",
        "unclassified": "Mi a warda e file sigur, pero mi no ta spera un dokumento den e paso aki. Kua dokumento e ta?",
        "extras": " Mi a warda tambe {count} file extra sigur. Laga mi sa kiko nan ta.",
        "identity": "Danki. Manda {document} aki den WhatsApp.",
        "opt_out": "Komprondé. Mi no ta manda bo mas mensahe.",
        "cancelled": "Komprondé. Mi a stòp e petishon di reservashon aki.",
        "ambiguous": "Bo ke pa mi stòp e reservashon aki, òf bo ke mas tempu?",
        "more_time": "No tin problema. Mi ta tene e reservashon mientras bo ta sigui.",
        "payment": "Danki — nos team lo verifiká e pago awor.",
        "payment_expired": "E periodo di 24 ora pa paga a kaduká, pues e outo no a keda reservá. Mi a pidi nos tim pa kontrolá disponibilidat aktual promé ku nos sigui.",
    },
    "de": {
        "next": "Erhalten — {stored} wurde sicher gespeichert. Bitte senden Sie jetzt {next}.",
        "review": "Erhalten — alle erforderlichen Dokumente wurden sicher gespeichert. Als Nächstes sende ich Ihnen den Vorvertrag zur Prüfung und Unterschrift.",
        "unclassified": "Ich habe die Datei sicher gespeichert, erwarte in diesem Schritt aber kein Dokument. Um welches Dokument handelt es sich?",
        "extras": " Ich habe außerdem {count} zusätzliche Datei(en) sicher gespeichert. Bitte teilen Sie mir mit, was sie sind.",
        "identity": "Danke. Bitte senden Sie jetzt {document} hier über WhatsApp.",
        "opt_out": "Verstanden. Ich werde Ihnen keine weiteren Nachrichten senden.",
        "cancelled": "Verstanden. Ich habe diese Reservierungsanfrage beendet.",
        "ambiguous": "Soll ich diese Reservierung beenden, oder möchten Sie mehr Zeit?",
        "more_time": "Kein Problem. Ich halte die Reservierung, während Sie fortfahren.",
        "payment": "Danke — unser Team prüft die Zahlung jetzt.",
        "payment_expired": "Das 24-stündige Zahlungsfenster ist abgelaufen, daher wurde das Fahrzeug nicht gesichert. Ich habe unser Team gebeten, die aktuelle Verfügbarkeit zu prüfen, bevor wir fortfahren.",
    },
    "es": {
        "next": "Recibido: {stored} se guardó de forma segura. Ahora envía {next}.",
        "review": "Recibido: todos los documentos necesarios se guardaron de forma segura. Ahora te enviaré el precontrato para que lo revises y firmes.",
        "unclassified": "Guardé el archivo de forma segura, pero no esperaba un documento en este paso. ¿Qué documento es?",
        "extras": " También guardé {count} archivo(s) adicional(es) de forma segura. Dime qué son.",
        "identity": "Gracias. Envía {document} aquí por WhatsApp.",
        "opt_out": "Entendido. No te enviaré más mensajes.",
        "cancelled": "Entendido. Detuve esta solicitud de reserva.",
        "ambiguous": "¿Quieres que detenga esta reserva o necesitas más tiempo?",
        "more_time": "Está bien. Mantendré la reserva en espera mientras continúas.",
        "payment": "Gracias. Nuestro equipo verificará el pago ahora.",
        "payment_expired": "La ventana de pago de 24 horas venció, por lo que el auto no quedó asegurado. Pedí a nuestro equipo que revise la disponibilidad actual antes de continuar.",
    },
}

_FAILURE_COPY = {
    "en": {
        "duplicate_document_content": (
            "That image is identical to a document you already sent, so I "
            "couldn't use it as {document}. Please send a different image "
            "showing {document}."
        ),
        "too_large": (
            "That file is too large. Please send {document} as a JPG, PNG, "
            "or PDF smaller than 10 MB."
        ),
        "dimensions": (
            "That image's dimensions are too large or too small to process. "
            "Please take a new, clear photo of {document} and send it again."
        ),
        "unreadable": (
            "I couldn't read that image. It may be damaged or unclear. "
            "Please take a new, well-lit photo of {document} and send it again."
        ),
        "file_type": (
            "That file format doesn't match its contents. Please send "
            "{document} as a genuine JPG, PNG, or PDF."
        ),
        "pdf": (
            "I couldn't read that PDF safely. Please send a new PDF, or a "
            "clear JPG or PNG photo of {document}, smaller than 10 MB."
        ),
        "temporary": (
            "I couldn't download that file from WhatsApp just now. Please "
            "wait a moment and resend {document}."
        ),
        "generic": (
            "I couldn't store that file safely. Please send a new, clear JPG, "
            "PNG, or PDF of {document}, smaller than 10 MB."
        ),
        "document": "the requested document",
    },
    "nl": {
        "duplicate_document_content": (
            "Deze afbeelding is identiek aan een document dat je al hebt "
            "gestuurd. Ik kon deze daarom niet gebruiken als {document}. "
            "Stuur een andere afbeelding waarop {document} staat."
        ),
        "too_large": (
            "Dit bestand is te groot. Stuur {document} als JPG, PNG of PDF "
            "kleiner dan 10 MB."
        ),
        "dimensions": (
            "De afmetingen van deze afbeelding zijn te groot of te klein om "
            "te verwerken. Maak een nieuwe, duidelijke foto van {document}."
        ),
        "unreadable": (
            "Ik kon deze afbeelding niet lezen; ze kan beschadigd of onduidelijk "
            "zijn. Stuur een nieuwe, goed belichte foto van {document}."
        ),
        "file_type": (
            "Het bestandsformaat komt niet overeen met de inhoud. Stuur "
            "{document} als een echte JPG, PNG of PDF."
        ),
        "pdf": (
            "Ik kon deze PDF niet veilig lezen. Stuur een nieuwe PDF of een "
            "duidelijke JPG- of PNG-foto van {document}, kleiner dan 10 MB."
        ),
        "temporary": (
            "Ik kon dit bestand zojuist niet downloaden uit WhatsApp. Wacht "
            "even en stuur {document} opnieuw."
        ),
        "generic": (
            "Ik kon dit bestand niet veilig opslaan. Stuur een nieuwe, duidelijke "
            "JPG, PNG of PDF van {document}, kleiner dan 10 MB."
        ),
        "document": "het gevraagde document",
    },
    "pap": {
        "duplicate_document_content": (
            "E imágen aki ta idéntiko na un dokumento ku bo a manda kaba. "
            "Mi no por usa esaki komo {document}. Manda un otro imágen ku ta "
            "mustra {document}."
        ),
        "too_large": (
            "E file aki ta muchu grandi. Manda {document} komo JPG, PNG òf "
            "PDF mas chikí ku 10 MB."
        ),
        "dimensions": (
            "E dimensonan di e imágen ta muchu grandi òf muchu chikí pa procesa. "
            "Tuma un foto nobo i kla di {document} i manda'é atrobe."
        ),
        "unreadable": (
            "Mi no por lesa e imágen aki; por ta ku e ta dañá òf no ta kla. "
            "Tuma un foto nobo ku bon lus di {document} i manda'é atrobe."
        ),
        "file_type": (
            "E tipo di file no ta kuadra ku su kontenido. Manda {document} "
            "komo un JPG, PNG òf PDF válido."
        ),
        "pdf": (
            "Mi no por lesa e PDF aki sigur. Manda un PDF nobo òf un foto JPG "
            "òf PNG kla di {document}, mas chikí ku 10 MB."
        ),
        "temporary": (
            "Mi no por a baha e file for di WhatsApp awor. Warda un momento i "
            "manda {document} atrobe."
        ),
        "generic": (
            "Mi no por a warda e file aki sigur. Manda un JPG, PNG òf PDF nobo "
            "i kla di {document}, mas chikí ku 10 MB."
        ),
        "document": "e dokumento ku nos a pidi",
    },
    "de": {
        "duplicate_document_content": (
            "Dieses Bild ist identisch mit einem bereits gesendeten Dokument. "
            "Ich konnte es deshalb nicht als {document} verwenden. Bitte senden "
            "Sie ein anderes Bild, das {document} zeigt."
        ),
        "too_large": (
            "Diese Datei ist zu groß. Bitte senden Sie {document} als JPG, PNG "
            "oder PDF mit weniger als 10 MB."
        ),
        "dimensions": (
            "Die Bildabmessungen sind zu groß oder zu klein für die Verarbeitung. "
            "Bitte fotografieren Sie {document} erneut klar und vollständig."
        ),
        "unreadable": (
            "Ich konnte dieses Bild nicht lesen; es könnte beschädigt oder "
            "unklar sein. Bitte senden Sie ein neues, gut beleuchtetes Foto von "
            "{document}."
        ),
        "file_type": (
            "Das Dateiformat stimmt nicht mit dem Inhalt überein. Bitte senden "
            "Sie {document} als echte JPG-, PNG- oder PDF-Datei."
        ),
        "pdf": (
            "Ich konnte diese PDF-Datei nicht sicher lesen. Bitte senden Sie eine "
            "neue PDF-Datei oder ein klares JPG-/PNG-Foto von {document} mit "
            "weniger als 10 MB."
        ),
        "temporary": (
            "Ich konnte die Datei gerade nicht von WhatsApp herunterladen. Bitte "
            "warten Sie einen Moment und senden Sie {document} erneut."
        ),
        "generic": (
            "Ich konnte diese Datei nicht sicher speichern. Bitte senden Sie eine "
            "neue, klare JPG-, PNG- oder PDF-Datei von {document} mit weniger "
            "als 10 MB."
        ),
        "document": "das angeforderte Dokument",
    },
    "es": {
        "duplicate_document_content": (
            "Esta imagen es idéntica a un documento que ya enviaste, por lo que "
            "no pude usarla como {document}. Envía una imagen diferente que "
            "muestre {document}."
        ),
        "too_large": (
            "El archivo es demasiado grande. Envía {document} como JPG, PNG o "
            "PDF de menos de 10 MB."
        ),
        "dimensions": (
            "Las dimensiones de la imagen son demasiado grandes o pequeñas para "
            "procesarla. Toma una foto nueva y clara de {document} y vuelve a enviarla."
        ),
        "unreadable": (
            "No pude leer la imagen; puede estar dañada o poco clara. Toma una "
            "foto nueva, bien iluminada, de {document} y vuelve a enviarla."
        ),
        "file_type": (
            "El formato del archivo no coincide con su contenido. Envía "
            "{document} como un JPG, PNG o PDF auténtico."
        ),
        "pdf": (
            "No pude leer ese PDF de forma segura. Envía un PDF nuevo o una foto "
            "JPG o PNG clara de {document}, de menos de 10 MB."
        ),
        "temporary": (
            "No pude descargar el archivo de WhatsApp en este momento. Espera "
            "un momento y vuelve a enviar {document}."
        ),
        "generic": (
            "No pude guardar el archivo de forma segura. Envía un JPG, PNG o PDF "
            "nuevo y claro de {document}, de menos de 10 MB."
        ),
        "document": "el documento solicitado",
    },
}

_FAILURE_CATEGORY = {
    "duplicate_document_content": "duplicate_document_content",
    "media_too_large": "too_large",
    "invalid_document_size": "too_large",
    "invalid_image_dimensions": "dimensions",
    "invalid_image_document": "unreadable",
    "document_content_type_mismatch": "file_type",
    "invalid_pdf_document": "pdf",
    "active_pdf_rejected": "pdf",
    "media_transport_failed": "temporary",
    "media_stream_failed": "temporary",
    "media_provider_unavailable": "temporary",
}


def _failure_reply(locale: str, error_code: str, expected_slot: str) -> str:
    copy = _FAILURE_COPY[locale]
    category = _FAILURE_CATEGORY.get(error_code, "generic")
    document = _SLOT_LABELS[locale].get(expected_slot, copy["document"])
    return copy[category].format(document=document)


def _create_document_attention(workflow_case: dict, code: str) -> None:
    """Create one deduplicated staff item without document bytes or PII."""
    conversation_id = str(workflow_case.get("conversationId") or "")
    if not conversation_id:
        try:
            context = ali_customer_dossier.customer_delivery_context(
                str(workflow_case["reservationPublicId"]),
            )
            conversation_id = str(context["conversation_id"])
        except Exception:
            conversation_id = str(workflow_case.get("reservationPublicId") or "")
    try:
        state_registry.create_pending_notification(
            "escalation",
            "whatsapp",
            conversation_id,
            "Ali reservation customer",
            "[ALI RESERVATION DOCUMENT ATTENTION]",
            f"A direct WhatsApp document stopped safely. Code: {code}.",
            mode="hard",
        )
    except Exception as exc:
        bm_logger.log(
            "ali_reservation_v2_document_attention_failed",
            error_code=type(exc).__name__,
        )


def _locale(conversation_id: str) -> str:
    booking = state_registry.wa_get_booking_state(conversation_id) or {}
    value = str((booking.get("fields") or {}).get("conversation_language") or "en")
    value = value.lower().split("-", 1)[0]
    return value if value in _COPY else "en"


def process_structural_text(message: dict) -> dict:
    """Handle deterministic post-quote gates without invoking Nick/Claude."""
    text = str(message.get("text") or "").strip()
    if not ali_reservation_v2.enabled() or not text:
        return {"handled": False}
    conversation_id = str(message.get("_zernio_conversation_id") or "")
    account_id = str(message.get("_zernio_account_id") or "")
    workflow_case = ali_reservation_v2.get_active_case(conversation_id, account_id)
    if not workflow_case:
        return {"handled": False}
    message_id = str(
        message.get("message_id") or message.get("_zernio_event_id") or ""
    )
    ali_reservation_v2.note_client_activity(
        workflow_case["reservationPublicId"], message_id,
    )
    locale = _locale(conversation_id)
    if workflow_case.get("negativeIntentPending"):
        resolution = ali_reservation_v2.classify_ambiguous_resolution(text)
        if resolution != "none":
            resolved = ali_reservation_v2.resolve_ambiguous_negative(
                workflow_case["reservationPublicId"],
                resolution,
                source_message_id=message_id,
            )
            return {
                "handled": True,
                "success": True,
                "reply": _COPY[locale][
                    "more_time" if resolution == "more_time" else "cancelled"
                ],
                "workflow_v2": resolved["case"],
            }
    intent = ali_reservation_v2.classify_structural_intent(text)
    classification = intent["classification"]
    if classification == "vehicle_rejection":
        ali_reservation_v2.apply_negative_intent(
            workflow_case["reservationPublicId"],
            classification,
            source_message_id=message_id,
        )
        # The structured quote/change arbiter still owns the natural reply.
        return {"handled": False, "negative_intent_recorded": True}
    if classification in {
        "global_opt_out", "reservation_decline", "ambiguous_negative",
    }:
        applied = ali_reservation_v2.apply_negative_intent(
            workflow_case["reservationPublicId"],
            classification,
            source_message_id=message_id,
        )
        key = {
            "global_opt_out": "opt_out",
            "reservation_decline": "cancelled",
            "ambiguous_negative": "ambiguous",
        }[classification]
        return {
            "handled": True,
            "success": True,
            "reply": _COPY[locale][key],
            "workflow_v2": applied["case"],
        }

    if (
        workflow_case["state"] == "documents_collecting"
        and not workflow_case.get("identityType")
    ):
        try:
            updated = ali_reservation_v2.set_identity_type(
                workflow_case["reservationPublicId"], text,
                message_id=message_id,
            )
        except Exception as exc:
            if str(getattr(exc, "code", "")) == "identity_type_not_recognized":
                return {"handled": False}
            raise
        expected_slot = str(updated.get("expectedDocumentSlot") or "")
        bm_logger.log(
            "ali_reservation_v2_identity_prompt_planned",
            identity_type=str(updated.get("identityType") or ""),
            expected_document_slot=expected_slot,
        )
        return {
            "handled": True,
            "success": True,
            "reply": _COPY[locale]["identity"].format(
                document=_SLOT_LABELS[locale].get(
                    expected_slot,
                    expected_slot or "document",
                ),
            ),
            "workflow_v2": updated,
            "continue_to_documents": bool(message.get("_zernio_attachments")),
        }

    if workflow_case["state"] == "payment_link_sent":
        from agents.social.ali_customer_dossier import is_customer_payment_report
        if is_customer_payment_report(text):
            try:
                ali_customer_dossier.record_customer_payment_report(
                    conversation_id,
                    account_id,
                    action_id=message_id,
                )
            except AliReservationError as exc:
                if exc.code != "payment_window_expired":
                    raise
                updated = ali_reservation_v2.transition(
                    workflow_case["reservationPublicId"],
                    "hold_expired",
                    actor_type="system",
                    actor_id="payment-window",
                    idempotency_key=f"payment-expired:{message_id}",
                    reason="payment_window_expired",
                    expected_revision=workflow_case["revision"],
                )
                return {
                    "handled": True,
                    "success": True,
                    "reply": _COPY[locale]["payment_expired"],
                    "workflow_v2": updated,
                }
            updated = ali_reservation_v2.transition(
                workflow_case["reservationPublicId"],
                "customer_reports_paid",
                actor_type="customer",
                actor_id="whatsapp",
                idempotency_key=f"payment-report:{message_id}",
                reason="customer_reported_payment",
                expected_revision=workflow_case["revision"],
            )
            return {
                "handled": True,
                "success": True,
                "reply": _COPY[locale]["payment"],
                "workflow_v2": updated,
            }
    return {"handled": False}


def process_whatsapp_documents(message: dict) -> dict:
    """Store an expected Ali V2 document bundle and return one safe reply."""
    attachments = [
        dict(item)
        for item in message.get("_zernio_attachments") or []
        if isinstance(item, dict)
    ]
    if not ali_reservation_v2.enabled() or not attachments:
        return {"handled": False}

    conversation_id = str(message.get("_zernio_conversation_id") or "")
    account_id = str(message.get("_zernio_account_id") or "")
    workflow_case = ali_reservation_v2.get_active_case(conversation_id, account_id)
    if not workflow_case:
        return {"handled": False}

    collecting = workflow_case["state"] in {
        "documents_collecting", "document_replacement_required",
    }
    expected = str(workflow_case.get("expectedDocumentSlot") or "")
    outside_checklist = not collecting or not expected

    # Store unexpected extras first as unclassified.  The expected document is
    # committed last because it may advance the workflow to staff review.
    if outside_checklist:
        ordered = [
            (item, "unclassified", "unclassified") for item in attachments
        ]
    else:
        ordered = [
            (item, "unclassified", "unclassified")
            for item in attachments[1:]
        ] + [(attachments[0], expected, "expected_slot")]
    stored = []
    current_item = {}
    current_media = {}
    try:
        for item, slot, source in ordered:
            current_item = item
            media = download_whatsapp_media(item.get("media_id"), account_id)
            current_media = media
            claimed_mime = str(item.get("mime_type") or media["content_type"])
            stored.append(ali_customer_dossier.store_whatsapp_document(
                workflow_case["reservationPublicId"],
                slot=slot,
                payload=media["payload"],
                claimed_mime=claimed_mime,
                provider_message_id=str(
                    item.get("provider_message_id")
                    or message.get("message_id")
                    or message.get("_zernio_event_id")
                    or ""
                ),
                provider_attachment_id=str(item.get("provider_attachment_id") or ""),
                filename=str(item.get("filename") or ""),
                classification_source=source,
            ))
    except Exception as exc:
        error_code = str(getattr(exc, "code", type(exc).__name__))[:80]
        bm_logger.log(
            "ali_reservation_v2_document_failed",
            reservation_public_id=workflow_case["reservationPublicId"],
            error_code=error_code,
            expected_document_slot=expected or "",
            attachment_count=len(attachments),
            claimed_mime=str(current_item.get("mime_type") or "")[:80],
            size_bytes=int(current_media.get("size_bytes") or 0),
        )
        _create_document_attention(workflow_case, error_code)
        return {
            "handled": True,
            "success": False,
            "reply": _failure_reply(
                _locale(conversation_id), error_code, expected,
            ),
            "error_code": error_code,
            "reservation_public_id": workflow_case["reservationPublicId"],
        }

    updated = stored[-1]["workflowV2"]
    locale = _locale(conversation_id)
    if outside_checklist:
        return {
            "handled": True,
            "success": True,
            "reply": _COPY[locale]["unclassified"],
            "reservation_public_id": workflow_case["reservationPublicId"],
            "document_count": len(stored),
            "workflow_v2": updated,
        }
    labels = _SLOT_LABELS[locale]
    next_slot = str(updated.get("expectedDocumentSlot") or "")
    if next_slot:
        reply = _COPY[locale]["next"].format(
            stored=labels.get(expected, expected),
            next=labels.get(next_slot, next_slot),
        )
    else:
        reply = _COPY[locale]["review"]
    if len(attachments) > 1:
        reply += _COPY[locale]["extras"].format(count=len(attachments) - 1)
    bm_logger.log(
        "ali_reservation_v2_document_stored",
        reservation_public_id=workflow_case["reservationPublicId"],
        expected_document_slot=expected,
        next_document_slot=next_slot,
        document_count=len(stored),
        replayed=any(bool(item.get("replayed")) for item in stored),
    )
    return {
        "handled": True,
        "success": True,
        "reply": reply,
        "reservation_public_id": workflow_case["reservationPublicId"],
        "document_count": len(stored),
        "workflow_v2": updated,
    }
