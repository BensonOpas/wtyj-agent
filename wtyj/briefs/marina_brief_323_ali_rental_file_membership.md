# BRIEF 323 — Make rental-file state own Ali customer membership
**Status:** Approved | **Files:** `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/tests/agents/test_ali_quote_leads.py` | **Depends on:** Briefs 318, 321 | **Blocks:** none

## Context

Ali Customers is projected from structured WhatsApp rental state. Brief 321 stopped a
resolved human relay from hiding Federico, but the query still excludes the generic
conversation status `closed`. That repeats the same ownership mistake: inbox work status is
being used to decide whether a rental file exists.

The rental lifecycle already has its own authoritative reservation projection and Closed tab.
A conversation may be closed while its rental file remains relevant, including completed,
cancelled, declined, or superseded reservations that operators must still be able to find.

## Why This Approach

Booking state owns customer membership. Conversation status controls inbox visibility and
operator handoff state only. Therefore `resolved` and `closed` remain visible in Customers;
only explicit archive, deletion, or blocking hides a rental file from the active customer
projection.

Copying conversation status into reservation lifecycle was rejected because it would create
two competing closure authorities. Deleting or rewriting existing statuses was rejected
because the data is valid; only the projection is wrong.

## Instructions

1. Include structured rental files whose generic conversation status is `resolved` or
   `closed`.
2. Continue excluding records that are deleted, blocked, or explicitly archived.
3. Keep rental completion and cancellation represented by the existing reservation
   operations lifecycle and the Customers Closed tab.
4. Do not mutate customer, conversation, quote, or reservation data.
5. Add regression tests for generic `closed`, resolved relay, deletion, blocking, and archive.

## Tests

1. A generic closed conversation with booking state remains in Quote Leads/Customers.
2. Resolving a staff escalation keeps the rental file visible.
3. Deleted, blocked, and archived conversations remain excluded.
4. Run the complete agent suite.

## Success Condition

Customer membership follows structured rental state, and inbox task closure can no longer
make a rental customer disappear. Completed rentals remain discoverable through Closed.

## Rollback

Revert Brief 323 and redeploy. No schema or customer-data rollback is required because this
change performs no data mutation.
