#!/usr/bin/env python3
"""Capacity system stress tests — state_registry + gws_calendar.check_availability.

Tests the full lifecycle: soft holds, expiration, confirmation, cancellation,
capacity math, race conditions, and edge cases.
"""
import sys, os, time
from datetime import datetime, timezone, timedelta

# Use a temporary DB for tests — don't touch the real one
from shared import state_registry
import tempfile
_test_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_test_db.close()
state_registry.DB_PATH = _test_db.name
# Re-initialise with new path
state_registry._get_conn().close()

from shared import config_loader
from agents.marina import gws_calendar


def _reset_db():
    """Wipe trip_bookings between tests."""
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM trip_bookings")
    conn.commit()
    conn.close()


# ─── BASIC OPERATIONS ───

def test_empty_db_full_capacity():
    """S1: Empty DB returns full capacity for any slot."""
    _reset_db()
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 30, f"Expected 30, got {spots}"
    print("  S1 PASS: Empty DB → full capacity (30 spots)")


def test_soft_hold_reduces_capacity():
    """S2: Creating a soft hold reduces available spots."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 4, 30)
    assert hold_id is not None, "Hold creation must succeed"
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 26, f"Expected 26, got {spots}"
    print("  S2 PASS: Soft hold (4 guests) reduces 30 → 26")


def test_multiple_holds_accumulate():
    """S3: Multiple holds on same slot accumulate correctly."""
    _reset_db()
    state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 10, 30)
    state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 8, 30)
    state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 5, 30)
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 7, f"Expected 7 (30-10-8-5), got {spots}"
    print("  S3 PASS: Three holds (10+8+5=23) → 7 remaining")


def test_hold_at_exact_capacity():
    """S4: Hold that exactly fills capacity succeeds."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 30, 30)
    assert hold_id is not None, "Exact capacity hold must succeed"
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 0, f"Expected 0, got {spots}"
    print("  S4 PASS: Hold at exact capacity (30/30) succeeds, 0 remaining")


def test_hold_over_capacity_rejected():
    """S5: Hold exceeding capacity returns None."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 31, 30)
    assert hold_id is None, "Over-capacity hold must be rejected"
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 30, f"Expected 30 unchanged, got {spots}"
    print("  S5 PASS: Over-capacity hold (31/30) rejected, capacity unchanged")


def test_hold_partial_then_overflow():
    """S6: Partial hold then overflow hold: second rejected, first preserved."""
    _reset_db()
    h1 = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 28, 30)
    assert h1 is not None
    h2 = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 5, 30)
    assert h2 is None, "Overflow hold (28+5=33 > 30) must be rejected"
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 2, f"Expected 2 (only first hold), got {spots}"
    print("  S6 PASS: 28 + 5 overflow → second rejected, 2 remaining")


# ─── CONFIRM / CANCEL ───

def test_confirm_hold():
    """S7: Confirmed hold stays counted, no expiration."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 4, 30)
    ok = state_registry.confirm_hold(hold_id)
    assert ok, "confirm_hold must return True"
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 26, f"Confirmed hold must still count. Expected 26, got {spots}"
    print("  S7 PASS: Confirmed hold stays counted (26 remaining)")


def test_cancel_hold_restores_capacity():
    """S8: Cancelled hold restores capacity."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 10, 30)
    spots_before = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots_before == 20
    state_registry.cancel_hold(hold_id)
    spots_after = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots_after == 30, f"Cancel must restore. Expected 30, got {spots_after}"
    print("  S8 PASS: Cancel restores capacity (20 → 30)")


def test_double_confirm():
    """S9: Double confirm is idempotent."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 4, 30)
    assert state_registry.confirm_hold(hold_id)
    ok2 = state_registry.confirm_hold(hold_id)  # already confirmed
    assert not ok2, "Second confirm should return False (already confirmed)"
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 26, "Still 26 after double confirm"
    print("  S9 PASS: Double confirm is idempotent")


def test_cancel_confirmed():
    """S10: Cancelling a confirmed hold still restores capacity."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 4, 30)
    state_registry.confirm_hold(hold_id)
    state_registry.cancel_hold(hold_id)
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 30, f"Cancel after confirm must restore. Expected 30, got {spots}"
    print("  S10 PASS: Cancel confirmed hold restores capacity")


def test_cancel_nonexistent():
    """S11: Cancelling nonexistent hold returns False, no crash."""
    _reset_db()
    ok = state_registry.cancel_hold(99999)
    assert not ok, "Cancel of nonexistent must return False"
    print("  S11 PASS: Cancel nonexistent hold → False, no crash")


# ─── EXPIRATION ───

def test_expired_hold_not_counted():
    """S12: Manually expired hold doesn't count toward capacity."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 10, 30)
    # Manually set expires_at to the past
    conn = state_registry._get_conn()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE trip_bookings SET expires_at=? WHERE id=?", (past, hold_id))
    conn.commit()
    conn.close()
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 30, f"Expired hold must not count. Expected 30, got {spots}"
    print("  S12 PASS: Expired hold not counted (30 remaining)")


