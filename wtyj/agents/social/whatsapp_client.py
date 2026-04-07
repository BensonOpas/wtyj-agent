# bluemarlin/agents/social/whatsapp_client.py
# Created: Brief 068
# Last modified: Brief 068
# Purpose: Parse inbound WhatsApp payloads + send outbound replies via Cloud API

import json
import os
import urllib.request

from shared.bm_logger import log

_API_VERSION = "v22.0"


# Brief 154 — read env vars at call time, not at import time. Same lazy pattern
# Brief 147 used for gws_calendar.py to fix the test_068 import-order bug.
def _access_token() -> str:
    return os.environ.get("WHATSAPP_ACCESS_TOKEN", "")


def _phone_number_id() -> str:
    return os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")


def parse_webhook_payload(payload: dict) -> list:
    """
    Extract normalized message objects from a Meta webhook payload.
    Returns a list of dicts. Skips status updates and non-message events.
    Non-text messages are included with text=None.
    """
    messages = []
    try:
        for entry in payload.get("entry", []):
            business_account_id = entry.get("id", "")
            for change in entry.get("changes", []):
                value = change.get("value", {})
                # Skip status updates (delivered, read, etc.)
                if "statuses" in value and "messages" not in value:
                    log("webhook_status_update", source="meta_whatsapp",
                        statuses=value.get("statuses"))
                    continue
                metadata = value.get("metadata", {})
                phone_number_id = metadata.get("phone_number_id", "")
                contacts = {c.get("wa_id", ""): c.get("profile", {}).get("name", "")
                            for c in value.get("contacts", [])}
                for msg in value.get("messages", []):
                    sender = msg.get("from", "")
                    normalized = {
                        "channel": "whatsapp",
                        "from": sender,
                        "from_name": contacts.get(sender, ""),
                        "message_id": msg.get("id", ""),
                        "text": msg.get("text", {}).get("body") if msg.get("type") == "text" else None,
                        "message_type": msg.get("type", "unknown"),
                        "timestamp": msg.get("timestamp", ""),
                        "business_account_id": business_account_id,
                        "phone_number_id": phone_number_id,
                    }
                    messages.append(normalized)
    except Exception as e:
        log("webhook_parse_error", source="meta_whatsapp", error=str(e))
    return messages


def send_text_message(to: str, text: str) -> bool:
    """Send a text message via WhatsApp Cloud API. Returns True on success."""
    url = f"https://graph.facebook.com/{_API_VERSION}/{_phone_number_id()}/messages"
    headers = {
        "Authorization": f"Bearer {_access_token()}",
        "Content-Type": "application/json",
    }
    body = json.dumps({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_body = resp.read().decode()
            log("whatsapp_send_ok", to=to, response=resp_body)
            return True
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        log("whatsapp_send_failed", to=to, status=e.code, error=error_body)
        return False
    except Exception as e:
        log("whatsapp_send_failed", to=to, error=str(e))
        return False


def _is_zernio_conversation_id(s: str) -> bool:
    """Zernio conversation IDs are 24-char lowercase hex strings.
    Meta phone numbers are E.164 or all-digit (10-15 chars).
    The two formats don't overlap. Brief 159."""
    if len(s) != 24:
        return False
    try:
        int(s, 16)
        return True
    except ValueError:
        return False


def send_whatsapp_message(customer_id: str, text: str) -> bool:
    """Send a WhatsApp text via Zernio Inbox API (preferred, Brief 143)
    if customer_id is a Zernio conversation_id, otherwise fall back to the
    legacy Meta Cloud API. Returns True on success.

    Brief 159: introduced to fix relay reply paths that previously used
    the legacy Meta API for ALL customers, silently failing for Zernio
    customers (everyone in production)."""
    if _is_zernio_conversation_id(customer_id):
        # Deferred imports to avoid circular dependency with social_publisher
        from agents.social.zernio_dm_client import send_dm_reply
        from agents.social import social_publisher
        account_id = social_publisher.get_account_id("whatsapp")
        if not account_id:
            log("zernio_send_no_account", conversation_id=customer_id[:20])
            return False
        return send_dm_reply(customer_id, account_id, text)
    return send_text_message(to=customer_id, text=text)
