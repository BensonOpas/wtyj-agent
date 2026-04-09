# BRIEF 176 — Marina context-aware fallback reply (API-failure path)
**Status:** Draft | **Files:** marina_agent.py, test_176 (new) | **Depends on:** 174 | **Blocks:** —

## Context

Third and final brief in the ash9772-triggered sequence. Brief 174 structurally eliminated the parser failure mode that stuck Anne-Sophie's email thread (tool use migration). Brief 175 fixed the semantic "next Saturday" date misinterpretation. Brief 176 addresses the THIRD issue from the research report: **when Marina DOES fall back (now only on genuine API-level failures — rate limit, timeout, Anthropic outage), her fallback reply ignores `thread_fields` and gaslights returning customers.**

Current fallback reply at `wtyj/agents/marina/marina_agent.py:789-808`:

```python
fallback = {
    "intents": ["inquiry"],
    "fields": {},
    "confidence": "low",
    "reply": (
        f"Hi! Could you let me know which {_svc_label} you're looking at, "
        f"what date works, and how many {_party_label}? I'll get you sorted "
        f"from there.\n\n"
        f"Warm regards,\n{signature}"
    ),
    ...
}
if channel == "whatsapp":
    fallback["reply"] = "Sorry, could you send that again? I missed it."
```

For a FIRST-CONTACT customer (empty `thread_fields`), this is fine. For a returning customer who has already provided name / guests / service / date, the reply is maddening because it pretends nothing was ever said. Anne-Sophie saw this three times in a row on her email thread — she told Marina "Klein Curacao, 7 people, next Saturday", Marina responded "Could you let me know which service, date, guests?". On the third round, Anne-Sophie wrote *"I told you two times"* then stopped replying.

After Brief 174, the parser-failure path is gone. But the fallback STILL fires in two real scenarios:
1. Anthropic API timeout (network blip between VPS and Anthropic)
2. Anthropic API exception (auth error, rate limit, model outage)
3. The defensive guard in Brief 174's new code path (tool_use block missing — should never happen with `tool_choice` forced, but defensive)

All three are rare but real. When they DO fire, the fallback should acknowledge what Marina already knows from the thread context instead of asking for everything from scratch.

**This is a Rule 3 accepted exception** (documented in `CLAUDE.md:149-155` under KNOWN OPEN ISSUES: *"Email fallback reply in marina_agent.py is a hardcoded string — accepted Rule 3 exception for API failure path only."*). Enhancing the fallback stays within that exception because it's still an API-failure-only path; the enhancement is smarter template logic, not a new static reply path for normal operation.

## Why This Approach

**Chosen — helper function `_build_contextual_fallback_reply(thread_fields, channel, signature, svc_label, party_label)` that reads `thread_fields` and assembles a reply acknowledging what's known and asking only for what's missing.**

Behavior examples:

| thread_fields state | Channel | Reply |
|---|---|---|
| `{}` (first contact) | email | Current behavior (unchanged) — ask for service, date, guests |
| `{customer_name: "Alice"}` | email | "Sorry Alice, I had a brief hiccup on my end. Could you let me know which service you're looking at, what date, and how many guests?" |
| `{customer_name: "Alice", guests: 7}` | email | "Sorry Alice, I had a brief hiccup on my end. I have you as a group of 7 — could you remind me which service and what date?" |
| `{customer_name: "Alice", guests: 7, service_name: "Klein Curaçao"}` | email | "Sorry Alice, I had a brief hiccup on my end. I have you as a group of 7 for Klein Curaçao — could you remind me what date works?" |
| `{customer_name: "Alice", guests: 7, service_name: "Klein Curaçao", date: "2026-04-11"}` | email | "Sorry Alice, I had a brief hiccup on my end. Could you resend your last message? I have your Klein Curaçao booking for 7 on April 11 on file." |
| `{}` | whatsapp | Current: "Sorry, could you send that again? I missed it." (unchanged) |
| `{customer_name: "Alice", guests: 7}` | whatsapp | "Sorry, had a hiccup. I've got you as 7 for the trip — which service and what date?" |

