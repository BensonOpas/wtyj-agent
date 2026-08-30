# BRIEF 317 — Meta-Safe Ali Pre-Reservation Follow-Ups
**Status:** Executed | **Files:** `agents/social/ali_lead_follow_up.py`, `agents/social/zernio_dm_client.py`, `agents/social/webhook_server.py`, `agents/social/social_agent.py`, `agents/marina/marina_agent.py`, `tests/agents/test_317_ali_pre_reservation_followups.py`, Ali `client.json` | **Depends on:** Brief 316 | **Blocks:** None

## Context
Ali's existing automated reminders begin only after a reservation exists. A customer such as Gina Purunchi who starts a WhatsApp car search but never reserves has no reservation row and therefore receives no reminder. Ali needs a polite way to ask whether that customer wants to continue or stop without surprising them, repeating an intake question, or breaching Meta's customer-service-window rules.

Meta permits free-form WhatsApp replies only during the customer-service window that ends 24 hours after the customer's latest message. Outside that window, a business-initiated message requires an approved template. A generic car-search reminder outside the window would be promotional follow-up rather than a transaction update, so this implementation does not attempt to reclassify or send it as a utility template. Opt-out requests must be honored.

## Why This Approach
An isolated lead-follow-up state machine owns the 3-hour, 8-hour, and 22-hour milestones. Every new customer message creates a new anchor and resets the schedule. The local planner stops ten minutes before the 24-hour limit, while the delivery worker independently checks Zernio's current WhatsApp history immediately before sending and fails closed if the provider cannot prove the window is open. Activation time is persisted so rollout never sends reminders for historical leads.

Reusing reservation reminders was rejected because those records do not exist before reservation and their next-action copy describes a different workflow. Sending an approved template after 24 hours was rejected because the requested generic car-search nudge is not a utility update. A single fixed delay was rejected because it would not provide the requested graduated check-ins or a final in-window opportunity.

## Instructions
1. Add a tenant- and feature-gated pre-reservation follow-up module with durable activation policy, delivery claims, idempotency keys, retry limits, opt-out preferences, and structured customer reply actions.
2. Calculate milestones from the latest signed customer inbound timestamp. Require the latest local conversation message to be from Ali, require no reservation, no active inbound processing, no human takeover, and no do-not-contact preference.
3. Send at 3, 8, and 22 elapsed hours. Respect configured quiet hours; coalesce missed milestones after quiet hours; skip rather than send if deferral reaches the 23-hour-50-minute safety boundary.
4. Store all localized customer copy and timing settings in Ali's `client.json`; keep business copy out of Python.
5. Immediately before each send, query the provider's current WhatsApp message history. Send only when the latest inbound proves the customer-service window is open. Treat provider errors, missing inbound history, and closed windows as no-send outcomes.
6. Persist the outbound reminder in conversation history only after provider-confirmed delivery.
7. Extend Marina's one existing model response with `ali_lead_follow_up_action`: `continue`, `stop`, or `none`. Let Nick answer the customer's newest message naturally; an explicit stop records do-not-contact and asks no new sales question.
8. Do not create staff notifications for these lead reminders and do not change the separate post-reservation reminder workflow.

## Tests
1. Verify the 3-hour, 8-hour, and 22-hour milestones are claimed once from the latest customer inbound and carry the 23-hour-50-minute local safety deadline.
2. Verify a new customer reply resets all reminder timing to that new inbound.
3. Verify quiet hours defer and coalesce milestones, while an expired window becomes terminal and is never claimed.
4. Verify activation is non-retroactive and that either a reservation or an explicit stop makes the lead ineligible.
5. Verify the scheduler never sends when provider-side window verification fails and persists a message only after an open-window, confirmed send.
6. Verify the provider check uses the latest inbound and fails closed on a provider error.
7. Verify Marina's response contract exposes the structured continue/stop/none decision.

## Success Condition
An eligible Ali customer who has not reserved receives at most three polite, localized follow-ups inside the customer-initiated 24-hour WhatsApp window, while replies reset the clock and reservation, opt-out, human takeover, quiet-hour expiry, or provider uncertainty prevents further sends.

## Rollback
Disable `features.ali_pre_reservation_reminders_enabled` for Ali immediately, then revert the Brief 317 commit. The additive audit tables may remain safely; no destructive data rollback is required.
