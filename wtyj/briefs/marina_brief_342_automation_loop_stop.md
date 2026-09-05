# BRIEF 342 — Stop Mermaid Automation Loops Before Reply
**Status:** Deployed | **Files:** `Dockerfile.tracy-loop-stop`, `wtyj/agents/social/mermaid_understanding.py`, `wtyj/agents/social/mermaid_reservation_workflow.py`, `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/tests/agents/test_mermaid_audit_policy.py`, `wtyj/tests/dashboard/test_mermaid_reservations_api.py` | **Depends on:** Mermaid issue 342 one-call understanding and durable WhatsApp state | **Blocks:** none

## Context
On 2026-09-04 production received a WhatsApp message whose sender name was `Unboks` and whose prose identified another automated assistant. Mermaid then generated and delivered repeated replies at 01:14:32, 01:14:42, 01:14:58, 01:15:10, 01:16:01, 01:16:16, 01:16:25, 01:16:42 and 01:16:49 UTC. The conversation stopped only when a separate AI-mute condition appeared at 01:16:59. The current guard in `wtyj/agents/social/social_agent.py` allows up to 50 replies in one hour; it limits volume but does not recognize an agent-to-agent loop. `wtyj/agents/social/mermaid_reservation_workflow.py:507-538` sends every specialized Mermaid inbound through the normal reservation turn, so another bot's inbound prose is presently treated like guest prose.

The required behavior is terminal and non-actionable: as soon as TRACY's one model call identifies an automated conversation loop, that turn must produce no provider reply, the stop must survive later webhooks and process restarts, and no escalation or reservation mutation may be created. The operator-facing dashboard must show exactly `Loop detected and stopped` while retaining the underlying conversation history.

## Why This Approach
The existing Mermaid structured-output contract is the correct understanding boundary: Claude understands whether the latest inbound and history represent another automated agent, while Python routes only on the resulting boolean. A durable flag in the existing per-conversation `whatsapp_booking_state.flags_json` avoids a schema migration and lets every later inbound short-circuit before another model call. The conversation list and detail API can project that terminal state without inserting a fake chat message or presenting it as a customer reply.

Rejected alternatives: lowering the 50-reply hourly limit still permits a visible loop and can block legitimate fast conversations; matching words such as `bot`, `Unboks`, or `automated` in Python violates the project's language/intent boundary and is brittle across six languages; creating a soft escalation contradicts the owner's explicit instruction that no operator action is needed; storing the status as an assistant message would falsely imply that it was sent to the customer.

## Instructions
1. Extend the structured Mermaid response schema and prompt in `wtyj/agents/social/mermaid_understanding.py:10-145` with one required boolean that is true only for a confirmed automated agent-to-agent loop. Provide the untrusted inbound sender name to the existing single model call as supporting evidence, and state that a loop decision is terminal, creates no human-review request and must not generate customer-facing action.
2. Treat the structured loop route as a server-owned no-reply outcome in `wtyj/agents/social/mermaid_model_recovery.py:123-150`, so a valid empty reply is not misclassified as a provider failure.
3. In `wtyj/agents/social/mermaid_reservation_workflow.py:507-760`, persist a Mermaid-only loop-stop flag and timestamp before any field, reservation, cancellation, payment, document or escalation logic. Return an empty result for the detecting event. At the start of every later model-backed turn, check the durable flag before cached-reply lookup or model generation and return empty immediately. Preserve all prior reservation fields, completed bookings and conversation history.
4. Project the terminal state from `wtyj/shared/state_registry.py:2890-2910` and `wtyj/shared/state_registry.py:4299-4382`. For stopped conversations, keep the row active and non-escalated but replace its list preview with the exact operator status `Loop detected and stopped`; include a boolean, status text and stop time in the row.
5. Add the same explicit fields to the conversation-detail envelope in `wtyj/dashboard/api.py:3172-3238`. Do not add it to the escalation queue and do not expose a resolve/acknowledge action.

## Tests
1. A structured `automation_loop=true` result returns no customer text, preserves existing intake, creates no reservation/escalation, and saves the terminal flag with the detecting message ID.
2. A later inbound to the same conversation returns no reply and performs no second model call, including when an old cached reply exists.
3. The model receives the latest inbound sender name as untrusted evidence, and valid loop output with an empty reply passes the recovery contract.
4. The conversation list projects the exact stop text as its preview while remaining non-escalated and preserving the stored inbound history.
5. The dashboard conversation-detail endpoint exposes `loopStopped`, exact `loopStatus`, and `loopStoppedAt` without setting escalation fields.

## Success Condition
A synthetic two-bot turn is stopped before provider delivery, every later inbound is suppressed without another model call, and the dashboard exposes exactly `Loop detected and stopped` with no operator task.

## Rollback
Revert the source commit and redeploy the prior pinned Mermaid image. Existing `mermaid_loop_stopped` flags are additive JSON keys ignored by the old code, so no data rewrite is required; retain them as audit evidence or remove only the exact keys in a separately reviewed maintenance operation.
