# bluemarlin/agents/social/social_agent.py
# Created: Brief 068
# Last modified: Brief 069
# Purpose: WhatsApp agent — calls marina_agent with channel="whatsapp"

from shared import state_registry
from shared import bm_logger
from agents.marina import marina_agent


def handle_incoming_whatsapp_message(message: dict) -> str:
    """
    Process a WhatsApp message: fetch state + history, call marina_agent,
    merge + persist state, return reply.
    Returns reply string or empty string on failure.
    """
    phone = message.get("from", "")
    text = message.get("text", "")
    from_name = message.get("from_name", "")

    # Get existing booking state
    state = state_registry.wa_get_booking_state(phone)
    fields = state.get("fields", {})
    flags = state.get("flags", {})

    # Get conversation history (last 10 messages, 24h window)
    history = state_registry.wa_get_history(phone, limit=10)

    # Build from identifier with name if available
    from_id = f"{phone} ({from_name})" if from_name else phone

    # Call marina_agent with channel="whatsapp"
    result = marina_agent.process_message(
        from_email=from_id,
        subject="",
        body=text,
        thread_fields=fields,
        thread_flags=flags,
        action_context="",
        channel="whatsapp",
        messages=history,
    )

    reply = result.get("reply", "")

    if reply:
        # Strip booking placeholders (orchestrator not active until Brief 070)
        reply = reply.replace("[BOOKING_REF]", "").replace("[PAYMENT_LINK]", "")

        # Merge fields — overwrite when Claude returns non-empty values
        new_fields = result.get("fields", {}) or {}
        for k, v in new_fields.items():
            if v is not None and v != "":
                fields[k] = v
            elif v == "" and k in fields:
                del fields[k]

        # Merge flags
        new_flags = result.get("flags", {}) or {}
        flags.update(new_flags)

        # Persist state
        state_registry.wa_save_booking_state(phone, fields, flags)

        # Log
        bm_logger.log("whatsapp_agent_reply",
            phone=phone,
            intents=result.get("intents", []),
            reply_length=len(reply))

    return reply
