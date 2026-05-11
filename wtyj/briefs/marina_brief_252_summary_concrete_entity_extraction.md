# BRIEF 252 — Tighten escalation summary to extract concrete entities + ban meta-language phrases

**Status:** Draft | **Files:** wtyj/dashboard/escalation_summary.py, wtyj/tests/dashboard/test_escalation_summary_confirmed_time.py | **Depends on:** Brief 251 (`13ad785`) | **Blocks:** none

## Context

Issue #20 follow-up — Calvin's verification after Brief 250 PARTIAL/FAIL. Brief 250's SQL fix for `wa_get_full_history` worked (Calvin confirmed: "newest customer message is now visible, so the oldest-20-message bug appears fixed"). But Claude's summary is still not operator-grade.

**Calvin's exact reproduction:**
- Customer's latest message: `"Actually, can we make it 10:30 instead? my dog is much better."`
- Live dashboard summary observed:
  - Summary (`reason`): `"Calvin updated their request. Their earlier message no longer reflects what they want."`
  - `customerWants`: `"An updated reply based on their latest message."`
  - Suggested next step: `"Ask the customer to confirm what they want, or take over to clarify directly."`

**Why this fails (Calvin's exact words):**
- The system can now see the latest message, but it still does not extract the concrete decision.
- It fails to say the customer is asking to move/confirm the appointment at 10:30.
- It gives vague meta-language (`updated request`, `updated reply`) instead of the actual operator decision.
- The operator still has to read the message manually, defeating the purpose of the summary box.

**Calvin's expected output for the same input:**
- Summary: `"Customer wants to change the appointment request to 10:30 and says their dog is much better."`
- Customer wants: `"Move or confirm the appointment at 10:30."`
- Suggested next step: `"Confirm whether 10:30 is available. If it is not available, offer the closest available time."`

**Verified read-only:** the current system prompt at `wtyj/dashboard/escalation_summary.py:179-222` has 8 hard rules including Brief 250's "MOST RECENT message changes the requested time → fields MUST reflect that NEW request." Claude IS following the Brief 250 rule — but at a meta-level ("updated request", "their latest message") instead of an entity-level ("10:30"). The Brief 250 rule says "reflect" without saying "include the specific entity verbatim" or "ban meta-phrases." Claude's compliance is technically correct but operationally useless.

**Verified — refactor opportunity:** the `system_prompt` is built inline as a string concatenation at line 179-222 of `generate_summary()`. There's no helper function — which is why Brief 250's test 4 was a banned source-string-grepper (no Python-callable surface to assert against). Brief 252 extracts the prompt construction into a `_build_system_prompt()` helper so tests can exercise it directly per Brief 251's pattern (`_build_ai_editor_prompt` + dict-based per-mode tests).

## Why This Approach

**Considered:** Add a Python post-processing step that strips meta-language phrases from Claude's output ("updated request" → empty, etc.). **Rejected:** Rule 5 violation (Python-side text classification of operator-facing summary); the result would be hollow strings ("Customer wants to ."). Fix the prompt; let Claude do the language work properly.

**Considered:** Add a SECOND Claude call that takes the meta-language summary as input and rewrites it concretely. **Rejected:** doubles latency + cost per escalation; the existing summary call has full conversation context and can do the entity extraction in one pass with sharper instructions.

**Considered:** Add new schema fields like `extractedEntities.requestedTime`, `extractedEntities.requestedReason`, etc., for Claude to populate verbatim. **Rejected for this brief:** larger surface (schema migration + frontend updates + bridge logic in escalation_dispatcher); the Brief 248 + 250 fields (`proposedTimes`, `confirmedTime`, `previousProposedTimes`) already capture the time entities. The bug is that `customerWants` / `operatorNeedsToDecide` aren't using them. A prompt rule fixes that without schema change.

**Considered:** Skip the helper-function refactor; just edit the inline `system_prompt` string and rely on Calvin's production verification. **Rejected:** Brief 250's test 4 was rejected for being a source-string-grepper precisely because there was no helper function to test. Brief 252 takes the opportunity to add the helper so this AND future prompt-rule changes are testable per the established Brief 251 pattern (`_build_ai_editor_prompt` direct-call tests).

**Tradeoff — DO/DON'T examples in the prompt make the prompt longer.** The new rule adds ~10-15 lines. Claude Sonnet 4.6 handles long system prompts well; the trade-off is acceptable. Concrete examples are what makes Claude actually follow the rule (Brief 248's confirmedTime field has explicit "QUALIFY" / "DO NOT qualify" examples and they work).

