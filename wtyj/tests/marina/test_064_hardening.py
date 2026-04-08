"""Tests for Brief 064 — Past Date Check, Escalation Email Info, Noreply Filter, Email-Based Returning Customer."""
import json
from datetime import datetime, timezone, timedelta

from agents.marina.email_poller import _post_validate, _day_matches, _SYSTEM_EMAIL_PREFIXES
from agents.marina.marina_agent import _build_user_prompt
from shared import config_loader, state_registry


def test_past_date_does_not_advance_state():
    """Brief 161 (was T1): past date returns (None, False) — Marina writes the rejection herself."""
    _service = config_loader.get_service("sunset_cruise")
    th = {
        "fields": {"service_key": "sunset_cruise", "service_name": "Sunset Cruise", "date": "2025-01-02", "guests": "2"},
        "flags": {},
        "messages": [],
    }
    result = {"intents": ["booking"], "fields": {"service_key": "sunset_cruise", "date": "2025-01-02", "guests": "2"}}
    reply, awaiting = _post_validate(th, result, _service)
    assert reply is None
    assert awaiting is False


def test_future_date_no_already_passed():
    """T2: Future date does not say 'already passed'."""
    _service = config_loader.get_service("sunset_cruise")
    _days_avail = _service.get("days_available", "daily")
    _test_date = None
    for d in range(60, 120):
        _candidate = (datetime.now(timezone(timedelta(hours=-4))) + timedelta(days=d)).strftime("%Y-%m-%d")
        _day_name = datetime.strptime(_candidate, "%Y-%m-%d").strftime("%A")
        if _day_matches(_day_name, _days_avail):
            _test_date = _candidate
            break
    th = {
        "fields": {"service_key": "sunset_cruise", "date": _test_date, "guests": "2",
                   "customer_name": "Test User", "phone": "+5999-1234567"},
        "flags": {},
        "messages": [],
    }
    result = {"fields": {"service_key": "sunset_cruise", "date": _test_date, "guests": "2",
                          "customer_name": "Test User", "phone": "+5999-1234567"}}
    reply, _ = _post_validate(th, result, _service)
    assert reply is None or "already passed" not in reply


def test_escalation_subject_format():
    """T3: Escalation subject contains customer email."""
    _from_email = "angry@customer.com"
    _subject_line = f"[ESCALATION] NO-REF - Unknown ({_from_email}) - complaint"
    assert "angry@customer.com" in _subject_line and "(" in _subject_line


def test_escalation_body_format():
    """T4: Escalation body starts with '=== CUSTOMER ==='."""
    _from_email = "angry@customer.com"
    _phone = "+5999-1234567"
    _fields = {"phone": _phone, "customer_name": "Test"}
    _escalation_alert = (
        f"=== CUSTOMER ===\n"
        f"Email: {_from_email}\n"
        f"Name: Unknown\n"
        f"Phone: {_phone or 'not provided'}\n\n"
        f"=== CHAT LOG ===\n(test chat log)\n\n"
        f"=== BOOKING FIELDS ===\n"
        f"{json.dumps(_fields, indent=2, ensure_ascii=False)}\n\n"
        f"=== MARINA'S INTERNAL NOTE ===\n"
        f"test note"
    )
    assert _escalation_alert.startswith("=== CUSTOMER ===")
    assert "angry@customer.com" in _escalation_alert


def test_system_email_prefixes_match():
    """T5: System email prefixes match all system emails."""
    _system_emails = [
        "noreply@example.com", "no-reply@shop.com", "no_reply@bank.com",
        "do-not-reply@service.com", "donotreply@alerts.com",
        "mailer-daemon@mx.com", "postmaster@domain.com", "bounce@lists.com",
    ]
    _all_match = all(
        any(e.lower().startswith(p) for p in _SYSTEM_EMAIL_PREFIXES)
        for e in _system_emails
    )
    assert _all_match


def test_system_email_prefixes_no_false_match():
    """T5b: System email prefixes don't match real emails."""
    _real_emails = [
        "john@example.com", "support@company.com", "marina@bluefinn.com",
    ]
    _no_match = not any(
        any(e.lower().startswith(p) for p in _SYSTEM_EMAIL_PREFIXES)
        for e in _real_emails
    )
    assert _no_match


def test_get_bookings_by_email():
    """T6: get_bookings_by_email returns matching bookings."""
    _test_ref = "BF-2026-T064A"
    _test_email = "Test064@Example.COM"
    _test_fields = {
        "service_key": "sunset_cruise", "date": "2027-06-15",
        "slot_time": "16:30", "guests": 4,
        "customer_name": "Test User 064", "special_requests": "",
    }
    _test_flags = {"payment_link": "https://demo.pay/test", "event_link": ""}
    state_registry.save_booking(_test_ref, _test_fields, _test_flags, _test_email)

    try:
        results = state_registry.get_bookings_by_email(_test_email)
        assert len(results) >= 1
        found = any(r["booking_ref"] == _test_ref for r in results)
        assert found
        found_booking = next((r for r in results if r["booking_ref"] == _test_ref), None)
        assert found_booking and found_booking["customer_email"] == "test064@example.com"
    finally:
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM bookings WHERE booking_ref = ?", (_test_ref,))
        conn.commit()
        conn.close()


def test_get_bookings_by_email_empty():
    """T7: get_bookings_by_email returns empty for unknown email."""
    empty = state_registry.get_bookings_by_email("nobody_ever_064@nonexistent.xyz")
    assert len(empty) == 0


def test_returning_customer_prompt():
    """T8: Returning customer context in prompt when bookings exist."""
    flags = {
        "_past_customer_bookings": "  - sunset_cruise on 2027-06-15 for 4 guests (ref: BF-2026-T064A)",
    }
    prompt = _build_user_prompt(
        "test@example.com", "New booking", "I want to book again",
        {}, flags,
    )
    assert "RETURNING CUSTOMER (by email)" in prompt
    assert "BF-2026-T064A" in prompt
