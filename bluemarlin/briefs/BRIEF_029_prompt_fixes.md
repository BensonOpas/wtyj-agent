# BRIEF 029 — Marina Prompt Fixes: Confirmation Step, Escalation, Vague Date

**Brief number:** 029
**Status:** Ready to execute
**Files modified:** bluemarlin/src/marina_agent.py, bluemarlin/src/email_poller.py
**Files created:** None
**Depends on:** Brief 027 (marina_agent.py), Brief 028 (email_poller.py)
**Blocks:** Nothing — fixes three live bugs

---

## CONTEXT

Three bugs identified in live testing, all fixable via prompt changes
and one Python routing change:

Bug 1 — Booking confirmation: when all required fields are present,
the system creates a hold immediately without asking the customer to
confirm. Customers paying $79–$480 expect a review moment before
committing. Fix: Marina sends a booking summary and asks for
confirmation. Hold is only created after customer says yes.

Bug 2 — Complaint and cancellation escalation: Marina tries to handle
complaints and cancellations herself by asking for booking details.
She has no access to booking records and cannot process refunds.
Fix: Marina acknowledges warmly, tells customer The Crew will be in
touch, and stops. No detail gathering.

Bug 3 — Vague date: "sometime next month" caused Marina to guess a
specific date and create a real calendar hold. Fix: if a date cannot
be resolved to a specific YYYY-MM-DD, Marina must ask for a specific
date. Never infer or guess.

---

## SOURCE MATERIAL

Files confirmed seen this session:

marina_agent.py _build_prompt() — lines 49–119, Brief 027.
Current prompt ends with JSON structure definition including
intents, fields, confidence, reply, clarifications_needed,
requires_human, flags, internal_note.

email_poller.py main loop — lines 299–440, Brief 028. Booking
trigger condition (Step 5):
if "booking" in result.get("intents", []):
    fields_now = th["fields"]
    if (fields_now.get("experience") and fields_now.get("date")
            and fields_now.get("guests") and fields_now.get("trip_key")
            and not th["flags"].get("hold_created")):

---

## PART 1 — marina_agent.py

Three additions to _build_prompt(). All added as new instruction
sections before the JSON structure definition at the end of the
prompt. Insert them as a block between the PAYMENT section and
the THREAD CONTEXT section.

### Addition 1 — Booking confirmation behaviour

Add this section to the prompt:

BOOKING CONFIRMATION BEHAVIOUR:
When all required booking fields are present (experience, date,
guests, trip_key) and the thread flag "awaiting_booking_confirmation"
is not set to true, do NOT assume the booking is confirmed. Instead:
- Send a warm booking summary to the customer listing: trip name,
  date, number of guests, departure time (if chosen), total price,
  what is included.
- End the summary with a single clear confirmation question:
  "Shall I lock this in for you?"
- Set flags: {"awaiting_booking_confirmation": true}
- Do NOT set any hold-related flags.

When "awaiting_booking_confirmation" is true in thread flags:
- If the customer's message is a confirmation (yes, sure, let's do
  it, perfect, go ahead, ja, si, or any equivalent in any language):
  set flags: {"booking_confirmed": true, "awaiting_booking_confirmation": false}
  Reply briefly confirming you are locking it in.
- If the customer wants to change something: update the relevant
  field, reset awaiting_booking_confirmation to false, and continue
  the conversation naturally.
- If unclear: ask for clarification.

### Addition 2 — Escalation behaviour for complaints and cancellations

Add this section to the prompt:

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

### Addition 3 — Date handling

The existing date instruction in the fields block already says
"If you cannot resolve it to a specific YYYY-MM-DD date, omit
this field entirely and include a clarification question in
clarifications_needed instead."

