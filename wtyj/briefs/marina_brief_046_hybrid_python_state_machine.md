# BRIEF 046 — Hybrid refactor: Python state machine + simplified Claude prompt
**Status:** Draft | **Files:** `src/marina_agent.py`, `src/email_poller.py` | **Depends on:** Brief 045 | **Blocks:** —

## Context
Marina's booking flow has been unreliable through Briefs 044–045. The prompt contains ~62 lines of complex state machine logic (FIRST/SECOND/THIRD checks, slot-unavailable-alternative handling, confirmation state transitions) that Claude follows inconsistently. Each brief patches one failure and exposes another.

## Why This Approach
Three options were considered: (1) keep patching the prompt (rabbit hole), (2) move everything to Python with static reply templates (violates Rule 3), (3) hybrid — Python handles deterministic validation + flag management, Claude handles language understanding + field extraction + conversational replies. Option 3 was chosen because it eliminates the source of bugs (prompt non-compliance on state machine rules) while preserving Claude's value (understanding customer intent, extracting fields, writing warm replies, detecting confirmation language). The data-driven validation messages are NOT static reply templates — they're dynamically generated from client.json data for checks Claude consistently failed.

## Source Material

**Multi-departure trips** (require departure_time selection):
- `klein_curacao`: 2 departures — 08:00 (BlueFinn2, Jan Thiel Beach), 08:30 (BlueFinn1, Jan Thiel Beach)
- `jet_ski`: 12 departures — 08:00 through 19:00

**Single-departure trips** (auto-select, no question needed):
- `snorkeling_3in1`: 10:00 (TopCat, Mood Beach pier)
- `west_coast_beach`: 09:00 (Red Dragon, Mood/Tomatoes)
- `sunset_cruise`: 17:30 (Kailani, Village Marina/Mood pier)

**days_available per trip:**
- `klein_curacao`: daily
- `snorkeling_3in1`: Fridays only
- `west_coast_beach`: Wednesdays and Sundays
- `sunset_cruise`: Tuesday, Thursday, Friday, Saturday
- `jet_ski`: daily

**Child pricing:** Only `klein_curacao` has `price_child_usd` (65) and `price_child_age_range` (4-12).

## Instructions

### Step 1 — Add helper functions to email_poller.py

Insert the following functions BEFORE the line `# ========= MAIN LOOP =========` (currently line 197). Add a blank line before the MAIN LOOP comment.

