# bluemarlin/agents/social/dm_agent.py
# Created: Brief 131
# Purpose: DM conversation handler — routes IG/FB DMs through Marina for Q&A, redirects bookings

import time
from datetime import datetime, timezone
from shared import state_registry
from shared import bm_logger
from agents.marina import marina_agent

_MAX_REPLIES_PER_HOUR = 30
_REPLY_WINDOW_SECONDS = 3600


def handle_incoming_dm(message: dict) -> str:
    """Process an incoming IG/FB DM through Marina. Q&A only, no booking flow.

    Args:
        message: normalized dict from parse_zernio_webhook with keys:
            conversation_id, platform, channel, sender_name, text, account_id

    Returns: reply text, or empty string if rate limited or error.
    """
    conversation_id = message["conversation_id"]
    channel = message["channel"]
    sender_name = message.get("sender_name", "")
    text = message["text"]

    # Rate limiting per conversation
    if _is_rate_limited(conversation_id, channel):
        bm_logger.log("dm_rate_limited", conversation_id=conversation_id[:20],
                       channel=channel)
        return ""

    # Get conversation history
    history = state_registry.dm_get_history(conversation_id, channel, limit=10)
    messages = [{"role": m["role"], "text": m["text"]} for m in history]

    try:
        result = marina_agent.process_message(
            from_email=conversation_id,
            subject="",
            body=text,
            thread_fields={"customer_name": sender_name} if sender_name else {},
            thread_flags={},
            action_context="",
            channel=channel,
            messages=messages,
        )

        reply = result.get("reply", "")
        if not reply:
            bm_logger.log("dm_empty_reply", conversation_id=conversation_id[:20],
                           channel=channel)
            return ""

        bm_logger.log("dm_reply_generated", conversation_id=conversation_id[:20],
                       channel=channel, intents=result.get("intents", []))
        return reply

    except Exception as e:
        bm_logger.log("dm_agent_error", conversation_id=conversation_id[:20],
                       channel=channel, error=str(e)[:200])
        return ""


def _is_rate_limited(conversation_id: str, channel: str) -> bool:
    """Check if conversation has exceeded reply rate limit."""
    history = state_registry.dm_get_history(conversation_id, channel, limit=50)
    now = time.time()
    cutoff = now - _REPLY_WINDOW_SECONDS
    recent_replies = 0
    for msg in history:
        if msg["role"] == "assistant":
            try:
                msg_time = datetime.fromisoformat(msg["created_at"]).timestamp()
                if msg_time > cutoff:
                    recent_replies += 1
            except (ValueError, KeyError):
                pass
    return recent_replies >= _MAX_REPLIES_PER_HOUR