def test_expire_stale_holds():
    """S13: expire_stale_holds() marks old holds as expired."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 10, 30)
    conn = state_registry._get_conn()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE trip_bookings SET expires_at=? WHERE id=?", (past, hold_id))
    conn.commit()
    conn.close()
    count = state_registry.expire_stale_holds()
    assert count == 1, f"Expected 1 expired, got {count}"
    conn = state_registry._get_conn()
    row = conn.execute("SELECT status FROM trip_bookings WHERE id=?", (hold_id,)).fetchone()
    conn.close()
    assert row[0] == 'expired', f"Status must be 'expired', got {row[0]}"
    print("  S13 PASS: expire_stale_holds() correctly marks old holds")


def test_confirmed_hold_never_expires():
    """S14: Confirmed holds have no expires_at and are never expired."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 10, 30)
    state_registry.confirm_hold(hold_id)
    count = state_registry.expire_stale_holds()
    assert count == 0, "Confirmed holds must not be expired"
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 20, f"Confirmed hold must persist. Expected 20, got {spots}"
    print("  S14 PASS: Confirmed hold never expires")


def test_create_hold_expires_stale_first():
    """S15: create_soft_hold expires stale holds before checking capacity."""
    _reset_db()
    # Fill capacity
    h1 = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 30, 30)
    assert h1 is not None
    # Manually expire it
    conn = state_registry._get_conn()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE trip_bookings SET expires_at=? WHERE id=?", (past, h1))
    conn.commit()
    conn.close()
    # New hold should succeed because stale is expired atomically
    h2 = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 4, 30)
    assert h2 is not None, "Must succeed after expiring stale hold"
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 26, f"Expected 26, got {spots}"
    print("  S15 PASS: create_soft_hold expires stale before checking capacity")


# ─── SLOT ISOLATION ───

def test_different_dates_isolated():
    """S16: Holds on different dates don't affect each other."""
    _reset_db()
    state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 20, 30)
    state_registry.create_soft_hold("klein_curacao", "2026-04-02", "08:00", 15, 30)
    spots_d1 = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    spots_d2 = state_registry.get_spots_remaining("klein_curacao", "2026-04-02", "08:00", 30)
    assert spots_d1 == 10, f"Day 1: expected 10, got {spots_d1}"
    assert spots_d2 == 15, f"Day 2: expected 15, got {spots_d2}"
    print("  S16 PASS: Different dates are isolated (10 and 15)")


def test_different_departures_isolated():
    """S17: Klein Curacao 08:00 and 08:30 are separate capacity pools."""
    _reset_db()
    state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 25, 30)
    state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:30", 10, 30)
    spots_0800 = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    spots_0830 = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:30", 30)
    assert spots_0800 == 5, f"08:00: expected 5, got {spots_0800}"
    assert spots_0830 == 20, f"08:30: expected 20, got {spots_0830}"
    print("  S17 PASS: 08:00 and 08:30 are separate capacity pools")


def test_different_trips_isolated():
    """S18: Different trip_keys don't interfere."""
    _reset_db()
    state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 28, 30)
    state_registry.create_soft_hold("jet_ski", "2026-04-01", "08:00", 3, 4)
    spots_kc = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    spots_js = state_registry.get_spots_remaining("jet_ski", "2026-04-01", "08:00", 4)
    assert spots_kc == 2, f"Klein: expected 2, got {spots_kc}"
    assert spots_js == 1, f"Jet ski: expected 1, got {spots_js}"
    print("  S18 PASS: Different trips isolated (klein=2, jet_ski=1)")


# ─── JET SKI (capacity=4, 12 time slots) ───

def test_jet_ski_capacity():
    """S19: Jet ski capacity is 4 per slot, each hourly slot independent."""
    _reset_db()
    for hour in range(8, 20):
        state_registry.create_soft_hold("jet_ski", "2026-04-01", f"{hour:02d}:00", 2, 4)
    # Check each slot has 2 remaining
    for hour in range(8, 20):
        spots = state_registry.get_spots_remaining("jet_ski", "2026-04-01", f"{hour:02d}:00", 4)
        assert spots == 2, f"Jet ski {hour:02d}:00: expected 2, got {spots}"
    print("  S19 PASS: Jet ski 12 slots each with independent capacity (2/4 used)")


