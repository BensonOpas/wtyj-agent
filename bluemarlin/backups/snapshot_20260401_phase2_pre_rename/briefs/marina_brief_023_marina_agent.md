# BRIEF 023 — marina_agent.py — Unified Claude Call (Isolated Test)
**Brief number:** 023
**Status:** Ready to execute
**Files created:** bluemarlin/src/marina_agent.py
**Files modified:** None
**Depends on:** Brief 001 (claude_client.py), Brief 022 (config_loader.py)
**Blocks:** Brief 024 (full refactor of email_poller.py)

---

## CONTEXT

The current system makes multiple Claude API calls per email and uses
Python to classify, route, and respond to natural language. This is
documented architectural drift (ARCHITECTURE_DRIFT_LOG.md).

The correct architecture: one Claude call per inbound message. Claude
returns structured JSON. Python sends the reply, persists state, and
logs. Python never makes language decisions.

This brief builds and tests that unified call in isolation as a new
standalone file. It does not touch email_poller.py. Brief 024 wires
it in.

---

## SOURCE MATERIAL

config_loader.py (Brief 022) exposes:
- get_business() — name, agent name, signature, languages
- get_trips() — all five trips with pricing, schedules, inclusions
- get_faq() — all FAQ entries
- get_booking_rules() — required fields, group threshold
- get_payment() — methods, hold duration, cash policy
- get_common_sense_knowledge() — timezone, currency, Marina persona

claude_client.py (Brief 001) exposes:
- complete(prompt, system=None) -> str
- extract(prompt) -> dict

---

## WHAT TO BUILD

Create bluemarlin/src/marina_agent.py with one public function:

```
process_message(
    from_email: str,
    subject: str,
    body: str,
    thread_fields: dict,
    thread_flags: dict
) -> dict
```

### Behaviour required

Makes exactly one Claude API call per invocation via claude_client.
The prompt must inject all of the following:
- Marina's persona and business details from config_loader
- All five trips with pricing, schedule, inclusions from config_loader.
  Skip any field whose value starts with [VERIFY
- All FAQ entries from config_loader.
  Skip any answer that starts with [VERIFY
- Booking rules and payment policy from config_loader
- Today's date in Curaçao timezone (America/Curacao, UTC-4)
- thread_fields — what has already been collected this thread
- thread_flags — current conversation state
- The inbound message: from_email, subject, body

Claude must be instructed to respond with ONLY a JSON object
with exactly these fields:
- intents — array, one or more of: booking, inquiry, cancellation,
  reschedule, complaint, social, off_topic
- fields — extracted booking fields: experience, date, guests,
  customer_name, phone, special_requests. Only fields that are
  present and certain.
- confidence — one of: high, medium, low
- reply — full reply to send to the customer. Warm, natural, signed
  with agent signature. Never a template. Never robotic.
- clarifications_needed — array of strings. Questions Marina still
  needs answered before proceeding.
- requires_human — boolean. True when: group of 15 or more guests,
  complaint with no booking context, or explicit request to speak
  to a human.
- flags — conversation state flags for Python to persist into
  thread_flags.
- internal_note — one sentence for the operator log. Never shown
  to the customer.

### On failure

If the Claude API call fails or the response cannot be parsed as
valid JSON with the required fields, process_message must return
a safe fallback dict — not raise. The fallback reply must be a
genuine natural language response directing the customer to share
their preferred date, number of guests, and experience. It must
be signed with the agent signature from config_loader.

### Constraints

- Exactly one Claude API call per process_message() invocation
- All business values sourced from config_loader — nothing hardcoded
  in the source file
- The reply field always comes from Claude — never constructed
  in Python
- File header follows project conventions (FILE, CREATED,
  LAST MODIFIED, DEPENDS ON)
- Make the API call directly using anthropic.Anthropic() inside
  marina_agent.py with max_tokens set to 2048. Do not use
  claude_client.extract() or claude_client.complete(). Do not
  modify claude_client.py.
- JSON parsing and code fence stripping must be handled inside
  marina_agent.py — strip markdown code fences if present, then
  parse with json.loads()

---

## TESTS

All tests must be run from the project root with bluemarlin/src
on the path.

**Test 1 — returns valid structure**
Call process_message with a simple price inquiry. Assert the result
is a dict containing reply (non-empty string, more than 20 chars),
intents (list), and requires_human (bool).

**Test 2 — booking intent detected**
Call process_message with a message clearly requesting a Klein
Curaçao trip for April 15 for 4 people. Assert "booking" is in
result["intents"].

**Test 3 — guests field extracted**
Call process_message with a message booking the sunset cruise on
April 20 2026 for 2 guests. Assert result["fields"]["guests"]
equals 2 (int or string "2" both acceptable).

**Test 4 — large group triggers requires_human**
Call process_message with a message requesting a booking for
20 people. Assert result["requires_human"] is True.

**Test 5 — reply is signed**
Call process_message with a general availability question.
Assert result["reply"] contains "BlueFinn" or "Marina".

**Test 6 — thread context is consumed**
Call process_message with body "Yes that date works for me",
thread_fields containing experience, date, and guests already
collected, and thread_flags containing awaiting_date_confirmation
True. Assert result is a dict with a reply.

**Test 7 — off topic classified correctly**
Call process_message with body "What is the capital of France?"
Assert "off_topic" in result["intents"].

**Test 8 — empty body does not raise**
Call process_message with empty subject and empty body.
Assert result is a dict and "reply" is in result.

---

## SUCCESS CONDITION

All 8 tests pass. marina_agent.py is importable from bluemarlin/src
without error. email_poller.py is untouched and the live service
is unaffected.

---

## ROLLBACK

No existing files are modified. Delete marina_agent.py if it causes
any import error. Live system unaffected.
