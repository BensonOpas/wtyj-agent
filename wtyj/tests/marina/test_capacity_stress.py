"""Capacity system stress tests — state_registry + gws_calendar.check_availability.

Tests the full lifecycle: soft holds, expiration, confirmation, cancellation,
capacity math, race conditions, and edge cases.
"""
import os
import tempfile
from datetime import datetime, timezone, timedelta

import pytest

from shared import state_registry
from shared import config_loader
from agents.marina import gws_calendar

# Use a temporary DB for tests — don't touch the real one
_test_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_test_db.close()
state_registry.DB_PATH = _test_db.name
# Re-initialise with new path
state_registry._get_conn().close()


def _reset_db():
    """Wipe service_bookings between tests."""
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM service_bookings")
    conn.commit()
    conn.close()


# ── BASIC OPERATIONS ──

def test_empty_db_full_capacity():
    """S1: Empty DB returns full capacity for any slot."""
    _reset_db()
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 30


def test_soft_hold_reduces_capacity():
    """S2: Creating a soft hold reduces available spots."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 4, 30)
    assert hold_id is not None
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 26


def test_multiple_holds_accumulate():
    """S3: Multiple holds on same slot accumulate correctly."""
    _reset_db()
    state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 10, 30)
    state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 8, 30)
    state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 5, 30)
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 7


def test_hold_at_exact_capacity():
    """S4: Hold that exactly fills capacity succeeds."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 30, 30)
    assert hold_id is not None
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 0


def test_hold_over_capacity_rejected():
    """S5: Hold exceeding capacity returns None."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 31, 30)
    assert hold_id is None
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 30


def test_hold_partial_then_overflow():
    """S6: Partial hold then overflow hold: second rejected, first preserved."""
    _reset_db()
    h1 = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 28, 30)
    assert h1 is not None
    h2 = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 5, 30)
    assert h2 is None
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 2


# ── CONFIRM / CANCEL ──

def test_confirm_hold():
    """S7: Confirmed hold stays counted, no expiration."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 4, 30)
    ok = state_registry.confirm_hold(hold_id)
    assert ok
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 26


def test_cancel_hold_restores_capacity():
    """S8: Cancelled hold restores capacity."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 10, 30)
    assert state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30) == 20
    state_registry.cancel_hold(hold_id)
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 30


def test_double_confirm():
    """S9: Double confirm is idempotent."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 4, 30)
    assert state_registry.confirm_hold(hold_id)
    ok2 = state_registry.confirm_hold(hold_id)
    assert not ok2
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 26


def test_cancel_confirmed():
    """S10: Cancelling a confirmed hold still restores capacity."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 4, 30)
    state_registry.confirm_hold(hold_id)
    state_registry.cancel_hold(hold_id)
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 30


def test_cancel_nonexistent():
    """S11: Cancelling nonexistent hold returns False, no crash."""
    _reset_db()
    ok = state_registry.cancel_hold(99999)
    assert not ok


# ── EXPIRATION ──

def test_expired_hold_not_counted():
    """S12: Manually expired hold doesn't count toward capacity."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 10, 30)
    conn = state_registry._get_conn()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE service_bookings SET expires_at=? WHERE id=?", (past, hold_id))
    conn.commit()
    conn.close()
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 30


def test_expire_stale_holds():
    """S13: expire_stale_holds() marks old holds as expired."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 10, 30)
    conn = state_registry._get_conn()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE service_bookings SET expires_at=? WHERE id=?", (past, hold_id))
    conn.commit()
    conn.close()
    count = state_registry.expire_stale_holds()
    assert count == 1
    conn = state_registry._get_conn()
    row = conn.execute("SELECT status FROM service_bookings WHERE id=?", (hold_id,)).fetchone()
    conn.close()
    assert row[0] == 'expired'


def test_confirmed_hold_never_expires():
    """S14: Confirmed holds have no expires_at and are never expired."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 10, 30)
    state_registry.confirm_hold(hold_id)
    count = state_registry.expire_stale_holds()
    assert count == 0
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 20


