# wtyj/agents/social/channels/whatsapp_zernio.py
# Brief 186 — Adapter for WhatsApp messages routed through Zernio.
# Includes _zernio_* metadata required for the debounce buffer round-trip.
from .base import Channel


class WhatsAppZernioChannel(Channel):
    """WhatsApp messages received via Zernio webhook.

    The output dict includes _zernio_* metadata because the message goes
    through the debounce buffer (_buffer_message → _flush_buffer) and the
    metadata is needed when the buffered message is later passed back to
    handle_incoming_whatsapp_message inside _flush_buffer's separate scope.
    """

    @classmethod
    def from_zernio(cls, zernio_msg: dict) -> dict:
        sender_name = zernio_msg.get("sender_name", "")
        conversation_id = zernio_msg["conversation_id"]
        return {
            "from": conversation_id,
            "text": zernio_msg.get("text", ""),
            "from_name": sender_name,
            "message_id": zernio_msg["message_id"],
            "channel": zernio_msg["channel"],
            "_zernio_conversation_id": conversation_id,
            "_zernio_account_id": zernio_msg["account_id"],
            "_zernio_channel": zernio_msg["channel"],
            "_zernio_sender_name": sender_name,
            "_zernio_sender_id": str(zernio_msg.get("sender_id") or "").strip(),
            "_zernio_interactive_type": str(
                zernio_msg.get("interactive_type") or ""
            ).strip(),
            "_zernio_interactive_id": str(
                zernio_msg.get("interactive_id") or ""
            ).strip(),
            "_zernio_attachments": [
                dict(item)
                for item in zernio_msg.get("attachments") or []
                if isinstance(item, dict)
            ],
            "_zernio_event_id": str(
                zernio_msg.get("event_id") or zernio_msg.get("message_id") or ""
            ).strip(),
            "_zernio_provider_message_id": str(
                zernio_msg.get("provider_message_id") or ""
            ).strip(),
            "_zernio_sent_at": str(
                zernio_msg.get("sent_at") or ""
            ).strip(),
        }
