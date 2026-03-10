#!/usr/bin/env python3
"""Tests for Brief 047 — Treat reschedule intent as booking-active."""
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

print("Running Brief 047 tests...")

# T1-T3: _BOOKING_INTENTS constant
from email_poller import _BOOKING_INTENTS
check("T1: booking in _BOOKING_INTENTS", "booking" in _BOOKING_INTENTS)
check("T2: reschedule in _BOOKING_INTENTS", "reschedule" in _BOOKING_INTENTS)
check("T3: inquiry NOT in _BOOKING_INTENTS", "inquiry" not in _BOOKING_INTENTS)

# T4-T5: _post_validate triggers on reschedule intent
from email_poller import _post_validate
th_resched = {"fields": {"experience": "3-in-1 Snorkeling", "date": "2026-03-13", "guests": "2", "trip_key": "snorkeling_3in1"}, "flags": {}}
trip_snorkel = {"display_name": "3-in-1 Snorkeling Trip", "departures": [{"time": "10:00", "vessel": "TopCat", "departure_point": "Mood Beach pier"}], "days_available": "Fridays only", "price_adult_usd": 110, "included": ["lunch", "3 snorkel sites"]}
result_resched = {"intents": ["reschedule"], "fields": {"date": "2026-03-13"}, "flags": {}}
override_r, awaiting_r = _post_validate(th_resched, result_resched, trip_snorkel)
check("T4: reschedule triggers summary", override_r is not None and "Want me to go ahead and book this" in override_r)
check("T5: reschedule sets awaiting", awaiting_r == True)

# T6: _post_validate does NOT trigger on inquiry intent
result_inquiry = {"intents": ["inquiry"], "fields": {}, "flags": {}}
override_i, awaiting_i = _post_validate(th_resched, result_inquiry, trip_snorkel)
check("T6: inquiry skips validation", override_i is None and awaiting_i == False)

# T7: _post_validate still triggers on booking intent (regression)
result_booking = {"intents": ["booking"], "fields": {}, "flags": {}}
override_b, awaiting_b = _post_validate(th_resched, result_booking, trip_snorkel)
check("T7: booking still triggers summary", override_b is not None and "Want me to go ahead and book this" in override_b)

# T8: wrong day + reschedule returns day-of-week error
th_bad = {"fields": {"experience": "3-in-1 Snorkeling", "date": "2026-03-09", "guests": "2", "trip_key": "snorkeling_3in1"}, "flags": {}}
result_resched_bad = {"intents": ["reschedule"], "fields": {"date": "2026-03-09"}, "flags": {}}
override_bad, awaiting_bad = _post_validate(th_bad, result_resched_bad, trip_snorkel)
check("T8: wrong day caught on reschedule", override_bad is not None and "Friday" in override_bad)

# T9: summary contains correct price for snorkeling ($110 x 2 = $220)
check("T9: summary has correct total", "$220" in override_r)

# T10: summary contains trip name
check("T10: summary has trip name", "3-in-1 Snorkeling Trip" in override_r)

print(f"\n{passed}/{passed+failed} tests passed.")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("All tests passed.")
