# BRIEF 259 — Unboks reply rhythm: drop validation-phrase reflex, vary rhythm, handle contradictions
**Status:** Draft | **Files:** `clients/unboks/config/client.json` | **Depends on:** Brief 258 | **Blocks:** issue #28 verification (round 3)

## Context

Calvin's live retest of Brief 258 + clarification follow-up at 2026-05-11T23:25:57Z reported "improved but still not human enough." Brief 258's banned-opener list (`Good question`, `No problem`, `Happy to go deeper`, `Got it`, `Let me break it down`, `Here's how it works`) successfully removed those exact phrases — but Marina REPLACED them with a different set of reflex validation phrases. Calvin's live sample:

- `Nice, Curaçao is home base for us too.`
- `WhatsApp works perfectly.`
- `Got it, so you have WhatsApp and email.`  ← `Got it,` slipped through despite Brief 258
- `That's a solid volume.`
- `Classic repeated questions.`

Calvin: *"This pattern feels artificial. A human does not validate every input before answering."* The deeper issue is structural — Marina is using a reflex template where EVERY reply opens with a validation-acknowledgement, then a fact, then an explanation, then a follow-up question. The Brief 258 ban hit one phrase pool; the SHAPE of the reflex pattern stayed.

Three additional refinements Calvin called out in the same addendum:

1. **Rhythm variation** — sometimes answer directly with no preface, sometimes ask a short next question, sometimes acknowledge briefly. Not every turn needs all three. Vary sentence count: one sentence + question; two short sentences; rarely a paragraph.

2. **Reduce salesy certainty** — phrases like `WhatsApp works perfectly` sound too polished. Better: `WhatsApp is a good starting point`. The "works perfectly" register is a brochure tell.

3. **Contradiction handling** — when the customer contradicts themselves (e.g., says "I don't have WhatsApp" then later says "WhatsApp"), Marina should clarify naturally rather than silently accepting both as true. Today she just accepts the most recent statement, which reads as inattentive.

Three concrete before/after example pairs from Calvin's addendum are included verbatim in Instructions step 1d below.

This is a tenant-config edit to `clients/unboks/config/client.json::agent_persona.freeform_notes` (currently 26,516 chars post-Brief-258 + follow-up). No code change.

## Why This Approach

Three options considered:

1. **Extend the Brief 258 "WhatsApp chat tone" section with anti-validation-reflex + rhythm + contradiction rules (chosen)** — keeps the entire tone direction in one place where Calvin already directed it. The structural reflex shape (validation → fact → explanation → question) is what's left after Brief 258 narrowed one phrase pool; this brief widens the rule from "ban specific phrases" to "ban the always-validate reflex pattern." Smallest change, lowest blast radius, uses the same `_build_agent_persona_block()` integration that Brief 258 already proved works.

2. **Code-side post-processing strip on Marina's output** — match validation phrases with regex and rewrite. Rejected: the SHAPE of the reflex (always opening with acknowledgment) cannot be captured by regex without false positives (sometimes "Got it," IS the right reply); and it would violate Rule 2 (Python classifying language). The right place to fix template-shape behavior is in the prompt.

3. **Change Marina's temperature / sampling** — make replies less deterministic. Rejected: temperature changes affect all aspects of generation, not just opening structure. Risks degrading factual accuracy on services / pricing / FAQ answers. The targeted fix is prompt-side guidance about reply shape, not a model-parameter change.

Trade-off accepted: prompt rules cannot perfectly enforce "vary rhythm" — Claude may still drift back to the validation pattern on certain inputs. The brief acknowledges this in Success Condition: this is round-3 of a tone fix, and tone fixes are inherently iterative. If Brief 259 doesn't close the loop, a round-4 brief can add more specific banned-phrase patterns, more example pairs, or a sentence-level structural rule.

## Instructions

