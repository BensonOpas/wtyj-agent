# BRIEF 285 — Ali watertight “Send my quote” confirmation
**Status:** Approved by owner | **Files:** `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/agents/social/social_agent.py`, `wtyj/agents/social/webhook_server.py`, `wtyj/agents/social/zernio_dm_client.py`, `wtyj/tests/agents/test_ali_quote_workflow.py`, `wtyj/tests/agents/test_ali_quote_intake_dispatch.py`, `wtyj/tests/agents/test_ali_latest_change_orchestration.py`, `wtyj/tests/social/test_message_reliability_p0.py` | **Depends on:** Briefs 280–284; GitHub issue #220 | **Blocks:** none

## Context

Ali’s provider-confirmed summary is still confirmed primarily by interpreting customer text. A production customer replied to the current complete summary with a debounced `Yes\nHow much`; the deterministic allowlist rejected the combined message, no `ali_quotes` row was created, and model wording nevertheless promised that a quote was coming. Complete/no-quote leads also project as generic `active`, so this silent failure is not visible as recovery work.

The owner approved a primary structured WhatsApp action labeled exactly **Send my quote**. The customer’s tap must prove confirmation of the exact provider-delivered summary, create or resume one durable quote job, and preserve text confirmation only as a safety net.

## Why This Approach

Reuse Zernio’s existing native postback transport, but give quote confirmation its own signed, versioned namespace. The payload contains no rental data; Python reloads the current tenant-owned fields and validates the signed current summary anchor before creating a quote. Provider-confirmed delivery commits the anchor and provider IDs atomically with the assistant timeline. This keeps Brief 280’s plan-send-commit boundary, current unique `(conversation_id, summary_hash)` idempotency, restart resumption, three-minute customer-only delay, and supersession guard.

Renaming a URL was rejected because it produces no structured selection event. Trusting button text or customer-provided rental data was rejected because it cannot prove which summary was confirmed. Removing text confirmations was rejected because provider controls can fail. Adding another Claude call was rejected because structured taps are protocol events, not language-understanding work. The approved exact button/fallback/status copy is a narrow deterministic workflow protocol exception consistent with Ali’s existing summary and quote-delivery copy.

## Instructions

