# BRIEF342 — Separate review FAQ answers from unverified staff prose
**Status:** Implemented, independently reviewed | **Files:** `wtyj/agents/social/mermaid_understanding.py`, `wtyj/agents/social/mermaid_reservation_workflow.py`, `wtyj/tests/agents/test_mermaid_audit_policy.py`, `wtyj/tests/social/test_mermaid_model_recovery.py`, `wtyj/tests/social/test_mermaid_soft_review.py` | **Depends on:** 178ba56 | **Blocks:** final candidate verification

## Context
The preserved third run has two related leaks. BASE047 T5 labels a plain YES as question, bypassing the acknowledge-only queued-status guard. BASE045 T6 answers food/check-in but adds that staff are reviewing the request even though only a soft queue entry exists. Its structured status is none and its guest-question excerpt is empty. The actual record and separate semantic review remain unchanged in `output/remediation-342-2026-09-04/review-final12-en-de.md` outside this checkout.

## Why This Approach
The existing dedicated `other_question_reply` field already separates supported general-trip answers from authoritative status rendering. Require it for ordinary FAQ answers during review too. The workflow must never use the raw general reply for a pending-review follow-up, even if a model action or excerpt is wrong. Reject keyword inspection or a second model call: Python routes structured values and the existing recorded status. Missing dedicated FAQ content yields honest recorded queue/status copy, not a fabricated answer; this remains a model-extraction limitation and does not prove the question was answered.

## Instructions
1. Extend the schema description and prompt at `mermaid_understanding.py:24,87-93` to require a dedicated general-trip FAQ answer while human_review_pending, including status none. Keep ordinary non-review intake replies unchanged. A status-none generated reply remains nonempty for existing validation; this work does not widen the companion empty-critical-reply exception.
2. Replace the action-dependent no-question fallback near `mermaid_reservation_workflow.py:696` with a final pending-review response route: dedicated FAQ, if supplied, plus recorded handover status. No raw-reply fallback and no dependence on generic details/question/acknowledge labels or the excerpt. Existing calendar, wildlife, pickup, payment and delivery selectors retain their authoritative branches; these branches already discard raw prose.
3. Preserve security, explicit human requests, cancellation, canonical summaries, review-blocked decisions and operator/global send controls. Do not change guest-question evidence for confirmation, queue records or booking state.

## Tests
Use real temporary SQLite and structured model stubs across all six locales: food/check-in FAQ with empty excerpt and has_open_question true plus dedicated content; plain YES labeled acknowledge/question/details; missing, empty or whitespace FAQ never leaks raw active-staff claims. Reproduce these failures before implementation. Preserve protected calendar/wildlife/pickup/status routes and primary-action priorities. Confirm non-review ordinary FAQ still uses its normal reply. Update existing review-FAQ fixtures to the new documented dedicated-body contract. No paid calls or live actions.

Before implementation, the selected regressions produced 48 failures and 12 passes. Evidence is preserved at `output/remediation-342-2026-09-04/review-faq-isolation-before.txt` outside this checkout. The first focused gate then passed 256 cases with four expected failures in old raw-only post-review FAQ fixtures. Those two fixture sites now supply the dedicated FAQ body and expect the recorded queue text alongside it; no failure or control assertion was removed.

The final six-file gate passed 378 tests: audit policy, buffered recovery, soft review, pickup facts, confirmation/cancellation and booking UX. Four additional protected-route cases verify calendar, wildlife, coverage and pricing remain ahead of the review fallback. Parent independently reviewed the extended brief and runtime/test output before commit. Raw third-run evidence remains unchanged; no paid run or deployment is included in these results.

## Success Condition
Review follow-ups use only the dedicated supported FAQ body and recorded status; generic labels and omitted excerpts cannot expose raw staff-progress prose, and existing booking/send controls remain intact.

## Rollback
Revert this focused source/test/brief commit before release. No data migration, live repair or configuration change is introduced.
