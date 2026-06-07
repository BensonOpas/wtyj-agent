# bluemarlin/agents/social/zernio_dm_client.py
# Created: Brief 130
# Purpose: Parse Zernio webhook payloads + send DM replies via Zernio Inbox API

import hashlib
import hmac
import os
import urllib.parse

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

    platform = data.get("platform", "")
    # Brief 170: normalize platform strings. Zernio's X / Twitter platform value
    # has been reported as both "x" and "twitter" in different docs — map both
    # to "twitter" internally so downstream routing and channel strings are stable.
    if platform in ("x", "X"):
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


def send_dm_reply(conversation_id: str, account_id: str, text: str,
                  attachment_url: str = "",
                  attachment_type: str = "image") -> bool:
    """Send a DM reply via Zernio Inbox API. Returns True on success."""
    if attachment_url:
        return send_dm_reply_with_attachment(
            conversation_id=conversation_id,
            account_id=account_id,
            text=text,
            attachment_url=attachment_url,
            attachment_type=attachment_type,
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


def send_dm_reply_with_attachment(conversation_id: str, account_id: str, text: str,
                                  attachment_url: str,
                                  attachment_type: str = "image") -> bool:
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
