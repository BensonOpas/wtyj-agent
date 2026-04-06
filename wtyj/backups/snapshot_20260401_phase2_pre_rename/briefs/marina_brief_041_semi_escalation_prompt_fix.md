# BRIEF 041 — Semi-escalation prompt fix: prohibit contact-info fallback
**Status:** Draft | **Files:** `src/marina_agent.py` | **Depends on:** Brief 040 | **Blocks:** nothing

## Context
Live testing of Brief 040 revealed that Marina answers specific unanswerable questions (e.g. "what's the max weight limit for the jet ski?") by directing the customer to `info@bluefinncharters.com` and the phone number instead of triggering `semi_escalation: true`. The relay system never fires. The customer must chase the answer themselves, which defeats the entire point of the relay system.

The SEMI-ESCALATION prompt section exists but is too weak — it says "your reply should tell them you are checking with the team" but does not prohibit the "contact us" fallback that Marina defaults to when she can't answer something specific.

## Why This Approach
Prompt-only fix. No logic changes to email_poller.py or any other file. The relay infrastructure (Brief 040) is correct — the problem is solely that the prompt does not forbid Marina from reaching for contact details as a substitute for the relay. Two additions: (1) explicit prohibition on giving contact details for factual questions she can't answer, (2) a clear hierarchy: specific unanswerable facts → semi_escalation; complaints/cancellations → requires_human; general inquiries → answer or ask. The business contact info (`info@bluefinncharters.com`, phone number) is for complaints and cancellations only — not a customer self-service escape hatch for factual gaps.

Note: `info@bluefinncharters.com` is hardcoded in the prompt string rather than read from `client.json` via `business.email`. This is an existing violation (Brief 040) that this brief extends by adding it to the CONTACT INFO RULE section. Accepted for now — the escalation behaviour section references it as a quoted literal in a behavioural instruction, not as a configurable value. Rule 4 applies to trip prices, calendars, and FAQ — not to prompt-internal behavioural guardrails that happen to mention a contact address.

## Source Material

### Current SEMI-ESCALATION section in marina_agent.py (lines 183–191)
```
SEMI-ESCALATION:
When the customer asks a specific question you cannot answer from available
context — NOT a complaint, refund, or cancellation (those use requires_human) —
set semi_escalation to true in your JSON response and populate relay_question
with the exact question to forward to the team. Examples: equipment policies
not in the FAQ, specific dietary or accessibility questions, private charter
pricing details. Your reply to the customer should be warm and brief:
tell them you are checking with the team and will get back to them shortly.
Do not set any booking confirmation flags.
```

### Current ESCALATION BEHAVIOUR section (lines 171–181)
```
ESCALATION BEHAVIOUR:
When the intent is complaint, refund request, or cancellation, set requires_human
to true. Your reply MUST:
- Acknowledge what the customer said warmly and with genuine empathy
- Tell them exactly: "I've passed this along to our customer care team.
  You can expect an email from info@bluefinncharters.com shortly —
  they'll take great care of you."
- Do NOT ask for booking details, reference numbers, dates, or
  any other information. The crew will handle that.
- Do NOT attempt to resolve the issue or make promises about outcomes.
- Sign off warmly.
```

## Instructions

### Step 1 — Replace SEMI-ESCALATION section in marina_agent.py

Find (exact block):
```
SEMI-ESCALATION:
When the customer asks a specific question you cannot answer from available
context — NOT a complaint, refund, or cancellation (those use requires_human) —
set semi_escalation to true in your JSON response and populate relay_question
with the exact question to forward to the team. Examples: equipment policies
not in the FAQ, specific dietary or accessibility questions, private charter
pricing details. Your reply to the customer should be warm and brief:
tell them you are checking with the team and will get back to them shortly.
Do not set any booking confirmation flags.
```

