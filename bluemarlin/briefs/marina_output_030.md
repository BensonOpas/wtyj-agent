# OUTPUT_030 — Hold Failure Reply

## Files modified
- `bluemarlin/src/marina_agent.py`
- `bluemarlin/src/email_poller.py`

## Files created
- `bluemarlin/briefs/OUTPUT_030.md` (this file)

---

## Changes made

### marina_agent.py — _build_prompt()

**reply field description** — replaced to focus on hold success case:
Old: generic warm reply description
New: "full reply to send when the booking hold is successfully created —
warm, celebratory, includes the booking summary, payment link placeholder
[PAYMENT_LINK], payment methods, hold duration, what to bring"

**reply_hold_failed field** — added after reply in JSON structure:
"reply to send ONLY if the calendar slot is unavailable or hold creation
fails — apologetic, offers to find another date or time, does NOT confirm
the booking, does NOT include a payment link — only write this field when
booking_confirmed is true in thread flags or you are sending a booking
confirmation"

reply_hold_failed is NOT added to _REQUIRED_RESPONSE_FIELDS — it is optional.
Fallback validation continues to work without it.

**[PAYMENT_LINK] instruction** — added to BOOKING CONFIRMATION BEHAVIOUR
section after "If unclear: ask for clarification.":
"When writing the reply for a confirmed booking (booking_confirmed is true
and hold will be attempted), include the exact string [PAYMENT_LINK] in the
reply where the payment link should appear. Python will replace [PAYMENT_LINK]
with the real payment URL before sending."

File header: LAST MODIFIED Brief 029 → Brief 030

### email_poller.py — main loop booking flow

**reply_text default** — added after `fields_now = th["fields"]` before
the hold trigger condition:
```python
reply_text = result["reply"]
```

**hold success block** — after pay_link is generated, added:
```python
reply_text = result["reply"].replace("[PAYMENT_LINK]", pay_link)
```

**hold failure block** — replaced `result["reply"]` with:
```python
failure_reply = result.get("reply_hold_failed") or result["reply"]
smtp_send(from_email, "Re: " + subj, failure_reply, ...)
```

**final booking smtp_send** — updated from `result["reply"]` to `reply_text`.

File header: LAST MODIFIED Brief 029 → Brief 030

---

## Test results

| # | Test | Result |
|---|------|--------|
| 1 | marina_agent imports cleanly | PASS |
| 2 | email_poller imports cleanly | PASS |
| 3 | reply_hold_failed and [PAYMENT_LINK] in source | PASS |
| 4 | reply_hold_failed not in _REQUIRED_RESPONSE_FIELDS | PASS |
| 5 | reply_hold_failed present and non-empty when booking_confirmed; [PAYMENT_LINK] in reply | PASS |
| 6 | reply_hold_failed absent/empty for inquiry | PASS |
| 7 | email_poller smtp called with reply_hold_failed on hold failure | PASS |
| 8 | [PAYMENT_LINK] replaced with real URL in reply on hold success | PASS |
| 9 | fallback returns without reply_hold_failed on API exception | PASS |
| 10 | slot unavailability instruction present in source | PASS |
