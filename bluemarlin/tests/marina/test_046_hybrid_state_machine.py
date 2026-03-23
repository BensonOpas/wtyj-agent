"""Tests for Brief 046 — Hybrid refactor: Python state machine + simplified prompt."""
import inspect

from agents.marina.email_poller import (
    _day_matches, _suggest_dates, _build_booking_summary,
    _build_action_context, _post_validate,
)
from agents.marina import marina_agent


# ── _day_matches ──

def test_daily_matches_any_day():
    """T1: daily matches any day."""
    assert _day_matches("Monday", "daily")


def test_monday_not_friday():
    """T2: Monday doesn't match Fridays only."""
    assert not _day_matches("Monday", "Fridays only")


def test_friday_matches_fridays():
    """T3: Friday matches Fridays only."""
    assert _day_matches("Friday", "Fridays only")


def test_wednesday_matches_wed_and_sun():
    """T4: Wednesday matches Wednesdays and Sundays."""
    assert _day_matches("Wednesday", "Wednesdays and Sundays")


# ── _suggest_dates ──

def test_suggest_dates_returns_friday():
    """T5: _suggest_dates returns Friday suggestions for Fridays-only trip."""
    suggestions = _suggest_dates("2026-03-09", "Fridays only")  # Monday
    assert "Friday" in suggestions


# ── _build_action_context ──

def test_action_context_awaiting_booking():
    """T6: action_context contains ACTION for awaiting_booking_confirmation."""
    ctx = _build_action_context({"flags": {"awaiting_booking_confirmation": True}})
    assert "ACTION:" in ctx and "booking_confirmed" in ctx


def test_action_context_empty_flags():
    """T7: action_context empty for no flags."""
    ctx_empty = _build_action_context({"flags": {}})
    assert ctx_empty == ""


def test_action_context_reply_hold_failed():
    """T8: action_context includes reply_hold_failed instruction."""
    ctx2 = _build_action_context({"flags": {"awaiting_booking_confirmation": True}})
    assert "reply_hold_failed" in ctx2


# ── _post_validate ──

_trip_multi = {
    "display_name": "Klein Curacao Trip",
    "departures": [
        {"time": "08:00", "vessel": "BlueFinn2", "departure_point": "Jan Thiel Beach"},
        {"time": "08:30", "vessel": "BlueFinn1", "departure_point": "Jan Thiel Beach"},
    ],
    "days_available": "daily",
}
_trip_single = {
    "display_name": "Sunset Cruise",
    "departures": [{"time": "17:30", "vessel": "Kailani", "departure_point": "Village Marina"}],
    "days_available": "Tuesday, Thursday, Friday, Saturday",
    "price_adult_usd": 79,
    "included": ["open bar", "snacks"],
}
_result_booking = {"intents": ["booking"], "fields": {}, "flags": {}}


def test_multi_departure_asks_for_time():
    """T9: multi-departure asks for departure time."""
    th = {"fields": {"experience": "Klein Curacao", "date": "2026-03-25", "guests": "2", "trip_key": "klein_curacao"}, "flags": {}}
    override, awaiting = _post_validate(th, _result_booking, _trip_multi)
    assert override is not None and "departure" in override.lower()


def test_multi_departure_no_awaiting():
    """T10: multi-departure does not set awaiting."""
    th = {"fields": {"experience": "Klein Curacao", "date": "2026-03-25", "guests": "2", "trip_key": "klein_curacao"}, "flags": {}}
    override, awaiting = _post_validate(th, _result_booking, _trip_multi)
    assert awaiting is False


def test_single_departure_builds_summary():
    """T11: single-departure builds summary."""
    th = {"fields": {"experience": "Sunset Cruise", "date": "2026-03-26", "guests": "2", "trip_key": "sunset_cruise"}, "flags": {}}
    override, awaiting = _post_validate(th, _result_booking, _trip_single)
    assert override is not None and "Want me to go ahead and book this" in override


def test_single_departure_sets_awaiting():
    """T12: single-departure sets awaiting."""
    th = {"fields": {"experience": "Sunset Cruise", "date": "2026-03-26", "guests": "2", "trip_key": "sunset_cruise"}, "flags": {}}
    override, awaiting = _post_validate(th, _result_booking, _trip_single)
    assert awaiting is True


def test_invalid_day_returns_error():
    """T13: wrong day returns day-of-week error."""
    th = {"fields": {"experience": "Snorkeling", "date": "2026-03-09", "guests": "2", "trip_key": "snorkeling_3in1"}, "flags": {}}
    trip_fri = {"display_name": "3-in-1 Snorkeling Trip", "departures": [{"time": "10:00"}], "days_available": "Fridays only"}
    override, awaiting = _post_validate(th, _result_booking, trip_fri)
    assert override is not None and "Friday" in override


