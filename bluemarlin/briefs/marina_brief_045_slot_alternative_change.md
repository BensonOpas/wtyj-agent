# BRIEF 045 — Slot-unavailable alternative = change, not confirmation + [PAYMENT_LINK] safety net
**Status:** Draft | **Files:** `bluemarlin/src/marina_agent.py`, `bluemarlin/src/email_poller.py` | **Depends on:** Brief 044 | **Blocks:** —

## Context

Live stress test: Klein Curacao 08:30 slot on March 20 was full. Marina offered alternatives (08:00 same day, 08:30 next day, 08:00 next day). Customer picked "bluefinn 2 on 21 march". Marina set `booking_confirmed: true` and sent the final booking reply with literal `[PAYMENT_LINK]` — skipping the confirmation summary step entirely. She should have treated picking an alternative as a CHANGE (update date+departure, reset flags, re-send summary for confirmation).

The `[PAYMENT_LINK]` literal was sent to the customer because Marina set `booking_confirmed` without writing `reply_hold_failed`, and the hold creation likely failed (slot_checked still true, slot_available still false from old date). No Python safety net exists to prevent sending `[PAYMENT_LINK]` as literal text.

## Why This Approach

Two minimal fixes. (1) Prompt-only addition to marina_agent.py — explicitly tell Marina that picking a slot-unavailable alternative is a CHANGE, not a confirmation. This slots into the existing `awaiting_booking_confirmation` handler as a new bullet, consistent with the FIRST/SECOND/THIRD check pattern. (2) Safety net in email_poller.py — strip `[PAYMENT_LINK]` from reply_text before sending. This is a one-liner that prevents the placeholder from ever reaching a customer regardless of how it gets there.

## Source Material

Current prompt text in marina_agent.py (lines 152–167):
```
When "awaiting_booking_confirmation" is true in thread flags:
- If the customer's message is a confirmation (yes, sure, let's do
  it, perfect, go ahead, ja, si, or any equivalent in any language):
  In your JSON response, the "flags" field MUST contain:
  "booking_confirmed": true, "awaiting_booking_confirmation": false
  Reply briefly confirming you are locking it in.
- If the customer wants to change something: if the change involves
  the date, FIRST verify the new date's day of week matches the
  trip's days_available (same check as initial booking). If the new
  date is invalid, do NOT reset awaiting_booking_confirmation —
  tell the customer which days the trip runs and suggest the nearest
  valid dates. If the new date is valid (or no date was changed),
  update the relevant field, reset awaiting_booking_confirmation to
  false, and re-run the FIRST, SECOND, and THIRD checks before sending a
  new booking summary.
- If unclear: ask for clarification.
```

Current email_poller.py line 671–672:
```python
                    # Send Claude's reply for all booking sub-cases
                    smtp_send(from_email, "Re: " + subj, reply_text,
```

## Instructions

### Step 1 — Add slot-unavailable alternative bullet to prompt

In `bluemarlin/src/marina_agent.py`, insert a new bullet between the "change" bullet (ending at line 166 with "new booking summary.") and the "unclear" bullet (line 167). Insert after `  new booking summary.` and before `- If unclear:`:

```
- If a slot was unavailable and you previously offered alternative
  dates or times: the customer picking one of those alternatives is
  a CHANGE, not a confirmation. Update the relevant fields (date,
  departure_time, or both), reset awaiting_booking_confirmation to
  false, and re-run the FIRST, SECOND, and THIRD checks before
  sending a new booking summary. Do NOT set booking_confirmed.
```

### Step 2 — Add [PAYMENT_LINK] safety strip in email_poller.py

In `bluemarlin/src/email_poller.py`, immediately before line 672 (`smtp_send` for booking sub-cases), add:

```python
                    reply_text = reply_text.replace("[PAYMENT_LINK]", "")
```

### Step 3 — Update file headers

In `bluemarlin/src/marina_agent.py`, change `# LAST MODIFIED: Brief 044` to `# LAST MODIFIED: Brief 045`.

In `bluemarlin/src/email_poller.py`, change `# Last modified: Brief 043` to `# Last modified: Brief 045`.

## Tests

File: `bluemarlin/tests/test_045_slot_alternative_change.py`

```python
#!/usr/bin/env python3
"""Tests for Brief 045 — Slot-unavailable alternative = change, not confirmation."""
import sys, os, inspect
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_prompt_alternative_is_change():
    """T1: Prompt says picking an alternative is a CHANGE, not a confirmation."""
    import marina_agent
    prompt = marina_agent._build_prompt("a@b.com", "test", "test", {}, {})
    assert "alternatives is" in prompt or "alternative" in prompt and "CHANGE" in prompt, \
        "Prompt must say alternatives = CHANGE"
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
```

## Success Condition

All 6 tests pass. Marina treats picking a slot-unavailable alternative as a change and re-sends the summary. `[PAYMENT_LINK]` is never sent as literal text.

## Rollback

Revert marina_agent.py prompt bullet and email_poller.py safety line. Change headers back.
