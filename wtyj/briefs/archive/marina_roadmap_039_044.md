# ROADMAP — Briefs 039–044
# Written: 2026-03-08 after /think session
# READ THIS before writing any brief in the 039–044 range.
# This file is the single source of truth for what needs to be built next.

---

## CONTEXT — Why these briefs exist

The booking system has four gaps that need fixing before demo:

1. **No capacity tracking** — the first customer to book a trip blocks the entire boat for everyone else. Trips have a max guest count (e.g. 30 people). Multiple families should be able to book the same trip+date up to that ceiling.
2. **No escalation system** — when Marina can't handle something, there's no structured handoff to a human.
3. **Booking ref never shown to customer** — `BF-YYYY-XXXXX` is generated but the customer never sees it. Marina also has no memory of past bookings if a customer emails in a new thread.
4. **No multi-trip booking** — a customer can't book two different trips in one conversation.

---

## ARCHITECTURE DECISION — How real booking systems work

**Research: Fareharbor, Bokun, Rezdy, Ticketmaster, Booking.com, Airbnb.**

Key findings:
- No production booking system uses Google Calendar as its availability database
- Calendar = crew scheduling display tool only
- Availability lives in a dedicated SQL database with capacity per slot
- Industry standard pattern: TWO-STEP soft hold → confirm
  - Step 1: Customer starts booking → SOFT HOLD (temporary, with expiry TTL)
  - Step 2: Customer confirms → CONFIRMED BOOKING (permanent)
  - If customer goes silent → soft hold expires → capacity auto-released
- Ticketmaster: Redis lock, 10-min TTL. Booking.com: soft hold 5-8 min, event-driven expiry.
- For email-based flow (slower than web): **24-hour soft hold** is appropriate

**Mapping to BlueMarlin's existing flow:**
- `awaiting_booking_confirmation` = Step 1 → soft hold created in SQLite
- `booking_confirmed` = Step 2 → soft hold confirmed (permanent)
- NEW: soft hold expires after 24h if customer doesn't respond

**IMPORTANT: Calendar is NOT being removed.**
Every confirmed booking still creates a Google Calendar event. The crew still sees their full schedule. What changes: the availability CHECK logic moves from calendar → SQLite. Calendar = crew view (unchanged). SQLite = availability gate (new).

---

## Brief 039 — Capacity-aware booking with soft holds (CRITICAL — do first)

### Problem
1. `check_availability()` is binary — any event blocks the whole slot
2. Multiple families should share a departure up to the capacity ceiling
3. Klein Curaçao has two departures on different vessels — each must be independent
4. No hold expiry — abandoned mid-bookings permanently consume capacity

### Confirmed values
Demo capacity (confirm with BlueFinn before go-live):
- `klein_curacao`: 30 per departure
- `snorkeling_3in1`: 20
- `west_coast_beach`: 25
- `sunset_cruise`: 20
- `jet_ski`: 4 (2 jet skis × 2 riders each)

Klein Curaçao calendar IDs (per vessel, move to departure level in client.json):
- 08:00 BlueFinn2: `4ce23ea0e7ec08da249c778969d71c199b8aaf7bf6114efac4fae7e0928f1b31@group.calendar.google.com`
- 08:30 BlueFinn1: `9f25610370f0f57fa395735502fcff767ba8276ee5a280d028fee7f003054928@group.calendar.google.com`

For all other trips (single departure): move existing trip-level `calendar_id` into the departure object.

### Changes required

**1. `config/client.json`**

Move `calendar_id` from trip level → departure level for ALL trips.
Add `"capacity": N` to each trip (top-level trip field).

Klein Curaçao becomes:
```json
"klein_curacao": {
  "capacity": 30,
  "departures": [
    {"time": "08:00", "vessel": "BlueFinn2", "departure_point": "Jan Thiel Beach",
     "calendar_id": "4ce23ea0e7ec08da249c778969d71c199b8aaf7bf6114efac4fae7e0928f1b31@group.calendar.google.com"},
    {"time": "08:30", "vessel": "BlueFinn1", "departure_point": "Jan Thiel Beach",
     "calendar_id": "9f25610370f0f57fa395735502fcff767ba8276ee5a280d028fee7f003054928@group.calendar.google.com"}
  ]
}
```

