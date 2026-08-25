# bluemarlin/agents/social/zernio_dm_client.py
# Created: Brief 130
# Purpose: Parse Zernio webhook payloads + send DM replies via Zernio Inbox API

import hashlib
import hmac
import os
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests as http_requests

from late import Late
from shared import bm_logger


def _get_client():
    """Create a Late/Zernio API client. Returns None if no API key."""
    api_key = os.environ.get("LATE_API_KEY", "")
    if not api_key:
        bm_logger.log("zernio_dm_no_api_key")
        return None
    return Late(api_key=api_key)


def verify_webhook_signature(payload_bytes: bytes, signature: str) -> bool:
    """Verify Zernio webhook HMAC-SHA256 signature. Returns True if valid."""
    secret = os.environ.get("ZERNIO_WEBHOOK_SECRET", "")
    if not secret:
        bm_logger.log("zernio_webhook_no_secret")
        return False
    expected = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_zernio_webhook(payload: dict) -> dict | None:
    """Parse a Zernio webhook payload into a normalized message dict.
    Returns None if not a message.received event or if parsing fails.

    Returns: {conversation_id, platform, channel, sender_name, sender_id, text,
              message_id, account_id}
    """
    event = payload.get("event", "")
    if event != "message.received":
        bm_logger.log("zernio_webhook_non_message", webhook_event=event)
        return None

    # Try nested structures — Zernio may use data.message or data directly
    data = payload.get("data", {})
    if not data:
        data = payload.get("message", {})

    text = data.get("text", "")
    if not text:
        # Try nested message object
        msg_obj = data.get("message", {})
        text = msg_obj.get("text", "") if isinstance(msg_obj, dict) else ""

    conversation_id = data.get("conversationId", "") or data.get("conversation_id", "")
    message_id = data.get("id", "") or data.get("messageId", "")
    # account_id may be in message object or top-level account object
    account_id = data.get("accountId", "") or data.get("account_id", "")
    if not account_id:
        account_obj = payload.get("account", {})
        if isinstance(account_obj, dict):
            account_id = account_obj.get("id", "")

    sender = data.get("sender", {})
    if isinstance(sender, dict):
        sender_name = sender.get("name", "")
        sender_id = sender.get("id", "")
    else:
        sender_name = ""
        sender_id = ""

    platform = str(data.get("platform") or "").strip().lower()
    # Brief 170: normalize provider platform strings before routing. Zernio has
    # reported X as both "x" and "twitter", and provider casing must never divert
    # WhatsApp into the generic DM path.
    if platform == "x":
        platform = "twitter"

    if not conversation_id or not message_id:
        bm_logger.log("zernio_webhook_missing_ids",
                       payload_keys=list(payload.keys()),
                       data_keys=list(data.keys()) if isinstance(data, dict) else [])
        return None

    channel = "whatsapp" if platform == "whatsapp" else (f"{platform}_dm" if platform else "unknown_dm")

    return {
        "conversation_id": conversation_id,
        "platform": platform,
        "channel": channel,
        "sender_name": sender_name,
        "sender_id": sender_id,
        "text": text,
        "message_id": message_id,
        "account_id": account_id,
    }


def parse_zernio_sent_webhook(payload: dict) -> dict | None:
    """Normalize an outgoing Zernio inbox event.

    WhatsApp Coexistence mirrors messages sent from the WhatsApp Business app
    as message.sent with message.source=whatsappbusinessapp. This parser stays
    separate from the inbound parser so outgoing events never enter the AI
    reply path.
    """
    if payload.get("event") != "message.sent":
        return None

    raw_data = payload.get("data")
    raw_data = raw_data if isinstance(raw_data, dict) else {}
    message = payload.get("message")
    if not isinstance(message, dict):
        nested = raw_data.get("message")
        message = nested if isinstance(nested, dict) else raw_data

    conversation = payload.get("conversation")
    if not isinstance(conversation, dict):
        nested = raw_data.get("conversation")
        conversation = nested if isinstance(nested, dict) else {}

    account = payload.get("account")
    if not isinstance(account, dict):
        nested = raw_data.get("account")
        account = nested if isinstance(nested, dict) else {}

    conversation_id = str(
        message.get("conversationId")
        or message.get("conversation_id")
        or conversation.get("id")
        or conversation.get("conversationId")
        or ""
    )
    message_id = str(message.get("id") or message.get("messageId") or "")
    account_id = str(
        message.get("accountId")
        or message.get("account_id")
        or conversation.get("accountId")
        or account.get("id")
        or account.get("accountId")
        or ""
    )
    platform = str(
        message.get("platform")
        or conversation.get("platform")
        or ""
    ).lower()
    source = str(message.get("source") or "").replace("_", "").lower()
    text = str(message.get("text") or message.get("message") or "")

    sender = message.get("sender")
    sender = sender if isinstance(sender, dict) else {}
    sender_name = str(
        sender.get("name")
        or account.get("name")
        or account.get("displayName")
        or "Secretaría"
    )
    sender_id = str(sender.get("id") or "")

    attachments = message.get("attachments")
    if not isinstance(attachments, list):
        attachments = []

    created_at = str(
        message.get("createdAt")
        or message.get("sentAt")
        or payload.get("timestamp")
        or ""
    )

    if not conversation_id or not message_id:
        bm_logger.log(
            "zernio_sent_webhook_missing_ids",
            payload_keys=list(payload.keys()),
            message_keys=list(message.keys()),
        )
        return None

    channel = (
        "whatsapp"
        if platform == "whatsapp"
        else (f"{platform}_dm" if platform else "unknown_dm")
    )
    return {
        "event": "message.sent",
        "conversation_id": conversation_id,
        "platform": platform,
        "channel": channel,
        "sender_name": sender_name,
        "sender_id": sender_id,
        "text": text,
        "message_id": message_id,
        "account_id": account_id,
        "direction": str(message.get("direction") or "outgoing").lower(),
        "source": source,
        "created_at": created_at,
        "attachments": attachments,
    }


