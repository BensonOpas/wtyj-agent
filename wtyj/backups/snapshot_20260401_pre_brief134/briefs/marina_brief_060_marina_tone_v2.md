# BRIEF 060 — Marina Tone v2: Python Templates + Claude Prompting
**Status:** Draft | **Files:** `src/marina_agent.py`, `src/email_poller.py`, `tests/test_marina_tone.py`, `tests/test_046_hybrid_state_machine.py`, `tests/test_047_reschedule_booking_flow.py`, `tests/test_048_human_speech_optimization.py`, `tests/test_038_prompt_fixes.py` | **Depends on:** Brief 059 | **Blocks:** —

## Context

Brief 059 added a WRITING STYLE section to the Claude prompt with banned phrases, banned AI habits, and a self-check. Live end-to-end testing on 2026-03-10 showed it did not work. Marina still sounds like an AI chatbot.

Two separate sources of AI-sounding output were identified:

1. **Python static templates** — `_build_booking_summary()` in email_poller.py generates bullet-point formatted booking summaries ending with "Shall I lock this in for you?" that REPLACE Claude's reply entirely. `_post_validate()` and slot-unavailable paths also contain hardcoded AI-sounding templates ("Great choice! Unfortunately...", "Almost there!", "Oh no —").

2. **Claude's own replies** — Despite Brief 059, Claude Sonnet still uses em dashes ("Got it —"), forced enthusiasm ("Amazing, let's lock it in! 🎉"), formulaic confirmations ("Shall I go ahead and confirm this?"), and reasoning out loud ("Perfect, twins at 3 means they're both under 4, so they sail free.").

## Why This Approach

Brief 059 relied entirely on negative instructions ("don't use em dashes", "avoid stock phrases"). Negative instructions are weak with LLMs. This brief takes a two-pronged approach: (A) rewrite the Python-generated text that Claude never touches, and (B) strengthen the Claude prompt with positive few-shot examples, a system/user message split, and condensed style directives. Few-shot examples are the single most reliable way to change LLM output tone. The system message split makes behavioral instructions more authoritative. The backward-compatible `_build_prompt()` wrapper preserves all 28 existing test calls.

Rule 4 tradeoff: The few-shot examples contain generic price/time values as tone references only. They are explicitly labeled "do not copy content or values" and Claude receives real business data from client.json via the user prompt. This is an accepted tradeoff — the examples exist to demonstrate writing style, not to convey business data.

## Source Material

### Current `_build_booking_summary()` output (email_poller.py lines 336-345)
```
Here's a quick summary of your booking:

  Trip: Sunset Cruise
  Date: Wednesday, 26 March 2026
  Guests: 2
  Departure: 17:30 from Village Marina aboard Kailani
  Total: $158 USD (2 x $79)
  Included: open bar, snacks

Shall I lock this in for you?
```

### Current `_post_validate()` messages (email_poller.py)
- Day-of-week (line 390): `"Great choice! Unfortunately, the {trip} doesn't run on {day}s — it runs {days_avail}."`
- Departure options (line 405): `"Almost there! The {trip} has a couple of departure options:"`
- Slot unavailable (lines 745, 756): `"Oh no — it looks like the {name} on that date is fully booked!"`

### Current `_suggest_dates()` format (line 310)
```
- Friday, 14 March 2026
- Friday, 21 March 2026
```

### Current WRITING STYLE in marina_agent.py (lines 116-165)
50 lines of mostly negative instructions: banned phrases, banned habits, self-check. No positive examples.

### Current API call (marina_agent.py line 345-349)
```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=2048,
    messages=[{"role": "user", "content": prompt}],
)
```
All prompt content in a single `user` message. No `system` parameter.

### Current fallback reply (marina_agent.py lines 328-333)
```python
f"Hi there!\n\nThank you for getting in touch. To help you out, "
f"could you let me know your preferred date, the number of guests, "
f"and which experience you are interested in?\n\n"
f"Warm regards,\n{signature}"
```

### Test assertions that reference "Shall I lock this in"
- `test_046_hybrid_state_machine.py` lines 57, 85
- `test_047_reschedule_booking_flow.py` lines 32, 43
- `test_048_human_speech_optimization.py` lines 41, 91, 100
- `test_038_prompt_fixes.py` line 68 (`lock_phrases` list)