```python
# ========= BOOKING VALIDATION HELPERS =========
def _day_matches(day_name, days_available):
    """Check if day_name matches the trip's days_available string."""
    if days_available.lower() == "daily":
        return True
    return day_name.lower() in days_available.lower()


def _suggest_dates(date_str, days_available):
    """Suggest 2-3 nearby valid dates."""
    from datetime import timedelta as _td
    base = datetime.strptime(date_str, "%Y-%m-%d")
    suggestions = []
    for offset in range(1, 14):
        candidate = base + _td(days=offset)
        if _day_matches(candidate.strftime("%A"), days_available):
            suggestions.append(f"- {candidate.strftime('%A, %d %B %Y')}")
            if len(suggestions) >= 3:
                break
    return "\n".join(suggestions) if suggestions else "Please suggest another date!"


def _build_booking_summary(fields, trip):
    """Build a data-driven booking summary from fields and trip config."""
    trip_name = trip.get("display_name", fields.get("trip_key", ""))
    date_str = fields.get("date", "")
    guests = int(fields.get("guests") or 1)
    departure_time = fields.get("departure_time", "")
    departures = trip.get("departures", [])
    dep_info = next((d for d in departures if d.get("time") == departure_time), None)
    if not dep_info and departures:
        dep_info = departures[0]
        departure_time = dep_info.get("time", "")
    vessel = dep_info.get("vessel", "") if dep_info else ""
    dep_point = dep_info.get("departure_point", "") if dep_info else ""
    price_adult = trip.get("price_adult_usd", 0)
    total = price_adult * guests
    included = ", ".join(trip.get("included", [])) or "see trip details"
    try:
        date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %d %B %Y")
    except ValueError:
        date_fmt = date_str
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


def _build_action_context(th):
    """Build action_context string for the Claude prompt based on thread state."""
    flags = th.get("flags", {})
    if flags.get("awaiting_booking_confirmation"):
        return (
            "ACTION: A booking summary was sent. The customer is replying. "
            "Determine if they are: (a) confirming — set booking_confirmed: true, "
            "awaiting_booking_confirmation: false, write a warm celebratory reply "
            "with the exact string [PAYMENT_LINK] where the payment link goes. "
            "Also write reply_hold_failed — an apologetic message if the slot turns "
            "out to be unavailable, without [PAYMENT_LINK]; "
            "(b) changing something — extract new fields, set "
            "awaiting_booking_confirmation: false; (c) unclear — ask "
            "for clarification. Do NOT generate a new booking summary."
        )
    return ""


def _post_validate(th, result, trip):
    """
    Validate extracted fields after Claude call.
    Returns (reply_override, should_set_awaiting).
    """
    fields = th.get("fields", {})
    flags = th.get("flags", {})

    if "booking" not in result.get("intents", []):
        return None, False
    if not all(fields.get(k) for k in ("experience", "date", "guests", "trip_key")):
        return None, False
    if flags.get("awaiting_booking_confirmation") or flags.get("booking_confirmed"):
        return None, False

    date = fields["date"]
    departures = trip.get("departures", [])

    # 1. Day-of-week check
    try:
        day_name = datetime.strptime(date, "%Y-%m-%d").strftime("%A")
        days_avail = trip.get("days_available", "daily")
        if not _day_matches(day_name, days_avail):
            signature = config_loader.get_agent_signature()
            return (
                f"Great choice! Unfortunately, the {trip.get('display_name', fields['trip_key'])} "
                f"doesn't run on {day_name}s — it runs {days_avail}. "
                f"Would any of these dates work instead?\n\n"
                f"{_suggest_dates(date, days_avail)}\n\n"
                f"Warm regards,\n{signature}"
            ), False
    except ValueError:
        pass

    # 2. Departure time check (multi-departure trips only)
    if len(departures) > 1 and not fields.get("departure_time"):
        dep_lines = "\n".join(
            f"- {d['time']} aboard {d.get('vessel', '?')} from {d.get('departure_point', '?')}"
            for d in departures
        )
        signature = config_loader.get_agent_signature()
        return (
            f"Almost there! The {trip.get('display_name', fields['trip_key'])} has "
            f"a couple of departure options:\n\n{dep_lines}\n\n"
            f"Which one works best for you?\n\n"
            f"Warm regards,\n{signature}"
        ), False

    # 3. Child pricing — Claude sets needs_child_ages flag
    if result.get("flags", {}).get("needs_child_ages"):
        return None, False

    # 4. All checks pass — build data-driven summary
    summary = _build_booking_summary(fields, trip)
    return summary, True


```

### Step 2 — Simplify marina_agent.py prompt

**2a.** Add `action_context: str = ""` parameter to `_build_prompt()`.

Change:
```python
def _build_prompt(
    from_email: str,
    subject: str,
    body: str,
    thread_fields: dict,
    thread_flags: dict,
) -> str:
```
To:
```python
def _build_prompt(
    from_email: str,
    subject: str,
    body: str,
    thread_fields: dict,
    thread_flags: dict,
    action_context: str = "",
) -> str:
```

**2b.** Replace the entire BOOKING CONFIRMATION BEHAVIOUR block (lines 118–179, from `BOOKING CONFIRMATION BEHAVIOUR:` through `sending.`) with:

```
BOOKING BEHAVIOUR:
When the customer wants to book, extract all fields you can find (experience,
date, guests, trip_key, departure_time, customer_name, phone, special_requests).
Python handles all booking validation, state management, and summary generation.
If you receive an ACTION instruction below, follow it exactly.
When no ACTION is given, reply naturally — ask for any missing required fields
(experience, date, guests) in a warm conversational way.

If the customer mentions children and the trip has age-based pricing (shown in
TRIPS data above), ask for their ages in your reply and set needs_child_ages
to true in your flags.

{action_context}
```

**2c.** Remove the entire AVAILABILITY CONTEXT block — from `AVAILABILITY CONTEXT:` through `Always write both when sending a booking summary.` (lines 218–229 in original). Remove the blank line before it too so there's a single blank line between SEMI-ESCALATION and THREAD CONTEXT.

