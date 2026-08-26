# Marina Brief 279 — Ali confirmation escape

## Problem

Ali's newest structured rental correction can be applied correctly while the
automatic summary response still suppresses a requested vehicle visual. The
same automatic response also repeats an unchanged summary for ordinary
questions or hesitation.

## Required behavior

- Keep one Claude call per inbound turn.
- Clear confirmations continue through the deterministic quote path.
- A structured vehicle recommendation outranks automatic summary presentation
  on that turn, including when the turn also changes the stored selection.
- Ordinary questions, rejection, and hesitation keep Claude's concise reply;
  they do not repeat an unchanged summary.
- Repeat the summary only when the same structured response explicitly marks a
  repeat-summary request.
- A valid correction without an immediate recommendation still produces one
  corrected summary and requires confirmation before a replacement quote.
- Preserve catalog validation, recommendation idempotency, immutable quote
  rows, multilingual behavior, and sanitized logging.

## Boundaries

No new model call, recommendation engine, price source, availability claim,
quote mutation, delivery-timing change, or static customer conversation
template. Reuse the existing Ali catalog, correction action, recommendation
plan, summary hash, and confirmation parser.

## Rollback

Revert the implementation commit and redeploy through the normal WTYJ
production pipeline. Existing persisted conversations and quote snapshots are
compatible because this change adds no storage schema or migration.
