# BRIEF342 — Keep dedicated FAQ answers on repeated review flags
**Status:** Deployed and verified at f220c3e; A4/A8 acceptance holds remain | **Files:** `wtyj/agents/social/mermaid_reservation_workflow.py`, `wtyj/tests/agents/test_mermaid_audit_policy.py`, `wtyj/tests/social/test_mermaid_model_recovery.py`, `wtyj/tests/fixtures/mermaid_review_faq_sdk_20260904.json` | **Depends on:** dc98142 | **Blocks:** candidate verification

## Context
The preserved compatibility run reports BASE043/044/045/046/048 T6 with correct food/check-in answers in `other_question_reply`, a nonempty `reply`, action question, status none, and `requires_human=true` during an existing soft review. BASE045 and BASE047 T4 also select wildlife_guarantee and have the same repeated flag, but their no-guarantee answers are hidden by queue-only output despite the original weak checks passing. BASE045 has an empty dedicated body, so appending model FAQ text would not fix it. Generation succeeds; the earlier human-takeover response branch discards the protected fact/FAQ rendering. This is deterministic routing after successful extraction, not a model outage. Root preserved all raw SDK tool inputs for offline replay.

## Why This Approach
Keep the existing review creation/deduplication and booking freeze. For an already-pending review with a generic question/details/acknowledge action and no pickup-review trigger, allow the existing protected fact/FAQ response branches to render despite result_action remaining human_takeover. This retains deterministic wildlife/calendar/pickup/status facts instead of rendering generated wildlife prose. Reject clearing requires_human, unconditional FAQ appending, or moving all fact routes ahead of human handling: those could weaken escalation priorities or bypass authoritative factual copy. No additional prompt or model call is required because the captured structured answers are already correct.

## Instructions
1. At `mermaid_reservation_workflow.py:682`, retain early queue-only human-takeover rendering except when review was already pending, the action is question/details/acknowledge, and pickup review did not trigger. In that narrow case continue through the existing protected calendar/wildlife/pickup/status and final dedicated-FAQ-plus-recorded-review response branches. Keep result_action=human_takeover so the handler preserves its freeze behavior. Never fall back to raw reply.
2. Preserve prior security handling and do not retain the FAQ on cancellation, summary confirmation, new-booking decisions, explicit request_human, new first-time review, or oversized pickup review. Do not change notification creation, hard-mode preservation, intake, reservation state, media jobs, checkout, global pause or operator mute controls.
3. Missing dedicated content still yields only truthful review copy; this is not claimed to answer a missing FAQ. The companion empty-critical-reply predicate remains unchanged.

## Tests
First reproduce the lost FAQ with captured structured shape across all six locales and the actual nonempty ordinary reply. Use real SQLite to verify a repeated flag deduplicates to one soft review, preserves saved details, remains unmuted and creates no reservation. Exercise generic action labels and missing dedicated content. Verify security, explicit/new review, blocked cancel/confirm/new booking and oversized pickup review cannot expose the FAQ. Add actual Marina SDK-to-buffered-worker coverage with six captured T6 tool inputs and BASE045/047 T4, requiring visible deterministic no-wildlife-guarantee answers rather than trusting the weak raw checks. Include duplicate-event and final operator/global pause guards. Replay preserved SDK inputs offline; do not call a paid model or alter raw results.

Pre-fix evidence: structured workflow regressions produced 18 failures and 61 passes; captured SDK and send-guard regressions produced 7 failures and 3 passes. The final six-suite gate passed 474 tests covering audit policy, recovery, soft review, pickup facts, confirmation/cancellation and booking UX. Logs are preserved outside this checkout in `output/remediation-342-2026-09-04/repeated-review-{faq-before,sdk-before,faq-after}.txt`. The eight fixture inputs are copied exactly from captured tool inputs; each identifies its original JSONL-line SHA-256. These offline results do not alter or replace the paid run's raw failures.

## Success Condition
An existing review plus a redundant requires_human flag cannot hide a valid dedicated general-trip answer, while all escalation, booking and send guards remain intact.

## Rollback
Revert this narrow source/test/brief commit before release. There is no configuration change, migration or live-state repair.

Independent output review passed with no actionable findings. The reviewer reran recovery plus audit-policy suites (345 passed) and verified all eight fixture inputs, guest messages and before-fields exactly against preserved SDK evidence. Parent approved the extended brief before the runtime hunk changed.