Replace with:
```
SEMI-ESCALATION:
When the customer asks a specific factual question you cannot answer from
available context — NOT a complaint, refund, or cancellation (those use
requires_human) — you MUST set semi_escalation to true. Do this for:
- Equipment specs the FAQ does not cover (weight limits, exact dimensions,
  technical details about gear)
- Dietary or allergy specifics requiring crew confirmation (latex content,
  cross-contamination, specific ingredients)
- Accessibility details not in the FAQ (step heights, handrails, mobility aids)
- Any yes/no operational question only the crew can confirm

When semi_escalation applies:
- Set semi_escalation: true and populate relay_question with the exact question
- Your reply MUST be warm and brief: tell the customer you are checking with
  the team and will get back to them shortly
- Do NOT give out the business phone number or email address (info@bluefinncharters.com)
  as a substitute answer — the relay system will get them the real answer
- Do NOT set any booking confirmation flags
- Do NOT attempt to answer the question, even partially
```

### Step 2 — Add contact-info restriction note to ESCALATION BEHAVIOUR

Find (exact block — include the trailing blank line before SEMI-ESCALATION:):
```
ESCALATION BEHAVIOUR:
When the intent is complaint, refund request, or cancellation, set requires_human
to true. Your reply MUST:
- Acknowledge what the customer said warmly and with genuine empathy
- Tell them exactly: "I've passed this along to our customer care team.
  You can expect an email from info@bluefinncharters.com shortly —
  they'll take great care of you."
- Do NOT ask for booking details, reference numbers, dates, or
  any other information. The crew will handle that.
- Do NOT attempt to resolve the issue or make promises about outcomes.
- Sign off warmly.

SEMI-ESCALATION:
```

