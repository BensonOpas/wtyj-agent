# Brief 277 — Ali natural summary confirmations

**Status:** Implemented | **Files:** `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/tests/agents/test_ali_quote_workflow.py`, `wtyj/tests/agents/test_ali_quote_intake_dispatch.py` | **Depends on:** Briefs 157, 271 | **Blocks:** Ali confirmed-summary production flow

## Context

Production accepted only a narrow exact confirmation set. Natural replies such
as “yes it does” and “yes, it does look right” were rejected and routed back to
the summary branch, so customers saw the same summary repeatedly.

## Goal

Accept clear natural EN/NL/PAP/DE confirmations deterministically while
rejecting negations, questions, uncertainty, qualifications, corrections, and
new rental or supplement details. A valid confirmation starts or reuses exactly
one quote and never repeats the summary.

## Scope

- Expand the exact normalized multilingual affirmative allowlist.
- Return machine-readable decision reason codes without retaining message text.
- Emit a sanitized confirmation-decision event containing only outcome, reason,
  summary version, and hash prefix.
- Return the existing preparing message for replayed confirmations after a quote
  already exists, without starting another worker.
- Preserve corrected-summary hashing, deterministic quote idempotency, and the
  customer-only three-minute final WhatsApp delivery boundary.
- Do not add fuzzy matching, model classification, schema changes, or customer
  data to logs.

## Why This Approach

An exact normalized allowlist safely covers natural confirmation variants while
remaining fail-closed. Substring or fuzzy matching could falsely accept mixed
corrections; a model classifier would make a deterministic safety boundary
nondeterministic. Existing quote uniqueness and persisted flags already provide
the correct replay ownership.

## Tests

1. Exact production phrases and common natural confirmations pass in EN/NL/PAP/DE.
2. Negations, corrections, qualifications, uncertainty, questions, and new
   detail messages fail with safe reason codes.
3. A natural confirmation starts one worker and returns the preparing message.
4. Replayed confirmation returns the preparing message without a duplicate worker.
5. Changed rental details produce one corrected summary and a new hash.
6. Decision logging contains no message text or customer PII.
7. Existing pricing, PDF, email, WhatsApp, timing, and replay tests remain green.

## Success Condition

Production accepts the reported natural affirmative phrases, rejects correction
examples, emits only sanitized decision metadata, and creates/sends no duplicate
quote while keeping the final customer WhatsApp quote gated for three minutes.

## Rollback

Revert the issue #181 commit and redeploy the previous image if any false
confirmation is observed. Do not disable the whole Ali conversation flow unless
customer safety requires it.

Tracking: GitHub issue #181.