**Tradeoff — `proposedTimes` should now include "10:30".** Claude's existing rule says "Extract EVERY proposed time/slot/option from the customer's messages" (line 187-189). For Calvin's input "can we make it 10:30 instead?", `proposedTimes` SHOULD include "10:30". The brief doesn't change that rule — it just adds the rule that `customerWants` and `operatorNeedsToDecide` MUST USE the entities from `proposedTimes` (or whichever applicable field) instead of meta-describing them.

## Instructions

### Step 1 — Extract `_build_system_prompt()` helper from `generate_summary`

In `wtyj/dashboard/escalation_summary.py:179-222`, the current code reads:

```python
        system_prompt = (
            "You are an operator-facing assistant. ..."
            ...
            "tell the operator what to decide RIGHT NOW based on the "
            "latest message, not what was being decided 20 messages ago."
        )
```

Refactor: move the entire string construction into a new module-level function above `generate_summary` (around line 165, after `_format_history`):

```python
def _build_system_prompt() -> str:
    """Brief 252: extracted from generate_summary so tests can exercise
    the prompt construction directly via Brief 236's function-output
    pattern (mirrors Brief 251's _build_ai_editor_prompt). The system
    prompt is constant per-call (does not depend on customer/channel/
    history) so no parameters are needed today; if future briefs add
    per-channel adaptation (Brief 251 Step 3 deferred), this helper
    grows parameters."""
    return (
        "You are an operator-facing assistant. Your job is to read a "
        "conversation between a CUSTOMER and an AI AGENT, then summarize "
        "the situation for a human operator who has to step in. The "
        "operator will read your summary BEFORE reading the conversation, "
        "so it must give them everything they need to make a decision in "
        "one glance.\n\n"
        "Hard rules:\n"
        "- Extract EVERY proposed time/slot/option from the customer's "
        "messages. Never summarize 'suggested a time' if exact times "
        "exist.\n"
        "- Use the customer's exact wording for times when possible.\n"
        "- Recommended options must be CONCRETE actions, not categories. "
        "'Confirm Thursday at 09:00' yes; 'Pick a time' no.\n"
        "- For scheduling escalations, always include "
        "'Suggest another time' and 'Switch to human takeover' as "
        "fallbacks.\n"
        "- Never invent customer wording or times that aren't in the "
        "transcript.\n"
        "- When the customer explicitly retracts a previously proposed "
        "time and proposes a different one (e.g., \"i changed my mind, "
        "change it to X\"), put the new time in proposedTimes and the "
        "retracted time(s) in previousProposedTimes. Do not put the "
        "same time in both lists.\n"
        "- Brief 248: when the customer's MOST RECENT message contains "
        "an explicit confirmation that they will attend at a specific "
        "time (e.g., \"we will be there at 12:00\", \"see you Friday "
        "at 15:00\"), populate confirmedTime with that exact time "
        "wording. Tentative language (\"maybe 12\", \"how about "
        "Tuesday?\") does NOT qualify. When in doubt, leave "
        "confirmedTime empty.\n"
        "- Brief 250: when the customer's MOST RECENT message changes "
        "the requested time, asks to reschedule, or introduces a new "
        "decision point (e.g., \"can u make it 10 instead\", "
        "\"actually let's do tomorrow\", \"my dog is sick can we "
        "move to X\"), the customerWants, operatorNeedsToDecide, "
        "and recommendedOptions fields MUST reflect that NEW request. "
        "Older proposed times that the customer hasn't explicitly "
        "kept on the table belong in previousProposedTimes (if they "
        "were retracted) OR may be omitted from proposedTimes if the "
        "newest message clearly supersedes them. The summary should "
        "tell the operator what to decide RIGHT NOW based on the "
        "latest message, not what was being decided 20 messages ago.\n"
        "- Brief 252: EXTRACT THE CONCRETE ENTITY. When the customer's "
        "latest message contains a specific time, date, location, "
        "service, or request, the customerWants, operatorNeedsToDecide, "
        "reason, and recommendedOptions fields MUST INCLUDE THAT EXACT "
        "ENTITY VERBATIM. Do NOT use meta-descriptions like \"updated "
        "request\", \"their latest message\", \"based on their reply\", "
        "\"new request\", or any phrase that describes the change "
        "without naming what was actually requested.\n"
        "  DO (concrete, names the entity): customerWants = \"Move or "
        "confirm the appointment at 10:30.\"; operatorNeedsToDecide = "
        "\"Confirm whether 10:30 is available, or offer the closest "
        "alternative.\"; reason = \"Customer asked to move the "
        "appointment to 10:30 and says their dog is much better.\"\n"
        "  DO NOT (meta, names nothing): customerWants = \"An updated "
        "reply based on their latest message.\"; operatorNeedsToDecide "
        "= \"Ask the customer to confirm what they want.\"; reason = "
        "\"Customer updated their request.\"\n"
        "  If the customer named a time, USE THE TIME. If they named "
        "a service, USE THE SERVICE. If they named a reason (\"because "
        "X\"), INCLUDE THE REASON. The summary box exists so the "
        "operator does NOT have to read the message themselves -- if "
        "your output forces them to read it, you have failed."
    )
```

