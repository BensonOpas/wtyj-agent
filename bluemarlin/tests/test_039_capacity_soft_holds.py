#!/usr/bin/env python3
# bluemarlin/tests/test_039_capacity_soft_holds.py
# Brief 039 — Capacity-aware booking with soft holds
# Run: cd bluemarlin && source ~/.zshrc && python3 tests/test_039_capacity_soft_holds.py

import os, sys, sqlite3, threading, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import state_registry
import gws_calendar
import config_loader

# ── Setup: clear trip_bookings for a clean run ──────────────────────────────
conn = sqlite3.connect(state_registry.DB_PATH)
conn.execute("DELETE FROM trip_bookings WHERE trip_key='klein_curacao' AND date='2026-04-01'")
conn.execute("DELETE FROM trip_bookings WHERE trip_key='klein_curacao' AND date='2026-04-02'")
conn.execute("DELETE FROM trip_bookings WHERE trip_key='jet_ski' AND date='2026-04-01'")
conn.commit()
conn.close()
print("Setup: cleared test rows from trip_bookings\n")

# T1: Book 20 guests Klein Curaçao 2026-04-01 08:00 → succeeds, spots_remaining = 10
print("T1: Book 20 guests klein_curacao 2026-04-01 08:00...")
hold1 = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 20, 30)
assert hold1 is not None, f"T1 fail: create_soft_hold returned None (expected hold_id)"
spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
assert spots == 10, f"T1 fail: expected spots_remaining=10, got {spots}"
print(f"T1 pass — hold_id={hold1}, spots_remaining={spots}")

# T2: Book 15 more guests same slot → FAILS (20+15=35 > 30)
print("\nT2: Book 15 more guests same slot (would exceed capacity)...")
hold2 = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 15, 30)
assert hold2 is None, f"T2 fail: expected None (over capacity), got hold_id={hold2}"
print(f"T2 pass — correctly rejected (hold_id=None)")

# T3: Book 10 more guests same slot → SUCCEEDS (20+10=30, exactly at limit)
print("\nT3: Book 10 more guests same slot (fills to capacity)...")
hold3 = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 10, 30)
assert hold3 is not None, f"T3 fail: expected hold_id, got None (should fit at limit)"
spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
assert spots == 0, f"T3 fail: expected spots_remaining=0, got {spots}"
print(f"T3 pass — hold_id={hold3}, spots_remaining={spots}")

# T4: Book 1 more → FAILS (slot full)
print("\nT4: Book 1 more guest (slot full)...")
hold4 = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 1, 30)
assert hold4 is None, f"T4 fail: expected None (slot full), got hold_id={hold4}"
print(f"T4 pass — correctly rejected when full")

# T5: Same trip 08:30 → independent slot, 30 available
print("\nT5: Klein Curaçao 08:30 — independent slot...")
avail5 = gws_calendar.check_availability("klein_curacao", "2026-04-01", "08:30", 1)
assert avail5["available"], f"T5 fail: 08:30 slot should be independent, got {avail5}"
assert avail5["spots_remaining"] == 30, \
    f"T5 fail: expected 30 spots for 08:30, got {avail5['spots_remaining']}"
print(f"T5 pass — 08:30 independent: spots_remaining={avail5['spots_remaining']}")

# T6: Same trip April 2 → fresh slot, 30 available
print("\nT6: Klein Curaçao April 2 — fresh date...")
avail6 = gws_calendar.check_availability("klein_curacao", "2026-04-02", "08:00", 1)
assert avail6["available"], f"T6 fail: April 2 should be fresh, got {avail6}"
assert avail6["spots_remaining"] == 30, \
    f"T6 fail: expected 30 for April 2, got {avail6['spots_remaining']}"
print(f"T6 pass — April 2 fresh: spots_remaining={avail6['spots_remaining']}")

