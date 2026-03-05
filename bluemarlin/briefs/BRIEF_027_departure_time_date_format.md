# BRIEF 027 — marina_agent.py — departure_time field + date format enforcement

**Brief number:** 027
**Status:** Ready to execute
**Files modified:** bluemarlin/src/marina_agent.py, bluemarlin/src/email_poller.py
**Files created:** None
**Depends on:** Brief 024 (email_poller.py), Brief 023 (marina_agent.py)
**Blocks:** Nothing — fixes two live bugs

---

## CONTEXT

Two bugs identified in live testing:

Bug 1 — date field is returned by marina_agent in natural language
format ("April 5", "April 20"). calendar.js requires YYYY-MM-DD.
Any date not in that format causes calendar.js to throw
"Invalid time value" and the hold fails.

Bug 2 — when a trip has multiple departures (e.g. klein_curacao has
08:00 and 08:30), the customer chooses one during conversation but
that choice is never extracted as a field. create_calendar_hold
always falls back to departures[0]["time"] from config regardless
of what the customer said.

---

## SOURCE MATERIAL

Files confirmed seen this session:

marina_agent.py _build_prompt() — lines 49–119. Current fields
instruction reads:
"experience, date, guests, customer_name, phone, special_requests,
trip_key — only if present and certain."

email_poller.py create_calendar_hold() — lines 175–212. Current
start_time logic:
start_time = departures[0].get("time", "09:00") if departures else "09:00"

client.json klein_curacao departures confirmed:
[{"time": "08:00", "vessel": "BlueFinn2", ...},
 {"time": "08:30", "vessel": "BlueFinn1", ...}]

---

## PART 1 — marina_agent.py

One change only: update the fields description in the prompt
inside _build_prompt().

Current fields line:
"fields": {"<extracted booking fields — experience, date, guests,
customer_name, phone, special_requests, trip_key — only if present
and certain. trip_key is the exact key from the trips list that
matches the experience: one of klein_curacao, snorkeling_3in1,
west_coast_beach, sunset_cruise, jet_ski — only include if you
are certain which trip they mean>"}

Replace with:
"fields": {"<extracted booking fields — only if present and certain:
  experience: the trip name as the customer described it
  date: MUST be in YYYY-MM-DD format. Convert any natural language
    date to YYYY-MM-DD before including. If you cannot resolve it
    to a specific YYYY-MM-DD date, omit this field entirely and
    include a clarification question in clarifications_needed instead.
  guests: exact integer only
  customer_name: customer's name
  phone: customer's phone number
  special_requests: forward-looking preferences only
  trip_key: exact key from the trips list — one of klein_curacao,
    snorkeling_3in1, west_coast_beach, sunset_cruise, jet_ski —
    only include if certain
  departure_time: the specific departure time the customer has
    chosen, in HH:MM format — only include if the customer has
    explicitly selected one from the available options>"}

Update file header: LAST MODIFIED Brief 024 → Brief 027
No other changes to marina_agent.py.

---

## PART 2 — email_poller.py

One change only: in create_calendar_hold(), update the start_time
lookup to use departure_time from fields if present, otherwise fall
back to config.

Current:
start_time = departures[0].get("time", "09:00") if departures else "09:00"

Replace with:
start_time = (
    fields_now.get("departure_time")
    or (departures[0].get("time", "09:00") if departures else "09:00")
)

Update file header: LAST MODIFIED Brief 025 → Brief 027
No other changes to email_poller.py.

---

## TESTS

**Test 1 — date format instruction is in the prompt**
Read marina_agent.py as text. Assert "YYYY-MM-DD" appears in the
source at least twice — once in the date field instruction.

**Test 2 — departure_time field instruction is in the prompt**
Read marina_agent.py as text. Assert "departure_time" appears in
the source.

**Test 3 — marina_agent returns date in YYYY-MM-DD format**
Call process_message with body:
"I want to book the sunset cruise for April 20 2026 for 2 people."
Assert result["fields"].get("date") == "2026-04-20"

**Test 4 — marina_agent extracts departure_time when customer chooses**
Call process_message with body:
"08:30 works for us.",
thread_fields={"trip_key": "klein_curacao", "experience":
"Klein Curaçao Trip", "date": "2026-04-20", "guests": 2},
thread_flags={}
Assert result["fields"].get("departure_time") == "08:30"

**Test 5 — departure_time not extracted when not mentioned**
Call process_message with body:
"I want to book Klein Curacao on April 20 for 2 people.",
thread_fields={}, thread_flags={}
Assert "departure_time" not in result.get("fields", {})

**Test 6 — create_calendar_hold uses departure_time from fields**
Call create_calendar_hold with fields containing trip_key
"klein_curacao", date "2026-04-20", guests 2, customer_name "Jan",
phone "+5999123456", departure_time "08:30".
Intercept the subprocess.run call. Assert the payload passed to
calendar.js contains start_time "08:30".

**Test 7 — create_calendar_hold falls back to config when
departure_time not in fields**
Call create_calendar_hold with fields containing trip_key
"sunset_cruise", date "2026-04-20", guests 2 — no departure_time.
Intercept the subprocess.run call. Assert the payload contains
start_time "17:30" (the first departure time for sunset_cruise
in client.json).

**Test 8 — marina_agent imports cleanly and email_poller imports
cleanly**
Assert no ImportError for either file.

---

## SUCCESS CONDITION

All 8 tests pass. Marina extracts dates in YYYY-MM-DD format.
Marina captures departure_time when the customer chooses one.
create_calendar_hold uses the customer's chosen departure_time
when present, config default when not. "Invalid time value"
error is resolved.

---

## ROLLBACK

Changes are limited to one line in create_calendar_hold and one
prompt block in _build_prompt. Both are easily reverted. No
existing behaviour is removed — only the date format is
enforced and a new field is added.
