"""Tests for Brief 050 — Manifest foundation."""
import os
import pytest

from shared import state_registry
from agents.marina import gws_calendar


# ── state_registry: manifest_events table ──

def test_manifest_events_table_exists():
    """T1: manifest_events table exists."""
    conn = state_registry._get_conn()
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    conn.close()
    assert "manifest_events" in tables


def test_manifest_events_columns():
    """T2: manifest_events has correct columns."""
    conn = state_registry._get_conn()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(manifest_events)").fetchall()]
    conn.close()
    assert cols == ["trip_key", "date", "departure_time", "calendar_id", "event_id", "html_link", "created_at"]


def test_trip_bookings_has_customer_name():
    """T3: trip_bookings has customer_name column."""
    conn = state_registry._get_conn()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(trip_bookings)").fetchall()]
    conn.close()
    assert "customer_name" in cols


def test_trip_bookings_has_customer_email():
    """T4: trip_bookings has customer_email column."""
    conn = state_registry._get_conn()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(trip_bookings)").fetchall()]
    conn.close()
    assert "customer_email" in cols


# ── state_registry: new functions exist ──

def test_set_booking_ref_callable():
    """T5: set_booking_ref callable."""
    assert callable(getattr(state_registry, 'set_booking_ref', None))


def test_get_manifest_event_callable():
    """T6: get_manifest_event callable."""
    assert callable(getattr(state_registry, 'get_manifest_event', None))


def test_save_manifest_event_callable():
    """T7: save_manifest_event callable."""
    assert callable(getattr(state_registry, 'save_manifest_event', None))


def test_delete_manifest_event_callable():
    """T8: delete_manifest_event callable."""
    assert callable(getattr(state_registry, 'delete_manifest_event', None))


def test_get_slot_passengers_callable():
    """T9: get_slot_passengers callable."""
    assert callable(getattr(state_registry, 'get_slot_passengers', None))


# ── state_registry: manifest CRUD ──

def test_save_get_manifest_event():
    """T10: save + get manifest event."""
    state_registry.save_manifest_event("test_trip", "2099-01-01", "09:00",
                                       "cal@group.calendar.google.com", "evt_123", "https://cal/evt_123")
    me = state_registry.get_manifest_event("test_trip", "2099-01-01", "09:00")
    assert me is not None and me["event_id"] == "evt_123"
    # cleanup
    state_registry.delete_manifest_event("test_trip", "2099-01-01", "09:00")


def test_get_manifest_event_missing():
    """T11: get_manifest_event returns None for missing slot."""
    missing = state_registry.get_manifest_event("no_trip", "2099-01-01", "09:00")
    assert missing is None


def test_delete_manifest_event():
    """T12: delete_manifest_event removes row."""
    state_registry.save_manifest_event("test_trip", "2099-01-01", "09:00",
                                       "cal@group.calendar.google.com", "evt_456", "https://cal/evt_456")
    state_registry.delete_manifest_event("test_trip", "2099-01-01", "09:00")
    deleted = state_registry.get_manifest_event("test_trip", "2099-01-01", "09:00")
    assert deleted is None


# ── state_registry: create_soft_hold with customer info ──

def test_create_soft_hold_with_customer_info():
    """T13: create_soft_hold with customer info returns hold_id."""
    hold_id = state_registry.create_soft_hold(
        "test_manifest", "2099-06-01", "10:00", 4, 30,
        customer_name="Test Customer", customer_email="test@example.com",
    )
    assert hold_id is not None
    # cleanup at end of related tests
    state_registry.cancel_hold(hold_id)


def test_get_slot_passengers():
    """T14: get_slot_passengers returns the customer info."""
    hold_id = state_registry.create_soft_hold(
        "test_manifest", "2099-06-01", "10:00", 4, 30,
        customer_name="Test Customer", customer_email="test@example.com",
    )
    passengers = state_registry.get_slot_passengers("test_manifest", "2099-06-01", "10:00")
    assert len(passengers) == 1
    assert passengers[0]["customer_name"] == "Test Customer"
    assert passengers[0]["customer_email"] == "test@example.com"
    assert passengers[0]["guests"] == 4
    state_registry.cancel_hold(hold_id)


def test_set_booking_ref():
    """T15: set_booking_ref updates the row."""
    hold_id = state_registry.create_soft_hold(
        "test_manifest", "2099-06-01", "10:00", 4, 30,
        customer_name="Test Customer", customer_email="test@example.com",
    )
    state_registry.set_booking_ref(hold_id, "BF-2099-00001")
    passengers = state_registry.get_slot_passengers("test_manifest", "2099-06-01", "10:00")
    assert passengers[0]["booking_ref"] == "BF-2099-00001"
    state_registry.cancel_hold(hold_id)


