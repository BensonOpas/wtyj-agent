# bluemarlin/agents/social/dm_agent.py
# Created: Brief 131
# Last modified: Brief 131b
# Purpose: DM Q&A agent — own Claude call, no booking flow, redirects to WhatsApp/email

import os
import re
import time
from datetime import datetime, timezone

import anthropic
from shared import state_registry, config_loader, bm_logger, auto_block, agent_identity

_MAX_REPLIES_PER_HOUR = 30
_REPLY_WINDOW_SECONDS = 3600


class HandoffPersistenceError(RuntimeError):
    """A customer handoff promise must not outlive its operator work item."""


_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\u2600-\u27BF"
    "\u200D\uFE0F"
    "]"
)


def _apply_reply_style_guards(reply: str, inbound_text: str) -> str:
    """Apply optional tenant-authored style constraints after generation."""
    persona = config_loader.get_raw().get("agent_persona", {}) or {}
    cleaned = reply

    for opener in persona.get("forbidden_reply_openers", []) or []:
        opener_text = str(opener or "").strip()
        if opener_text and cleaned.lower().startswith(opener_text.lower()):
            cleaned = cleaned[len(opener_text):].lstrip()
            break

    if persona.get("enforce_emoji_mirroring") and not _EMOJI_RE.search(
        inbound_text or ""
    ):
        cleaned = _EMOJI_RE.sub("", cleaned)
        cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()


def _build_dm_approved_answers_block(channel: str) -> str:
    """Brief 234: mirror of marina_agent._build_approved_answers_block for
    the IG/FB DM path. Returns an APPROVED ANSWERS prompt block listing
    recent operator-curated learnings for this channel, or '' when the
    tenant hasn't opted in or no learnings match.

    Returned without a leading '\n\n' because the caller joins parts
    with '\n\n'.join(...) — the joiner handles spacing. Tenant opt-in
    via client.json::features.approved_learnings_in_prompt (default
    false). Channel filter is exact-string match so Instagram and
    Facebook learning pools stay isolated."""
    features = config_loader.get_raw().get("features", {}) or {}
    if not features.get("approved_learnings_in_prompt"):
        return ""
    try:
        rows = state_registry.get_approved_learnings_for_prompt(channel, limit=20)
    except Exception:
        return ""
    if not rows:
        return ""
    pairs = []
    for r in rows:
        q = (r.get("question") or "").strip()
        a = (r.get("answer") or "").strip()
        if not a:
            continue
        if q:
            pairs.append(f"Q: {q}\nA: {a}")
        else:
            pairs.append(f"A: {a}")
    if not pairs:
        return ""
    return (
        "APPROVED ANSWERS (operator-curated knowledge):\n"
        "The team has previously answered similar customer questions on this "
        "channel. Use these as authoritative context, they reflect how the "
        "human team wants you to handle these situations going forward. Match "
        "the spirit; do not copy verbatim if the customer phrasing differs.\n\n"
        + "\n\n".join(pairs)
    )


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
    final_override = (persona.get("reservation_demo_override") or "").strip()
    if final_override:
        master_prompt = "\n\n".join(part for part in (master_prompt, final_override) if part)
    enforcement_notes = (persona.get("enforcement_notes") or "").strip()
    # Brief 206: booking_flow gate so the BOOKING REDIRECT block doesn't inject
    # for non-booking tenants (unboks etc.) where it would render a recursive
    # wa.me/<same-number-the-customer-is-on> redirect.
    booking_flow = config_loader.get_raw().get("features", {}).get("booking_flow", True)

    try:
        from shared import icp_overrides
        override_envelope = icp_overrides.fetch_overrides()
    except Exception:
        override_envelope = None
    agent_name = (
        agent_identity.override_agent_name(override_envelope)
        or agent_identity.clean_agent_name(business.get("agent_name"))
        or agent_identity.DEFAULT_AGENT_NAME
    )
    company_name = business.get("name", "the business")
    wa_number = business.get("whatsapp", "")
    wa_link = wa_number.replace("+", "").replace(" ", "")
    booking_email = business.get("booking_email", business.get("email", ""))
    languages = ", ".join(business.get("languages", ["English"]))
    terminology = config_loader.get_raw().get("terminology", {})
    service_label = terminology.get("service_label", "service")

    # Brief 327: this Q&A agent serves every configured short-form channel.
    # Keep the channel context explicit so WhatsApp and X/Twitter prompts are
    # never mislabeled as Facebook DMs. This is presentation context only; it
    # does not classify user text or change dispatch behavior.
    channel_label = {
        "whatsapp": "WhatsApp messages",
        "instagram_dm": "Instagram DMs",
        "facebook_dm": "Facebook DMs",
        "twitter_dm": "X/Twitter DMs",
    }.get(str(channel or "").strip().lower(), "messages on this channel")

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
    intro = (
        f"You are {agent_name}, answering {channel_label} for {company_name}.\n"
        f"Your customer-facing name is {agent_name}. Use this name only when natural. "
        "Do not overuse it, do not claim to be human, and do not imply any professional license or authority.\n"
        f"{agent_identity.agent_name_authority_rule(agent_name)}"
    )
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

    # Brief 234: optional APPROVED ANSWERS block (gated on
    # features.approved_learnings_in_prompt). Computed once, used by
    # both the master_prompt branch and the fallback branch below.
    approved_answers_block = _build_dm_approved_answers_block(channel)

    if master_prompt:
        # Brief 203: master prompt mode. Drop the "friendly, casual, and human"
        # tone tail (qa_role_short, not qa_role_full) so master prompt's own
        # Tone block is sole tone source. Inject master prompt as standalone
        # paragraph (no wrapper — it has its own internal section headers).
        # Brief 206: only include BOOKING REDIRECT block when booking_flow is
        # true. Non-booking tenants don't have bookings to redirect to.
        parts = [intro, qa_role_short, master_prompt]
        if approved_answers_block:
            parts.append(approved_answers_block)
        parts.extend([services_block, faq_block])
        if booking_flow:
            parts.append(booking_redirect_block)
        parts.extend([language_block, emoji_block])
        if enforcement_notes:
            parts.append(enforcement_notes)
        parts.append(output_rule)
        return "\n\n".join(parts)

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

    fallback_parts = [intro, qa_role_full]
    if approved_answers_block:
        fallback_parts.append(approved_answers_block)
    fallback_parts.extend([
        services_block, faq_block, writing_style_block,
    ])
    if booking_flow:
        fallback_parts.append(booking_redirect_block)
    fallback_parts.extend([
        language_block, avoid_block, emoji_block, output_rule,
    ])
    return "\n\n".join(fallback_parts)


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