Single-departure trips (e.g. sunset_cruise): same structure, just one departure object with `calendar_id` inside it.

**2. `src/state_registry.py`**

Add to `_init_db()`:
```sql
CREATE TABLE IF NOT EXISTS trip_bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_key TEXT NOT NULL,
    date TEXT NOT NULL,
    departure_time TEXT NOT NULL,
    guests INTEGER NOT NULL,
    booking_ref TEXT,
    status TEXT DEFAULT 'soft_hold',
    expires_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trip_bookings_lookup
    ON trip_bookings(trip_key, date, departure_time, status);
```

New public functions:
```python
def expire_stale_holds() -> int:
    """UPDATE status='expired' WHERE status='soft_hold' AND expires_at < now(). Returns count."""

def get_spots_remaining(trip_key, date, departure_time, capacity) -> int:
    """capacity - SUM(guests) WHERE trip_key=? AND date=? AND departure_time=?
    AND status IN ('soft_hold','confirmed') AND (expires_at > now() OR status='confirmed')"""

def create_soft_hold(trip_key, date, departure_time, guests, capacity) -> int | None:
    """Atomic: expire stale, check capacity, insert soft_hold with expires_at=now+24h.
    Returns new row id (hold_id) on success, None if at capacity."""

def confirm_hold(hold_id) -> bool:
    """UPDATE status='confirmed', expires_at=NULL WHERE id=hold_id AND status='soft_hold'"""

def cancel_hold(hold_id) -> bool:
    """UPDATE status='cancelled' WHERE id=hold_id"""
```

**3. `src/gws_calendar.py`**

Rewrite `check_availability(trip_key, date, start_time, new_guests) -> dict`:
```python
def check_availability(trip_key, date, start_time, new_guests):
    state_registry.expire_stale_holds()
    capacity = config_loader.get_trip(trip_key).get("capacity", 20)
    spots = state_registry.get_spots_remaining(trip_key, date, start_time, capacity)
    return {
        "available": spots >= new_guests,
        "spots_remaining": spots,
        "capacity": capacity
    }
```
No more gws CLI call for availability. SQLite only.

Update `create_hold(fields_now) -> dict`:
- Look up `calendar_id` from the matching departure object (match on departure_time)
- Returns `{"ok": True, "eventId": ..., "htmlLink": ...}` or error dict
- Calendar event still created for crew scheduling — just uses departure-level calendar_id now

**4. `src/email_poller.py`**

Step 3b (availability pre-check, triggered by `awaiting_booking_confirmation`):
- Pass `guests` count: `check_availability(trip_key, date, departure_time, int(guests))`
- If available: create soft hold → `hold_id = state_registry.create_soft_hold(...)`
- Store `th["flags"]["hold_id"] = hold_id`
- Feed `spots_remaining` into marina_agent context for next call

Step 4 (booking_confirmed → create calendar hold):
- After `gws_calendar.create_hold()` succeeds: `state_registry.confirm_hold(th["flags"]["hold_id"])`
- If calendar hold fails: `state_registry.cancel_hold(th["flags"]["hold_id"])`

**5. `src/marina_agent.py`**

Add to `_build_prompt()` thread context section:
```python
f"spots_remaining: {thread_flags.get('spots_remaining', 'unknown')}"
f"trip_capacity: {thread_flags.get('trip_capacity', 'unknown')}"
```

Add to prompt instructions:
```
When spots_remaining is provided:
- Mention it naturally if > 0: "We still have {N} spots available on that date!"
- Urgency if < 5: "Only {N} spots left — book soon!"
- If spots_remaining = 0: apologize, offer alternative dates
```

### Tests
1. Book 20 guests Klein Curaçao 2026-04-01 08:00 → succeeds, spots_remaining = 10
2. Book 15 more guests same slot → FAILS (total 35 > 30)
3. Book 10 more guests same slot → SUCCEEDS (total 30, at limit)
4. Book 1 more → FAILS
5. Book same trip 08:30 → independent slot, 30 available
6. Book same trip April 2 → fresh slot, 30 available
7. Simulate 24h expiry → expired hold's guests released, spots_remaining increases
8. Concurrent race: two customers both pass availability, only one creates hold (SQLite transaction)

