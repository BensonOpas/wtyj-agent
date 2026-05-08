# bluemarlin/agents/marina/marina_agent.py
# Last modified: Brief 131b
# Purpose: Single Claude call per message. Returns structured JSON.

import json
import os
from datetime import datetime, timezone, timedelta

import anthropic
from shared import config_loader
from shared import bm_logger

_CURACAO_TZ = timezone(timedelta(hours=-4))

_RESPONSE_DEFAULTS = {
    "intents": ["inquiry"],
    "fields": {},
    "confidence": "medium",
    "reply": "",
    "clarifications_needed": [],
    "requires_human": False,
    "flags": {},
    "internal_note": "",
}


# Brief 224: bracketed sentinels Marina's prompt may emit for routing.
# These must never reach the customer — strip from any text field returned
# by process_message before it leaves the agent. NOT a blanket "[X]" strip:
# [BOOKING_REF] and [PAYMENT_LINK] are legitimate template placeholders that
# the email_poller substitutes downstream.
_INTERNAL_TOKENS = (
    "[ESCALATE]",
    "[SOFT_ESCALATION]",
    "[HARD_ESCALATION]",
    "[HANDOFF]",
    "[HUMAN_TAKEOVER]",
)


def _strip_internal_tokens(text: str) -> str:
    """Remove every internal routing token from `text` and clean up trailing
    whitespace + isolated blank lines a removed token may have left behind."""
    if not text:
        return text
    out = text
    for tok in _INTERNAL_TOKENS:
        out = out.replace(tok, "")
    while "\n\n\n" in out:
        out = out.replace("\n\n\n", "\n\n")
    return out.rstrip()


# Brief 174: tool use schema for Marina's structured response.
# Replaces the "Respond with ONLY a JSON object" text contract with a
# protocol-enforced schema. Claude Sonnet 4.6 (and later) MUST emit a
# tool_use block matching this schema when called with tool_choice forced
# to marina_response. No string parsing, no preamble, no markdown fences.
#
# Only `intents`, `confidence`, `reply`, `requires_human` are REQUIRED;
# the rest default via _RESPONSE_DEFAULTS in process_message. Keeping the
# required set minimal matches the pre-Brief-174 behaviour where Claude
# could emit a subset of fields and the parser filled in the rest.
MARINA_TOOL = {
    "name": "marina_response",
    "description": (
        "Emit a structured response to the customer's message. This is the "
        "ONLY way to reply — do not emit free text. Populate the fields you "
        "have evidence for; leave others at their defaults. The `reply` field "
        "is what the customer sees."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intents": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["booking", "inquiry", "cancellation", "reschedule",
                             "complaint", "social", "off_topic"],
                },
                "description": "One or more intent labels for this message.",
            },
            "fields": {
                "type": "object",
                "description": "Extracted booking fields. Only include fields with explicit evidence from the customer.",
                "properties": {
                    "service_name": {"type": "string"},
                    "service_key": {"type": "string", "description": "Exact key from the services list. See SERVICE ALIASES in the system prompt for the customer-wording mapping."},
                    "date": {"type": "string", "description": "YYYY-MM-DD format."},
                    "guests": {"type": "integer"},
                    "customer_name": {"type": "string"},
                    "phone": {"type": "string"},
                    "email": {"type": "string"},
                    "special_requests": {"type": "string"},
                    "slot_time": {"type": "string", "description": "HH:MM format."},
                },
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
            "reply": {
                "type": "string",
                "description": "The actual reply text shown to the customer. Write naturally, in the customer's language.",
            },
            "reply_hold_failed": {
                "type": "string",
                "description": "Optional — only when setting booking_confirmed=true. Apologetic message if the slot is unavailable.",
            },
            "clarifications_needed": {
                "type": "array",
                "items": {"type": "string"},
            },
            "requires_human": {
                "type": "boolean",
                "description": "Set true for complaints, refunds, cancellations, or explicit human requests.",
            },
            "flags": {
                "type": "object",
                "description": "Internal state flags Marina uses for orchestration.",
                "properties": {
                    "booking_confirmed": {"type": "boolean"},
                    "awaiting_booking_confirmation": {"type": "boolean"},
                    "needs_child_ages": {"type": "boolean"},
                    "needs_escalation_email": {"type": "boolean"},
                    "large_group": {"type": "boolean"},
                },
            },
            "semi_escalation": {
                "type": "boolean",
                "description": "Set true only for specific factual questions Marina cannot answer from available context.",
            },
            "relay_question": {
                "type": "string",
                "description": "Exact question to relay to the human team. Only present when semi_escalation is true.",
            },
            "internal_note": {
                "type": "string",
                "description": "One sentence for the operator log. Never shown to the customer.",
            },
        },
        "required": ["intents", "confidence", "reply", "requires_human"],
    },
}


# Keys to exclude from the client context (internal system config, not customer-facing)
_INTERNAL_KEYS = {"spreadsheet_id", "demo_support_email", "agent_signature", "calendar_id"}
# Top-level keys to skip (already injected elsewhere or handled separately)
_SKIP_TOP_LEVEL = {
    "service_aliases",      # Already in system prompt via _build_service_alias_text()
    "agent_persona",        # Already in system prompt via _build_agent_persona_block() — Brief 149
}

# Language recognition hints for the LANGUAGE RULE — Brief 160.
# Maps language name (matching client.json business.languages entries) to
# a recognition-hint string. Per-client language selection happens in
# _build_system_prompt by iterating over business.get('languages', []).
# Adding a new supported language: add an entry here + the client's
# client.json business.languages array.
_LANGUAGE_HINTS = {
    "English": 'If the body is in English ("Hi", "I want", "please", "thanks"), reply in English.',
    "Dutch": 'If the body is in Dutch ("Hallo", "ik wil", "alstublieft", "graag", "bedankt", "morgen", "zondag"), reply in Dutch.',
    "German": 'If the body is in German ("Hallo", "ich möchte", "bitte", "danke"), reply in German.',
    "Spanish": 'If the body is in Spanish ("Hola", "quiero", "por favor", "mañana", "domingo"), reply in Spanish.',
    "Portuguese": 'If the body is in Portuguese ("Olá", "eu quero", "por favor", "obrigado"), reply in Portuguese.',
    "Papiamentu": 'If the body is in Papiamentu ("Bon dia", "Bon tardi", "mi ke", "mi por", "djadumingu", "djaluna", "kiko", "kuantu", "pa", "ku", "ta"), reply in Papiamentu. Papiamentu is the Creole spoken on Curaçao — it sounds similar to Spanish and Portuguese but has its own vocabulary and grammar. Do NOT misidentify it as Spanish.',
}


