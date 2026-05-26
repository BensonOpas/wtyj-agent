# bluemarlin/agents/social/dm_agent.py
# Created: Brief 131
# Last modified: Brief 131b
# Purpose: DM Q&A agent — own Claude call, no booking flow, redirects to WhatsApp/email

import os
import re
import time
from datetime import datetime, timezone

import anthropic
from shared import state_registry, config_loader, bm_logger, icp_overrides
from shared import llm_telemetry, tenant_context

_MAX_REPLIES_PER_HOUR = 30
_REPLY_WINDOW_SECONDS = 3600


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


def _build_dm_icp_override_block(envelope: dict) -> str:
    """Render Nr3 SOT/tone overrides for the Q&A-only DM prompt path."""
    if not isinstance(envelope, dict):
        return ""

    entries = envelope.get("sot_entries") or []
    ai_agent_settings = envelope.get("ai_agent_settings") or {}
    if not isinstance(entries, list):
        entries = []
    if not isinstance(ai_agent_settings, dict):
        ai_agent_settings = {}

    tone = ai_agent_settings.get("tone")
    rules = ai_agent_settings.get("escalation_rules")

    has_tone = isinstance(tone, dict) and (
        (tone.get("tone") or "").strip() or (tone.get("notes") or "").strip()
    )
    has_rules = isinstance(rules, dict) and (
        rules.get("soft_escalation") or rules.get("hard_escalation")
    )

    clean_entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = (entry.get("title") or "").strip()
        content = (entry.get("content") or "").strip()
        category = (entry.get("category") or "general").strip()
        if title and content:
            clean_entries.append((category, title, content))

    if not (has_tone or has_rules or clean_entries):
        return ""

    lines = [
        "FINAL TENANT-SPECIFIC OPERATOR OVERRIDES FROM NR3 (HIGHEST PRIORITY):",
        "- These are the latest Calvin/operator instructions for this tenant.",
        "- Follow this block over generic DM examples, old default wording, and generic platform behavior.",
        "- Apply these instructions immediately in the next reply.",
    ]

    if has_tone:
        tone_value = (tone.get("tone") or "").strip()
        notes = (tone.get("notes") or "").strip()
        if tone_value:
            lines.append(f"\nTone override: {tone_value}")
        if notes:
            lines.append(f"Tone notes: {notes}")

    if clean_entries:
        lines.append("\nSource of Truth overrides:")
        for category, title, content in clean_entries:
            lines.append(f"[{category}] {title}\n{content}")

    if has_rules:
        soft = rules.get("soft_escalation") or {}
        hard = rules.get("hard_escalation") or {}
        lines.append("\nEscalation rule overrides:")
        if isinstance(soft, dict) and soft.get("enabled"):
            lines.append(f"- Agent needs help when: {(soft.get('when') or '').strip()}")
        if isinstance(hard, dict) and hard.get("enabled"):
            lines.append(f"- Human takeover when: {(hard.get('when') or '').strip()}")

    return "\n".join(lines)


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
    # Brief 206: booking_flow gate so the BOOKING REDIRECT block doesn't inject
    # for non-booking tenants (unboks etc.) where it would render a recursive
    # wa.me/<same-number-the-customer-is-on> redirect.
    booking_flow = config_loader.get_raw().get("features", {}).get("booking_flow", True)

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
    tenant_language_block = tenant_context.language_prompt_block(channel)
    tenant_safety_block = tenant_context.safety_prompt_block()
    emoji_block = "Emojis: sparingly, only if the customer used them first."
    output_rule = "Reply with ONLY your message text. No JSON. No code fences. No metadata. Just the reply."

    # Brief 234: optional APPROVED ANSWERS block (gated on
    # features.approved_learnings_in_prompt). Computed once, used by
    # both the master_prompt branch and the fallback branch below.
    approved_answers_block = _build_dm_approved_answers_block(channel)
    try:
        icp_override_block = _build_dm_icp_override_block(
            icp_overrides.fetch_overrides())
    except Exception:
        icp_override_block = ""

    if master_prompt:
        # Brief 203: master prompt mode. Drop the "friendly, casual, and human"
        # tone tail (qa_role_short, not qa_role_full) so master prompt's own
        # Tone block is sole tone source. Inject master prompt as standalone
        # paragraph (no wrapper — it has its own internal section headers).
        # Brief 206: only include BOOKING REDIRECT block when booking_flow is
        # true. Non-booking tenants don't have bookings to redirect to.
        parts = [intro, qa_role_short, master_prompt]
        if tenant_safety_block:
            parts.append(tenant_safety_block)
        if approved_answers_block:
            parts.append(approved_answers_block)
        parts.extend([services_block, faq_block])
        if booking_flow:
            parts.append(booking_redirect_block)
        parts.extend([tenant_language_block, language_block, emoji_block])
        if icp_override_block:
            parts.append(icp_override_block)
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
    if tenant_safety_block:
        fallback_parts.append(tenant_safety_block)
    if approved_answers_block:
        fallback_parts.append(approved_answers_block)
    fallback_parts.extend([
        services_block, faq_block, writing_style_block,
        booking_redirect_block, tenant_language_block, language_block, avoid_block,
        emoji_block, output_rule,
    ])
    if icp_override_block:
        fallback_parts.insert(-1, icp_override_block)
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

    try:
        if not icp_overrides.channel_is_enabled(channel):
            bm_logger.log("icp_channel_disabled_skip",
                          channel=channel,
                          conversation_id=conversation_id[:20])
            return ""
    except Exception as e:
        bm_logger.log("icp_channel_check_failed",
                      channel=channel, error=str(e)[:120])

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
            llm_telemetry.log_llm_event(
                provider="anthropic",
                model="claude-sonnet-4-6",
                feature_path="DM agent",
                channel=channel,
                started_at=time.monotonic(),
                success=False,
                error="missing_api_key",
                fallback_used=True,
            )
            return tenant_context.localized_fallback_reply(
                message_text=text, channel=channel)

        client = anthropic.Anthropic(api_key=api_key)
        system_prompt = _build_dm_system_prompt(channel)
        user_prompt = _build_dm_user_prompt(text, sender_name, messages)

        _started_at = time.monotonic()
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        llm_telemetry.log_llm_event(
            provider="anthropic",
            model="claude-sonnet-4-6",
            feature_path="DM agent",
            channel=channel,
            started_at=_started_at,
            success=True,
            response=response,
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

        # Brief 206: detect [ESCALATE] sentinel from master prompt's ESCALATION
        # SCRIPT. If present, strip it from the visible reply AND create a
        # pending_notifications row so the escalation surfaces in the operator
        # dashboard. The visible reply is unchanged (sans sentinel line).
        escalate_requested = "[ESCALATE]" in reply
        if escalate_requested:
            reply = reply.replace("[ESCALATE]", "").rstrip()
            try:
                _company = config_loader.get_business().get("name", "the business")
                _agent = config_loader.get_business().get("agent_name", "CSA")
                state_registry.create_pending_notification(
                    notification_type="escalation",
                    channel=channel,
                    customer_id=conversation_id,
                    customer_name=sender_name or "Unknown contact",
                    subject=f"{_agent} escalated a {channel} conversation",
                    body=(
                        f"Customer message:\n{text}\n\n"
                        f"{_agent}'s reply:\n{reply}\n\n"
                        f"({_company} — auto-escalated by {_agent} based on "
                        f"conversation context.)"
                    ),
                    mode="soft",
                )
                bm_logger.log("dm_escalation_created",
                               conversation_id=conversation_id[:20],
                               channel=channel)
            except Exception as e:
                bm_logger.log("dm_escalation_create_failed",
                               conversation_id=conversation_id[:20],
                               channel=channel,
                               error=str(e)[:200])

        if not reply:
            bm_logger.log("dm_empty_reply", conversation_id=conversation_id[:20],
                           channel=channel)
            return ""

        bm_logger.log("dm_reply_generated", conversation_id=conversation_id[:20],
                       channel=channel)
        return reply

    except Exception as e:
        _started_at = locals().get("_started_at", time.monotonic())
        llm_telemetry.log_llm_event(
            provider="anthropic",
            model="claude-sonnet-4-6",
            feature_path="DM agent",
            channel=channel,
            started_at=_started_at,
            success=False,
            error=e,
            fallback_used=True,
        )
        bm_logger.log("dm_agent_error", conversation_id=conversation_id[:20],
                       channel=channel, error=str(e)[:200])
        return tenant_context.localized_fallback_reply(
            message_text=text, channel=channel)


_DM_FALLBACK = "Thanks for your message. The team will review it and reply shortly."


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
