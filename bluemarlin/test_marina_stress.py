#!/usr/bin/env python3
# bluemarlin/test_marina_stress.py
# Stress test — 14 scenarios covering language adaptation, trip key mapping,
# booking flow, edge cases, and escalation.
# Run: cd bluemarlin && source ~/.zshrc && python3 test_marina_stress.py

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import marina_agent

DIVIDER = "=" * 70


def run(label, from_email, subject, body, thread_fields=None, thread_flags=None):
    thread_fields = thread_fields or {}
    thread_flags = thread_flags or {}

    print(f"\n{DIVIDER}")
    print(f"SCENARIO: {label}")
    print(f"BODY: {body[:140]}")
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


# -----------------------------------------------------------------------
# S1 — Dutch inquiry
# Expected: reply in Dutch, trip_key extracted or clarification asked in Dutch
# -----------------------------------------------------------------------
s1 = run(
    label="S1 — Dutch inquiry (language adaptation)",
    from_email="pieter@example.nl",
    subject="Vraag over Klein Curaçao",
    body="Hallo, ik wil graag meer informatie over de Klein Curaçao trip. "
         "We zijn met 3 personen en willen graag gaan op 20 april 2026. "
         "Kunt u ons helpen?",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S2 — All fields provided, Klein Curaçao by name
# Expected: awaiting_booking_confirmation=true, booking summary in reply
# -----------------------------------------------------------------------
s2 = run(
    label="S2 — Full booking, Klein Curaçao by name",
    from_email="alice@example.com",
    subject="Booking Klein Curacao",
    body="Hi, I'd like to book the Klein Curacao trip for May 3 2026, "
         "for 6 adults. My name is Alice Brown.",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S3 — Customer confirms S2-style booking
# Expected: booking_confirmed=true, [PAYMENT_LINK] in reply
# -----------------------------------------------------------------------
s3 = run(
    label="S3 — Customer confirms booking",
    from_email="alice@example.com",
    subject="Re: Booking Klein Curacao",
    body="Perfect, yes please go ahead!",
    thread_fields={
        "experience": "Klein Curaçao",
        "trip_key": "klein_curacao",
        "date": "2026-05-03",
        "guests": 6,
        "customer_name": "Alice Brown",
    },
    thread_flags={
        "awaiting_booking_confirmation": True,
    },
)

# -----------------------------------------------------------------------
# S4 — Vague trip name: "snorkeling"
# Expected: trip_key=snorkeling_3in1 extracted
# -----------------------------------------------------------------------
s4 = run(
    label="S4 — Trip key mapping: 'snorkeling'",
    from_email="bob@example.com",
    subject="Snorkeling inquiry",
    body="Hi, I want to go snorkeling on April 25 2026 with 2 people.",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S5 — Vague trip name: "evening cruise"
# Expected: trip_key=sunset_cruise extracted
# -----------------------------------------------------------------------
s5 = run(
    label="S5 — Trip key mapping: 'evening cruise'",
    from_email="carol@example.com",
    subject="Evening cruise",
    body="Hello! We would love to join an evening cruise on June 5 2026. "
         "Just the two of us.",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S6 — Vague trip name: "jet ski"
# Expected: trip_key=jet_ski extracted
# -----------------------------------------------------------------------
s6 = run(
    label="S6 — Trip key mapping: 'jet ski'",
    from_email="dan@example.com",
    subject="Jet ski",
    body="Hey, can I book a jet ski session for tomorrow, just me?",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S7 — Vague trip name: "west coast beach"
# Expected: trip_key=west_coast_beach extracted
# -----------------------------------------------------------------------
s7 = run(
    label="S7 — Trip key mapping: 'west coast beach'",
    from_email="eva@example.com",
    subject="West coast beach trip",
    body="Hi! Interested in the west coast beach trip for April 30 2026, "
         "group of 5.",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S8 — Large group (20 people)
# Expected: requires_human=true (threshold is 15+)
# -----------------------------------------------------------------------
s8 = run(
    label="S8 — Large group (20 people) — should escalate",
    from_email="events@company.com",
    subject="Group booking",
    body="Hello, we are a company of 20 people looking to book the Klein "
         "Curaçao trip on May 15 2026 for a team outing.",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S9 — Vague date: "sometime next month"
# Expected: date omitted from fields, clarification asked
# -----------------------------------------------------------------------
s9 = run(
    label="S9 — Vague date: 'sometime next month' — should ask for specific date",
    from_email="fred@example.com",
    subject="Trip inquiry",
    body="Hi, I'd like to book the sunset cruise for sometime next month "
         "with my partner.",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S10 — Natural language date: "April 15"
# Expected: date resolved to 2026-04-15
# -----------------------------------------------------------------------
s10 = run(
    label="S10 — Natural language date: 'April 15'",
    from_email="gina@example.com",
    subject="Klein Curacao booking",
    body="Hi there! I want to book Klein Curacao for April 15 for 3 people. "
         "Name is Gina Torres.",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S11 — Multi-departure trip with explicit departure time
# Klein Curaçao has 08:00 and 08:30 options
# Expected: departure_time=08:00 captured
# -----------------------------------------------------------------------
s11 = run(
    label="S11 — Multi-departure trip with chosen time (08:00)",
    from_email="hans@example.com",
    subject="Klein Curacao 8am departure",
    body="Hello, I'd like to book the Klein Curacao trip on May 10 2026 "
         "for 4 people. We prefer the 8:00 AM departure. Name: Hans Müller.",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S12 — Field change mid-confirmation (customer changes date)
# Thread has awaiting_booking_confirmation=true
# Expected: confirmation reset, new date captured, new summary or clarification
# -----------------------------------------------------------------------
s12 = run(
    label="S12 — Field change mid-confirmation (date change)",
    from_email="alice@example.com",
    subject="Re: Booking sunset cruise",
    body="Actually, can we change it to May 10 instead? The 5th doesn't work.",
    thread_fields={
        "experience": "Sunset Cruise",
        "trip_key": "sunset_cruise",
        "date": "2026-05-05",
        "guests": 2,
        "customer_name": "Alice Brown",
    },
    thread_flags={
        "awaiting_booking_confirmation": True,
    },
)

# -----------------------------------------------------------------------
# S13 — Special requests
# Expected: special_requests captured, booking flow proceeds
# -----------------------------------------------------------------------
s13 = run(
    label="S13 — Special requests: vegetarian + elderly guest",
    from_email="james@example.com",
    subject="Klein Curacao booking with special needs",
    body="Hi, I want to book the Klein Curacao trip on April 18 2026 for 3 people. "
         "Name is James Lee. One of us is vegetarian and my mother uses a walking "
         "stick — any accommodations available?",
    thread_fields={},
    thread_flags={},
)

# -----------------------------------------------------------------------
# S14 — Cancellation request
# Expected: requires_human=true, warm escalation, no info gathering
# -----------------------------------------------------------------------
s14 = run(
    label="S14 — Cancellation request — should escalate warmly",
    from_email="lisa@example.com",
    subject="Cancel my booking",
    body="Hi, I need to cancel my booking for next week. Something came up "
         "and we can no longer make it.",
    thread_fields={},
    thread_flags={},
)

print(f"\n{DIVIDER}")
print(f"Done — 14 scenarios run. Review replies above.")
print(f"Key checks:")
print(f"  S1  — reply is in Dutch")
print(f"  S2  — awaiting_booking_confirmation=true, booking summary present")
print(f"  S3  — booking_confirmed=true, [PAYMENT_LINK] in reply")
print(f"  S4  — trip_key=snorkeling_3in1")
print(f"  S5  — trip_key=sunset_cruise")
print(f"  S6  — trip_key=jet_ski")
print(f"  S7  — trip_key=west_coast_beach")
print(f"  S8  — requires_human=true")
print(f"  S9  — date not in fields, clarification asked")
print(f"  S10 — date=2026-04-15")
print(f"  S11 — departure_time=08:00")
print(f"  S12 — awaiting_booking_confirmation reset, new date captured")
print(f"  S13 — special_requests captured")
print(f"  S14 — requires_human=true, no info requests")
print(DIVIDER)