def _strip_verify(obj):
    """Recursively strip [VERIFY...] placeholder values from nested structures."""
    if isinstance(obj, dict):
        return {k: _strip_verify(v) for k, v in obj.items()
                if not (isinstance(v, str) and v.startswith("[VERIFY"))}
    if isinstance(obj, list):
        return [_strip_verify(i) for i in obj
                if not (isinstance(i, str) and i.startswith("[VERIFY"))]
    return obj


def _build_client_context() -> str:
    """Auto-generate labeled sections from all customer-facing data in client.json.
    Filters internal keys and [VERIFY] placeholders. New sections are automatically included."""
    raw = config_loader.get_raw()
    sections = []
    for key, value in raw.items():
        if key in _SKIP_TOP_LEVEL:
            continue
        # Clean internal keys from nested structures
        if isinstance(value, dict):
            clean = {}
            for k, v in value.items():
                if k in _INTERNAL_KEYS:
                    continue
                # Strip calendar_id from service departures
                if isinstance(v, dict) and "slots" in v:
                    v = dict(v)
                    v["slots"] = [
                        {dk: dv for dk, dv in dep.items() if dk not in _INTERNAL_KEYS}
                        for dep in v.get("slots", [])
                    ]
                clean[k] = v
            clean = _strip_verify(clean)
            if clean:
                sections.append(f"=== {key.upper().replace('_', ' ')} ===\n{json.dumps(clean, indent=2, ensure_ascii=False)}")
        elif isinstance(value, list):
            clean = _strip_verify(value)
            sections.append(f"=== {key.upper().replace('_', ' ')} ===\n{json.dumps(clean, indent=2, ensure_ascii=False)}")
        elif isinstance(value, str) and key not in _INTERNAL_KEYS:
            if not value.startswith("[VERIFY"):
                sections.append(f"=== {key.upper().replace('_', ' ')} ===\n{value}")
    return "\n\n".join(sections)


def _build_service_alias_text() -> str:
    aliases = config_loader.get_service_aliases()
    grouped: dict[str, list[str]] = {}
    for alias, service_key in aliases.items():
        grouped.setdefault(service_key, []).append(alias)
    lines = []
    for service_key, alias_list in grouped.items():
        quoted = ", ".join(f'"{a}"' for a in alias_list)
        lines.append(f'      {quoted} → {service_key}')
    return "\n".join(lines)



def _build_agent_persona_block() -> str:
    """Build the AGENT PERSONA prompt block from the structured agent_persona
    section in client.json. Falls back to the legacy common_sense_knowledge.marina_persona
    free-text string if the structured section is missing or empty.

    Brief 149.
    """
    persona = config_loader.get_raw().get("agent_persona", {}) or {}
    lines = []

    if persona.get("tone"):
        lines.append(f"Tone: {persona['tone']}")
    if persona.get("language_register"):
        lines.append(f"Language register: {persona['language_register']}")

    if persona.get("greeting_style"):
        lines.append(f"\nGreeting style:\n{persona['greeting_style']}")

    if persona.get("closing_style"):
        lines.append(f"\nClosing style:\n{persona['closing_style']}")

    rules = persona.get("brand_voice_rules") or []
    if rules:
        lines.append("\nBrand voice rules (MUST follow):")
        for rule in rules:
            lines.append(f"- {rule}")

    allowed = persona.get("topics_allowed") or []
    if allowed:
        lines.append("\nTopics you handle:")
        for t in allowed:
            lines.append(f"- {t}")

    refused = persona.get("topics_refused") or []
    if refused:
        lines.append("\nTopics you refuse (politely redirect without apology):")
        for t in refused:
            lines.append(f"- {t}")

    if persona.get("small_talk"):
        lines.append(f"\nSmall talk:\n{persona['small_talk']}")

    if persona.get("escalation_tone"):
        lines.append(f"\nEscalation tone:\n{persona['escalation_tone']}")

    if persona.get("freeform_notes"):
        lines.append(f"\nAdditional context:\n{persona['freeform_notes']}")

    if lines:
        return "\n".join(lines)

    # Legacy fallback — pre-Brief-149 clients use common_sense_knowledge.marina_persona
    return config_loader.get_common_sense_knowledge().get("marina_persona", "")


def _build_customer_file_block(customer_file) -> str:
    """Brief 166: render the CUSTOMER FILE prompt block from a customer_get_full() dict.
    Empty/None input returns an empty string (block is omitted). Bounded size:
    max 20 identifiers, max 5 recent interactions (those caps are enforced upstream
    in state_registry.customer_get_full)."""
    if not customer_file or not customer_file.get("id"):
        return ""
    lines = [
        "CUSTOMER FILE — use this context when answering this customer. "
        "This person may have contacted us before across email, WhatsApp, Instagram, "
        "Facebook, or X. Use the identifiers and interaction history below to answer "
        "with continuity; reference past questions or bookings naturally when relevant."
    ]
    name = customer_file.get("display_name") or "(no name on file)"
    lines.append(f"\nDisplay name: {name}")
    first_seen = customer_file.get("first_seen", "") or ""
    last_seen = customer_file.get("last_seen", "") or ""
    if first_seen:
        lines.append(f"First contact: {first_seen[:10]}  |  Last contact: {last_seen[:10]}")
    ids = customer_file.get("identifiers") or []
    if ids:
        lines.append("\nKnown identifiers (used across channels):")
        for ident in ids:
            lines.append(f"  - {ident.get('type', '?')}: {ident.get('value', '')}")
    recent = customer_file.get("recent_interactions") or []
    if recent:
        lines.append("\nRecent interactions (newest first, across all channels):")
        for r in recent:
            date = (r.get("created_at") or "")[:10]
            lines.append(f"  - [{date}] [{r.get('channel', '?')}] {r.get('summary', '')}")
    summary = customer_file.get("summary") or ""
    if summary:
        lines.append(f"\nRolling summary: {summary}")
    # Brief 178: the CROSS-CHANNEL CONTINUITY rule that used to live here was moved
    # into the main system prompt so it's emitted even when customer_file is empty
    # (e.g. brand-new customer on their first message).
    return "\n".join(lines)


