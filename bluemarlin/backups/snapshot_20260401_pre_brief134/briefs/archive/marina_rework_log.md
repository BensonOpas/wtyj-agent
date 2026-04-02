# MARINA REWORK LOG
## The thinking behind the system redesign — recorded for future reference
**Written:** March 5, 2026
**Author:** Claude (technical architect), session with Benson
**Purpose:** Full record of the thought process, decisions, mistakes, pivots, and
reasoning behind the Marina agent rework. To be read by anyone joining the project
or revisiting architectural decisions.
---
## WHERE IT STARTED
The original system was built incrementally across Briefs 001–021. It worked —
emails came in, the system replied, bookings were attempted. But it had accumulated
a significant amount of what we called "architectural drift."
The core problem: Python was making language decisions.
When an email arrived, the system would:
- Run the message through a Python function that pattern-matched against hardcoded
  keyword lists to classify the intent ("booking", "inquiry", "cancellation" etc.)
- Run the date through a separate Python classifier with lists called VAGUE_PATTERNS
  and RESOLVABLE_PATTERNS
- Match the experience description against hardcoded package name strings
- Check whether the customer was confirming a date by looking for words like
  "yes", "sure", "ok" in a Python list called CONFIRM_WORDS
- Select a pre-written reply by calling one of 9 static safe_X_reply() functions
  (safe_booking_unclear_reply, safe_date_unclear_reply, etc.)
This was not a deliberate choice — it grew organically. Each brief solved a specific
problem (date ambiguity, experience matching, confirmation handling) by adding Python
logic. The logic made sense in isolation. Together it became a rule engine that was
trying to understand language, which is exactly what Claude is for.
The symptoms:
- Replies felt robotic because they came from static templates
- Edge cases broke silently — unusual phrasing fell through the classifiers
- Each new brief added more patterns and more edge cases
- email_poller.py grew to 1241 lines
- The system could not understand "I'd love to do the sunset one" because it was
  looking for exact package name matches
This was documented in ARCHITECTURE_DRIFT_LOG.md and discussed at length before
the rework began.
---
## THE DECISION TO REWORK
The rework decision was not made lightly. The system was live and handling real
emails. The question was whether to keep patching the existing architecture or
start from correct first principles.
The architectural principle we kept coming back to:
  Python routes. Claude understands.
Everything in email_poller.py that was trying to understand language needed to move
into a single Claude API call. Python's job was to receive structured output from
that call and act on it — save state, call APIs, send the reply. Nothing more.
The rework was phased deliberately:
Phase 1 — Brief 022: Create client.json and config_loader.py. Move all business
data out of hardcoded values and into a single source of truth. This was a
prerequisite for everything else — the Claude prompt needed real data to inject,
not placeholder strings.
Phase 2 — Brief 023: Build marina_agent.py in isolation. One function,
process_message(), one Claude API call, structured JSON output. Test it completely
before touching email_poller.py. This isolation was important — we wanted to know
marina_agent worked correctly before ripping out the existing email_poller logic.
Phase 3 — Brief 024: Rework email_poller.py. Remove all 19 drift functions, all
static reply templates, all Python language classifiers. Wire marina_agent in as
the single Claude call. Reduce from 1241 lines to 452 lines.
---
## WHAT WAS IN client.json
client.json became the single source of truth for all BlueFinn business data:
- Five trips with real pricing: Klein Curaçao ($120 adult, $65 child 4-12, under 4
  free), 3-in-1 Snorkeling ($110), West Coast Beach ($120), Sunset Cruise ($79),
  Jet Ski ($135)
- Real departure times and vessels (where confirmed by BlueFinn)
- FAQ section with common questions
- Booking rules: required fields, group threshold (15+), advance booking typical days
- Payment methods: credit card, iDeal, Apple Pay, Google Pay, Amex, cash at office
- Marina's persona and agent signature
- Common sense knowledge: timezone, currency, what to bring, turtle/dolphin notes
- [VERIFY] placeholders for: cancellation policy, private charter pricing, vessel
  names for snorkeling/west coast/sunset, shade on boats, snorkeling duration
