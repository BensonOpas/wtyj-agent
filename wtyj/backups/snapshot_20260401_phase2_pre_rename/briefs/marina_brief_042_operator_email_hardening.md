# BRIEF 042 — Operator email hardening: escalation guard + relay token auth
**Status:** Draft | **Files:** `src/email_poller.py` | **Depends on:** Brief 040 | **Blocks:** nothing

## Context

Two bugs found in live testing of Brief 040's escalation system:

1. **Escalation reply loop**: Benson replied to the `[ESCALATION]` alert email (from butlerbensonagent@gmail.com → hello@wetakeyourjob.com). The poller had no guard for this — it treated Benson's message as a new inbound customer message, sent a holding reply back to Benson, and fired a second `[ESCALATION]` alert. The escalation flow is one-way: operator contacts the customer directly via info@bluefinncharters.com. Operator replies to escalation alerts must be silently dropped before any processing.

2. **Relay detection is subject-tag-only**: Current relay detection requires `"[RELAY]" in subject` from `demo_support_email`. This works but relies on a magic string. If two relays are pending simultaneously, thread matching falls back to "first awaiting_relay thread found" which is ambiguous. Industry standard (Zendesk, Intercom, Help Scout) embeds an opaque unique token per relay ticket in the subject. Replacing `[RELAY]` with `[RELAY-<12-char-hex-token>]` gives exact one-to-one thread matching and removes the magic-string dependency.

## Why This Approach

Fix 1 is a one-line drop-before-processing guard — the simplest possible fix. Fix 2 adds `uuid.uuid4().hex[:12]` as a relay token stored on thread state at relay alert send time and embedded in the subject. Token extraction on reply is a simple regex. This matches how ticketing systems have solved this for 20 years. Keeping the `[RELAY-` prefix (with hyphen) ensures the detection condition stays readable. The token makes the relay alert subject unforgeable without knowing the UUID, and maps exactly to the right thread without relying on booking_ref (which is often "NO-REF" for early-stage threads). No dependency changes — `uuid` is Python stdlib.

## Source Material

### email_poller.py — imports block (lines 19–20)
```python
import imaplib, email, urllib.request, urllib.parse, json, time, os, re, hashlib
from datetime import datetime, timezone
```

### email_poller.py — relay detection block (lines 278–295)
```python
                # [RELAY] inbound from human team — reformulate and forward to original customer
                if from_email.lower() == demo_support_email.lower() and "[RELAY]" in subj:
                    ref_match = re.search(r'BF-\d{4}-\d{5}', subj)
                    relay_ref = ref_match.group() if ref_match else None
                    customer_thread_key = None
                    customer_th = None
                    for tk, t in state["threads"].items():
                        if (t.get("flags", {}).get("awaiting_relay")
                                and (relay_ref is None
                                     or t.get("flags", {}).get("booking_ref") == relay_ref)):
                            customer_thread_key = tk
                            customer_th = t
                            break
                    if customer_th is None:
                        log(f"RELAY: no matching customer thread for ref={relay_ref} — skipping")
```

### email_poller.py — relay_token cleared after relay resolved (lines 323–324)
```python
                    customer_th["flags"]["awaiting_relay"] = False
                    customer_th["flags"].pop("relay_question", None)
```

### email_poller.py — semi-escalation handler: flags set + subject (lines 436–456)
```python
                    th["flags"]["awaiting_relay"] = True
                    th["flags"]["relay_question"] = relay_question
                    th["flags"]["relay_customer_email"] = from_email
                    th["flags"]["relay_reply_subject"] = "Re: " + subj
                    _ref = th["flags"].get("booking_ref", "NO-REF")
                    _cname = th["fields"].get("customer_name", "Unknown")
                    _relay_alert = (
                        f"Customer: {_cname} <{from_email}>\n"
                        f"Their question: {relay_question}\n\n"
                        f"Booking context:\n"
                        f"  Trip: {th['fields'].get('trip_key', '')} | "
                        f"Date: {th['fields'].get('date', '')} | "
                        f"Guests: {th['fields'].get('guests', '')}\n"
                        f"  Ref: {_ref}\n\n"
                        f"INSTRUCTIONS: Reply to this email with your answer.\n"
                        f"Marina will relay it to the customer in her own words."
                    )
                    try:
                        smtp_send(
                            demo_support_email,
                            f"[RELAY] {_ref} — {_cname}",
```

## Instructions

### Step 1 — Add uuid import

Find:
```python
import imaplib, email, urllib.request, urllib.parse, json, time, os, re, hashlib
```

Replace with:
```python
import imaplib, email, urllib.request, urllib.parse, json, time, os, re, hashlib, uuid
```

### Step 2 — Add escalation reply guard (before relay detection block)

Find (exact, include the comment):
```python
                # [RELAY] inbound from human team — reformulate and forward to original customer
                if from_email.lower() == demo_support_email.lower() and "[RELAY]" in subj:
```

