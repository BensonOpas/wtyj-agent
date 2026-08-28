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
`AliQuoteError` into `processor_unconfigured`. Existing replacement rows with
that legacy code may actually represent a temporary provider or delivery
failure and were excluded from recovery even though the same conversation has
an earlier provider-accepted quote.

## Why This Approach

Keep the durable lease/recovery architecture and correct only candidate
selection and narrow legacy compatibility. Newest-first scanning makes the most
recent customer promise the first recovery candidate without weakening
idempotency or supersession. A `processor_unconfigured` row is eligible only
when it is a later summary version in a conversation with an earlier accepted
quote, and it remains subject to the existing attempt cap and exponential
backoff.

Rejected alternative: mark `processor_unconfigured` generally retryable. That
would loop genuine configuration failures and weaken the fail-closed behavior
for first quotes and unrelated conversations. Also rejected: unbounded scanning
of all historical quotes on every five-second poll.

## Instructions

1. Order bounded candidate scans by descending quote ID so recent confirmed
   replacement quotes cannot be starved by historical terminal rows.
2. Document the newest-first invariant in the recovery module.
3. Recognize legacy `processor_unconfigured` only when the row is summary
   version 2 or later and the same conversation has an earlier quote whose
   WhatsApp PDF was provider-accepted.
4. Keep the existing maximum attempts and backoff; do not make retries
   unlimited.
5. Preserve current exclusions for first-quote configuration failures,
   superseded rows, integrity failures, and all other non-retryable errors.
6. Preserve customer and rental privacy in logs and tests.

## Tests

1. Create more old non-retryable attention rows than the scan limit, then a
   newer stale confirmed replacement. The scan must return the replacement.
2. Prove a versioned legacy replacement with an accepted predecessor is
   recoverable below the attempt cap and blocked at the cap.
3. Preserve the existing regression that an ordinary first-quote
   `processor_unconfigured` row is non-retryable.
4. Run the full repository suite and the normal canary/production pipeline.

## Success Condition

A newly confirmed replacement quote is always visible to the bounded recovery
scanner, while only the narrowly proven legacy replacement case receives a
bounded compatibility retry.

## Rollback

Revert the merge commit and redeploy. Brief 291 recovery remains active with
its previous oldest-first and narrower retry behavior; no quote data changes are
required.