Key principles:
1. **Acknowledge the hiccup.** The word "hiccup" or "brief issue" signals "this is my fault, not yours".
2. **Use the customer's name when known.** Personal acknowledgment reduces the robot feel.
3. **Only ask for missing pieces.** Never re-ask what's already in `thread_fields`.
4. **WhatsApp stays terse** (under 40 words). Email can be slightly longer but still concise.
5. **If ALL fields are present**, don't ask the customer to restate — acknowledge the full context and ask them to resend their LAST message (the one that triggered the fallback).
6. **Still static template logic.** Marina doesn't call Claude from the fallback path. The whole point of a fallback is that Claude is unavailable.

**Rejected — call Marina again with a different prompt on fallback.**
- Adds a Claude API call inside the failure handler — if the first call failed from rate limit / outage, the second will too.
- Violates Rule 1 (one Claude call per inbound message).
- Doubles latency on the exact scenarios that are already slow (API issues).

**Rejected — store the last-successful reply and retransmit.**
- The last successful reply may not be relevant to the current customer message.
- Adds state management to the fallback path.
- Doesn't actually acknowledge that the CURRENT message failed.

**Rejected — skip the fallback entirely and let the customer resend.**
- Customer sees Marina silent. Worse UX than a fallback.
- Breaks the existing "Marina always replies" guarantee.

## Instructions

### Step 1: Add `_build_contextual_fallback_reply` helper in `marina_agent.py`

**File:** `wtyj/agents/marina/marina_agent.py`

Add a new helper function at module level, right before the `process_message` function definition (around line 772). This keeps it visible near the code that uses it.

```python
def _build_contextual_fallback_reply(
    thread_fields: dict,
    channel: str,
    signature: str,
    svc_label: str,
    party_label: str,
) -> str:
    """Brief 176: construct the fallback reply based on what Marina already knows
    about this customer from the current thread state. Used ONLY on API-level
    failures (timeout, rate limit, Anthropic outage, defensive guard) — not in
    the normal Claude-succeeds path. Rule 3 accepted exception (documented in
    CLAUDE.md KNOWN OPEN ISSUES).

    Principles:
    - Acknowledge the hiccup (not the customer's fault)
    - Use the customer's name when known
    - Only ask for missing fields (name / guests / service / date)
    - WhatsApp stays under 40 words; email can be slightly longer
    - If all fields present, acknowledge the full context and ask the customer
      to resend their last message (the one that triggered the fallback)
    """
    fields = thread_fields or {}
    name = (fields.get("customer_name") or "").strip()
    guests = fields.get("guests")
    service = (fields.get("service_name") or "").strip()
    date = (fields.get("date") or "").strip()

    has_name = bool(name)
    has_guests = bool(guests)
    has_service = bool(service)
    has_date = bool(date)

    # Build "known" phrase for the parts Marina already has
    known_parts = []
    if has_guests and has_service:
        known_parts.append(f"you as a group of {guests} for {service}")
    elif has_guests:
        known_parts.append(f"you as a group of {guests}")
    elif has_service:
        known_parts.append(f"the {service} booking")
    if has_date:
        if known_parts:
            known_parts[-1] = known_parts[-1] + f" on {date}"
        else:
            known_parts.append(f"a booking for {date}")
    known_str = " and ".join(known_parts)

    # Build "missing" list — the fields Marina needs
    missing_parts = []
    if not has_service:
        missing_parts.append(f"which {svc_label} you're looking at")
    if not has_date:
        missing_parts.append("what date works")
    if not has_guests:
        missing_parts.append(f"how many {party_label}")
    missing_str = " and ".join(missing_parts)

    name_prefix = f"{name}, " if has_name else ""

    if channel == "whatsapp":
        # Under 40 words, no signature
        if not known_parts and not missing_parts:
            return f"Sorry{', ' + name if has_name else ''}, had a brief hiccup. Could you resend your last message?"
        if not missing_parts:
            # Full context — just ask to resend
            return f"Sorry {name_prefix}had a brief hiccup. I have {known_str} on file — could you resend your last message?"
        if not known_parts:
            return f"Sorry {name_prefix}had a hiccup. Could you let me know {missing_str}?"
        return f"Sorry {name_prefix}had a hiccup. I've got {known_str} — could you remind me {missing_str}?"

    # Email — slightly longer, signed
    signoff = f"\n\nWarm regards,\n{signature}"
    if not known_parts and not missing_parts:
        return (
            f"Hi{' ' + name if has_name else ''},\n\n"
            f"Sorry, I had a brief hiccup on my end — could you resend your "
            f"last message and I'll get right back to you?{signoff}"
        )
    if not missing_parts:
        # Full context — ask to resend the last message
        return (
            f"Hi{' ' + name if has_name else ''},\n\n"
            f"Sorry, I had a brief hiccup on my end. I have {known_str} on "
            f"file — could you resend your last message so I can pick up "
            f"where we left off?{signoff}"
        )
    if not known_parts:
        # No context yet — classic first-contact reply
        return (
            f"Hi{' ' + name if has_name else ''}! Could you let me know "
            f"{missing_str}? I'll get you sorted from there.{signoff}"
        )
    return (
        f"Hi {name_prefix}sorry for the brief hiccup on my end. I have "
        f"{known_str} — could you remind me {missing_str}?{signoff}"
    )
```