def test_create_hold_expires_stale_first():
    """S15: create_soft_hold expires stale holds before checking capacity."""
    _reset_db()
    h1 = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 30, 30)
    assert h1 is not None
    conn = state_registry._get_conn()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE service_bookings SET expires_at=? WHERE id=?", (past, h1))
    conn.commit()
    conn.close()
    h2 = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 4, 30)
    assert h2 is not None
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 26


# ── SLOT ISOLATION ──

def test_different_dates_isolated():
    """S16: Holds on different dates don't affect each other."""
    _reset_db()
    state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 20, 30)
    state_registry.create_soft_hold("klein_curacao", "2026-04-02", "08:00", 15, 30)
    assert state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30) == 10
    assert state_registry.get_spots_remaining("klein_curacao", "2026-04-02", "08:00", 30) == 15


def test_different_departures_isolated():
    """S17: Klein Curacao 08:00 and 08:30 are separate capacity pools."""
    _reset_db()
    state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 25, 30)
    state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:30", 10, 30)
    assert state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30) == 5
    assert state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:30", 30) == 20


def test_different_trips_isolated():
    """S18: Different service_keys don't interfere."""
    _reset_db()
    state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 28, 30)
    state_registry.create_soft_hold("jet_ski", "2026-04-01", "08:00", 3, 4)
    assert state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30) == 2
    assert state_registry.get_spots_remaining("jet_ski", "2026-04-01", "08:00", 4) == 1


# ── JET SKI (capacity=4, 12 time slots) ──

def test_jet_ski_capacity():
    """S19: Jet ski capacity is 4 per slot, each hourly slot independent."""
    _reset_db()
    for hour in range(8, 20):
        state_registry.create_soft_hold("jet_ski", "2026-04-01", f"{hour:02d}:00", 2, 4)
    for hour in range(8, 20):
        spots = state_registry.get_spots_remaining("jet_ski", "2026-04-01", f"{hour:02d}:00", 4)
        assert spots == 2, f"Jet ski {hour:02d}:00: expected 2, got {spots}"


def test_jet_ski_full_slot():
    """S20: Jet ski slot fills at 4 guests."""
    _reset_db()
    h1 = state_registry.create_soft_hold("jet_ski", "2026-04-01", "10:00", 4, 4)
    assert h1 is not None
    h2 = state_registry.create_soft_hold("jet_ski", "2026-04-01", "10:00", 1, 4)
    assert h2 is None
    assert state_registry.get_spots_remaining("jet_ski", "2026-04-01", "11:00", 4) == 4


# ── CHECK_AVAILABILITY VIA GWS_CALENDAR ──

def test_check_availability_empty():
    """S21: gws_calendar.check_availability on empty DB returns full capacity."""
    _reset_db()
    avail = gws_calendar.check_availability("klein_curacao", "2026-04-01", "08:00", 4)
    assert avail["available"] is True
    assert avail["spots_remaining"] == 30
    assert avail["capacity"] == 30


def test_check_availability_with_hold():
    """S22: check_availability reflects existing holds."""
    _reset_db()
    state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 28, 30)
    avail = gws_calendar.check_availability("klein_curacao", "2026-04-01", "08:00", 4)
    assert avail["available"] is False
    assert avail["spots_remaining"] == 2
    avail2 = gws_calendar.check_availability("klein_curacao", "2026-04-01", "08:00", 2)
    assert avail2["available"] is True


def test_check_availability_all_trips():
    """S23: check_availability returns correct capacity for each service type."""
    _reset_db()
    expected = {
        "klein_curacao": 30,
        "snorkeling_3in1": 20,
        "west_coast_beach": 25,
        "sunset_cruise": 20,
        "jet_ski": 4,
    }
    for service_key, cap in expected.items():
        service = config_loader.get_service(service_key)
        deps = service.get("slots", [])
        start = deps[0]["time"] if deps else "09:00"
        avail = gws_calendar.check_availability(service_key, "2026-04-01", start)
        assert avail["capacity"] == cap, f"{service_key}: expected capacity={cap}, got {avail['capacity']}"


