#!/usr/bin/env python3
"""Tests for Brief 045 — Slot-unavailable alternative = change, not confirmation."""
import sys, os, inspect
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_prompt_alternative_is_change():
    """T1: Prompt says picking an alternative is a CHANGE, not a confirmation."""
    import marina_agent
    prompt = marina_agent._build_prompt("a@b.com", "test", "test", {}, {})
    assert "CHANGE, not a confirmation" in prompt, \
        "Prompt must contain exact phrase 'CHANGE, not a confirmation'"
    print("  T1 PASS: Prompt says picking an alternative is a CHANGE")

def test_prompt_no_booking_confirmed_for_alternatives():
    """T2: Prompt says Do NOT set booking_confirmed for alternatives."""
    import marina_agent
    prompt = marina_agent._build_prompt("a@b.com", "test", "test", {}, {})
    assert "Do NOT set booking_confirmed" in prompt, \
        "Prompt must prohibit booking_confirmed for alternatives"
    print("  T2 PASS: Prompt prohibits booking_confirmed for alternatives")

def test_prompt_rerun_checks_for_alternatives():
    """T3: Prompt instructs re-running FIRST, SECOND, and THIRD checks for alternatives."""
    import marina_agent
    prompt = marina_agent._build_prompt("a@b.com", "test", "test", {}, {})
    # Find the alternative bullet and check it contains re-run instruction
    idx = prompt.index("CHANGE, not a confirmation")
    section = prompt[idx:idx + 300]
    assert "FIRST, SECOND, and THIRD checks" in section, \
        f"Alternative bullet must reference all three checks. Got: {section[:150]!r}"
    print("  T3 PASS: Alternative bullet includes FIRST, SECOND, and THIRD checks")

def test_payment_link_safety_strip():
    """T4: email_poller.py strips [PAYMENT_LINK] before booking smtp_send."""
    import email_poller
    source = inspect.getsource(email_poller.main)
    # Find the booking smtp_send section
    booking_send_idx = source.index("# Send Claude's reply for all booking sub-cases")
    smtp_idx = source.index("smtp_send(from_email", booking_send_idx)
    # The safety strip must be between the comment and the smtp_send
    between = source[booking_send_idx:smtp_idx]
    assert '[PAYMENT_LINK]' in between and '.replace(' in between, \
        f"Must strip [PAYMENT_LINK] before booking smtp_send. Got: {between!r}"
    print("  T4 PASS: [PAYMENT_LINK] safety strip before booking smtp_send")

def test_marina_agent_header():
    """T5: marina_agent.py file header says Brief 045."""
    import marina_agent
    source = inspect.getsource(marina_agent)
    assert "Brief 045" in source, "marina_agent.py header must reference Brief 045"
    print("  T5 PASS: marina_agent.py header updated to Brief 045")

def test_email_poller_header():
    """T6: email_poller.py file header says Brief 045."""
    import email_poller
    source = inspect.getsource(email_poller)
    assert "Brief 045" in source, "email_poller.py header must reference Brief 045"
    print("  T6 PASS: email_poller.py header updated to Brief 045")

if __name__ == "__main__":
    print("Running Brief 045 tests...")
    test_prompt_alternative_is_change()
    test_prompt_no_booking_confirmed_for_alternatives()
    test_prompt_rerun_checks_for_alternatives()
    test_payment_link_safety_strip()
    test_marina_agent_header()
    test_email_poller_header()
    print("\nAll 6 tests passed.")
