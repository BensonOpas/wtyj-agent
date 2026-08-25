# Issue 165 — Humanize Carlos and isolate Ali quote deliveries

**Status:** Executed
**Files:** `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/tests/agents/test_ali_quote_workflow.py`
**Depends on:** Ali quote workflow from PR #158; guarded Ali WhatsApp routing from PR #164
**Blocks:** Guarded two-number production canary

## Context

The live Ali intake summary used form-like instructions such as “Reply yes if everything is correct.” The first production quote also proved that staff-email failure stopped the workflow before the already-generated PDF could be attempted on WhatsApp. Issue #165 requires customer-facing language that sounds like Carlos and channel delivery that does not let one failed destination block the other.

## Why This Approach

Keep the existing deterministic Ali confirmation state machine and change only its four-locale wording plus delivery sequencing. The customer WhatsApp PDF is attempted first, staff email is attempted independently, and any channel failure is recorded after both eligible channels have had their chance. A second Claude call was rejected because it would violate the one-call inbound-message contract and make a state-changing confirmation prompt nondeterministic.

## Instructions

1. Update the existing summary and progress labels in `wtyj/agents/social/ali_quote_workflow.py` with concise natural EN, NL, PAP, and DE copy. Preserve the same fields, confirmation hash, and state transition.
2. In `process_quote`, attempt customer WhatsApp delivery before staff email. Collect delivery errors and raise only after both enabled, unfinished delivery channels have been attempted.
3. Preserve retry limits, idempotent sent-status guards, PDF integrity checks, operator-alert behavior, and escalation behavior.
4. Add behavior tests in `wtyj/tests/agents/test_ali_quote_workflow.py` for all four locales and for each delivery channel failing without blocking the other.

## Tests

- All four localized summaries start and end with the approved natural language and omit the rejected form instructions.
- All four progress messages retain WhatsApp and the 30-minute promise.
- Staff-email failure still allows one successful WhatsApp PDF delivery.
- WhatsApp failure still allows one successful staff-email delivery.
- Existing replay test continues to prove one delivery per channel.

## Success Condition

A fresh Ali WhatsApp confirmation uses the approved Carlos wording and independently delivers the identical quote PDF to customer WhatsApp and staff email without either channel blocking the other.

## Rollback

Revert the issue #165 merge commit and redeploy the previous `wtyj-agent` image. Leave all four Ali quote feature flags off until the prior image is healthy.
