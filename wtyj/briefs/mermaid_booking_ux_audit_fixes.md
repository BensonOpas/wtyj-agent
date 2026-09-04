# Mermaid booking UX audit fixes
**Status:** In progress | **Files:** Mermaid understanding, workflow, guest presentation, documents, payment, delivery reconciliation, webhook recovery loop, tenant catalog, focused tests | **Depends on:** deployed 70deced reservation demo | **Blocks:** premium demo acceptance

## Context
The audited Calvin conversation ending 003 skipped a pickup-price question, promised a pickup price in a quote that excluded it, repeated summaries, and gave pier-arrival instructions after a hotel-pickup request. Zernio delivered the receipt after the synchronous check timed out; local delivery remained failed and repeated checkout callbacks retried with changing signed URLs.

## Why This Approach
Keep one model call for understanding and natural language. Python owns the summary, amounts and transport state. Preserve answers to mixed question/detail turns and suppress confirmation until an unanswered question is handled. Keep pickup explicitly pending and excluded throughout chat, checkout, quote and receipt. Use account-scoped read-only provider evidence to reconcile delayed receipts. Reject a prompt-only fix: server overrides and generic document instructions caused defects even with a correct model answer. Reject increasing synchronous wait time: it would make checkout slower and still lose late delivery.

## Instructions
- Update mermaid_understanding.system_prompt and tool contract to use concise, calm hospitality language, answer questions first, avoid stock praise and technical wording, and report open questions independently of field extraction.
- Update mermaid_reservation_workflow.process_model_turn to preserve mixed-turn answers, show one priced summary at a meaningful transition, and expose persisted pricing/transport facts to the model.
- Share catalog-backed transport and pricing presentation across _summary, quote/receipt rendering, checkout and success_message. Include supplied hotel; never turn a pending pickup into pier instructions or a confirmed transfer.
- Reconcile document jobs using account-guarded GET history and exact document URL identity, ignoring only signed query parameters. Require delivered/read evidence; record the actual provider message in local history. Unknown delivery stays pending, and repeated payment callbacks must not blindly resend. Run bounded reconciliation from the existing recovery loop.
- Preserve existing reservation and payment records and previously delivered PDFs. Deploy a dedicated Mermaid image with a rollback image retained; do not restart other tenants or send unsolicited test messages.

## Tests
Mixed question/details, correction versus approval, one-summary behavior, all six transport locales, priced summary, pending pickup on checkout/quote/receipt, delayed delivery, changed URL signatures, foreign account/history, duplicate callbacks, and an isolated real-model replay of Calvin's journey with provider sends disabled.

## Success Condition
Calvin's replay answers the pickup question immediately, never invents its price, shows one clear priced summary, and completes with matching transport instructions; late delivery reconciles without another send.

## Rollback
Restore Mermaid's prior image reference and recreate only its agent service, retaining the database and current credentials. Restore only the catalog's presentation additions if necessary. No peer tenant changes.