def _handoff_reply(message: dict, reply: str, *, defer_handoff: bool):
    business = config_loader.get_business()
    agent = business.get("agent_name", "CSA")
    notification = {
        "notification_type": "escalation",
        "channel": message["channel"],
        "customer_id": message["conversation_id"],
        "customer_name": message.get("sender_name") or "Unknown contact",
        "subject": f"{agent} escalated a {message['channel']} conversation",
        "body": (
            f"Customer message:\n{message.get('text') or '[Attachment received]'}\n\n"
            f"{agent}'s reply:\n{reply}\n\n"
            f"({business.get('name', 'the business')} — auto-escalated by {agent} "
            "based on conversation context.)"
        ),
        "mode": "soft",
    }
    if defer_handoff:
        # The durable webhook owns the authoritative account/processing-token
        # fence and commits this intent before making a customer promise.
        return {"text": reply, "handoff_notification": notification}
    try:
        state_registry.create_pending_notification(**notification)
    except Exception as exc:
        raise HandoffPersistenceError("handoff persistence unavailable") from exc
    return reply


def handle_incoming_dm(message: dict, *, defer_handoff: bool = False) -> str | dict:
    """Process an incoming IG/FB DM. Own Claude call, Q&A only.

    Args:
        message: normalized dict with keys:
            conversation_id, platform, channel, sender_name, text, account_id

    Returns: reply text, or a text/handoff intent when deferral is requested.
    Handoff persistence failures propagate instead of silently promising a
    notification that was never saved.
    """
    conversation_id = message["conversation_id"]
    channel = message["channel"]
    sender_name = message.get("sender_name", "")
    text = message["text"]

    ignored = state_registry.match_ignored_contact(
        channel=channel,
        sender_id=conversation_id,
    )
    if isinstance(ignored, dict) and ignored:
        state_registry.record_ignored_contact_event(
            contact_id=ignored.get("id"),
            channel=channel,
            sender_identifier=conversation_id,
        )
        bm_logger.log("ignored_contact_inbound_suppressed",
                      channel=channel,
                      sender=conversation_id[:50],
                      reason="Ignored inbound message because sender is on Excluded Contacts / Ignore List.")
        return ""

    moderation = auto_block.evaluate_inbound(
        channel=channel,
        user_identifier=conversation_id,
        text=text,
        customer_name=sender_name,
    )
    if moderation.get("action") == "blocked":
        bm_logger.log("dm_auto_blocked", conversation_id=conversation_id[:50],
                      category=moderation.get("category"), channel=channel)
        return ""
    if moderation.get("action") == "warn":
        bm_logger.log("dm_auto_block_warning", conversation_id=conversation_id[:50],
                      channel=channel)
        return moderation.get("reply", "")

    # Rate limiting per conversation
    if _is_rate_limited(conversation_id, channel):
        bm_logger.log("dm_rate_limited", conversation_id=conversation_id[:20],
                       channel=channel)
        return ""

    attachment_policy = (
        (config_loader.get_raw().get("agent_persona") or {}).get(
            "unsupported_attachment_handoff"
        ) or {}
    )
    attachment_reply = str(attachment_policy.get("reply") or "").strip()
    if (
        attachment_policy.get("enabled") is True
        and attachment_reply
        and message.get("attachments")
    ):
        # Q&A tenants explicitly opt into metadata-only human routing. Never
        # fetch, transcribe, or infer the contents of an unsupported attachment.
        return _handoff_reply(message, attachment_reply, defer_handoff=defer_handoff)

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
        reply = re.sub(r"\s*—\s*", ", ", reply)
        # Strip markdown code fences if present
        reply = re.sub(r"^```(?:json)?\s*", "", reply)
        reply = re.sub(r"\s*```$", "", reply.strip())
        reply = _apply_reply_style_guards(reply, text)
        # Clean up double spaces left by stripped placeholders
        while "  " in reply:
            reply = reply.replace("  ", " ")
        reply = reply.strip()

        # Sentinel detection produces an intent for durable webhook callers;
        # notification persistence happens only after their final fences.
        escalate_requested = "[ESCALATE]" in reply
        if escalate_requested:
            reply = reply.replace("[ESCALATE]", "").rstrip()

        if not reply:
            bm_logger.log("dm_empty_reply", conversation_id=conversation_id[:20],
                           channel=channel)
            return ""

        bm_logger.log("dm_reply_generated", conversation_id=conversation_id[:20],
                       channel=channel)
        if escalate_requested:
            return _handoff_reply(message, reply, defer_handoff=defer_handoff)
        return reply

    except HandoffPersistenceError:
        raise
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