---

## Brief 040 — Escalation system: semi + full (HIGH)

### Two modes

**Semi-escalation** — question Marina can't answer (not a complaint/refund/cancellation):
- Marina → customer: *"Great question! I'm just checking with the team and I'll get back to you shortly!"*
- email_poller sends relay alert to `butlerbensonagent@gmail.com` (DEMO) / `info@bluefinncharters.com` (PROD)
- Human replies to that alert → Marina receives it, reformulates in her voice → sends to customer
- Thread stays OPEN — Marina continues handling other messages

**Full escalation** — complaint, refund, cancellation, anything needing human authority:
- Marina → customer: *"I've passed this along to our customer care team. You can expect an email from info@bluefinncharters.com shortly — they'll take great care of you."*
- Marina does NOT say "email us at..." — the crew contacts the customer
- email_poller sends full alert to `butlerbensonagent@gmail.com` (DEMO) with complete chat log
- Thread marked `fully_escalated: true` — Marina sends brief holding replies only, no normal processing

### Messages log (needed for both — add to email_poller)

Every inbound + outbound message appended to `th["messages"]`:
```python
th.setdefault("messages", [])
# On inbound receive:
th["messages"].append({"role": "customer", "ts": datetime.now(timezone.utc).isoformat(), "body": body})
# After sending reply:
th["messages"].append({"role": "marina", "ts": datetime.now(timezone.utc).isoformat(), "body": reply_text})
```

### Semi-escalation: relay alert email format

```
To: butlerbensonagent@gmail.com
Reply-To: hello@wetakeyourjob.com
Subject: [RELAY] {booking_ref or "NO-REF"} — {customer_name}

Customer: {customer_name} <{from_email}>
Their question: {relay_question}

Booking context:
  Trip: {trip_key} | Date: {date} | Guests: {guests}
  Ref: {booking_ref or "none yet"}

INSTRUCTIONS: Reply to this email with your answer.
Marina will relay it to the customer in her own words.
```

### Relay detection in email_poller (runs BEFORE normal processing)

```python
if from_email == "butlerbensonagent@gmail.com" and "[RELAY]" in subject:
    # extract booking_ref from subject (regex BF-\d{4}-\d{5})
    # find customer thread via booking_ref or awaiting_relay flag
    # call marina_agent with relay context (see marina_agent changes below)
    # send reformulated reply to original customer thread
    # clear th["flags"]["awaiting_relay"]
    continue
```

### Full escalation alert format

```
To: butlerbensonagent@gmail.com
Subject: [ESCALATION] {booking_ref} — {customer_name} — {intents}

=== CHAT LOG ===
{th["messages"] formatted as: [ROLE | timestamp]\nbody\n---}

=== BOOKING FIELDS ===
{json.dumps(th["fields"], indent=2)}

=== MARINA'S INTERNAL NOTE ===
{result["internal_note"]}
```

### New flags

marina_agent returns:
- `semi_escalation: true` — question Marina can't answer, not critical
- (full escalation uses existing `requires_human: true`)

thread state:
- `awaiting_relay: true/false`
- `relay_question: str`
- `relay_customer_email: str`
- `fully_escalated: true/false`

### marina_agent.py prompt additions

New flag instruction:
```
semi_escalation (bool, optional): Set true when the customer asks a specific question
you cannot answer from available context (NOT complaints, refunds, or cancellations —
those use requires_human). Example: operational details not in FAQ, specific dietary
questions, accessibility questions. When set, also populate relay_question with the
exact question to forward.
relay_question (str, optional): The specific question to relay to the human team.
Only when semi_escalation is true.
```

Relay mode instruction (injected when `awaiting_relay` is in thread flags):
```
RELAY MODE: A human support agent has answered the customer's question.
Their answer: "{human_answer}"
Reformulate this answer in Marina's warm, natural voice. Same language as the customer used.
Do not add information the human didn't provide. Do not make promises beyond what was said.
Set intents: ["inquiry"] and reply with the reformulated answer.
```