**2d.** Remove spots_remaining and trip_capacity from THREAD CONTEXT. Replace:
```
  spots_remaining: {thread_flags.get('spots_remaining', 'unknown')}
  trip_capacity: {thread_flags.get('trip_capacity', 'unknown')}
```
With nothing (delete those two lines).

**2e.** Update the `"reply"` description in the JSON spec. Replace:
```
  "reply": "<full reply to send when the booking hold is successfully created — warm, celebratory, includes the booking summary, payment link placeholder [PAYMENT_LINK], payment methods, hold duration, what to bring>",
```
With:
```
  "reply": "<your reply to the customer — warm and natural. Follow any ACTION instruction above. When no ACTION is given, reply conversationally.>",
```

**2f.** Update `"reply_hold_failed"` description. Replace:
```
  "reply_hold_failed": "<reply to send if the calendar slot is unavailable or hold creation fails — apologetic, warm, offers to find another date or time, does NOT confirm the booking, does NOT include a payment link. Write this field ONLY when you are setting awaiting_booking_confirmation to true OR booking_confirmed to true in your current JSON response. Do not write it for inquiry, escalation, clarification, or any path where no booking hold will be attempted.>",
```
With:
```
  "reply_hold_failed": "<optional — write ONLY when setting booking_confirmed to true. Apologetic message if the slot is unavailable, without [PAYMENT_LINK].>",
```

**2g.** Update `"flags"` description. Replace:
```
  "flags": {{"awaiting_booking_confirmation": <true when you are sending a booking summary asking the customer to confirm — omit or false otherwise>, "booking_confirmed": <true only when the customer has just confirmed in this message — omit or false otherwise>}},
```
With:
```
  "flags": {{"booking_confirmed": <true only when the customer has just confirmed a booking — omit or false otherwise>, "awaiting_booking_confirmation": <set to false only when the customer wants to change something after a booking summary — omit otherwise>, "needs_child_ages": <true when children are mentioned and the trip has age-based pricing — omit or false otherwise>}},
```

### Step 3 — Add action_context parameter to process_message

**3a.** Add `action_context: str = ""` parameter:
```python
def process_message(
    from_email: str,
    subject: str,
    body: str,
    thread_fields: dict,
    thread_flags: dict,
    action_context: str = "",
) -> dict:
```

**3b.** Pass action_context to `_build_prompt()`. Change:
```python
        prompt = _build_prompt(from_email, subject, body, thread_fields, thread_flags)
```
To:
```python
        prompt = _build_prompt(from_email, subject, body, thread_fields, thread_flags, action_context)
```

### Step 4 — Modify email_poller.py main loop

**4a.** Modify Step 1 — add action_context building before marina_agent call. Replace:
```python
                # Step 1: Call marina_agent (single Claude call per message)
                agent_flags = dict(th.get("flags", {}))
                for _rk in ("awaiting_relay", "relay_token", "relay_question",
                            "relay_customer_email", "relay_reply_subject"):
                    agent_flags.pop(_rk, None)
                result = marina_agent.process_message(
                    from_email, subj, body,
                    th.get("fields", {}), agent_flags,
                )
```
With:
```python
                # Step 1: Build action context + call marina_agent (single Claude call per message)
                agent_flags = dict(th.get("flags", {}))
                for _rk in ("awaiting_relay", "relay_token", "relay_question",
                            "relay_customer_email", "relay_reply_subject"):
                    agent_flags.pop(_rk, None)
                action_context = _build_action_context(th)
                result = marina_agent.process_message(
                    from_email, subj, body,
                    th.get("fields", {}), agent_flags, action_context,
                )
```

**4b.** Replace the field merge + flag merge + change detection block. Replace the entire block from `# Step 2: Merge fields` through `log(f"Soft hold cancelled for {from_email}: customer changed booking details")`:

```python
                # Step 2: Merge fields — always overwrite when Claude returns non-empty values
                th.setdefault("fields", {})
                new_fields = result.get("fields", {}) or {}
                new_flags = result.get("flags", {}) or {}
                for k, v in new_fields.items():
                    if v is not None and v != "":
                        th["fields"][k] = v

                # Step 3: Persist flags — Python manages awaiting_booking_confirmation (set only)
                th.setdefault("flags", {})
                _was_awaiting = th["flags"].get("awaiting_booking_confirmation", False)
                if new_flags.get("awaiting_booking_confirmation"):
                    new_flags.pop("awaiting_booking_confirmation")
                th["flags"].update(new_flags)

                # Change detection: cancel soft hold if customer changed booking details
                if _was_awaiting and not th["flags"].get("awaiting_booking_confirmation") \
                        and not th["flags"].get("booking_confirmed"):
                    if th["flags"].get("hold_id"):
                        state_registry.cancel_hold(th["flags"]["hold_id"])
                        th["flags"].pop("hold_id", None)
                    th["flags"]["slot_checked"] = False
                    th["flags"]["slot_available"] = False
                    log(f"Soft hold cancelled for {from_email}: customer changed booking details")
```

NOTE: The field merge now always overwrites non-empty values. This is correct because: (1) Claude is told to "extract all fields you can find," (2) Claude sees thread context so it re-extracts existing fields, (3) when a field is absent or empty in Claude's response, it's not overwritten. This eliminates the dead-end where a customer couldn't change their date after a slot-unavailable response.

**4c.** After the `log(f"Intents: ...")` line, insert post-validation + reply_text initialization. After:
```python
                log(f"Intents: {result.get('intents')} | Fields: {th['fields']}")
```
Insert:
```python

                # Step 3a: Post-validation — Python validates fields and may override reply
                reply_text = result["reply"]
                _pv_trip_key = th["fields"].get("trip_key", "")
                _pv_trip = config_loader.get_trip(_pv_trip_key) if _pv_trip_key else {}
                if "booking" in result.get("intents", []):
                    _pv_override, _pv_set_awaiting = _post_validate(th, result, _pv_trip)
                    if _pv_override:
                        reply_text = _pv_override
                        if _pv_set_awaiting:
                            th["flags"]["awaiting_booking_confirmation"] = True

```

**4d.** Modify Step 3b trigger condition. Replace:
```python
                if (result.get("flags", {}).get("awaiting_booking_confirmation")
                        and not th["flags"].get("slot_checked")):
```
With:
```python
                if (th["flags"].get("awaiting_booking_confirmation")
                        and not th["flags"].get("slot_checked")):
```

**4e.** In Step 3b, modify the slot-unavailable branch. Replace:
```python
                    else:
                        log(f"Slot unavailable for {from_email}: "
                            f"{avail.get('spots_remaining', 0)}/{avail.get('capacity', 0)} spots remaining")
```
With:
```python
                    else:
                        th["flags"]["awaiting_booking_confirmation"] = False
                        th["flags"]["slot_checked"] = False
                        _unavail_name = _pv_trip.get("display_name", _ck_trip)
                        _unavail_sig = config_loader.get_agent_signature()
                        reply_text = (
                            f"Oh no — it looks like the {_unavail_name} on that date "
                            f"is fully booked! Would you like to try a different date?\n\n"
                            f"Warm regards,\n{_unavail_sig}"
                        )
                        log(f"Slot unavailable for {from_email}: "
                            f"{avail.get('spots_remaining', 0)}/{avail.get('capacity', 0)} spots remaining")
```

Also modify the soft hold race case. Replace:
```python
                        else:
                            # Race: capacity was grabbed between check and insert
                            th["flags"]["slot_available"] = False
                            log(f"Soft hold race for {from_email}: slot full at insert time")
```
With:
```python
                        else:
                            # Race: capacity was grabbed between check and insert
                            th["flags"]["slot_available"] = False
                            th["flags"]["awaiting_booking_confirmation"] = False
                            th["flags"]["slot_checked"] = False
                            _unavail_name = _pv_trip.get("display_name", _ck_trip)
                            _unavail_sig = config_loader.get_agent_signature()
                            reply_text = (
                                f"Oh no — it looks like the {_unavail_name} on that date "
                                f"is fully booked! Would you like to try a different date?\n\n"
                                f"Warm regards,\n{_unavail_sig}"
                            )
                            log(f"Soft hold race for {from_email}: slot full at insert time")
```

**4f.** Modify Step 5 reply selection. Replace the block:
```python
                # Step 5: Booking flow
                if "booking" in result.get("intents", []):
                    fields_now = th["fields"]
                    if (th["flags"].get("slot_checked")
                            and not th["flags"].get("slot_available")
                            and result.get("flags", {}).get("awaiting_booking_confirmation")):
                        reply_text = result.get("reply_hold_failed") or result["reply"]
                    else:
                        reply_text = result["reply"]
```
With:
```python
                # Step 5: Booking flow
                if "booking" in result.get("intents", []):
                    fields_now = th["fields"]
```