1. **Edit `clients/unboks/config/client.json` — extend the existing Brief 258 "WhatsApp chat tone (issue #28 direction):" section** in `agent_persona.freeform_notes`. Four surgical changes:

   **(a) Extend the "Banned reflex openers" list** with the new patterns Calvin called out. Change from the current 6-phrase list to include the new entries. New full list:

   ```
   Banned reflex openers:
   Do not start replies with "Good question," "No problem," "Happy to go deeper," "Got it," "Let me break it down," "Here's how it works," "Nice," "That's a solid," "Classic," "Perfect," or any equivalent always-validate / always-acknowledge opener. Use them at most rarely, and never as a reflex opener. Never start two consecutive replies with the same opener. The underlying reflex you're avoiding is "validate-then-answer on every turn" — a human does not validate every input before answering. Sometimes just answer.
   ```

   **(b) Add a new "Reply rhythm" section** immediately after "Format and length for WhatsApp:". Insert:

   ```
   Reply rhythm:
   Vary the shape of replies. Not every turn needs a validation, a fact, an explanation, and a follow-up question. Mix it up:
   - Sometimes answer directly with no preface. Just the answer.
   - Sometimes ask a short next question with no validation.
   - Sometimes acknowledge briefly, then answer. Acknowledge means one short clause, not a full sentence of validation.
   - Sometimes give a fact and stop, without asking anything next.
   Vary sentence count too: one sentence with a short question; two short sentences; rarely a paragraph. The signal you've drifted back to template-mode is if three consecutive replies all open with an acknowledgment + fact + question.
   ```

   **(c) Add a new "Reduce salesy certainty" rule** as its own line within the "Format and length for WhatsApp:" block (append to the existing bullet list there):

   ```
   - Reduce salesy certainty. Phrases like "works perfectly," "exactly what you need," "this is the solution," "the perfect fit" sound too polished. Prefer "is a good starting point," "usually helps most with," "can take some of that off your plate." When you're not sure, say so; when you are sure, sound matter-of-fact, not brochure-confident.
   ```

   **(d) Add a new "Contradiction handling" section** after "Poor-fit lead handling:". Insert:

   ```
   Contradiction handling:
   When the customer contradicts something they said earlier (e.g., "I don't have WhatsApp" then later mentions "WhatsApp," or "I get a few messages" then later "we get hundreds a day"), do not silently accept the latest statement. Briefly clarify, one short question. Example (mirror the shape, do not copy verbatim): "Earlier you mentioned you don't use WhatsApp. Was that a recent change, or did I misread?" Do not make a big deal of it; do not sound accusatory; do not lecture. Just one quick clarifying question, then continue.
   ```

   **(e) Add three new before/after example pairs to the existing "Examples of better phrasing (mirror these, do not copy verbatim):" block**, appended after the existing example pairs and before "Identity rules unchanged:". The framing "mirror these, do not copy verbatim" from the existing block header applies to all pairs including these new ones — Claude treats them as few-shot guidance, not templates. Calvin's pairs verbatim from his addendum:

   ```
   - Avoid: "Nice, Curaçao is home base for us too. For a bakery..." Prefer: "For a bakery, this usually helps most with repeated messages: hours, prices, custom orders, and what is available that day. Where do most customers contact you now?"
   - Avoid: "That's a solid volume. At 300 messages a week..." Prefer: "300 a week is enough for this to matter. If many are repeats, your AI Agent can take a lot of that off your plate. What do people ask most?"
   - Avoid: "Classic repeated questions. Those are exactly what your AI Agent handles well..." Prefer: "Those are the right kind of questions for your AI Agent: opening hours, lunch break, and prices. We would put those answers into your intake, then the agent can reply to customers without you typing the same thing every day. Want to do a quick setup call?"
   ```

2. **No other changes**. Existing Brief 258 sections (Pronoun and terminology, Poor-fit lead handling, Identity rules) remain unchanged. Brief 258's existing example pairs (5 of them) remain; Brief 259 appends 3 more.

3. **No code changes**. `_build_agent_persona_block()` at `wtyj/agents/marina/marina_agent.py:230` (definition) / `:584` (injection site) continues to inject the full `freeform_notes` into the system prompt unchanged.

## Tests

This brief is a pure data extension of Brief 258's `freeform_notes` edit. Same constraints apply: the only deterministic test that doesn't reduce to a Brief 236-banned source-string grep is the JSON-loads / builder-runs guardrail, which Brief 258 already added at `wtyj/tests/marina/test_149_agent_persona.py::test_brief_258_unboks_persona_block_builds_without_error`. That existing test continues to cover the failure mode Brief 259 could introduce (malformed JSON edit). No new test needed.

The behavioral verification is Calvin's live retest captured in Success Condition. Tone changes for LLMs are not deterministically unit-testable without an LLM-output judge.

## Success Condition

After Brief 259 deploys:
- Calvin re-runs the bakery acceptance script from issue #28 (`hello` → `what is unboks` → `how does it work?` → `i have a small bakery in curacao` → `300 approx` (messages/week) → `wat time are we open , do we close for lunch and prices` → etc.).
- Marina's replies show NONE of: `Nice, ...`, `Got it, ...`, `That's a solid ...`, `Classic ...`, `Perfect ...`, `works perfectly` as openers or close-equivalents on EVERY turn. They may appear occasionally on the right turn; the test is "do they appear as a reflex pattern across 3+ consecutive replies?"
- Some replies start directly with the answer or a question, no validation preface.
- Sentence-count varies: at least one one-sentence + one-question reply; at least one two-short-sentences reply; no paragraph that reads brochure-style.
- If Calvin intentionally contradicts an earlier statement, Marina asks one short clarifying question rather than silently accepting both.
- All 4 production containers healthy post-deploy.

## Rollback

```
ssh root@108.61.192.52 "bash /root/wtyj/scripts/rollback.sh all"
```

Canonical rollback per `wtyj/briefs/infra.md:188`. Restores `wtyj-agent:previous` image (pre-Brief-259 freeform_notes) and restarts all four production containers. The on-disk `clients/unboks/config/client.json` in the repo is reverted by `git revert <Brief 259 source SHA>` if needed. Pure data change; no schema migration, no destructive operations. If Brief 259's prompt additions make Marina worse rather than better, rollback returns to the Brief 258 + clarification state in <30s.