def test_jet_ski_full_slot():
    """S20: Jet ski slot fills at 4 guests."""
    _reset_db()
    h1 = state_registry.create_soft_hold("jet_ski", "2026-04-01", "10:00", 4, 4)
    assert h1 is not None
    h2 = state_registry.create_soft_hold("jet_ski", "2026-04-01", "10:00", 1, 4)
    assert h2 is None, "5th guest on jet ski (cap=4) must be rejected"
    # Adjacent slot still open
    spots_11 = state_registry.get_spots_remaining("jet_ski", "2026-04-01", "11:00", 4)
    assert spots_11 == 4, f"11:00 must be unaffected. Expected 4, got {spots_11}"
    print("  S20 PASS: Jet ski fills at 4, adjacent slot unaffected")


# ─── CHECK_AVAILABILITY VIA GWS_CALENDAR ───

def test_check_availability_empty():
    """S21: gws_calendar.check_availability on empty DB returns full capacity."""
    _reset_db()
    avail = gws_calendar.check_availability("klein_curacao", "2026-04-01", "08:00", 4)
    assert avail["available"] is True
    assert avail["spots_remaining"] == 30
    assert avail["capacity"] == 30
    print("  S21 PASS: check_availability empty → available=True, 30/30")


def test_check_availability_with_hold():
    """S22: check_availability reflects existing holds."""
    _reset_db()
    state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 28, 30)
    avail = gws_calendar.check_availability("klein_curacao", "2026-04-01", "08:00", 4)
    assert avail["available"] is False, "28+4=32 > 30, must be unavailable"
    assert avail["spots_remaining"] == 2
    avail2 = gws_calendar.check_availability("klein_curacao", "2026-04-01", "08:00", 2)
    assert avail2["available"] is True, "28+2=30, fits exactly"
    print("  S22 PASS: check_availability with hold → correct availability")


def test_check_availability_all_trips():
    """S23: check_availability returns correct capacity for each trip type."""
    _reset_db()
    expected = {
        "klein_curacao": 30,
        "snorkeling_3in1": 20,
        "west_coast_beach": 25,
        "sunset_cruise": 20,
        "jet_ski": 4,
    }
    for trip_key, cap in expected.items():
        trip = config_loader.get_trip(trip_key)
        deps = trip.get("departures", [])
        start = deps[0]["time"] if deps else "09:00"
        avail = gws_calendar.check_availability(trip_key, "2026-04-01", start)
        assert avail["capacity"] == cap, \
            f"{trip_key}: expected capacity={cap}, got {avail['capacity']}"
    print(f"  S23 PASS: All 5 trip capacities correct: {expected}")


# ─── COMPLEX LIFECYCLE ───

def test_full_booking_lifecycle():
    """S24: Full lifecycle: hold → check → confirm → check → still counted."""
    _reset_db()
    # Hold
    hold_id = state_registry.create_soft_hold("sunset_cruise", "2026-04-05", "17:30", 6, 20)
    assert hold_id is not None
    spots = state_registry.get_spots_remaining("sunset_cruise", "2026-04-05", "17:30", 20)
    assert spots == 14
    # Confirm
    state_registry.confirm_hold(hold_id)
    spots = state_registry.get_spots_remaining("sunset_cruise", "2026-04-05", "17:30", 20)
    assert spots == 14, "Confirmed still counts"
    # Expire stale (shouldn't touch confirmed)
    state_registry.expire_stale_holds()
    spots = state_registry.get_spots_remaining("sunset_cruise", "2026-04-05", "17:30", 20)
    assert spots == 14, "Confirmed survives expire sweep"
    print("  S24 PASS: Full lifecycle: hold → confirm → survives expiry (14 remaining)")


def test_hold_cancel_rebook():
    """S25: Hold → cancel → rebook: capacity restored then re-consumed."""
    _reset_db()
    h1 = state_registry.create_soft_hold("west_coast_beach", "2026-04-06", "09:00", 25, 25)
    assert h1 is not None
    spots = state_registry.get_spots_remaining("west_coast_beach", "2026-04-06", "09:00", 25)
    assert spots == 0, "Fully booked"
    # Try to add more — rejected
    h2 = state_registry.create_soft_hold("west_coast_beach", "2026-04-06", "09:00", 1, 25)
    assert h2 is None
    # Cancel first hold
    state_registry.cancel_hold(h1)
    spots = state_registry.get_spots_remaining("west_coast_beach", "2026-04-06", "09:00", 25)
    assert spots == 25, "Capacity restored after cancel"
    # Rebook
    h3 = state_registry.create_soft_hold("west_coast_beach", "2026-04-06", "09:00", 10, 25)
    assert h3 is not None
    spots = state_registry.get_spots_remaining("west_coast_beach", "2026-04-06", "09:00", 25)
    assert spots == 15
    print("  S25 PASS: Hold → cancel → rebook works (25 → 0 → 25 → 15)")