# ── COMPLEX LIFECYCLE ──

def test_full_booking_lifecycle():
    """S24: Full lifecycle: hold -> check -> confirm -> check -> still counted."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("sunset_cruise", "2026-04-05", "17:30", 6, 20)
    assert hold_id is not None
    assert state_registry.get_spots_remaining("sunset_cruise", "2026-04-05", "17:30", 20) == 14
    state_registry.confirm_hold(hold_id)
    assert state_registry.get_spots_remaining("sunset_cruise", "2026-04-05", "17:30", 20) == 14
    state_registry.expire_stale_holds()
    assert state_registry.get_spots_remaining("sunset_cruise", "2026-04-05", "17:30", 20) == 14


def test_hold_cancel_rebook():
    """S25: Hold -> cancel -> rebook: capacity restored then re-consumed."""
    _reset_db()
    h1 = state_registry.create_soft_hold("west_coast_beach", "2026-04-06", "09:00", 25, 25)
    assert h1 is not None
    assert state_registry.get_spots_remaining("west_coast_beach", "2026-04-06", "09:00", 25) == 0
    h2 = state_registry.create_soft_hold("west_coast_beach", "2026-04-06", "09:00", 1, 25)
    assert h2 is None
    state_registry.cancel_hold(h1)
    assert state_registry.get_spots_remaining("west_coast_beach", "2026-04-06", "09:00", 25) == 25
    h3 = state_registry.create_soft_hold("west_coast_beach", "2026-04-06", "09:00", 10, 25)
    assert h3 is not None
    assert state_registry.get_spots_remaining("west_coast_beach", "2026-04-06", "09:00", 25) == 15


def test_mixed_statuses():
    """S26: Mix of soft_hold, confirmed, cancelled, expired — only active ones count."""
    _reset_db()
    h1 = state_registry.create_soft_hold("snorkeling_3in1", "2026-04-07", "10:00", 5, 20)
    h2 = state_registry.create_soft_hold("snorkeling_3in1", "2026-04-07", "10:00", 3, 20)
    h3 = state_registry.create_soft_hold("snorkeling_3in1", "2026-04-07", "10:00", 4, 20)
    h4 = state_registry.create_soft_hold("snorkeling_3in1", "2026-04-07", "10:00", 2, 20)
    state_registry.confirm_hold(h1)
    state_registry.cancel_hold(h2)
    conn = state_registry._get_conn()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE service_bookings SET expires_at=? WHERE id=?", (past, h3))
    conn.commit()
    conn.close()
    spots = state_registry.get_spots_remaining("snorkeling_3in1", "2026-04-07", "10:00", 20)
    assert spots == 13


def test_zero_guests_hold():
    """S27: Hold with 0 guests succeeds but doesn't reduce capacity."""
    _reset_db()
    hold_id = state_registry.create_soft_hold("klein_curacao", "2026-04-01", "08:00", 0, 30)
    assert hold_id is not None
    spots = state_registry.get_spots_remaining("klein_curacao", "2026-04-01", "08:00", 30)
    assert spots == 30


def test_many_small_holds_fill_capacity():
    """S28: Many 1-guest holds fill capacity correctly."""
    _reset_db()
    hold_ids = []
    for i in range(4):
        h = state_registry.create_soft_hold("jet_ski", "2026-04-01", "14:00", 1, 4)
        assert h is not None
        hold_ids.append(h)
    h5 = state_registry.create_soft_hold("jet_ski", "2026-04-01", "14:00", 1, 4)
    assert h5 is None
    assert state_registry.get_spots_remaining("jet_ski", "2026-04-01", "14:00", 4) == 0
    state_registry.cancel_hold(hold_ids[2])
    h6 = state_registry.create_soft_hold("jet_ski", "2026-04-01", "14:00", 1, 4)
    assert h6 is not None
