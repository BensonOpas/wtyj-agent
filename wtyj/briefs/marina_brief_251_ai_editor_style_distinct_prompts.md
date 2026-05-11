# BRIEF 251 — Upgrade `/ai-editor` style prompts to per-style distinct instructions

**Status:** Draft | **Files:** wtyj/dashboard/api.py, wtyj/tests/social/test_212_dashboard_endpoint_polish.py | **Depends on:** Brief 250 (`64e3284`) | **Blocks:** none

## Context

Issue #21 (Calvin live verification, P1) — the dashboard Agent Editor's `style` tool produces near-identical outputs across all 5 styles (`professional`, `warmer`, `shorter`, `friendlier`, `direct`). Calvin's verdict: "outputs feel weak; shorter is not reliably shorter; more direct is not clearly direct; the tool does not feel premium."

Frontend audit (issue's "Root cause" section) confirmed the frontend passes the correct payload — `{action: "style", text, style, context}`. The bug is backend prompt construction.

**Verified read-only:** the current `_build_ai_editor_prompt` at `wtyj/dashboard/api.py:2793-2821` has a `style` branch (lines 2813-2820) that produces a single template:

```python
    if action == "style":
        return (
            f"Rewrite the following text in a more {style} style. Keep the "
            "same language, factual content, and any names. Return only "
            "the rewritten text — no preamble, no quotation marks, no "
            "explanation.\n\n"
            f"Text:\n{text}"
        )
```

The 5 styles all hit the SAME instruction with the style name swapped in. Claude can't meaningfully differentiate "more professional style" from "more friendlier style" from a single-adjective instruction — especially when the input is already neutral. That's why Calvin sees ~identical outputs.

**Verified — endpoint plumbing is correct:**
- `wtyj/dashboard/api.py:2790` — `_AI_EDITOR_VALID_STYLES = {"professional", "warmer", "shorter", "friendlier", "direct"}` matches issue #21's spec exactly.
- `wtyj/dashboard/api.py:2836-2838` — validation rejects unknown style values with 400.
- `wtyj/dashboard/api.py:2846-2850` — `style` action uses Sonnet 4.6 (not Haiku), correct per Brief 221.
- `wtyj/dashboard/api.py:2858` — response unwraps `resp.content[0].text` and returns `{text: rewritten}`. No quote-stripping needed because the prompt explicitly says "no quotation marks".

**Verified — the em-dash global rule already aligns with Brief 244's customer-facing strip:**
- Brief 244 added em-dash strip in `marina_agent.py:1115-1117` AND `dm_agent.py:253` for customer-facing replies.
- AI editor outputs are operator-facing drafts (operator sees them in the composer before sending). Brief 244's customer-facing strip doesn't catch them. So issue #21's "no em dashes" rule must be enforced in the AI editor prompt itself; the strip on send-time happens later (only when the operator actually sends the message and it goes through `marina_agent.process_message` or `dm_agent.process_message`).
- Brief 251 adds "Do not use em dashes" to each style instruction directly — Claude follows it at draft time so operators don't even see em-dashes in the composer.

## Why This Approach

**Considered:** Add a single richer global prompt that lists all 5 styles' definitions and asks Claude to apply the requested one. **Rejected:** the 5 instructions in issue #21 differ in goal (concise vs warm vs direct), not just in adjective. A single prompt that conditionally branches inside the model's reasoning is harder to debug + tune individually. Per-style distinct prompts are easier to iterate.

**Considered:** Add a Python-side enforcement check for `shorter` — if `len(output) >= len(input)`, retry up to N times. **Rejected for this brief:** retry logic adds latency + cost + complexity for a quality-of-output issue. Issue #21's "hard rule" is best enforced via prompt instruction first; if Claude's compliance rate is unacceptable in production, a follow-up brief adds retries with a measured threshold. For now: trust Claude + add the instruction explicitly.

**Considered:** Use a `style` → `system_prompt + user_prompt` two-message structure so each style has its own system prompt. **Rejected:** the existing endpoint uses a single user-message Claude API call (`messages=[{role: "user", content: prompt}]`). Switching to system + user adds API call shape complexity for marginal quality benefit; per-style distinct user prompts achieve the same differentiation. Single-message stays.

**Considered:** Add the customer-facing em-dash strip Brief 244 has — strip em-dashes from the AI editor response server-side before returning. **Rejected:** AI editor output is operator-facing (the composer pre-fill); operators see it, choose to send/edit/discard. Stripping server-side would mask what Claude actually returned. The prompt-side instruction + the existing customer-facing strip on send-time (Brief 244's `marina_agent.process_message` / `dm_agent.process_message`) is the right belt-and-suspenders. Operators won't accidentally send em-dashes to customers because the on-send strip catches anything Claude didn't.

**Tradeoff — exact instruction strings come from issue #21 with minimal adaptation.** Calvin specified each style's instruction in the issue body. Brief 251 uses those instructions verbatim with light formatting adjustments (newlines for readability, consistent suffix "Return only the rewritten message. No preamble, no explanation."). This preserves Calvin's chosen wording. If a future brief tunes them based on real output samples, that's a separate prompt-engineering iteration.

**Tradeoff — `recommendedOptions` / context-aware adaptation.** The request body includes `context: {conversationId, escalationMode, channel}` but the current prompt doesn't use those fields. Brief 251 keeps that decision unchanged — the channel-aware adaptation ("WhatsApp should feel conversational; email may be slightly more structured" per issue #21's Global rules) is a nice-to-have that adds prompt complexity for marginal benefit on operator drafts. The current `style` adjective + tone-shaping prompt does most of the work. Defer channel-context adaptation to a separate brief if Calvin observes channel-mismatched outputs.

## Instructions

### Step 1 — Replace single-template style branch with per-style distinct instructions

In `wtyj/dashboard/api.py`, the current code at lines 2813-2820 reads:

```python
    if action == "style":
        return (
            f"Rewrite the following text in a more {style} style. Keep the "
            "same language, factual content, and any names. Return only "
            "the rewritten text — no preamble, no quotation marks, no "
            "explanation.\n\n"
            f"Text:\n{text}"
        )
```

Replace with:

```python
    if action == "style":
        # Brief 251: per-style distinct instructions. The pre-Brief-251
        # template `"Rewrite ... in a more {style} style"` produced
        # near-identical outputs because Claude couldn't differentiate
        # styles from a single-adjective instruction. Each style now has
        # its own goal-shaped instruction strategy per issue #21.
        instruction = _STYLE_INSTRUCTIONS.get(style)
        if not instruction:
            # Defensive: validator at the endpoint already rejects unknown
            # styles with 400 before this branch is reached. Belt-and-
            # suspenders so a future caller bypassing the validator gets
            # a clear error instead of an empty prompt.
            raise ValueError(f"unknown style: {style}")
        return f"{instruction}\n\nText:\n{text}"
```

Then add a new module-level dictionary above the `_build_ai_editor_prompt` function (around line 2792, after `_AI_EDITOR_VALID_STYLES`):

```python
# Brief 251: per-style distinct instructions for /ai-editor action='style'.
# Each instruction defines a different goal-shaping strategy so Claude
# produces meaningfully different rewrites across the 5 styles. Verbatim
# from issue #21 with light formatting; global suffixes (preserve
# meaning / no em dashes / return only rewrite) repeated per-style for
# Claude's per-prompt context isolation.
_STYLE_INSTRUCTIONS = {
    "professional": (
        "Rewrite this customer service message in a professional tone. "
        "Keep it concise and clear. Remove filler words and grammar "
        "errors. Do not make it overly stiff or corporate if the "
        "original is informal. Preserve the full meaning. Do not add "
        "any information not in the original. Do not use em dashes. "
        "Return only the rewritten message. No preamble, no explanation."
    ),
    "warmer": (
        "Rewrite this customer service message to sound warmer and "
        "more human. Show genuine appreciation. Avoid corporate "
        "language. It should feel personal, like it was written by a "
        "real person who cares. Preserve the full meaning. Do not add "
        "any information not in the original. Do not use em dashes. "
        "Return only the rewritten message. No preamble, no explanation."
    ),
    "shorter": (
        "Rewrite this message using as few words as possible while "
        "preserving the full meaning. The output must be shorter than "
        "the input. Remove all filler, redundancy, and unnecessary "
        "phrasing. Do not add any content that was not in the "
        "original. Do not use em dashes. Return only the rewritten "
        "message. No preamble, no explanation."
    ),
    "friendlier": (
        "Rewrite this customer service message in a friendly, "
        "approachable tone. Keep it professional enough for customer "
        "service but make it feel conversational and relaxed, not "
        "stiff. Preserve the full meaning. Do not add any information "
        "not in the original. Do not use em dashes. Return only the "
        "rewritten message. No preamble, no explanation."
    ),
    "direct": (
        "Rewrite this customer service message as directly and plainly "
        "as possible. Use simple language. No filler. Keep only what "
        "is necessary to be polite and convey the meaning. The result "
        "should feel crisp and efficient. Do not add any content that "
        "was not in the original. Do not use em dashes. Return only "
        "the rewritten message. No preamble, no explanation."
    ),
}
```

The validator at endpoint level (api.py:2836-2838) continues to reject unknown styles with 400 BEFORE this code runs; the `_STYLE_INSTRUCTIONS.get(style)` lookup is defensive against future internal callers that bypass the validator.

### Step 2 — Add 5 new tests by extending `test_212_dashboard_endpoint_polish.py`

Per Brief 236 rule: extend the existing per-module test file for `/ai-editor` (`wtyj/tests/social/test_212_dashboard_endpoint_polish.py`). Append:

```python


# ── Brief 251: per-style distinct AI editor prompts ─

def test_ai_editor_style_professional_uses_distinct_prompt():
    """Brief 251: the 'professional' style instruction must include the
    Calvin-specified phrasing about keeping it concise and clear AND
    removing filler — distinctive markers absent from the other 4 style
    instructions."""
    from dashboard.api import _build_ai_editor_prompt
    prompt = _build_ai_editor_prompt(
        action="style", text="hello", target_language="", style="professional")
    assert "professional tone" in prompt
    assert "Remove filler words" in prompt
    assert "Do not use em dashes" in prompt
    # Must NOT contain the warmer / friendlier / shorter / direct
    # distinctive markers (proves the prompt is style-specific).
    assert "warmer and more human" not in prompt
    assert "approachable tone" not in prompt
    assert "must be shorter than the input" not in prompt
    assert "directly and plainly" not in prompt


def test_ai_editor_style_warmer_uses_distinct_prompt():
    """Brief 251: 'warmer' style instruction includes the 'warmer and
    more human' goal + 'genuine appreciation' markers."""
    from dashboard.api import _build_ai_editor_prompt
    prompt = _build_ai_editor_prompt(
        action="style", text="hello", target_language="", style="warmer")
    assert "warmer and more human" in prompt
    assert "genuine appreciation" in prompt
    assert "Do not use em dashes" in prompt
    assert "professional tone" not in prompt
    assert "must be shorter than the input" not in prompt


def test_ai_editor_style_shorter_uses_distinct_prompt():
    """Brief 251: 'shorter' style instruction MUST tell Claude the
    output has to be shorter than the input (Calvin's hard rule from
    issue #21). Distinctive phrase: 'must be shorter than the input'."""
    from dashboard.api import _build_ai_editor_prompt
    prompt = _build_ai_editor_prompt(
        action="style", text="hello", target_language="", style="shorter")
    assert "must be shorter than the input" in prompt
    assert "as few words as possible" in prompt
    assert "Do not use em dashes" in prompt
    assert "professional tone" not in prompt
    assert "warmer and more human" not in prompt


def test_ai_editor_style_friendlier_uses_distinct_prompt():
    """Brief 251: 'friendlier' style instruction = 'friendly,
    approachable tone' + 'conversational and relaxed, not stiff'."""
    from dashboard.api import _build_ai_editor_prompt
    prompt = _build_ai_editor_prompt(
        action="style", text="hello", target_language="", style="friendlier")
    assert "approachable tone" in prompt
    assert "conversational and relaxed" in prompt
    assert "Do not use em dashes" in prompt
    assert "warmer and more human" not in prompt
    assert "must be shorter than the input" not in prompt
    assert "directly and plainly" not in prompt


def test_ai_editor_style_direct_uses_distinct_prompt():
    """Brief 251: 'direct' style instruction includes 'directly and
    plainly' + 'crisp and efficient' markers."""
    from dashboard.api import _build_ai_editor_prompt
    prompt = _build_ai_editor_prompt(
        action="style", text="hello", target_language="", style="direct")
    assert "directly and plainly" in prompt
    assert "crisp and efficient" in prompt
    assert "Do not use em dashes" in prompt
    assert "professional tone" not in prompt
    assert "warmer and more human" not in prompt
    assert "approachable tone" not in prompt
```

**Test design notes:**
- All 5 tests call `_build_ai_editor_prompt` directly (Python function-output testing, NOT source-file grepping per Brief 236).
- Each test asserts BOTH the positive markers (distinctive phrases for THIS style) AND negative markers (phrases that must NOT appear from OTHER styles) — guards against future regressions where two style instructions converge.
- "Do not use em dashes" is asserted in every test — Brief 244's em-dash global rule applies to the AI editor's draft outputs too.
- No real Anthropic API call; these test the prompt construction logic, not Claude's output quality. Claude's output quality is observable in production via Calvin's verification flow.

## Step 3 — Out of scope (documented for future briefs)

- **Server-side enforcement of `shorter` "output must be shorter than input"** — if Claude's compliance rate is unsatisfactory in production, a follow-up brief adds Python-side length check + retry. For now: instruction tells Claude; we trust Claude per Rule 2 (Claude does the language understanding).
- **Channel-context-aware adaptation** ("WhatsApp should feel conversational; email may be slightly more structured" per issue #21's Global rules). Defer; current adjective + tone-shaping prompt does most of the work. Add if Calvin observes channel-mismatched outputs.
- **System-prompt + user-prompt two-message structure** — would let each style have its own dedicated system prompt. Defer; per-style distinct user prompts are sufficient differentiation today.
- **Em-dash strip on AI editor server response** — output is operator-facing draft; on-send strip (Brief 244's `marina_agent` / `dm_agent` strips) catches anything Claude didn't already follow. Prompt-side instruction is the right belt-and-suspenders here.
- **Token cost reduction via Haiku for some styles** — Brief 221 already moved `translate` to Haiku. `style` stays on Sonnet because operator-authored drafts need brand-voice quality. Revisit if cost becomes a concern.
- **Live before/after sample collection** — issue #21 asks for "Test examples before/after for all 5 styles" in the report. The deterministic Python tests verify the PROMPT shape; real Claude before/after samples require manual or LLM-call evaluation. OUTPUT 251 will include sample outputs from a manual Anthropic API call against Calvin's example input ("all good. ,thank you , was a pleasure , next time again .") to demonstrate the distinct outputs.

## Tests

5 new tests appended to `wtyj/tests/social/test_212_dashboard_endpoint_polish.py` (extending the existing per-module file for `/ai-editor` per Brief 236).

Expected after-test count: **1078 passing / 0 failures** (1073 baseline + 5 new = 1078).

## Success Condition

After this brief lands:
1. `_build_ai_editor_prompt(action="style", style=X, ...)` returns 5 measurably different prompt strings for `X` in `{professional, warmer, shorter, friendlier, direct}`.
2. Each prompt contains the distinctive instruction phrasing from issue #21's spec.
3. Each prompt contains "Do not use em dashes" — em-dash global rule enforced at draft time.
4. `_STYLE_INSTRUCTIONS.get("unknown")` returns None; the defensive raise at the call site produces a clear `ValueError` if a future internal caller bypasses the endpoint validator.
5. `_build_ai_editor_prompt` for `action="fix"` and `action="translate"` continues to work — Brief 251 only touches the `style` branch.
6. Existing `/ai-editor` tests in `test_212_dashboard_endpoint_polish.py` still pass.
7. 1078 tests passing.
8. Production: Calvin verifies that the 5 styles produce distinctly different rewrites on the same input.

## Rollback

```
git revert <brief-251-commit-sha>
git push origin main
```

This restores the pre-Brief-251 single-template style prompt. The 5 styles go back to producing near-identical outputs. CI re-deploys in ~90s. No data migration needed (pure prompt change).
