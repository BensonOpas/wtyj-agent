# BRIEF 322 — Put Agent-needs-help cases in Ali Today
**Status:** Approved | **Files:** `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/tests/agents/test_ali_quote_leads.py` | **Depends on:** Briefs 318, 321 | **Blocks:** none

## Context

Ali customer W has two unresolved soft relay records with `status='sent'`. The Conversations
screen correctly labels the case "Agent needs help", but Today says there are zero staff
actions. The Quote Leads operations projection only checks `notification_type='escalation'`;
soft relays use `notification_type='relay'`, so W is incorrectly projected as waiting on the
customer.

## Why This Approach

Today must be driven by the server-owned operations contract. Both unresolved escalations and
unresolved relays require an operator decision or answer, so both belong in the same staff
attention set. The frontend then consumes one stable `answer_customer` action without
reimplementing notification-table semantics.

Fetching the escalation list separately in Today was rejected because it would create two
competing workflow authorities and miss the customer lifecycle context. Renaming relay rows
to escalation was rejected because soft relay and hard takeover remain meaningfully different
inside Conversations.

## Instructions

1. Treat unresolved `escalation` and `relay` notifications as active staff attention.
2. Preserve their existing mode, status, reply, resolve, and human-takeover behavior.
3. Project either type as `responsibleParty='staff'`, `operatorAction='answer_customer'`, and
   `actionTarget='conversation'` through the existing operations contract.
4. Keep resolved rows out of the action queue.
5. Add a regression test using the live production shape: a sent soft relay.

## Tests

1. A `relay` row with `status='sent'` produces `needs_an_answer` and a staff-owned
   `answer_customer` operation targeting the conversation.
2. Existing escalation, quote, reservation, and resolved-customer projection tests pass.
3. Run the complete agent test suite.

## Success Condition

W and every future unresolved Agent-needs-help case appear in Today as staff work, while
resolved cases disappear from the action queue.

## Rollback

Revert Brief 322 and redeploy. No schema or customer-data rollback is required.
