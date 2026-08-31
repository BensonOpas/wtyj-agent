# BRIEF 325 — Ali quote-summary delivery recovery and truthful status
**Status:** Approved | **Files:** `wtyj/agents/social/webhook_server.py`, `wtyj/shared/state_registry.py`, `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/agents/marina/marina_agent.py`, `wtyj/tests/social/test_message_reliability_p0.py`, `wtyj/tests/agents/test_ali_quote_workflow.py`, `wtyj/tests/agents/test_319_ali_multi_question_care.py` | **Depends on:** Briefs 280, 283, 285, 319, 320 | **Blocks:** none

## Context

Ferla Silvina supplied the last required quote fact at 18:16 UTC on 2026-08-31. The Ali
planner produced a complete `SUMMARY_PRESENTED` action, but Zernio rejected the outbound
send and the inbound ledger was immediately finalized as `send_failed`. Ordinary summary
delivery had no automatic retry. The provider-confirmed summary anchor therefore was never
committed, no confirmation control reached the customer, and no quote record was created.

Later customer turns were planned as ordinary `DISCOVERY` replies because the complete draft
had not changed. Nick then said the quote was in process even though no active quote existed.
This combined a delivery reliability gap with a workflow truth gap and left the customer
waiting indefinitely.

## Why This Approach

Reuse the existing durable inbound ledger and stale-turn recovery loop. A provider-rejected
Ali turn remains recoverable and is retried with the same provider message and action
idempotency keys. Retries are bounded; exhaustion becomes visible Technical attention for
structured controls/media and the existing hard delivery failure for other Ali turns.
Separately, make the deterministic planner re-present any complete current summary that lacks
a provider-confirmed delivery anchor. Add a structured quote-status intent so multilingual
messages such as “I am waiting for the quote” route on model-provided structure rather than
Python language matching.

A new outbound-outbox subsystem was rejected because the existing ledger already durably
stores the inbound event needed to reconstruct the exact server-owned action. A synchronous
second send was rejected because it is not restart-safe. Generating a quote without customer
confirmation was rejected because it would bypass the approved summary and Send My Quote
gate.

## Instructions

1. In `wtyj/agents/social/webhook_server.py:200`, distinguish recoverable Ali provider-send
   failures from ordinary terminal failures. Keep the inbound batch in the durable recovery
   lifecycle, retry it after the existing stale interval, and convert it to the existing
   operator-visible delivery failure only after a bounded number of attempts. Preserve Brief
   319's Technical attention ownership for structured controls and vehicle media.
2. In `wtyj/shared/state_registry.py:1438`, return the claimed row's prior reason so recovery
   can identify provider-send retries without introducing a new schema or tenant-global
   state. Preserve attempt counts, idempotency and newer-outbound supersession.
3. In `wtyj/agents/social/ali_quote_workflow.py:3030`, add structured
   `request_quote_status` handling. An active quote may report its persisted status; a
   complete rental without an active quote must re-present the current summary and
   confirmation action. Before the generic fallback, re-present a complete current summary
   whenever no provider-confirmed current-summary anchor exists.
4. In `wtyj/agents/marina/marina_agent.py:1127`, teach the one Claude call to label multilingual
   quote-waiting/status messages as `request_quote_status`. Forbid claims that a quote is
   being prepared or processed unless persisted workflow state contains an active quote.
5. Preserve the one-model-call rule, tenant isolation, provider-confirmed state commits,
   current summary hash/version validation and the signed Send My Quote gate. Do not create a
   quote automatically and do not contact real customers during automated tests.

## Tests

1. A failed Ali summary send remains unconfirmable but is recoverable instead of terminal.
2. Recovery retries a provider-failed summary, commits it exactly once on provider success,
   and sends at most one recovery heartbeat.
3. Repeated provider failures are bounded and become operator-visible Technical attention
   for structured delivery, never the misleading Agent needs help state.
4. A complete draft with no current provider-confirmed summary is always planned as a
   summary, including a structured quote-status request; an actual active quote returns only
   its persisted processing status.
5. Prompt/schema tests prove quote-status intent exists and Nick cannot announce processing
   without an active quote. Run the focused social and Ali workflow suites, then the complete
   suite.

## Success Condition

A provider-rejected Ali summary is recovered automatically or escalated after bounded retries,
and no customer can be told that an official quote is processing unless a persisted quote
actually exists.

## Rollback

Revert the Brief 325 commit and redeploy. Existing inbound rows require no schema rollback;
rows already in recovery remain compatible with the previous stale-turn worker.
