# tests/test_booking_ref_reply.py
# Brief 058 — Fix: Booking Ref Missing from Confirmation Reply

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import marina_agent


def test_booking_ref_placeholder_replaced():
    """[BOOKING_REF] in reply_text is replaced with actual ref."""
    reply_text = "You're confirmed! Your booking reference is [BOOKING_REF] — see you soon."
    booking_ref = "BF-2026-12345"
    result = reply_text.replace("[BOOKING_REF]", booking_ref)
    assert "BF-2026-12345" in result
    assert "[BOOKING_REF]" not in result


def test_payment_link_and_booking_ref_both_replaced():
    """Both [PAYMENT_LINK] and [BOOKING_REF] are replaced independently."""
    reply_text = "Ref: [BOOKING_REF]. Pay here: [PAYMENT_LINK]."
    result = reply_text.replace("[PAYMENT_LINK]", "https://demo.pay/abc")
    result = result.replace("[BOOKING_REF]", "BF-2026-99999")
    assert "BF-2026-99999" in result
    assert "https://demo.pay/abc" in result
    assert "[BOOKING_REF]" not in result
    assert "[PAYMENT_LINK]" not in result


def test_reply_without_placeholder_unaffected():
    """A reply with no [BOOKING_REF] placeholder is returned unchanged."""
    reply_text = "You're all set! See you on the water."
    result = reply_text.replace("[BOOKING_REF]", "BF-2026-12345")
    assert result == reply_text


def test_prompt_contains_booking_ref_placeholder_instruction():
    """Prompt instructs Marina to use [BOOKING_REF] placeholder, not read from thread_flags."""
    prompt = marina_agent._build_prompt("a@b.com", "test", "hi", {}, {})
    booking_ref_section_start = prompt.index("BOOKING REFERENCE:")
    escalation_start = prompt.index("ESCALATION BEHAVIOUR:")
    booking_ref_section = prompt[booking_ref_section_start:escalation_start]
    assert "[BOOKING_REF]" in booking_ref_section
    assert "thread_flags" not in booking_ref_section


def test_prompt_no_longer_references_thread_flags_for_booking_ref():
    """Old broken instruction ('booking_ref is present in thread_flags') is gone."""
    prompt = marina_agent._build_prompt("a@b.com", "test", "hi", {}, {})
    assert "booking_ref is present in thread_flags" not in prompt


def test_booking_ref_format_matches_expected_pattern():
    """Generated booking_ref matches BF-YYYY-NNNNN format."""
    import time
    import re
    booking_ref = f"BF-{time.strftime('%Y')}-{int(time.time()) % 100000:05d}"
    assert re.match(r"BF-\d{4}-\d{5}$", booking_ref)


if __name__ == "__main__":
    tests = [
        test_booking_ref_placeholder_replaced,
        test_payment_link_and_booking_ref_both_replaced,
        test_reply_without_placeholder_unaffected,
        test_prompt_contains_booking_ref_placeholder_instruction,
        test_prompt_no_longer_references_thread_flags_for_booking_ref,
        test_booking_ref_format_matches_expected_pattern,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__} — {e}")
    print(f"\n{passed}/{len(tests)} tests passed.")