**4g.** In Step 5 hold creation success, change the [PAYMENT_LINK] replacement. Replace:
```python
                            reply_text = result["reply"].replace("[PAYMENT_LINK]", pay_link)
```
With:
```python
                            reply_text = reply_text.replace("[PAYMENT_LINK]", pay_link)
```

### Step 5 — Update file headers

- `marina_agent.py` line 3: `Brief 045` → `Brief 046`
- `email_poller.py` line 4: `Brief 045` → `Brief 046`

## Tests

Save as `tests/test_046_hybrid_state_machine.py`:

```python
#!/usr/bin/env python3
"""Tests for Brief 046 — Hybrid refactor: Python state machine + simplified prompt."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        print(f"  {name} PASS")
        passed += 1
    else:
        print(f"  {name} FAIL")
        failed += 1

print("Running Brief 046 tests...")

# Import helpers from email_poller
from email_poller import _day_matches, _suggest_dates, _build_booking_summary, _build_action_context, _post_validate

# T1-T4: _day_matches
check("T1: daily matches any day", _day_matches("Monday", "daily"))
check("T2: Monday doesn't match Fridays only", not _day_matches("Monday", "Fridays only"))
check("T3: Friday matches Fridays only", _day_matches("Friday", "Fridays only"))
check("T4: Wednesday matches Wednesdays and Sundays", _day_matches("Wednesday", "Wednesdays and Sundays"))

# T5: _suggest_dates returns valid alternatives
suggestions = _suggest_dates("2026-03-09", "Fridays only")  # Monday
check("T5: suggest_dates returns Friday suggestions", "Friday" in suggestions)

# T6: _build_action_context with awaiting_booking_confirmation
ctx = _build_action_context({"flags": {"awaiting_booking_confirmation": True}})
check("T6: action_context contains ACTION for awaiting", "ACTION:" in ctx and "booking_confirmed" in ctx)

# T7: _build_action_context with empty flags
ctx_empty = _build_action_context({"flags": {}})
check("T7: action_context empty for no flags", ctx_empty == "")

# T8: _build_action_context includes reply_hold_failed instruction
ctx2 = _build_action_context({"flags": {"awaiting_booking_confirmation": True}})
check("T8: action_context mentions reply_hold_failed", "reply_hold_failed" in ctx2)

# T9: _post_validate with multi-departure trip, no departure_time
th_multi = {"fields": {"experience": "Klein Curacao", "date": "2026-03-25", "guests": "2", "trip_key": "klein_curacao"}, "flags": {}}
trip_multi = {"display_name": "Klein Curacao Trip", "departures": [{"time": "08:00", "vessel": "BlueFinn2", "departure_point": "Jan Thiel Beach"}, {"time": "08:30", "vessel": "BlueFinn1", "departure_point": "Jan Thiel Beach"}], "days_available": "daily"}
result_booking = {"intents": ["booking"], "fields": {}, "flags": {}}
override, awaiting = _post_validate(th_multi, result_booking, trip_multi)
check("T9: multi-departure asks for departure time", override is not None and "departure" in override.lower())
check("T10: multi-departure does not set awaiting", awaiting == False)

# T11: _post_validate with single-departure trip
th_single = {"fields": {"experience": "Sunset Cruise", "date": "2026-03-26", "guests": "2", "trip_key": "sunset_cruise"}, "flags": {}}
trip_single = {"display_name": "Sunset Cruise", "departures": [{"time": "17:30", "vessel": "Kailani", "departure_point": "Village Marina"}], "days_available": "Tuesday, Thursday, Friday, Saturday", "price_adult_usd": 79, "included": ["open bar", "snacks"]}
override_s, awaiting_s = _post_validate(th_single, result_booking, trip_single)
check("T11: single-departure builds summary", override_s is not None and "Shall I lock this in" in override_s)
check("T12: single-departure sets awaiting", awaiting_s == True)

# T13: _post_validate with invalid day-of-week
th_bad_day = {"fields": {"experience": "Snorkeling", "date": "2026-03-09", "guests": "2", "trip_key": "snorkeling_3in1"}, "flags": {}}
trip_fri = {"display_name": "3-in-1 Snorkeling Trip", "departures": [{"time": "10:00"}], "days_available": "Fridays only"}
override_d, awaiting_d = _post_validate(th_bad_day, result_booking, trip_fri)
check("T13: wrong day returns day-of-week error", override_d is not None and "Friday" in override_d)
check("T14: wrong day does not set awaiting", awaiting_d == False)

# T15: _post_validate skips when already awaiting
th_already = {"fields": {"experience": "X", "date": "2026-03-25", "guests": "2", "trip_key": "klein_curacao"}, "flags": {"awaiting_booking_confirmation": True}}
override_a, awaiting_a = _post_validate(th_already, result_booking, trip_multi)
check("T15: skips validation when already awaiting", override_a is None and awaiting_a == False)

# T16: _post_validate skips when missing required fields
th_incomplete = {"fields": {"experience": "X", "date": "2026-03-25"}, "flags": {}}
override_inc, awaiting_inc = _post_validate(th_incomplete, result_booking, trip_multi)
check("T16: skips when missing required fields", override_inc is None and awaiting_inc == False)

# T17: _build_booking_summary generates correct summary
summary = _build_booking_summary(
    {"trip_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "departure_time": "17:30"},
    trip_single
)
check("T17: summary contains trip name", "Sunset Cruise" in summary)
check("T18: summary contains price", "$158" in summary)
check("T19: summary contains departure", "17:30" in summary)
check("T20: summary ends with lock-in question", "Shall I lock this in" in summary)

# T21: Prompt no longer contains FIRST/SECOND/THIRD check text
import marina_agent
prompt = marina_agent._build_prompt("test@test.com", "Test", "Test", {}, {})
check("T21: prompt has no FIRST check", "FIRST:" not in prompt and "- FIRST" not in prompt)
check("T22: prompt has no SECOND check", "SECOND:" not in prompt and "- SECOND" not in prompt)
check("T23: prompt has no THIRD check", "THIRD:" not in prompt and "- THIRD" not in prompt)

# T24: Prompt contains BOOKING BEHAVIOUR
check("T24: prompt contains BOOKING BEHAVIOUR", "BOOKING BEHAVIOUR:" in prompt)

# T25: Prompt contains action_context placeholder resolved
prompt_with_action = marina_agent._build_prompt("t@t.com", "T", "T", {}, {}, "ACTION: test instruction")
check("T25: action_context injected into prompt", "ACTION: test instruction" in prompt_with_action)

# T26: process_message accepts action_context parameter
import inspect
sig = inspect.signature(marina_agent.process_message)
check("T26: process_message has action_context param", "action_context" in sig.parameters)

# T27: Prompt no longer contains AVAILABILITY CONTEXT
check("T27: no AVAILABILITY CONTEXT in prompt", "AVAILABILITY CONTEXT:" not in prompt)

# T28: _post_validate respects needs_child_ages flag
result_kids = {"intents": ["booking"], "fields": {}, "flags": {"needs_child_ages": True}}
th_kids = {"fields": {"experience": "Klein", "date": "2026-03-25", "guests": "4", "trip_key": "klein_curacao", "departure_time": "08:00"}, "flags": {}}
override_k, awaiting_k = _post_validate(th_kids, result_kids, trip_multi)
check("T28: needs_child_ages skips summary", override_k is None and awaiting_k == False)

print(f"\n{passed}/{passed+failed} tests passed.")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("All tests passed.")
```

## Known Limitations
- **Child pricing in summary**: `_build_booking_summary` uses adult rate for all guests. When children are present and ages are known, the summary price may be higher than actual. The `needs_child_ages` flag correctly prevents premature summaries, but after ages are provided, the summary uses adult pricing. Follow-up brief should add `children_count`/`children_ages` fields and tiered pricing to `_build_booking_summary`. Only affects `klein_curacao` (the only trip with `price_child_usd`).

## Success Condition
All 28 tests pass. Prompt no longer contains state machine logic (FIRST/SECOND/THIRD checks, AVAILABILITY CONTEXT). Python controls day-of-week validation, departure time gating, booking summary generation, and `awaiting_booking_confirmation` flag management.

## Rollback
Revert both files to Brief 045 versions: `git checkout HEAD -- src/marina_agent.py src/email_poller.py`
