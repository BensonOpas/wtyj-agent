"""Tests for Brief 054 — Booking ref in confirmation + cross-thread memory."""
import sys, os, time, re

# Use a test database to avoid touching production data
from shared import state_registry
_ORIGINAL_DB_PATH = state_registry.DB_PATH
state_registry.DB_PATH = os.path.join(os.path.dirname(__file__), 'test_054.db')

from agents.marina import marina_agent
from agents.marina import email_poller


def _cleanup_db():
    """Remove test database if it exists."""
    if os.path.exists(state_registry.DB_PATH):
        os.remove(state_registry.DB_PATH)
    wal = state_registry.DB_PATH + "-wal"
    shm = state_registry.DB_PATH + "-shm"
    if os.path.exists(wal):
        os.remove(wal)
    if os.path.exists(shm):
        os.remove(shm)


def test_save_and_get_booking():
    """Round-service: save a booking, retrieve it, verify all fields."""
    _cleanup_db()
    fields = {
        "service_key": "klein_curacao",
        "customer_name": "Callou",
        "date": "2026-04-15",
        "slot_time": "08:30",
        "guests": 4,
        "special_requests": "window seat",
    }
    flags = {
        "payment_link": "https://demo.pay/bluemarlin/pay123",
        "event_link": "https://calendar.google.com/event/abc",
    }
    state_registry.save_booking("BF-2026-00001", fields, flags,
                                customer_email="callou@example.com")
    result = state_registry.get_booking("BF-2026-00001")

    assert result is not None, "FAIL: booking should exist"
    assert result["booking_ref"] == "BF-2026-00001", f"FAIL: ref={result['booking_ref']}"
    assert result["service_key"] == "klein_curacao", f"FAIL: service_key={result['service_key']}"
    assert result["customer_name"] == "Callou", f"FAIL: name={result['customer_name']}"
    assert result["customer_email"] == "callou@example.com", f"FAIL: email={result['customer_email']}"
    assert result["date"] == "2026-04-15", f"FAIL: date={result['date']}"
    assert result["slot_time"] == "08:30", f"FAIL: dep={result['slot_time']}"
    assert result["guests"] == 4, f"FAIL: guests={result['guests']}"
    assert result["special_requests"] == "window seat", f"FAIL: sr={result['special_requests']}"
    assert result["payment_link"] == "https://demo.pay/bluemarlin/pay123"
    assert result["event_link"] == "https://calendar.google.com/event/abc"
    assert result["status"] == "confirmed", f"FAIL: status={result['status']}"
    _cleanup_db()
    print("PASS: test_save_and_get_booking")


def test_get_booking_not_found():
    """Non-existent ref returns None."""
    _cleanup_db()
    result = state_registry.get_booking("BF-9999-99999")
    assert result is None, f"FAIL: expected None, got {result}"
    _cleanup_db()
    print("PASS: test_get_booking_not_found")


def test_save_booking_upsert():
    """Saving with same ref overwrites — upsert behavior."""
    _cleanup_db()
    fields1 = {"service_key": "klein_curacao", "customer_name": "Alice", "guests": 2}
    flags1 = {}
    state_registry.save_booking("BF-2026-00002", fields1, flags1,
                                customer_email="alice@example.com")

    fields2 = {"service_key": "sunset_cruise", "customer_name": "Alice Updated", "guests": 3}
    flags2 = {}
    state_registry.save_booking("BF-2026-00002", fields2, flags2,
                                customer_email="alice@example.com")

    result = state_registry.get_booking("BF-2026-00002")
    assert result["service_key"] == "sunset_cruise", f"FAIL: service_key not updated"
    assert result["customer_name"] == "Alice Updated", f"FAIL: name not updated"
    assert result["guests"] == 3, f"FAIL: guests not updated"
    _cleanup_db()
    print("PASS: test_save_booking_upsert")


def test_detect_booking_ref_found():
    """Detects BF-YYYY-XXXXX pattern in message body."""
    body = "Hi, my booking reference is BF-2026-12345, can I change the date?"
    ref = email_poller._detect_booking_ref(body)
    assert ref == "BF-2026-12345", f"FAIL: expected BF-2026-12345, got {ref}"
    print("PASS: test_detect_booking_ref_found")


def test_detect_booking_ref_not_found():
    """No pattern in body returns None."""
    body = "Hi, I want to book a service to Klein Curaçao!"
    ref = email_poller._detect_booking_ref(body)
    assert ref is None, f"FAIL: expected None, got {ref}"
    print("PASS: test_detect_booking_ref_not_found")


def test_detect_booking_ref_multiple():
    """Multiple refs in body — returns first one."""
    body = "I have BF-2026-11111 and also BF-2026-22222"
    ref = email_poller._detect_booking_ref(body)
    assert ref == "BF-2026-11111", f"FAIL: expected first ref, got {ref}"
    print("PASS: test_detect_booking_ref_multiple")