Escalation reply instruction:
```
FULL ESCALATION REPLY: When requires_human is true, your reply MUST say:
"I've passed this along to our customer care team. You can expect an email from
info@bluefinncharters.com shortly — they'll take great care of you."
Do not ask for more information. Do not promise a resolution. Just acknowledge warmly.
```

### sheets_writer.py

Update `log_escalation(data)` to accept and write `messages_json` field.
Add Chat Log column to Escalations tab row (JSON string of th["messages"]).

### format_sheets.py

Update Escalations tab column list to include Chat Log (wide column, wrap text).

### Files to modify
- `src/marina_agent.py` — semi_escalation flag, relay_question field, relay mode prompt, escalation reply instruction
- `src/email_poller.py` — messages log accumulation, relay detection block, alert email sending, fully_escalated guard
- `src/sheets_writer.py` — log_escalation adds messages_json
- `src/format_sheets.py` — Escalations tab Chat Log column
- `config/client.json` — add `"support_email": "info@bluefinncharters.com"`, `"demo_support_email": "butlerbensonagent@gmail.com"`

### Tests
1. "Can I bring my DSLR camera?" → semi_escalation: true, customer gets holding reply, relay alert sent to butlerbensonagent@gmail.com
2. Simulate reply from butlerbensonagent@gmail.com with [RELAY] in subject → Marina reformulates and sends to customer
3. "I want a refund" → requires_human: true, customer told crew will contact them, thread marked fully_escalated
4. Follow-up from customer on fully_escalated thread → Marina sends holding reply only
5. Escalations tab in Sheets: row has Chat Log as JSON array

---

## Brief 042 — Booking ref in confirmation + cross-thread memory (MEDIUM)