Several of these [VERIFY] items are still outstanding. BlueFinn has not confirmed
them. They do not block the system from working — Claude skips [VERIFY] fields
naturally — but they represent gaps in the business data.
---
## MARINA_AGENT.PY — HOW IT WORKS
marina_agent.process_message() takes:
- from_email, subject, body (the inbound email)
- thread_fields (what's been collected so far in this conversation)
- thread_flags (state flags from previous turns)
It builds a prompt that injects:
- Full Marina persona and business identity
- All five trips with real pricing and schedules
- FAQ
- Booking rules and payment policy
- Today's date in Curaçao timezone
- Thread context (what fields and flags are already known)
- The inbound message
Claude returns a JSON object with:
- intents: list (booking, inquiry, cancellation, reschedule, complaint, social,
  off_topic)
- fields: dict of extracted booking fields
- confidence: high / medium / low
- reply: the full natural language reply to send
- clarifications_needed: list of questions still outstanding
- requires_human: boolean
- flags: dict of state flags for Python to persist
- internal_note: one sentence for the operator log
Python receives this, merges fields and flags into thread state, routes on
structured values, calls calendar.js and payment_stub if appropriate, sends
the reply exactly as Claude wrote it. Python never reads the reply content.
Python never interprets language.
The model used: claude-sonnet-4-6. max_tokens: 2048.
---
## BUGS FOUND IN LIVE TESTING AND HOW THEY WERE FIXED
**Bug 1 — date field returned as natural language**
During live testing, marina_agent returned dates like "April 20" and "April 5"
instead of YYYY-MM-DD. calendar.js does date.split('-').map(Number) which requires
YYYY-MM-DD. Any natural language date caused calendar.js to throw "Invalid time
value" and the hold failed silently — Marina sent a booking confirmation but no
hold was created.
Fix (Brief 027): Added explicit date format instruction to the prompt. Claude must
return date in YYYY-MM-DD format. If it cannot resolve the date to a specific
YYYY-MM-DD, it must omit the field and add a clarification question instead.
**Bug 2 — departure_time never extracted**
Klein Curaçao has two departure options (08:00 BlueFinn2, 08:30 BlueFinn1).
When a customer said "08:30 works for us", marina_agent never extracted that as
a field because departure_time was not in the extractable fields list. email_poller
always fell back to departures[0]["time"] from config regardless of customer choice.
Fix (Brief 027): Added departure_time to extractable fields in the prompt. Added
priority logic to create_calendar_hold — use fields_now.get("departure_time") if
present, otherwise fall back to config.
**Bug 3 — thread key breaks on subject change**
The system groups emails into threads using sender email + normalized subject.
When a customer replies with a slightly different subject (e.g. starting a thread
as "Klein Curaçao trip" then replying as "booking"), the thread key changes and
the system creates a new thread with no previous fields. Context is lost.
During testing this caused Marina to ask for a date the customer had already
provided, and to misread "April 20" as "April 5" (today's date at processing time).
Status: Known open issue. Not yet fixed. Solution is to use email headers
(Message-ID, In-Reply-To, References) for thread matching instead of subject.
This is more robust and matches how email clients actually track threads.
**Bug 4 — vague date caused hold creation**
Customer said "sometime next month." Marina picked a specific date (March 25) and
created a real Google Calendar hold without the customer confirming any date.
This created a phantom hold for a date that was never agreed.
Root cause: The date format instruction added in Brief 027 was not strong enough.
Claude inferred a date from "next month" rather than treating it as unresolvable.
Status: Known open issue. Needs stronger prompt instruction. Phantom hold was
manually deleted from Google Calendar.
**Bug 5 — complaint and cancellation not escalating to human**
When a customer complained or requested a cancellation, Marina tried to handle
it herself by asking for booking details. This is wrong — Marina has no access
to booking records and cannot process refunds or investigate complaints. These
must go to a human immediately.
Status: Known open issue. Needs prompt instruction specifying that when
requires_human is true for complaint or cancellation, Marina should acknowledge
warmly and tell the customer the Guest Experience Team will be in touch — not
ask for details.
---
## WHAT WAS TESTED MANUALLY (live system)
All tests were run by sending real emails to hello@wetakeyourjob.com.
1. Standard booking flow — PASS
   Customer: "Hi I'd like to book Klein Curaçao April 20 for 2 people"
   Marina asked for departure time and child/adult confirmation before creating hold.

2. Social + booking in same message — PASS
   Customer commented on Curaçao weather + booking request.
   Marina responded to both naturally.
3. Full booking completion — PASS
   Sarah test: 4 adults, April 20, Klein Curaçao, chose 08:00 BlueFinn2.
   Marina confirmed all details, created hold, sent payment link with correct total
   ($480), correct vessel, correct inclusions, correct payment methods.
4. Large group (25 people) — PASS
   Marina correctly flagged for human and provided contact details without
   attempting a hold.
5. Off-topic redirect — PASS
   Restaurant recommendation request. Marina redirected to TripAdvisor naturally
   and pivoted back to bookings.
6. Multi-language (Dutch) — PASS
   Marina replied in Dutch, confirmed trip availability on correct days, asked
   for contact details before creating hold.
7. Infant edge case — PASS
   "2 adults and a baby (8 months)". Marina counted 2 guests, identified infant
   as under 4 and free, calculated correct total.
8. Complaint — PARTIAL PASS
   Tone was correct, escalation was acknowledged, but Marina incorrectly tried to
   gather booking details rather than deferring entirely to the Guest Experience Team.
9. Cancellation — PARTIAL PASS
   Same issue as complaint — Marina asked for details instead of deferring.
10. Vague date — FAIL
    "Sometime next month" caused Marina to guess a date and create a phantom hold.
---
## THE NEXT PHASE — WHAT WE ARE PLANNING
At the time of writing this log, we have identified several significant improvements
needed. These are being planned but not yet written as briefs. This section records
the thinking so it is not lost.
**1 — Booking confirmation step before hold creation**
Currently, when all required fields are present, the system creates a hold
immediately. This is too fast. Customers paying $79–$480 expect a moment to review
before committing. The industry standard for charter and tour operators is an
explicit confirmation step.
Proposed flow:
- All fields present → Marina sends a booking summary and asks "Shall I lock this
  in for you?"
- Customer confirms → hold created, payment link sent
- Customer changes something → Marina updates fields and re-confirms
Implementation: new thread flag awaiting_booking_confirmation. Marina sends summary
on first complete set of fields, creates hold only on explicit customer yes.
Claude interprets the yes — "sure", "let's do it", "ja", anything — no Python
pattern matching.
**2 — Persistent booking record in Google Sheets**
Currently the only permanent record of a booking is the Google Calendar hold event
and an ephemeral thread state file. If a customer emails 2 weeks after their trip
to complain, Marina has no memory of the booking. Staff have no central record to
query.
Proposed: at hold creation time, write a row to a dedicated Bookings sheet with:
booking reference (BF-2026-XXXX incrementing), customer name, email, phone, trip,
date, guests, departure time, total price, hold event ID, timestamp, status.
This row becomes the source of truth for:
- Post-trip complaints (staff look up by reference or name)
- Cancellation requests (verify identity by matching name + email against record)
- Refund processing (staff update status in sheet)
- Any future customer contact referencing a past booking
The booking reference is included in every confirmation email Marina sends.
**3 — Google Sheets full rework**
The current Sheets integration was built early and is not well structured. Different
types of events (bookings, inquiries, complaints, special requests) currently end
up mixed together or in the wrong tabs. This needs to be reorganised with clear
tabs: Bookings, Escalations, Inquiries. Each tab with consistent columns and a
clear purpose. A separate brief with a Sheets redesign tutorial to guide the layout.
**4 — Escalation path for complaints and refunds (Point 1)**
When requires_human fires for complaint or cancellation:
- Marina sends warm acknowledgement to customer — "our Guest Experience Team will
  be in touch with you shortly"
- System sends internal email to info@bluefinncharters.com with full context:
  customer name, email, thread summary, fields collected, marina's internal_note
- Sheets gets a row in the Escalations tab: timestamp, customer, intent, status
  Pending Human
- BlueFinn staff reply directly to customer from info@bluefinncharters.com
- Customer receives a reply from a real person who already knows their situation
**5 — Supervised handoff for medium complexity (Point 2)**
For cases that don't warrant full escalation but need human judgment — specific
questions, special arrangements, accessibility needs:
- System sends a WhatsApp message to a designated BlueFinn staff number with
  thread context and prompt to draft a reply
- Staff reply via WhatsApp Web or phone
- System sends the reply via smtp_send() from hello@wetakeyourjob.com as Marina
- Customer sees no break in conversation
Dependency: WhatsApp Business API (Twilio or 360dialog). Not yet built.
Planned for post-pitch.
**6 — Email thread continuity fix**
Use Message-ID and In-Reply-To headers for thread matching instead of sender +
subject. This is the correct RFC 2822 approach and matches how email clients
track threads natively. Eliminates the lost context bug when customers change
subject.
**7 — Booking reference system**
Generate BF-YYYY-XXXX booking references at hold creation. Include in confirmation
email, Sheets record, and calendar hold description. Use as the identity
verification anchor for cancellation and post-trip contact.
**8 — Identity verification for cancellations**
No KYC or biometric infrastructure needed at BlueFinn's scale. Standard approach:
require booking reference + original email address for any cancellation or refund
request. Staff cross-reference against Sheets record before processing. Impersonation
requires knowing both pieces of information.
**9 — Cancellation policy**
BlueFinn has not yet provided their cancellation policy. This is a [VERIFY] item
in client.json. The industry standard for tour operators at this price point is
tiered: full refund 7+ days before departure, partial refund 2–7 days, no refund
within 24 hours or no-show. BlueFinn needs to confirm their specific terms before
Marina can communicate them accurately.
**10 — Post-trip follow-up**
Not yet planned but worth noting: the booking record in Sheets enables post-trip
follow-up emails. After the trip date passes, a script could identify completed
bookings and send a thank-you + review request from Marina. This is a future
enhancement, not a current priority.
---
## ARCHITECTURE PRINCIPLES — NON-NEGOTIABLE
These were established early and must not be violated in any future brief:
1. ONE Claude API call per inbound message. Via marina_agent.process_message().
   Never add a second Claude call inside email_poller.
2. Python routes on structured values only. Python never reads reply content,
   never pattern-matches language, never classifies intent. Claude does all of that.
3. All replies are Claude-generated. No static reply templates. No safe_X_reply()
   functions. Ever.
4. All business values live in client.json. Never hardcode trip names, prices,
   departure times, or any BlueFinn-specific data in source files.
5. Claude Code never browses the web. All external data is fetched by the architect
   (this chat) and included in briefs as source material.
6. No brief is written without seeing the current state of every file it modifies.
---
## FILES AND THEIR CURRENT STATE (as of Brief 027)
| File | Lines | Last Modified | Purpose |
|------|-------|---------------|---------|
| email_poller.py | ~452 | Brief 027 | Main loop, orchestrator |
| marina_agent.py | ~175 | Brief 027 | Single Claude call, structured output |
| config_loader.py | 94 | Brief 022 | Read-only interface to client.json |
| client.json | — | Brief 026 | Business data, trip info, real calendar IDs |
| calendar.js | ~76 | Brief 026 | Google Calendar hold creation via Node |
| claude_client.py | 44 | Brief 001 | Original Claude wrapper (superseded) |
| state_registry.py | — | Brief 004 | Thread state persistence |
| sheets_writer.py | — | Early brief | Google Sheets logging (needs rework) |
| payment_stub.py | — | Early brief | Payment link generation (stub) |
---
## THINGS THAT SURPRISED US DURING DEVELOPMENT
1. Claude was better at inferring context than expected. When given full thread
   history and a message like "08:30 works" with no other context, it correctly
   extracted departure_time: "08:30" and associated it with the Klein Curaçao
   departure options from the trips context.
2. Claude spontaneously checked day-of-week availability. In the Dutch language
   test, the customer asked for April 25. Claude correctly identified it as a
   Saturday and confirmed the Sunset Cruise runs on Saturdays — without being
   explicitly prompted to check days_available. This came from the trip data in
   the prompt.
3. The Unicode escape bug. Brief 024's Write tool stored "Curaçao" and "—" as
   literal escape sequences (\u00e7, \u2014) in email_poller.py instead of actual
   Unicode characters. This caused the smtp_send From header and anti-loop message
   to display as garbled text. Brief 025 fixed these as part of the BlueFinn
   cleanup. Worth watching on any future file writes.
4. "Invalid time value" was a misleading error. The actual problem was date format
   (natural language vs YYYY-MM-DD), not time format. The error came from
   JavaScript's date parsing after the date string failed to split correctly.
   Took a full test cycle to trace.
5. The system handled the infant test better than expected. "2 adults and a baby
   (8 months)" → guests: 2, under-4 pricing surfaced correctly, total calculated
   as $240 not $360. This was purely Claude's reasoning from the pricing structure
   in the prompt — no special handling in Python.
---
## WHAT THIS SYSTEM IS AND IS NOT
**What it is:**
An autonomous email booking agent for a small charter business. It handles
the majority of incoming booking inquiries end to end — collecting information,
answering questions, creating calendar holds, and sending payment links — with
no human involvement. It handles multi-language naturally. It understands human
speech dynamically because Claude is doing the understanding, not Python.
**What it is not:**
A replacement for human judgment on complex cases. It is explicitly designed to
escalate — to a human, gracefully, with full context — whenever something exceeds
its scope. Complaints, refunds, large groups, identity verification, edge cases.
The escalation path is not a failure mode. It is a designed feature.
**The standard it should be held to:**
Would a customer who booked a $480 family trip feel well-served by this system?
If yes, it is working. If they feel confused, ignored, rushed, or mishandled,
something is wrong and needs fixing.
