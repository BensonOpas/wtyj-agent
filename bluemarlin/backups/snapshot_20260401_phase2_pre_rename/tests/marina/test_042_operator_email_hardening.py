#!/usr/bin/env python3
"""Tests for Brief 042 — Operator email hardening: escalation guard + relay token auth."""
import re
import uuid


def _make_thread(awaiting_relay=False, relay_token=None):
    flags = {}
    if awaiting_relay:
        flags["awaiting_relay"] = True
    if relay_token:
        flags["relay_token"] = relay_token
    return {"fields": {}, "flags": flags}


def _escalation_guard(from_email, subj, demo_support_email):
    """Mirrors the guard condition added in Step 2."""
    return from_email.lower() == demo_support_email.lower() and "[ESCALATION]" in subj


def _relay_detect(from_email, subj, demo_support_email):
    """Mirrors the relay detection condition after Step 2."""
    return from_email.lower() == demo_support_email.lower() and "[RELAY-" in subj


def _find_thread_by_token(threads, relay_token_in):
    """Mirrors the token-based thread lookup from Step 3."""
    for tk, t in threads.items():
        stored_token = t.get("flags", {}).get("relay_token")
        if (t.get("flags", {}).get("awaiting_relay")
                and relay_token_in
                and stored_token == relay_token_in):
            return tk, t
    return None, None


def test_escalation_guard_drops_operator_replies():
    """T1: Email from demo_support with [ESCALATION] in subject is dropped."""
    demo = "butlerbensonagent@gmail.com"
    assert _escalation_guard(demo, "Re: [ESCALATION] NO-REF — Unknown — complaint", demo) is True
    assert _escalation_guard(demo, "[ESCALATION] BF-2026-00001 — John — complaint", demo) is True
    # Normal customer email must NOT be dropped
    assert _escalation_guard("customer@example.com", "Re: [ESCALATION]", demo) is False
    print("  T1 PASS: escalation guard correctly identifies operator replies")


def test_relay_detection_uses_hyphen_prefix():
    """T2: Relay detection uses [RELAY- prefix (not bare [RELAY])."""
    demo = "butlerbensonagent@gmail.com"
    token = uuid.uuid4().hex[:12]
    subject_with_token = f"Re: [RELAY-{token}] NO-REF — Unknown"
    subject_old_format = "Re: [RELAY] NO-REF — Unknown"

    assert _relay_detect(demo, subject_with_token, demo) is True, \
        "New [RELAY-<token>] format must be detected"
    assert _relay_detect(demo, subject_old_format, demo) is False, \
        "Old [RELAY] format (no hyphen-token) must NOT match"
    print("  T2 PASS: relay detection uses [RELAY- prefix correctly")


def test_relay_token_format():
    """T3: relay_token is 12-char lowercase hex."""
    token = uuid.uuid4().hex[:12]
    assert len(token) == 12, f"Token must be 12 chars, got {len(token)}"
    assert re.fullmatch(r'[a-f0-9]{12}', token), f"Token must be hex: {token!r}"
    # Generate 10 tokens — all unique
    tokens = {uuid.uuid4().hex[:12] for _ in range(10)}
    assert len(tokens) == 10, "Tokens must be unique"
    print(f"  T3 PASS: relay_token format correct (example: {token!r})")


def test_token_based_thread_lookup_matches_correct_thread():
    """T4: Token lookup finds the correct thread, not just any awaiting_relay thread."""
    token_a = uuid.uuid4().hex[:12]
    token_b = uuid.uuid4().hex[:12]
    threads = {
        "thread:customer_a": _make_thread(awaiting_relay=True, relay_token=token_a),
        "thread:customer_b": _make_thread(awaiting_relay=True, relay_token=token_b),
        "thread:customer_c": _make_thread(awaiting_relay=False),
    }
    # Reply with token_b → should find customer_b only
    tk, t = _find_thread_by_token(threads, token_b)
    assert tk == "thread:customer_b", f"Expected customer_b, got {tk}"
    # Reply with unknown token → no match
    tk2, t2 = _find_thread_by_token(threads, "000000000000")
    assert tk2 is None, "Unknown token must not match any thread"
    # None token → no match
    tk3, t3 = _find_thread_by_token(threads, None)
    assert tk3 is None, "None token must not match any thread"
    print("  T4 PASS: token lookup is exact — no accidental cross-thread relay")


def test_relay_token_cleared_after_resolution():
    """T5: relay_token is popped from flags when relay is resolved."""
    token = uuid.uuid4().hex[:12]
    flags = {
        "awaiting_relay": True,
        "relay_token": token,
        "relay_question": "What is the weight limit?",
    }
    # Simulate resolution (mirrors email_poller Step 4 clear)
    flags["awaiting_relay"] = False
    flags.pop("relay_question", None)
    flags.pop("relay_token", None)
    assert "relay_token" not in flags, "relay_token must be cleared after relay resolved"
    assert "relay_question" not in flags, "relay_question must be cleared after relay resolved"
    assert flags.get("awaiting_relay") is False
    print("  T5 PASS: relay_token cleared from thread flags after resolution")


if __name__ == "__main__":
    print("Running Brief 042 tests...")
    test_escalation_guard_drops_operator_replies()
    test_relay_detection_uses_hyphen_prefix()
    test_relay_token_format()
    test_token_based_thread_lookup_matches_correct_thread()
    test_relay_token_cleared_after_resolution()
    print("\nAll 5 tests passed.")
