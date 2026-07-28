"""Tests for direct operator replies from the Inbox conversation pane."""

import asyncio

import pytest
from fastapi import HTTPException

from dashboard import api


def test_whatsapp_conversation_reply_sends_before_storing(monkeypatch):
    events = []

    def fake_send(conversation_id, message, confirm_delivery=False):
        events.append(("send", conversation_id, message, confirm_delivery))
        return True

    def fake_store(conversation_id, role, message):
        events.append(("store", conversation_id, role, message))

    monkeypatch.setattr(api, "send_whatsapp_message", fake_send)
    monkeypatch.setattr(api.state_registry, "wa_store_message", fake_store)

    result = asyncio.run(
        api.reply_to_whatsapp_conversation(
            "  0123456789abcdef01234567\n",
            api.WhatsAppConversationReplyRequest(message="  Hola, Lucia  "),
        )
    )

    assert events == [
        ("send", "0123456789abcdef01234567", "Hola, Lucia", True),
        ("store", "0123456789abcdef01234567", "operator", "Hola, Lucia"),
    ]
    assert result == {
        "ok": True,
        "reply": "Hola, Lucia",
        "channel": "whatsapp",
        "role": "operator",
        "delivery_mode": "free_text",
        "original_message_sent": True,
    }


def test_whatsapp_conversation_reply_is_not_stored_when_zernio_fails(monkeypatch):
    stored = []
    monkeypatch.setattr(api, "send_whatsapp_message", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(api.state_registry, "wa_store_message", lambda *args: stored.append(args))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            api.reply_to_whatsapp_conversation(
                "0123456789abcdef01234567",
                api.WhatsAppConversationReplyRequest(message="Hola"),
            )
        )

    assert exc_info.value.status_code == 502
    assert "WhatsApp" in str(exc_info.value.detail)
    assert stored == []


@pytest.mark.parametrize("message", ["", "   ", "x" * 4097])
def test_whatsapp_conversation_reply_rejects_invalid_messages(monkeypatch, message):
    sent = []
    monkeypatch.setattr(api, "send_whatsapp_message", lambda *args: sent.append(args) or True)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            api.reply_to_whatsapp_conversation(
                "0123456789abcdef01234567",
                api.WhatsAppConversationReplyRequest(message=message),
            )
        )

    assert exc_info.value.status_code == 400
    assert sent == []

def test_stable_whatsapp_reply_route_is_registered_for_post():
    matches = [
        route
        for route in api.router.routes
        if getattr(route, "path", None) == "/dashboard/api/messages/whatsapp/reply"
    ]

    assert len(matches) == 1
    assert "POST" in matches[0].methods


def test_stable_whatsapp_reply_delegates_to_provider_send(monkeypatch):
    events = []

    monkeypatch.setattr(
        api,
        "send_whatsapp_message",
        lambda conversation_id, message, confirm_delivery=False: events.append(
            ("send", conversation_id, message, confirm_delivery)
        ) or True,
    )
    monkeypatch.setattr(
        api.state_registry,
        "wa_store_message",
        lambda conversation_id, role, message: events.append(
            ("store", conversation_id, role, message)
        ),
    )

    result = asyncio.run(
        api.reply_to_whatsapp_conversation_direct(
            api.DirectWhatsAppConversationReplyRequest(
                conversation_id="0123456789abcdef01234567",
                message="Hola desde recepción",
            )
        )
    )

    assert result["ok"] is True
    assert events == [
        (
            "send",
            "0123456789abcdef01234567",
            "Hola desde recepción",
            True,
        ),
        (
            "store",
            "0123456789abcdef01234567",
            "operator",
            "Hola desde recepción",
        ),
    ]

def test_whatsapp_window_closed_is_not_reported_as_sent(monkeypatch):
    stored = []

    def raise_window_closed(*_args, **_kwargs):
        raise api.WhatsAppWindowClosedError(
            "Han pasado más de 24 horas desde el último mensaje del contacto."
        )

    monkeypatch.setattr(api, "send_whatsapp_message", raise_window_closed)
    monkeypatch.setattr(
        api,
        "send_whatsapp_template_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            api.ZernioReplyError(
                "La plantilla de seguimiento está pendiente de aprobación de Meta."
            )
        ),
    )
    monkeypatch.setattr(
        api.state_registry,
        "wa_store_message",
        lambda *args: stored.append(args),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            api.reply_to_whatsapp_conversation(
                "0123456789abcdef01234567",
                api.WhatsAppConversationReplyRequest(message="Hola"),
            )
        )

    assert exc_info.value.status_code == 409
    assert "pendiente" in str(exc_info.value.detail)
    assert stored == []


def test_provider_delivery_failure_is_not_stored(monkeypatch):
    stored = []

    def raise_delivery_failed(*_args, **_kwargs):
        raise api.ZernioReplyError(
            "WhatsApp marcó el mensaje como fallido."
        )

    monkeypatch.setattr(api, "send_whatsapp_message", raise_delivery_failed)
    monkeypatch.setattr(
        api.state_registry,
        "wa_store_message",
        lambda *args: stored.append(args),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            api.reply_to_whatsapp_conversation(
                "0123456789abcdef01234567",
                api.WhatsAppConversationReplyRequest(message="Hola"),
            )
        )

    assert exc_info.value.status_code == 502
    assert "fallido" in str(exc_info.value.detail)
    assert stored == []

def test_closed_window_sends_template_and_stores_template_text(monkeypatch):
    stored = []

    def raise_window_closed(*_args, **_kwargs):
        raise api.WhatsAppWindowClosedError("window closed")

    monkeypatch.setattr(api, "send_whatsapp_message", raise_window_closed)
    monkeypatch.setattr(
        api,
        "send_whatsapp_template_message",
        lambda conversation_id, template_name, language="es": (
            conversation_id == "0123456789abcdef01234567"
            and template_name == "consulta_despertares_seguimiento"
            and language == "es"
        ),
    )
    monkeypatch.setattr(
        api.state_registry,
        "wa_store_message",
        lambda *args: stored.append(args),
    )

    result = asyncio.run(
        api.reply_to_whatsapp_conversation(
            "0123456789abcdef01234567",
            api.WhatsAppConversationReplyRequest(message="texto libre"),
        )
    )

    assert result["delivery_mode"] == "template"
    assert result["original_message_sent"] is False
    assert result["reply"] == api._DESPERTARES_REENGAGEMENT_TEXT
    assert stored == [(
        "0123456789abcdef01234567",
        "operator",
        api._DESPERTARES_REENGAGEMENT_TEXT,
    )]