Replace the entire date field description (the full date: block starting from 'date: MUST be in YYYY-MM-DD format') with:
  date: MUST be in YYYY-MM-DD format. You must convert any natural
    language date (e.g. "April 20", "next Saturday", "in two weeks")
    to YYYY-MM-DD using today's date as reference. If the customer
    has given a vague or unresolvable date (e.g. "sometime next
    month", "in the summer", "soon") you MUST omit this field and
    ask for a specific date in clarifications_needed. Never infer,
    guess, or pick a date the customer has not explicitly stated or
    clearly implied. When in doubt, ask.

Update file header: LAST MODIFIED Brief 027 → Brief 029

---

## PART 2 — email_poller.py

### Change 1 — Booking trigger checks booking_confirmed flag

Current trigger condition:
```python
if (fields_now.get("experience") and fields_now.get("date")
        and fields_now.get("guests") and fields_now.get("trip_key")
        and not th["flags"].get("hold_created")):
```

Replace with:
```python
if (fields_now.get("experience") and fields_now.get("date")
        and fields_now.get("guests") and fields_now.get("trip_key")
        and th["flags"].get("booking_confirmed")
        and not th["flags"].get("hold_created")):
```

This is the only Python change. Python routes on the structured
flag value. Claude decides when booking_confirmed is true based
on the customer's natural language response. Python never reads
the reply content.

Update file header: LAST MODIFIED Brief 028 → Brief 029
No other changes to email_poller.py.

---

## TESTS

**Test 1 — marina_agent imports cleanly**
Import marina_agent. Assert no ImportError.

**Test 2 — email_poller imports cleanly**
Import email_poller. Assert no ImportError.

**Test 3 — awaiting_booking_confirmation flag set when all fields
present and not yet confirmed**
Call process_message with body:
"Klein Curaçao April 20 2026 2 adults",
thread_fields={}, thread_flags={}
Assert result["flags"].get("awaiting_booking_confirmation") == True
Assert result["flags"].get("booking_confirmed") is not True

**Test 4 — booking_confirmed set on yes response**
Call process_message with body: "Yes let's do it",
thread_fields={"experience": "Klein Curaçao Trip",
  "date": "2026-04-20", "guests": 2,
  "trip_key": "klein_curacao"},
thread_flags={"awaiting_booking_confirmation": True}
Assert result["flags"].get("booking_confirmed") == True
Assert not result["flags"].get("awaiting_booking_confirmation")

**Test 5 — hold not triggered without booking_confirmed**
Mock create_calendar_hold. Trigger booking flow with all fields
present but booking_confirmed not in flags.
Assert create_calendar_hold was NOT called.

**Test 6 — complaint sets requires_human and reply mentions The Crew**
Call process_message with body:
"Your boat was dirty and the crew was rude. I want a refund.",
thread_fields={}, thread_flags={}
Assert result.get("requires_human") == True
Assert "Crew" in result.get("reply", "")
Assert result["reply"] does not ask the customer to provide booking
details, reference numbers, dates, or contact information — verify
by checking the reply does not contain any of: "booking reference",
"reference number", "trip name", "date of your trip", "contact"

**Test 7 — cancellation sets requires_human and reply mentions
The Crew**
Call process_message with body:
"I need to cancel my booking please.",
thread_fields={}, thread_flags={}
Assert result.get("requires_human") == True
Assert "Crew" in result.get("reply", "")

**Test 8 — vague date omitted and clarification requested**
Call process_message with body:
"I want to book Klein Curaçao sometime next month for 2 people.",
thread_fields={}, thread_flags={}
Assert "date" not in result.get("fields", {})
Assert len(result.get("clarifications_needed", [])) > 0

**Test 9 — specific date resolved to YYYY-MM-DD**
Call process_message with body:
"Klein Curaçao on April 20th for 2 adults",
thread_fields={}, thread_flags={}
Assert result["fields"].get("date") == "2026-04-20"

**Test 10 — booking_confirmed prompt instruction present in source**
Read marina_agent.py as text. Assert "awaiting_booking_confirmation"
in source. Assert "booking_confirmed" in source.
Assert "The Crew" in source. Assert "Never infer, guess" in source.

---

## SUCCESS CONDITION

All 10 tests pass. Holds are only created after explicit customer
confirmation. Complaints and cancellations escalate to The Crew
without detail gathering. Vague dates are never guessed.

---

## ROLLBACK

Changes are limited to prompt additions in _build_prompt() and one
condition line in email_poller.py. Both are easily reverted.
No existing behaviour is removed — only new routing logic and
prompt instructions added. Live service not restarted as part of
this brief.