# T7: Simulate 24h expiry → expired hold's guests released
# get_spots_remaining filters by expires_at > now, so an already-expired row
# is already invisible to it. To correctly test expiry, we must:
# 1. Insert an ACTIVE hold (expires far in the future) → capacity consumed
# 2. Verify spots are consumed (spots_before == 0)
# 3. Force-expire by updating expires_at to the past via direct SQL
# 4. Call expire_stale_holds() → status becomes 'expired'
# 5. Verify spots are released (spots_after == 4)
print("\nT7: Simulate expired hold...")
conn = sqlite3.connect(state_registry.DB_PATH)
conn.execute("DELETE FROM trip_bookings WHERE trip_key='jet_ski' AND date='2026-04-01'")
future_exp = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
now_str = datetime.now(timezone.utc).isoformat()
conn.execute(
    "INSERT INTO trip_bookings "
    "(trip_key, date, departure_time, guests, status, expires_at, created_at) "
    "VALUES ('jet_ski', '2026-04-01', '10:00', 4, 'soft_hold', ?, ?)",
    (future_exp, now_str)
)
conn.commit()
conn.close()
spots_before = state_registry.get_spots_remaining("jet_ski", "2026-04-01", "10:00", 4)
assert spots_before == 0, f"T7 fail: expected 0 spots with active hold, got {spots_before}"
# Force expiry by backdating expires_at
conn = sqlite3.connect(state_registry.DB_PATH)
conn.execute(
    "UPDATE trip_bookings SET expires_at='2020-01-01T00:00:00+00:00' "
    "WHERE trip_key='jet_ski' AND date='2026-04-01' AND departure_time='10:00'"
)
conn.commit()
conn.close()
expired_count = state_registry.expire_stale_holds()
assert expired_count >= 1, f"T7 fail: expected at least 1 expired hold, got {expired_count}"
spots_after = state_registry.get_spots_remaining("jet_ski", "2026-04-01", "10:00", 4)
assert spots_after == 4, f"T7 fail: expected 4 spots after expiry, got {spots_after}"
print(f"T7 pass — expired_count={expired_count}, spots_after={spots_after}")

# T8: Concurrent race — two threads both check available, only one gets the last spot
print("\nT8: Concurrent race for last spot...")
conn = sqlite3.connect(state_registry.DB_PATH)
conn.execute("DELETE FROM trip_bookings WHERE trip_key='klein_curacao' AND date='2026-04-01'")
conn.commit()
conn.close()
# Pre-fill 29 guests so only 1 spot remains
hold_pre = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 29, 30)
assert hold_pre is not None, "T8 setup fail"

results = []
def try_grab(guests):
    hid = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", guests, 30)
    results.append(hid)

t1 = threading.Thread(target=try_grab, args=(1,))
t2 = threading.Thread(target=try_grab, args=(1,))
t1.start(); t2.start()
t1.join(); t2.join()

successful = [r for r in results if r is not None]
failed = [r for r in results if r is None]
assert len(successful) == 1, \
    f"T8 fail: expected exactly 1 success, got {len(successful)} successes. results={results}"
assert len(failed) == 1, \
    f"T8 fail: expected exactly 1 failure, got {len(failed)} failures. results={results}"
print(f"T8 pass — race handled correctly: 1 success (hold_id={successful[0]}), 1 rejected")

# ── Schema checks ────────────────────────────────────────────────────────────
print("\nSchema check: client.json departure-level calendar_ids...")
kc = config_loader.get_trip("klein_curacao")
assert kc.get("capacity") == 30, f"Schema fail: klein_curacao capacity={kc.get('capacity')}"
assert "calendar_id" not in kc, "Schema fail: trip-level calendar_id still present on klein_curacao"
kc_deps = kc.get("departures", [])
assert len(kc_deps) == 2, f"Schema fail: expected 2 klein_curacao departures, got {len(kc_deps)}"
assert kc_deps[0].get("time") == "08:00", f"Schema fail: first departure not 08:00"
assert kc_deps[0].get("calendar_id", "").endswith("@group.calendar.google.com"), \
    "Schema fail: 08:00 departure missing calendar_id"
assert kc_deps[1].get("time") == "08:30", f"Schema fail: second departure not 08:30"
assert kc_deps[1].get("calendar_id") == \
    "9f25610370f0f57fa395735502fcff767ba8276ee5a280d028fee7f003054928@group.calendar.google.com", \
    f"Schema fail: 08:30 calendar_id wrong"
print("Schema pass — klein_curacao: capacity=30, 2 departure-level calendar_ids")

jk = config_loader.get_trip("jet_ski")
assert jk.get("capacity") == 4, f"Schema fail: jet_ski capacity={jk.get('capacity')}"
assert jk.get("duration_hours") == 1, f"Schema fail: jet_ski duration_hours={jk.get('duration_hours')}"
assert "calendar_id" not in jk, "Schema fail: trip-level calendar_id still present on jet_ski"
jk_deps = jk.get("departures", [])
assert len(jk_deps) == 12, f"Schema fail: jet_ski should have 12 departures, got {len(jk_deps)}"
assert jk_deps[0].get("time") == "08:00", f"Schema fail: first jet_ski departure not 08:00"
assert jk_deps[-1].get("time") == "19:00", f"Schema fail: last jet_ski departure not 19:00"
print("Schema pass — jet_ski: capacity=4, duration_hours=1, 12 hourly departures 08:00–19:00")

print("\nAll 8 tests + schema checks passed.")