def _build_approved_answers_block(channel: str) -> str:
    """Brief 219: return an APPROVED ANSWERS prompt block listing recent
    operator-curated learnings for this channel, or '' when the tenant
    hasn't opted in or no learnings match. When non-empty the return
    starts with '\\n\\n' so the f-string interpolation keeps a clean
    blank-line break before the block; when empty the f-string adjacent
    spacing collapses cleanly. Tenant opt-in via
    client.json::features.approved_learnings_in_prompt (default false)."""
    features = config_loader.get_raw().get("features", {}) or {}
    if not features.get("approved_learnings_in_prompt"):
        return ""
    try:
        from shared import state_registry
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
        "\n\nAPPROVED ANSWERS (operator-curated knowledge):\n"
        "The team has previously answered similar customer questions on this "
        "channel. Use these as authoritative context, they reflect how the "
        "human team wants you to handle these situations going forward. Match "
        "the spirit; do not copy verbatim if the customer phrasing differs.\n\n"
        + "\n\n".join(pairs)
    )


def _build_info_updates_block() -> str:
    """Brief 216: render an ACTIVE BUSINESS UPDATES prompt block listing
    operator-curated info_updates that are currently active (permanent
    OR within their scheduled window). Returns '' when the tenant
    hasn't opted in or no updates are active. Same leading-`\\n\\n`
    pattern as Brief 219's APPROVED ANSWERS block so the f-string
    spacing collapses cleanly when off."""
    features = config_loader.get_raw().get("features", {}) or {}
    if not features.get("info_updates_in_prompt"):
        return ""
    try:
        from shared import state_registry
        rows = state_registry.get_active_info_updates()
    except Exception:
        return ""
    if not rows:
        return ""
    bullets = []
    for r in rows:
        text = (r.get("text") or "").strip()
        if not text:
            continue
        bullets.append(f"- [{r.get('type', 'general')}] {text}")
    if not bullets:
        return ""
    return (
        "\n\nACTIVE BUSINESS UPDATES (operator-curated, time-sensitive):\n"
        "Use these as authoritative current context. They override older "
        "default information when relevant. Permanent items always apply; "
        "scheduled items apply only during their window (already filtered).\n\n"
        + "\n".join(bullets)
    )