def test_invalid_day_no_awaiting():
    """T14: wrong day does not set awaiting."""
    th = {"fields": {"experience": "Snorkeling", "date": "2026-03-09", "guests": "2", "trip_key": "snorkeling_3in1"}, "flags": {}}
    trip_fri = {"display_name": "3-in-1 Snorkeling Trip", "departures": [{"time": "10:00"}], "days_available": "Fridays only"}
    override, awaiting = _post_validate(th, _result_booking, trip_fri)
    assert awaiting is False


def test_skips_when_already_awaiting():
    """T15: skips validation when already awaiting."""
    th = {"fields": {"experience": "X", "date": "2026-03-25", "guests": "2", "trip_key": "klein_curacao"}, "flags": {"awaiting_booking_confirmation": True}}
    override, awaiting = _post_validate(th, _result_booking, _trip_multi)
    assert override is None and awaiting is False


def test_skips_when_missing_fields():
    """T16: skips when missing required fields."""
    th = {"fields": {"experience": "X", "date": "2026-03-25"}, "flags": {}}
    override, awaiting = _post_validate(th, _result_booking, _trip_multi)
    assert override is None and awaiting is False


# ── _build_booking_summary ──

def test_summary_contains_trip_name():
    """T17: summary contains trip name."""
    summary = _build_booking_summary(
        {"trip_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "departure_time": "17:30"},
        _trip_single,
    )
    assert "Sunset Cruise" in summary


def test_summary_contains_price():
    """T18: summary contains price."""
    summary = _build_booking_summary(
        {"trip_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "departure_time": "17:30"},
        _trip_single,
    )
    assert "$158" in summary


def test_summary_contains_departure():
    """T19: summary contains departure."""
    summary = _build_booking_summary(
        {"trip_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "departure_time": "17:30"},
        _trip_single,
    )
    assert "17:30" in summary


def test_summary_ends_with_lock_in():
    """T20: summary ends with lock-in question."""
    summary = _build_booking_summary(
        {"trip_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "departure_time": "17:30"},
        _trip_single,
    )
    assert "Want me to go ahead and book this" in summary


# ── Prompt checks ──

def test_prompt_no_first_check():
    """T21: prompt has no FIRST check."""
    prompt = marina_agent._build_prompt("test@test.com", "Test", "Test", {}, {})
    assert "FIRST:" not in prompt and "- FIRST" not in prompt


def test_prompt_no_second_check():
    """T22: prompt has no SECOND check."""
    prompt = marina_agent._build_prompt("test@test.com", "Test", "Test", {}, {})
    assert "SECOND:" not in prompt and "- SECOND" not in prompt


def test_prompt_no_third_check():
    """T23: prompt has no THIRD check."""
    prompt = marina_agent._build_prompt("test@test.com", "Test", "Test", {}, {})
    assert "THIRD:" not in prompt and "- THIRD" not in prompt


def test_prompt_contains_booking_behaviour():
    """T24: prompt contains BOOKING BEHAVIOUR."""
    prompt = marina_agent._build_prompt("test@test.com", "Test", "Test", {}, {})
    assert "BOOKING BEHAVIOUR:" in prompt


def test_action_context_injected():
    """T25: action_context injected into prompt."""
    prompt = marina_agent._build_prompt("t@t.com", "T", "T", {}, {}, "ACTION: test instruction")
    assert "ACTION: test instruction" in prompt


def test_process_message_has_action_context_param():
    """T26: process_message has action_context param."""
    sig = inspect.signature(marina_agent.process_message)
    assert "action_context" in sig.parameters


def test_no_availability_context():
    """T27: no AVAILABILITY CONTEXT in prompt."""
    prompt = marina_agent._build_prompt("test@test.com", "Test", "Test", {}, {})
    assert "AVAILABILITY CONTEXT:" not in prompt


def test_needs_child_ages_skips_summary():
    """T28: needs_child_ages skips summary."""
    result_kids = {"intents": ["booking"], "fields": {}, "flags": {"needs_child_ages": True}}
    th = {"fields": {"experience": "Klein", "date": "2026-03-25", "guests": "4", "trip_key": "klein_curacao", "departure_time": "08:00"}, "flags": {}}
    override, awaiting = _post_validate(th, result_kids, _trip_multi)
    assert override is None and awaiting is False
