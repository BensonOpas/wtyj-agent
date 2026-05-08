# BRIEF 224 — Strip internal escalation tokens from Marina email replies
**Status:** Draft | **Files:** `wtyj/agents/marina/marina_agent.py`, `wtyj/tests/marina/test_224_strip_internal_tokens.py` | **Depends on:** Brief 206 (`[ESCALATE]` sentinel emission), Brief 209 (unboks escalation script in `freeform_notes`) | **Blocks:** clean customer-facing emails for unboks (and any future tenant whose master prompt instructs Marina to emit a sentinel)

## Context

Marina's master prompt for unboks (and any tenant with an escalation script in `freeform_notes`) instructs her to end a reply with the literal token `[ESCALATE]` on its own line. The token is a sentinel for the routing layer — it should never reach the customer.

`wtyj/agents/social/dm_agent.py:215-221` already strips `[ESCALATE]` from the IG/FB DM path before the reply is sent. **The email path has no equivalent strip.** Marina's reply flows through `marina_agent.process_message()` and is sent verbatim via `smtp_send()` from one of the 13 call sites in `wtyj/agents/marina/email_poller.py`. Result: real customer emails for unboks have ended with:

```
Marina
Unboks
[ESCALATE]
```

SR (Calvin) reported this from production. It's a customer-trust bug, not theoretical.

A second-order question: SR asks for a broader strip of `[SOFT_ESCALATION]`, `[HARD_ESCALATION]`, `[HANDOFF]`, `[HUMAN_TAKEOVER]`, "any bracketed internal routing marker". A blanket `r"\[[A-Z_]+\]"` regex is dangerous — `[BOOKING_REF]` and `[PAYMENT_LINK]` are legitimate template placeholders that get replaced with real values at `email_poller.py:1212-1225,1290-1291`. Stripping them would break booking flow. We use an explicit allowlist of escalation tokens.

## Why This Approach

**Chosen:** strip in `marina_agent.process_message()` immediately before the `return result` on line 1061. One chokepoint for every caller of Marina's structured response — email today, any future channel that calls `process_message()`. Strip applies to both `result["reply"]` and `result["reply_hold_failed"]` (the booking-failure fallback at `email_poller.py:1193`, which is also customer-facing text Marina generated).

**Rejected:** strip inside `email_adapter.smtp_send()`. Would catch every email outbound including operator-typed `/escalations/{id}/reply` text. Operators don't type these tokens, so the broader catch is unnecessary; meanwhile `smtp_send` becoming content-aware is a bad layering signal — transport shouldn't sanitize semantic content.

**Rejected:** put the strip in each `email_poller.py` smtp_send call site. 13 sites, 13 chances to forget. One central sanitize at the source is correct.

**Rejected:** also touch `dm_agent.py`. dm_agent already strips `[ESCALATE]` (line 221). Expanding that to the full token list there is a separate change — `dm_agent` doesn't go through `marina_agent` and the IG/FB master prompt currently only emits `[ESCALATE]`. We'd be adding speculative defense. Defer if/when a tenant's DM prompt emits another token.

**Tradeoff:** if a future caller of `marina_agent.process_message()` LEGITIMATELY wants to detect a sentinel before send (the way `dm_agent.py:219` does for `[ESCALATE]` to fire `state_registry.create_pending_notification`), they'd need to inspect the raw response BEFORE the strip. **Mitigation:** for the email path, escalation detection runs at `email_poller.py` via `result["requires_human"]` from Marina's structured fields, not from the literal `[ESCALATE]` token. The token in the email path is decorative — its job is to signal Marina-internally "I'm escalating," and `requires_human` carries the routing semantics. So stripping at marina_agent is safe for the email path. dm_agent is unaffected because it never calls `marina_agent.process_message`.

## Instructions

1. Open `wtyj/agents/marina/marina_agent.py`. After the `_RESPONSE_DEFAULTS` dict (currently ends ~line 24), insert a constant tuple and a helper:

```python
# Brief 224: bracketed sentinels Marina's prompt may emit for routing.
# These must never reach the customer — strip from any text field returned
# by process_message before it leaves the agent. NOT a blanket "[X]" strip:
# [BOOKING_REF] and [PAYMENT_LINK] are legitimate template placeholders that
# the email_poller substitutes downstream.
_INTERNAL_TOKENS = (
    "[ESCALATE]",
    "[SOFT_ESCALATION]",
    "[HARD_ESCALATION]",
    "[HANDOFF]",
    "[HUMAN_TAKEOVER]",
)


def _strip_internal_tokens(text: str) -> str:
    """Remove every internal routing token from `text` and clean up trailing
    whitespace + isolated blank lines a removed token may have left behind."""
    if not text:
        return text
    out = text
    for tok in _INTERNAL_TOKENS:
        out = out.replace(tok, "")
    # Collapse runs of 3+ newlines (a stripped token on its own line leaves
    # `\n\n\n`) down to a maximum of 2 newlines (one blank line between
    # paragraphs is fine). Trailing whitespace also goes.
    while "\n\n\n" in out:
        out = out.replace("\n\n\n", "\n\n")
    return out.rstrip()
```