### Step 2: Wire the helper into `process_message`'s fallback construction

**File:** `wtyj/agents/marina/marina_agent.py`

Replace the existing fallback dict construction (currently at around lines 789-808). Find:

```python
    fallback = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "low",
        "reply": (
            f"Hi! Could you let me know which {_svc_label} you're looking at, "
            f"what date works, and how many {_party_label}? I'll get you sorted "
            f"from there.\n\n"
            f"Warm regards,\n{signature}"
        ),
        "clarifications_needed": ["date", _party_label, "service_name"],
        "requires_human": False,
        "flags": {},
        "internal_note": "Fallback response — Claude API call failed or returned unparseable output.",
    }
    if channel == "whatsapp":
        # ⚠️  HARDCODED FALLBACK — Rule 3 accepted exception (API failure path only)
        # If agent name changes from "Marina", update this message.
        # See also: email fallback above (lines 459-473) — same exception.
        fallback["reply"] = "Sorry, could you send that again? I missed it."
```

Replace with:

```python
    # Brief 176: context-aware fallback — acknowledges what thread_fields
    # already contains instead of gaslighting returning customers with a
    # generic first-contact reply. Rule 3 accepted exception (API failure
    # path only). See _build_contextual_fallback_reply docstring.
    _fallback_reply = _build_contextual_fallback_reply(
        thread_fields=thread_fields,
        channel=channel,
        signature=signature,
        svc_label=_svc_label,
        party_label=_party_label,
    )
    fallback = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "low",
        "reply": _fallback_reply,
        "clarifications_needed": ["date", _party_label, "service_name"],
        "requires_human": False,
        "flags": {},
        "internal_note": "Fallback response — Claude API call failed or returned unparseable output.",
    }
```

The `if channel == "whatsapp":` override block gets DELETED — the helper handles both channels natively.

**CRITICAL:** Brief 174's tests (`test_174_tool_use.py::test_process_message_falls_back_on_empty_reply`, `test_process_message_falls_back_on_anthropic_exception`, `test_process_message_falls_back_when_no_tool_use_block`) and `test_marina_tone.py::test_response_empty_reply_returns_fallback` assert on `result["internal_note"] == "Fallback response — Claude API call failed or returned unparseable output."`. This field MUST stay unchanged in the new fallback dict — do not alter the `internal_note` string. Verify by running those specific tests after the edit.

### Step 3: Tests

**File:** `wtyj/tests/marina/test_176_contextual_fallback.py` (new)

Five tests covering the realistic `thread_fields` states. Each test calls the helper DIRECTLY (not through `process_message`) with different field combinations and verifies the output structure.

