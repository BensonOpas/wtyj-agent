# Issue 163 — Ali Zernio WhatsApp routing and outbound safety

Status: implementation
Owner: Unboks
Issue: https://github.com/BensonOpas/wtyj-agent/issues/163

## Problem

Ali Car Rental uses `workflow.type=ali_quote` with `features.booking_flow=false`.
The Zernio webhook selector only recognized `callback_follow_up` as a structured
WhatsApp workflow when booking flow was disabled. Ali traffic therefore entered
the generic DM agent. Its fallback prompt contained a booking redirect to
WhatsApp/email, so the model sent customers away from the same WhatsApp chat and
bypassed the Ali intake sanitizer.

## Required behavior

- Zernio WhatsApp for `ali_quote` always uses the structured WhatsApp agent.
- Generic DM fallback prompts never contain booking redirects when
  `booking_flow=false`.
- Every Ali AI-generated WhatsApp reply is sanitized at the last outbound
  boundary, independent of automation switches and upstream routing.
- Zernio platform names are normalized before channel routing.
- A deployment must fail if an Ali runtime is pinned to an unverifiable raw
  image digest, and Ali must be included in automatic rollback/health checks.

Human dashboard replies are not altered. Non-Ali Q&A-only tenants retain their
existing generic DM route.

## Files

- `wtyj/agents/social/webhook_server.py`
- `wtyj/agents/social/dm_agent.py`
- `wtyj/agents/social/zernio_dm_client.py`
- existing webhook, DM, and Ali intake test modules
- `wtyj/scripts/process_deploy_queue.sh`
- `wtyj/scripts/rollback.sh`

## Verification

- Unit: selector matrix, mixed-case provider channel normalization, fallback
  prompt gating, exact leaked-reply sanitization.
- Integration: Zernio buffer flush calls the Ali orchestrator and never the DM
  agent for the production-shaped configuration.
- Delivery: final Zernio and legacy Meta send boundaries cannot emit contact
  redirects for Ali.
- Deployment: configured/running image identity and port 8101 health are
  asserted.
- Guarded canary: features stay off and the synthetic conversation stays muted
  until the patched image, route, and sanitizer are verified. Enable intake
  first, then delivery only after a safe intake result.

## Rollback

Disable all four Ali quote feature switches, mute the synthetic conversation,
and run the standard rollback for `ali-car-rental`. The rollback recreates the
tenant from `wtyj-agent:previous` and verifies port 8101.
