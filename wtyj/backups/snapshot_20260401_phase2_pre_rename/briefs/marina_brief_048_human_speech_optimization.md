# BRIEF 048 — Human speech optimization: multi-topic fix + prompt hardening
**Status:** Draft | **Files:** `email_poller.py`, `marina_agent.py` | **Depends on:** Brief 047 | **Blocks:** none

## Context
Live testing after Brief 046/047 revealed three issues with how Marina handles messy real-world messages:

1. **Multi-topic answers dropped** — Customer asked about food and hotel pickup alongside a booking. `_post_validate` replaced Claude's entire reply (including answers to those questions) with a departure-options override. The non-booking answers were silently discarded.
2. **Date not cleared on rejection** — Customer said "nvm the 28th, friday instead." Claude kept date=2026-03-28 (Saturday) in extracted fields. The old date persisted, `_post_validate` saw complete fields, and built a summary for the wrong date.
3. **Guest count hallucinated** — Customer said "We" in Dutch (no number). Claude extracted guests=15 (the group_threshold_requires_human value from the prompt context), triggering unnecessary escalation.

## Why This Approach
Fix 1 (multi-topic) was the hardest design choice. Three options considered:
- **New `side_answers` JSON field** — Clean separation but adds prompt complexity and another point of compliance failure.
- **Pre-validation via action_context** — Move validation before Claude call. But fields aren't extracted yet on first messages, so post-validation is still needed.
- **Append override when non-booking intents present** (selected) — When Claude returns multiple intents (e.g. `["booking", "inquiry"]`), append the override to Claude's reply instead of replacing. When booking is the only intent, replace as before. Simple, no prompt schema changes, worst case is slight redundancy.

For the signature duplication issue when appending: remove signatures from override messages entirely. Step 3a adds signature only in the replace path (booking-only intent).

Fix 2 (date clearing) requires BOTH a prompt change AND a merge logic change. The current field merge (email_poller.py lines 532–534) skips empty strings: `if v is not None and v != ""`. So even if Claude returns `date: ""`, the old date persists. The fix: when Claude returns `""` for a field that already has a value, treat it as an intentional clear and delete the field. This is safe because the prompt says "only if present and certain" — Claude omits fields it didn't extract (they're absent from the dict), and only returns `""` when explicitly clearing.

## Source Material

### Current `_post_validate` override messages (email_poller.py)
Day-of-week error (lines 300–306):
```python
return (
    f"Great choice! Unfortunately, the {trip.get('display_name', fields['trip_key'])} "
    f"doesn't run on {day_name}s — it runs {days_avail}. "
    f"Would any of these dates work instead?\n\n"
    f"{_suggest_dates(date, days_avail)}\n\n"
    f"Warm regards,\n{signature}"
), False
```

Departure options (lines 317–322):
```python
return (
    f"Almost there! The {trip.get('display_name', fields['trip_key'])} has "
    f"a couple of departure options:\n\n{dep_lines}\n\n"
    f"Which one works best for you?\n\n"
    f"Warm regards,\n{signature}"
), False
```

Booking summary (lines 245–255 in `_build_booking_summary`):
```python
signature = config_loader.get_agent_signature()
return (
    f"Here's a quick summary of your booking:\n\n"
    ...
    f"Shall I lock this in for you?\n\n"
    f"Warm regards,\n{signature}"
)
```

### Current field merge (email_poller.py lines 528–534):
```python
# Step 2: Merge fields — always overwrite when Claude returns non-empty values
th.setdefault("fields", {})
new_fields = result.get("fields", {}) or {}
new_flags = result.get("flags", {}) or {}
for k, v in new_fields.items():
    if v is not None and v != "":
        th["fields"][k] = v
```

### Current Step 3a (email_poller.py lines 555–564):
```python
reply_text = result["reply"]
_pv_trip_key = th["fields"].get("trip_key", "")
_pv_trip = config_loader.get_trip(_pv_trip_key) if _pv_trip_key else {}
if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
    _pv_override, _pv_set_awaiting = _post_validate(th, result, _pv_trip)
    if _pv_override:
        reply_text = _pv_override
        if _pv_set_awaiting:
            th["flags"]["awaiting_booking_confirmation"] = True
```

### Current prompt field descriptions (marina_agent.py lines 194):
```
guests: exact integer only
```

### Current prompt date description (marina_agent.py lines 186–193):
```
date: MUST be in YYYY-MM-DD format. You must convert any natural
  language date ... Never infer, guess, or pick a date the customer
  has not explicitly stated or clearly implied. When in doubt, ask.
```

