import os
import sys
from unittest.mock import Mock, patch

import pytest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("LATE_API_KEY", "test-zernio-key")

from agents.social.channels.whatsapp_zernio import WhatsAppZernioChannel
from agents.social.zernio_dm_client import parse_zernio_webhook
from agents.social.zernio_whatsapp_media import (
    ZernioMediaError,
    download_whatsapp_media,
)
from agents.social.ali_reservation_v2_inbound import (
    process_structural_text,
    process_whatsapp_documents,
)


def _payload(*, text="", attachments=None):
    return {
        "id": "event-media-1",
        "event": "message.received",
        "account": {"id": "account-1"},
        "data": {
            "conversationId": "conversation-1",
            "id": "message-1",
            "platform": "whatsapp",
            "text": text,
            "sender": {"id": "+351963618055", "name": "Synthetic"},
            "attachments": attachments or [],
        },
    }


def test_parser_keeps_only_authenticated_media_identifiers():
    parsed = parse_zernio_webhook(_payload(attachments=[{
        "id": "attachment-1",
        "type": "document",
        "filename": "license.pdf",
        "mimeType": "application/pdf",
        "url": "https://provider.invalid/secret",
        "payload": {"id": "media-1"},
    }]))

    assert parsed["text"] == ""
    assert parsed["event_id"] == "event-media-1"
    assert parsed["attachments"] == [{
        "provider_attachment_id": "attachment-1",
        "media_id": "media-1",
        "type": "document",
        "filename": "license.pdf",
        "mime_type": "application/pdf",
    }]
    assert "provider.invalid" not in repr(parsed)


def test_adapter_preserves_media_for_debounced_whatsapp_path():
    parsed = parse_zernio_webhook(_payload(attachments=[{
        "id": "attachment-1",
        "type": "image",
        "payload": {"id": "media-1"},
    }]))

    adapted = WhatsAppZernioChannel.from_zernio(parsed)

    assert adapted["text"] == ""
    assert adapted["_zernio_event_id"] == "event-media-1"
    assert adapted["_zernio_attachments"][0]["media_id"] == "media-1"


def _response(*, status=200, body=b"%PDF-test", headers=None):
    response = Mock()
    response.status_code = status
    response.headers = headers or {
        "Content-Type": "application/pdf",
        "Content-Length": str(len(body)),
    }
    response.iter_content.return_value = [body]
    return response


@patch("agents.social.zernio_whatsapp_media.requests.get")
def test_download_uses_authenticated_endpoint_without_redirects(
    mock_get,
    monkeypatch,
):
    monkeypatch.setenv("LATE_API_KEY", "test-zernio-key")
    mock_get.return_value = _response()

    result = download_whatsapp_media("media-1", "account-1")

    assert result["payload"] == b"%PDF-test"
    assert result["content_type"] == "application/pdf"
    _, kwargs = mock_get.call_args
    assert kwargs["headers"] == {"Authorization": "Bearer test-zernio-key"}
    assert kwargs["params"] == {"accountId": "account-1"}
    assert kwargs["allow_redirects"] is False


@pytest.mark.parametrize("status,retryable", [(400, False), (429, True), (503, True)])
@patch("agents.social.zernio_whatsapp_media.requests.get")
def test_download_classifies_provider_failures(mock_get, status, retryable):
    mock_get.return_value = _response(status=status)

    with pytest.raises(ZernioMediaError) as error:
        download_whatsapp_media("media-1", "account-1")

    assert error.value.retryable is retryable


@patch("agents.social.zernio_whatsapp_media.requests.get")
def test_download_rejects_redirect_and_oversized_stream(mock_get):
    mock_get.return_value = _response(status=302, headers={"Location": "https://x.invalid"})
    with pytest.raises(ZernioMediaError, match="media_redirect_rejected"):
        download_whatsapp_media("media-1", "account-1")

    mock_get.return_value = _response(
        body=b"x" * 5,
        headers={"Content-Type": "image/jpeg", "Content-Length": "11"},
    )
    with pytest.raises(ZernioMediaError, match="media_too_large"):
        download_whatsapp_media("media-1", "account-1", max_bytes=10)


