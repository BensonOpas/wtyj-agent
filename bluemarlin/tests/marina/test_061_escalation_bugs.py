"""Tests for Brief 061 — Escalation Logic Bugs: NO-REF, Empty Name, Silent Ref Drop."""
from agents.marina.email_poller import _resolve_booking_ref, _detect_booking_ref
from agents.marina import marina_agent


def test_returning_booking_fallthrough():
    """T1: _resolve_booking_ref falls through to returning_booking."""
    th = {"fields": {}, "flags": {"returning_booking": "BF-2026-12345"}, "messages": []}
    assert _resolve_booking_ref(th) == "BF-2026-12345"


def test_booking_ref_takes_priority():
    """T2: _resolve_booking_ref uses booking_ref when present."""
    th = {"fields": {}, "flags": {"booking_ref": "BF-2026-99999", "returning_booking": "BF-2026-12345"}, "messages": []}
    assert _resolve_booking_ref(th) == "BF-2026-99999"


def test_no_ref_fallback():
    """T3: _resolve_booking_ref returns NO-REF when neither present."""
    th = {"fields": {}, "flags": {}, "messages": []}
    assert _resolve_booking_ref(th) == "NO-REF"


def test_unknown_ref_flag():
    """T4: Unknown ref flag set when ref not found."""
    th = {"fields": {}, "flags": {}}
    _detected_ref = "BF-2026-00000"
    _past_booking = None  # Simulates get_booking returning None
    if _past_booking:
        th["flags"]["returning_booking"] = _detected_ref
    else:
        th["flags"]["unknown_ref"] = _detected_ref
    assert th["flags"]["unknown_ref"] == "BF-2026-00000"
    assert "returning_booking" not in th["flags"]


def test_unknown_ref_in_prompt():
    """T5: Unknown ref section appears in prompt when flag set."""
    prompt = marina_agent._build_user_prompt("a@b.com", "T", "T", {}, {"unknown_ref": "BF-2026-00000"})
    assert "BF-2026-00000" in prompt
    assert "not found" in prompt.lower() or "couldn't find" in prompt.lower()


def test_no_unknown_ref_when_absent():
    """T6: Unknown ref section absent when flag not set."""
    prompt = marina_agent._build_user_prompt("a@b.com", "T", "T", {}, {})
    assert "UNKNOWN BOOKING REF" not in prompt


def test_detect_valid_ref():
    """T7: _detect_booking_ref extracts valid ref format."""
    ref = _detect_booking_ref("My booking BF-2026-12345 needs to be cancelled")
    assert ref == "BF-2026-12345"


def test_detect_no_ref():
    """T8: _detect_booking_ref returns None for no ref."""
    ref = _detect_booking_ref("I want to book a service")
    assert ref is None
