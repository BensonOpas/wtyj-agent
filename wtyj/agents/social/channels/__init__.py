# wtyj/agents/social/channels/__init__.py
# Brief 186 — Channel adapter registry.
from .base import Channel
from .whatsapp_zernio import WhatsAppZernioChannel
from .zernio_dm import ZernioDMChannel

# Maps the "channel" field from parse_zernio_webhook output to an adapter
# class. Channel names match what zernio_dm_client.py:85 produces:
#   - "whatsapp" for platform="whatsapp"
#   - "{platform}_dm" for any other platform (e.g. "instagram_dm")
ZERNIO_CHANNELS = {
    "whatsapp": WhatsAppZernioChannel,
    "instagram_dm": ZernioDMChannel,
    "facebook_dm": ZernioDMChannel,
    "twitter_dm": ZernioDMChannel,
}

# Default adapter for unknown channels (e.g. a new Zernio platform we haven't
# explicitly registered). Falls back to the generic DM adapter so the system
# does not crash on unfamiliar inbound messages.
DEFAULT_ZERNIO_CHANNEL = ZernioDMChannel

__all__ = [
    "Channel",
    "WhatsAppZernioChannel",
    "ZernioDMChannel",
    "ZERNIO_CHANNELS",
    "DEFAULT_ZERNIO_CHANNEL",
]