### Current BOOKING BEHAVIOUR (marina_agent.py lines 119–131):
```
BOOKING BEHAVIOUR:
When the customer wants to book, extract all fields you can find ...
Python handles all booking validation, state management, and summary generation.
If you receive an ACTION instruction below, follow it exactly.
When no ACTION is given, reply naturally — ask for any missing required fields
(experience, date, guests) in a warm conversational way.

If the customer mentions children and the trip has age-based pricing ...
```

## Instructions

### Step 1 — Remove signatures from `_post_validate` override messages (email_poller.py)

**1a.** In the day-of-week error return (lines 299–306), remove the signature fetch and trailing signature lines. Change from:
```python
            signature = config_loader.get_agent_signature()
            return (
                f"Great choice! Unfortunately, the {trip.get('display_name', fields['trip_key'])} "
                f"doesn't run on {day_name}s — it runs {days_avail}. "
                f"Would any of these dates work instead?\n\n"
                f"{_suggest_dates(date, days_avail)}\n\n"
                f"Warm regards,\n{signature}"
            ), False
```
to:
```python
            return (
                f"Great choice! Unfortunately, the {trip.get('display_name', fields['trip_key'])} "
                f"doesn't run on {day_name}s — it runs {days_avail}. "
                f"Would any of these dates work instead?\n\n"
                f"{_suggest_dates(date, days_avail)}"
            ), False
```

**1b.** In the departure options return (lines 316–322), remove the signature fetch and trailing signature. Change from:
```python
        signature = config_loader.get_agent_signature()
        return (
            f"Almost there! The {trip.get('display_name', fields['trip_key'])} has "
            f"a couple of departure options:\n\n{dep_lines}\n\n"
            f"Which one works best for you?\n\n"
            f"Warm regards,\n{signature}"
        ), False
```
to:
```python
        return (
            f"Almost there! The {trip.get('display_name', fields['trip_key'])} has "
            f"a couple of departure options:\n\n{dep_lines}\n\n"
            f"Which one works best for you?"
        ), False
```

**1c.** In `_build_booking_summary` (lines 244–255), remove the signature fetch and trailing signature. Change from:
```python
    signature = config_loader.get_agent_signature()
    return (
        f"Here's a quick summary of your booking:\n\n"
        f"  Trip: {trip_name}\n"
        f"  Date: {date_fmt}\n"
        f"  Guests: {guests}\n"
        f"  Departure: {departure_time} from {dep_point} aboard {vessel}\n"
        f"  Total: ${total} USD ({guests} x ${price_adult})\n"
        f"  Included: {included}\n\n"
        f"Shall I lock this in for you?\n\n"
        f"Warm regards,\n{signature}"
    )
```
to:
```python
    return (
        f"Here's a quick summary of your booking:\n\n"
        f"  Trip: {trip_name}\n"
        f"  Date: {date_fmt}\n"
        f"  Guests: {guests}\n"
        f"  Departure: {departure_time} from {dep_point} aboard {vessel}\n"
        f"  Total: ${total} USD ({guests} x ${price_adult})\n"
        f"  Included: {included}\n\n"
        f"Shall I lock this in for you?"
    )
```

### Step 2 — Update Step 3a to append/replace based on intents (email_poller.py)

Change lines 559–564 from:
```python
                if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
                    _pv_override, _pv_set_awaiting = _post_validate(th, result, _pv_trip)
                    if _pv_override:
                        reply_text = _pv_override
                        if _pv_set_awaiting:
                            th["flags"]["awaiting_booking_confirmation"] = True
```
to:
```python
                if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
                    _pv_override, _pv_set_awaiting = _post_validate(th, result, _pv_trip)
                    if _pv_override:
                        _intents = result.get("intents", [])
                        _has_side_topics = any(i not in _BOOKING_INTENTS for i in _intents)
                        if _has_side_topics:
                            # Preserve Claude's answers to non-booking questions
                            reply_text = result["reply"].rstrip() + "\n\n" + _pv_override
                        else:
                            # Booking-only: use override with signature
                            _sig = config_loader.get_agent_signature()
                            reply_text = _pv_override + f"\n\nWarm regards,\n{_sig}"
                        if _pv_set_awaiting:
                            th["flags"]["awaiting_booking_confirmation"] = True
```

### Step 3 — Fix field merge to allow intentional clears (email_poller.py)

