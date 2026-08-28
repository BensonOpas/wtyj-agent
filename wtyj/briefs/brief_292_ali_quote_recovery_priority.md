# BRIEF 292 — Prioritize the Latest Confirmed Replacement Quote
**Status:** Approved | **Files:** `agents/social/ali_quote_recovery.py`, `tests/agents/test_ali_quote_recovery_priority.py` | **Depends on:** Brief 291 | **Blocks:** production proof for issue #288

## Context

Brief 291 deployed a supervised recovery process, but the affected owner/test
conversation still had no second staff quote email after the recovery startup
grace. The bounded scanner selected rows in oldest-first order and filtered
retryability only after applying its SQL limit. A backlog of old terminal
`attention_required` rows could therefore fill the scan window and prevent a
newer confirmed replacement quote from ever being examined.

The previous outer quote processor also historically collapsed every
`AliQuoteError` into `processor_unconfigured`. Existing rows with that legacy
code may actually represent a temporary provider or delivery failure and were
excluded from recovery even though the tenant is currently configured and its
first quote was generated successfully.

## Why This Approach

Keep the durable lease/recovery architecture and correct only candidate
selection and legacy compatibility. Newest-first scanning makes the most recent
customer promise the first recovery candidate without weakening idempotency or
supersession. Treat the legacy collapsed error as retryable only under the
existing attempt cap and exponential backoff.

Rejected alternative: unbounded scanning of every historical quote on each
five-second poll. That would create unnecessary SQLite load and still would not
repair the incorrectly classified legacy row.

## Instructions

1. Order bounded candidate scans by descending quote ID so recent confirmed
   replacement quotes cannot be starved by historical terminal rows.
2. Document the newest-first invariant in the recovery module.
3. Add the legacy `processor_unconfigured` code to the bounded retry set. Keep
   the existing maximum attempts and backoff; do not make retries unlimited.
4. Preserve current exclusions for superseded rows, integrity failures, and all
   other non-retryable terminal errors.
5. Preserve customer and rental privacy in logs and tests.

## Tests

1. Create more old non-retryable attention rows than the scan limit, then a
   newer stale confirmed replacement. The scan must return the replacement.
2. Prove a legacy `processor_unconfigured` row is recoverable below the attempt
   cap and blocked at the cap.
3. Run the full repository suite and the normal canary/production pipeline.

## Success Condition

A newly confirmed replacement quote is always visible to the bounded recovery
scanner and a legacy misclassified row receives a bounded recovery attempt.

## Rollback

Revert the merge commit and redeploy. Brief 291 recovery remains active with
its previous oldest-first and narrower retry behavior; no quote data changes are
required.
