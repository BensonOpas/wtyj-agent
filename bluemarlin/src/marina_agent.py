# FILE: marina_agent.py
# CREATED: Brief 023
# LAST MODIFIED: Brief 048
# DEPENDS ON: claude_client.py (Brief 001), config_loader.py (Brief 022)
# IMPORTS FROM: config_loader.py (Brief 022)

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import anthropic

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader

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


def _build_faq_text() -> str:
    faq = config_loader.get_faq()
    lines = []
    for key, answer in faq.items():
        if isinstance(answer, str) and answer.startswith("[VERIFY"):
            continue
        lines.append(f"  {key}: {answer}")
    return "\n".join(lines)


def _build_prompt(
    from_email: str,
    subject: str,
    body: str,
    thread_fields: dict,
    thread_flags: dict,
    action_context: str = "",
) -> str:
    business = config_loader.get_business()
    booking_rules = config_loader.get_booking_rules()
    payment = config_loader.get_payment()
    csk = config_loader.get_common_sense_knowledge()
    today = datetime.now(_CURACAO_TZ).strftime("%Y-%m-%d")
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

    trips_text = _build_trips_text()
    faq_text = _build_faq_text()

    return f"""You are {business.get('agent_name', 'Marina')}, the booking agent for {business.get('name', 'BlueFinn Charters Curaçao')}.
{relay_mode_section}{fully_escalated_section}
PERSONA: {csk.get('marina_persona', '')}
LANGUAGE RULE: Identify the reply language by reading the body text of the inbound message only. If the body is written in English, your reply MUST be in English — even if the sender has a German, Dutch, or other non-English name. Only use a non-English language if the body text itself is clearly written in that language. Supported languages: {', '.join(business.get('languages', []))}. When in doubt, default to English.
AGENT SIGNATURE: {signature}
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

{action_context}

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

THREAD CONTEXT (already collected this conversation):
  Fields: {json.dumps(thread_fields, ensure_ascii=False)}
  Flags: {json.dumps(thread_flags, ensure_ascii=False)}

INBOUND MESSAGE:
  From: {from_email}
  Subject: {subject}
  Body: {body}

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
      "Klein Curaçao", "Klein", "island trip", "day trip", "turtle trip" → klein_curacao
      "snorkeling", "snorkel", "3-in-1", "3 in 1", "snorkeling trip" → snorkeling_3in1
      "west coast", "beach trip", "west coast beach" → west_coast_beach
      "sunset", "sunset cruise", "evening cruise", "evening trip" → sunset_cruise
      "jet ski", "jetski", "jet-ski" → jet_ski
      Only include trip_key if certain. If the customer's description is ambiguous, omit it and ask.
    departure_time: the specific departure time the customer has chosen, in HH:MM format — only include if the customer has explicitly selected one from the available options>"}},
  "confidence": "<high | medium | low>",
  "reply": "<your reply to the customer — warm and natural. Follow any ACTION instruction above. When no ACTION is given, reply conversationally.>",
  "reply_hold_failed": "<optional — write ONLY when setting booking_confirmed to true. Apologetic message if the slot is unavailable, without [PAYMENT_LINK].>",
  "clarifications_needed": ["<questions Marina still needs answered before proceeding>"],
  "requires_human": <true if group of 15 or more guests, complaint with no booking context, or explicit request to speak to a human — otherwise false>,
  "flags": {{"booking_confirmed": <true only when the customer has just confirmed a booking — omit or false otherwise>, "awaiting_booking_confirmation": <set to false only when the customer wants to change something after a booking summary — omit otherwise>, "needs_child_ages": <true when children are mentioned and the trip has age-based pricing — omit or false otherwise>}},
  "semi_escalation": <true only when the customer asks a specific unanswerable question — NOT for complaints or cancellations — omit or false otherwise>,
  "relay_question": "<exact question to relay to the human team — only present when semi_escalation is true — omit otherwise>",
  "internal_note": "<one sentence for the operator log — never shown to the customer>"
}}"""


def process_message(
    from_email: str,
    subject: str,
    body: str,
    thread_fields: dict,
    thread_flags: dict,
    action_context: str = "",
) -> dict:
    signature = config_loader.get_agent_signature()

    fallback = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "low",
        "reply": (
            f"Hi there!\n\nThank you for getting in touch. To help you out, "
            f"could you let me know your preferred date, the number of guests, "
            f"and which experience you are interested in?\n\n"
            f"Warm regards,\n{signature}"
        ),
        "clarifications_needed": ["date", "guests", "experience"],
        "requires_human": False,
        "flags": {},
        "internal_note": "Fallback response — Claude API call failed or returned unparseable output.",
    }

    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        client = anthropic.Anthropic(api_key=api_key)
        prompt = _build_prompt(from_email, subject, body, thread_fields, thread_flags, action_context)

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

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
