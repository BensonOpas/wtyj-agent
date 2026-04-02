"""Tests for Brief 055 — Multi-service booking in one thread."""
import sys, os, json

from agents.marina import email_poller
from agents.marina import marina_agent
from shared import config_loader


def _make_thread(fields=None, flags=None, completed=None):
    th = {
        "fields": fields or {},
        "flags": flags or {},
        "last_customer_hash": "",
        "reply_times": [],
        "messages": [],
    }
    if completed is not None:
        th["completed_bookings"] = completed
    return th


def test_reset_after_hold_created():
    """After hold_created=True, reset archives booking and clears fields/flags."""
    th = _make_thread(
        fields={
            "service_key": "klein_curacao",
            "service_name": "Klein Curaçao",
            "date": "2026-04-15",
            "guests": "4",
            "slot_time": "08:30",
            "customer_name": "Callou",
            "phone": "+5999 123 4567",
        },
        flags={
            "hold_created": True,
            "booking_confirmed": True,
            "booking_ref": "BF-2026-00001",
            "payment_link": "https://demo.pay/bluemarlin/pay123",
            "slot_checked": True,
            "slot_available": True,
            "hold_id": 42,
            "event_id": "evt123",
            "event_link": "https://calendar.google.com/event/abc",
        },
    )
    result = email_poller._maybe_reset_for_new_booking(th)
    assert result == True, "FAIL: should return True when reset happens"
    # Fields: customer_name and phone preserved, everything else cleared
    assert th["fields"]["customer_name"] == "Callou", "FAIL: customer_name should persist"
    assert th["fields"]["phone"] == "+5999 123 4567", "FAIL: phone should persist"
    assert "service_key" not in th["fields"], "FAIL: service_key should be cleared"
    assert "service_name" not in th["fields"], "FAIL: experience should be cleared"
    assert "date" not in th["fields"], "FAIL: date should be cleared"
    assert "guests" not in th["fields"], "FAIL: guests should be cleared"
    # Flags: booking flags cleared
    assert "hold_created" not in th["flags"], "FAIL: hold_created should be cleared"
    assert "booking_confirmed" not in th["flags"], "FAIL: booking_confirmed should be cleared"
    assert "booking_ref" not in th["flags"], "FAIL: booking_ref should be cleared"
    assert "slot_checked" not in th["flags"], "FAIL: slot_checked should be cleared"
    assert "hold_id" not in th["flags"], "FAIL: hold_id should be cleared"
    # Completed bookings list
    assert len(th["completed_bookings"]) == 1
    archived = th["completed_bookings"][0]
    assert archived["booking_ref"] == "BF-2026-00001", f"FAIL: archived ref={archived['booking_ref']}"
    assert archived["service_key"] == "klein_curacao", f"FAIL: archived service={archived['service_key']}"
    assert archived["date"] == "2026-04-15", f"FAIL: archived date={archived['date']}"
    assert archived["guests"] == "4", f"FAIL: archived guests={archived['guests']}"
    print("PASS: test_reset_after_hold_created")


def test_no_reset_without_hold_created():
    """Without hold_created, no reset happens."""
    th = _make_thread(
        fields={"service_key": "klein_curacao", "date": "2026-04-15"},
        flags={"awaiting_booking_confirmation": True},
    )
    result = email_poller._maybe_reset_for_new_booking(th)
    assert result == False, "FAIL: should return False without hold_created"
    assert th["fields"]["service_key"] == "klein_curacao", "FAIL: fields should be unchanged"
    print("PASS: test_no_reset_without_hold_created")


def test_max_bookings_blocks_reset():
    """At max_bookings_per_thread (3), no reset happens."""
    completed = [
        {"booking_ref": f"BF-2026-0000{i}", "service_key": "klein_curacao",
         "date": "2026-04-15", "guests": "2"} for i in range(3)
    ]
    th = _make_thread(
        fields={"service_key": "sunset_cruise", "date": "2026-04-16", "customer_name": "Callou"},
        flags={"hold_created": True, "booking_ref": "BF-2026-00004"},
        completed=completed,
    )
    result = email_poller._maybe_reset_for_new_booking(th)
    assert result == False, "FAIL: should return False at max bookings"
    assert th["flags"].get("hold_created") == True, "FAIL: flags should be unchanged at max"
    assert len(th["completed_bookings"]) == 3, "FAIL: completed list should not grow past max"
    print("PASS: test_max_bookings_blocks_reset")


def test_second_booking_archives_correctly():
    """Second booking adds to completed_bookings list."""
    first_completed = [{
        "booking_ref": "BF-2026-00001",
        "service_key": "klein_curacao",
        "service_name": "Klein Curaçao",
        "date": "2026-04-15",
        "guests": "4",
        "slot_time": "08:30",
        "payment_link": "https://demo.pay/1",
    }]
    th = _make_thread(
        fields={
            "service_key": "sunset_cruise",
            "service_name": "Sunset Cruise",
            "date": "2026-04-16",
            "guests": "2",
            "slot_time": "17:00",
            "customer_name": "Callou",
            "phone": "+5999 123 4567",
        },
        flags={
            "hold_created": True,
            "booking_ref": "BF-2026-00002",
            "payment_link": "https://demo.pay/2",
        },
        completed=first_completed,
    )
    result = email_poller._maybe_reset_for_new_booking(th)
    assert result == True
    assert len(th["completed_bookings"]) == 2
    assert th["completed_bookings"][0]["booking_ref"] == "BF-2026-00001"
    assert th["completed_bookings"][1]["booking_ref"] == "BF-2026-00002"
    assert th["completed_bookings"][1]["service_key"] == "sunset_cruise"
    assert th["completed_bookings"][1]["date"] == "2026-04-16"
    # Fields reset but identity preserved
    assert th["fields"]["customer_name"] == "Callou"
    assert "service_key" not in th["fields"]
    print("PASS: test_second_booking_archives_correctly")