@patch("agents.social.ali_reservation_v2_inbound.state_registry.wa_get_booking_state")
@patch("agents.social.ali_reservation_v2_inbound.ali_customer_dossier.store_whatsapp_document")
@patch("agents.social.ali_reservation_v2_inbound.download_whatsapp_media")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.get_active_case")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.enabled")
def test_expected_media_is_stored_then_next_slot_is_requested(
    enabled, get_case, download, store, booking,
):
    enabled.return_value = True
    get_case.return_value = {
        "reservationPublicId": "reservation-1",
        "state": "documents_collecting",
        "expectedDocumentSlot": "license_front",
    }
    download.return_value = {
        "payload": b"\xff\xd8\xffvalid",
        "content_type": "image/jpeg",
    }
    store.return_value = {
        "workflowV2": {
            "state": "documents_collecting",
            "expectedDocumentSlot": "license_back",
        },
    }
    booking.return_value = {"fields": {"conversation_language": "en"}}

    result = process_whatsapp_documents({
        "message_id": "message-1",
        "_zernio_event_id": "event-1",
        "_zernio_conversation_id": "conversation-1",
        "_zernio_account_id": "account-1",
        "_zernio_attachments": [{
            "media_id": "media-1",
            "provider_attachment_id": "attachment-1",
            "mime_type": "image/jpeg",
        }],
    })

    assert result["handled"] is True
    assert result["success"] is True
    assert "back of your driver's license" in result["reply"]
    store.assert_called_once()
    assert store.call_args.kwargs["slot"] == "license_front"
    assert store.call_args.kwargs["provider_message_id"] == "message-1"


@patch("agents.social.ali_reservation_v2_inbound.state_registry.wa_get_booking_state")
@patch("agents.social.ali_reservation_v2_inbound.ali_customer_dossier.store_whatsapp_document")
@patch("agents.social.ali_reservation_v2_inbound.download_whatsapp_media")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.get_active_case")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.enabled")
def test_passport_is_stored_before_drivers_license_is_requested(
    enabled, get_case, download, store, booking,
):
    enabled.return_value = True
    get_case.return_value = {
        "reservationPublicId": "reservation-1",
        "state": "documents_collecting",
        "expectedDocumentSlot": "passport",
    }
    download.return_value = {
        "payload": b"%PDF-valid",
        "content_type": "application/pdf",
    }
    store.return_value = {
        "workflowV2": {
            "state": "documents_collecting",
            "expectedDocumentSlot": "license_front",
        },
    }
    booking.return_value = {"fields": {"conversation_language": "en"}}

    result = process_whatsapp_documents({
        "message_id": "message-passport-1",
        "_zernio_event_id": "event-passport-1",
        "_zernio_conversation_id": "conversation-1",
        "_zernio_account_id": "account-1",
        "_zernio_attachments": [{
            "media_id": "media-passport-1",
            "provider_attachment_id": "attachment-passport-1",
            "mime_type": "application/pdf",
        }],
    })

    assert result["success"] is True
    assert result["reply"] == (
        "Got it — your passport is stored securely. Please send "
        "the front of your driver's license next."
    )
    assert store.call_args.kwargs["slot"] == "passport"


@patch("agents.social.ali_reservation_v2_inbound.state_registry.wa_get_booking_state")
@patch("agents.social.ali_reservation_v2_inbound.ali_customer_dossier.store_whatsapp_document")
@patch("agents.social.ali_reservation_v2_inbound.download_whatsapp_media")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.get_active_case")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.enabled")
def test_multiple_media_stores_extras_unclassified_before_expected(
    enabled, get_case, download, store, booking,
):
    enabled.return_value = True
    get_case.return_value = {
        "reservationPublicId": "reservation-1",
        "state": "documents_collecting",
        "expectedDocumentSlot": "passport",
    }
    download.return_value = {
        "payload": b"%PDF-valid",
        "content_type": "application/pdf",
    }
    store.side_effect = [
        {"workflowV2": {"state": "documents_collecting", "expectedDocumentSlot": "passport"}},
        {"workflowV2": {"state": "document_review_pending", "expectedDocumentSlot": None}},
    ]
    booking.return_value = {"fields": {"conversation_language": "en"}}

    result = process_whatsapp_documents({
        "message_id": "message-1",
        "_zernio_conversation_id": "conversation-1",
        "_zernio_account_id": "account-1",
        "_zernio_attachments": [
            {"media_id": "media-1", "provider_attachment_id": "attachment-1"},
            {"media_id": "media-2", "provider_attachment_id": "attachment-2"},
        ],
    })

    assert result["success"] is True
    assert "review" in result["reply"]
    assert [call.kwargs["slot"] for call in store.call_args_list] == [
        "unclassified", "passport",
    ]
    assert "extra file" in result["reply"]