Change lines 532–534 from:
```python
                for k, v in new_fields.items():
                    if v is not None and v != "":
                        th["fields"][k] = v
```
to:
```python
                for k, v in new_fields.items():
                    if v is not None and v != "":
                        th["fields"][k] = v
                    elif v == "" and k in th["fields"]:
                        # Intentional clear — Claude returned empty string for existing field
                        del th["fields"][k]
```

### Step 4 — Update slot-unavailable override messages (email_poller.py)

The slot-unavailable messages in Step 3b also have signatures. These fire AFTER Step 3a and are NOT subject to the multi-topic append logic (they're availability failures, not field validation). **Leave these unchanged** — they always fully replace because the booking can't proceed regardless of side topics.

### Step 5 — Harden `guests` field description (marina_agent.py)

Change line 194 from:
```
    guests: exact integer only
```
to:
```
    guests: exact integer ONLY when the customer explicitly states a number.
      "We", "us", "our family" without a number does NOT count — omit this
      field entirely. Never infer a guest count from context or business rules.
```

### Step 6 — Add date-clearing instruction (marina_agent.py)

After the existing date description (line 193, ending with "When in doubt, ask."), add:
```
      If the customer explicitly rejects or cancels a previously stated date
      (e.g. "nvm the 28th", "not that date", "change the date"), you MUST
      set date to "" (empty string) so the old date is cleared. Then ask
      for a specific new date in clarifications_needed.
```

### Step 7 — Add multi-topic guidance to BOOKING BEHAVIOUR (marina_agent.py)

After line 125 ("(experience, date, guests) in a warm conversational way."), add:
```

When the customer asks non-booking questions alongside a booking request
(e.g. "book X for 2 on March 28, also is there food?"), answer those
questions in your reply. Python may append booking-specific information
(summaries, departure options, date corrections) after your reply.
```

### Step 8 — Update file headers
- `email_poller.py`: change `LAST MODIFIED: Brief 047` to `LAST MODIFIED: Brief 048`
- `marina_agent.py`: change `LAST MODIFIED: Brief 046` to `LAST MODIFIED: Brief 048`

## Tests

```python
# === Fix 1: Multi-topic reply preservation ===

# T1: _post_validate override has NO signature (day-of-week)
from email_poller import _post_validate, _BOOKING_INTENTS
th_dow = {"fields": {"experience": "Snorkeling", "date": "2026-03-09", "guests": "2", "trip_key": "snorkeling_3in1"}, "flags": {}}
trip_fri = {"display_name": "3-in-1 Snorkeling Trip", "departures": [{"time": "10:00"}], "days_available": "Fridays only"}
result_b = {"intents": ["booking"], "fields": {}, "flags": {}}
override_dow, _ = _post_validate(th_dow, result_b, trip_fri)
check("T1: day-of-week override has no signature", "Warm regards" not in override_dow)

# T2: _post_validate override has NO signature (departure options)
th_dep = {"fields": {"experience": "Klein Curacao", "date": "2026-03-25", "guests": "2", "trip_key": "klein_curacao"}, "flags": {}}
trip_kc = {"display_name": "Klein Curacao Trip", "departures": [{"time": "08:00", "vessel": "BlueFinn2", "departure_point": "Jan Thiel Beach"}, {"time": "08:30", "vessel": "BlueFinn1", "departure_point": "Jan Thiel Beach"}], "days_available": "daily"}
override_dep, _ = _post_validate(th_dep, result_b, trip_kc)
check("T2: departure override has no signature", "Warm regards" not in override_dep)

# T3: _build_booking_summary has NO signature
from email_poller import _build_booking_summary
trip_sc = {"display_name": "Sunset Cruise", "departures": [{"time": "17:30", "vessel": "Kailani", "departure_point": "Village Marina"}], "days_available": "Tuesday, Thursday, Friday, Saturday", "price_adult_usd": 79, "included": ["open bar", "snacks"]}
summary = _build_booking_summary({"trip_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "departure_time": "17:30"}, trip_sc)
check("T3: booking summary has no signature", "Warm regards" not in summary)
check("T4: summary still has lock-in question", "Shall I lock this in" in summary)
check("T5: summary still has correct price", "$158" in summary)

# T6: Simulate multi-intent — override should be APPENDED (test the logic inline)
# When intents = ["booking", "inquiry"], override should be appended to Claude's reply
intents_multi = ["booking", "inquiry"]
has_side = any(i not in _BOOKING_INTENTS for i in intents_multi)
check("T6: multi-intent detected as has_side_topics", has_side == True)

# T7: Simulate booking-only intent — no side topics
intents_single = ["booking"]
has_side_single = any(i not in _BOOKING_INTENTS for i in intents_single)
check("T7: booking-only has no side topics", has_side_single == False)

# T8: Simulate reschedule + inquiry — side topics detected
intents_resched = ["reschedule", "inquiry"]
has_side_resched = any(i not in _BOOKING_INTENTS for i in intents_resched)
check("T8: reschedule+inquiry has side topics", has_side_resched == True)

# === Fix 2: Date clearing instruction in prompt ===

# T9: Prompt contains date-clearing instruction
import marina_agent
prompt = marina_agent._build_prompt("t@t.com", "T", "T", {}, {})
check("T9: prompt has date-clearing instruction", 'set date to ""' in prompt or "set date to empty" in prompt.lower())

# T10: Prompt still has original date instruction
check("T10: prompt still has YYYY-MM-DD instruction", "YYYY-MM-DD" in prompt)

# === Fix 3: Guest hallucination guard ===

# T11: Prompt contains guest-count guard
check("T11: prompt warns against inferring guests", "Never infer a guest count" in prompt)

# T12: Prompt mentions "We" as non-count
check("T12: prompt says We is not a count", '"We"' in prompt or "'We'" in prompt)

# === Fix 4: Multi-topic prompt guidance ===

# T13: Prompt has multi-topic instruction
check("T13: prompt has multi-topic guidance", "non-booking questions alongside" in prompt)

# === Regression tests ===

# T14: _post_validate still triggers on booking intent
override_reg, awaiting_reg = _post_validate(
    {"fields": {"experience": "Sunset", "date": "2026-03-26", "guests": "2", "trip_key": "sunset_cruise"}, "flags": {}},
    {"intents": ["booking"], "fields": {}, "flags": {}},
    trip_sc
)
check("T14: booking still builds summary", override_reg is not None and "Shall I lock this in" in override_reg)
check("T15: booking still sets awaiting", awaiting_reg == True)

# T16: _post_validate still triggers on reschedule intent (Brief 047 regression)
override_resched, _ = _post_validate(
    {"fields": {"experience": "Snorkeling", "date": "2026-03-13", "guests": "2", "trip_key": "snorkeling_3in1"}, "flags": {}},
    {"intents": ["reschedule"], "fields": {}, "flags": {}},
    trip_fri
)
check("T16: reschedule still triggers validation", override_resched is not None and "Shall I lock this in" in override_resched)

# === Fix 2 integration: Date clearing through merge ===

# T17: Empty-string date clears existing date in thread fields
th_date_clear = {"fields": {"experience": "Klein", "date": "2026-03-28", "guests": "2", "trip_key": "klein_curacao"}}
new_fields_clear = {"date": ""}
for k, v in new_fields_clear.items():
    if v is not None and v != "":
        th_date_clear["fields"][k] = v
    elif v == "" and k in th_date_clear["fields"]:
        del th_date_clear["fields"][k]
check("T17: empty string clears existing date", "date" not in th_date_clear["fields"])

# T18: Empty-string for non-existing field is ignored (no KeyError)
th_no_phone = {"fields": {"experience": "Klein"}}
new_fields_phone = {"phone": ""}
for k, v in new_fields_phone.items():
    if v is not None and v != "":
        th_no_phone["fields"][k] = v
    elif v == "" and k in th_no_phone["fields"]:
        del th_no_phone["fields"][k]
check("T18: empty string for absent field is safe", "phone" not in th_no_phone["fields"])

# T19: Non-empty values still merge normally (regression)
th_merge = {"fields": {"experience": "Klein"}}
new_fields_normal = {"date": "2026-03-25", "guests": "2"}
for k, v in new_fields_normal.items():
    if v is not None and v != "":
        th_merge["fields"][k] = v
    elif v == "" and k in th_merge["fields"]:
        del th_merge["fields"][k]
check("T19: normal merge still works", th_merge["fields"]["date"] == "2026-03-25" and th_merge["fields"]["guests"] == "2")
```

## Success Condition
Multi-topic messages preserve Claude's non-booking answers alongside Python's booking overrides. Prompt hardening prevents guest hallucination and stale-date persistence. All 19 tests pass, plus Brief 046 and 047 regression suites.

## Rollback
Revert `email_poller.py` and `marina_agent.py` to Brief 047 state. No other files affected.
