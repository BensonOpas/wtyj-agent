"""Deterministic Ali reservation V2 inbound document handling.

Media bytes are downloaded from Zernio's authenticated endpoint, validated and
stored privately before any customer acknowledgement.  Nothing in this path is
sent to Nick/Claude and no provider URL is retained.
"""

from __future__ import annotations

from agents.social import ali_customer_dossier, ali_reservation_v2
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
}

_COPY = {
    "en": {
        "next": "Got it — {stored} is stored securely. Please send {next} next.",
        "review": "Got it — your documents are stored securely. Our team will review them now.",
        "failed": "I couldn't store that file safely. Please resend it as a clear JPG, PNG, or PDF under 10 MB.",
        "unclassified": "I stored the file securely, but I’m not expecting a document at this step. What document is it?",
        "extras": " I also stored {count} extra file(s) securely. Please tell me what they are.",
        "identity": "Thanks. Please send the front of your driver's license here in WhatsApp.",
        "opt_out": "Understood. I won't send you any more messages.",
        "cancelled": "Understood. I’ve stopped this reservation request.",
        "ambiguous": "Would you like me to stop this reservation, or would you like more time?",
        "more_time": "No problem. I’ll keep the reservation on hold while you continue.",
        "payment": "Thanks — our team will verify the payment now.",
    },
    "nl": {
        "next": "Ontvangen — {stored} is veilig opgeslagen. Stuur nu {next}.",
        "review": "Ontvangen — je documenten zijn veilig opgeslagen. Ons team beoordeelt ze nu.",
        "failed": "Ik kon dat bestand niet veilig opslaan. Stuur het opnieuw als duidelijke JPG, PNG of PDF onder 10 MB.",
        "unclassified": "Ik heb het bestand veilig opgeslagen, maar verwacht nu geen document. Welk document is het?",
        "extras": " Ik heb ook {count} extra bestand(en) veilig opgeslagen. Laat weten wat ze zijn.",
        "identity": "Bedankt. Stuur nu de voorkant van je rijbewijs hier in WhatsApp.",
        "opt_out": "Begrepen. Ik stuur je geen berichten meer.",
        "cancelled": "Begrepen. Ik heb deze reserveringsaanvraag gestopt.",
        "ambiguous": "Wil je dat ik deze reservering stop, of wil je meer tijd?",
        "more_time": "Geen probleem. Ik houd de reservering vast terwijl je verdergaat.",
        "payment": "Bedankt — ons team controleert de betaling nu.",
    },
    "pap": {
        "next": "Risibí — {stored} ta warda sigur. Awor manda {next}.",
        "review": "Risibí — bo dokumentonan ta warda sigur. Nos team lo kontrolá nan awor.",
        "failed": "Mi no por a warda e file ei sigur. Manda'é atrobe komo un JPG, PNG òf PDF kla bou di 10 MB.",
        "unclassified": "Mi a warda e file sigur, pero mi no ta spera un dokumento den e paso aki. Kua dokumento e ta?",
        "extras": " Mi a warda tambe {count} file extra sigur. Laga mi sa kiko nan ta.",
        "identity": "Danki. Manda e parti dilanti di bo reibeweis aki den WhatsApp.",
        "opt_out": "Komprondé. Mi no ta manda bo mas mensahe.",
        "cancelled": "Komprondé. Mi a stòp e petishon di reservashon aki.",
        "ambiguous": "Bo ke pa mi stòp e reservashon aki, òf bo ke mas tempu?",
        "more_time": "No tin problema. Mi ta tene e reservashon mientras bo ta sigui.",
        "payment": "Danki — nos team lo verifiká e pago awor.",
    },
    "de": {
        "next": "Erhalten — {stored} wurde sicher gespeichert. Bitte senden Sie jetzt {next}.",
        "review": "Erhalten — Ihre Dokumente wurden sicher gespeichert. Unser Team prüft sie jetzt.",
        "failed": "Ich konnte diese Datei nicht sicher speichern. Bitte senden Sie sie erneut als klare JPG-, PNG- oder PDF-Datei unter 10 MB.",
        "unclassified": "Ich habe die Datei sicher gespeichert, erwarte in diesem Schritt aber kein Dokument. Um welches Dokument handelt es sich?",
        "extras": " Ich habe außerdem {count} zusätzliche Datei(en) sicher gespeichert. Bitte teilen Sie mir mit, was sie sind.",
        "identity": "Danke. Bitte senden Sie jetzt die Vorderseite Ihres Führerscheins hier in WhatsApp.",
        "opt_out": "Verstanden. Ich werde Ihnen keine weiteren Nachrichten senden.",
        "cancelled": "Verstanden. Ich habe diese Reservierungsanfrage beendet.",
        "ambiguous": "Soll ich diese Reservierung beenden, oder möchten Sie mehr Zeit?",
        "more_time": "Kein Problem. Ich halte die Reservierung, während Sie fortfahren.",
        "payment": "Danke — unser Team prüft die Zahlung jetzt.",
    },
}


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
        return {
            "handled": True,
            "success": True,
            "reply": _COPY[locale]["identity"],
            "workflow_v2": updated,
            "continue_to_documents": bool(message.get("_zernio_attachments")),
        }

    if workflow_case["state"] == "payment_link_sent":
        from agents.social.ali_customer_dossier import is_customer_payment_report
        if is_customer_payment_report(text):
            ali_customer_dossier.record_customer_payment_report(
                conversation_id,
                account_id,
                action_id=message_id,
            )
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
    try:
        for item, slot, source in ordered:
            media = download_whatsapp_media(item.get("media_id"), account_id)
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
        )
        _create_document_attention(workflow_case, error_code)
        return {
            "handled": True,
            "success": False,
            "reply": _COPY[_locale(conversation_id)]["failed"],
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
    return {
        "handled": True,
        "success": True,
        "reply": reply,
        "reservation_public_id": workflow_case["reservationPublicId"],
        "document_count": len(stored),
        "workflow_v2": updated,
    }