@patch("agents.social.ali_reservation_v2_inbound.state_registry.wa_get_booking_state")
@patch("agents.social.ali_reservation_v2_inbound.ali_customer_dossier.store_whatsapp_document")
@patch("agents.social.ali_reservation_v2_inbound.download_whatsapp_media")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.get_active_case")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.enabled")
def test_media_outside_checklist_is_stored_unclassified_and_not_guessed(
    enabled, get_case, download, store, booking,
):
    enabled.return_value = True
    get_case.return_value = {
        "reservationPublicId": "reservation-1",
        "state": "contract_sent",
        "expectedDocumentSlot": None,
    }
    download.return_value = {
        "payload": b"%PDF-valid",
        "content_type": "application/pdf",
    }
    store.return_value = {
        "workflowV2": {
            "state": "contract_sent",
            "expectedDocumentSlot": None,
        },
    }
    booking.return_value = {"fields": {"conversation_language": "en"}}

    result = process_whatsapp_documents({
        "message_id": "message-outside-1",
        "_zernio_conversation_id": "conversation-1",
        "_zernio_account_id": "account-1",
        "_zernio_attachments": [{
            "media_id": "media-outside-1",
            "provider_attachment_id": "attachment-outside-1",
        }],
    })

    assert result["handled"] is True
    assert result["success"] is True
    assert "What document is it?" in result["reply"]
    assert store.call_args.kwargs["slot"] == "unclassified"


@patch("agents.social.ali_reservation_v2_inbound.state_registry.create_pending_notification")
@patch("agents.social.ali_reservation_v2_inbound.ali_customer_dossier.customer_delivery_context")
@patch("agents.social.ali_reservation_v2_inbound.state_registry.wa_get_booking_state")
@patch("agents.social.ali_reservation_v2_inbound.download_whatsapp_media")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.get_active_case")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.enabled")
def test_media_failure_fails_closed_and_creates_staff_attention(
    enabled, get_case, download, booking, context, notify,
):
    enabled.return_value = True
    get_case.return_value = {
        "reservationPublicId": "reservation-1",
        "state": "documents_collecting",
        "expectedDocumentSlot": "license_front",
    }
    download.side_effect = ZernioMediaError("media_provider_unavailable", retryable=True)
    booking.return_value = {"fields": {"conversation_language": "en"}}
    context.return_value = {"conversation_id": "conversation-1"}

    result = process_whatsapp_documents({
        "message_id": "message-1",
        "_zernio_conversation_id": "conversation-1",
        "_zernio_account_id": "account-1",
        "_zernio_attachments": [{
            "media_id": "media-1",
            "provider_attachment_id": "attachment-1",
        }],
    })

    assert result["handled"] is True
    assert result["success"] is False
    notify.assert_called_once()
    assert "media_provider_unavailable" in notify.call_args.args[5]


@patch("agents.social.ali_reservation_v2_inbound.state_registry.wa_get_booking_state")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.set_identity_type")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.note_client_activity")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.get_active_case")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.enabled")
def test_identity_type_is_selected_without_a_claude_turn(
    enabled, get_case, note_activity, set_identity, booking,
):
    enabled.return_value = True
    get_case.return_value = {
        "reservationPublicId": "reservation-1",
        "state": "documents_collecting",
        "identityType": None,
    }
    set_identity.return_value = {
        "state": "documents_collecting",
        "identityType": "passport",
        "expectedDocumentSlot": "passport",
    }
    booking.return_value = {"fields": {"conversation_language": "en"}}

    result = process_structural_text({
        "text": "passport",
        "message_id": "message-1",
        "_zernio_conversation_id": "conversation-1",
        "_zernio_account_id": "account-1",
    })

    assert result["handled"] is True
    assert result["reply"] == (
        "Thanks. Please send your passport here in WhatsApp."
    )
    note_activity.assert_called_once_with("reservation-1", "message-1")
    set_identity.assert_called_once_with(
        "reservation-1", "passport", message_id="message-1",
    )