Then replace the inline construction in `generate_summary` (lines 179-222) with a single call:

```python
        system_prompt = _build_system_prompt()
```

This refactor is structurally equivalent — the function returns the same string the inline construction built — but adds a Python-callable surface for tests.

### Step 2 — Add 3 new tests by extending `test_escalation_summary_confirmed_time.py`

Per Brief 236 rule: extend `wtyj/tests/dashboard/test_escalation_summary_confirmed_time.py` (the existing per-module file for `escalation_summary.py`). Append:

```python


# ── Brief 252: prompt extracts concrete entities + bans meta-language ─

def test_summary_prompt_includes_concrete_entity_extraction_rule():
    """Brief 252: the system prompt MUST include the entity-extraction
    rule. Distinctive markers from Calvin's issue #20 follow-up that
    distinguish this rule from the existing Brief 248 / Brief 250 rules."""
    from dashboard.escalation_summary import _build_system_prompt
    prompt = _build_system_prompt()
    # Distinctive marker for Brief 252's entity-extraction rule.
    assert "EXTRACT THE CONCRETE ENTITY" in prompt
    assert "MUST INCLUDE THAT EXACT ENTITY VERBATIM" in prompt
    # Brief 252 explicitly bans the meta-phrases Calvin observed in
    # production.
    assert "updated request" in prompt
    assert "their latest message" in prompt
    assert "based on their reply" in prompt


def test_summary_prompt_includes_concrete_do_examples():
    """Brief 252: the prompt MUST include positive DO examples that
    show Claude what concrete entity extraction looks like (not just
    the negative DO NOT)."""
    from dashboard.escalation_summary import _build_system_prompt
    prompt = _build_system_prompt()
    # Calvin's specific expected output shape from issue #20 follow-up:
    assert "Move or confirm the appointment at 10:30" in prompt
    assert "Confirm whether 10:30 is available" in prompt
    # The "if customer named X, USE X" enforcement triplet:
    assert "USE THE TIME" in prompt
    assert "USE THE SERVICE" in prompt
    assert "INCLUDE THE REASON" in prompt


def test_summary_prompt_preserves_brief_248_and_250_rules():
    """Brief 252 regression: the helper extraction must not drop the
    earlier Brief 248 (confirmedTime) or Brief 250 (latest-message
    anchoring) rules. Both must remain in the prompt verbatim."""
    from dashboard.escalation_summary import _build_system_prompt
    prompt = _build_system_prompt()
    # Brief 248 marker (from the confirmedTime rule):
    assert "When in doubt, leave confirmedTime empty" in prompt
    # Brief 250 marker (from the latest-message anchoring rule):
    assert "what was being decided 20 messages ago" in prompt
    # Brief 248's explicit qualifier example:
    assert "we will be there at 12:00" in prompt
```

