# BRIEF 319 — Nick high-engagement multi-question care
**Status:** Approved | **Files:** `wtyj/agents/marina/marina_agent.py`, `wtyj/tests/agents/test_319_ali_multi_question_care.py`, `wtyj/tests/social/test_message_reliability_p0.py` | **Depends on:** Brief 284 / #213, Brief 262 / source-of-truth storage | **Blocks:** none

## Context

Ali customers sometimes send one carefully written WhatsApp message containing their
rental facts and six or more direct questions. These messages signal strong engagement
and deserve a complete, careful response. The current Ali prompt permits a longer reply,
but it does not define a premium response protocol. Nick can therefore answer only one
question, ask for a fact the customer already supplied, or rush back into quote intake.

The operator has also approved Ali-specific policy answers in the dashboard Source of
Truth. The dashboard persists those blocks, but the booking agent does not currently read
that store. Nick therefore cannot reliably use the operator-approved facts when answering
the customer's detailed questions.

## Why This Approach

Keep detection and response composition inside Nick's existing single model call. The
model can understand questions across every supported language and can distinguish a
long list of rental questions from unrelated punctuation. Python remains responsible for
state and delivery, not language classification.

Inject the existing tenant-local Source of Truth into the same system prompt. This makes
the dashboard's “Agent knowledge” label truthful and keeps business policy out of source
code. A hardcoded Ali answer table was rejected because each future rental tenant needs
its own policies. A question-mark counter and keyword classifier were rejected because
they fail on multilingual prose and violate the architecture's no-language-classifier
rule. A second model call was rejected because the runtime contract permits one model call
per inbound message.

## Instructions

1. Add a bounded renderer for the tenant-local `source_of_truth` blocks. Preserve block,
   subsection and item structure, ignore empty values, and return an empty block on any
   read error. Treat this operator-curated content as authoritative business policy while
   retaining existing workflow-state and live-catalog authority.
2. Include the rendered Source of Truth in every tenant's system prompt. Isolation remains
   per-container/per-database; never use a global cache or a tenant identifier supplied by
   the browser.
3. Add an Ali-only, highest-priority high-engagement protocol. A detailed message or a
   message with multiple direct questions must cause Nick to:
   - briefly recognize the customer's effort without canned praise;
   - extract and retain every rental fact already supplied;
   - answer every question directly, in the order asked;
   - use a numbered structure when it improves scanability;
   - separate any genuinely unknown item, say it needs checking, and never invent it;
   - only after all answers, explain the quote progress and ask at most one missing field.
4. Clarify that the one-question-at-a-time rule limits new questions Nick asks. It never
   permits Nick to ignore questions the customer asked.
5. Let a high-engagement WhatsApp reply exceed normal booking length when needed for a
   complete answer, while keeping each answer concise, warm, precise and mobile-readable.
6. Preserve the published catalog, workflow state, media-first vehicle selection, quote
   authority, first-person voice, tenant isolation and one-model-call architecture.
7. Do not contact any real customer during testing.

## Tests

1. Store nested Source of Truth blocks in a temporary tenant database and build the real
   system prompt. Assert the authoritative facts and structure are present.
2. Point the same prompt builder at a second empty tenant database and assert the first
   tenant's facts are absent.
3. Verify malformed/empty Source of Truth fails closed and never prevents a reply.
4. Build the Ali prompt and full user prompt using both owner-provided detailed messages.
   Assert the runtime contract requires ordered complete answers, fact preservation,
   premium care, honest unknown handling and no more than one new intake question.
5. Run the focused Ali quote-intake tests and full Marina/agent regression suite.
6. Keep the existing recovery test scoped to the synthetic inbound it creates. Other
   suites may leave unrelated stale synthetic rows in the shared test database; those rows
   must not make a correctly superseded inbound look recoverable or fail the release gate.

## Success Condition

In a synthetic Ali WhatsApp conversation, each detailed multi-question message receives
one complete, ordered, tenant-policy-grounded answer before Nick resumes the official
quote flow, without asking again for facts the customer already provided.

## Rollback

Revert the Brief 319 commit and redeploy. Source of Truth data remains stored and editable
in the tenant database; only its prompt injection and the Ali response protocol are
removed, so no data migration is required.
