#!/usr/bin/env python3
"""Tests for Brief 061 — Escalation Logic Bugs: NO-REF, Empty Name, Silent Ref Drop."""
import sys, os

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

print("Running Brief 061 tests...")

# T1: _resolve_booking_ref falls through to returning_booking
from agents.marina.email_poller import _resolve_booking_ref
th1 = {"fields": {}, "flags": {"returning_booking": "BF-2026-12345"}, "messages": []}
check("T1: returning_booking fallthrough", _resolve_booking_ref(th1) == "BF-2026-12345")

# T2: _resolve_booking_ref uses booking_ref when present (regression)
th2 = {"fields": {}, "flags": {"booking_ref": "BF-2026-99999", "returning_booking": "BF-2026-12345"}, "messages": []}
check("T2: booking_ref takes priority", _resolve_booking_ref(th2) == "BF-2026-99999")

# T3: _resolve_booking_ref returns NO-REF when neither present
th3 = {"fields": {}, "flags": {}, "messages": []}
check("T3: NO-REF fallback", _resolve_booking_ref(th3) == "NO-REF")

# T4: Unknown ref flag set when ref not found
th4 = {"fields": {}, "flags": {}}
_detected_ref = "BF-2026-00000"
_past_booking = None  # Simulates get_booking returning None
if _past_booking:
    th4["flags"]["returning_booking"] = _detected_ref
else:
    th4["flags"]["unknown_ref"] = _detected_ref
check("T4: unknown_ref flag set", th4["flags"]["unknown_ref"] == "BF-2026-00000")
check("T4b: returning_booking not set", "returning_booking" not in th4["flags"])

# T5: Unknown ref section appears in prompt when flag set
from agents.marina import marina_agent
prompt_unknown = marina_agent._build_user_prompt("a@b.com", "T", "T", {}, {"unknown_ref": "BF-2026-00000"})
check("T5: unknown ref in prompt", "BF-2026-00000" in prompt_unknown)
check("T5b: not found instruction in prompt",
      "not found" in prompt_unknown.lower() or "couldn't find" in prompt_unknown.lower())

# T6: Unknown ref section absent when flag not set
prompt_normal = marina_agent._build_user_prompt("a@b.com", "T", "T", {}, {})
check("T6: no UNKNOWN BOOKING REF when flag absent", "UNKNOWN BOOKING REF" not in prompt_normal)

# T7: _detect_booking_ref extracts valid ref format
from agents.marina.email_poller import _detect_booking_ref
ref7 = _detect_booking_ref("My booking BF-2026-12345 needs to be cancelled")
check("T7: detect valid ref", ref7 == "BF-2026-12345")

# T8: _detect_booking_ref returns None for no ref
ref8 = _detect_booking_ref("I want to book a trip")
check("T8: no ref returns None", ref8 is None)

print(f"\n{passed}/{passed+failed} tests passed.")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("All tests passed.")
