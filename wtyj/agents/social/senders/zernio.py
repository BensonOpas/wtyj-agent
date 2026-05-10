# wtyj/agents/social/senders/zernio.py
# Brief 187 — Sender adapter wrapping zernio_dm_client.send_dm_reply.
# All Zernio-routed channels (WhatsApp via Zernio, Instagram DM, Facebook DM,
# X/Twitter DM) use the same Zernio Inbox API endpoint, so a single class
# covers all four registry entries.
from .base import Sender
from agents.social.zernio_dm_client import send_dm_reply


class ZernioSender(Sender):
    """Sends replies via Zernio's Inbox API (covers all Zernio-routed channels)."""

    @classmethod
    def send(cls, conversation_id: str, account_id: str, text: str) -> bool:
        # Brief 238 — tenant isolation: refuse outbound sends to accounts
        # not allowlisted in this tenant's client.json. Strict mode blocks
        # the call entirely; permissive mode logs and proceeds.
        from shared.tenant_guard import is_account_allowed
        if not is_account_allowed(account_id, direction="outbound"):
            return False
        return send_dm_reply(conversation_id, account_id, text)