def test_mixed_statuses():
    """S26: Mix of soft_hold, confirmed, cancelled, expired — only active ones count."""
    _reset_db()
    h1 = state_registry.create_soft_hold("snorkeling_3in1", "2026-04-07", "10:00", 5, 20)
    h2 = state_registry.create_soft_hold("snorkeling_3in1", "2026-04-07", "10:00", 3, 20)
    h3 = state_registry.create_soft_hold("snorkeling_3in1", "2026-04-07", "10:00", 4, 20)
    h4 = state_registry.create_soft_hold("snorkeling_3in1", "2026-04-07", "10:00", 2, 20)
    # h1: confirm, h2: cancel, h3: expire, h4: leave as soft_hold
    state_registry.confirm_hold(h1)
    state_registry.cancel_hold(h2)
    conn = state_registry._get_conn()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE trip_bookings SET expires_at=? WHERE id=?", (past, h3))
    conn.commit()
    conn.close()
    # h1 (5, confirmed) + h4 (2, soft_hold) = 7 active
    spots = state_registry.get_spots_remaining("snorkeling_3in1", "2026-04-07", "10:00", 20)
    assert spots == 13, f"Expected 13 (20 - 5 confirmed - 2 soft_hold), got {spots}"
    print("  S26 PASS: Mixed statuses: only confirmed + active soft_hold count (13 remaining)")


def test_zero_guests_hold():
    """S27: Hold with 0 guests succeeds but doesn't reduce capacity."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 0, 30)
    assert hold_id is not None, "0-guest hold should succeed"
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 30, f"0-guest hold must not reduce capacity. Got {spots}"
    print("  S27 PASS: 0-guest hold succeeds, capacity unchanged")


def test_many_small_holds_fill_capacity():
    """S28: Many 1-guest holds fill capacity correctly."""
    _reset_db()
    hold_ids = []
    for i in range(4):
        h = state_registry.create_soft_hold("jet_ski", "2026-04-01", "14:00", 1, 4)
        assert h is not None, f"Hold {i+1} of 4 must succeed"
        hold_ids.append(h)
    # 5th should fail
    h5 = state_registry.create_soft_hold("jet_ski", "2026-04-01", "14:00", 1, 4)
    assert h5 is None, "5th 1-guest hold must be rejected (cap=4)"
    spots = state_registry.get_spots_remaining("jet_ski", "2026-04-01", "14:00", 4)
    assert spots == 0
    # Cancel one, then add one
    state_registry.cancel_hold(hold_ids[2])
    h6 = state_registry.create_soft_hold("jet_ski", "2026-04-01", "14:00", 1, 4)
    assert h6 is not None, "After cancel, new hold must succeed"
    print("  S28 PASS: 4x1-guest fills cap=4, 5th rejected, cancel+rebook works")


# ─── CLEANUP ───

def cleanup():
    """Remove temp database."""
    try:
        os.unlink(_test_db.name)
    except Exception:
        pass


if __name__ == "__main__":
    tests = [
        test_empty_db_full_capacity,
        test_soft_hold_reduces_capacity,
        test_multiple_holds_accumulate,
        test_hold_at_exact_capacity,
        test_hold_over_capacity_rejected,
        test_hold_partial_then_overflow,
        test_confirm_hold,
        test_cancel_hold_restores_capacity,
        test_double_confirm,
        test_cancel_confirmed,
        test_cancel_nonexistent,
        test_expired_hold_not_counted,
        test_expire_stale_holds,
        test_confirmed_hold_never_expires,
        test_create_hold_expires_stale_first,
        test_different_dates_isolated,
        test_different_departures_isolated,
        test_different_trips_isolated,
        test_jet_ski_capacity,
        test_jet_ski_full_slot,
        test_check_availability_empty,
        test_check_availability_with_hold,
        test_check_availability_all_trips,
        test_full_booking_lifecycle,
        test_hold_cancel_rebook,
        test_mixed_statuses,
        test_zero_guests_hold,
        test_many_small_holds_fill_capacity,
    ]
    print(f"Running {len(tests)} capacity stress tests...\n")
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {t.__name__}: {e}")
            failed += 1
    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    cleanup()
    if failed:
        sys.exit(1)
    print("All tests passed.")