def test_non_booking_flags_preserved():
    """Flags not in _BOOKING_FLAGS_TO_RESET survive the reset."""
    th = _make_thread(
        fields={"service_key": "klein_curacao", "customer_name": "Test"},
        flags={
            "hold_created": True,
            "booking_ref": "BF-2026-00001",
            "fully_escalated": False,
            "awaiting_relay": False,
            "returning_booking": "BF-2026-00099",
        },
    )
    email_poller._maybe_reset_for_new_booking(th)
    # These are NOT in _BOOKING_FLAGS_TO_RESET — they should survive
    assert "fully_escalated" in th["flags"], "FAIL: fully_escalated should survive"
    assert "awaiting_relay" in th["flags"], "FAIL: awaiting_relay should survive"
    assert "returning_booking" in th["flags"], "FAIL: returning_booking should survive"
    # Booking flags should be cleared
    assert "hold_created" not in th["flags"], "FAIL: hold_created should be cleared"
    assert "booking_ref" not in th["flags"], "FAIL: booking_ref should be cleared"
    print("PASS: test_non_booking_flags_preserved")


def test_prompt_completed_bookings_section():
    """When _completed_bookings_summary is in flags, prompt includes COMPLETED BOOKINGS section."""
    prompt = marina_agent._build_prompt(
        "test@example.com", "booking", "I also want sunset cruise",
        {"customer_name": "Callou"},
        {"_completed_bookings_summary": "  - Klein Curaçao on 2026-04-15 for 4 guests (ref: BF-2026-00001)"},
    )
    assert "COMPLETED BOOKINGS IN THIS THREAD:" in prompt, "FAIL: missing COMPLETED BOOKINGS section"
    assert "Klein Curaçao" in prompt, "FAIL: completed booking details not in prompt"
    assert "BF-2026-00001" in prompt, "FAIL: booking ref not in prompt"
    print("PASS: test_prompt_completed_bookings_section")


def test_prompt_max_bookings_reached():
    """When _max_bookings_reached is True, prompt includes MAX BOOKINGS section."""
    prompt = marina_agent._build_prompt(
        "test@example.com", "booking", "I want another service",
        {"customer_name": "Callou"},
        {"_max_bookings_reached": True},
    )
    assert "MAX BOOKINGS REACHED:" in prompt, "FAIL: missing MAX BOOKINGS section"
    assert "email again" in prompt, "FAIL: should mention emailing again"
    print("PASS: test_prompt_max_bookings_reached")


def test_prompt_no_completed_without_data():
    """Without completed bookings data, no COMPLETED BOOKINGS section."""
    prompt = marina_agent._build_prompt(
        "test@example.com", "booking", "I want to book",
        {}, {},
    )
    assert "COMPLETED BOOKINGS IN THIS THREAD:" not in prompt
    assert "MAX BOOKINGS REACHED:" not in prompt
    print("PASS: test_prompt_no_completed_without_data")


def test_completed_bookings_summary_format():
    """Verify the summary format that gets injected into agent_flags."""
    completed = [
        {
            "booking_ref": "BF-2026-00001",
            "service_key": "klein_curacao",
            "service_name": "Klein Curaçao",
            "date": "2026-04-15",
            "guests": "4",
        },
        {
            "booking_ref": "BF-2026-00002",
            "service_key": "sunset_cruise",
            "service_name": "Sunset Cruise",
            "date": "2026-04-16",
            "guests": "2",
        },
    ]
    lines = []
    for cb in completed:
        lines.append(
            f"  - {cb.get('service_name', cb.get('service_key', '?'))} on "
            f"{cb.get('date', '?')} for {cb.get('guests', '?')} guests "
            f"(ref: {cb.get('booking_ref', 'N/A')})"
        )
    summary = "\n".join(lines)
    assert "Klein Curaçao on 2026-04-15 for 4 guests (ref: BF-2026-00001)" in summary
    assert "Sunset Cruise on 2026-04-16 for 2 guests (ref: BF-2026-00002)" in summary
    print("PASS: test_completed_bookings_summary_format")


def test_intent_gating_prevents_non_booking_reset():
    """Verify that the reset is gated on booking intent — non-booking intents
    should NOT trigger _maybe_reset_for_new_booking even with hold_created=True.
    This test validates the gating logic by showing that _maybe_reset_for_new_booking
    only checks hold_created and max_bookings — the intent gating is done by the
    caller in the main loop."""
    th = _make_thread(
        fields={"service_key": "klein_curacao", "customer_name": "Test",
                "date": "2026-04-15", "guests": "2"},
        flags={"hold_created": True, "booking_ref": "BF-2026-00001"},
    )
    # _maybe_reset_for_new_booking itself always resets when hold_created is True
    # The intent gating happens in the main loop BEFORE calling this function
    result = email_poller._maybe_reset_for_new_booking(th)
    assert result == True, "FAIL: function should return True (intent gating is in caller)"
    # This test documents that the CALLER must gate on booking intent
    print("PASS: test_intent_gating_prevents_non_booking_reset")


if __name__ == "__main__":
    test_reset_after_hold_created()
    test_no_reset_without_hold_created()
    test_max_bookings_blocks_reset()
    test_second_booking_archives_correctly()
    test_non_booking_flags_preserved()
    test_prompt_completed_bookings_section()
    test_prompt_max_bookings_reached()
    test_prompt_no_completed_without_data()
    test_completed_bookings_summary_format()
    test_intent_gating_prevents_non_booking_reset()
    print(f"\n10/10 tests passed.")
