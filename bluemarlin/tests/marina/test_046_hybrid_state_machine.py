#!/usr/bin/env python3
"""Tests for Brief 046 — Hybrid refactor: Python state machine + simplified prompt."""
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

print("Running Brief 046 tests...")

# Import helpers from email_poller
from agents.marina.email_poller import _day_matches, _suggest_dates, _build_booking_summary, _build_action_context, _post_validate

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
check("T11: single-departure builds summary", override_s is not None and "Want me to go ahead and book this" in override_s)
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
check("T20: summary ends with lock-in question", "Want me to go ahead and book this" in summary)

# T21: Prompt no longer contains FIRST/SECOND/THIRD check text
from agents.marina import marina_agent
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