```python
"""Tests for Brief 176 — Marina context-aware fallback reply."""
import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from agents.marina import marina_agent


# Common args for the helper
def _call(thread_fields, channel="email"):
    return marina_agent._build_contextual_fallback_reply(
        thread_fields=thread_fields,
        channel=channel,
        signature="Marina\nBlueMarlin Charters",
        svc_label="trip",
        party_label="guests",
    )


def test_fallback_empty_fields_email_is_first_contact():
    """Brief 176: empty thread_fields on email → classic first-contact reply."""
    reply = _call({})
    # Should NOT acknowledge any "known" details
    assert "I have" not in reply
    assert "I've got" not in reply
    # Should ask for the missing info
    assert "trip" in reply.lower()
    assert "date" in reply.lower()
    assert "guests" in reply.lower()
    # Has a signature
    assert "Marina" in reply


def test_fallback_partial_fields_email_acknowledges_known():
    """Brief 176: partial fields → acknowledge known, ask for missing."""
    reply = _call({
        "customer_name": "Alice",
        "guests": 7,
        "service_name": "Klein Curaçao",
    })
    # Acknowledges the customer name
    assert "Alice" in reply
    # Acknowledges guests + service
    assert "7" in reply
    assert "Klein Curaçao" in reply
    # Still asks for the missing date
    assert "date" in reply.lower()
    # Does NOT re-ask for service or guests (they're already known)
    assert "which trip" not in reply.lower()
    assert "how many guests" not in reply.lower()


def test_fallback_all_fields_email_asks_to_resend():
    """Brief 176: all fields known → don't re-ask anything; ask to resend last message."""
    reply = _call({
        "customer_name": "Alice",
        "guests": 7,
        "service_name": "Klein Curaçao",
        "date": "2026-04-11",
    })
    # Acknowledges everything
    assert "Alice" in reply
    assert "7" in reply
    assert "Klein Curaçao" in reply
    assert "2026-04-11" in reply
    # Does NOT re-ask for any of the four fields (explicit substrings the
    # missing-field branches would have produced)
    lower = reply.lower()
    assert "what date" not in lower
    assert "date works" not in lower
    assert "which trip" not in lower
    assert "how many guests" not in lower
    # Asks the customer to resend their last message
    assert "resend" in lower or "last message" in lower


def test_fallback_whatsapp_is_terse():
    """Brief 176: WhatsApp fallback must be under 40 words, no signature."""
    reply = _call({
        "customer_name": "Alice",
        "guests": 7,
    }, channel="whatsapp")
    word_count = len(reply.split())
    assert word_count < 40, f"WhatsApp fallback too long: {word_count} words"
    # No email signature
    assert "Warm regards" not in reply
    # Acknowledges the customer + guests
    assert "Alice" in reply
    assert "7" in reply


def test_fallback_whatsapp_empty_fields():
    """Brief 176: WhatsApp fallback with empty fields — short, asks to resend OR asks missing."""
    reply = _call({}, channel="whatsapp")
    word_count = len(reply.split())
    assert word_count < 40
    assert "hiccup" in reply.lower() or "missed" in reply.lower() or "resend" in reply.lower()
```

### Step 4: Run tests + regression

```bash
python3 -m pytest wtyj/tests/marina/test_176_contextual_fallback.py -v --tb=short
python3 -m pytest wtyj/tests/ -q --tb=line
```

Expected: 5 new tests pass, **833 total passing** (828 baseline + 5 new).

Also run the specific tests that assert on `internal_note` to verify they still pass after the wire-in:
```bash
python3 -m pytest wtyj/tests/marina/test_174_tool_use.py::test_process_message_falls_back_on_empty_reply wtyj/tests/marina/test_174_tool_use.py::test_process_message_falls_back_on_anthropic_exception wtyj/tests/marina/test_174_tool_use.py::test_process_message_falls_back_when_no_tool_use_block wtyj/tests/marina/test_marina_tone.py::test_response_empty_reply_returns_fallback -v
```

All four MUST still pass — they rely on the `internal_note` string, which Step 2 preserves.

### Step 5: Commit + push source, deploy, post-exec docs

Standard workflow per `.claude/commands/brief.md` — commit source + tests + brief, push, fire background deploy, write post-exec docs in parallel, verify health, commit post-exec docs.

Deploy command (shared wtyj-agent image, rebuild once via BlueMarlin, recreate Adamus):
```
ssh root@108.61.192.52 "cd /root && git pull && cd /root/clients/bluemarlin && docker compose down && docker compose build && docker compose up -d && cd /root/clients/adamus && docker compose down && docker compose up -d"
```

Health check:
```
ssh root@108.61.192.52 "curl -s http://localhost:8001/health && curl -s http://localhost:8002/health"
```

## Success Condition

1. `_build_contextual_fallback_reply` function exists at module level in marina_agent.py
2. `process_message` uses the helper to build the fallback dict's `reply` field
3. The WhatsApp override block is removed from `process_message`
4. `internal_note` string is unchanged ("Fallback response — Claude API call failed or returned unparseable output.")
5. 5 new tests passing in test_176_contextual_fallback.py
6. All 4 Brief 174/tone fallback tests still pass (internal_note invariant preserved)
7. Full regression: **833 passing, 0 failures** (828 baseline + 5 new)
8. Both containers healthy post-deploy

## Rollback

Single commit. `git revert <sha> && git push` restores the generic fallback. Zero schema changes, zero data migration.
