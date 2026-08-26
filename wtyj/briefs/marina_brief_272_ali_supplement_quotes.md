# BRIEF 272 — Ali supplement questions and quote itemization
**Status:** Executed | **Files:** `wtyj/agents/marina/marina_agent.py`, `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/agents/social/ali_quote_pdf.py`, `wtyj/agents/social/ali_quote_delivery.py`, focused tests | **Depends on:** Ali catalog version 13 supplement contract | **Blocks:** issue 180 production completion

## Context

Ali's published catalog now contains tenant-managed supplements with localized names, fixed integer-cent pricing, a per-day or per-rental billing basis, and stable opaque IDs. Unboks previously discarded the catalog `extras` collection, told Carlos never to add extras, sent only legacy unquantified IDs, omitted supplements from the confirmation summary, and showed no calculation detail in the WhatsApp quote or PDF. That could silently omit a requested child seat.

## Why This Approach

Ali remains the only pricing source. Carlos receives public supplement names and current prices for conversation, while Python resolves the selected name to the current server-owned ID and sends Ali only `{id, quantity}`. The alternative of copying supplement configuration into tenant JSON or an Unboks dashboard was rejected because it creates a second pricing truth. Keyword-based child-seat parsing was also rejected because it violates the one-Claude-call architecture and would be brittle across four languages.

## Instructions

1. Extend the existing structured response at `wtyj/agents/marina/marina_agent.py:141` with supplement name and bounded quantity, never ID or price.
2. Refresh and inject the current public supplement catalog in `wtyj/agents/marina/marina_agent.py:827`, instructing Carlos to answer price questions first, expose singular quantity one, and ask one quantity question only when ambiguous.
3. Resolve names/translations to current IDs and prices in `wtyj/agents/social/ali_quote_workflow.py:616`; validate state at `:152` and build the strict no-PII Ali request at `:245`.
4. Include current supplement state in the deterministic confirmation and hash at `wtyj/agents/social/ali_quote_workflow.py:782` and `:837`, including quantity, basis, unit price, rental days, and integer-cent line total.
5. Localize and itemize the immutable Ali pricing line in `wtyj/agents/social/ali_quote_pdf.py:159` and the customer caption in `wtyj/agents/social/ali_quote_delivery.py:46`.
6. Preserve existing quote replacement, replay protection, three-minute customer-only delivery timing, and immediate staff/internal delivery.

## Tests

- Resolve EN/NL/PAP/DE supplement names to one current ID; reject quantity outside 1-20 and duplicate selections.
- Confirm two child seats for seven days show `2 × USD 5.00 × 7 = USD 70.00` and send only ID plus quantity to Ali.
- Change the catalog price and prove the next summary/hash uses it while the earlier immutable quote request remains unchanged.
- Render one-page EN/NL/PAP/DE PDFs and verify localized headers/name, unit price, basis, rental days, line total, rental total, and separate refundable deposit.
- Verify WhatsApp itemization, no-PII request boundaries, replay idempotency, and the existing customer-only delay.
- Run the full repository suite.

## Success Condition

A synthetic customer can request child seats naturally in any supported language and receive one immutable quote whose summary, WhatsApp caption, and PDF all show the authoritative itemized supplement while Ali remains the sole pricing source.

## Rollback

Revert the issue 180 Unboks merge commit and redeploy the previous main image; leave the additive Ali supplement/catalog data in place because older Unboks builds safely ignore it and historical quote snapshots remain immutable.
