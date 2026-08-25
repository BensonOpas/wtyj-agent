# Issue 168 — Prevent Ali quote mailbox self-reply loops

**Status:** Executed
**Files:** `wtyj/agents/marina/email_poller.py`, `wtyj/tests/marina/test_164_support_email_filter.py`
**Depends on:** Ali staff PDF delivery from PR #158 and the issue #165 independent-delivery workflow
**Blocks:** Second guarded Ali production canary

## Context

The first successful production quote sent the required PDF from the authenticated Gmail mailbox back to that same staff mailbox. Because Ali's public business config intentionally does not advertise email, the authenticated sender address was absent from the existing business-owned sender guard. The inbox poller therefore treated its own quote as customer mail and generated seven replies to itself.

## Approach

Extend the existing business-owned sender helper with `EMAIL_ADDR`, the authenticated mailbox already used by the adapter. This is the narrowest durable guard: self-sent staff mail is marked seen before rate limits, state mutation, model calls, or replies, while legitimate customer email behavior and the outbound PDF attachment path remain unchanged.

The owner-approved tenant ignore-list entry remains as defense in depth. Generic Ali escalation and appointment alerts remain disabled; the direct staff PDF email remains enabled.

## Tests

- The authenticated mailbox is guarded even when business config contains no email fields.
- The authenticated mailbox is lowercased.
- An authenticated mailbox already present in business config is deduplicated.
- Existing business-owned email behavior and relay/escalation exceptions remain covered.

## Success Condition

Each completed Ali quote produces one customer WhatsApp PDF and one staff PDF email. The staff email cannot re-enter customer intake or produce any automatic reply.

## Rollback

Revert the issue #168 merge commit and redeploy the previous image. Keep the Ali mailbox on the tenant ignore list until a replacement guard is live.
