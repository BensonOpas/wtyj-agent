# wtyj/agents/social/senders/base.py
# Brief 187 — Sender adapter base class.
from abc import ABC, abstractmethod


class Sender(ABC):
    """Base class for outbound message sender adapters.

    A sender knows how to deliver a reply text to a customer conversation
    on a specific channel. The dispatcher (send_reply in __init__.py) picks
    a sender by channel name and delegates to its send() classmethod.
    """

    @classmethod
    @abstractmethod
    def send(cls, conversation_id: str, account_id: str, text: str,
             attachment_url: str = "", attachment_type: str = "image") -> bool:
        """Send a reply to the given conversation.

        Args:
            conversation_id: the platform's conversation identifier
                (Zernio conversation hex string for IG/FB/X DMs and Zernio
                WhatsApp; phone number for Meta WhatsApp direct).
            account_id: the connected social account identifier (required
                for Zernio so it knows which account is sending; may be
                ignored by senders that don't need it).
            text: the reply text to deliver.
            attachment_url: optional public media URL to send with the reply.
            attachment_type: provider attachment type, defaults to image.

        Returns:
            True on successful send, False otherwise. Errors are logged by
            the underlying transport, not raised.
        """