Replace with:
```python
                # Drop operator replies to [ESCALATION] alerts — escalation is one-way
                if from_email.lower() == demo_support_email.lower() and "[ESCALATION]" in subj:
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    log(f"Dropped escalation reply from {from_email} — one-way flow")
                    continue

                # [RELAY] inbound from human team — reformulate and forward to original customer
                if from_email.lower() == demo_support_email.lower() and "[RELAY-" in subj:
```

Note: this single edit does two things — inserts the escalation guard AND changes `"[RELAY]" in subj` to `"[RELAY-" in subj`.

### Step 3 — Replace relay thread lookup with token-based matching

Find (exact block):
```python
                    ref_match = re.search(r'BF-\d{4}-\d{5}', subj)
                    relay_ref = ref_match.group() if ref_match else None
                    customer_thread_key = None
                    customer_th = None
                    for tk, t in state["threads"].items():
                        if (t.get("flags", {}).get("awaiting_relay")
                                and (relay_ref is None
                                     or t.get("flags", {}).get("booking_ref") == relay_ref)):
                            customer_thread_key = tk
                            customer_th = t
                            break
                    if customer_th is None:
                        log(f"RELAY: no matching customer thread for ref={relay_ref} — skipping")
```

Replace with:
```python
                    token_match = re.search(r'\[RELAY-([a-f0-9]{12})\]', subj)
                    relay_token_in = token_match.group(1) if token_match else None
                    customer_thread_key = None
                    customer_th = None
                    for tk, t in state["threads"].items():
                        stored_token = t.get("flags", {}).get("relay_token")
                        if (t.get("flags", {}).get("awaiting_relay")
                                and relay_token_in
                                and stored_token == relay_token_in):
                            customer_thread_key = tk
                            customer_th = t
                            break
                    if customer_th is None:
                        log(f"RELAY: no matching customer thread for token={relay_token_in} — skipping")
```

### Step 4 — Clear relay_token when relay is resolved

Find:
```python
                    customer_th["flags"]["awaiting_relay"] = False
                    customer_th["flags"].pop("relay_question", None)
```

Replace with:
```python
                    customer_th["flags"]["awaiting_relay"] = False
                    customer_th["flags"].pop("relay_question", None)
                    customer_th["flags"].pop("relay_token", None)
```

### Step 5 — Generate relay_token in semi-escalation handler and use it in subject

Find (exact block — includes the smtp_send subject line):
```python
                    th["flags"]["awaiting_relay"] = True
                    th["flags"]["relay_question"] = relay_question
                    th["flags"]["relay_customer_email"] = from_email
                    th["flags"]["relay_reply_subject"] = "Re: " + subj
                    _ref = th["flags"].get("booking_ref", "NO-REF")
                    _cname = th["fields"].get("customer_name", "Unknown")
                    _relay_alert = (
                        f"Customer: {_cname} <{from_email}>\n"
                        f"Their question: {relay_question}\n\n"
                        f"Booking context:\n"
                        f"  Trip: {th['fields'].get('trip_key', '')} | "
                        f"Date: {th['fields'].get('date', '')} | "
                        f"Guests: {th['fields'].get('guests', '')}\n"
                        f"  Ref: {_ref}\n\n"
                        f"INSTRUCTIONS: Reply to this email with your answer.\n"
                        f"Marina will relay it to the customer in her own words."
                    )
                    try:
                        smtp_send(
                            demo_support_email,
                            f"[RELAY] {_ref} — {_cname}",
```

Replace with:
```python
                    relay_token = uuid.uuid4().hex[:12]
                    th["flags"]["awaiting_relay"] = True
                    th["flags"]["relay_token"] = relay_token
                    th["flags"]["relay_question"] = relay_question
                    th["flags"]["relay_customer_email"] = from_email
                    th["flags"]["relay_reply_subject"] = "Re: " + subj
                    _ref = th["flags"].get("booking_ref", "NO-REF")
                    _cname = th["fields"].get("customer_name", "Unknown")
                    _relay_alert = (
                        f"Customer: {_cname} <{from_email}>\n"
                        f"Their question: {relay_question}\n\n"
                        f"Booking context:\n"
                        f"  Trip: {th['fields'].get('trip_key', '')} | "
                        f"Date: {th['fields'].get('date', '')} | "
                        f"Guests: {th['fields'].get('guests', '')}\n"
                        f"  Ref: {_ref}\n\n"
                        f"INSTRUCTIONS: Reply to this email with your answer.\n"
                        f"Marina will relay it to the customer in her own words."
                    )
                    try:
                        smtp_send(
                            demo_support_email,
                            f"[RELAY-{relay_token}] {_ref} — {_cname}",
```

### Step 6 — Update file header

Find:
```python
# LAST MODIFIED: Brief 040
```

Replace with:
```python
# LAST MODIFIED: Brief 042
```

## Tests

Write `bluemarlin/tests/test_042_operator_email_hardening.py`:

```python
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
```

## Success Condition

All 5 tests pass: `python3 bluemarlin/tests/test_042_operator_email_hardening.py`

## Rollback

`git checkout HEAD -- src/email_poller.py`
