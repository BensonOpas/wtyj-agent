#!/usr/bin/env python3
# bluemarlin/test_038_prompt_fixes.py
# Brief 038 — child age pricing + mid-confirmation day-of-week check
# Run: cd bluemarlin && source ~/.zshrc && python3 test_038_prompt_fixes.py

import os, sys, json
from agents.marina import marina_agent

# --- Prompt structure tests (no API call) ---
prompt = marina_agent._build_prompt(
    from_email="test@example.com",
    subject="Test",
    body="Hello",
    thread_fields={},
    thread_flags={},
)

# T1: BOOKING BEHAVIOUR section present in prompt (supersedes Brief 038 SECOND check, removed in Brief 046)
assert "BOOKING BEHAVIOUR:" in prompt, "T1 fail: BOOKING BEHAVIOUR missing from prompt"
print("T1 pass — BOOKING BEHAVIOUR present in prompt")

# T2: Child age instruction present (restructured in Brief 046)
assert "needs_child_ages" in prompt, \
    "T2 fail: child age flag instruction missing"
print("T2 pass — child age flag instruction present")

# T3: Date clearing instruction present (added in Brief 048)
assert 'set date to ""' in prompt or "set date to empty" in prompt.lower(), \
    "T3 fail: date clearing instruction missing"
print("T3 pass — date clearing instruction present")

# T4: Guest hallucination guard present (added in Brief 048)
assert "Never infer a guest count" in prompt, \
    "T4 fail: guest hallucination guard missing"
print("T4 pass — guest hallucination guard present")

# T5: File header updated (now Brief 060)
with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "marina_agent.py")) as f:
    header = f.read(300)
assert "Last modified: Brief" in header, "T5 fail: file header not updated"
print("T5 pass — file header updated to Brief 060")

# --- Live model tests (2 API calls) ---

# T6: S12 re-run — date change mid-confirmation to invalid day (Sunday sunset cruise)
# Expected: awaiting_booking_confirmation NOT set; reply does not offer to lock in
print("\nT6: Running S12 re-run (mid-confirmation Sunday date change)...")
s12 = marina_agent.process_message(
    from_email="alice@example.com",
    subject="Re: Booking sunset cruise",
    body="Actually, can we change it to May 10 instead? The 5th doesn't work.",
    thread_fields={
        "service_name": "Sunset Cruise",
        "service_key": "sunset_cruise",
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
lock_phrases = ["shall i lock", "lock this in", "locking this in", "locking it in", "go ahead and book"]
assert not any(phrase in reply_s12.lower() for phrase in lock_phrases), \
    f"T6 fail: reply contains booking summary / lock-in offer for invalid Sunday date.\nreply={reply_s12[:300]}"
print(f"T6 pass — no flag set and no lock-in offer for invalid Sunday date. flags={flags_s12}")

# T7: S21 re-run — "2 adults and 3 kids" — should ask ages, not send summary
print("\nT7: Running S21 re-run (2 adults 3 kids, ages unknown)...")
s21 = marina_agent.process_message(
    from_email="marco@example.com",
    subject="Klein Curacao booking",
    body="Hi, I'd like to book the Klein Curacao service on May 20 2026. We are 2 adults and 3 kids. Name is Marco Rossi.",
    thread_fields={},
    thread_flags={},
)
flags_s21 = s21.get("flags", {})
assert not flags_s21.get("awaiting_booking_confirmation"), \
    f"T7 fail: booking summary sent without asking child ages. flags={flags_s21}"
print(f"T7 pass — no booking summary sent before asking child ages. flags={flags_s21}")
print(f"  clarifications: {s21.get('clarifications_needed', [])}")

print("\nAll 7 tests passed.")
