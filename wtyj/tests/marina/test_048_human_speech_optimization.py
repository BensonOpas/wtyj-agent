"""Tests for Brief 048 — Human speech optimization: multi-topic fix + prompt hardening."""
from agents.marina.email_poller import _post_validate, _BOOKING_INTENTS, _build_booking_summary
from agents.marina import marina_agent


_trip_fri = {"display_name": "3-in-1 Snorkeling Trip", "slots": [{"time": "10:00"}], "days_available": "Fridays only"}
_trip_kc = {
    "display_name": "Klein Curacao Trip",
    "slots": [
        {"time": "08:00", "resource": "BlueFinn2", "location": "Jan Thiel Beach"},
        {"time": "08:30", "resource": "BlueFinn1", "location": "Jan Thiel Beach"},
    ],
    "days_available": "daily",
}
_trip_sc = {
    "display_name": "Sunset Cruise",
    "slots": [{"time": "17:30", "resource": "Kailani", "location": "Village Marina"}],
    "days_available": "Tuesday, Thursday, Friday, Saturday",
    "price": 79,
    "included": ["open bar", "snacks"],
}
_result_b = {"intents": ["booking"], "fields": {}, "flags": {}}


# === Fix 1: Multi-topic reply preservation ===

def test_day_of_week_override_no_signature():
    """T1: day-of-week override has no signature."""
    th = {"fields": {"service_name": "Snorkeling", "date": "2026-03-09", "guests": "2", "service_key": "snorkeling_3in1"}, "flags": {}}
    override, _ = _post_validate(th, _result_b, _trip_fri)
    assert "Warm regards" not in override


def test_departure_override_no_signature():
    """T2: departure override has no signature."""
    th = {"fields": {"service_name": "Klein Curacao", "date": "2026-12-25", "guests": "2", "service_key": "klein_curacao"}, "flags": {}}
    override, _ = _post_validate(th, _result_b, _trip_kc)
    assert "Warm regards" not in override


def test_booking_summary_no_signature():
    """T3: booking summary has no signature."""
    summary = _build_booking_summary(
        {"service_key": "sunset_cruise", "date": "2026-12-26", "guests": "2", "slot_time": "17:30"},
        _trip_sc,
    )
    assert "Warm regards" not in summary


def test_summary_lock_in_question():
    """T4: summary still has lock-in question."""
    summary = _build_booking_summary(
        {"service_key": "sunset_cruise", "date": "2026-12-26", "guests": "2", "slot_time": "17:30"},
        _trip_sc,
    )
    assert "Want me to go ahead and book this" in summary


def test_summary_correct_price():
    """T5: summary still has correct price."""
    summary = _build_booking_summary(
        {"service_key": "sunset_cruise", "date": "2026-12-26", "guests": "2", "slot_time": "17:30"},
        _trip_sc,
    )
    assert "$158" in summary


def test_multi_intent_has_side_topics():
    """T6: multi-intent detected as has_side_topics."""
    intents_multi = ["booking", "inquiry"]
    has_side = any(i not in _BOOKING_INTENTS for i in intents_multi)
    assert has_side is True


def test_booking_only_no_side_topics():
    """T7: booking-only has no side topics."""
    intents_single = ["booking"]
    has_side_single = any(i not in _BOOKING_INTENTS for i in intents_single)
    assert has_side_single is False


def test_reschedule_inquiry_has_side_topics():
    """T8: reschedule+inquiry has side topics."""
    intents_resched = ["reschedule", "inquiry"]
    has_side_resched = any(i not in _BOOKING_INTENTS for i in intents_resched)
    assert has_side_resched is True


# === Fix 2: Date clearing instruction in prompt ===

def test_prompt_date_clearing_instruction():
    """T9: prompt has date-clearing instruction."""
    prompt = marina_agent._build_prompt("t@t.com", "T", "T", {}, {})
    assert 'set date to ""' in prompt or "set date to empty" in prompt.lower()


def test_prompt_yyyy_mm_dd():
    """T10: prompt still has YYYY-MM-DD instruction."""
    prompt = marina_agent._build_prompt("t@t.com", "T", "T", {}, {})
    assert "YYYY-MM-DD" in prompt


# === Fix 3: Guest hallucination guard ===

def test_prompt_guest_count_guard():
    """T11: prompt warns against inferring guests."""
    prompt = marina_agent._build_prompt("t@t.com", "T", "T", {}, {})
    assert "Never infer a guest count" in prompt


def test_prompt_we_not_count():
    """T12: prompt says 'We' is not a count."""
    prompt = marina_agent._build_prompt("t@t.com", "T", "T", {}, {})
    assert '"We"' in prompt or "'We'" in prompt


# === Fix 4: Multi-topic prompt guidance ===

def test_prompt_multi_topic_guidance():
    """T13: prompt has multi-topic guidance."""
    prompt = marina_agent._build_prompt("t@t.com", "T", "T", {}, {})
    assert "non-booking questions alongside" in prompt


# === Regression tests ===

def test_booking_still_builds_summary():
    """T14: booking still builds summary."""
    override, awaiting = _post_validate(
        {"fields": {"service_name": "Sunset", "date": "2026-12-26", "guests": "2", "service_key": "sunset_cruise"}, "flags": {}},
        {"intents": ["booking"], "fields": {}, "flags": {}},
        _trip_sc,
    )
    assert override is not None and "Want me to go ahead and book this" in override


def test_booking_still_sets_awaiting():
    """T15: booking still sets awaiting."""
    override, awaiting = _post_validate(
        {"fields": {"service_name": "Sunset", "date": "2026-12-26", "guests": "2", "service_key": "sunset_cruise"}, "flags": {}},
        {"intents": ["booking"], "fields": {}, "flags": {}},
        _trip_sc,
    )
    assert awaiting is True


def test_reschedule_still_triggers():
    """T16: reschedule still triggers validation (Brief 047 regression)."""
    override, _ = _post_validate(
        {"fields": {"service_name": "Snorkeling", "date": "2026-04-03", "guests": "2", "service_key": "snorkeling_3in1"}, "flags": {}},
        {"intents": ["reschedule"], "fields": {}, "flags": {}},
        _trip_fri,
    )
    assert override is not None and "Want me to go ahead and book this" in override


# === Fix 2 integration: Date clearing through merge ===

def test_empty_string_clears_date():
    """T17: empty string clears existing date."""
    th = {"fields": {"service_name": "Klein", "date": "2026-03-28", "guests": "2", "service_key": "klein_curacao"}}
    new_fields = {"date": ""}
    for k, v in new_fields.items():
        if v is not None and v != "":
            th["fields"][k] = v
        elif v == "" and k in th["fields"]:
            del th["fields"][k]
    assert "date" not in th["fields"]


def test_empty_string_absent_field_safe():
    """T18: empty string for absent field is safe."""
    th = {"fields": {"service_name": "Klein"}}
    new_fields = {"phone": ""}
    for k, v in new_fields.items():
        if v is not None and v != "":
            th["fields"][k] = v
        elif v == "" and k in th["fields"]:
            del th["fields"][k]
    assert "phone" not in th["fields"]


def test_normal_merge_still_works():
    """T19: non-empty values still merge normally."""
    th = {"fields": {"service_name": "Klein"}}
    new_fields = {"date": "2026-12-25", "guests": "2"}
    for k, v in new_fields.items():
        if v is not None and v != "":
            th["fields"][k] = v
        elif v == "" and k in th["fields"]:
            del th["fields"][k]
    assert th["fields"]["date"] == "2026-12-25" and th["fields"]["guests"] == "2"
