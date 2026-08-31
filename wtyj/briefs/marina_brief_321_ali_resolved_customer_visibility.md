# BRIEF 321 — Keep resolved Ali customers visible
**Status:** Approved | **Files:** `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/tests/agents/test_ali_quote_leads.py` | **Depends on:** Brief 318 | **Blocks:** none

## Context

Ali's Customers page is projected from WhatsApp booking state. A live customer, Federico
Barcio, disappeared from Customers after staff resolved a pending relay even though his
rental intake remained active and he was still visible in Conversations.

The escalation resolver correctly uses `conversation_status.status = 'resolved'` to mean
that the operator work item is complete and Nick may resume. The Customers projection
incorrectly interpreted the same operational status as a closed customer lifecycle and
filtered the customer out.

## Why This Approach

Customer membership remains anchored to the tenant's booking state. Resolving a staff task
must not erase or hide that state, so `resolved` is no longer an exclusion status for the
Customers projection. Deleted, blocked, explicitly closed, and archived conversations remain
excluded.

Changing Federico's status back to pending was rejected because it would falsely reopen a
completed staff task and the same disappearance would recur the next time an escalation was
resolved. Adding a second customer table was rejected because the booking state is already
the canonical tenant-scoped customer source.

## Instructions

1. Include booking-state customers whose operational conversation status is `resolved`.
2. Continue excluding deleted, blocked, closed, and archived conversations.
3. Do not reopen resolved escalations or change Nick's takeover-release behavior.
4. Add a regression test that resolves a real pending escalation and proves the customer
   remains in the Quote Leads/Customers projection.

## Tests

1. Verify deleted, blocked, closed, and archived conversations remain excluded.
2. Resolve a staff escalation through `resolve_conversation_from_escalation`, verify its
   operational status is `resolved`, and verify its customer remains visible exactly once.
3. Run the complete agent test suite.

## Success Condition

Federico and every other active booking-state customer remain visible in Customers after a
staff escalation or relay is resolved, without reopening the completed work item.

## Rollback

Revert Brief 321 and redeploy. No schema or customer-data rollback is required.
