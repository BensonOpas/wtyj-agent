# BRIEF342 — Accept validated server-rendered replies
**Status:** Deployed and verified at f220c3e; A4/A8 acceptance holds remain | **Files:** Mermaid understanding, Marina adapter, model recovery, reservation workflow and existing recovery tests | **Depends on:** 178ba56 | **Blocks:** final candidate verification

## Context
The preserved final synthetic run has valid structured wildlife/status and confirmation tool results with `reply: ""`. Marina rejects these as `claude_empty_reply` before Python can render the authoritative response. This produces outage fallback copy even though the model selected a route that already has server-owned output. Repeated confirmation of an existing reservation also needs a recorded status response rather than relying on optional model prose.

## Why This Approach
Use one shared structured-route predicate for the adapter and recovery validator. Permit an empty string only when the route guarantees server output: security, human review, cancellation, payment status, supported calendar/status selectors, or confirmation without proven guest uncertainty. Keep all supplied schema fields strictly validated before caching a generated result. Blank ordinary FAQ/intake replies remain retryable. Reuse existing critical copy authorized by issue342; add no language classifier, business fact or new guest-facing template.

## Instructions
1. Share the existing exact latest-guest question-excerpt proof and a narrow server-output predicate in Mermaid understanding. The predicate must reject a blank confirmation with a real guest question unless a separate protected selector guarantees output.
2. Permit this exception only in the Mermaid adapter and recovery path. `reply` must remain a string; malformed structured output must remain retryable. Preserve one model call, event leases/cache and provider failure behavior.
3. For repeat confirmation of an existing reservation without guest uncertainty, render its recorded payment state without creating another reservation, quote or media job. Preserve review/security/cancel priorities and final operator/global-pause send guards.
4. Sanitize a string `other_question_reply` through the same internal-token/em-dash cleanup as `reply`, without converting malformed values to strings.

## Tests
Use the actual Marina SDK adapter with a mocked Anthropic client and the buffered webhook/real temporary SQLite workflow. Verify empty wildlife/status and canonical confirmation across six languages; existing reservation repeats; a separate FAQ body alongside recorded status; sanitizer parity; malformed critical fields and empty ordinary FAQ remain retryable and the same event can recover. Preserve actual guest-question, review, operator and tenant pause tests. No paid calls or provider sends.

The initial SDK regressions reproduced 19 failures with 12 passing cases before the source change. The final focused gate passed 344 tests across model recovery, soft review, confirmation/cancellation, audit policy, pickup pricing, Marina tool-use and internal-token sanitization. It includes six-language canonical summary → one confirmation → one quote → repeat unpaid-status flows, plus unchanged paid/cancelled reservations. All SDK and customer-provider calls were stubbed; SQLite and generated documents used temporary paths.

Independent output review approved the adapter/recovery/schema boundary and workflow changes, and independently reran all 129 model-recovery tests successfully.

## Success Condition
Valid critical routes always produce their authoritative response. Missing ordinary answers and malformed tool output never become successfully cached generated replies. Confirmation remains single-step after a canonical summary and duplicate-safe.

## Rollback
Revert the focused source/test commit before release; no data migration or live-state repair is introduced. Parent owns candidate integration and deployment.
