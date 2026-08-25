# ISSUE 157 — Ali intake dispatch and catalog binding

**Status:** Executed | **Files:** `wtyj/agents/marina/marina_agent.py`, `wtyj/agents/social/social_agent.py`, `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/tests/agents/test_ali_quote_intake_dispatch.py`, `wtyj/tests/agents/test_ali_quote_workflow.py` | **Depends on:** merged Ali quote delivery contract and configured service credential | **Blocks:** guarded synthetic WhatsApp delivery canary

## Context

The first automation-only synthetic canary exposed an integration gap. Marina returned a generic contact redirect instead of building an Ali rental summary. Delivery switches were off, so no PDF, email, or operator alert was sent. The tenant was immediately disabled and the synthetic contact muted.

The quote workflow accepted pre-filled test fields, but the one Claude call had no Ali-specific intake rules or live Ali catalog context. It could not safely derive Ali's server-owned category IDs. When required fields were absent, the deterministic handler returned `None` and preserved Marina's generic reply. Existing workflow tests bypassed this seam by supplying complete fields directly.

## Why This Approach

The fix preserves one Claude call per inbound message. It reads the published catalog through the existing authenticated Ali service client, exposes only public names and fixed USD rates to Marina, and resolves customer-facing names to IDs in Python. Customer and conversation data never enter the catalog request or Ali application.

The existing `ali_quote_automation` flag is now the master intake kill switch. A configured but paused Ali tenant is kept out of the generic booking engine and receives no contact-channel redirect. No new AI call, booking engine, price calculation, or customer data path was added.

## Instructions

1. Read and validate the current authenticated Ali catalog with one retry for transient failures and a short in-process cache.
2. Inject a highest-priority Ali WhatsApp intake contract and sanitized catalog into Marina's existing system prompt.
3. Require short, one-question-at-a-time collection of name, rental period, pickup/return locations, driver age, language, and one published vehicle/category.
4. Prohibit email/telephone/form/WhatsApp redirects because the customer is already in the correct WhatsApp conversation.
5. Keep all published IDs Python-owned. Resolve exact normalized vehicle/category names against the same catalog and discard fabricated IDs.
6. Keep Ali out of the generic booking/hold engine whether automation is active or paused.
7. Leave all production feature switches off until the PR is reviewed, deployed, and a new allowlisted synthetic canary is authorized.

## Tests

Focused tests cover authenticated catalog reads, sanitized prompt context, fixed-rate visibility, name-to-ID resolution, fabricated-ID rejection, paused-state behavior, contact-redirect prohibition, and a complete natural intake producing the deterministic summary. The complete repository suite passes with 1,437 tests and six unrelated existing deprecation warnings.

## Success Condition

With automation alone enabled for an allowlisted synthetic contact, a complete rental request produces exactly one Ali confirmation summary using a current published category. It must not mention an email address, telephone number, website, `wa.me` link, or another channel. Delivery switches remain off until this intake result is observed and accepted.

## Rollback

Disable `ali_quote_automation` first. Revert this issue's commits or deploy the prior image. The paused tenant remains outside the generic booking engine. No database migration or customer-data cleanup is required by this fix.
