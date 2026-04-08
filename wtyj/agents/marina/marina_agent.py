# bluemarlin/agents/marina/marina_agent.py
# Last modified: Brief 131b
# Purpose: Single Claude call per message. Returns structured JSON.

import json
import os
import re
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


def _build_system_prompt(thread_flags: dict, channel: str = "email") -> str:
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
        "do not count. Read the body text only. Only fall back to English if "
        "the body is actually in English or is too short to identify (e.g. just "
        '"ok" or "yes" — use the language from the previous turn).'
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
            "\"All set! Ref [BOOKING_REF], here's your payment link: [PAYMENT_LINK]\n\n"
            "See you Saturday!\"\n"
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
            f"Booking confirmation:\n"
            f"\"You're all set! Your booking reference is [BOOKING_REF]. Here's your\n"
            f"payment link: [PAYMENT_LINK]. See you Saturday! 🎉\"\n"
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

    return f"""You are {business.get('agent_name', 'Marina')}, the booking agent for {business.get('name', 'the business')}.
{relay_mode_section}{fully_escalated_section}
AGENT PERSONA:
{_build_agent_persona_block()}

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

Respond with ONLY a JSON object. No explanation. No markdown. No code fences. Just the JSON.

The JSON must have ALL of these fields, even if empty (use {{}} for objects, [] for arrays, "" for strings, false for booleans):
{{
  "intents": ["<one or more of: booking, inquiry, cancellation, reschedule, complaint, social, off_topic>"],
  "fields": {{"<extracted booking fields — only if present and certain:
    service_name: the service name as the customer described it
    date: MUST be in YYYY-MM-DD format. You must convert any natural
      language date (e.g. "April 20", "next Saturday", "in two weeks")
      to YYYY-MM-DD using today's date as reference. If the customer
      has given a vague or unresolvable date (e.g. "sometime next
      month", "in the summer", "soon") you MUST omit this field and
      ask for a specific date in clarifications_needed. Never infer,
      guess, or pick a date the customer has not explicitly stated or
      clearly implied. When in doubt, ask.
      If the customer explicitly rejects or cancels a previously stated date
      (e.g. "nvm the 28th", "not that date", "change the date"), you MUST
      set date to "" (empty string) so the old date is cleared. Then ask
      for a specific new date in clarifications_needed.
    guests: exact integer ONLY when the customer explicitly states a number.
      "We", "us", "our family" without a number does NOT count — omit this
      field entirely. Never infer a guest count from context or business rules.
    customer_name: customer's name
    phone: customer's phone number
    email: customer's email address — only if explicitly provided
    special_requests: forward-looking preferences only
    service_key: exact key from the trips list. Match the customer's wording to one of these keys:
{_build_service_alias_text()}
      Only include service_key if certain. If the customer's description is ambiguous, omit it and ask.
    slot_time: the specific departure time the customer has chosen, in HH:MM format — only include if the customer has explicitly selected one from the available options>"}},
  "confidence": "<high | medium | low>",
  "reply": "<your reply to the customer, written naturally as a real person would. Follow any ACTION instruction. When no ACTION is given, reply conversationally.>",
  "reply_hold_failed": "<optional — write ONLY when setting booking_confirmed to true. Apologetic message if the slot is unavailable, without [PAYMENT_LINK].>",
  "clarifications_needed": ["<questions Marina still needs answered before proceeding>"],
  "requires_human": <true if complaint with no booking context, or explicit request to speak to a human — otherwise false>,
  "flags": {{"booking_confirmed": <true ONLY after the customer explicitly confirms a booking summary they were shown (e.g. "yes", "go ahead", "book it") — NEVER on the initial booking request, even if all details are provided — omit or false otherwise>, "awaiting_booking_confirmation": <set to false only when the customer wants to change something after a booking summary — omit otherwise>, "needs_child_ages": <true when children are mentioned and the service has age-based pricing — omit or false otherwise>, "needs_escalation_email": <true when a WhatsApp escalation needs the customer's email before proceeding — omit or false otherwise>, "large_group": <true when the guest count meets or exceeds the large group threshold — omit or false otherwise>}},
  "semi_escalation": <true only when the customer asks a specific unanswerable question — NOT for complaints or cancellations — omit or false otherwise>,
  "relay_question": "<exact question to relay to the human team — only present when semi_escalation is true — omit otherwise>",
  "internal_note": "<one sentence for the operator log — never shown to the customer>"
}}"""


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
                role_label = "Customer" if m.get("role") == "user" else "Marina"
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


def process_message(
    from_email: str,
    subject: str,
    body: str,
    thread_fields: dict,
    thread_flags: dict,
    action_context: str = "",
    channel: str = "email",
    messages: list = None,
) -> dict:
    signature = config_loader.get_agent_signature()

    _terminology = config_loader.get_raw().get("terminology", {})
    _svc_label = _terminology.get("service_label", "service")
    _party_label = _terminology.get("party_size_label", "guests")

    fallback = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "low",
        "reply": (
            f"Hi! Could you let me know which {_svc_label} you're looking at, "
            f"what date works, and how many {_party_label}? I'll get you sorted "
            f"from there.\n\n"
            f"Warm regards,\n{signature}"
        ),
        "clarifications_needed": ["date", _party_label, "service_name"],
        "requires_human": False,
        "flags": {},
        "internal_note": "Fallback response — Claude API call failed or returned unparseable output.",
    }
    if channel == "whatsapp":
        # ⚠️  HARDCODED FALLBACK — Rule 3 accepted exception (API failure path only)
        # If agent name changes from "Marina", update this message.
        # See also: email fallback above (lines 459-473) — same exception.
        fallback["reply"] = "Sorry, could you send that again? I missed it."

    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        client = anthropic.Anthropic(api_key=api_key)
        system_prompt = _build_system_prompt(thread_flags, channel=channel)
        user_prompt = _build_user_prompt(from_email, subject, body, thread_fields, thread_flags,
                                          action_context, channel=channel, messages=messages)

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()

        # Log API token usage
        _usage = getattr(response, "usage", None)
        if _usage:
            bm_logger.log("api_usage",
                input_tokens=_usage.input_tokens,
                output_tokens=_usage.output_tokens,
                model="claude-sonnet-4-6",
                channel=channel,
                from_id=from_email[:50])

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw.strip())

        result = json.loads(raw)

        if not isinstance(result, dict):
            bm_logger.log("claude_response_invalid", reason="not_a_dict",
                          raw_preview=raw[:200], channel=channel, from_id=from_email[:50])
            return fallback

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
                          raw_preview=raw[:300])
            return fallback

        return result

    except Exception as _exc:
        bm_logger.log("claude_api_error",
                      error=str(_exc)[:200],
                      channel=channel, from_id=from_email[:50])
        return fallback
