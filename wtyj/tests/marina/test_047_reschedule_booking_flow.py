"""Tests for Brief 047 — Treat reschedule intent as booking-active."""
from agents.marina.email_poller import _BOOKING_INTENTS, _post_validate


_trip_snorkel = {
    "display_name": "3-in-1 Snorkeling Trip",
    "slots": [{"time": "10:00", "resource": "TopCat", "location": "Mood Beach pier"}],
    "days_available": "Fridays only",
    "price": 110,
    "included": ["lunch", "3 snorkel sites"],
}
_th_resched = {
    "fields": {"service_name": "3-in-1 Snorkeling", "date": "2027-12-17", "guests": "2", "service_key": "snorkeling_3in1"},
    "flags": {},
}


def test_booking_in_booking_intents():
    """T1: booking in _BOOKING_INTENTS."""
    assert "booking" in _BOOKING_INTENTS


def test_reschedule_in_booking_intents():
    """T2: reschedule in _BOOKING_INTENTS."""
    assert "reschedule" in _BOOKING_INTENTS


def test_inquiry_not_in_booking_intents():
    """T3: inquiry NOT in _BOOKING_INTENTS."""
    assert "inquiry" not in _BOOKING_INTENTS


def test_reschedule_advances_state():
    """Brief 161: reschedule with valid fields advances state, override is None."""
    result = {"intents": ["reschedule"], "fields": {"date": "2027-12-17"}, "flags": {}}
    override, awaiting = _post_validate(_th_resched, result, _trip_snorkel)
    assert override is None
    assert awaiting is True


def test_reschedule_sets_awaiting():
    """T5: reschedule sets awaiting."""
    result = {"intents": ["reschedule"], "fields": {"date": "2027-12-17"}, "flags": {}}
    override, awaiting = _post_validate(_th_resched, result, _trip_snorkel)
    assert awaiting is True


def test_inquiry_skips_validation():
    """T6: inquiry skips validation."""
    result = {"intents": ["inquiry"], "fields": {}, "flags": {}}
    override, awaiting = _post_validate(_th_resched, result, _trip_snorkel)
    assert override is None and awaiting is False


def test_booking_still_advances_state():
    """Brief 161 (was T7): booking still advances state, override is None."""
    result = {"intents": ["booking"], "fields": {}, "flags": {}}
    override, awaiting = _post_validate(_th_resched, result, _trip_snorkel)
    assert override is None
    assert awaiting is True


def test_wrong_day_reschedule_does_not_advance():
    """Brief 161 (was T8): wrong day + reschedule returns (None, False)."""
    th_bad = {"fields": {"service_name": "3-in-1 Snorkeling", "date": "2026-03-09", "guests": "2", "service_key": "snorkeling_3in1"}, "flags": {}}
    result = {"intents": ["reschedule"], "fields": {"date": "2026-03-09"}, "flags": {}}
    override, awaiting = _post_validate(th_bad, result, _trip_snorkel)
    assert override is None
    assert awaiting is False
