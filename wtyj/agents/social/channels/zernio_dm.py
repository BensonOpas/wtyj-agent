# wtyj/agents/social/channels/zernio_dm.py
# Brief 186 — Generic adapter for Zernio DM channels (Instagram, Facebook,
# X/Twitter, and any future Zernio-routed DM platforms). DM channels do NOT
# include _zernio_* metadata because they are not buffered/debounced — the
# message is dispatched directly to handle_incoming_whatsapp_message inside
# the original _process_zernio_event function scope.
from .base import Channel


class ZernioDMChannel(Channel):
    """Generic adapter for Zernio DM channels (IG, FB, X/Twitter, etc.)."""

    @classmethod
    def from_zernio(cls, zernio_msg: dict) -> dict:
        return {
            "from": zernio_msg["conversation_id"],
            "text": zernio_msg.get("text", ""),
            "from_name": zernio_msg.get("sender_name", ""),
            "channel": zernio_msg["channel"],
            "message_id": zernio_msg["message_id"],
        }
