# bluemarlin/agents/social/social_agent.py
# Created: Brief 068
# Last modified: Brief 068
# Purpose: Social agent stub — will be replaced with Claude-powered Q&A

from shared.bm_logger import log


def handle_incoming_whatsapp_message(message: dict) -> str:
    """
    Process a normalized WhatsApp message and return a reply string.
    Stub: returns hardcoded test reply. Will be replaced with Claude Q&A.
    """
    log("agent_stub_called", channel="whatsapp",
        message_from=message.get("from", ""),
        message_text=message.get("text", ""))
    return "Thanks for your message! BlueMarlin test agent is online. 🚀"