def test_cancelled_hold_excluded():
    """T16: cancelled hold excluded from passengers."""
    hold_id = state_registry.create_soft_hold(
        "test_manifest", "2099-06-01", "10:00", 4, 30,
        customer_name="Test Customer", customer_email="test@example.com",
    )
    state_registry.cancel_hold(hold_id)
    passengers = state_registry.get_slot_passengers("test_manifest", "2099-06-01", "10:00")
    assert len(passengers) == 0


# ── gws_calendar: new functions exist ──

def test_build_manifest_body_callable():
    """T17: _build_manifest_body callable."""
    assert callable(getattr(gws_calendar, '_build_manifest_body', None))


def test_create_or_update_manifest_callable():
    """T18: create_or_update_manifest callable."""
    assert callable(getattr(gws_calendar, 'create_or_update_manifest', None))


def test_update_manifest_callable():
    """T19: update_manifest callable."""
    assert callable(getattr(gws_calendar, 'update_manifest', None))


def test_remove_from_manifest_callable():
    """T20: remove_from_manifest callable."""
    assert callable(getattr(gws_calendar, 'remove_from_manifest', None))


# ── gws_calendar: _build_manifest_body output ──

@pytest.fixture()
def manifest_body_passengers():
    """Insert two test passengers for manifest body test, clean up after."""
    h1 = state_registry.create_soft_hold("klein_curacao", "2099-07-01", "08:00", 4, 30,
                                         customer_name="Alice", customer_email="alice@test.com")
    state_registry.set_booking_ref(h1, "BF-2099-10001")
    h2 = state_registry.create_soft_hold("klein_curacao", "2099-07-01", "08:00", 6, 30,
                                         customer_name="Bob", customer_email="bob@test.com")
    state_registry.set_booking_ref(h2, "BF-2099-10002")
    yield
    state_registry.cancel_hold(h1)
    state_registry.cancel_hold(h2)


def _get_body(manifest_body_passengers):
    return gws_calendar._build_manifest_body(
        "klein_curacao", "2099-07-01", "08:00",
        "cal@group.calendar.google.com", 120, 30, 8,
    )


def test_manifest_summary_guest_count(manifest_body_passengers):
    """T21: manifest summary contains guest count and capacity."""
    body = _get_body(manifest_body_passengers)
    assert "10/30 pax" in body["summary"]


def test_manifest_summary_trip_name(manifest_body_passengers):
    """T22: manifest summary contains trip name."""
    body = _get_body(manifest_body_passengers)
    assert "KLEIN CURACAO" in body["summary"]


def test_manifest_revenue(manifest_body_passengers):
    """T23: manifest description has $1,200 revenue (10 * $120)."""
    body = _get_body(manifest_body_passengers)
    assert "$1,200" in body["description"]


def test_manifest_alice(manifest_body_passengers):
    """T24: manifest description lists Alice."""
    body = _get_body(manifest_body_passengers)
    assert "Alice" in body["description"]


def test_manifest_bob(manifest_body_passengers):
    """T25: manifest description lists Bob."""
    body = _get_body(manifest_body_passengers)
    assert "Bob" in body["description"]


def test_manifest_booking_ref(manifest_body_passengers):
    """T26: manifest description has booking refs."""
    body = _get_body(manifest_body_passengers)
    assert "BF-2099-10001" in body["description"]


def test_manifest_start_time(manifest_body_passengers):
    """T27: manifest body has start dateTime."""
    body = _get_body(manifest_body_passengers)
    assert body["start"]["dateTime"] != ""


def test_manifest_total_guests(manifest_body_passengers):
    """T28: _total_guests == 10."""
    body = _get_body(manifest_body_passengers)
    assert body.get("_total_guests") == 10


# ── gws_calendar: create_hold backward compat ──

def test_create_hold_still_callable():
    """T29: create_hold still callable."""
    assert callable(getattr(gws_calendar, 'create_hold', None))


# ── file headers ──

def test_state_registry_header():
    """T30: state_registry header says Brief."""
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "shared", "state_registry.py")) as f:
        sr_src = f.read()
    assert "Last modified: Brief" in sr_src


def test_gws_calendar_header():
    """T31: gws_calendar header says Brief."""
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "gws_calendar.py")) as f:
        gc_src = f.read()
    assert "Last modified: Brief" in gc_src
