# BRIEF 058 — Fix: Booking Ref Missing from Confirmation Reply
**Status:** Draft
**Files:** `src/marina_agent.py`, `src/email_poller.py`
**Depends on:** Brief 054 (booking_ref generation), Brief 051 ([PAYMENT_LINK] pattern)
**Blocks:** —

---

## Context

Brief 054 added booking ref generation (BF-YYYY-XXXXX) and instructed Marina to include it in the confirmation reply. Live testing shows the ref is absent from confirmation emails.

Root cause: `marina_agent.process_message()` is called at email_poller.py line 685, where `reply_text = result["reply"]` is set. The booking_ref is only generated at line 899 — well after the Claude call returns. Marina cannot include a value that does not exist when she writes the reply.

Brief 054's prompt instruction ("include booking_ref when present in thread_flags") is logically impossible to satisfy at confirmation time — booking_ref is never in thread_flags when Marina is called.

---

## Why This Approach

`[PAYMENT_LINK]` already solves this exact problem. Marina writes a literal placeholder in her reply; Python replaces it at line 954 after the hold succeeds. The same mechanism applied to booking_ref costs one prompt line and one `.replace()` call — no new mechanism, no new state, no pre-generation of refs that might be abandoned on hold failure.

Alternatives rejected:
- Pre-generate booking_ref before the Claude call and pass it in: creates orphan refs on hold failure. The ref is only meaningful after a successful manifest creation.
- Append ref as a hardcoded string after Marina's reply: violates Rule 3 (static reply string). Claude must control phrasing.
- Two Claude calls — one to generate reply, one with the ref: violates Rule 1.

---

## Source Material

### email_poller.py — line 685
```python
reply_text = result["reply"]   # Marina's reply is set here, before booking_ref exists
```

### email_poller.py — line 899–900
```python
booking_ref = f"BF-{time.strftime('%Y')}-{int(time.time()) % 100000:05d}"
th["flags"]["booking_ref"] = booking_ref
```

### email_poller.py — line 954 (existing [PAYMENT_LINK] replacement — add booking_ref on the next line)
```python
reply_text = reply_text.replace("[PAYMENT_LINK]", pay_link)
```

### marina_agent.py — lines 164–168 (current broken instruction)
```python
BOOKING REFERENCE:
When booking_ref is present in thread_flags AND you are writing a booking
confirmation reply (booking_confirmed: true), you MUST include the booking
reference naturally in your reply. Example: "Your booking reference is
BF-2026-12345 — keep this handy for any future questions or changes!"
```

---

## Instructions

### Step 1 — marina_agent.py: Update the BOOKING REFERENCE prompt section

Replace lines 164–168 (the full BOOKING REFERENCE block) with:

```
BOOKING REFERENCE:
When you set booking_confirmed to true, you MUST include the exact placeholder
[BOOKING_REF] in your reply where the reference number should appear. Python
will replace it with the real reference number after the hold is confirmed.
Example: "Your booking reference is [BOOKING_REF] — keep this handy for any
future questions or changes!"
```

### Step 2 — email_poller.py: Replace [BOOKING_REF] after hold success

At line 954, immediately after the existing `[PAYMENT_LINK]` replacement, add:

```python
reply_text = reply_text.replace("[BOOKING_REF]", booking_ref)
```

So the two lines together read:
```python
reply_text = reply_text.replace("[PAYMENT_LINK]", pay_link)
reply_text = reply_text.replace("[BOOKING_REF]", booking_ref)
```

### Step 3 — Update file headers

- `marina_agent.py`: change `# LAST MODIFIED: Brief 055` → `# LAST MODIFIED: Brief 058`
- `email_poller.py`: change `# LAST MODIFIED: Brief 055` → `# LAST MODIFIED: Brief 058`

---

## Tests

Write `bluemarlin/tests/test_booking_ref_reply.py`.

**Test 1 — `[BOOKING_REF]` placeholder is replaced in reply_text**
```python
reply_text = "You're confirmed! Your booking reference is [BOOKING_REF] — see you soon."
booking_ref = "BF-2026-12345"
result = reply_text.replace("[BOOKING_REF]", booking_ref)
assert "BF-2026-12345" in result
assert "[BOOKING_REF]" not in result
```

**Test 2 — `[PAYMENT_LINK]` and `[BOOKING_REF]` both replaced in one reply**
```python
reply_text = "Ref: [BOOKING_REF]. Pay here: [PAYMENT_LINK]."
result = reply_text.replace("[PAYMENT_LINK]", "https://demo.pay/abc")
result = result.replace("[BOOKING_REF]", "BF-2026-99999")
assert "BF-2026-99999" in result
assert "https://demo.pay/abc" in result
assert "[BOOKING_REF]" not in result
assert "[PAYMENT_LINK]" not in result
```

**Test 3 — Reply with no placeholder is unaffected**
```python
reply_text = "You're all set! See you on the water."
result = reply_text.replace("[BOOKING_REF]", "BF-2026-12345")
assert result == reply_text
```

**Test 4 — Prompt contains new [BOOKING_REF] placeholder instruction (not old thread_flags instruction)**
```python
from src.marina_agent import _build_prompt
prompt = _build_prompt("a@b.com", "test", "hi", {}, {})
assert "[BOOKING_REF]" in prompt
assert "thread_flags" not in prompt[prompt.index("BOOKING REFERENCE"):prompt.index("ESCALATION")]
```

**Test 5 — Old test update: `test_prompt_contains_booking_ref_instruction` from Brief 054 tests**
Update the existing test in `tests/test_marina_agent_054.py` (or equivalent) to assert `"[BOOKING_REF]"` appears in the prompt instead of `"booking_ref is present in thread_flags"`.

---

## Success Condition

After deploying, send a test booking to Marina and confirm the word is in the confirmation email reply (e.g. "BF-2026-XXXXX").

## Rollback

Revert the two prompt lines and remove the `.replace("[BOOKING_REF]", booking_ref)` line from email_poller.py. The ref will go back to being absent from replies but nothing will break.
