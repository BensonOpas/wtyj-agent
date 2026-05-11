# OUTPUT 259 — Unboks reply rhythm: anti-validation reflex + contradiction handling

## What was done

Round-3 tone fix for issue #28. Calvin's live retest of Brief 258 + the clarification follow-up reported "improved but still not human enough" — the terminology fixes landed (`AI Agent` / `we` / `your agent`) but Marina's reply-shape reflex stayed: every turn opened with a validation phrase (`Nice, ...` / `Got it, ...` / `That's a solid ...` / `Classic ...` / `Perfect ...` / `WhatsApp works perfectly`) then a fact then a question. Brief 258 banned one phrase pool; the SHAPE survived. Brief 259 widens the rule from "ban specific phrases" to "ban the always-validate reflex pattern" plus structural rhythm guidance.

Pure tenant-config edit to `clients/unboks/config/client.json::agent_persona.freeform_notes` (26,516 → 29,161 chars). Five surgical extensions to the existing Brief 258 "WhatsApp chat tone (issue #28 direction):" section: (a) Banned-opener list extended with `Nice,` / `That's a solid` / `Classic` / `Perfect` plus a meta-rule "the underlying reflex you're avoiding is validate-then-answer on every turn"; (b) new "Reply rhythm" section instructing rotation among direct answer / short next question / brief acknowledge / fact-and-stop, plus sentence-count variation; (c) "Reduce salesy certainty" rule replacing `works perfectly` / `exactly what you need` patterns with matter-of-fact alternatives; (d) new "Contradiction handling" section asking Marina to surface a one-sentence clarifying question when the customer contradicts themselves rather than silently accepting both; (e) Calvin's 3 verbatim before/after example pairs appended to the existing "Examples of better phrasing" block.

## Tests

1102 passing / 0 failures unchanged. Brief 258's `test_brief_258_unboks_persona_block_builds_without_error` continues to cover the only deterministic failure mode (malformed JSON / KeyError in builder). Tone-shape verification is Calvin's live retest per Success Condition; LLM tone is not deterministically unit-testable without an LLM-output judge.

## Unexpected findings

Brief-reviewer round 1 FAIL caught three issues that would have shipped a brief with subtle problems: (a) wrong `marina_agent.py:275-276` citation — actual location is `wtyj/agents/marina/marina_agent.py:230` (definition) / `:584` (injection); fixed. (b) The Contradiction-handling example reply contained an em-dash (`WhatsApp — is that a recent change`) — same `freeform_notes` block has an explicit "No em dashes" rule; the new guidance was about to violate the file's own existing rule. Replaced the em-dash with a period break. (c) The 3 new before/after pairs lacked the "mirror these, do not copy verbatim" caveat the existing block carries in its header — risk of Claude treating them as templates. Reframed inline so the caveat explicitly inherits to the new pairs. Round 2 PASS with no issues.

## Deployment

Source commit `271db21` ([HOTFIX] — bypasses off-hours queue). All 4 production containers expected healthy post-deploy via the shared `wtyj-agent` image; only wtyj-unboks's runtime behavior changes (other tenants' client.json files untouched). This is round-3 of a tone fix and tone fixes are iterative — if Calvin's retest reveals continued drift, a round-4 brief can tighten further with sentence-level structural rules or temperature changes (currently deferred per Brief 259's Why-This-Approach).