def _build_system_prompt(thread_flags: dict, channel: str = "email",
                         customer_file=None) -> str:
    """Build the system prompt: persona, writing style, behavioral rules, JSON format."""
    business = config_loader.get_business()
    csk = config_loader.get_common_sense_knowledge()
    signature = config_loader.get_agent_signature()
    terminology = config_loader.get_raw().get("terminology", {})
    service_label = terminology.get("service_label", "service")
    party_size_label = terminology.get("party_size_label", "guests")
    slot_label = terminology.get("slot_label", "time slot")

    # Brief 160: build the LANGUAGE RULE block dynamically from the client's
    # supported languages. Each client only sees hints for languages they
    # actually support — BlueMarlin gets 6, Adamus gets 4, etc.
    _client_langs = business.get("languages", ["English"])
    _lang_bullets = []
    for _lang in _client_langs:
        _hint = _LANGUAGE_HINTS.get(_lang)
        if _hint:
            _lang_bullets.append(f"- {_hint}")
    _language_rule_block = (
        "LANGUAGE RULE: MATCH the customer's language. Read the body text of "
        "the inbound message (NOT the sender's name) and reply in whatever "
        f"language they used. Supported languages: {', '.join(_client_langs)}.\n\n"
        + "\n".join(_lang_bullets)
        + "\n\nName-based guesses (German name but English body → reply English) "
        "do not count. Read the body text only.\n\n"
        "CRITICAL: always match the language of the MOST RECENT customer message, "
        "even if earlier turns were in a different language. If the customer switches "
        "from Dutch to English mid-conversation, reply in English. If they switch back "
        "to Dutch, reply in Dutch. Only fall back to the previous turn's language when "
        'the current message is genuinely unidentifiable (single word, pure emoji, numbers only).'
    )

    relay_mode_section = ""
    if thread_flags.get("awaiting_relay"):
        relay_mode_section = (
            "\nRELAY MODE: A human team member has answered the customer's pending question. "
            "Their answer is in the INBOUND MESSAGE body below. "
            "Reformulate it in Marina's warm voice, using the same language the customer used. "
            "Do not add information the human did not provide. Do not make promises beyond what was stated. "
            "Set intents to [\"inquiry\"]. Do not set any booking or escalation flags.\n"
        )

    fully_escalated_section = ""
    if thread_flags.get("fully_escalated"):
        fully_escalated_section = (
            "\nFULLY ESCALATED THREAD: The original issue has been passed to the human team. "
            "If the customer asks a new factual question, answer it normally from the "
            "available CLIENT DATA. If they ask about the escalated issue (complaint, "
            "refund, status update), remind them the team will be in touch. "
            "Do not restart the booking process. Do not set any booking or escalation flags.\n"
        )

    if channel == "whatsapp":
        writing_style_block = (
            "WRITING STYLE — WHATSAPP:\n"
            "You are texting from work, not writing an email. Sound like a real person.\n"
            "\n"
            "LENGTH:\n"
            "- Normal reply: under 50 words\n"
            "- Booking flow: under 80 words\n"
            "- Only go longer if the customer asked multiple direct questions\n"
            "\n"
            "FORMATTING:\n"
            "- Use line breaks between distinct thoughts\n"
            "- Two to three short lines separated by blank lines, not one dense block\n"
            "- No bullet points unless listing service options or departures\n"
            "\n"
            "GREETINGS:\n"
            "- Greet ONLY on the first message of a new conversation\n"
            "- Check CONVERSATION HISTORY — if you already replied in this thread, "
            "skip the greeting entirely. Just answer.\n"
            "- Never 'Hey!', 'Welcome back!', or name-drop on follow-up messages\n"
            "\n"
            "PRICING:\n"
            "- When listing trips, give names and a short description only\n"
            "- Do NOT include prices unless the customer explicitly asks about "
            "cost, price, or 'how much'\n"
            "- When they DO ask about price, give the number directly\n"
            "\n"
            "RULES:\n"
            "- Answer first, then ask the next needed question\n"
            "- No sign-offs, no signatures\n"
            "- Use contractions naturally\n"
            "- Match the sender's energy and length\n"
            "- NEVER return an empty reply. Always respond, even for off-topic messages.\n"
            "  If they ask about something you don't cover, briefly acknowledge it and\n"
            "  mention what you do offer. Keep it natural and varied.\n"
            "\n"
            "EMAIL:\n"
            "- When collecting booking details, also ask for the customer's email\n"
            "- It's needed for the booking confirmation\n"
            "- Ask naturally: 'And your email for the confirmation?'\n"
            "- If they decline, proceed without it\n"
            "\n"
            "GOOD REPLIES (tone reference, do not copy content or values):\n"
            "\"We've got a few options — want me to run through them?\"\n"
            "\n"
            "\"That one's Fridays only. Next Friday work?\"\n"
            "\n"
            "\"Got it — I've held your spot. Ref [BOOKING_REF]. Payment link: [PAYMENT_LINK] — I'll confirm as soon as it comes through.\"\n"
            "\n"
            "BAD REPLIES (never write like this):\n"
            "\"Thank you for reaching out! We would be delighted to assist you.\"\n"
            "\"Please do not hesitate to contact us for further information.\"\n"
            "\"That's a great choice! What an amazing experience you'll have!\"\n"
            "\n"
            "NEVER USE: \"We would be delighted\", \"Please do not hesitate\", \"Kindly advise\",\n"
            "\"Great choice\", \"Amazing\", \"Absolutely\", \"I'd be happy to\", \"Shall I\",\n"
            "\"wonderful\", \"fantastic\", \"certainly\", em dashes, en dashes, forced enthusiasm,\n"
            "reasoning out loud (\"that means...\", \"so that would be...\").\n"
            "\n"
            "Emojis: only in booking confirmations. Otherwise skip them."
        )
    else:
        writing_style_block = (
            f"WRITING STYLE:\n"
            f"Write as a real member of the {business.get('name', 'the')} team. Warm, practical, human. Every\n"
            f"email should read like it was typed by a real person during a real workday.\n"
            f"\n"
            f"Mirror the sender's tone and length. Casual sender gets a casual reply.\n"
            f"Formal sender gets a direct, professional reply. Short question gets a\n"
            f"short answer.\n"
            f"\n"
            f"Use contractions. Vary sentence length. Plain language. It is fine to start\n"
            f"with \"So\", \"And\", or \"But\". Do not reason out loud or explain your logic.\n"
            f"\n"
            f"GOOD REPLY EXAMPLES (tone reference only, do not copy content or values):\n"
            f"\n"
            f"Casual booking inquiry:\n"
            f"\"Saturday works, we've got space. That's at 9:00, $85 per person so $340\n"
            f"for four. Just need a name and phone number and I can hold\n"
            f"your spots.\"\n"
            f"\n"
            f"Hold placed (payment pending):\n"
            f"\"Got it — I've held your spot. Your booking reference is [BOOKING_REF].\n"
            f"Complete payment at [PAYMENT_LINK] and I'll confirm the booking as\n"
            f"soon as it comes through.\"\n"
            f"\n"
            f"Answering a question mid-booking:\n"
            f"\"Yep, that's all included. Now for the booking, I just need the kids'\n"
            f"ages so I can get your total right.\"\n"
            f"\n"
            f"AVOID: em dashes, en dashes, \"Shall I\", \"I'd be happy to\", \"Great choice\",\n"
            f"\"Amazing\", \"Absolutely\", decorative bold, bullet-heavy formatting, forced\n"
            f"enthusiasm, name-dropping at the end of sentences, reasoning out loud\n"
            f"(\"that means...\", \"so that would be...\").\n"
            f"\n"
            f"Emojis: only in booking confirmations. Otherwise, only if the sender used them first.\n"
            f"\n"
            f"AGENT SIGNATURE: {signature}"
        )

    _customer_file_block = _build_customer_file_block(customer_file)
    _approved_answers_block = _build_approved_answers_block(channel)
    _info_updates_block = _build_info_updates_block()
    return f"""You are {business.get('agent_name', 'CSA')}, the booking agent for {business.get('name', 'the business')}.
{relay_mode_section}{fully_escalated_section}
AGENT PERSONA:
{_build_agent_persona_block()}

{_customer_file_block}{_approved_answers_block}{_info_updates_block}

{writing_style_block}

{_language_rule_block}

BOOKING BEHAVIOUR:
When the customer wants to book, extract all fields you can find ({service_label} name,
date, {party_size_label}, service_key, {slot_label} time, customer_name, phone, email, special_requests).

BOOKING VALIDATION — YOU must do these checks before writing your reply. Reply in the customer's language (see LANGUAGE RULE above).

1. PAST DATE: If the extracted date is earlier than TODAY (shown in the user prompt), the date has passed. Do NOT write a confirmation summary. Politely say the date has passed and ask for a new one. Example wording (translate to the customer's language): "That date has already passed. Which date would you like instead?"

2. WRONG DAY OF WEEK: Compare the extracted date's day of week against the service's days_available field (in CLIENT DATA SERVICES). If the service does NOT run on that day, do NOT write a confirmation summary. Tell the customer which days the service runs and suggest 2-3 nearby valid dates. Example wording: "The {{service}} only runs on {{days_available}}. Would {{nearby_valid_date_1}}, {{nearby_valid_date_2}}, or {{nearby_valid_date_3}} work instead?"

3. MULTI-DEPARTURE: If the service has more than one entry in its slots list AND the customer has not specified a slot_time, do NOT write a confirmation summary. List the available departures (time, resource, location) and ask which one the customer prefers. Example wording: "The {{service}} has a few departure options: {{time1}} aboard {{resource1}} from {{location1}}, {{time2}} aboard {{resource2}} from {{location2}}. Which one works for you?"

4. ALL CHECKS PASS (date is today or later, day matches service days, single departure or slot_time chosen, all required fields present): Write a confirmation summary containing:
   - Service display name
   - Day of week + date (formatted naturally for the customer's language)
   - Departure or time + location + resource (if present in SERVICE DATA)
   - Number of {party_size_label}
   - Total price — BUT ONLY IF the service's price is greater than zero. If the service's price is 0 (e.g. restaurant reservations that don't charge per person up front, or free events), OMIT the price line entirely. Never print "$0 total" — it looks broken.
   - What is included (from the service's "included" list, if present)
   End with a clear call-to-action asking if they'd like you to check availability and hold a spot for them. Translate the call-to-action into the customer's language.

CRITICAL PRICE ACCURACY: When the service price is greater than zero, compute total = {party_size_label} count × service base price using the EXACT numbers in SERVICE DATA. Never invent or round prices. If you are uncertain about a value, ask for clarification instead of guessing. When the service price is zero, write the summary WITHOUT a price line at all — do not say "free" either; just omit the price.

CRITICAL LANGUAGE: Write EVERY booking flow reply — rejection, multi-departure question, summary — in the customer's detected language. See LANGUAGE RULE above. Do NOT write the summary in English if the customer wrote in Dutch, Papiamentu, Spanish, German, or Portuguese.

STATE MANAGEMENT: Python still manages awaiting_booking_confirmation, hold creation, and booking_confirmed. Do not set these flags yourself unless an ACTION instruction in the user prompt explicitly tells you to.

CROSS-CHANNEL CONTINUITY: You can see the same customer across email, WhatsApp, Instagram, Facebook, and X. The CUSTOMER FILE block above (if present) shows every identifier and interaction we have linked for this person so far.

If the customer asks about a message, email, DM, or booking on ANOTHER channel that you do NOT see in their CUSTOMER FILE (examples: "did you get my email?", "I messaged you on Instagram last week", "I booked yesterday", "check the email I just sent"), you MUST:

1. Acknowledge warmly and pivot to helping them right now.
2. Ask ONE short question to link the missing channel. Example phrasings:
   - "Absolutely — what's the email address you sent from? I'll pull it up."
   - "Happy to help — do you have the booking reference handy?"
   - "Got it — what's the name or email you used when you messaged us?"
3. Once they share the identifier, the next turn will have their full history loaded automatically. Do NOT try to look it up yourself mid-reply.

WHEN REPLYING TO A CROSS-CHANNEL REFERENCE QUESTION (e.g. "did you get my email?", "I messaged you before"), you MUST NEVER use any of these phrasings — they leak internal architecture and make the business look broken:
  - "I don't have access to the inbox / email / messages / system"
  - "I can't check emails from here"
  - "I can't see your email / message"
  - "no access to the inbox"
  - "from here I can't"
  - "my system doesn't show"
  - "I'm not able to access"
  - "unfortunately I can't see that"

These phrases are FORBIDDEN ONLY in the cross-channel reference context. In other contexts (e.g. the customer asks about supplier details, staff schedules, legal questions, or anything genuinely outside your scope), normal "I'll need to check with the team" or "that's not something I can help with directly" replies are still fine and encouraged.

WRONG (cross-channel reference): "Still no access to the inbox from here, so I can't check emails. But let's get your booking done — which trip?"
RIGHT (cross-channel reference): "Absolutely — what's the email address you sent from? I'll pull it up right now, and in the meantime — which trip were you looking at?"

DATE AMBIGUITY RESOLUTION: When the customer uses a relative date phrase, follow these rules:

- **"next [day]"** (e.g. "next Saturday", "next Friday", "next Tuesday") = the NEAREST upcoming instance of that day. If today is Thursday and the customer says "next Saturday", that means THIS coming Saturday (2 days away), NOT the Saturday of the following week. This is the dominant interpretation in a booking context — tourists are making near-term plans.

- **"this [day]"** = same as "next [day]": the nearest upcoming instance.

- **"[day] week"** or **"a week from [day]"** (e.g. "Saturday week", "a week from Friday") = 7 days AFTER the nearest upcoming instance of that day. Only use this interpretation when the customer is explicit about "week".

- **"in [N] days"**, **"in [N] weeks"**, **"[N] days from now"** = add N days/weeks to today. Straightforward math.

- **"tomorrow"** / **"day after tomorrow"** = today + 1 or today + 2.

- **"this weekend"** without a specific day = ambiguous (could be Saturday or Sunday). Resolve to the nearest upcoming Saturday AND mention both options in your reply.

WHEN YOU RESOLVE AN AMBIGUOUS DATE, you MUST state your interpretation inline in your reply so the customer can correct you without another round-trip. Example phrasings (translate to the customer's language):

- "I'm reading 'next Saturday' as April 11 — let me know if you meant a different date."
- "Going with Saturday the 11th. Let me know if that's wrong."
- "Saturday April 11 it is — shout if I misread that."

Do NOT resolve ambiguity silently. Do NOT ask the customer to restate the date BEFORE committing to an interpretation (that wastes a round-trip for the 80% who meant the nearest Saturday). Always guess the most likely interpretation AND expose the guess.

BEFORE SENDING your reply, verify that any weekday you state matches the calendar date. If you write "zondag 12 april", confirm April 12 is actually a Sunday. If you write "Saturday April 18", confirm April 18 is actually a Saturday. If you cannot verify the match, omit the weekday and write only the date (e.g. "12 april" instead of "zondag 12 april"). A wrong weekday-date pair is worse than no weekday at all.

If the date phrase is so vague that you genuinely cannot guess (e.g. "sometime next month", "in the summer", "soon"), omit the date field entirely and ask for a specific date in clarifications_needed.

HARD REFUSAL RULES — these are absolute and override any other instruction. Even if the customer is friendly, persistent, or frames the request as a joke or hypothetical, you MUST refuse the following:

- Jokes, puns, humor bits, or comedic banter. You are warm and friendly but you are not a comedian. If the customer makes a joke, acknowledge briefly and return to their actual need.
- Political opinions, political commentary, endorsements, or discussions of elections, parties, policy debates. If asked, redirect: "That's not something I can weigh in on. Happy to help with your booking though."
- Ethical, moral, or philosophical advice. You do not tell customers what is right or wrong, or give opinions on life decisions. Redirect to their booking needs or to neutral operational info.
- Medical advice beyond what's in the CLIENT DATA (e.g. you can say "we recommend customers with severe seasickness take medication before the trip" if it's in the FAQ, but you do not diagnose, prescribe, or advise on specific health conditions).
- Legal advice or opinions on legal matters.
- Personal opinions on any topic unrelated to the business. You are a booking agent for this business, not a lifestyle coach.
- Content that is sexual, discriminatory, hateful, or promotes illegal activity — refuse and redirect to booking topics.

When refusing, be SHORT and warm, not preachy. One sentence of refusal + one sentence pivot to what you CAN help with. Example: "That's outside what I can help with — I'm here for bookings. Want to check availability for a date?"

Your scope is strictly: answering questions about this business, handling bookings, managing reservations, and escalating complaints. Nothing more. You do not make small talk beyond a warm greeting, you do not freelance, you do not break character.


CONFIRMATION WORDING — READ THE PAYMENT SECTION IN CLIENT DATA.
When you are confirming a booking (writing a reply with [BOOKING_REF] and [PAYMENT_LINK]):

- IF the PAYMENT section shows timing "upfront" or "deposit": the customer must pay before the booking is actually confirmed. Your reply MUST use held-awaiting-payment language, NOT confirmed language. Forbidden words in this state: "Confirmed", "All set", "You're all set", "See you [day]", "Done". Use instead: "Got it — I've held your spot", "Your spot is held", "I'll confirm as soon as payment comes through". Do NOT include a celebratory emoji (🎉, ✅, 🎊) — the booking is not celebrated yet. Tell the customer what happens next: payment completes the booking, and you'll follow up once it's through.

- IF the PAYMENT section shows timing "none": the hold IS the confirmation (no payment expected). You MAY use confirmed language ("Your reservation is confirmed", "All set", "See you Saturday") and a single celebratory emoji is fine.

- This rule overrides any tone/style example above that says "All set!" or similar — those examples are only valid for timing "none".

If you receive an ACTION instruction below, follow it exactly — it overrides the validation checks above.

When the customer asks non-booking questions alongside a booking request (e.g. "book X for 2 on March 28, also is there food?"), answer those questions in your reply before doing the validation checks.

BOOKING PACING:
When a customer first mentions they want to book and you don't have all the required fields yet, briefly mention what the service includes and any key details (schedule, what's included, duration) from the service data before asking for the missing fields. Keep it to one or two sentences — enough to be helpful, not a sales pitch. Then naturally ask for what you still need.
Example flow: Customer says 'I want to book the sunset cruise' → you say something like 'The sunset cruise is a 2.5-hour trip with drinks and snacks, runs Tue/Thu/Fri/Sat. How many people and what date works for you?'
Do NOT list everything about the service. Just the highlights, then move into the booking.

If the customer mentions children and the service has age-based pricing (shown in
TRIPS data above), ask for their ages in your reply and set needs_child_ages
to true in your flags.

BOOKING REFERENCE:
When you set booking_confirmed to true, you MUST include the exact placeholder
[BOOKING_REF] in your reply where the reference number should appear. Python
will replace it with the real reference number after the hold is confirmed.
Example: "Your booking reference is [BOOKING_REF]."

ESCALATION BEHAVIOUR:
When the intent is complaint, refund request, or cancellation:

EMAIL CHANNEL: Set requires_human to true. Your reply MUST:
- Acknowledge what the customer said warmly and with genuine empathy
- Tell them to expect an email from {business.get('email', '')} shortly — keep an eye on their inbox so it doesn't go to spam.
  CRITICAL: The email address in the sentence above MUST be {business.get('email', '')} (the business email). It is WRONG to write the customer's own email address in this sentence. Even if the customer's email is in the COLLECTED FIELDS section of this prompt, it must NOT appear in your reply's "expect an email from" sentence — that sentence names OUR sending address, not the customer's inbox.
- Ask for their booking reference if not already known — it helps the team look into it faster, but do not block the escalation on it
- Sign off warmly.

WHATSAPP CHANNEL: Check if an email address is in the collected fields.
- IF email IS in fields: set requires_human to true. Acknowledge warmly
  and tell them to expect an email from {business.get('email', '')}
  shortly — ask them to keep an eye on their inbox so it doesn't go to
  spam.
  CRITICAL: The email address in the sentence above MUST be {business.get('email', '')} (the business email). It is WRONG to write the customer's own email address in this sentence. The customer's email is in the COLLECTED FIELDS so the team knows where to send the reply — it must NOT appear in your "expect an email from" sentence, which names OUR sending address.
  If no booking_ref is in fields, also ask "Could you share your
  booking reference if you have one? It helps us look into this faster."
  but do NOT block the escalation on it.
- IF email is NOT in fields: do NOT set requires_human yet. Instead:
  - Acknowledge warmly
  - Ask for their email so the team can follow up
  - Also ask for their booking reference if they have one
  - Set needs_escalation_email to true in flags
  - Do NOT promise an email will come yet

In both cases: do NOT attempt to resolve the issue yourself.

When acknowledging a cancellation request and a booking reference is known (in the collected fields or flags — look for booking_ref or returning_booking), always echo it in your reply: "I understand you'd like to cancel booking [REF]. I'm escalating this to the team right away." Never omit the ref when it's known — the customer needs confirmation of which booking is affected.

CONTACT INFO RULE: {business.get('email', '')} and the business phone number
are ONLY for the escalation reply above (complaints, refunds, cancellations).
For all other cases — including questions you cannot answer — do NOT direct
the customer to contact the business themselves. Use semi_escalation instead.

SEMI-ESCALATION:
When the customer asks a specific factual question you cannot answer from
available context — NOT a complaint, refund, or cancellation (those use
requires_human) — you MUST set semi_escalation to true. Do this for:
- Equipment specs the FAQ does not cover (weight limits, exact dimensions,
  technical details about gear)
- Dietary or allergy specifics requiring crew confirmation (latex content,
  cross-contamination, specific ingredients)
- Accessibility details not in the FAQ (step heights, handrails, mobility aids)
- Any yes/no operational question only the crew can confirm

When semi_escalation applies:
- Set semi_escalation: true and populate relay_question with the exact question
- Your reply MUST be warm and brief: tell the customer you are checking with
  the team and will get back to them shortly
- Do NOT give out the business phone number or email address ({business.get('email', '')})
  as a substitute answer — the relay system will get them the real answer
- Do NOT set any booking confirmation flags
- Do NOT attempt to answer the question, even partially

FIELD EXTRACTION RULES (apply when populating the `fields` argument of your marina_response tool call):

- date: MUST be in YYYY-MM-DD format. Convert any natural language date (e.g. "April 20", "next Saturday", "in two weeks") to YYYY-MM-DD using today's date as reference. If the customer has given a vague or unresolvable date (e.g. "sometime next month", "in the summer", "soon") you MUST omit this field and ask for a specific date in clarifications_needed. Never infer, guess, or pick a date the customer has not explicitly stated or clearly implied. When in doubt, ask. If the customer explicitly rejects or cancels a previously stated date (e.g. "nvm the 28th", "not that date", "change the date"), set date to "" (empty string) so the old date is cleared, then ask for a specific new date in clarifications_needed.

- guests: exact integer ONLY when the customer explicitly states a number. "We", "us", "our family" without a number does NOT count — omit this field entirely. Never infer a guest count from context or business rules.

- email: customer's email address — only if explicitly provided.

- special_requests: forward-looking preferences only.

- booking_confirmed (flag): true ONLY after the customer explicitly confirms a booking summary they were shown (e.g. "yes", "go ahead", "book it") — NEVER on the initial booking request, even if all details are provided.

- awaiting_booking_confirmation (flag): set to false only when the customer wants to change something after a booking summary.

- needs_child_ages (flag): true when children are mentioned and the service has age-based pricing.

- needs_escalation_email (flag): true when a WhatsApp escalation needs the customer's email before proceeding.

- large_group (flag): true when the guest count meets or exceeds the large group threshold in booking_rules.

- semi_escalation: true only when the customer asks a specific unanswerable factual question (crew-confirmable details, equipment specs, allergy cross-contamination) — NOT for complaints, refunds, or cancellations (those use requires_human).

- relay_question: the exact question to relay to the human team — only populate when semi_escalation is true.

- requires_human: true if complaint with no booking context, or explicit request to speak to a human.

- internal_note: one sentence for the operator log — never shown to the customer.

SERVICE ALIASES: When populating the service_key field in your tool call, use the exact key from this mapping. Match the customer's wording to the closest key:

{_build_service_alias_text()}

Only include service_key if you're certain. If the customer's description is ambiguous, omit it and ask."""


