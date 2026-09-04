# BRIEF — Consulta September AI cost and completed-form monitoring
**Status:** In progress | **Files:** shared/ai_monitoring.py; existing Anthropic call sites; shared/state_registry.py; dashboard/api.py; scripts/ai_monitor_report.py; tests/test_ai_monitoring.py | **Depends on:** current deployed source c42adcb | **Blocks:** September financial baseline

## Context
Only Consulta Despertares has real customers; other tenants are demos. Existing JSON usage logs omit five response paths and customer display-name changes fragment attribution. The user defines a converted lead as a fully completed prospect form, not a reply, inactivity, copied status, or callback closure. First-name, surnames, valid phone, appointment preference, session type, preferred clinic and callback preference are required. Visit reason is explicitly optional on the provided form.

## Why This Approach
Add a tenant-enabled, local usage ledger and form-completion observer without changing prompts, models, retries, cache configuration, customer delivery or existing workflow statuses. Reject inferring completion from a thank-you or ready_to_call because neither establishes all fields. Reject changing the API key now: user will consider that separately. Response metadata is recorded before downstream parsing. Provider-side billing remains unavailable with the shared key.

## User clarification
The primary metric is FULL cumulative customer cost, before and after form completion. Completion is a milestone only, never a stop condition. Report customer totals and monthly cost per AI-served customer, with overhead separately visible.

## Instructions
Use shared/ai_monitoring.py for all twelve production Anthropic calls. Preserve exact message-create arguments and return/exception behavior. Record HTTP attempt counts with metadata-only hooks when supported; otherwise label attempt visibility unknown. Persist no prompts, response text, names, phone numbers or consultation reason. Hash normalized tenant/channel/conversation identities. Calls without an explicit conversation are overhead, not allocated arbitrarily to a lead. Observe committed follow-up/state writes; never mutate workflow status. Seed existing forms with unknown historical completion time, import September legacy usage separately, and exclude earlier already-complete forms from newly measured conversions. Store in persistent tenant data. Add an authenticated read-only summary route and CLI snapshots, both independent of additional AI calls.

## Tests
Verify unchanged request arguments/results/errors; successful and retry metadata capture with an HTTP mock transport; complete/incomplete/optional form fields; first completion counted only once; baseline completion exclusion; cost before/after conversion; UTC month boundaries; legacy import idempotence; concurrent request attribution; persistence-failure isolation; tenant disablement and prompt/content exclusion.

## Success Condition
Consulta-only deployment records real request metadata and completed-form transitions, exports September totals and coverage gaps, and existing service health/customer handling remains unchanged.

## Rollback
Restore the previous Consulta image using its compose override and recreate only that service. Monitoring data is additive in a separate database and can remain for audit. No customer database schema, credentials, or prompts are changed.
