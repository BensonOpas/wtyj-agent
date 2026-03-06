# FILE: marina_agent.py
# CREATED: Brief 023
# LAST MODIFIED: Brief 031
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

BOOKING CONFIRMATION BEHAVIOUR:
When your fields response contains all four required booking fields
(experience, date, guests, trip_key) — whether extracted from this
message or already in thread context — AND "awaiting_booking_confirmation"
is not true in thread flags AND "booking_confirmed" is not true in
thread flags, do NOT assume the booking is confirmed. Instead:
- Send a warm booking summary to the customer listing: trip name,
  date, number of guests, departure time (if chosen), total price,
  what is included.
- departure_time is NOT a required field. Do not wait for it before
  sending the summary. If not yet chosen, you may ask in the same
  message, but still send the summary and set the confirmation flag.
- End the summary with a single clear confirmation question:
  "Shall I lock this in for you?"
- In your JSON response, the "flags" field MUST contain:
  "awaiting_booking_confirmation": true
- Do NOT set any hold-related flags.

When "awaiting_booking_confirmation" is true in thread flags:
- If the customer's message is a confirmation (yes, sure, let's do
  it, perfect, go ahead, ja, si, or any equivalent in any language):
  In your JSON response, the "flags" field MUST contain:
  "booking_confirmed": true, "awaiting_booking_confirmation": false
  Reply briefly confirming you are locking it in.
- If the customer wants to change something: update the relevant
  field, reset awaiting_booking_confirmation to false, and continue
  the conversation naturally.
- If unclear: ask for clarification.

When writing the reply for a confirmed booking (booking_confirmed
is true and hold will be attempted), include the exact string
[PAYMENT_LINK] in the reply where the payment link should appear.
Python will replace [PAYMENT_LINK] with the real payment URL before
sending.

ESCALATION BEHAVIOUR:
When the intent is complaint or cancellation, set requires_human
to true. Your reply must:
- Acknowledge what the customer said warmly and with genuine empathy
- Tell them: "I've passed this to our Crew who will be in touch
  with you shortly."
- Do NOT ask for booking details, reference numbers, dates, or
  any other information. The Crew will handle that.
- Do NOT attempt to resolve the issue or make promises about
  outcomes.
- Sign off warmly.

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
    guests: exact integer only
    customer_name: customer's name
    phone: customer's phone number
    special_requests: forward-looking preferences only
    trip_key: exact key from the trips list — one of klein_curacao, snorkeling_3in1, west_coast_beach, sunset_cruise, jet_ski — only include if certain
    departure_time: the specific departure time the customer has chosen, in HH:MM format — only include if the customer has explicitly selected one from the available options>"}},
  "confidence": "<high | medium | low>",
  "reply": "<full reply to send when the booking hold is successfully created — warm, celebratory, includes the booking summary, payment link placeholder [PAYMENT_LINK], payment methods, hold duration, what to bring>",
  "reply_hold_failed": "<reply to send if the calendar slot is unavailable or hold creation fails — apologetic, warm, offers to find another date or time, does NOT confirm the booking, does NOT include a payment link. Write this field whenever awaiting_booking_confirmation is being set to true OR booking_confirmed is true in thread flags. Always write it alongside the summary reply so Python can choose the correct one based on actual availability.>",
  "clarifications_needed": ["<questions Marina still needs answered before proceeding>"],
  "requires_human": <true if group of 15 or more guests, complaint with no booking context, or explicit request to speak to a human — otherwise false>,
  "flags": {{"awaiting_booking_confirmation": <true when you are sending a booking summary asking the customer to confirm — omit or false otherwise>, "booking_confirmed": <true only when the customer has just confirmed in this message — omit or false otherwise>}},
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