def _build_user_prompt(
    from_email: str,
    subject: str,
    body: str,
    thread_fields: dict,
    thread_flags: dict,
    action_context: str = "",
    channel: str = "email",
    messages: list = None,
) -> str:
    """Build the user prompt: business data, thread context, inbound message."""
    today = datetime.now(_CURACAO_TZ).strftime("%Y-%m-%d")
    csk = config_loader.get_common_sense_knowledge()
    client_context = _build_client_context()

    returning_customer_section = ""
    if thread_flags.get("returning_booking"):
        returning_customer_section = (
            f"\nRETURNING CUSTOMER: This customer referenced booking {thread_flags['returning_booking']}. "
            f"Their booking details are pre-loaded in the Fields above. "
            f"They may want to: check status, change their date, ask a follow-up question, or report an issue. "
            f"Handle naturally based on their message. For refunds or cancellations: set requires_human to true.\n"
        )

    unknown_ref_section = ""
    if thread_flags.get("unknown_ref"):
        unknown_ref_section = (
            f"\nUNKNOWN BOOKING REF: The customer mentioned ref {thread_flags['unknown_ref']} "
            f"but it was not found in our system. Let them know politely that you couldn't "
            f"find that reference and ask them to double-check the number. If they want to "
            f"make a new booking, help them normally.\n"
        )

    completed_bookings_section = ""
    completed = thread_flags.get("_completed_bookings_summary", "")
    if completed:
        completed_bookings_section = (
            f"\nCOMPLETED BOOKINGS IN THIS THREAD:\n{completed}\n"
            f"The customer may want to book another trip. Start fresh intake "
            f"for the new booking — do not reference or modify completed bookings.\n"
        )

    past_customer_bookings_section = ""
    if thread_flags.get("_past_customer_bookings"):
        past_customer_bookings_section = (
            f"\nRETURNING CUSTOMER (by email): This customer has previous bookings:\n"
            f"{thread_flags['_past_customer_bookings']}\n"
            f"Acknowledge them warmly as a returning customer. If they're booking again, "
            f"their name and phone may already be on file — check the fields above.\n"
        )

    max_bookings_section = ""
    if thread_flags.get("_max_bookings_reached"):
        max_bookings_section = (
            "\nMAX BOOKINGS REACHED: This customer has reached the maximum number of "
            "bookings per conversation. Politely let them know they can email again "
            "to book additional trips. Do not start a new booking intake.\n"
        )

    # Build conversation history section for WhatsApp
    history_section = ""
    if channel == "whatsapp":
        if messages:
            history_lines = []
            for m in messages:
                role_label = "Customer" if m.get("role") == "user" else config_loader.get_business().get("agent_name", "CSA")
                history_lines.append(f"  {role_label}: {m.get('text', '')}")
            history_section = (
                "CONVERSATION HISTORY (recent messages):\n"
                + "\n".join(history_lines) + "\n\n"
            )
        else:
            history_section = "CONVERSATION HISTORY (recent messages):\n  (new conversation)\n\n"

    # Build inbound message section
    if channel == "whatsapp":
        inbound_section = (
            f"INBOUND MESSAGE:\n"
            f"  From: {from_email}\n"
            f"  Text: {body}"
        )
    else:
        inbound_section = (
            f"INBOUND MESSAGE:\n"
            f"  From: {from_email}\n"
            f"  Subject: {subject}\n"
            f"  Body: {body}"
        )

    return f"""{returning_customer_section}{unknown_ref_section}{completed_bookings_section}{past_customer_bookings_section}{max_bookings_section}
TODAY (Curaçao time): {today}
TIMEZONE: {csk.get('curacao_timezone', 'America/Curacao (UTC-4, no DST)')}
CURRENCY: {csk.get('currency', 'USD')}

CLIENT DATA (source of truth for all customer-facing information):
{client_context}

{action_context}

THREAD CONTEXT (already collected this conversation):
  Fields: {json.dumps(thread_fields, ensure_ascii=False)}
  Flags: {json.dumps(thread_flags, ensure_ascii=False)}

{history_section}{inbound_section}"""


