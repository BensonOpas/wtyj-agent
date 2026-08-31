# BRIEF 320 — Nick single policy authority and detailed-care truth guards
**Status:** Approved | **Files:** `wtyj/agents/marina/marina_agent.py`, `wtyj/tests/agents/test_319_ali_multi_question_care.py` | **Depends on:** Brief 319, J3-N2-02 ICP overrides | **Blocks:** none

## Context

The first live synthetic check for Brief 319 proved that Nick now recognizes and answers
long multi-question messages, but also exposed a policy-authority conflict. Ali's tenant-local
dashboard Source of Truth said the booking deposit is 15% and is paid through a WhatsApp
payment link. An older central ICP Source of Truth was injected later in the same prompt and
said 25% by bank transfer. The model followed the later stale instruction.

The same check showed three smaller quality gaps: Nick used canned meta-praise, calculated an
unofficial total from a daily catalog rate instead of waiting for the quote engine, and kept
only the first of two supplied driver ages in the structured quote facts.

## Why This Approach

Use one business-policy authority per prompt. When tenant-local dashboard Source of Truth
exists, it replaces central ICP SOT entries; ICP tone and escalation settings remain active.
When dashboard SOT is empty, ICP SOT remains the compatibility fallback. Place the selected
dashboard SOT after generic rules but before live catalog, persisted workflow and Ali workflow
rules so current facts cannot be overridden by generic examples while server state still wins.

Keeping both SOT collections and merely telling the model which is newer was rejected because
contradictory facts would remain in the context. Hardcoding Ali's deposit or insurance answers
in Python was rejected because future rental tenants need different policies. A Python
question counter or long-message classifier was rejected because Claude already understands
the message in the one permitted model call and supports every tenant language.

## Instructions

1. During prompt assembly, select tenant-local dashboard SOT when it contains valid blocks.
   Suppress central ICP SOT entries in both their early and final render positions for that
   prompt, while preserving ICP tone and escalation overrides.
2. Keep ICP SOT as the fallback for tenants whose dashboard Source of Truth is empty.
3. Render the selected dashboard SOT late enough to override generic examples, but keep the
   current live catalog, persisted workflow state and Ali workflow contract authoritative.
4. Strengthen Ali's detailed-message protocol so Nick avoids canned compliments, starts with
   a task-specific acknowledgement, answers every point, and never announces that the
   customer's message was long or detailed.
5. When no immutable official quote total exists, Nick must not multiply a daily rate or
   invent a conversational total. He explains that he is preparing the official quote and
   asks at most one missing quote field after answering all policy questions.
6. Preserve multiple supplied driver ages: use the main driver's age in `driver_age` and
   retain additional driver ages in `comments` without overwriting other volunteered notes.
7. Keep one Claude call, tenant isolation, multilingual understanding and the existing
   deterministic quote workflow unchanged. Do not contact a real customer during tests.

## Tests

1. Seed dashboard SOT with a current policy and fake ICP SOT with a conflicting stale policy.
   Build the real system prompt and verify only the current policy is present, the dashboard
   block has late precedence, and ICP tone still survives.
2. Build a prompt with an empty dashboard SOT and verify ICP SOT remains available as fallback.
3. Verify the Ali contract covers natural acknowledgement, no unofficial total calculation,
   full multi-driver fact preservation and the one-new-question rule.
4. Run focused Ali prompt/quote tests and the complete test suite.
5. After deployment, run both owner-provided messages through the live Ali agent in a
   non-delivery synthetic call and inspect the answer and extracted fields.

## Success Condition

Both detailed owner examples receive complete, ordered, current-policy answers with all quote
facts retained, no stale 25% policy, no invented total, and at most one missing-field question.

## Rollback

Revert the Brief 320 commit and redeploy. Restore the backed-up Ali central ICP state only if
the operator explicitly wants the superseded 25% policy; no schema or customer-data rollback
is required.
