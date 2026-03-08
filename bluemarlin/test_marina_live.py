#!/usr/bin/env python3
# bluemarlin/test_marina_live.py
# Level 1 live test — marina_agent only, no calendar, no sheets, no email
# Run: cd bluemarlin && source ~/.zshrc && python3 test_marina_live.py

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import marina_agent

DIVIDER = "-" * 60


def run(label, from_email, subject, body, thread_fields=None, thread_flags=None):
    thread_fields = thread_fields or {}
    thread_flags = thread_flags or {}

    print(f"\n{DIVIDER}")
    print(f"SCENARIO: {label}")
    print(f"BODY: {body[:120]}")
    print(DIVIDER)

    result = marina_agent.process_message(
        from_email=from_email,
        subject=subject,
        body=body,
        thread_fields=thread_fields,
        thread_flags=thread_flags,
    )

    print(f"intents:          {result.get('intents')}")
    print(f"confidence:       {result.get('confidence')}")
    print(f"fields:           {json.dumps(result.get('fields', {}), ensure_ascii=False)}")
    print(f"flags:            {json.dumps(result.get('flags', {}), ensure_ascii=False)}")
    print(f"requires_human:   {result.get('requires_human')}")
    print(f"clarifications:   {result.get('clarifications_needed')}")
    print(f"internal_note:    {result.get('internal_note')}")
    print(f"\nREPLY:\n{result.get('reply')}")
    if result.get("reply_hold_failed"):
        print(f"\nREPLY (hold failed):\n{result.get('reply_hold_failed')}")

    return result


# ------------------------------------------------------------
# Scenario 1: First contact, all fields in one message
# Expected: fields extracted, awaiting_booking_confirmation=true
# ------------------------------------------------------------
s1 = run(
    label="1 — First contact, all fields provided",
    from_email="john@example.com",
    subject="Booking Klein Curacao",
    body="Hi, I'd like to book the Klein Curacao trip for April 10 2026, for 4 people. My name is John Smith.",
    thread_fields={},
    thread_flags={},
)

# ------------------------------------------------------------
# Scenario 2: First contact, missing fields
# Expected: Marina asks for what's missing
# ------------------------------------------------------------
s2 = run(
    label="2 — First contact, missing date and guests",
    from_email="maria@example.com",
    subject="Trip inquiry",
    body="Hi there! I'm interested in the sunset cruise. Can you tell me more?",
    thread_fields={},
    thread_flags={},
)

# ------------------------------------------------------------
# Scenario 3: Customer confirms booking
# Simulate: all fields already in thread, awaiting confirmation
# Expected: booking_confirmed=true, reply with [PAYMENT_LINK]
# ------------------------------------------------------------
s3 = run(
    label="3 — Customer confirms booking",
    from_email="john@example.com",
    subject="Re: Booking Klein Curacao",
    body="Yes, let's do it!",
    thread_fields={
        "experience": "Klein Curacao",
        "trip_key": "klein_curacao",
        "date": "2026-04-10",
        "guests": 4,
        "customer_name": "John Smith",
    },
    thread_flags={
        "awaiting_booking_confirmation": True,
    },
)

# ------------------------------------------------------------
# Scenario 4: Complaint
# Expected: requires_human=true, warm escalation reply, no detail gathering
# ------------------------------------------------------------
s4 = run(
    label="4 — Complaint",
    from_email="angry@example.com",
    subject="Terrible experience",
    body="The boat was dirty and the crew was rude. I want a refund.",
    thread_fields={},
    thread_flags={},
)

# ------------------------------------------------------------
# Scenario 5: Off-topic
# Expected: intents=off_topic, polite decline
# ------------------------------------------------------------
s5 = run(
    label="5 — Off-topic",
    from_email="random@example.com",
    subject="Quick question",
    body="Hey, do you know where I can rent a car in Curacao?",
    thread_fields={},
    thread_flags={},
)

print(f"\n{DIVIDER}")
print("Done. Review each reply above for tone, accuracy, and flag correctness.")
print(DIVIDER)