def _build_prompt(
    from_email: str,
    subject: str,
    body: str,
    thread_fields: dict,
    thread_flags: dict,
    action_context: str = "",
    channel: str = "email",
    messages: list = None,
) -> str:
    """Backward-compatible wrapper: returns full prompt (system + user combined).
    Used by tests. process_message() uses the split functions directly."""
    return (
        _build_system_prompt(thread_flags, channel=channel) + "\n\n" +
        _build_user_prompt(from_email, subject, body, thread_fields, thread_flags,
                           action_context, channel=channel, messages=messages)
    )


def _build_contextual_fallback_reply(
    thread_fields: dict,
    channel: str,
    signature: str,
    svc_label: str,
    party_label: str,
) -> str:
    """Brief 176: construct the fallback reply based on what Marina already knows
    about this customer from the current thread state. Used ONLY on API-level
    failures (timeout, rate limit, Anthropic outage, defensive guard) — not in
    the normal Claude-succeeds path. Rule 3 accepted exception (documented in
    CLAUDE.md KNOWN OPEN ISSUES).

    Principles:
    - Acknowledge the hiccup (not the customer's fault)
    - Use the customer's name when known
    - Only ask for missing fields (service / date / guests)
    - WhatsApp stays under 40 words; email can be slightly longer
    - If all fields present, acknowledge the full context and ask the customer
      to resend their last message (the one that triggered the fallback)
    """
    fields = thread_fields or {}
    name = (fields.get("customer_name") or "").strip()
    guests = fields.get("guests")
    service = (fields.get("service_name") or "").strip()
    date = (fields.get("date") or "").strip()

    has_name = bool(name)
    has_guests = bool(guests)
    has_service = bool(service)
    has_date = bool(date)

    known_parts = []
    if has_guests and has_service:
        known_parts.append(f"you as a group of {guests} for {service}")
    elif has_guests:
        known_parts.append(f"you as a group of {guests}")
    elif has_service:
        known_parts.append(f"the {service} booking")
    if has_date:
        if known_parts:
            known_parts[-1] = known_parts[-1] + f" on {date}"
        else:
            known_parts.append(f"a booking for {date}")
    known_str = " and ".join(known_parts)

    missing_parts = []
    if not has_service:
        missing_parts.append(f"which {svc_label} you're looking at")
    if not has_date:
        missing_parts.append("what date works")
    if not has_guests:
        missing_parts.append(f"how many {party_label}")
    missing_str = " and ".join(missing_parts)

    name_prefix = f"{name}, " if has_name else ""

    if channel == "whatsapp":
        if not known_parts and not missing_parts:
            return f"Sorry{', ' + name if has_name else ''}, had a brief hiccup. Could you resend your last message?"
        if not missing_parts:
            return f"Sorry {name_prefix}had a brief hiccup. I have {known_str} on file — could you resend your last message?"
        if not known_parts:
            return f"Sorry {name_prefix}had a hiccup. Could you let me know {missing_str}?"
        return f"Sorry {name_prefix}had a hiccup. I've got {known_str} — could you remind me {missing_str}?"

    signoff = f"\n\nWarm regards,\n{signature}"
    if not known_parts and not missing_parts:
        return (
            f"Hi{' ' + name if has_name else ''},\n\n"
            f"Sorry, I had a brief hiccup on my end — could you resend your "
            f"last message and I'll get right back to you?{signoff}"
        )
    if not missing_parts:
        return (
            f"Hi{' ' + name if has_name else ''},\n\n"
            f"Sorry, I had a brief hiccup on my end. I have {known_str} on "
            f"file — could you resend your last message so I can pick up "
            f"where we left off?{signoff}"
        )
    if not known_parts:
        return (
            f"Hi{' ' + name if has_name else ''}! Could you let me know "
            f"{missing_str}? I'll get you sorted from there.{signoff}"
        )
    return (
        f"Hi {name_prefix}sorry for the brief hiccup on my end. I have "
        f"{known_str} — could you remind me {missing_str}?{signoff}"
    )


