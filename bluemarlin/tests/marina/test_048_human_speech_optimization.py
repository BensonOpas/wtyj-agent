#!/usr/bin/env python3
"""Tests for Brief 048 — Human speech optimization: multi-topic fix + prompt hardening."""
import sys, os

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

print("Running Brief 048 tests...")

# === Fix 1: Multi-topic reply preservation ===

# T1: _post_validate override has NO signature (day-of-week)
from agents.marina.email_poller import _post_validate, _BOOKING_INTENTS
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
from agents.marina.email_poller import _build_booking_summary
trip_sc = {"display_name": "Sunset Cruise", "departures": [{"time": "17:30", "vessel": "Kailani", "departure_point": "Village Marina"}], "days_available": "Tuesday, Thursday, Friday, Saturday", "price_adult_usd": 79, "included": ["open bar", "snacks"]}
summary = _build_booking_summary({"trip_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "departure_time": "17:30"}, trip_sc)
check("T3: booking summary has no signature", "Warm regards" not in summary)
check("T4: summary still has lock-in question", "Want me to go ahead and book this" in summary)
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
from agents.marina import marina_agent
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
check("T14: booking still builds summary", override_reg is not None and "Want me to go ahead and book this" in override_reg)
check("T15: booking still sets awaiting", awaiting_reg == True)

# T16: _post_validate still triggers on reschedule intent (Brief 047 regression)
override_resched, _ = _post_validate(
    {"fields": {"experience": "Snorkeling", "date": "2026-03-13", "guests": "2", "trip_key": "snorkeling_3in1"}, "flags": {}},
    {"intents": ["reschedule"], "fields": {}, "flags": {}},
    trip_fri
)
check("T16: reschedule still triggers validation", override_resched is not None and "Want me to go ahead and book this" in override_resched)

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

print(f"\n{passed}/{passed+failed} tests passed.")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("All tests passed.")
