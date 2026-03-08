#!/usr/bin/env python3
# bluemarlin/test_038_prompt_fixes.py
# Brief 038 — child age pricing + mid-confirmation day-of-week check
# Run: cd bluemarlin && source ~/.zshrc && python3 test_038_prompt_fixes.py

import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import marina_agent

# --- Prompt structure tests (no API call) ---
prompt = marina_agent._build_prompt(
    from_email="test@example.com",
    subject="Test",
    body="Hello",
    thread_fields={},
    thread_flags={},
)

# T1: SECOND check present in prompt
assert "SECOND:" in prompt, "T1 fail: SECOND check missing from BOOKING CONFIRMATION BEHAVIOUR"
print("T1 pass — SECOND check present in prompt")

# T2: Child age instruction present (text spans two lines in the f-string — check for the unique phrase)
assert "for them before sending the summary" in prompt, \
    "T2 fail: child age clarification instruction missing"
print("T2 pass — child age clarification instruction present")

# T3: Mid-confirmation date change check present (lowercase "if" in prompt text)
assert "if the change involves" in prompt, \
    "T3 fail: mid-confirmation date change instruction missing"
print("T3 pass — mid-confirmation date change instruction present")

# T4: Mid-confirmation handler includes day-of-week guard (exact phrase from inserted text)
assert "do NOT reset awaiting_booking_confirmation" in prompt, \
    "T4 fail: awaiting_booking_confirmation guard missing from mid-confirmation handler"
print("T4 pass — awaiting_booking_confirmation guard present in mid-confirmation handler")

# T5: File header updated to Brief 038
with open(os.path.join(os.path.dirname(__file__), "src", "marina_agent.py")) as f:
    header = f.read(300)
assert "Brief 038" in header, "T5 fail: file header not updated to Brief 038"
print("T5 pass — file header updated to Brief 038")

# --- Live model tests (2 API calls) ---

# T6: S12 re-run — date change mid-confirmation to invalid day (Sunday sunset cruise)
# Expected: awaiting_booking_confirmation NOT set; reply does not offer to lock in
print("\nT6: Running S12 re-run (mid-confirmation Sunday date change)...")
s12 = marina_agent.process_message(
    from_email="alice@example.com",
    subject="Re: Booking sunset cruise",
    body="Actually, can we change it to May 10 instead? The 5th doesn't work.",
    thread_fields={
        "experience": "Sunset Cruise",
        "trip_key": "sunset_cruise",
        "date": "2026-05-05",
        "guests": 2,
        "customer_name": "Alice Brown",
    },
    thread_flags={"awaiting_booking_confirmation": True},
)
flags_s12 = s12.get("flags", {})
reply_s12 = s12.get("reply", "")
# Bug was: awaiting_booking_confirmation=true AND reply contained a full booking summary for Sunday
# Fix verified by: flag absent AND reply does not offer to lock in the Sunday date
assert not flags_s12.get("awaiting_booking_confirmation"), \
    f"T6 fail: awaiting_booking_confirmation=true for invalid Sunday date. flags={flags_s12}"
lock_phrases = ["shall i lock", "lock this in", "locking this in", "locking it in"]
assert not any(phrase in reply_s12.lower() for phrase in lock_phrases), \
    f"T6 fail: reply contains booking summary / lock-in offer for invalid Sunday date.\nreply={reply_s12[:300]}"
print(f"T6 pass — no flag set and no lock-in offer for invalid Sunday date. flags={flags_s12}")

# T7: S21 re-run — "2 adults and 3 kids" — should ask ages, not send summary
print("\nT7: Running S21 re-run (2 adults 3 kids, ages unknown)...")
s21 = marina_agent.process_message(
    from_email="marco@example.com",
    subject="Klein Curacao booking",
    body="Hi, I'd like to book the Klein Curacao trip on May 20 2026. We are 2 adults and 3 kids. Name is Marco Rossi.",
    thread_fields={},
    thread_flags={},
)
flags_s21 = s21.get("flags", {})
assert not flags_s21.get("awaiting_booking_confirmation"), \
    f"T7 fail: booking summary sent without asking child ages. flags={flags_s21}"
print(f"T7 pass — no booking summary sent before asking child ages. flags={flags_s21}")
print(f"  clarifications: {s21.get('clarifications_needed', [])}")

print("\nAll 7 tests passed.")
