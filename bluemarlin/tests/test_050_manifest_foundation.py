#!/usr/bin/env python3
"""Tests for Brief 050 — Manifest foundation."""
import sys, os, sqlite3
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

print("Running Brief 050 tests...")

import state_registry
import gws_calendar

# ── state_registry: manifest_events table ──

# T1: manifest_events table exists
conn = state_registry._get_conn()
tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
conn.close()
check("T1: manifest_events table exists", "manifest_events" in tables)

# T2: manifest_events has correct columns
conn = state_registry._get_conn()
cols = [r[1] for r in conn.execute("PRAGMA table_info(manifest_events)").fetchall()]
conn.close()
check("T2: manifest_events columns correct",
      cols == ["trip_key", "date", "departure_time", "calendar_id", "event_id", "html_link", "created_at"])

# T3: trip_bookings has customer_name column
conn = state_registry._get_conn()
cols_tb = [r[1] for r in conn.execute("PRAGMA table_info(trip_bookings)").fetchall()]
conn.close()
check("T3: trip_bookings has customer_name", "customer_name" in cols_tb)

# T4: trip_bookings has customer_email column
check("T4: trip_bookings has customer_email", "customer_email" in cols_tb)

# ── state_registry: new functions exist ──

check("T5: set_booking_ref callable", callable(getattr(state_registry, 'set_booking_ref', None)))
check("T6: get_manifest_event callable", callable(getattr(state_registry, 'get_manifest_event', None)))
check("T7: save_manifest_event callable", callable(getattr(state_registry, 'save_manifest_event', None)))
check("T8: delete_manifest_event callable", callable(getattr(state_registry, 'delete_manifest_event', None)))
check("T9: get_slot_passengers callable", callable(getattr(state_registry, 'get_slot_passengers', None)))

# ── state_registry: manifest CRUD ──

# T10: save + get manifest event
state_registry.save_manifest_event("test_trip", "2099-01-01", "09:00",
                                   "cal@group.calendar.google.com", "evt_123", "https://cal/evt_123")
me = state_registry.get_manifest_event("test_trip", "2099-01-01", "09:00")
check("T10: save+get manifest event", me is not None and me["event_id"] == "evt_123")

# T11: get_manifest_event returns None for missing slot
missing = state_registry.get_manifest_event("no_trip", "2099-01-01", "09:00")
check("T11: get_manifest_event None for missing", missing is None)

# T12: delete_manifest_event removes row
state_registry.delete_manifest_event("test_trip", "2099-01-01", "09:00")
deleted = state_registry.get_manifest_event("test_trip", "2099-01-01", "09:00")
check("T12: delete_manifest_event works", deleted is None)

# ── state_registry: create_soft_hold with customer info ──

# T13: create_soft_hold accepts customer_name and customer_email
hold_id = state_registry.create_soft_hold(
    "test_manifest", "2099-06-01", "10:00", 4, 30,
    customer_name="Test Customer", customer_email="test@example.com"
)
check("T13: create_soft_hold with customer info returns hold_id", hold_id is not None)

# T14: get_slot_passengers returns the customer info
passengers = state_registry.get_slot_passengers("test_manifest", "2099-06-01", "10:00")
check("T14: get_slot_passengers returns customer",
      len(passengers) == 1 and passengers[0]["customer_name"] == "Test Customer"
      and passengers[0]["customer_email"] == "test@example.com"
      and passengers[0]["guests"] == 4)

# T15: set_booking_ref updates the row
state_registry.set_booking_ref(hold_id, "BF-2099-00001")
passengers2 = state_registry.get_slot_passengers("test_manifest", "2099-06-01", "10:00")
check("T15: set_booking_ref updates row", passengers2[0]["booking_ref"] == "BF-2099-00001")

# T16: get_slot_passengers excludes cancelled holds
state_registry.cancel_hold(hold_id)
passengers3 = state_registry.get_slot_passengers("test_manifest", "2099-06-01", "10:00")
check("T16: cancelled hold excluded from passengers", len(passengers3) == 0)

# ── gws_calendar: new functions exist ──

check("T17: _build_manifest_body callable", callable(getattr(gws_calendar, '_build_manifest_body', None)))
# T18-T20: gws_calendar public functions are callable-only checks because
# create_or_update_manifest, update_manifest, and remove_from_manifest call
# _run_gws (live gws CLI) — behavioral testing requires VPS with credentials.
check("T18: create_or_update_manifest callable", callable(getattr(gws_calendar, 'create_or_update_manifest', None)))
check("T19: update_manifest callable", callable(getattr(gws_calendar, 'update_manifest', None)))
check("T20: remove_from_manifest callable", callable(getattr(gws_calendar, 'remove_from_manifest', None)))

# ── gws_calendar: _build_manifest_body output ──

# Insert two test passengers for manifest body test
h1 = state_registry.create_soft_hold("klein_curacao", "2099-07-01", "08:00", 4, 30,
                                     customer_name="Alice", customer_email="alice@test.com")
state_registry.set_booking_ref(h1, "BF-2099-10001")
h2 = state_registry.create_soft_hold("klein_curacao", "2099-07-01", "08:00", 6, 30,
                                     customer_name="Bob", customer_email="bob@test.com")
state_registry.set_booking_ref(h2, "BF-2099-10002")

body = gws_calendar._build_manifest_body(
    "klein_curacao", "2099-07-01", "08:00",
    "cal@group.calendar.google.com", 120, 30, 8
)

# T21: manifest summary contains guest count and capacity
check("T21: summary has 10/30 pax", "10/30 pax" in body["summary"])

# T22: manifest summary contains trip name
check("T22: summary has KLEIN CURACAO", "KLEIN CURACAO" in body["summary"])

# T23: manifest description has total revenue (10 * $120 = $1,200)
check("T23: description has $1,200 revenue", "$1,200" in body["description"])

# T24: manifest description lists both passengers
check("T24: description has Alice", "Alice" in body["description"])
check("T25: description has Bob", "Bob" in body["description"])

# T26: manifest description has booking refs
check("T26: description has BF-2099-10001", "BF-2099-10001" in body["description"])

# T27: manifest body has start/end times
check("T27: body has start dateTime", body["start"]["dateTime"] != "")

# T28: _total_guests field present
check("T28: _total_guests == 10", body.get("_total_guests") == 10)

# ── gws_calendar: create_hold still exists (backward compat) ──
check("T29: create_hold still callable", callable(getattr(gws_calendar, 'create_hold', None)))

# ── file headers ──
with open(os.path.join(os.path.dirname(__file__), "..", "src", "state_registry.py")) as f:
    sr_src = f.read()
check("T30: state_registry header says Brief 050", "Brief 050" in sr_src)

with open(os.path.join(os.path.dirname(__file__), "..", "src", "gws_calendar.py")) as f:
    gc_src = f.read()
check("T31: gws_calendar header says Brief 050", "Brief 050" in gc_src)

# ── Cleanup test data ──
conn = state_registry._get_conn()
conn.execute("DELETE FROM trip_bookings WHERE trip_key IN ('test_manifest', 'klein_curacao') AND date LIKE '2099%'")
conn.execute("DELETE FROM manifest_events WHERE trip_key='test_trip'")
conn.commit()
conn.close()

print(f"\n{passed}/{passed+failed} tests passed.")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("All tests passed.")
