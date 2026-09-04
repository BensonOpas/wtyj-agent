# BRIEF 342 A1 — Isolate malformed responses from provider outages
**Status:** Deployed and verified at f220c3e; A4/A8 acceptance holds remain | **Files:** `wtyj/agents/marina/marina_agent.py`, `wtyj/agents/social/mermaid_model_recovery.py`, `wtyj/tests/social/test_mermaid_model_recovery.py` | **Depends on:** 2286d9f | **Blocks:** candidate follow-up audit/deployment

## Context
The preserved first real-model audit returned `fields: ""` with otherwise valid FAQ output in PARA006 turn 3. Schema recovery rejected it, then its global five-second provider circuit prevented model calls for another synthetic conversation (PARA005) and later fresh messages. No provider error occurred. The generic adapter currently defaults missing fields, but does not normalize this empty representation (`marina_agent.py:2199`). Recovery currently opens the provider circuit for every failure (`mermaid_model_recovery.py:241`).

## Why This Approach
An exactly empty string contains no extracted fields and can safely mean an empty object for this Mermaid contract. Nonempty strings and other malformed values remain rejected, preserving data validation. Reject broad coercion, which could hide lost passenger or payment data. A malformed response remains a bounded event failure; it does not prove a provider outage and must not block other conversations. Keep the existing shared breaker for actual transient/provider/credential/billing errors rather than removing outage protection.

## Instructions
1. In the Mermaid-only adapter at `marina_agent.py:2199`, normalize exactly empty `fields` to an empty object before existing defaults; preserve other contracts and malformed nonempty values.
2. At `mermaid_model_recovery.py:241`, preserve event attempts, retry delay, notice idempotency and failed response caching rules. For `invalid_response`, do not create/update the provider circuit or provider technical alert. If this invocation owned an expired circuit's probe, delete only that same probe with no later failure timestamp, resolving its alert only if no circuit remains. Never clear a concurrent later provider failure.
3. Preserve actual provider outage backoff, bounded probes, operator notifications and explicit human bypass. Add no model call or live/customer send.

## Tests
- Real SQLite plus mocked actual Anthropic SDK → Marina → buffered workflow: empty-string fields deliver the valid FAQ once, preserve saved intake, and cache a successful empty object with one call.
- Invalid structured output keeps its own five-second retry and one notice, but does not prevent a different conversation or fresh same-conversation event from generating.
- The failed event can recover after its delay; newer successful same-conversation events still supersede obsolete failures.
- A malformed circuit probe clears only its own old circuit; a concurrent later real provider failure and alert survive. Existing transient/billing/credential/concurrency tests remain green.
- Nonempty strings, lists, null and other malformed fields are still rejected by the actual adapter/recovery path.

## Success Condition
A malformed model response cannot suppress independent healthy messages, and real provider failures retain the existing outage protections.

## Rollback
Revert this focused source commit and rebuild the candidate; no live changes or data migrations are part of this brief. Any eventual deployment uses the existing Mermaid-only guarded deployment and saved baseline image/config rollback.
