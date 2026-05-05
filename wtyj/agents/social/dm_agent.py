# bluemarlin/agents/social/dm_agent.py
# Created: Brief 131
# Last modified: Brief 131b
# Purpose: DM Q&A agent — own Claude call, no booking flow, redirects to WhatsApp/email

import os
import re
import time
from datetime import datetime, timezone

import anthropic
from shared import state_registry, config_loader, bm_logger

_MAX_REPLIES_PER_HOUR = 30
_REPLY_WINDOW_SECONDS = 3600


def _build_dm_system_prompt(channel: str) -> str:
    """Build a Q&A-focused system prompt for DM channels. No booking logic.
    Brief 203: when client.json's agent_persona.freeform_notes is set, the
    master prompt block replaces the hardcoded WRITING STYLE / AVOID blocks.
    The structural pieces (services, FAQ, booking redirect, language) stay in
    both modes."""
    business = config_loader.get_business()
    csk = config_loader.get_common_sense_knowledge()
    trips = config_loader.get_services()
    faq = config_loader.get_faq()
    # Brief 203: agent_persona pulled from raw client.json (config_loader has no
    # dedicated getter today — get_raw is the consistent escape hatch used elsewhere).
    persona = config_loader.get_raw().get("agent_persona", {})
    master_prompt = (persona.get("freeform_notes") or "").strip()

    agent_name = business.get("agent_name", "CSA")
    company_name = business.get("name", "the business")
    wa_number = business.get("whatsapp", "")
    wa_link = wa_number.replace("+", "").replace(" ", "")
    booking_email = business.get("booking_email", business.get("email", ""))
    languages = ", ".join(business.get("languages", ["English"]))
    terminology = config_loader.get_raw().get("terminology", {})
    service_label = terminology.get("service_label", "service")

    platform_name = "Instagram" if channel == "instagram_dm" else "Facebook"

    # Build service list
    service_lines = []
    for key, data in trips.items():
        name = data.get("display_name", key)
        price = data.get("price_pp", "")
        days = data.get("days_available", "")
        desc = data.get("description", "")[:100]
        line = f"- {name}"
        if price:
            line += f" (${price}/person)"
        if days:
            line += f" — {days}"
        if desc:
            line += f" — {desc}"
        service_lines.append(line)

    # Build FAQ
    faq_lines = []
    for q, a in faq.items():
        faq_lines.append(f"Q: {q.replace('_', ' ').title()}\nA: {a}")

    # Common structural blocks (data injection, not voice).
    # Empty services/faq lists render as bare "SERVICES:\n" / "FAQ:\n" — same as
    # existing behavior (chr(10).join on an empty list = ""). No empty-state change.
    intro = f"You are {agent_name}, answering {platform_name} DMs for {company_name}."
    qa_role_short = f"You are a Q&A helper. You answer questions about {service_label}s, pricing, availability, and general info."
    qa_role_full = qa_role_short + " You are friendly, casual, and human."
    services_block = f"{service_label.upper()}S:\n{chr(10).join(service_lines)}"
    faq_block = f"FAQ:\n{chr(10).join(faq_lines)}"
    booking_redirect_block = f"""BOOKING REDIRECT — CRITICAL:
You CANNOT process {service_label} bookings in DMs. When someone wants to book, asks about availability for a specific date, or provides booking details (date, guests, time):
- Do NOT ask for their date, number of guests, time, name, or any booking details
- Do NOT confirm any booking or mention booking references
- Redirect them: "For bookings, message us on WhatsApp at wa.me/{wa_link} or email {booking_email} — we handle all bookings there!"
- You may answer a general question about the service first, then redirect
- If they insist on booking here, repeat the redirect once more. Do not cave."""
    language_block = f"LANGUAGE: Reply in the same language the customer writes in. Supported: {languages}. Default to English if unclear."
    emoji_block = "Emojis: sparingly, only if the customer used them first."
    output_rule = "Reply with ONLY your message text. No JSON. No code fences. No metadata. Just the reply."

    if master_prompt:
        # Brief 203: master prompt mode. Drop the "friendly, casual, and human"
        # tone tail (qa_role_short, not qa_role_full) so master prompt's own
        # Tone block is sole tone source. Inject master prompt as standalone
        # paragraph (no wrapper — it has its own internal section headers).
        return (
            intro + "\n\n"
            + qa_role_short + "\n\n"
            + master_prompt + "\n\n"
            + services_block + "\n\n"
            + faq_block + "\n\n"
            + booking_redirect_block + "\n\n"
            + language_block + "\n\n"
            + emoji_block + "\n\n"
            + output_rule
        )

    # Fallback: no master prompt set — use hardcoded WRITING STYLE / AVOID blocks.
    # Byte-equivalent backward-compat path.
    writing_style_block = f"""WRITING STYLE:
- Short replies. Under 60 words for simple questions, under 100 for detailed ones.
- Sound like a real person texting from work. Not a chatbot.
- Use line breaks between thoughts. No walls of text.
- No sign-offs, no signatures, no "Hope that helps!"
- Use contractions. Match the sender's energy.
- Greet ONLY on the very first message. If CONVERSATION HISTORY shows you already replied, skip the greeting entirely.
- When listing {service_label}s, give names and brief descriptions. Only include prices if asked."""
    avoid_block = "AVOID: em dashes, \"Shall I\", \"I'd be happy to\", \"Great choice\", \"Nice choice\", \"Amazing\", \"Absolutely\", \"certainly\", \"wonderful\", \"fantastic\", forced enthusiasm, reasoning out loud."

    return (
        intro + "\n\n"
        + qa_role_full + "\n\n"
        + services_block + "\n\n"
        + faq_block + "\n\n"
        + writing_style_block + "\n\n"
        + booking_redirect_block + "\n\n"
        + language_block + "\n\n"
        + avoid_block + "\n\n"
        + emoji_block + "\n\n"
        + output_rule
    )


