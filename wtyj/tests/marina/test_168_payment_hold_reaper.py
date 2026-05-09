"""Tests for Brief 168 — payment hold state machine + reaper.

Covers:
- Schema ALTER TABLE added the new columns
- set_payment_window updates a confirmed hold
- get_holds_needing_reminder returns rows in the window
- get_expired_payment_holds returns rows past the deadline
- mark_payment_reminder_sent / expire_payment_hold flip the flags
- hold_reaper._feature_enabled reads config correctly
- hold_reaper exists as a module and has main()
"""
import os
from datetime import datetime, timezone, timedelta

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from shared import state_registry
from agents.marina import hold_reaper


def _cleanup(hold_ids):
    conn = state_registry._get_conn()
    for hid in hold_ids:
        conn.execute("DELETE FROM service_bookings WHERE id = ?", (hid,))
    conn.commit()
    conn.close()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _past_iso(minutes: int):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _future_iso(minutes: int):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


# --- Schema ---

def test_schema_service_bookings_has_payment_expires_at():
    conn = state_registry._get_conn()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(service_bookings)").fetchall()]
    conn.close()
    assert "payment_expires_at" in cols
    assert "payment_reminder_sent_at" in cols
    assert "customer_phone" in cols


# --- State machine helpers ---

def test_set_payment_window_updates_confirmed_hold():
    hid = state_registry.create_soft_hold(
        "sunset_cruise", "2027-12-17", "17:30", 2, 25,
        customer_name="Alice", customer_email="alice@test168.test"
    )
    assert hid is not None
    state_registry.confirm_hold(hid)
    expires = _future_iso(360)  # 6 hours out
    ok = state_registry.set_payment_window(hid, expires, customer_phone="+15551234")
    assert ok is True
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT payment_expires_at, customer_phone FROM service_bookings WHERE id = ?",
        (hid,)
    ).fetchone()
    conn.close()
    assert row[0] == expires
    assert row[1] == "+15551234"
    _cleanup([hid])


def test_get_holds_needing_reminder_in_window():
    hid = state_registry.create_soft_hold(
        "sunset_cruise", "2027-12-18", "17:30", 2, 25,
        customer_name="Bob", customer_email="bob@test168.test"
    )
    state_registry.confirm_hold(hid)
    # Expires in 30 minutes, reminder window is 60 minutes → we're inside the window
    state_registry.set_payment_window(hid, _future_iso(30), customer_phone="+15552")
    due = state_registry.get_holds_needing_reminder(_now_iso(), 60)
    due_ids = [h["id"] for h in due]
    assert hid in due_ids
    _cleanup([hid])


def test_get_holds_needing_reminder_excludes_if_reminder_sent():
    hid = state_registry.create_soft_hold(
        "sunset_cruise", "2027-12-19", "17:30", 2, 25,
        customer_name="Carol", customer_email="carol@test168.test"
    )
    state_registry.confirm_hold(hid)
    state_registry.set_payment_window(hid, _future_iso(30), customer_phone="+15553")
    state_registry.mark_payment_reminder_sent(hid)
    due = state_registry.get_holds_needing_reminder(_now_iso(), 60)
    assert hid not in [h["id"] for h in due]
    _cleanup([hid])


def test_get_holds_needing_reminder_excludes_outside_window():
    hid = state_registry.create_soft_hold(
        "sunset_cruise", "2027-12-20", "17:30", 2, 25,
        customer_name="Dave", customer_email="dave@test168.test"
    )
    state_registry.confirm_hold(hid)
    # Expires in 120 minutes, reminder window is 60 — still too early
    state_registry.set_payment_window(hid, _future_iso(120), customer_phone="+15554")
    due = state_registry.get_holds_needing_reminder(_now_iso(), 60)
    assert hid not in [h["id"] for h in due]
    _cleanup([hid])


def test_get_expired_payment_holds_returns_past_deadline():
    hid = state_registry.create_soft_hold(
        "sunset_cruise", "2027-12-21", "17:30", 2, 25,
        customer_name="Eve", customer_email="eve@test168.test"
    )
    state_registry.confirm_hold(hid)
    # Expired 10 minutes ago
    state_registry.set_payment_window(hid, _past_iso(10), customer_phone="+15555")
    expired = state_registry.get_expired_payment_holds(_now_iso())
    assert hid in [h["id"] for h in expired]
    _cleanup([hid])


def test_expire_payment_hold_flips_status():
    hid = state_registry.create_soft_hold(
        "sunset_cruise", "2027-12-22", "17:30", 2, 25,
        customer_name="Frank", customer_email="frank@test168.test"
    )
    state_registry.confirm_hold(hid)
    state_registry.set_payment_window(hid, _past_iso(1), customer_phone="+15556")
    ok = state_registry.expire_payment_hold(hid)
    assert ok is True
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT status, payment_expires_at FROM service_bookings WHERE id = ?", (hid,)
    ).fetchone()
    conn.close()
    assert row[0] == "payment_expired"
    assert row[1] is None
    _cleanup([hid])


# --- Reaper module smoke tests ---

def test_reaper_module_has_main():
    assert callable(hold_reaper.main)


def test_reaper_tick_runs_without_error_on_empty_db():
    """Brief 168: calling _tick() with no pending holds should be a no-op."""
    hold_reaper._tick()


def test_reaper_feature_enabled_reads_config():
    """_feature_enabled returns True for a client with payment.timing=upfront
    and hold_duration_hours set. Reads from the live config_loader which is
    currently pointed at BlueMarlin (payment.timing=upfront, hold_duration_hours=6)."""
    assert hold_reaper._feature_enabled() is True