## Instructions

### Part A — Rewrite Python templates (`src/email_poller.py`)

#### Step A1. Update file header
Change `# LAST MODIFIED: Brief 058` → `# LAST MODIFIED: Brief 060`

#### Step A2. Rewrite `_build_booking_summary()` (lines 336-345)
Replace the return statement only. Keep all data extraction logic (lines 316-335) unchanged.

Replace:
```python
    return (
        f"Here's a quick summary of your booking:\n\n"
        f"  Trip: {trip_name}\n"
        f"  Date: {date_fmt}\n"
        f"  Guests: {guests}\n"
        f"  Departure: {departure_time} from {dep_point} aboard {vessel}\n"
        f"  Total: ${total} USD ({guests} x ${price_adult})\n"
        f"  Included: {included}\n\n"
        f"Shall I lock this in for you?"
    )
```

With:
```python
    return (
        f"Just to confirm the details: {trip_name} on {date_fmt}, "
        f"{departure_time} departure from {dep_point} on {vessel}. "
        f"{guests} guests, ${total} total (${price_adult} each). "
        f"Includes {included}.\n\n"
        f"Want me to go ahead and book this?"
    )
```

#### Step A3. Rewrite `_post_validate()` day-of-week message (lines 389-394)
Replace:
```python
            return (
                f"Great choice! Unfortunately, the {trip.get('display_name', fields['trip_key'])} "
                f"doesn't run on {day_name}s — it runs {days_avail}. "
                f"Would any of these dates work instead?\n\n"
                f"{_suggest_dates(date, days_avail)}"
            ), False
```

With:
```python
            return (
                f"The {trip.get('display_name', fields['trip_key'])} "
                f"doesn't run on {day_name}s, only {days_avail}. "
                f"Would any of these work instead?\n\n"
                f"{_suggest_dates(date, days_avail)}"
            ), False
```

#### Step A4. Rewrite `_post_validate()` departure options (lines 404-408)
Replace:
```python
        return (
            f"Almost there! The {trip.get('display_name', fields['trip_key'])} has "
            f"a couple of departure options:\n\n{dep_lines}\n\n"
            f"Which one works best for you?"
        ), False
```

With:
```python
        return (
            f"The {trip.get('display_name', fields['trip_key'])} has "
            f"a couple of departure times:\n\n{dep_lines}\n\n"
            f"Which one works for you?"
        ), False
```

#### Step A5. Rewrite slot unavailable messages (lines 744-748 and 754-758)
Both instances are identical. Replace each:
```python
                            reply_text = (
                                f"Oh no — it looks like the {_unavail_name} on that date "
                                f"is fully booked! Would you like to try a different date?\n\n"
                                f"Warm regards,\n{_unavail_sig}"
                            )
```

With:
```python
                            reply_text = (
                                f"Unfortunately the {_unavail_name} is fully booked on that date. "
                                f"Would you like to try a different date?\n\n"
                                f"Warm regards,\n{_unavail_sig}"
                            )
```

#### Step A6. Rewrite `_suggest_dates()` format (line 310)
Replace:
```python
            suggestions.append(f"- {candidate.strftime('%A, %d %B %Y')}")
```

With:
```python
            suggestions.append(f"  {candidate.strftime('%A %d %B')}")
```

### Part B — Strengthen Claude prompting (`src/marina_agent.py`)

#### Step B1. Update file header
Change `# LAST MODIFIED: Brief 059` → `# LAST MODIFIED: Brief 060`

#### Step B2. Create `_build_system_prompt()` function

Add this new function after `_build_faq_text()` (after line 46) and before `_build_prompt()`:

