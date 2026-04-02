# BRIEF 082 — Fix Semi-Escalation Relay + Revert Full Escalation Relay
**Status:** Approved | **Files:** `agents/marina/email_poller.py`, `agents/social/social_agent.py`, `tests/social/test_077_relay_bridge.py` | **Depends on:** 081 | **Blocks:** —

## Context
Two issues from live WhatsApp testing on 2026-03-13:

1. **Semi-escalation relay doesn't reformulate.** The WhatsApp relay handler (email_poller.py line 644) strips `awaiting_relay` and `relay_question` from the flags before calling marina_agent. Marina_agent has a RELAY MODE section (marina_agent.py line 64) that activates when `awaiting_relay=True` — it tells Claude to reformulate the operator's answer. By stripping the flag, marina_agent never enters relay mode. The operator's answer gets a random response instead of being reformulated.

2. **Full escalation should not have relay tokens.** Brief 081 Part B added relay tokens to full escalation. This was wrong — full escalation is one-way by design (operator contacts customer directly). Semi-escalation is the relay path (Marina relays the answer back). Need to revert Part B.

## Why This Approach
The relay handler filter was copy-pasted from the normal message handler (social_agent.py line 275) where stripping relay flags makes sense — you don't want normal messages to trigger relay mode. But inside the relay handler itself, those flags are exactly what marina_agent needs to enter RELAY MODE.

The full escalation revert restores the original Brief 077 design: semi = relay (two-way), full = notification (one-way).

## Source Material

### Relay handler filter — email_poller.py lines 643-646 (current, broken)
```python
                            _wa_agent_flags = dict(_wa_flags)
                            for _rk in ("awaiting_relay", "relay_token",
                                        "relay_question", "reply_times"):
                                _wa_agent_flags.pop(_rk, None)
```

### RELAY MODE in marina_agent.py lines 63-71 (needs `awaiting_relay=True` to activate)
```python
    relay_mode_section = ""
    if thread_flags.get("awaiting_relay"):
        relay_mode_section = (
            "\nRELAY MODE: A human team member has answered the customer's pending question. "
            "Their answer is in the INBOUND MESSAGE body below. "
            "Reformulate it in Marina's warm voice, using the same language the customer used. "
            "Do not add information the human did not provide. Do not make promises beyond what was stated. "
            "Set intents to [\"inquiry\"]. Do not set any booking or escalation flags.\n"
        )
```

### Full escalation handler — social_agent.py lines 542-589 (has relay tokens to revert)

### Escalation drop — email_poller.py lines 613-618 (narrowed in Brief 081, needs restoring)

### Test 2c (test_full_escalation_creates_relay_token) — needs removing
### Test 6 (test_full_escalation_inserts_notification) line 318 — needs reverting to `is None`

## Instructions

### Step 1 — Fix relay handler filter in email_poller.py

Change lines 643-646 from:
```python
                            _wa_agent_flags = dict(_wa_flags)
                            for _rk in ("awaiting_relay", "relay_token",
                                        "relay_question", "reply_times"):
                                _wa_agent_flags.pop(_rk, None)
```
to:
```python
                            _wa_agent_flags = dict(_wa_flags)
                            for _rk in ("relay_token", "reply_times"):
                                _wa_agent_flags.pop(_rk, None)
```

This keeps `awaiting_relay` and `relay_question` in the flags so marina_agent enters RELAY MODE.

### Step 2 — Revert full escalation relay tokens in social_agent.py

In the full escalation handler (Step 7.6), remove the 3 relay token lines (current lines 544-547):
```python
        # Generate relay token for WhatsApp escalations — allows operator reply-back
        _esc_relay_token = uuid.uuid4().hex[:12]
        flags["awaiting_relay"] = True
        flags["relay_token"] = _esc_relay_token
```
Delete these 4 lines entirely.

### Step 3 — Revert escalation subject in social_agent.py

Change line 572-574 from:
```python
        _esc_subject = (
            f"[RELAY-{_esc_relay_token}] [ESCALATION] {_esc_ref} - {_cname} "
            f"(WhatsApp: {phone}) - {_esc_intents}")
```
to:
```python
        _esc_subject = (
            f"[ESCALATION] {_esc_ref} - {_cname} "
            f"(WhatsApp: {phone}) - {_esc_intents}")
```

### Step 4 — Remove relay instructions from escalation body in social_agent.py

Remove the relay instructions from the escalation body. Change lines 583-585 from:
```python
            f"{result.get('internal_note', '')}"
            f"\n\nINSTRUCTIONS: Reply to this email with your answer.\n"
            f"Marina will relay it to the customer in her own words."
```
to:
```python
            f"{result.get('internal_note', '')}"
```

### Step 5 — Revert notification creation in social_agent.py

Change lines 587-589 from:
```python
        state_registry.create_pending_notification(
            'escalation', 'whatsapp', phone, _cname,
            _esc_subject, _esc_body, relay_token=_esc_relay_token)
```
to:
```python
        state_registry.create_pending_notification(
            'escalation', 'whatsapp', phone, _cname,
            _esc_subject, _esc_body)
```

### Step 6 — Restore original escalation drop in email_poller.py

Change lines 613-618 from:
```python
                # Drop operator replies to [ESCALATION] alerts without relay token — one-way flow
                if (from_email.lower() == demo_support_email.lower()
                        and "[ESCALATION]" in subj and "[RELAY-" not in subj):
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    log(f"Dropped escalation reply from {from_email} — no relay token, one-way flow")
                    continue
```
to:
```python
                # Drop operator replies to [ESCALATION] alerts — escalation is one-way
                if from_email.lower() == demo_support_email.lower() and "[ESCALATION]" in subj:
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    log(f"Dropped escalation reply from {from_email} — one-way flow")
                    continue
```

### Step 7 — Remove `fully_escalated` clearing from relay handler

Remove line 661 from email_poller.py:
```python
                            _wa_flags.pop("fully_escalated", None)
```

This was added for full escalation relay which we're reverting. Semi-escalation doesn't set `fully_escalated`, so this line is dead code.

### Step 8 — Update tests

**Remove test 2c** (`test_full_escalation_creates_relay_token`, lines 126-156) — this test validates the wrong design (relay tokens on full escalation).

**Revert test 6** (`test_full_escalation_inserts_notification`, lines 317-319) from:
```python
    assert match[0]["relay_token"] is not None
    assert len(match[0]["relay_token"]) == 12
```
to:
```python
    assert match[0]["relay_token"] is None
```

## Tests

```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin && python3 -m pytest tests/social/test_077_relay_bridge.py -v
```

Expected: 11/11 pass (12 current minus 1 removed).

Full regression:
```bash
python3 -m pytest tests/social/ -v
```

Expected: 103/103 pass (104 current minus 1 removed).

## Success Condition
All 103 social tests pass. Semi-escalation relay handler keeps `awaiting_relay` in flags so marina_agent enters RELAY MODE. Full escalation is one-way with no relay token.

## Rollback
Revert changes to email_poller.py, social_agent.py, and test_077_relay_bridge.py.
