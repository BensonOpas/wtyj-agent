#!/usr/bin/env python3
"""Tests for Brief 043 — Fix relay detection + poisoned relay bug."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from email.header import make_header, Header


def test_decode_subj_rfc2047():
    """T1: _decode_subj correctly decodes RFC 2047 encoded [RELAY-token] subject."""
    from email_poller import _decode_subj
    # Simulate what Gmail does: encode the subject as UTF-8 RFC 2047
    raw = str(Header("[RELAY-d820b609f103] NO-REF - Unknown", "utf-8"))
    decoded = _decode_subj(raw)
    assert "[RELAY-d820b609f103]" in decoded, (
        f"Decoded subject must contain [RELAY-token]. Got: {decoded!r}"
    )
    assert "[RELAY-" in decoded, f"Must contain [RELAY- prefix. Got: {decoded!r}"
    print(f"  T1 PASS: RFC 2047 subject decoded correctly")
    print(f"         raw:     {raw!r}")
    print(f"         decoded: {decoded!r}")


def test_decode_subj_plain_ascii():
    """T2: _decode_subj passes through plain ASCII subjects unchanged."""
    from email_poller import _decode_subj
    plain = "Re: Jet ski question"
    assert _decode_subj(plain) == plain, "Plain ASCII must pass through unchanged"
    assert _decode_subj("") == "", "Empty string must return empty"
    assert _decode_subj(None) == "", "None must return empty"
    print("  T2 PASS: plain ASCII subjects pass through unchanged")


def test_relay_detection_on_decoded_subject():
    """T3: Relay detection condition matches on decoded RFC 2047 subject."""
    from email_poller import _decode_subj
    raw_encoded = str(Header("Re: [RELAY-abc123def456] NO-REF - Unknown", "utf-8"))
    subj = _decode_subj(raw_encoded)
    demo = "butlerbensonagent@gmail.com"
    from_email = "butlerbensonagent@gmail.com"
    # Simulate the detection condition from email_poller
    assert from_email.lower() == demo.lower() and "[RELAY-" in subj, (
        f"Relay detection must match on decoded subject. subj={subj!r}"
    )
    print("  T3 PASS: relay detection matches on decoded RFC 2047 subject")


def test_escalation_guard_on_decoded_subject():
    """T4: Escalation guard matches on decoded RFC 2047 subject."""
    from email_poller import _decode_subj
    raw_encoded = str(Header("Re: [ESCALATION] NO-REF - Unknown - complaint", "utf-8"))
    subj = _decode_subj(raw_encoded)
    demo = "butlerbensonagent@gmail.com"
    from_email = "butlerbensonagent@gmail.com"
    assert from_email.lower() == demo.lower() and "[ESCALATION]" in subj, (
        f"Escalation guard must match on decoded subject. subj={subj!r}"
    )
    print("  T4 PASS: escalation guard matches on decoded RFC 2047 subject")


def test_step1_strips_relay_flags():
    """T5: Verify email_poller Step 1 call site strips relay flags."""
    import email_poller
    import inspect
    source = inspect.getsource(email_poller.main)
    # The Step 1 block must contain agent_flags with relay stripping
    assert "agent_flags = dict(th.get" in source, \
        "Step 1 must create agent_flags copy"
    assert "agent_flags.pop(_rk, None)" in source or "agent_flags.pop(" in source, \
        "Step 1 must pop relay keys from agent_flags"
    # The process_message call in Step 1 must pass agent_flags
    step1_idx = source.index("# Step 1: Call marina_agent")
    step2_idx = source.index("# Step 2: Merge fields")
    step1_block = source[step1_idx:step2_idx]
    pm_idx = step1_block.index("marina_agent.process_message")
    pm_section = step1_block[pm_idx:pm_idx + 200]
    assert "agent_flags" in pm_section, \
        f"Step 1 process_message must use agent_flags. Got: {pm_section[:100]!r}"
    print("  T5 PASS: Step 1 call site strips relay flags from marina_agent input")


def test_fully_escalated_strips_relay_flags():
    """T6: Verify fully_escalated guard also strips relay flags."""
    import email_poller
    import inspect
    source = inspect.getsource(email_poller.main)
    esc_idx = source.index("# Fully escalated guard")
    step1_idx = source.index("# Step 1: Call marina_agent")
    esc_block = source[esc_idx:step1_idx]
    assert "_esc_flags = dict(th.get" in esc_block, \
        "Fully escalated guard must create _esc_flags copy"
    assert 'th.get("flags", {})' not in esc_block.split("marina_agent.process_message")[1].split(")")[0], \
        "Fully escalated guard must use _esc_flags, not th.get('flags') directly"
    print("  T6 PASS: fully_escalated guard strips relay flags from marina_agent input")


if __name__ == "__main__":
    print("Running Brief 043 tests...")
    test_decode_subj_rfc2047()
    test_decode_subj_plain_ascii()
    test_relay_detection_on_decoded_subject()
    test_escalation_guard_on_decoded_subject()
    test_step1_strips_relay_flags()
    test_fully_escalated_strips_relay_flags()
    print("\nAll 6 tests passed.")
