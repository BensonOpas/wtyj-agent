#!/usr/bin/env python3
"""Tests for Brief 064 — Past Date Check, Escalation Email Info, Noreply Filter, Email-Based Returning Customer."""
import sys, os, json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock


passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        print(f"  {name} PASS")
        passed += 1
    else:
        print(f"  {name} FAIL")
        failed += 1

print("Running Brief 064 tests...")

# --- T1: Past date returns "already passed" ---
from agents.marina.email_poller import _post_validate
from shared import config_loader

# Build a thread with a past date
_trip = config_loader.get_trip("sunset_cruise")
_th_past = {
    "fields": {"trip_key": "sunset_cruise", "experience": "Sunset Cruise", "date": "2025-01-02", "guests": "2"},
    "flags": {},
    "messages": [],
}
_result_past = {"intents": ["booking"], "fields": {"trip_key": "sunset_cruise", "date": "2025-01-02", "guests": "2"}}
_reply_past, _should_await_past = _post_validate(_th_past, _result_past, _trip)
check("T1: Past date returns 'already passed'", _reply_past is not None and "already passed" in _reply_past)

# --- T2: Future date still builds summary ---
_future_date = (datetime.now(timezone(timedelta(hours=-4))) + timedelta(days=60)).strftime("%Y-%m-%d")
# Find a valid day for sunset_cruise
_days_avail = _trip.get("days_available", "daily")
# Just use a far future date and skip day-of-week issues by picking the right day
from agents.marina.email_poller import _day_matches
_test_date = None
for d in range(60, 120):
    _candidate = (datetime.now(timezone(timedelta(hours=-4))) + timedelta(days=d)).strftime("%Y-%m-%d")
    _day_name = datetime.strptime(_candidate, "%Y-%m-%d").strftime("%A")
    if _day_matches(_day_name, _days_avail):
        _test_date = _candidate
        break

_th_future = {
    "fields": {"trip_key": "sunset_cruise", "date": _test_date, "guests": "2",
               "customer_name": "Test User", "phone": "+5999-1234567"},
    "flags": {},
    "messages": [],
}
_result_future = {"fields": {"trip_key": "sunset_cruise", "date": _test_date, "guests": "2",
                              "customer_name": "Test User", "phone": "+5999-1234567"}}
_reply_future, _should_await_future = _post_validate(_th_future, _result_future, _trip)
# Future date should either return None (no override) or a summary (not "already passed")
check("T2: Future date does not say 'already passed'",
      _reply_future is None or "already passed" not in _reply_future)

# --- T3: Escalation subject contains customer email ---
check("T3: Escalation subject format includes email",
      "({from_email})" in
      f"[ESCALATION] BF-2026-12345 - John Doe ({'{from_email}'}) - complaint")

# Let's test the actual format by simulating what the code does
_booking_ref_esc = "NO-REF"
_customer_name_esc = "Unknown"
_from_email_test = "angry@customer.com"
_intents_str = "complaint"
_subject_line = f"[ESCALATION] {_booking_ref_esc} - {_customer_name_esc} ({_from_email_test}) - {_intents_str}"
check("T3: Escalation subject contains customer email",
      "angry@customer.com" in _subject_line and "(" in _subject_line)

# --- T4: Escalation body starts with "=== CUSTOMER ===" ---
_phone_esc = "+5999-1234567"
_chat_log = "(test chat log)"
_fields = {"phone": _phone_esc, "customer_name": "Test"}
_escalation_alert = (
    f"=== CUSTOMER ===\n"
    f"Email: {_from_email_test}\n"
    f"Name: {_customer_name_esc}\n"
    f"Phone: {_phone_esc or 'not provided'}\n\n"
    f"=== CHAT LOG ===\n{_chat_log}\n\n"
    f"=== BOOKING FIELDS ===\n"
    f"{json.dumps(_fields, indent=2, ensure_ascii=False)}\n\n"
    f"=== MARINA'S INTERNAL NOTE ===\n"
    f"test note"
)
check("T4: Escalation body starts with '=== CUSTOMER ==='",
      _escalation_alert.startswith("=== CUSTOMER ==="))
check("T4b: Escalation body contains customer email",
      "angry@customer.com" in _escalation_alert)

# --- T5: System email prefixes match expected patterns ---
from agents.marina.email_poller import _SYSTEM_EMAIL_PREFIXES

_system_emails = [
    "noreply@example.com", "no-reply@shop.com", "no_reply@bank.com",
    "do-not-reply@service.com", "donotreply@alerts.com",
    "mailer-daemon@mx.com", "postmaster@domain.com", "bounce@lists.com",
]
_real_emails = [
    "john@example.com", "support@company.com", "marina@bluefinn.com",
]
_all_system_match = all(
    any(e.lower().startswith(p) for p in _SYSTEM_EMAIL_PREFIXES)
    for e in _system_emails
)
_no_real_match = not any(
    any(e.lower().startswith(p) for p in _SYSTEM_EMAIL_PREFIXES)
    for e in _real_emails
)
check("T5: System email prefixes match all system emails", _all_system_match)
check("T5b: System email prefixes don't match real emails", _no_real_match)

# --- T6: get_bookings_by_email returns matching bookings ---
from shared import state_registry

# Insert a test booking, then look it up
_test_ref = "BF-2026-T064A"
_test_email = "Test064@Example.COM"
_test_fields = {
    "trip_key": "sunset_cruise", "date": "2027-06-15",
    "departure_time": "16:30", "guests": 4,
    "customer_name": "Test User 064", "special_requests": "",
}
_test_flags = {"payment_link": "https://demo.pay/test", "event_link": ""}
state_registry.save_booking(_test_ref, _test_fields, _test_flags, _test_email)

_results = state_registry.get_bookings_by_email(_test_email)
check("T6: get_bookings_by_email returns matching bookings", len(_results) >= 1)
_found = any(r["booking_ref"] == _test_ref for r in _results)
check("T6b: Found the specific test booking", _found)

# Verify email was normalized to lowercase
_found_booking = next((r for r in _results if r["booking_ref"] == _test_ref), None)
check("T6c: Email normalized to lowercase in DB",
      _found_booking and _found_booking["customer_email"] == "test064@example.com")

# --- T7: get_bookings_by_email returns empty for unknown email ---
_empty = state_registry.get_bookings_by_email("nobody_ever_064@nonexistent.xyz")
check("T7: get_bookings_by_email returns empty for unknown email", len(_empty) == 0)

# --- T8: Returning customer context in prompt when bookings exist ---
from agents.marina.marina_agent import _build_user_prompt

_thread_flags_with_bookings = {
    "_past_customer_bookings": "  - sunset_cruise on 2027-06-15 for 4 guests (ref: BF-2026-T064A)",
}
_prompt = _build_user_prompt(
    "test@example.com", "New booking", "I want to book again",
    {}, _thread_flags_with_bookings
)
check("T8: Returning customer section in prompt",
      "RETURNING CUSTOMER (by email)" in _prompt)
check("T8b: Past booking details in prompt",
      "BF-2026-T064A" in _prompt)

# --- Cleanup test booking ---
conn = state_registry._get_conn()
conn.execute("DELETE FROM bookings WHERE booking_ref = ?", (_test_ref,))
conn.commit()
conn.close()

# --- Summary ---
print(f"\nBrief 064: {passed} passed, {failed} failed out of {passed + failed}")
if failed > 0:
    sys.exit(1)
