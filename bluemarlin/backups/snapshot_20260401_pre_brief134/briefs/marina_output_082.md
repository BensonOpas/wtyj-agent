# OUTPUT 082 — Fix Semi-Escalation Relay + Revert Full Escalation Relay

**Brief:** marina_brief_082_relay_fix_and_escalation_revert.md
**Status:** Complete
**Date:** 2026-03-13

## What Was Done

1. **Fixed relay handler filter** (email_poller.py) — changed filter to only strip `relay_token` and `reply_times`. Now keeps `awaiting_relay` and `relay_question` so marina_agent enters RELAY MODE and properly reformulates operator's answer.

2. **Reverted full escalation relay** (social_agent.py) — removed relay token generation, `[RELAY-xxx]` from subject, relay instructions from body, and `relay_token` from notification creation. Full escalation is one-way again.

3. **Restored original escalation drop** (email_poller.py) — operator replies to `[ESCALATION]` emails are dropped (one-way flow).

4. **Removed `fully_escalated` clearing** from relay handler — dead code since semi-escalation doesn't set `fully_escalated`.

5. **Updated tests** — removed `test_full_escalation_creates_relay_token`, reverted `test_full_escalation_inserts_notification` to assert `relay_token is None`.

## Test Results
```
test_077 suite: 11/11 PASSED
Full social regression: 103/103 PASSED
```

## Unexpected
Nothing unexpected.
