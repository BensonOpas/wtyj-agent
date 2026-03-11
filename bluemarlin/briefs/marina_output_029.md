# OUTPUT_029 — Marina Prompt Fixes: Confirmation Step, Escalation, Vague Date

## Files modified
- `bluemarlin/src/marina_agent.py`
- `bluemarlin/src/email_poller.py`

## Files created
- `bluemarlin/briefs/OUTPUT_029.md` (this file)

---

## Changes made

### marina_agent.py — _build_prompt()

Three additions inserted between PAYMENT section and THREAD CONTEXT section:

**1. BOOKING CONFIRMATION BEHAVIOUR** — new section:
- Triggers when fields response contains all four required fields
  (experience, date, guests, trip_key) and awaiting_booking_confirmation
  is not set.
- Marina sends booking summary and asks "Shall I lock this in for you?"
- Sets awaiting_booking_confirmation: true in flags JSON.
- departure_time clarification added: not required, do not block summary.
- On confirmation (yes/sure/ja/si/etc): sets booking_confirmed: true,
  awaiting_booking_confirmation: false.

**2. ESCALATION BEHAVIOUR** — new section:
- When intent is complaint or cancellation: requires_human = true.
- Reply acknowledges warmly, tells customer The Crew will be in touch.
- No detail gathering. No promises.

**3. Date field description** — replaced:
Old: "Convert any natural language date to YYYY-MM-DD before including."
New: Stronger wording — "Never infer, guess, or pick a date the customer
has not explicitly stated or clearly implied. When in doubt, ask."
Vague dates (e.g. "sometime next month") must be omitted and a
clarification question added.

**flags field description** — updated to show actual flag keys:
Changed from generic placeholder to explicit keys with conditions:
awaiting_booking_confirmation and booking_confirmed.

File header: LAST MODIFIED Brief 027 → Brief 029

### email_poller.py — booking trigger

Added `th["flags"].get("booking_confirmed")` check to booking trigger:

Before:
```python
if (fields_now.get("experience") and fields_now.get("date")
        and fields_now.get("guests") and fields_now.get("trip_key")
        and not th["flags"].get("hold_created")):
```

After:
```python
if (fields_now.get("experience") and fields_now.get("date")
        and fields_now.get("guests") and fields_now.get("trip_key")
        and th["flags"].get("booking_confirmed")
        and not th["flags"].get("hold_created")):
```

File header: LAST MODIFIED Brief 028 → Brief 029

---

## Test results

| # | Test | Result |
|---|------|--------|
| 1 | marina_agent imports cleanly | PASS |
| 2 | email_poller imports cleanly | PASS |
| 3 | awaiting_booking_confirmation=True when all fields present | PASS |
| 4 | booking_confirmed=True on "Yes let's do it" | PASS |
| 5 | hold NOT triggered without booking_confirmed | PASS |
| 6 | complaint → requires_human=True, reply mentions The Crew, no detail gathering | PASS |
| 7 | cancellation → requires_human=True, reply mentions The Crew | PASS |
| 8 | "sometime next month" → date omitted, clarifications_needed populated | PASS |
| 9 | "April 20th" → date resolved to 2026-04-20 | PASS |
| 10 | awaiting_booking_confirmation, booking_confirmed, The Crew, Never infer/guess in source | PASS |

---

## Debugging notes

Test 3 required prompt iteration. The model correctly generated the booking
summary reply but consistently returned flags: {} across four iterations.
Root causes diagnosed:
1. The flags JSON template used a placeholder format that the model treated
   as optional — fixed by showing actual flag key names with conditions.
2. The model was waiting for departure_time before presenting the summary —
   fixed by explicitly stating departure_time is not required and must not
   block the confirmation flow.