def test_returning_customer_field_population():
    """When a booking is found, fields are populated on empty thread."""
    _cleanup_db()
    fields = {
        "service_key": "snorkeling_3in1",
        "customer_name": "Calvin",
        "date": "2026-05-01",
        "slot_time": "09:00",
        "guests": 6,
    }
    flags = {}
    state_registry.save_booking("BF-2026-00003", fields, flags,
                                customer_email="calvin@example.com")

    # Simulate empty thread
    th = {"fields": {}, "flags": {}}
    body = "Hi, my ref is BF-2026-00003, can I change the date?"
    ref = email_poller._detect_booking_ref(body)
    assert ref == "BF-2026-00003"

    past = state_registry.get_booking(ref)
    assert past is not None
    # Simulate the field population logic from the brief
    for k in ("service_key", "date", "guests", "customer_name", "slot_time"):
        v = past.get(k)
        if v and not th["fields"].get(k):
            th["fields"][k] = v if not isinstance(v, int) else str(v)
    th["flags"]["returning_booking"] = ref

    assert th["fields"]["service_key"] == "snorkeling_3in1"
    assert th["fields"]["customer_name"] == "Calvin"
    assert th["fields"]["date"] == "2026-05-01"
    assert th["fields"]["guests"] == "6"  # converted to string
    assert th["flags"]["returning_booking"] == "BF-2026-00003"
    _cleanup_db()
    print("PASS: test_returning_customer_field_population")


def test_returning_customer_no_overwrite():
    """Returning customer lookup does NOT overwrite existing thread fields."""
    _cleanup_db()
    fields = {
        "service_key": "klein_curacao",
        "customer_name": "Calvin",
        "date": "2026-05-01",
        "guests": 6,
    }
    flags = {}
    state_registry.save_booking("BF-2026-00004", fields, flags,
                                customer_email="calvin@example.com")

    # Thread already has some fields from current conversation
    th = {"fields": {"customer_name": "Calvin Updated", "service_key": "sunset_cruise"}, "flags": {}}
    past = state_registry.get_booking("BF-2026-00004")
    for k in ("service_key", "date", "guests", "customer_name", "slot_time"):
        v = past.get(k)
        if v and not th["fields"].get(k):
            th["fields"][k] = v if not isinstance(v, int) else str(v)

    # Existing fields should NOT be overwritten
    assert th["fields"]["customer_name"] == "Calvin Updated", "FAIL: existing name was overwritten"
    assert th["fields"]["service_key"] == "sunset_cruise", "FAIL: existing service_key was overwritten"
    # But missing fields should be populated
    assert th["fields"]["date"] == "2026-05-01", "FAIL: date not populated"
    assert th["fields"]["guests"] == "6", "FAIL: guests not populated"
    _cleanup_db()
    print("PASS: test_returning_customer_no_overwrite")


def test_prompt_contains_booking_ref_instruction():
    """Marina's prompt instructs use of [BOOKING_REF] placeholder (Brief 058 fix)."""
    prompt = marina_agent._build_prompt(
        "test@example.com", "booking", "test body",
        {"service_key": "klein_curacao"}, {"booking_ref": "BF-2026-99999"},
    )
    assert "BOOKING REFERENCE:" in prompt, "FAIL: prompt missing BOOKING REFERENCE section"
    booking_ref_section_start = prompt.index("BOOKING REFERENCE:")
    escalation_start = prompt.index("ESCALATION BEHAVIOUR:")
    booking_ref_section = prompt[booking_ref_section_start:escalation_start]
    assert "[BOOKING_REF]" in booking_ref_section, "FAIL: prompt doesn't contain [BOOKING_REF] placeholder"
    assert "thread_flags" not in booking_ref_section, "FAIL: old thread_flags reference still present"
    print("PASS: test_prompt_contains_booking_ref_instruction")


def test_prompt_contains_returning_customer_section():
    """When returning_booking is in flags, prompt includes RETURNING CUSTOMER section."""
    prompt = marina_agent._build_prompt(
        "test@example.com", "booking", "my ref is BF-2026-00001",
        {"service_key": "klein_curacao", "customer_name": "Calvin"},
        {"returning_booking": "BF-2026-00001"},
    )
    assert "RETURNING CUSTOMER:" in prompt, "FAIL: prompt missing RETURNING CUSTOMER section"
    assert "BF-2026-00001" in prompt, "FAIL: prompt doesn't include the booking ref"
    print("PASS: test_prompt_contains_returning_customer_section")


def test_prompt_no_returning_section_without_flag():
    """Without returning_booking flag, no RETURNING CUSTOMER section."""
    prompt = marina_agent._build_prompt(
        "test@example.com", "booking", "test body",
        {}, {},
    )
    assert "RETURNING CUSTOMER:" not in prompt, "FAIL: RETURNING CUSTOMER should not appear without flag"
    print("PASS: test_prompt_no_returning_section_without_flag")


def test_booking_ref_instruction_unconditional():
    """BOOKING REFERENCE instruction appears even with empty flags (it's static text)."""
    prompt = marina_agent._build_prompt(
        "test@example.com", "booking", "test body",
        {}, {},
    )
    assert "BOOKING REFERENCE:" in prompt, "FAIL: BOOKING REFERENCE instruction should always appear"
    print("PASS: test_booking_ref_instruction_unconditional")


if __name__ == "__main__":
    test_save_and_get_booking()
    test_get_booking_not_found()
    test_save_booking_upsert()
    test_detect_booking_ref_found()
    test_detect_booking_ref_not_found()
    test_detect_booking_ref_multiple()
    test_returning_customer_field_population()
    test_returning_customer_no_overwrite()
    test_prompt_contains_booking_ref_instruction()
    test_prompt_contains_returning_customer_section()
    test_prompt_no_returning_section_without_flag()
    test_booking_ref_instruction_unconditional()
    print(f"\n12/12 tests passed.")
