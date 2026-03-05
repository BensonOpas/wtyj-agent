# FILE: marina_agent.py
# CREATED: Brief 023
# LAST MODIFIED: Brief 027
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
) -> str:
    business = config_loader.get_business()
    booking_rules = config_loader.get_booking_rules()
    payment = config_loader.get_payment()
    csk = config_loader.get_common_sense_knowledge()
    today = datetime.now(_CURACAO_TZ).strftime("%Y-%m-%d")
    signature = config_loader.get_agent_signature()

    trips_text = _build_trips_text()
    faq_text = _build_faq_text()

    return f"""You are {business.get('agent_name', 'Marina')}, the booking agent for {business.get('name', 'BlueFinn Charters Curaçao')}.

PERSONA: {csk.get('marina_persona', '')}
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
    date: MUST be in YYYY-MM-DD format. Convert any natural language date to YYYY-MM-DD before including. If you cannot resolve it to a specific YYYY-MM-DD date, omit this field entirely and include a clarification question in clarifications_needed instead.
    guests: exact integer only
    customer_name: customer's name
    phone: customer's phone number
    special_requests: forward-looking preferences only
    trip_key: exact key from the trips list — one of klein_curacao, snorkeling_3in1, west_coast_beach, sunset_cruise, jet_ski — only include if certain
    departure_time: the specific departure time the customer has chosen, in HH:MM format — only include if the customer has explicitly selected one from the available options>"}},
  "confidence": "<high | medium | low>",
  "reply": "<full reply to send to the customer — warm, natural, signed with agent signature — never a template, never robotic>",
  "clarifications_needed": ["<questions Marina still needs answered before proceeding>"],
  "requires_human": <true if group of 15 or more guests, complaint with no booking context, or explicit request to speak to a human — otherwise false>,
  "flags": {{"<conversation state flags for Python to persist into thread_flags>"}},
  "internal_note": "<one sentence for the operator log — never shown to the customer>"
}}"""


def process_message(
    from_email: str,
    subject: str,
    body: str,
    thread_fields: dict,
    thread_flags: dict,
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
        prompt = _build_prompt(from_email, subject, body, thread_fields, thread_flags)

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