@pytest.mark.parametrize(
    "locale,choice,identity_type,slot,expected_reply",
    [
        (
            "en", "passport", "passport", "passport",
            "Thanks. Please send your passport here in WhatsApp.",
        ),
        (
            "nl", "paspoort", "passport", "passport",
            "Bedankt. Stuur nu je paspoort hier in WhatsApp.",
        ),
        (
            "pap", "pasport", "passport", "passport",
            "Danki. Manda bo pasport aki den WhatsApp.",
        ),
        (
            "de", "Reisepass", "passport", "passport",
            "Danke. Bitte senden Sie jetzt Ihren Reisepass hier über WhatsApp.",
        ),
        (
            "en", "ID card", "id_card", "identity_front",
            "Thanks. Please send the front of your ID card here in WhatsApp.",
        ),
        (
            "nl", "identiteitskaart", "id_card", "identity_front",
            "Bedankt. Stuur nu de voorkant van je identiteitskaart hier in WhatsApp.",
        ),
        (
            "pap", "karta di identidat", "id_card", "identity_front",
            "Danki. Manda e parti dilanti di bo karta di identidat aki den WhatsApp.",
        ),
        (
            "de", "Personalausweis", "id_card", "identity_front",
            "Danke. Bitte senden Sie jetzt die Vorderseite Ihres Personalausweises hier über WhatsApp.",
        ),
    ],
)
@patch("agents.social.ali_reservation_v2_inbound.state_registry.wa_get_booking_state")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.set_identity_type")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.note_client_activity")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.get_active_case")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.enabled")
def test_identity_prompt_matches_persisted_choice_in_all_locales(
    enabled, get_case, note_activity, set_identity, booking,
    locale, choice, identity_type, slot, expected_reply,
):
    enabled.return_value = True
    get_case.return_value = {
        "reservationPublicId": "reservation-1",
        "state": "documents_collecting",
        "identityType": None,
    }
    set_identity.return_value = {
        "state": "documents_collecting",
        "identityType": identity_type,
        "expectedDocumentSlot": slot,
    }
    booking.return_value = {"fields": {"conversation_language": locale}}

    result = process_structural_text({
        "text": choice,
        "message_id": "message-locale-1",
        "_zernio_conversation_id": "conversation-1",
        "_zernio_account_id": "account-1",
    })

    assert result["handled"] is True
    assert result["reply"] == expected_reply
    set_identity.assert_called_once_with(
        "reservation-1", choice, message_id="message-locale-1",
    )


@patch("agents.social.ali_reservation_v2_inbound.state_registry.wa_get_booking_state")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.apply_negative_intent")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.note_client_activity")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.get_active_case")
@patch("agents.social.ali_reservation_v2_inbound.ali_reservation_v2.enabled")
def test_global_opt_out_is_structural_and_does_not_reach_nick(
    enabled, get_case, note_activity, apply_intent, booking,
):
    enabled.return_value = True
    get_case.return_value = {
        "reservationPublicId": "reservation-1",
        "state": "documents_collecting",
        "identityType": "passport",
    }
    apply_intent.return_value = {
        "case": {"state": "client_opted_out"},
        "action": "acknowledge_opt_out_once",
        "repeated": False,
    }
    booking.return_value = {"fields": {"conversation_language": "en"}}

    result = process_structural_text({
        "text": "stop messaging me",
        "message_id": "message-2",
        "_zernio_conversation_id": "conversation-1",
        "_zernio_account_id": "account-1",
    })

    assert result["handled"] is True
    assert result["reply"] == "Understood. I won't send you any more messages."
    apply_intent.assert_called_once_with(
        "reservation-1", "global_opt_out", source_message_id="message-2",
    )