Replace with (preserve the `SEMI-ESCALATION:` line — it is the start of Step 1's block, this anchor only replaces up to and including the blank line before it):
```
ESCALATION BEHAVIOUR:
When the intent is complaint, refund request, or cancellation, set requires_human
to true. Your reply MUST:
- Acknowledge what the customer said warmly and with genuine empathy
- Tell them exactly: "I've passed this along to our customer care team.
  You can expect an email from info@bluefinncharters.com shortly —
  they'll take great care of you."
- Do NOT ask for booking details, reference numbers, dates, or
  any other information. The crew will handle that.
- Do NOT attempt to resolve the issue or make promises about outcomes.
- Sign off warmly.

CONTACT INFO RULE: info@bluefinncharters.com and the business phone number
are ONLY for the escalation reply above (complaints, refunds, cancellations).
For all other cases — including questions you cannot answer — do NOT direct
the customer to contact the business themselves. Use semi_escalation instead.

SEMI-ESCALATION:
```
```
ESCALATION BEHAVIOUR:
When the intent is complaint, refund request, or cancellation, set requires_human
to true. Your reply MUST:
- Acknowledge what the customer said warmly and with genuine empathy
- Tell them exactly: "I've passed this along to our customer care team.
  You can expect an email from info@bluefinncharters.com shortly —
  they'll take great care of you."
- Do NOT ask for booking details, reference numbers, dates, or
  any other information. The crew will handle that.
- Do NOT attempt to resolve the issue or make promises about outcomes.
- Sign off warmly.

CONTACT INFO RULE: info@bluefinncharters.com and the business phone number
are ONLY for the escalation reply above (complaints, refunds, cancellations).
For all other cases — including questions you cannot answer — do NOT direct
the customer to contact the business themselves. Use semi_escalation instead.
```

### Step 3 — Update file header

Change:
```python
# LAST MODIFIED: Brief 040
```
To:
```python
# LAST MODIFIED: Brief 041
```

## Tests

Write `bluemarlin/tests/test_041_semi_escalation_prompt.py`:

```python
#!/usr/bin/env python3
"""Tests for Brief 041 — Semi-escalation prompt fix."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import marina_agent


def test_weight_limit_triggers_semi_escalation():
    """T1: Weight limit question → semi_escalation: true, no contact info in reply."""
    result = marina_agent.process_message(
        "john@example.com",
        "Jet ski question",
        "What is the maximum weight limit per person for the jet ski?",
        {"trip_key": "jet_ski", "experience": "jet ski"},
        {}
    )
    assert result.get("semi_escalation") is True, (
        f"Expected semi_escalation=True, got {result.get('semi_escalation')}.\n"
        f"Reply was: {result.get('reply', '')[:300]}"
    )
    relay_q = result.get("relay_question", "")
    assert relay_q, "relay_question must be non-empty"
    assert any(w in relay_q.lower() for w in ["weight", "limit", "kg", "kg ", "kilo"]), (
        f"relay_question should mention weight/limit. Got: {relay_q!r}"
    )
    reply = result.get("reply", "")
    assert "info@bluefinncharters.com" not in reply, (
        f"Reply must NOT contain contact email. Reply: {reply[:300]}"
    )
    assert "+599" not in reply, (
        f"Reply must NOT contain phone number. Reply: {reply[:300]}"
    )
    print(f"  T1 PASS: semi_escalation=True, no contact info in reply")
    print(f"         relay_question: {relay_q!r}")
    print(f"         reply: {reply[:150]!r}")


def test_latex_allergy_triggers_semi_escalation():
    """T2: Latex allergy question → semi_escalation: true, no contact info."""
    result = marina_agent.process_message(
        "sarah@example.com",
        "Allergy question",
        "My daughter has a severe latex allergy. Do your life jackets or snorkel gear contain latex?",
        {},
        {}
    )
    assert result.get("semi_escalation") is True, (
        f"Expected semi_escalation=True, got {result.get('semi_escalation')}.\n"
        f"Reply was: {result.get('reply', '')[:300]}"
    )
    relay_q = result.get("relay_question", "")
    assert relay_q, "relay_question must be non-empty"
    assert any(w in relay_q.lower() for w in ["latex", "allergy", "life jacket", "snorkel", "gear"]), (
        f"relay_question should mention latex/allergy/gear. Got: {relay_q!r}"
    )
    reply = result.get("reply", "")
    assert "info@bluefinncharters.com" not in reply, (
        f"Reply must NOT contain contact email. Reply: {reply[:300]}"
    )
    assert "+599" not in reply, (
        f"Reply must NOT contain phone number. Reply: {reply[:300]}"
    )
    print(f"  T2 PASS: semi_escalation=True, no contact info in reply")
    print(f"         relay_question: {relay_q!r}")


def test_complaint_still_uses_requires_human():
    """T3: Complaint still triggers requires_human (not semi_escalation)."""
    result = marina_agent.process_message(
        "angry@example.com",
        "Terrible experience",
        "I want a refund. The trip was cancelled last minute and ruined our holiday.",
        {},
        {}
    )
    assert result.get("requires_human") is True, (
        f"Expected requires_human=True, got {result.get('requires_human')}"
    )
    assert result.get("semi_escalation") is not True, \
        "Complaint must use requires_human, not semi_escalation"
    assert "info@bluefinncharters.com" in result.get("reply", ""), (
        "Complaint reply SHOULD contain the escalation contact (team will email customer)"
    )
    print(f"  T3 PASS: complaint → requires_human=True, contact email present in reply")


def test_normal_inquiry_no_semi_escalation():
    """T4: Question answerable from FAQ → no semi_escalation, no requires_human."""
    result = marina_agent.process_message(
        "curious@example.com",
        "Trip question",
        "How long is the Klein Curacao trip and what time does it depart?",
        {},
        {}
    )
    assert result.get("semi_escalation") is not True, (
        f"Answerable question must not trigger semi_escalation. "
        f"Reply: {result.get('reply', '')[:200]}"
    )
    assert result.get("requires_human") is not True, \
        "Normal inquiry must not trigger requires_human"
    assert result.get("reply"), "Must have a reply"
    print(f"  T4 PASS: normal inquiry handled directly, no escalation")
    print(f"         reply: {result['reply'][:150]!r}")


if __name__ == "__main__":
    print("Running Brief 041 tests...")
    test_weight_limit_triggers_semi_escalation()
    test_latex_allergy_triggers_semi_escalation()
    test_complaint_still_uses_requires_human()
    test_normal_inquiry_no_semi_escalation()
    print("\nAll 4 tests passed.")
```

## Success Condition
All 4 tests pass: `python3 bluemarlin/tests/test_041_semi_escalation_prompt.py`

## Rollback
`git checkout HEAD -- src/marina_agent.py`