def _build_dm_user_prompt(text: str, sender_name: str, messages: list) -> str:
    """Build the user prompt with conversation history and inbound message."""
    today = datetime.now(timezone(offset=__import__('datetime').timedelta(hours=-4))).strftime("%Y-%m-%d")
    business = config_loader.get_business()

    history_section = ""
    if messages:
        history_lines = []
        for m in messages:
            role_label = "Customer" if m.get("role") == "user" else business.get("agent_name", "CSA")
            history_lines.append(f"  {role_label}: {m.get('text', '')}")
        history_section = (
            "CONVERSATION HISTORY (recent messages):\n"
            + "\n".join(history_lines) + "\n\n"
        )
    else:
        history_section = "CONVERSATION HISTORY:\n  (new conversation)\n\n"

    return f"""TODAY: {today}

{history_section}INBOUND DM:
  From: {sender_name or 'Unknown'}
  Message: {text}"""


def handle_incoming_dm(message: dict) -> str:
    """Process an incoming IG/FB DM. Own Claude call, Q&A only.

    Args:
        message: normalized dict with keys:
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
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            bm_logger.log("dm_no_api_key", conversation_id=conversation_id[:20])
            return _DM_FALLBACK

        client = anthropic.Anthropic(api_key=api_key)
        system_prompt = _build_dm_system_prompt(channel)
        user_prompt = _build_dm_user_prompt(text, sender_name, messages)

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        reply = response.content[0].text.strip()

        # Log token usage
        _usage = getattr(response, "usage", None)
        if _usage:
            bm_logger.log("dm_api_usage",
                          input_tokens=_usage.input_tokens,
                          output_tokens=_usage.output_tokens,
                          channel=channel)

        # Safety net: strip unreplaced booking placeholders
        reply = reply.replace("[BOOKING_REF]", "").replace("[PAYMENT_LINK]", "")
        # Brief 201: strip em-dashes (Claude ignores brand_voice_rules on this).
        # Em-dash only — en-dashes and hyphens left alone.
        reply = reply.replace("—", ",")
        # Strip markdown code fences if present
        reply = re.sub(r"^```(?:json)?\s*", "", reply)
        reply = re.sub(r"\s*```$", "", reply.strip())
        # Clean up double spaces left by stripped placeholders
        while "  " in reply:
            reply = reply.replace("  ", " ")
        reply = reply.strip()

        if not reply:
            bm_logger.log("dm_empty_reply", conversation_id=conversation_id[:20],
                           channel=channel)
            return ""

        bm_logger.log("dm_reply_generated", conversation_id=conversation_id[:20],
                       channel=channel)
        return reply

    except Exception as e:
        bm_logger.log("dm_agent_error", conversation_id=conversation_id[:20],
                       channel=channel, error=str(e)[:200])
        # ⚠️  HARDCODED FALLBACK — Rule 3 accepted exception (API failure path only)
        return _DM_FALLBACK


# ⚠️  HARDCODED FALLBACK — Rule 3 accepted exception (API failure path only)
# If agent name changes from Marina, update this message.
_DM_FALLBACK = "Sorry, could you send that again? I missed it."


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