### Problem
1. `BF-YYYY-XXXXX` is generated at hold creation but never shown to the customer
2. Returning customer emails in a new thread — Marina has no memory of their booking
3. Chat log needed for escalations (solved by Brief 040's messages log, ref to it here)

### Booking ref in customer's confirmation email

Ref is generated in email_poller at hold success time (current behavior — keep timing).
Already stored in `th["flags"]["booking_ref"]` — it IS passed to marina_agent in thread_flags.

Add to `marina_agent.py` prompt:
```
When booking_ref is present in thread_flags, include it naturally in your confirmation reply.
Example: "Your booking reference is BF-2026-12345 — keep this handy for any future questions or changes!"
```

### Cross-thread memory: SQLite bookings table

Add to `state_registry.py` `_init_db()`:
```sql
CREATE TABLE IF NOT EXISTS bookings (
    booking_ref TEXT PRIMARY KEY,
    trip_key TEXT,
    customer_name TEXT,
    customer_email TEXT,
    date TEXT,
    departure_time TEXT,
    guests INTEGER,
    special_requests TEXT,
    payment_link TEXT,
    event_link TEXT,
    messages_json TEXT,
    status TEXT DEFAULT 'pending_payment',
    created_at TEXT NOT NULL
);
```

New public functions:
```python
def save_booking(booking_ref, fields, messages, flags) -> None:
    """Upsert booking record. Called after hold creation success."""

def get_booking(booking_ref) -> dict | None:
    """Returns full booking dict or None."""
```

### email_poller.py changes

After hold creation success: call `state_registry.save_booking(booking_ref, th["fields"], th["messages"], th["flags"])`

Booking ref detection in new/unknown threads (runs after marina_agent call):
```python
mentioned_ref = re.search(r'BF-\d{4}-\d{5}', body)
if mentioned_ref and not th["flags"].get("booking_ref"):
    past = state_registry.get_booking(mentioned_ref.group())
    if past:
        th["flags"]["loaded_booking_ref"] = mentioned_ref.group()
        for k in ("trip_key", "date", "guests", "customer_name", "departure_time"):
            if past.get(k) and not th["fields"].get(k):
                th["fields"][k] = past[k]
```

### marina_agent.py prompt addition

When `loaded_booking_ref` is in thread_flags:
```
RETURNING CUSTOMER CONTEXT:
Booking Ref: {loaded_booking_ref}
Trip: {trip_key} | Date: {date} | Guests: {guests} | Status: {status}
Previous conversation (last 3 messages):
{last 3 entries from messages_json}

The customer may want to: change their date, ask a follow-up question, check status, or report an issue.
Handle naturally based on their message. For refunds or cancellations: set requires_human: true.
```

### Files to modify
- `src/state_registry.py` — bookings table + save_booking / get_booking
- `src/email_poller.py` — save_booking after hold success; booking_ref regex detection; inject returning customer context into thread_flags before marina_agent call
- `src/marina_agent.py` — include booking_ref in confirmation reply; returning customer context section

### Tests
1. Complete full booking flow → Marina's confirmation reply contains "BF-2026-XXXXX"
2. New thread from same customer with "My ref is BF-2026-XXXXX" → Marina loads booking, responds with context
3. `bookings` table: all fields correct after successful hold
4. Returning customer asks to change date → Marina handles it, escalates if refund involved

---

## Brief 043 — Multi-trip booking in one thread (MEDIUM — do after 039–042)

### Problem
Customer: "I want to book Klein Curaçao for Saturday AND a sunset cruise for Sunday."
Thread state tracks only one active booking.

### Approach
After `hold_created` = true:
- Copy current booking (fields + flags + booking_ref) into `th["completed_bookings"]` list
- Reset `th["fields"]` and booking-related flags for fresh intake
- Marina detects "I also want to book..." and starts new intake naturally

Safeguard: `max_bookings_per_customer: 3` in `client.json` booking_rules section.
Check: `len(th.get("completed_bookings", [])) >= max` → Marina declines politely.

### Files
- `email_poller.py` — completed_bookings accumulation, post-hold reset logic, max check
- `marina_agent.py` — prompt: multi-booking awareness, completed_bookings summary in context
- `client.json` — add `"max_bookings_per_customer": 3` to booking_rules

---

## Brief 044 — Marina tone (LATER — do not start until 039–043 complete)

**DO NOT START THIS BRIEF until all functional briefs are done.**

Research needed first: Caribbean charter / watersports customer support writing style.
Check: TripAdvisor reviews of BlueFinn and similar operators, WhatsApp support transcripts if available.
Goal: Marina sounds like a real person, not an AI. Shorter sentences, less enthusiasm punctuation, natural warmth.
Implementation: prompt-only changes to `marina_agent.py`.

---

## CONFIRMED VALUES (hardcode these in briefs — do not re-ask)

| Value | Setting |
|-------|---------|
| Marina's inbox | `hello@wetakeyourjob.com` |
| Demo support/relay email | `butlerbensonagent@gmail.com` |
| Production support email | `info@bluefinncharters.com` |
| Klein Curaçao 08:00 (BlueFinn2) calendar_id | `4ce23ea0e7ec08da249c778969d71c199b8aaf7bf6114efac4fae7e0928f1b31@group.calendar.google.com` |
| Klein Curaçao 08:30 (BlueFinn1) calendar_id | `9f25610370f0f57fa395735502fcff767ba8276ee5a280d028fee7f003054928@group.calendar.google.com` |
| Capacity — klein_curacao | 30 |
| Capacity — snorkeling_3in1 | 20 |
| Capacity — west_coast_beach | 25 |
| Capacity — sunset_cruise | 20 |
| Capacity — jet_ski | 4 |

---

## Files affected across all briefs

| File | Briefs |
|------|--------|
| `config/client.json` | 039 (capacity + departure calendar_ids), 040 (support emails), 043 (max_bookings) |
| `src/state_registry.py` | 039 (trip_bookings table + 5 functions), 042 (bookings table + 2 functions) |
| `src/gws_calendar.py` | 039 (check_availability rewrite + create_hold departure calendar_id) |
| `src/email_poller.py` | 039, 040, 042, 043 |
| `src/marina_agent.py` | 039 (spots_remaining prompt), 040 (escalation flags + relay mode), 042 (booking_ref + returning customer) |
| `src/sheets_writer.py` | 040 (log_escalation + messages JSON) |
| `src/format_sheets.py` | 040 (Escalations tab Chat Log column) |

## Execution order
**039 → 040 → 042 → 043 → 044**
Do not skip ahead. Each brief depends on the previous.