def process_message(
    from_email: str,
    subject: str,
    body: str,
    thread_fields: dict,
    thread_flags: dict,
    action_context: str = "",
    channel: str = "email",
    messages: list = None,
    customer_file=None,
) -> dict:
    signature = config_loader.get_agent_signature()

    _terminology = config_loader.get_raw().get("terminology", {})
    _svc_label = _terminology.get("service_label", "service")
    _party_label = _terminology.get("party_size_label", "guests")

    # Brief 176: context-aware fallback — acknowledges what thread_fields
    # already contains instead of gaslighting returning customers with a
    # generic first-contact reply. Rule 3 accepted exception (API failure
    # path only). See _build_contextual_fallback_reply docstring.
    _fallback_reply = _build_contextual_fallback_reply(
        thread_fields=thread_fields,
        channel=channel,
        signature=signature,
        svc_label=_svc_label,
        party_label=_party_label,
    )
    fallback = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "low",
        "reply": _fallback_reply,
        "clarifications_needed": ["date", _party_label, "service_name"],
        "requires_human": False,
        "flags": {},
        "internal_note": "Fallback response — Claude API call failed or returned unparseable output.",
    }

    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        client = anthropic.Anthropic(api_key=api_key)
        system_prompt = _build_system_prompt(thread_flags, channel=channel, customer_file=customer_file)
        user_prompt = _build_user_prompt(from_email, subject, body, thread_fields, thread_flags,
                                          action_context, channel=channel, messages=messages)

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            tools=[MARINA_TOOL],
            tool_choice={"type": "tool", "name": "marina_response"},
            messages=[{"role": "user", "content": user_prompt}],
        )

        # Log API token usage
        _usage = getattr(response, "usage", None)
        if _usage:
            bm_logger.log("api_usage",
                input_tokens=_usage.input_tokens,
                output_tokens=_usage.output_tokens,
                model="claude-sonnet-4-6",
                channel=channel,
                from_id=from_email[:50])

        # Brief 174: tool_choice forces Claude to emit a single tool_use block.
        # Extract its input — already a dict, no parsing needed.
        tool_use_block = next(
            (b for b in response.content if b.type == "tool_use"),
            None,
        )
        if tool_use_block is None:
            # Should be impossible with forced tool_choice, but guard anyway.
            bm_logger.log("claude_no_tool_use_block",
                          content_types=[b.type for b in response.content],
                          channel=channel, from_id=from_email[:50])
            return fallback
        result = dict(tool_use_block.input)

        # Default missing fields instead of rejecting the entire response
        for field, default in _RESPONSE_DEFAULTS.items():
            if field not in result:
                result[field] = default
                bm_logger.log("claude_field_defaulted", field=field,
                              channel=channel, from_id=from_email[:50])

        # If reply is empty after defaults, fall back (preserves email fallback reply)
        if not result.get("reply"):
            bm_logger.log("claude_empty_reply",
                          intents=result.get("intents", []),
                          channel=channel, from_id=from_email[:50],
                          input_preview=str(result)[:200])
            return fallback

        # Brief 224: sanitize customer-facing text fields before returning.
        result["reply"] = _strip_internal_tokens(result.get("reply", ""))
        if result.get("reply_hold_failed"):
            result["reply_hold_failed"] = _strip_internal_tokens(result["reply_hold_failed"])

        return result

    except Exception as _exc:
        bm_logger.log("claude_api_error",
                      error=str(_exc)[:200],
                      channel=channel, from_id=from_email[:50])
        return fallback