```python
def _build_system_prompt(thread_flags: dict) -> str:
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

    return f"""You are {business.get('agent_name', 'Marina')}, the booking agent for {business.get('name', 'BlueFinn Charters Curaçao')}.
{relay_mode_section}{fully_escalated_section}
PERSONA: {csk.get('marina_persona', '')}

WRITING STYLE:
Write as a real member of the BlueFinn team. Warm, practical, human. Every
email should read like it was typed by a real person during a real workday.

Mirror the sender's tone and length. Casual sender gets a casual reply.
Formal sender gets a direct, professional reply. Short question gets a
short answer.

Use contractions. Vary sentence length. Plain language. It is fine to start
with "So", "And", or "But". Do not reason out loud or explain your logic.

GOOD REPLY EXAMPLES (tone reference only, do not copy content or values):

Casual booking inquiry:
"Saturday works, we've got space. That trip leaves at 9:00, it's $85 per
person so $340 for four. Just need a name and phone number and I can hold
your spots."

Booking confirmation:
"You're all set! Your booking reference is [BOOKING_REF]. Here's your
payment link: [PAYMENT_LINK]. See you Saturday! 🎉"

Answering a question mid-booking:
"Yep, drinks are included once the BBQ is served. Beer, wine, cocktails.
Now for the booking, I just need the kids' ages so I can get your total
right."

AVOID: em dashes, en dashes, "Shall I", "I'd be happy to", "Great choice",
"Amazing", "Absolutely", decorative bold, bullet-heavy formatting, forced
enthusiasm, name-dropping at the end of sentences, reasoning out loud
("that means...", "so that would be...").

Emojis: only in booking confirmations. Otherwise, only if the sender used them first.

AGENT SIGNATURE: {signature}

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
      "Klein Curaçao", "Klein", "island trip", "day trip", "turtle trip" → klein_curacao
      "snorkeling", "snorkel", "3-in-1", "3 in 1", "snorkeling trip" → snorkeling_3in1
      "west coast", "beach trip", "west coast beach" → west_coast_beach
      "sunset", "sunset cruise", "evening cruise", "evening trip" → sunset_cruise
      "jet ski", "jetski", "jet-ski" → jet_ski
      Only include trip_key if certain. If the customer's description is ambiguous, omit it and ask.
    departure_time: the specific departure time the customer has chosen, in HH:MM format — only include if the customer has explicitly selected one from the available options>"}},
  "confidence": "<high | medium | low>",
  "reply": "<your reply to the customer, written naturally as a real person would. Follow any ACTION instruction. When no ACTION is given, reply conversationally.>",
  "reply_hold_failed": "<optional — write ONLY when setting booking_confirmed to true. Apologetic message if the slot is unavailable, without [PAYMENT_LINK].>",
  "clarifications_needed": ["<questions Marina still needs answered before proceeding>"],
  "requires_human": <true if group of 15 or more guests, complaint with no booking context, or explicit request to speak to a human — otherwise false>,
  "flags": {{"booking_confirmed": <true only when the customer has just confirmed a booking — omit or false otherwise>, "awaiting_booking_confirmation": <set to false only when the customer wants to change something after a booking summary — omit otherwise>, "needs_child_ages": <true when children are mentioned and the trip has age-based pricing — omit or false otherwise>}},
  "semi_escalation": <true only when the customer asks a specific unanswerable question — NOT for complaints or cancellations — omit or false otherwise>,
  "relay_question": "<exact question to relay to the human team — only present when semi_escalation is true — omit otherwise>",
  "internal_note": "<one sentence for the operator log — never shown to the customer>"
}}"""
```

#### Step B3. Create `_build_user_prompt()` function

Add this new function after `_build_system_prompt()` and before `_build_prompt()`:

```python
def _build_user_prompt(
    from_email: str,
    subject: str,
    body: str,
    thread_fields: dict,
    thread_flags: dict,
    action_context: str = "",
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

    completed_bookings_section = ""
    completed = thread_flags.get("_completed_bookings_summary", "")
    if completed:
        completed_bookings_section = (
            f"\nCOMPLETED BOOKINGS IN THIS THREAD:\n{completed}\n"
            f"The customer may want to book another trip. Start fresh intake "
            f"for the new booking — do not reference or modify completed bookings.\n"
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

    return f"""{returning_customer_section}{completed_bookings_section}{max_bookings_section}
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

INBOUND MESSAGE:
  From: {from_email}
  Subject: {subject}
  Body: {body}"""
```

#### Step B4. Rewrite `_build_prompt()` as backward-compatible wrapper

Replace the entire existing `_build_prompt()` function (lines 49-311) with:

```python
def _build_prompt(
    from_email: str,
    subject: str,
    body: str,
    thread_fields: dict,
    thread_flags: dict,
    action_context: str = "",
) -> str:
    """Backward-compatible wrapper: returns full prompt (system + user combined).
    Used by tests. process_message() uses the split functions directly."""
    return (
        _build_system_prompt(thread_flags) + "\n\n" +
        _build_user_prompt(from_email, subject, body, thread_fields, thread_flags, action_context)
    )
```

#### Step B5. Update `process_message()` to use split prompts

In `process_message()`, replace:
```python
        prompt = _build_prompt(from_email, subject, body, thread_fields, thread_flags, action_context)

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
```

With:
```python
        system_prompt = _build_system_prompt(thread_flags)
        user_prompt = _build_user_prompt(from_email, subject, body, thread_fields, thread_flags, action_context)

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
```

#### Step B6. Update fallback reply (lines 328-333)
Replace:
```python
        "reply": (
            f"Hi there!\n\nThank you for getting in touch. To help you out, "
            f"could you let me know your preferred date, the number of guests, "
            f"and which experience you are interested in?\n\n"
            f"Warm regards,\n{signature}"
        ),
```

With:
```python
        "reply": (
            f"Hi! Could you let me know which trip you're looking at, "
            f"what date works, and how many guests? I'll get you sorted "
            f"from there.\n\n"
            f"Warm regards,\n{signature}"
        ),
```

### Part C — Update existing tests

#### Step C1. `tests/test_046_hybrid_state_machine.py`
Line 57: Replace `"Shall I lock this in"` with `"Want me to go ahead and book this"`
Line 85: Replace `"Shall I lock this in"` with `"Want me to go ahead and book this"`

#### Step C2. `tests/test_047_reschedule_booking_flow.py`
Line 32: Replace `"Shall I lock this in"` with `"Want me to go ahead and book this"`
Line 43: Replace `"Shall I lock this in"` with `"Want me to go ahead and book this"`

#### Step C3. `tests/test_048_human_speech_optimization.py`
Line 41: Replace `"Shall I lock this in"` with `"Want me to go ahead and book this"`
Line 91: Replace `"Shall I lock this in"` with `"Want me to go ahead and book this"`
Line 100: Replace `"Shall I lock this in"` with `"Want me to go ahead and book this"`

#### Step C4. `tests/test_038_prompt_fixes.py`
Line 68: Replace:
```python
lock_phrases = ["shall i lock", "lock this in", "locking this in", "locking it in"]
```
With:
```python
lock_phrases = ["shall i lock", "lock this in", "locking this in", "locking it in", "go ahead and book"]
```

### Part D — Rewrite `tests/test_marina_tone.py`

Replace entire file with:

```python
# tests/test_marina_tone.py
# Brief 060 — Marina Tone v2

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import marina_agent
import config_loader
from email_poller import _build_booking_summary, _post_validate


def test_system_prompt_contains_writing_style():
    """System prompt has WRITING STYLE section."""
    sp = marina_agent._build_system_prompt({})
    assert "WRITING STYLE:" in sp


def test_system_prompt_contains_example_replies():
    """System prompt has few-shot tone examples."""
    sp = marina_agent._build_system_prompt({})
    assert "GOOD REPLY EXAMPLES" in sp
    assert "tone reference" in sp


def test_system_prompt_contains_json_format():
    """System prompt has the JSON response format."""
    sp = marina_agent._build_system_prompt({})
    assert '"intents"' in sp
    assert '"reply"' in sp


def test_user_prompt_contains_inbound_message():
    """User prompt has inbound message with body text."""
    up = marina_agent._build_user_prompt("a@b.com", "test subj", "hello body", {}, {})
    assert "INBOUND MESSAGE:" in up
    assert "hello body" in up


def test_user_prompt_contains_business_data():
    """User prompt has TRIPS and FAQ sections."""
    up = marina_agent._build_user_prompt("a@b.com", "test", "hi", {}, {})
    assert "TRIPS" in up
    assert "FAQ:" in up


def test_build_prompt_wrapper_combines_both():
    """Backward-compatible _build_prompt returns content from both system and user."""
    full = marina_agent._build_prompt("a@b.com", "test", "hi", {}, {})
    assert "WRITING STYLE:" in full
    assert "INBOUND MESSAGE:" in full
    assert "TRIPS" in full


def test_booking_summary_no_old_format():
    """Booking summary does not contain old bullet-point format."""
    trip = {"display_name": "Sunset Cruise", "departures": [{"time": "17:30", "vessel": "Kailani", "departure_point": "Village Marina"}], "price_adult_usd": 79, "included": ["open bar", "snacks"]}
    summary = _build_booking_summary({"trip_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "departure_time": "17:30"}, trip)
    assert "Here's a quick summary" not in summary
    assert "Shall I lock this in" not in summary


def test_booking_summary_has_price_data():
    """Booking summary still contains price information."""
    trip = {"display_name": "Sunset Cruise", "departures": [{"time": "17:30", "vessel": "Kailani", "departure_point": "Village Marina"}], "price_adult_usd": 79, "included": ["open bar", "snacks"]}
    summary = _build_booking_summary({"trip_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "departure_time": "17:30"}, trip)
    assert "$158" in summary
    assert "$79" in summary


def test_booking_summary_new_closer():
    """Booking summary ends with new natural closer."""
    trip = {"display_name": "Sunset Cruise", "departures": [{"time": "17:30", "vessel": "Kailani", "departure_point": "Village Marina"}], "price_adult_usd": 79, "included": ["open bar", "snacks"]}
    summary = _build_booking_summary({"trip_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "departure_time": "17:30"}, trip)
    assert "Want me to go ahead and book this?" in summary


def test_slot_unavailable_no_em_dashes():
    """Post-validate day-of-week message has no em dashes or exclamation openers."""
    th = {"fields": {"experience": "Snorkeling", "date": "2026-03-09", "guests": "2", "trip_key": "snorkeling_3in1"}, "flags": {}}
    trip = {"display_name": "3-in-1 Snorkeling Trip", "departures": [{"time": "10:00"}], "days_available": "Fridays only"}
    result = {"intents": ["booking"], "fields": {}, "flags": {}}
    override, _ = _post_validate(th, result, trip)
    assert "Great choice" not in override
    assert "—" not in override


def test_persona_still_correct():
    """marina_persona in client.json still has hospitality and tone mirroring."""
    persona = config_loader.get_common_sense_knowledge().get("marina_persona", "")
    assert "hospitality" in persona
    assert "mirrors the tone" in persona


if __name__ == "__main__":
    tests = [
        test_system_prompt_contains_writing_style,
        test_system_prompt_contains_example_replies,
        test_system_prompt_contains_json_format,
        test_user_prompt_contains_inbound_message,
        test_user_prompt_contains_business_data,
        test_build_prompt_wrapper_combines_both,
        test_booking_summary_no_old_format,
        test_booking_summary_has_price_data,
        test_booking_summary_new_closer,
        test_slot_unavailable_no_em_dashes,
        test_persona_still_correct,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__} — {e}")
    print(f"\n{passed}/{len(tests)} tests passed.")
    if passed < len(tests):
        sys.exit(1)
```

## Tests

11 tests in `test_marina_tone.py`:
1. System prompt contains "WRITING STYLE"
2. System prompt contains "GOOD REPLY EXAMPLES" and "tone reference"
3. System prompt contains JSON format spec (`"intents"`, `"reply"`)
4. User prompt contains "INBOUND MESSAGE:" and body text
5. User prompt contains "TRIPS" and "FAQ"
6. `_build_prompt()` wrapper contains content from both system and user
7. Booking summary does NOT contain "Here's a quick summary" or "Shall I lock this in"
8. Booking summary contains "$158" and "$79" (price data preserved)
9. Booking summary contains "Want me to go ahead and book this?"
10. Post-validate day-of-week message has no "Great choice" or em dashes
11. Persona still has "hospitality" and "mirrors the tone"

Plus 8 updated assertions across 4 existing test files.

## Success Condition

All tests pass. Deploy to VPS and send test emails. Marina's replies should sound like a real person: no bullet-point summaries, no "Shall I lock this in", no forced enthusiasm, tone mirrors the sender.

## Rollback

Revert `src/marina_agent.py` and `src/email_poller.py` to Brief 059/058 versions. Revert test files. No database or config changes to undo.
