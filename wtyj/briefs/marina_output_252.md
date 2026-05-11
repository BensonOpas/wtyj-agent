# OUTPUT 252 — Tighten escalation summary to extract concrete entities + ban meta-language phrases

## What was done

Follow-up to issue #20 after Calvin's PARTIAL/FAIL verification on Brief 250. Brief 250's SQL fix worked (Calvin: "newest customer message is now visible"); but Claude was producing meta-language ("Calvin updated their request", "An updated reply based on their latest message") instead of extracting the concrete entity ("Customer wants 10:30"). Per-step shipped:

1. **Refactored `escalation_summary.py`**: extracted the inline `system_prompt` string (was at lines 179-222 inside `generate_summary`) into a new module-level `_build_system_prompt()` helper (added at lines ~165-251). Refactor is structurally equivalent — the function returns the same string the inline construction built — but adds a Python-callable surface for tests per Brief 236's function-output pattern (mirrors Brief 251's `_build_ai_editor_prompt`). `generate_summary` now calls `system_prompt = _build_system_prompt()` (1 line vs 44 lines inline).
2. **Added Brief 252 hard rule** at the end of the helper's prompt string: `"EXTRACT THE CONCRETE ENTITY"`. The rule explicitly: (a) tells Claude that customerWants / operatorNeedsToDecide / reason / recommendedOptions MUST INCLUDE THE EXACT ENTITY VERBATIM (time/date/location/service the customer named), (b) bans the specific meta-phrases Calvin observed in production ("updated request", "their latest message", "based on their reply", "new request"), (c) provides positive DO examples using Calvin's expected output verbatim ("Move or confirm the appointment at 10:30", "Confirm whether 10:30 is available"), (d) provides negative DO NOT examples using the meta-phrases Calvin saw, (e) includes the enforcement triplet "If the customer named a time, USE THE TIME. If they named a service, USE THE SERVICE. If they named a reason, INCLUDE THE REASON."
3. **3 new tests appended to `wtyj/tests/dashboard/test_escalation_summary_confirmed_time.py`** (extending the existing per-module file per Brief 236). Tests call `_build_system_prompt()` directly and assert: (a) Brief 252's distinctive markers present + the banned meta-phrases appear in the prompt as DON'T examples, (b) the DO examples include Calvin's expected output shape + the USE/INCLUDE enforcement triplet, (c) regression guard — Brief 248's confirmedTime rule + Brief 250's anchoring rule still present in the helper's output.

**Brief-reviewer:** PASS round 1 zero issues. Anchors verified, refactor preserves byte-for-byte (just moves construction into helper), tests use Brief 236-compliant function-output pattern.

**Output-reviewer:** pending.

## Tests

1081 passing / 0 failures (1078 baseline + 3 new = 1081). Targeted file `wtyj/tests/dashboard/test_escalation_summary_confirmed_time.py` runs 7/7 (was 4; added 3).

## Production verification needed (post-deploy)

Calvin sends another customer message that names a specific time/service/reason inside an unresolved escalation. The next escalation summary should:
- `customerWants`: include the named entity verbatim (e.g., "Move or confirm the appointment at 10:30") — NOT meta-phrases like "An updated reply based on their latest message".
- `operatorNeedsToDecide`: name the concrete decision (e.g., "Confirm whether 10:30 is available") — NOT "Ask the customer to confirm what they want".
- `reason`: include the time + the customer's stated reason if any (e.g., "Customer asked to move the appointment to 10:30 and says their dog is much better") — NOT "Customer updated their request".
- `recommendedOptions`: concrete actions naming the entity ("Confirm 10:30", "Suggest closest alternative if 10:30 unavailable") — NOT vague placeholders.

If Claude still produces meta-language despite the explicit rule + DO/DON'T examples, that's a Claude-compliance issue requiring either model-temperature tuning OR a separate Python-side post-processing step (deferred to a follow-up brief).

## Deployment

Source commit pending. Will deploy via the standard CI pipeline. **Pure prompt change + helper refactor** — no schema migration, no behavioral change to other code paths. Briefs 238-251 all preserved. The refactor is structurally equivalent (helper returns the same string the inline construction built); the new Brief 252 rule is the only behavioral addition.

## Out-of-scope (deferred per brief Step 3)

- Server-side enforcement that customerWants doesn't contain meta-phrases (Python check on Claude's output) — Rule 5 territory; defer.
- New `extractedEntities.requestedTime` schema fields — defer; Brief 248's `proposedTimes` + `confirmedTime` already capture time entities; the bug is `customerWants` not USING them.
- Channel-context-aware adaptation (different prompt per channel) — defer.
- Helper parameterization — kept parameter-less today; future brief grows when channel-specific rules are added.
- Backfilling Calvin's existing meta-language summaries — auto-corrects on next escalation event.
