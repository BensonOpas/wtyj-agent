# BRIEF 030 — Hold Failure Reply

**Brief number:** 030
**Status:** Ready to execute
**Files modified:** bluemarlin/src/marina_agent.py, bluemarlin/src/email_poller.py
**Files created:** None
**Depends on:** Brief 029 (marina_agent.py, email_poller.py)
**Blocks:** Nothing — fixes live bug

---

## CONTEXT

When a hold creation fails (slot unavailable, calendar error, etc),
email_poller sends whatever reply Claude wrote — which assumed the
hold would succeed. The customer receives a confirmation message for
a booking that does not exist.

The fix: Claude writes two replies when a booking confirmation is
being processed — reply (assumes success) and reply_hold_failed
(slot unavailable). Python picks the correct one based on the hold
outcome. One Claude call. No new API calls. No static templates.

---

## SOURCE MATERIAL

Files confirmed seen this session:

marina_agent.py — 231 lines, Brief 029. JSON response structure
defined at end of _build_prompt(). Current reply field is a single
string. flags field has explicit key names.

email_poller.py hold failure block (lines ~360–385, Brief 029):
When res.get("ok") is False:
  logs hold_failed
  calls sheets_writer.log_hold_failed
  calls smtp_send with result["reply"]
  continues

email_poller.py hold success block (lines ~386–420, Brief 029):
When res.get("ok") is True:
  sets hold flags
  calls payment_stub
  calls sheets_writer.log_hold_created
  logs hold_created
Then sends result["reply"] after the if/else block.

---

## PART 1 — marina_agent.py

### Change 1 — Add reply_hold_failed to JSON schema

In _build_prompt(), find the JSON structure definition. After the
"reply" field definition, add a new field:
```
  "reply": "<full reply to send when the booking hold is successfully created — warm, celebratory, includes the booking summary, payment link placeholder [PAYMENT_LINK], payment methods, hold duration, what to bring>",
  "reply_hold_failed": "<reply to send ONLY if the calendar slot is unavailable or hold creation fails — apologetic, offers to find another date or time, does NOT confirm the booking, does NOT include a payment link — only write this field when booking_confirmed is true in thread flags or you are sending a booking confirmation>",
```

Note: reply_hold_failed is optional. Claude should only write it
when booking_confirmed is true or awaiting_booking_confirmation is
being resolved. For all other message types (inquiries, complaints,
off-topic) reply_hold_failed should be omitted or empty string.

Also add reply_hold_failed to _REQUIRED_RESPONSE_FIELDS? No —
it is optional. Do NOT add it to _REQUIRED_RESPONSE_FIELDS.
The fallback validation check must not fail if it is absent.

### Change 2 — Add [PAYMENT_LINK] placeholder instruction

In the BOOKING CONFIRMATION BEHAVIOUR section, add this line after
the existing confirmation behaviour instructions:

When writing the reply for a confirmed booking (booking_confirmed
is true and hold will be attempted), include the exact string
[PAYMENT_LINK] in the reply where the payment link should appear.
Python will replace [PAYMENT_LINK] with the real payment URL before
sending.

Update file header: LAST MODIFIED Brief 029 → Brief 030

---

## PART 2 — email_poller.py

### Change 1 — Replace [PAYMENT_LINK] in reply before sending

In the hold success block, after pay_link is generated, add:
```python
reply_text = result["reply"].replace("[PAYMENT_LINK]", pay_link)
```

Then in the smtp_send call at the end of the booking flow, replace:
```python
smtp_send(from_email, "Re: " + subj, result["reply"], ...)
```
with:
```python
smtp_send(from_email, "Re: " + subj, reply_text, ...)
```

Note: reply_text must be defined before the hold success/fail
branching so it is in scope for the smtp_send at the end. Set
a default before the if block:
```python
reply_text = result["reply"]
```

Then inside the hold success block, override it:
```python
reply_text = result["reply"].replace("[PAYMENT_LINK]", pay_link)
```

### Change 2 — Use reply_hold_failed on hold failure

In the hold failure block, replace:
```python
smtp_send(from_email, "Re: " + subj, result["reply"], ...)
```
with:
```python
failure_reply = result.get("reply_hold_failed") or result["reply"]
smtp_send(from_email, "Re: " + subj, failure_reply, ...)
```

Update file header: LAST MODIFIED Brief 029 → Brief 030

---

## TESTS

**Test 1 — marina_agent imports cleanly**
Import marina_agent. Assert no ImportError.

**Test 2 — email_poller imports cleanly**
Import email_poller. Assert no ImportError.

**Test 3 — reply_hold_failed present in source**
Read marina_agent.py as text. Assert "reply_hold_failed" in source.
Assert "[PAYMENT_LINK]" in source.

**Test 4 — reply_hold_failed not in _REQUIRED_RESPONSE_FIELDS**
Read marina_agent.py as text. Assert "reply_hold_failed" not in
the _REQUIRED_RESPONSE_FIELDS set definition.

**Test 5 — process_message returns reply_hold_failed when
booking_confirmed is true**
Call process_message with body: "Yes let's do it",
thread_fields={"experience": "Klein Curaçao Trip",
  "date": "2026-04-20", "guests": 2,
  "trip_key": "klein_curacao"},
thread_flags={"awaiting_booking_confirmation": True}
Assert "reply_hold_failed" in result
Assert result["reply_hold_failed"] is a non-empty string
Assert "[PAYMENT_LINK]" in result.get("reply", "")

**Test 6 — reply_hold_failed absent or empty for inquiry**
Call process_message with body:
"What trips do you have available?",
thread_fields={}, thread_flags={}
result_reply_failed = result.get("reply_hold_failed", "")
Assert not result_reply_failed or len(result_reply_failed) < 20

**Test 7 — email_poller uses reply_hold_failed on hold failure**
Mock create_calendar_hold to return ok=False, error="UNAVAILABLE".
Mock smtp_send and capture the body argument.
Inject a result dict with reply="success reply" and
reply_hold_failed="sorry slot unavailable reply".
Trigger the hold failure path.
Assert smtp_send was called with "sorry slot unavailable reply".

**Test 8 — email_poller replaces [PAYMENT_LINK] in reply on
hold success**
Mock create_calendar_hold to return ok=True, eventId="abc".
Mock payment_stub to return payment_id="testpay123".
Mock smtp_send and capture the body argument.
Inject a result dict with reply="Pay here: [PAYMENT_LINK]".
Trigger the hold success path.
Assert "[PAYMENT_LINK]" not in captured body.
Assert "testpay123" in captured body or "demo.pay" in captured body.

**Test 9 — fallback still valid without reply_hold_failed**
Call process_message with a message that forces the fallback
(mock anthropic to raise Exception).
Assert result is the fallback dict.
Assert "reply" in result.
Assert process does not raise.

**Test 10 — reply_hold_failed source instruction present**
Read marina_agent.py as text.
Assert "UNAVAILABLE" in source or "slot is unavailable" in source
or "calendar slot" in source.

---

## SUCCESS CONDITION

All 10 tests pass. When a hold fails, the customer receives an
apology with an offer to find another date — not a false
confirmation. Payment link is injected at send time, not
hardcoded by Claude.

---

## ROLLBACK

Changes are additive. reply_hold_failed is optional and Python
falls back to result["reply"] if absent. The [PAYMENT_LINK]
replacement only fires in the hold success path. Neither change
affects any other flow.
