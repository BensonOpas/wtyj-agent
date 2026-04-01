# bluemarlin/agents/social/zernio_dm_client.py
# Created: Brief 130
# Purpose: Parse Zernio webhook payloads + send DM replies via Zernio Inbox API

import hashlib
import hmac
import os

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

    if not conversation_id or not message_id:
        bm_logger.log("zernio_webhook_missing_ids",
                       payload_keys=list(payload.keys()),
                       data_keys=list(data.keys()) if isinstance(data, dict) else [])
        return None

    channel = f"{platform}_dm" if platform else "unknown_dm"

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


def send_dm_reply(conversation_id: str, account_id: str, text: str) -> bool:
    """Send a DM reply via Zernio Inbox API. Returns True on success."""
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