**Test design notes:**
- All 3 tests call `_build_system_prompt()` directly — Python function-output testing per Brief 236 (NOT source-file grepping; the function returns a string, tests assert on the function's return value).
- Test 1 asserts BOTH the new rule's distinctive phrases AND the explicit meta-phrases that are now banned. The negative-meta phrases must appear in the prompt as DON'T examples, not as outputs.
- Test 2 asserts the DO examples that show Claude what concrete extraction looks like — using Calvin's exact expected output shape from his issue #20 follow-up.
- Test 3 is a regression guard: the helper extraction must preserve Brief 248's confirmedTime rule + Brief 250's anchoring rule. If a future brief touches `_build_system_prompt` and accidentally drops either, these assertions fail.

## Step 3 — Out of scope (documented for future briefs)

- **Server-side enforcement that customerWants doesn't contain meta-phrases** (Python check on Claude's output). Defer; trust Claude's prompt compliance per Rule 2. If non-compliance is observed, follow-up brief adds the check.
- **New `extractedEntities.requestedTime` / `extractedEntities.requestedReason` schema fields.** Defer; Brief 248's `proposedTimes` + `confirmedTime` already capture time entities. The bug is `customerWants` / `operatorNeedsToDecide` not USING them — a prompt rule fixes that.
- **Channel-context-aware adaptation** (different prompt per channel). Defer; the entity-extraction rule applies regardless of channel.
- **Helper parameterization** (e.g., `_build_system_prompt(channel)`) — kept parameter-less today; future brief grows parameters when channel-specific rules are added.
- **Backfilling Calvin's existing escalation summaries** that have meta-language outputs. Auto-corrects on the next escalation event for each conversation.

## Tests

3 new tests appended to `wtyj/tests/dashboard/test_escalation_summary_confirmed_time.py`.

Expected after-test count: **1081 passing / 0 failures** (1078 baseline + 3 new = 1081).

## Success Condition

After this brief lands:
1. `_build_system_prompt()` exists as a module-level helper function in `wtyj/dashboard/escalation_summary.py`, returning the full system prompt string.
2. `generate_summary` calls `_build_system_prompt()` instead of constructing the prompt inline. The string sent to Claude is byte-for-byte identical to pre-refactor PLUS the new Brief 252 rule.
3. The Brief 252 rule explicitly: (a) tells Claude to EXTRACT CONCRETE ENTITIES VERBATIM, (b) gives DO examples using Calvin's exact expected output, (c) gives DO NOT examples banning the meta-phrases Calvin observed in production.
4. Brief 248's confirmedTime rule + Brief 250's anchoring rule preserved unchanged.
5. Existing escalation summary behavior (intent + topic + proposedTimes + previousProposedTimes + confirmedTime + customerWants + operatorNeedsToDecide + reason + recommendedOptions + latestCustomerMessage) preserved.
6. 1081 tests passing.
7. Production verification by Calvin: send another customer message that names a specific time/service/reason; the resulting summary fields should USE the named entity verbatim (not meta-phrases).

## Rollback

```
git revert <brief-252-commit-sha>
git push origin main
```

This restores the inline `system_prompt` construction in `generate_summary` (no helper function) and removes the Brief 252 rule. Claude goes back to producing the meta-language Calvin observed. CI re-deploys in ~90s.
