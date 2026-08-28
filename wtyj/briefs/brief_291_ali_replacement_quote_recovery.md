# BRIEF 291 — Durable Ali Replacement-Quote Recovery
**Status:** Approved | **Files:** `agents/social/ali_quote_recovery.py`, `supervisord.conf`, `tests/agents/test_ali_quote_recovery.py` | **Depends on:** Ali quote workflow and signed summary confirmation | **Blocks:** final closure of GitHub issue #288

## Context

A live owner/test conversation received one official quote, then changed the
rental end date by fifteen days and confirmed a corrected summary. Nick said the
replacement quote was being prepared, but no second customer PDF or staff quote
email followed.

The confirmed quote row is already durable and immutable, and the quote
processor is idempotent per quote and delivery asset. The failure boundary is
process ownership: the inbound path starts a daemon thread, while the existing
restart recovery runs only once when the webhook server starts. A thread lost
after confirmation can therefore leave a valid `confirmed`, `pricing`,
`quoted`, `pdf_ready`, or `delivering` row without a running processor.
Retryable `attention_required` rows are also not continuously reclaimed.

## Why This Approach

Use the existing `ali_quotes` row as the durable queue record and add one small,
supervised recovery process. It scans only rows that have stopped making
progress, claims them through an additive SQLite lease table, and reuses the
existing `_process_production()` path. This preserves the current immutable
quote snapshot, provider idempotency key, accepted per-asset delivery states,
and three-minute customer boundary.

Rejected alternative: introduce a second quote/job state machine or message
broker. That would duplicate current truth and increase deployment risk. Also
rejected: immediately process every pending row in a second worker, because it
would race the normal inbound daemon during the intentional three-minute delay.

## Instructions

1. Add `agents/social/ali_quote_recovery.py` as an Ali-only supervised process.
2. Create an additive `ali_quote_processing_leases` table after the existing
   quote schema is ready. Lease acquisition must use `BEGIN IMMEDIATE`, reject
   an unexpired lease, and reclaim an expired lease after a crash.
3. Treat `confirmed`, `pricing`, `quoted`, and `pdf_ready` as abandoned only
   after a safety window. Do not reclaim `delivering` during the existing
   three-minute customer delay.
4. Retry `attention_required` only for bounded transient delivery/provider
   failures. Apply exponential backoff and a maximum attempt count. Never loop
   configuration, authorization, validation, or integrity failures.
5. Re-read the row after lease acquisition so a quote that progressed between
   scan and claim is not processed twice.
6. Renew the lease while processing and release it on every outcome. A process
   crash leaves an expiring lease that another supervisor instance can reclaim.
7. Reuse `ali_quote_workflow._process_production()` so pricing, rendering,
   staff email, customer image/PDF, post-quote actions, supersession checks,
   signed URLs, and per-asset idempotency remain authoritative.
8. Log only quote public ID, status, attempt count, safe error code, and lease
   outcome. Never log customer, phone, dates, vehicle, locations, or pricing.
9. Start the process from `supervisord.conf`. Exit normally for non-Ali tenants
   or when `features.ali_quote_recovery_enabled` is explicitly false.
10. Give the normal webhook startup/daemon processing a grace period before the
    recovery scan begins. Continue scanning for the lifetime of the container.

## Tests

1. Deliver an initial synthetic quote, create a second immutable quote after a
   +15-day end-date change, abandon the second row, and prove recovery completes
   only that second row exactly once.
2. Prove an unexpired lease blocks a parallel worker and an expired lease is
   reclaimed.
3. Prove retryable `attention_required` rows are requeued with backoff, while
   non-retryable and max-attempt rows are not.
4. Prove `delivering` is not reclaimed during the three-minute customer delay
   and becomes recoverable only after the stale threshold.
5. Prove the switch is Ali-only and reversible. Run the full repository suite.

## Success Condition

Every provider-confirmed corrected Ali summary has a durable replacement quote
that is automatically processed or reclaimed after worker loss, without
resending the original quote or creating a third quote on replay.

## Rollback

Set `features.ali_quote_recovery_enabled` to `false` for Ali and restart the
container, or revert the merge commit and redeploy. Preserve all quote rows,
leases, immutable snapshots, attempts, and accepted delivery states.
