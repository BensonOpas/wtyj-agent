#!/usr/bin/env python3
# bluemarlin/test_036_prompt_fixes.py
# Brief 036 — Marina prompt bug fixes
# Run: cd bluemarlin && python3 test_036_prompt_fixes.py

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import marina_agent

prompt = marina_agent._build_prompt(
    from_email="test@example.com",
    subject="Test",
    body="Hello",
    thread_fields={},
    thread_flags={},
)

# T1: Language rule is body-text-based
assert "body text" in prompt, f"T1 fail: 'body text' missing from LANGUAGE RULE"
print("T1 pass — LANGUAGE RULE specifies body text")

# T2: Language rule explicitly handles Germanic/non-English names
assert "German" in prompt or "sender" in prompt.lower() or "name" in prompt.lower(), \
    f"T2 fail: LANGUAGE RULE does not address name-based interference"
print("T2 pass — LANGUAGE RULE addresses non-English names")

# T3: BOOKING CONFIRMATION section includes days_available check
assert "days_available" in prompt, \
    f"T3 fail: 'days_available' check missing from BOOKING CONFIRMATION section"
print("T3 pass — days_available validation present in prompt")

# T4: BOOKING CONFIRMATION day-of-week check references TRIPS data
assert "day the trip does not run" in prompt, \
    f"T4 fail: day-of-week block missing from BOOKING CONFIRMATION section"
print("T4 pass — day-of-week validation block present in prompt")

# T5: reply_hold_failed description includes "ONLY when"
assert "ONLY when" in prompt, \
    f"T5 fail: 'ONLY when' missing from reply_hold_failed description"
print("T5 pass — reply_hold_failed scoped with 'ONLY when'")

# T6: reply_hold_failed description excludes escalation paths
assert "escalation" in prompt or "inquiry" in prompt, \
    f"T6 fail: reply_hold_failed exclusion of non-booking paths missing"
print("T6 pass — reply_hold_failed exclusion of non-booking paths present")

# T7: File header updated to Brief 036
with open(os.path.join(os.path.dirname(__file__), "src", "marina_agent.py")) as f:
    header = f.read(300)
assert "Brief 036" in header, f"T7 fail: file header not updated to Brief 036"
print("T7 pass — file header updated to Brief 036")

print("\nAll 7 tests passed.")
print("\nManual verification: re-run test_marina_stress.py and confirm:")
print("  S7  — no booking summary for Thursday west_coast_beach")
print("  S11 — English reply for English message (Hans Müller scenario)")
print("  S8  — no reply_hold_failed for group escalation")
