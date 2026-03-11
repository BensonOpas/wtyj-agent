# tests/test_marina_tone.py
# Brief 060 — Marina Tone v2: system/user split + template rewrites

import sys
import os
from agents.marina import marina_agent
from shared import config_loader
from agents.marina.email_poller import _build_booking_summary


def test_system_prompt_contains_writing_style():
    """T1: _build_system_prompt contains WRITING STYLE section."""
    sp = marina_agent._build_system_prompt({})
    assert "WRITING STYLE:" in sp


def test_system_prompt_contains_example_replies():
    """T2: _build_system_prompt contains tone reference examples."""
    sp = marina_agent._build_system_prompt({})
    assert "tone reference" in sp


def test_system_prompt_contains_json_format():
    """T3: _build_system_prompt contains JSON format spec."""
    sp = marina_agent._build_system_prompt({})
    assert '"intents"' in sp
    assert '"reply"' in sp


def test_user_prompt_contains_inbound_message():
    """T4: _build_user_prompt contains INBOUND MESSAGE and body."""
    up = marina_agent._build_user_prompt("a@b.com", "test", "hello world", {}, {})
    assert "INBOUND MESSAGE:" in up
    assert "hello world" in up


def test_user_prompt_contains_trips_and_faq():
    """T5: _build_user_prompt contains TRIPS and FAQ sections."""
    up = marina_agent._build_user_prompt("a@b.com", "test", "hi", {}, {})
    assert "TRIPS" in up
    assert "FAQ" in up


def test_build_prompt_wrapper_combines_both():
    """T6: _build_prompt wrapper contains content from both system and user prompts."""
    full = marina_agent._build_prompt("a@b.com", "test", "hi", {}, {})
    assert "WRITING STYLE:" in full
    assert "INBOUND MESSAGE:" in full


def test_booking_summary_no_old_header():
    """T7: Booking summary does NOT contain old bullet-point header."""
    trip = {
        "display_name": "Sunset Cruise",
        "departures": [{"time": "17:30", "vessel": "Kailani", "departure_point": "Village Marina"}],
        "price_adult_usd": 79,
        "included": ["open bar", "snacks"],
    }
    summary = _build_booking_summary(
        {"trip_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "departure_time": "17:30"},
        trip,
    )
    assert "Here's a quick summary" not in summary


def test_booking_summary_no_old_lock_phrase():
    """T8: Booking summary does NOT contain old lock-in phrase."""
    trip = {
        "display_name": "Sunset Cruise",
        "departures": [{"time": "17:30", "vessel": "Kailani", "departure_point": "Village Marina"}],
        "price_adult_usd": 79,
        "included": ["open bar", "snacks"],
    }
    summary = _build_booking_summary(
        {"trip_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "departure_time": "17:30"},
        trip,
    )
    assert "Shall I lock this in" not in summary


def test_booking_summary_has_price():
    """T9: Booking summary contains exact prices."""
    trip = {
        "display_name": "Sunset Cruise",
        "departures": [{"time": "17:30", "vessel": "Kailani", "departure_point": "Village Marina"}],
        "price_adult_usd": 79,
        "included": ["open bar", "snacks"],
    }
    summary = _build_booking_summary(
        {"trip_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "departure_time": "17:30"},
        trip,
    )
    assert "$158" in summary
    assert "$79" in summary


def test_booking_summary_new_closer():
    """T10: Booking summary contains the new closer phrase."""
    trip = {
        "display_name": "Sunset Cruise",
        "departures": [{"time": "17:30", "vessel": "Kailani", "departure_point": "Village Marina"}],
        "price_adult_usd": 79,
        "included": ["open bar", "snacks"],
    }
    summary = _build_booking_summary(
        {"trip_key": "sunset_cruise", "date": "2026-03-26", "guests": "2", "departure_time": "17:30"},
        trip,
    )
    assert "Want me to go ahead and book this?" in summary


def test_post_validate_day_of_week_no_em_dashes():
    """T11: Day-of-week override has no em dashes or old phrasing."""
    from agents.marina.email_poller import _post_validate
    th = {"fields": {"experience": "Snorkeling", "date": "2026-03-09", "guests": "2", "trip_key": "snorkeling_3in1"}, "flags": {}}
    trip = {"display_name": "3-in-1 Snorkeling Trip", "departures": [{"time": "10:00"}], "days_available": "Fridays only"}
    result = {"intents": ["booking"], "fields": {}, "flags": {}}
    override, _ = _post_validate(th, result, trip)
    assert override is not None
    assert "—" not in override
    assert "Great choice" not in override


def test_persona_in_client_json():
    """T12: marina_persona in client.json has hospitality reference."""
    persona = config_loader.get_common_sense_knowledge().get("marina_persona", "")
    assert "hospitality" in persona
    assert "mirrors the tone" in persona


if __name__ == "__main__":
    tests = [
        test_system_prompt_contains_writing_style,
        test_system_prompt_contains_example_replies,
        test_system_prompt_contains_json_format,
        test_user_prompt_contains_inbound_message,
        test_user_prompt_contains_trips_and_faq,
        test_build_prompt_wrapper_combines_both,
        test_booking_summary_no_old_header,
        test_booking_summary_no_old_lock_phrase,
        test_booking_summary_has_price,
        test_booking_summary_new_closer,
        test_post_validate_day_of_week_no_em_dashes,
        test_persona_in_client_json,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__} — {e}")
    print(f"\n{passed}/{len(tests)} tests passed.")
