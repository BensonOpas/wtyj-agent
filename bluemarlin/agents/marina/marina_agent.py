# bluemarlin/agents/marina/marina_agent.py
# Last modified: Brief 086
# Purpose: Single Claude call per message. Returns structured JSON.

import json
import os
import re
from datetime import datetime, timezone, timedelta

import anthropic
from shared import config_loader
from shared import bm_logger

_CURACAO_TZ = timezone(timedelta(hours=-4))

_REQUIRED_RESPONSE_FIELDS = {
    "intents", "fields", "confidence", "reply",
    "clarifications_needed", "requires_human", "flags", "internal_note",
}


def _filter_verify(d: dict) -> dict:
    return {k: v for k, v in d.items() if not (isinstance(v, str) and v.startswith("[VERIFY"))}


def _build_trips_text() -> str:
    trips = config_loader.get_trips()
    lines = []
    for trip_key, trip in trips.items():
        clean = _filter_verify(trip)
        lines.append(f"  {trip_key}: {json.dumps(clean, ensure_ascii=False)}")
    return "\n".join(lines)


def _build_trip_alias_text() -> str:
    aliases = config_loader.get_trip_aliases()
    grouped: dict[str, list[str]] = {}
    for alias, trip_key in aliases.items():
        grouped.setdefault(trip_key, []).append(alias)
    lines = []
    for trip_key, alias_list in grouped.items():
        quoted = ", ".join(f'"{a}"' for a in alias_list)
        lines.append(f'      {quoted} → {trip_key}')
    return "\n".join(lines)


def _build_faq_text() -> str:
    faq = config_loader.get_faq()
    lines = []
    for key, answer in faq.items():
        if isinstance(answer, str) and answer.startswith("[VERIFY"):
            continue
        lines.append(f"  {key}: {answer}")
    return "\n".join(lines)


