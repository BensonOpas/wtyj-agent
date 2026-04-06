# OUTPUT 081 — Fix Booking Decline Loop + Escalation Relay-Back

**Brief:** marina_brief_081_decline_loop_and_escalation_relay.md
**Status:** Complete
**Date:** 2026-03-13

## What Was Done

### Bug A — Booking decline loop

**Prompt fix:** Added option (d) to `_build_action_context()` in both `social_agent.py` and `email_poller.py`:
```
(d) declining or saying no — set awaiting_booking_confirmation: false,
use intent 'inquiry' (not 'booking'), acknowledge gracefully and ask
if they'd like to look at something else.
```

**Python guard:** Added field-change detection before post-validate in both files. When `_was_awaiting` was True and Claude returned NO new booking fields (decline), post-validate is skipped. When Claude returned new fields (change details, e.g., "make it 6 guests"), post-validate runs and generates a new summary.

### Bug B — Escalation relay-back

1. Full escalation in `social_agent.py` now generates a relay token and sets `awaiting_relay=True` + `relay_token` in flags alongside `fully_escalated=True`
2. Escalation email subject now includes `[RELAY-xxx]` alongside `[ESCALATION]`
3. Escalation email body now includes relay instructions for the operator
4. `email_poller.py` escalation drop narrowed: only drops `[ESCALATION]` emails WITHOUT `[RELAY-` token
5. WhatsApp relay handler now clears `fully_escalated` flag after relay fires — bot resumes normal operation

## Test Results

```
test_077 suite: 12/12 PASSED (9 existing + 3 new)
Full social regression: 104/104 PASSED (101 existing + 3 new)
```

New tests:
- `test_full_escalation_creates_relay_token` — verifies relay token in flags + notification subject
- `test_booking_decline_no_loop` — Claude returns inquiry intent for decline, no summary loop
- `test_booking_decline_with_booking_intent_no_loop` — even with booking intent + no new fields, guard prevents loop

Updated test:
- `test_full_escalation_inserts_notification` — assertion changed from `relay_token is None` to `is not None` with length check

## Unexpected

Brief reviewer caught two issues in first review:
1. Original `and not _was_awaiting` guard was too broad — would block the change-details flow. Fixed with field-change detection.
2. Existing test 6 expected `relay_token is None` for full escalation — needed updating.

Both fixed before execution. No issues during execution.
