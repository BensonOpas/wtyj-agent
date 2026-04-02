# BRIEF 043 — Fix relay detection + poisoned relay bug
**Status:** Draft | **Files:** `src/email_poller.py` | **Depends on:** Brief 042 | **Blocks:** nothing

## Context

Live testing of the relay round-trip revealed two bugs:

1. **Relay detection fails on RFC 2047 encoded subjects.** VPS logs prove it: Benson's relay reply arrived with subject `=?utf-8?q?Re:_[RELAY-d820b609f103]...?=` but the check `"[RELAY-" in subj` failed because Python's legacy `email.message_from_bytes()` does NOT auto-decode RFC 2047 headers. `msg.get("Subject", "")` returns the raw encoded string. The relay handler never fired. Marina processed the reply as a normal customer message and replied to butlerbensonagent@gmail.com instead of the actual customer.

2. **Poisoned relay: customer re-email on `awaiting_relay` thread triggers relay mode.** When a customer sends another message while `awaiting_relay: true` on the thread, `_build_prompt()` in marina_agent.py injects the RELAY MODE section (line 64). Marina treats the customer's new message as the relay answer from the team and generates a garbled response. The fix is in email_poller.py: strip relay flags from the copy passed to marina_agent for non-relay messages. marina_agent.py is not touched.

## Why This Approach

Fix 1: decoding the subject once at read time (line 213) fixes all downstream uses — relay detection, escalation guard, normalize_subject, thread key, logging. No per-check decoding needed. `email.header.decode_header` is stdlib (`from email.header import decode_header`).

Fix 2: stripping relay flags from the copy passed to marina_agent is minimal and surgical. The relay handler already passes `customer_th.get("flags", {})` directly for actual relay messages — that path still works. The thread state itself is NOT mutated, only the copy sent to marina_agent. This avoids touching marina_agent.py or changing the RELAY MODE prompt logic.

## Source Material

### email_poller.py — imports (lines 19–21)
```python
import imaplib, email, urllib.request, urllib.parse, json, time, os, re, hashlib, uuid
from datetime import datetime, timezone
from email.utils import parseaddr
```

### email_poller.py — subject read (line 213)
```python
                subj = msg.get("Subject", "") or ""
```

### email_poller.py — helpers section start (lines 58–60)
```python
# ========= HELPERS =========
def log(msg):
    print(msg, flush=True)
```

### email_poller.py — Step 1 marina_agent call (lines 367–371)
```python
                # Step 1: Call marina_agent (single Claude call per message)
                result = marina_agent.process_message(
                    from_email, subj, body,
                    th.get("fields", {}), th.get("flags", {})
                )
```

## Instructions

### Step 1 — Add decode_header import

Find:
```python
from email.utils import parseaddr
```

Replace with:
```python
from email.utils import parseaddr
from email.header import decode_header as _decode_header
```

### Step 2 — Add _decode_subj helper

Find (exact):
```python
# ========= HELPERS =========
def log(msg):
    print(msg, flush=True)
```

Replace with:
```python
# ========= HELPERS =========
def _decode_subj(raw):
    parts = []
    for data, charset in _decode_header(raw or ""):
        if isinstance(data, bytes):
            parts.append(data.decode(charset or "utf-8", errors="ignore"))
        else:
            parts.append(data)
    return "".join(parts)

def log(msg):
    print(msg, flush=True)
```

### Step 3 — Use _decode_subj at line 213

Find:
```python
                subj = msg.get("Subject", "") or ""
```

Replace with:
```python
                subj = _decode_subj(msg.get("Subject", ""))
```

### Step 4a — Strip relay flags before fully_escalated marina_agent call

Find:
```python
                # Fully escalated guard — still calls marina_agent (one Claude call), skip booking flow
                if th["flags"].get("fully_escalated"):
                    result = marina_agent.process_message(
                        from_email, subj, body,
                        th.get("fields", {}), th.get("flags", {})
                    )
```

Replace with:
```python
                # Fully escalated guard — still calls marina_agent (one Claude call), skip booking flow
                if th["flags"].get("fully_escalated"):
                    _esc_flags = dict(th.get("flags", {}))
                    for _rk in ("awaiting_relay", "relay_token", "relay_question",
                                "relay_customer_email", "relay_reply_subject"):
                        _esc_flags.pop(_rk, None)
                    result = marina_agent.process_message(
                        from_email, subj, body,
                        th.get("fields", {}), _esc_flags
                    )
```

### Step 4b — Strip relay flags before marina_agent Step 1 call

Find:
```python
                # Step 1: Call marina_agent (single Claude call per message)
                result = marina_agent.process_message(
                    from_email, subj, body,
                    th.get("fields", {}), th.get("flags", {})
                )
```

Replace with:
```python
                # Step 1: Call marina_agent (single Claude call per message)
                agent_flags = dict(th.get("flags", {}))
                for _rk in ("awaiting_relay", "relay_token", "relay_question",
                            "relay_customer_email", "relay_reply_subject"):
                    agent_flags.pop(_rk, None)
                result = marina_agent.process_message(
                    from_email, subj, body,
                    th.get("fields", {}), agent_flags,
                )
```

### Step 5 — Update file header

Find:
```python
# LAST MODIFIED: Brief 042
```

Replace with:
```python
# LAST MODIFIED: Brief 043
```

## Tests

Write `bluemarlin/tests/test_043_relay_detection_fixes.py`:

```python
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
    # Must NOT pass th.get("flags") directly to marina_agent in Step 1
    # (The only remaining direct th.get("flags") should be in the relay handler)
    step1_idx = source.index("# Step 1: Call marina_agent")
    step2_idx = source.index("# Step 2: Merge fields")
    step1_block = source[step1_idx:step2_idx]
    assert 'th.get("flags", {})' not in step1_block, \
        "Step 1 must use agent_flags, not th.get('flags') directly"
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
```

## Success Condition

All 6 tests pass: `python3 bluemarlin/tests/test_043_relay_detection_fixes.py`

## Rollback

`git checkout HEAD -- src/email_poller.py`