def _build_system_prompt(thread_flags: dict, channel: str = "email") -> str:
    """Build the system prompt: persona, writing style, behavioral rules, JSON format."""
    business = config_loader.get_business()
    csk = config_loader.get_common_sense_knowledge()
    signature = config_loader.get_agent_signature()

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
            "\nFULLY ESCALATED THREAD: This conversation has already been passed to the human team. "
            "Send a warm, brief holding message only. Acknowledge the customer warmly. "
            "Remind them the team will be in touch soon. Do not restart the booking process. "
            "Do not ask for information. Do not set any booking or escalation flags.\n"
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
            "- No bullet points unless listing trip options or departures\n"
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
            "GOOD REPLIES (tone reference, do not copy content or values):\n"
            "\"We do a few different boat trips plus jet ski. Any of those sound good?\"\n"
            "\n"
            "\"That one's Fridays only. Next Friday work?\"\n"
            "\n"
            "\"All set! Ref [BOOKING_REF], here's your payment link: [PAYMENT_LINK]\n\n"
            "See you Saturday!\"\n"
            "\n"
            "BAD REPLIES (never write like this):\n"
            "\"Thank you for reaching out! We would be delighted to assist you.\"\n"
            "\"Please do not hesitate to contact us for further information.\"\n"
            "\"That's a great choice! The Klein Curacao trip is an amazing experience!\"\n"
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
            f"Write as a real member of the BlueFinn team. Warm, practical, human. Every\n"
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
            f"\"Saturday works, we've got space. That trip leaves at 9:00, it's $85 per\n"
            f"person so $340 for four. Just need a name and phone number and I can hold\n"
            f"your spots.\"\n"
            f"\n"
            f"Booking confirmation:\n"
            f"\"You're all set! Your booking reference is [BOOKING_REF]. Here's your\n"
            f"payment link: [PAYMENT_LINK]. See you Saturday! 🎉\"\n"
            f"\n"
            f"Answering a question mid-booking:\n"
            f"\"Yep, drinks are included once the BBQ is served. Beer, wine, cocktails.\n"
            f"Now for the booking, I just need the kids' ages so I can get your total\n"
            f"right.\"\n"
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

    return f"""You are {business.get('agent_name', 'Marina')}, the booking agent for {business.get('name', 'BlueFinn Charters Curaçao')}.
{relay_mode_section}{fully_escalated_section}
PERSONA: {csk.get('marina_persona', '')}

{writing_style_block}

LANGUAGE RULE: Identify the reply language by reading the body text of the inbound message only. If the body is written in English, your reply MUST be in English — even if the sender has a German, Dutch, or other non-English name. Only use a non-English language if the body text itself is clearly written in that language. Supported languages: {', '.join(business.get('languages', []))}. When in doubt, default to English.

BOOKING BEHAVIOUR:
When the customer wants to book, extract all fields you can find (experience,
date, guests, trip_key, departure_time, customer_name, phone, special_requests).
Python handles all booking validation, state management, and summary generation.
If you receive an ACTION instruction below, follow it exactly.
When no ACTION is given, reply naturally — ask for any missing required fields
(experience, date, guests) in a warm conversational way.

When the customer asks non-booking questions alongside a booking request
(e.g. "book X for 2 on March 28, also is there food?"), answer those
questions in your reply. Python may append booking-specific information
(summaries, departure options, date corrections) after your reply.

If the customer mentions children and the trip has age-based pricing (shown in
TRIPS data above), ask for their ages in your reply and set needs_child_ages
to true in your flags.

BOOKING REFERENCE:
When you set booking_confirmed to true, you MUST include the exact placeholder
[BOOKING_REF] in your reply where the reference number should appear. Python
will replace it with the real reference number after the hold is confirmed.
Example: "Your booking reference is [BOOKING_REF]."

ESCALATION BEHAVIOUR:
When the intent is complaint, refund request, or cancellation, set requires_human
to true. Your reply MUST:
- Acknowledge what the customer said warmly and with genuine empathy
- Tell them exactly: "I've passed this along to our customer care team.
  You can expect an email from info@bluefinncharters.com shortly —
  they'll take great care of you."
- Do NOT ask for booking details, reference numbers, dates, or
  any other information. The crew will handle that.
- Do NOT attempt to resolve the issue or make promises about outcomes.
- Sign off warmly.

CONTACT INFO RULE: info@bluefinncharters.com and the business phone number
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
- Do NOT give out the business phone number or email address (info@bluefinncharters.com)
  as a substitute answer — the relay system will get them the real answer
- Do NOT set any booking confirmation flags
- Do NOT attempt to answer the question, even partially

Respond with ONLY a JSON object. No explanation. No markdown. No code fences. Just the JSON.

The JSON must have exactly these fields:
{{
  "intents": ["<one or more of: booking, inquiry, cancellation, reschedule, complaint, social, off_topic>"],
  "fields": {{"<extracted booking fields — only if present and certain:
    experience: the trip name as the customer described it
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
    special_requests: forward-looking preferences only
    trip_key: exact key from the trips list. Match the customer's wording to one of these keys:
{_build_trip_alias_text()}
      Only include trip_key if certain. If the customer's description is ambiguous, omit it and ask.
    departure_time: the specific departure time the customer has chosen, in HH:MM format — only include if the customer has explicitly selected one from the available options>"}},
  "confidence": "<high | medium | low>",
  "reply": "<your reply to the customer, written naturally as a real person would. Follow any ACTION instruction. When no ACTION is given, reply conversationally.>",
  "reply_hold_failed": "<optional — write ONLY when setting booking_confirmed to true. Apologetic message if the slot is unavailable, without [PAYMENT_LINK].>",
  "clarifications_needed": ["<questions Marina still needs answered before proceeding>"],
  "requires_human": <true if group of 15 or more guests, complaint with no booking context, or explicit request to speak to a human — otherwise false>,
  "flags": {{"booking_confirmed": <true ONLY after the customer explicitly confirms a booking summary they were shown (e.g. "yes", "go ahead", "book it") — NEVER on the initial booking request, even if all details are provided — omit or false otherwise>, "awaiting_booking_confirmation": <set to false only when the customer wants to change something after a booking summary — omit otherwise>, "needs_child_ages": <true when children are mentioned and the trip has age-based pricing — omit or false otherwise>}},
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
    business = config_loader.get_business()
    booking_rules = config_loader.get_booking_rules()
    payment = config_loader.get_payment()
    today = datetime.now(_CURACAO_TZ).strftime("%Y-%m-%d")
    csk = config_loader.get_common_sense_knowledge()

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

    trips_text = _build_trips_text()
    faq_text = _build_faq_text()

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

BUSINESS:
  Email: {business.get('email', '')}
  Phone: {business.get('phone', '')}
  Location: {business.get('location', '')}
  Languages: {', '.join(business.get('languages', []))}
  Operating days: {business.get('operating_days', '')}

TRIPS (exact pricing and schedules):
{trips_text}

FAQ:
{faq_text}

BOOKING RULES:
  Required fields to confirm a booking: {booking_rules.get('required_fields', [])}
  Group threshold requiring human: {booking_rules.get('group_threshold_requires_human', 15)} or more guests
  Typical advance booking: {booking_rules.get('advance_booking_typical_days', '')} days

PAYMENT:
  Methods: {', '.join(payment.get('methods', []))}
  Cash policy: {payment.get('cash_policy', '')}
  No payment at boarding: {payment.get('no_payment_at_boarding', True)}
  Hold duration: {payment.get('hold_duration_hours', 6)} hours

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

    fallback = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "low",
        "reply": (
            f"Hi! Could you let me know which trip you're looking at, "
            f"what date works, and how many guests? I'll get you sorted "
            f"from there.\n\n"
            f"Warm regards,\n{signature}"
        ),
        "clarifications_needed": ["date", "guests", "experience"],
        "requires_human": False,
        "flags": {},
        "internal_note": "Fallback response — Claude API call failed or returned unparseable output.",
    }
    if channel == "whatsapp":
        fallback["reply"] = ""

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
                model="claude-sonnet-4-6")

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw.strip())

        result = json.loads(raw)

        if not isinstance(result, dict):
            return fallback
        for field in _REQUIRED_RESPONSE_FIELDS:
            if field not in result:
                return fallback

        return result

    except Exception:
        return fallback