1. In `ali_quote_workflow.py`, add a bounded signed payload contract `ali_quote_confirm:v1:<opaque signature>`. Derive it from the conversation ID, summary hash, and summary version using an Ali/Zernio server secret. Parse only WhatsApp `button_reply`/`list_reply` interaction types, compare signatures in constant time, and never accept rental fields from the payload.
2. Build a summary confirmation control only for an `AliTurnPlan(outbound_kind="summary")`. Its button title is exactly `Send my quote`; its fallback appends exactly `Reply SEND QUOTE to continue.`. Extend the deterministic summary closing so the customer is told to tap the control to prepare the official quote.
3. Extend `commit_ali_turn_delivery()` so a provider-confirmed summary atomically persists an auditable anchor: hashed conversation identity, current draft/summary hash, summary version, delivered timestamp, required-field names, signed interaction token, provider message IDs, and delivery mode. Clear the current anchor on a quote-affecting invalidation, but retain the last confirmed token plus quote ID so repeated taps return truthful persisted status without creating another job.
4. In `zernio_dm_client.py`, add one replay-safe Ali confirmation sender using the same service-window, provider-status confirmation, reconciliation, and `Idempotency-Key` primitives as the vehicle picker. On an immediate interactive rejection or ambiguous failure, send the same summary as plain text with the exact fallback instruction. Return provider IDs and the actual delivery mode.
5. In `webhook_server.py`, send summary plans through the confirmation sender, then commit the anchor only after the interactive or fallback summary is provider-confirmed. For a later `message.failed` on a recorded confirmation provider ID, mark the failure, resend the same summary plus exact fallback idempotently, and create a visible hard notification only if recovery fails. Never route the provider failure to Nick.
6. In `social_agent.py`, resolve the signed quote-control tap before Claude. A current valid tap becomes the deterministic `SEND QUOTE` confirmation signal and creates/resumes one quote. A stale tap creates no quote and returns the current deterministic summary with a fresh control. A repeated tap for an already-created quote returns status from the persisted quote row. Do not call Claude for these structured protocol events.
7. Keep natural confirmation as a contextual fallback only while a current provider-delivered summary anchor exists. The existing deterministic confirmation helper must accept `Yes`, `Yes, how much?`, batched `Yes\nHow much`, `OK`, `OK thanks`, `send it`, `go ahead`, and `I agree`; it must reject corrections, uncertainty, and question-only messages. `SEND QUOTE` and `Send my quote` are exact fallback commands. An ineligible `confirm_summary` turn must re-present deterministic current details and can never reuse model quote-promise wording.
8. After the quote row is durably committed, retain the current first-person quote-preparing response and start immediate pricing/PDF/staff email/internal work. Only customer WhatsApp delivery waits 180 seconds from persisted confirmation. Preserve restart resumption, duplicate-click/webhook idempotency, and suppression of customer delivery after a quote-affecting change.
9. Make terminal status truthful. During processing, a repeated confirmation says the quote is already being prepared. After provider delivery, `I accept` acknowledges acceptance and creates/deduplicates a staff/internal notification. Never claim a delivered quote has not been sent. Unexpected processor exceptions must mark the quote `attention_required` and create the existing visible escalation instead of dying silently.
10. Change quote-lead projection so complete required details with no quote are `ready_to_quote` (or `needs_an_answer` when an escalation exists), never generic `active`. Keep every change behind `tenant_configured()/tenant_enabled()` and preserve all other tenants.
11. Keep price authority unchanged: fixed catalog daily rates may be stated, but no Python or model path introduced by this brief may calculate or promise a rental total. The official deterministic quote engine remains the only total source.

## Tests

1. Build a complete EN/NL/PAP/DE summary and assert the exact structured `Send my quote` control, signed opaque payload, no customer/rental data in the payload, and exact fallback instruction.
2. Prove a provider-confirmed current tap creates one quote and one processing response; duplicate webhook, repeated tap, and restart/replay create one row and one customer delivery.
3. Prove a stale tap after vehicle/date/location/driver/supplement change creates no obsolete quote and returns a fresh summary/control. Prove a change during the 180-second delay preserves pricing/PDF/staff work and suppresses obsolete customer assets.
4. Table-drive contextual text confirmation: accept every owner-approved phrase only with a current anchor; reject question-only, `yes but change the dates`, `add a child seat`, and `maybe`; assert no ineligible model promise is returned.
5. Simulate immediate interactive rejection and late `message.failed`: the exact fallback is sent once, failure is recorded, and unrecoverable fallback creates one visible hard notification.
6. Prove quote work starts before the customer delay, +60-second restart waits only 120 seconds, +180 seconds sends immediately, and unexpected processor failure becomes `attention_required` plus escalation.
7. Prove post-delivery `I accept` reads the real quote, acknowledges it, and deduplicates the staff notification. Prove complete/no-quote dashboard rows project as `ready_to_quote`.
8. Run focused Ali workflow/intake/orchestration/reliability tests, then `python3 -m pytest wtyj/tests/ -q` with zero failures.

## Success Condition

A synthetic Ali customer receives one provider-confirmed summary with **Send my quote**, one valid tap durably creates exactly one quote, immediate internal work completes, the customer receives exactly one official quote after the existing three-minute boundary, and every failure path either recovers with `Reply SEND QUOTE to continue.` or creates a visible operator failure.

## Rollback

Revert the Brief 285 merge commit and deploy the previous image through the normal CI rollback path. No destructive migration is added; new JSON flags are ignored by older code and existing `ali_quotes` rows remain valid. If the interactive path misbehaves, restore the prior image so natural text confirmation remains available while preserving all quote rows and customer history.
