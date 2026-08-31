# BRIEF 325 — Keep Ali rental intake out of generic scheduling escalations
**Status:** Approved by owner | **Files:** `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/agents/social/webhook_server.py`, `wtyj/agents/social/zernio_dm_client.py`, `wtyj/shared/state_registry.py`, `wtyj/shared/escalation_dispatcher.py`, `wtyj/dashboard/escalation_summary.py`, focused tests | **Depends on:** Brief 285, Brief 318, Brief 322 | **Blocks:** none

## Context

Ferla Silvina asked to rent a car from 24 December through 29 December. Nick
correctly collected the rental dates, vehicle, driver and airport details and
was preparing the official quote. A malformed multilingual quote-confirmation
control failed local delivery validation. That technical failure was then
stored as a generic hard escalation. The generic appointment summarizer read
the rental dates as proposed meeting times, created an appointment row and
presented `Agent needs help`, `Human takeover` and `Decision needed` in Ali's
dashboard even though no human rental decision was required.

## Five-Step Simplification

1. **Question the requirement:** rental pickup and return dates are rental-file
   data, never meeting availability and never a reason for human takeover.
2. **Delete:** remove the duplicate fallback rewrite that converts a localized
   message into a stringified dictionary, and prevent Ali rental workflows from
   writing appointment rows.
3. **Simplify:** keep genuine customer escalations separate from technical
   delivery attention. Normal complete pre-quote files remain owned by Nick.
4. **Accelerate:** accept every supported localized confirmation control at the
   provider boundary so Nick can immediately continue the rental flow.
5. **Automate:** add executable multilingual, tenant-boundary and dashboard
   projection tests so cross-vertical scheduling logic cannot return.

## Instructions

1. Preserve the locale-specific quote confirmation built by
   `build_quote_confirmation_control()`; do not reconstruct it in the webhook.
2. Validate all supported localized button pairs and fallback instructions in
   the Zernio adapter from the workflow's canonical constants.
3. On a terminal provider-delivery failure, create technical attention rather
   than a customer escalation or human takeover.
4. Technical notifications must not open/escalate the conversation and must not
   appear through the generic escalation API.
5. Pass the active workflow type into escalation summarization and hard-block
   appointment creation for `ali_quote`. The Ali prompt must explicitly state
   that rental dates are not scheduling slots.
6. Project genuine customer escalations as operator work, genuine technical
   failures as technical work, and ordinary `ready_to_quote` files as Nick's
   work with no staff action.
7. Repair only Ferla's invalid derived escalation and appointment records after
   deployment. Preserve her conversation, rental state and customer data.

## Tests

1. English, Dutch, Papiamentu, German and Spanish confirmation controls pass
   provider validation without losing their localized fallback text.
2. The webhook preserves the builder's fallback and labels terminal delivery
   failures as technical attention.
3. Technical notifications do not set conversation status to open and are not
   returned by the generic escalation list.
4. An Ali summary containing a rental date range cannot create an appointment.
5. The Ali escalation prompt identifies rental dates as rental data, not
   proposed meeting times.
6. A normal complete pre-quote rental file remains agent-owned; a true customer
   escalation and a true delivery failure project to their distinct queues.
7. Run the focused tests and the full backend suite.

## Success Condition

Ali's dashboard treats a normal rental inquiry as Nick-owned rental work. It
shows no generic scheduling decision, no human takeover and no appointment for
rental dates. Real customer questions and real technical failures still reach
the correct operator queue with car-rental-specific context.

## Rollback

Revert Brief 325 and redeploy. Restore no deleted customer data: the production
repair removes only the invalid derived escalation and appointment rows.
