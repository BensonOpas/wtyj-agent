# BRIEF 036 — Marina prompt bug fixes: language body-only, day-of-week validation, reply_hold_failed scope
**Status:** Draft | **Files:** `src/marina_agent.py`, `briefs/SYSTEM_STATE.md` | **Depends on:** Brief 035 | **Blocks:** nothing

## Context
Stress test (`test_marina_stress.py`, 14 scenarios) exposed 3 bugs in the marina_agent.py prompt:

1. **S11 — Language detection fires on sender name, not message body.** Hans Müller sent an English message; Marina replied in Dutch because she inferred language from "Müller." The Brief 035 LANGUAGE instruction says "detect the language of the inbound message" but does not say to use the body text only.

2. **S7 — Day-of-week validation inconsistent.** west_coast_beach (Wednesdays and Sundays only) was booked on a Thursday. Marina sent a full booking summary and set awaiting_booking_confirmation=true. The calendar hold then failed and reply_hold_failed was sent. Customer received: summary → "slot unavailable." Bad UX. By contrast, S4 (snorkeling_3in1 Fridays-only) was correctly handled — Marina refused the summary and suggested adjacent Fridays. The difference: "Fridays only" reads as a hard rule; "Wednesdays and Sundays" read as a schedule listing. A prompt instruction is needed that applies consistently to ALL trips.

3. **S8 — reply_hold_failed generated for group escalation.** 20-person group (requires_human=true, no hold attempted). Marina generated reply_hold_failed saying "that slot is unavailable" — wrong content for an escalation path where no hold is ever attempted. The current instruction says "write this field whenever awaiting_booking_confirmation is being set to true OR booking_confirmed is true in thread flags" — but Marina wrote it even when neither was true.

All three are prompt text changes only. No Python logic changes.

**Day-of-week check tradeoff:** The instruction in Fix 2 is phrased generically ("check the trip's days_available field listed in TRIPS above") rather than using a hardcoded example like "west_coast_beach runs Wednesdays and Sundays." This avoids embedding business-specific values in the prompt logic — if operating days change in client.json, the instruction remains correct because it points Marina at the injected TRIPS data. A generic instruction is slightly less concrete than a named example, but the TRIPS block already contains the actual schedule and Marina demonstrated she can read it correctly in S4 (snorkeling Friday-only check). The prior approach (with hardcoded example) would have violated Rule 4.

## Why This Approach
All three are prompt precision issues — Claude is doing what the prompt permits, not what it should restrict. Tightening the wording at the exact points where Marina over-generalises fixes the observed behaviour without restructuring the prompt. Adding a dedicated day-of-week check step before the booking summary step is the correct location — it stops the wrong-day problem at source rather than relying on the calendar hold rejection to clean it up.

## Source Material

### marina_agent.py — relevant sections (confirmed from file read this session)

**File header (lines 1–5):**
```
# FILE: marina_agent.py
# CREATED: Brief 023
# LAST MODIFIED: Brief 035
```

**LANGUAGE line (line 69) — current:**
```
LANGUAGE: Detect the language of the customer's inbound message and write your reply in that same language. Supported languages: {', '.join(business.get('languages', []))}. If the language is unclear or not in the supported list, default to English.
```

**BOOKING CONFIRMATION BEHAVIOUR — opening paragraph (lines 99–115) — current:**
```
BOOKING CONFIRMATION BEHAVIOUR:
When your fields response contains all four required booking fields
(experience, date, guests, trip_key) — whether extracted from this
message or already in thread context — AND "awaiting_booking_confirmation"
is not true in thread flags AND "booking_confirmed" is not true in
thread flags, do NOT assume the booking is confirmed. Instead:
- Send a warm booking summary to the customer listing: trip name,
  date, number of guests, departure time (if chosen), total price,
  what is included.
- departure_time is NOT a required field. Do not wait for it before
  sending the summary. If not yet chosen, you may ask in the same
  message, but still send the summary and set the confirmation flag.
- End the summary with a single clear confirmation question:
  "Shall I lock this in for you?"
- In your JSON response, the "flags" field MUST contain:
  "awaiting_booking_confirmation": true
- Do NOT set any hold-related flags.
```

**reply_hold_failed field description (line 184) — current:**
```
  "reply_hold_failed": "<reply to send if the calendar slot is unavailable or hold creation fails — apologetic, warm, offers to find another date or time, does NOT confirm the booking, does NOT include a payment link. Write this field whenever awaiting_booking_confirmation is being set to true OR booking_confirmed is true in thread flags. Always write it alongside the summary reply so Python can choose the correct one based on actual availability.>",
```

### Stress test results that confirm each bug
- S7 fields: `{"flags": {"awaiting_booking_confirmation": true}}` — Thursday, west_coast_beach (Wed/Sun only)
- S11 reply: Dutch language despite English body text ("Hello, I'd like to book...")
- S8 output: `reply_hold_failed` present despite `requires_human=true` and no booking summary

## Instructions

### 1. Fix LANGUAGE instruction — body text only

Find (exact text, line 69):
```
LANGUAGE: Detect the language of the customer's inbound message and write your reply in that same language. Supported languages: {', '.join(business.get('languages', []))}. If the language is unclear or not in the supported list, default to English.
```

Replace with:
```
LANGUAGE: Detect the language of the customer's inbound message from the body text only. Do not infer language from the sender's name or email address. Write your reply in that same language. Supported languages: {', '.join(business.get('languages', []))}. If the language is unclear or not in the supported list, default to English.
```

### 2. Add day-of-week validation step to BOOKING CONFIRMATION BEHAVIOUR