2. In `marina_agent.process_message()`, replace the success-path return (currently `return result` on line 1061) with:

```python
        # Brief 224: sanitize customer-facing text fields before returning.
        result["reply"] = _strip_internal_tokens(result.get("reply", ""))
        if result.get("reply_hold_failed"):
            result["reply_hold_failed"] = _strip_internal_tokens(result["reply_hold_failed"])

        return result
```

The fallback path (lines 1003-1004 / 1067) returns a hardcoded string with no tokens — leave unchanged.

3. Create `wtyj/tests/marina/test_224_strip_internal_tokens.py` with the 5 tests below.

## Tests

```python
"""Tests for Brief 224 — strip internal escalation tokens from Marina
replies before they reach customer-facing channels."""
import os
from unittest.mock import patch, MagicMock

import pytest


def _mock_anthropic_response(reply_text: str, reply_hold_failed: str = ""):
    """Build a mock anthropic response whose tool_use block carries the given
    reply (and optionally reply_hold_failed) field."""
    block = MagicMock()
    block.type = "tool_use"
    inp = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "medium",
        "reply": reply_text,
        "clarifications_needed": [],
        "requires_human": False,
        "flags": {},
        "internal_note": "",
    }
    if reply_hold_failed:
        inp["reply_hold_failed"] = reply_hold_failed
    block.input = inp
    resp = MagicMock()
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=10, output_tokens=20)
    return resp


def _call_process_message(reply_text: str, reply_hold_failed: str = ""):
    from agents.marina import marina_agent
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
         patch("agents.marina.marina_agent.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            reply_text, reply_hold_failed)
        return marina_agent.process_message(
            from_email="alice@example.com",
            subject="hi",
            body="hello",
            thread_fields={},
            thread_flags={},
            action_context={},
            channel="email",
            messages=[],
        )


def test_escalate_token_stripped_from_reply():
    """Brief 224: [ESCALATE] sentinel removed from customer-facing reply."""
    result = _call_process_message(
        "Got it, passing this to the team.\n\nMarina\nUnboks\n[ESCALATE]"
    )
    assert "[ESCALATE]" not in result["reply"]
    assert result["reply"].endswith("Unboks")


def test_all_listed_tokens_stripped():
    """All five internal tokens listed in _INTERNAL_TOKENS are removed."""
    text = ("Reply body.\n[ESCALATE]\n[SOFT_ESCALATION]\n"
            "[HARD_ESCALATION]\n[HANDOFF]\n[HUMAN_TAKEOVER]\nMarina")
    result = _call_process_message(text)
    for tok in ("[ESCALATE]", "[SOFT_ESCALATION]", "[HARD_ESCALATION]",
                "[HANDOFF]", "[HUMAN_TAKEOVER]"):
        assert tok not in result["reply"]
    assert "Reply body." in result["reply"]
    assert "Marina" in result["reply"]


def test_booking_ref_and_payment_link_preserved():
    """Regression: legitimate template placeholders are NOT stripped."""
    text = "Booked! Ref: [BOOKING_REF]. Pay here: [PAYMENT_LINK]"
    result = _call_process_message(text)
    assert "[BOOKING_REF]" in result["reply"]
    assert "[PAYMENT_LINK]" in result["reply"]


def test_reply_hold_failed_also_stripped():
    """The booking-failure fallback field is also customer-facing — strip
    tokens from it too."""
    result = _call_process_message(
        reply_text="ok",
        reply_hold_failed="Sorry, hold failed. We'll be in touch.\n[ESCALATE]",
    )
    assert "[ESCALATE]" not in result["reply_hold_failed"]
    assert "Sorry, hold failed" in result["reply_hold_failed"]


def test_no_tokens_no_change():
    """Reply with no internal tokens is returned untouched (apart from a
    trailing rstrip), so existing prompts continue to behave the same."""
    text = "Hello! Thanks for your message.\n\nMarina"
    result = _call_process_message(text)
    assert result["reply"] == text  # no trailing whitespace to strip
```

## Success Condition

After deploy, an unboks customer who triggers an escalation receives an email that ends with `Marina\nUnboks` and contains no `[ESCALATE]` token. New regression tests in `test_224_strip_internal_tokens.py` prove the strip applies to all five listed tokens, leaves `[BOOKING_REF]` / `[PAYMENT_LINK]` alone, and covers both `reply` and `reply_hold_failed`. Full suite stays at 1028 + 5 new = 1033 passing / 0 failures.

## Rollback

`git revert <commit>`. The two-helper additions to `marina_agent.py` and the new test file are the entire surface area — revert restores the leak (Marina emails customers `[ESCALATE]`) but doesn't break anything else. Customers who received tokens in the meantime aren't recoverable, but the leak stops with the revert.
