import asyncio
from unittest.mock import patch

from fastapi import HTTPException

from agents.social.zernio_dm_client import WhatsAppWindowClosedError
from dashboard import api


def test_dashboard_whatsapp_reply_keeps_operator_text_verbatim():
    message = "  Hola Vanessa.\n\nTe escribimos cuando puedas.  "

    with (
        patch("dashboard.api.send_whatsapp_message", return_value=True) as send,
        patch.object(api.state_registry, "wa_store_message") as store,
    ):
        response = asyncio.run(
            api.reply_to_whatsapp_conversation(
                "conversation-1",
                api.WhatsAppConversationReplyRequest(message=message),
            )
        )

    send.assert_called_once_with(
        "conversation-1", message, confirm_delivery=True
    )
    store.assert_called_once_with("conversation-1", "operator", message)
    assert response["reply"] == message
    assert response["original_message_sent"] is True


def test_dashboard_whatsapp_reply_never_substitutes_a_template_when_window_closed():
    message = "Mensaje humano exacto"

    with (
        patch(
            "dashboard.api.send_whatsapp_message",
            side_effect=WhatsAppWindowClosedError("window closed"),
        ),
        patch("dashboard.api.send_whatsapp_template_message") as template_send,
        patch.object(api.state_registry, "wa_store_message") as store,
    ):
        try:
            asyncio.run(
                api.reply_to_whatsapp_conversation(
                    "conversation-1",
                    api.WhatsAppConversationReplyRequest(message=message),
                )
            )
        except HTTPException as exc:
            assert exc.status_code == 409
            assert "No se ha enviado ningún mensaje" in exc.detail
        else:
            raise AssertionError("The closed window must reject, not rewrite")

    template_send.assert_not_called()
    store.assert_not_called()