Find (exact text, lines 99–115):
```
BOOKING CONFIRMATION BEHAVIOUR:
When your fields response contains all four required booking fields
(experience, date, guests, trip_key) — whether extracted from this
message or already in thread context — AND "awaiting_booking_confirmation"
is not true in thread flags AND "booking_confirmed" is not true in
thread flags, do NOT assume the booking is confirmed. Instead:
- Send a warm booking summary to the customer listing: trip name,
  date, number of guests, departure time (if chosen), total price,
  what is included.
```

Replace with:
```
BOOKING CONFIRMATION BEHAVIOUR:
When your fields response contains all four required booking fields
(experience, date, guests, trip_key) — whether extracted from this
message or already in thread context — AND "awaiting_booking_confirmation"
is not true in thread flags AND "booking_confirmed" is not true in
thread flags, do NOT assume the booking is confirmed. Instead:
- FIRST: verify the requested date's day of week matches the trip's
  days_available field shown in TRIPS above. If the date falls on a
  day the trip does not run, do NOT set awaiting_booking_confirmation
  and do NOT send a booking summary. Instead, tell the customer which
  days the trip runs and suggest the nearest valid dates.
- Send a warm booking summary to the customer listing: trip name,
  date, number of guests, departure time (if chosen), total price,
  what is included.
```

### 3. Fix reply_hold_failed scope — only write for booking confirmation paths

Find (exact text, line 184):
```
  "reply_hold_failed": "<reply to send if the calendar slot is unavailable or hold creation fails — apologetic, warm, offers to find another date or time, does NOT confirm the booking, does NOT include a payment link. Write this field whenever awaiting_booking_confirmation is being set to true OR booking_confirmed is true in thread flags. Always write it alongside the summary reply so Python can choose the correct one based on actual availability.>",
```

Replace with:
```
  "reply_hold_failed": "<reply to send if the calendar slot is unavailable or hold creation fails — apologetic, warm, offers to find another date or time, does NOT confirm the booking, does NOT include a payment link. Write this field ONLY when you are setting awaiting_booking_confirmation to true OR booking_confirmed to true in your current JSON response. Do not write it for inquiry, escalation, clarification, or any path where no booking hold will be attempted.>",
```

### 4. Update file header

Find:
```
# LAST MODIFIED: Brief 035
```

Replace with:
```
# LAST MODIFIED: Brief 036
```

### 5. Update SYSTEM_STATE.md Decision Log

Append to the Decision Log at the end of `briefs/SYSTEM_STATE.md`:
```
Brief 036 — Marina prompt bug fixes: language body-only, day-of-week validation, reply_hold_failed scope
Decision: Three prompt fixes following stress test (14 scenarios). Fix 1: language from body text only. Fix 2: day-of-week check before booking summary. Fix 3: reply_hold_failed only on booking confirmation paths.
Outcome: pending
```

## Tests

Write as `bluemarlin/test_036_prompt_fixes.py` and run it:

```python
#!/usr/bin/env python3
# bluemarlin/test_036_prompt_fixes.py
# Brief 036 — Marina prompt bug fixes
# Run: cd bluemarlin && python3 test_036_prompt_fixes.py

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import marina_agent

prompt = marina_agent._build_prompt(
    from_email="test@example.com",
    subject="Test",
    body="Hello",
    thread_fields={},
    thread_flags={},
)

# T1: Language instruction includes "body text only"
assert "body text only" in prompt, f"T1 fail: 'body text only' missing from LANGUAGE instruction"
print("T1 pass — LANGUAGE instruction specifies body text only")

# T2: Language instruction contains the exact phrase that distinguishes Fix 1
# (unique to the fix — not present anywhere else in the prompt)
assert "Do not infer language from the sender" in prompt, \
    f"T2 fail: exact Fix 1 phrase 'Do not infer language from the sender' missing"
print("T2 pass — sender name exclusion instruction present")

# T3: BOOKING CONFIRMATION section includes days_available check
assert "days_available" in prompt, \
    f"T3 fail: 'days_available' check missing from BOOKING CONFIRMATION section"
print("T3 pass — days_available validation present in prompt")

# T4: BOOKING CONFIRMATION day-of-week check references TRIPS data
assert "day the trip does not run" in prompt, \
    f"T4 fail: day-of-week block missing from BOOKING CONFIRMATION section"
print("T4 pass — day-of-week validation block present in prompt")

# T5: reply_hold_failed description includes "ONLY when"
assert "ONLY when" in prompt, \
    f"T5 fail: 'ONLY when' missing from reply_hold_failed description"
print("T5 pass — reply_hold_failed scoped with 'ONLY when'")

# T6: reply_hold_failed description excludes escalation paths
assert "escalation" in prompt or "inquiry" in prompt, \
    f"T6 fail: reply_hold_failed exclusion of non-booking paths missing"
print("T6 pass — reply_hold_failed exclusion of non-booking paths present")

# T7: File header updated to Brief 036
with open(os.path.join(os.path.dirname(__file__), "src", "marina_agent.py")) as f:
    header = f.read(300)
assert "Brief 036" in header, f"T7 fail: file header not updated to Brief 036"
print("T7 pass — file header updated to Brief 036")

print("\nAll 7 tests passed.")
print("\nManual verification: re-run test_marina_stress.py and confirm:")
print("  S7  — no booking summary for Thursday west_coast_beach")
print("  S11 — English reply for English message (Hans Müller scenario)")
print("  S8  — no reply_hold_failed for group escalation")
```

## Success Condition
All 7 prompt inspection tests pass. Manual re-run of `test_marina_stress.py` confirms: S7 no longer sends a booking summary for a Thursday date, S11 replies in English, S8 has no reply_hold_failed.

## Rollback
`git checkout HEAD~1 -- bluemarlin/src/marina_agent.py` restores to Brief 035 state.
