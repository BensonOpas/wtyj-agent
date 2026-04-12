# wtyj/agents/social/channels/base.py
# Brief 186 — Channel adapter base class.
from abc import ABC, abstractmethod


class Channel(ABC):
    """Base class for channel adapters.

    A channel adapter knows how to convert a parsed Zernio webhook message
    (output of parse_zernio_webhook in zernio_dm_client.py) into the dict
    shape that handle_incoming_whatsapp_message consumes.
    """

    @classmethod
    @abstractmethod
    def from_zernio(cls, zernio_msg: dict) -> dict:
        """Convert a parse_zernio_webhook output dict into a message dict
        suitable for handle_incoming_whatsapp_message.

        Args:
            zernio_msg: dict with keys conversation_id, platform, channel,
                        sender_name, sender_id, text, message_id, account_id

        Returns:
            dict with keys: from, text, from_name, channel, message_id.
            WhatsApp via Zernio also includes: _zernio_conversation_id,
            _zernio_account_id, _zernio_channel, _zernio_sender_name (needed
            for the debounce buffer round-trip in _flush_buffer).
        """
