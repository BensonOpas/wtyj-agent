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
    "fields": {"service_name": "3-in-1 Snorkeling", "date": "2026-04-03", "guests": "2", "service_key": "snorkeling_3in1"},
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


def test_reschedule_triggers_summary():
    """T4: reschedule triggers summary."""
    result = {"intents": ["reschedule"], "fields": {"date": "2026-04-03"}, "flags": {}}
    override, awaiting = _post_validate(_th_resched, result, _trip_snorkel)
    assert override is not None and "Want me to go ahead and book this" in override


def test_reschedule_sets_awaiting():
    """T5: reschedule sets awaiting."""
    result = {"intents": ["reschedule"], "fields": {"date": "2026-04-03"}, "flags": {}}
    override, awaiting = _post_validate(_th_resched, result, _trip_snorkel)
    assert awaiting is True


def test_inquiry_skips_validation():
    """T6: inquiry skips validation."""
    result = {"intents": ["inquiry"], "fields": {}, "flags": {}}
    override, awaiting = _post_validate(_th_resched, result, _trip_snorkel)
    assert override is None and awaiting is False


def test_booking_still_triggers_summary():
    """T7: booking still triggers summary (regression)."""
    result = {"intents": ["booking"], "fields": {}, "flags": {}}
    override, awaiting = _post_validate(_th_resched, result, _trip_snorkel)
    assert override is not None and "Want me to go ahead and book this" in override


def test_wrong_day_reschedule():
    """T8: wrong day + reschedule returns day-of-week error."""
    th_bad = {"fields": {"service_name": "3-in-1 Snorkeling", "date": "2026-03-09", "guests": "2", "service_key": "snorkeling_3in1"}, "flags": {}}
    result = {"intents": ["reschedule"], "fields": {"date": "2026-03-09"}, "flags": {}}
    override, awaiting = _post_validate(th_bad, result, _trip_snorkel)
    assert override is not None and "Friday" in override


def test_reschedule_summary_correct_price():
    """T9: summary contains correct price for snorkeling ($110 x 2 = $220)."""
    result = {"intents": ["reschedule"], "fields": {"date": "2026-04-03"}, "flags": {}}
    override, _ = _post_validate(_th_resched, result, _trip_snorkel)
    assert "$220" in override


def test_reschedule_summary_trip_name():
    """T10: summary contains service name."""
    result = {"intents": ["reschedule"], "fields": {"date": "2026-04-03"}, "flags": {}}
    override, _ = _post_validate(_th_resched, result, _trip_snorkel)
    assert "3-in-1 Snorkeling Trip" in override