class ZernioReplyError(RuntimeError):
    """Provider rejected or did not confirm an operator reply."""


class WhatsAppWindowClosedError(ZernioReplyError):
    """WhatsApp free-text window is closed for this conversation."""


def _response_json(response) -> dict:
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _payload_messages(payload: dict) -> list[dict]:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        messages = payload.get("data", [])
    return [item for item in messages if isinstance(item, dict)] if isinstance(messages, list) else []


def _parse_provider_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _confirmed_text_reply(
    conversation_id: str,
    account_id: str,
    text: str,
    api_key: str,
) -> bool:
    """Send free text only inside WhatsApp's active window and confirm status."""
    base_url = (
        "https://zernio.com/api/v1/inbox/conversations/"
        f"{urllib.parse.quote(conversation_id)}"
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    detail_response = http_requests.get(
        base_url,
        headers=headers,
        params={"accountId": account_id},
        timeout=15,
    )
    if detail_response.status_code == 404:
        return False
    if not 200 <= detail_response.status_code < 300:
        bm_logger.log(
            "zernio_dm_confirmation_detail_failed",
            conversation_id=conversation_id[:20],
            status=detail_response.status_code,
            error=detail_response.text[:200],
        )
        return False

    detail_payload = _response_json(detail_response)
    detail = detail_payload.get("data", detail_payload)
    platform = str(detail.get("platform") or "").lower() if isinstance(detail, dict) else ""

    messages_response = http_requests.get(
        f"{base_url}/messages",
        headers=headers,
        params={"accountId": account_id, "limit": 100, "sortOrder": "desc"},
        timeout=15,
    )
    if not 200 <= messages_response.status_code < 300:
        bm_logger.log(
            "zernio_dm_confirmation_history_failed",
            conversation_id=conversation_id[:20],
            status=messages_response.status_code,
            error=messages_response.text[:200],
        )
        return False

    existing_messages = _payload_messages(_response_json(messages_response))
    if platform == "whatsapp":
        latest_incoming = next(
            (
                _parse_provider_time(item.get("createdAt") or item.get("created_at"))
                for item in existing_messages
                if str(item.get("direction") or "").lower() == "incoming"
            ),
            None,
        )
        if latest_incoming is None or datetime.now(timezone.utc) - latest_incoming > timedelta(hours=24):
            bm_logger.log(
                "zernio_whatsapp_window_closed",
                conversation_id=conversation_id[:20],
                latest_incoming_at=latest_incoming.isoformat() if latest_incoming else "",
            )
            raise WhatsAppWindowClosedError(
                "Han pasado más de 24 horas desde el último mensaje del contacto. "
                "WhatsApp no permite enviar texto libre. El contacto debe escribir "
                "primero o se debe usar una plantilla aprobada."
            )

    send_response = http_requests.post(
        f"{base_url}/messages",
        headers=headers,
        json={"accountId": account_id, "message": text},
        timeout=15,
    )
    send_payload = _response_json(send_response)
    if not 200 <= send_response.status_code < 300:
        detail_message = (
            send_payload.get("message")
            or send_payload.get("error")
            or send_payload.get("detail")
            or send_response.text[:200]
        )
        bm_logger.log(
            "zernio_dm_send_failed",
            conversation_id=conversation_id[:20],
            status=send_response.status_code,
            error=str(detail_message)[:200],
        )
        raise ZernioReplyError(
            "WhatsApp rechazó el mensaje. Inténtalo de nuevo o usa una plantilla aprobada."
        )

    data = send_payload.get("data", send_payload)
    message_id = ""
    if isinstance(data, dict):
        message_id = str(data.get("messageId") or data.get("id") or "")
    terminal_success = {"sent", "delivered", "read"}
    terminal_failure = {"failed", "rejected", "undeliverable"}

    for attempt in range(8):
        if attempt:
            time.sleep(0.5)
        status_response = http_requests.get(
            f"{base_url}/messages",
            headers=headers,
            params={"accountId": account_id, "limit": 20, "sortOrder": "desc"},
            timeout=15,
        )
        if not 200 <= status_response.status_code < 300:
            continue
        candidates = _payload_messages(_response_json(status_response))
        matched = next(
            (
                item for item in candidates
                if (
                    message_id
                    and str(item.get("id") or item.get("messageId") or "") == message_id
                )
                or (
                    not message_id
                    and str(item.get("direction") or "").lower() == "outgoing"
                    and str(item.get("message") or item.get("text") or "") == text
                )
            ),
            None,
        )
        if not matched:
            continue
        status = str(
            matched.get("status") or matched.get("deliveryStatus") or ""
        ).lower()
        if status in terminal_success:
            bm_logger.log(
                "zernio_dm_delivery_confirmed",
                conversation_id=conversation_id[:20],
                status=status,
            )
            return True
        if status in terminal_failure:
            bm_logger.log(
                "zernio_dm_delivery_failed",
                conversation_id=conversation_id[:20],
                status=status,
                error_code=str(matched.get("errorCode") or "")[:80],
                failure_reason=str(matched.get("failureReason") or "")[:200],
            )
            raise ZernioReplyError(
                "WhatsApp marcó el mensaje como fallido. No se ha entregado al contacto."
            )

    bm_logger.log(
        "zernio_dm_delivery_unconfirmed",
        conversation_id=conversation_id[:20],
        message_id=message_id[:20],
    )
    raise ZernioReplyError(
        "Zernio aceptó el mensaje, pero WhatsApp no confirmó el envío. "
        "No se mostrará como enviado."
    )


def send_dm_reply(conversation_id: str, account_id: str, text: str,
                  attachment_url: str = "",
                  attachment_type: str = "image",
                  confirm_delivery: bool = False) -> bool:
    """Send a DM reply; optionally require provider delivery confirmation."""
    if attachment_url:
        return send_dm_reply_with_attachment(
            conversation_id=conversation_id,
            account_id=account_id,
            text=text,
            attachment_url=attachment_url,
            attachment_type=attachment_type,
        )

    api_key = os.environ.get("LATE_API_KEY", "")
    if not api_key:
        bm_logger.log("zernio_dm_no_api_key")
        return False

    if confirm_delivery:
        return _confirmed_text_reply(
            conversation_id=conversation_id,
            account_id=account_id,
            text=text,
            api_key=api_key,
        )

    client = _get_client()
    if not client:
        return False
    try:
        client.inbox.send_inbox_message(
            conversation_id=conversation_id,
            account_id=account_id,
            message=text,
        )
        bm_logger.log("zernio_dm_sent", conversation_id=conversation_id[:20])
        return True
    except Exception as e:
        bm_logger.log("zernio_dm_send_failed", conversation_id=conversation_id[:20],
                       error=str(e)[:200])
        return False

def send_dm_template(
    conversation_id: str,
    account_id: str,
    template_name: str,
    language: str = "es",
) -> bool:
    """Send and confirm an approved WhatsApp template in an existing thread."""
    api_key = os.environ.get("LATE_API_KEY", "")
    if not api_key:
        raise ZernioReplyError("No está configurada la conexión con WhatsApp.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    templates_response = http_requests.get(
        "https://zernio.com/api/v1/whatsapp/templates",
        headers=headers,
        params={"accountId": account_id},
        timeout=15,
    )
    templates_payload = _response_json(templates_response)
    templates = templates_payload.get("templates", [])
    selected = next(
        (
            item for item in templates
            if isinstance(item, dict)
            and item.get("name") == template_name
            and str(item.get("language") or "") == language
        ),
        None,
    )
    template_status = str(selected.get("status") or "").upper() if selected else ""
    if template_status != "APPROVED":
        bm_logger.log(
            "zernio_whatsapp_template_unavailable",
            template_name=template_name,
            status=template_status or "missing",
        )
        if template_status == "PENDING":
            raise ZernioReplyError(
                "La plantilla de seguimiento está pendiente de aprobación de Meta. "
                "Todavía no se puede reabrir esta conversación."
            )
        raise ZernioReplyError(
            "No hay una plantilla de WhatsApp aprobada para reabrir esta conversación."
        )

    base_url = (
        "https://zernio.com/api/v1/inbox/conversations/"
        f"{urllib.parse.quote(conversation_id)}/messages"
    )
    send_response = http_requests.post(
        base_url,
        headers=headers,
        json={
            "accountId": account_id,
            "template": {
                "elements": [{
                    "name": template_name,
                    "language": language,
                }],
            },
        },
        timeout=15,
    )
    payload = _response_json(send_response)
    if not 200 <= send_response.status_code < 300:
        provider_error = (
            payload.get("message")
            or payload.get("error")
            or payload.get("detail")
            or send_response.text[:200]
        )
        bm_logger.log(
            "zernio_whatsapp_template_send_failed",
            template_name=template_name,
            status=send_response.status_code,
            error=str(provider_error)[:200],
        )
        raise ZernioReplyError(
            "WhatsApp rechazó la plantilla de seguimiento. No se ha enviado."
        )

    data = payload.get("data", payload)
    message_id = ""
    if isinstance(data, dict):
        message_id = str(data.get("messageId") or data.get("id") or "")

    for attempt in range(8):
        if attempt:
            time.sleep(0.5)
        status_response = http_requests.get(
            base_url,
            headers=headers,
            params={"accountId": account_id, "limit": 20, "sortOrder": "desc"},
            timeout=15,
        )
        if not 200 <= status_response.status_code < 300:
            continue
        messages = _payload_messages(_response_json(status_response))
        matched = next(
            (
                item for item in messages
                if message_id
                and str(item.get("id") or item.get("messageId") or "") == message_id
            ),
            None,
        )
        if not matched:
            continue
        status = str(
            matched.get("status") or matched.get("deliveryStatus") or ""
        ).lower()
        if status in {"sent", "delivered", "read"}:
            bm_logger.log(
                "zernio_whatsapp_template_confirmed",
                template_name=template_name,
                status=status,
            )
            return True
        if status in {"failed", "rejected", "undeliverable"}:
            bm_logger.log(
                "zernio_whatsapp_template_delivery_failed",
                template_name=template_name,
                status=status,
            )
            raise ZernioReplyError(
                "WhatsApp marcó la plantilla como fallida. No se ha entregado."
            )

    raise ZernioReplyError(
        "WhatsApp no confirmó el envío de la plantilla de seguimiento."
    )


def send_dm_reply_with_attachment(conversation_id: str, account_id: str, text: str,
                                  attachment_url: str,
                                  attachment_type: str = "image",
                                  attachment_name: str = "") -> bool:
    """Send a Zernio inbox message with a public attachment URL.

    The current Python SDK wrapper only exposes text parameters for
    send_inbox_message, so attachment sends use Zernio's documented REST shape.
    """
    api_key = os.environ.get("LATE_API_KEY", "")
    if not api_key:
        bm_logger.log("zernio_dm_no_api_key")
        return False
    if attachment_type not in {"image", "video", "audio", "file"}:
        bm_logger.log("zernio_dm_attachment_invalid_type",
                      attachment_type=attachment_type)
        return False
    url = (
        "https://zernio.com/api/v1/inbox/conversations/"
        f"{urllib.parse.quote(conversation_id)}/messages"
    )
    body = {
        "accountId": account_id,
        "message": text or "",
        "attachmentUrl": attachment_url,
        "attachmentType": attachment_type,
    }
    if attachment_type == "file" and str(attachment_name or "").strip():
        safe_name = os.path.basename(
            str(attachment_name).replace("\x00", "").replace("\r", "").replace("\n", "")
        ).strip()[:160]
        if safe_name:
            body["attachmentName"] = safe_name
    try:
        resp = http_requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=15,
        )
        if 200 <= resp.status_code < 300:
            bm_logger.log("zernio_dm_attachment_sent",
                          conversation_id=conversation_id[:20],
                          attachment_type=attachment_type)
            return True
        bm_logger.log("zernio_dm_attachment_send_failed",
                      conversation_id=conversation_id[:20],
                      status=resp.status_code,
                      error=resp.text[:200])
        return False
    except Exception as e:
        bm_logger.log("zernio_dm_attachment_send_failed",
                      conversation_id=conversation_id[:20],
                      error=str(e)[:200])
        return False


def send_typing_indicator(conversation_id: str, account_id: str):
    """Send typing indicator via Zernio. Best-effort, no error on failure."""
    client = _get_client()
    if not client:
        return
    try:
        client.messages.send_typing_indicator(
            conversation_id=conversation_id,
            account_id=account_id,
        )
    except Exception:
        pass  # Typing indicator is cosmetic — never block on failure
