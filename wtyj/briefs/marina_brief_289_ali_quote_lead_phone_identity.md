# BRIEF 289 — Ali Quote Leads provider-confirmed phone identity
**Status:** Approved by owner | **Files:** `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/dashboard/api.py`, `wtyj/tests/agents/test_ali_quote_leads.py` | **Depends on:** Brief 270; GitHub issue #230 | **Blocks:** none

## Context

The live Ali Quote Leads card displayed `WhatsApp ••••8172` for a customer whose
provider-confirmed WhatsApp number ends in `8003`. Production tracing proved
that `8172` came from the internal 24-character Zernio conversation id. The id
happened to contain twelve digits, so `_masked_whatsapp_identifier()` accepted
it as if it were a phone number. No runtime error was emitted because the
mapping was deterministic but semantically wrong.

## Why This Approach

Keep the quote read model fail-closed, then hydrate its display identity at the
authenticated API boundary through the existing tenant-guarded Zernio contact
resolver. This resolver already uses the tenant account allowlist and caches
provider results. Returning the full phone to the browser was rejected because
the current Quote Leads UI needs only a masked contact hint. Persisting another
phone copy was rejected because the provider remains the canonical source and
the read model requires no new table or migration.

## Instructions

1. In `wtyj/agents/social/ali_quote_workflow.py:1058-1235`, never pass a Zernio
   conversation id to the phone-mask function. Default every projected lead to
   the generic `WhatsApp conversation` label.
2. Add a deterministic hydrator that accepts only contacts already resolved by
   the tenant-guarded provider lookup, strips an optional `whatsapp:` prefix,
   validates normal phone length, and returns only the masked last four digits.
3. Keep `phone_normalized` empty so the authenticated Quote Leads response does
   not expose a new full-phone field.
4. In `wtyj/dashboard/api.py:4471-4500`, resolve current lead conversation ids
   through `resolve_zernio_conversation_contacts()` off the event loop and apply
   the hydrator before filtering/counting the response.
5. Preserve status calculation, counts, no-cache headers, tenant isolation,
   conversation/quote state, and all customer-facing behavior. Send no message.

## Tests

1. A synthetic 24-hex conversation id containing 9–15 digits remains
   `WhatsApp conversation` and never becomes a masked phone.
2. A provider-confirmed phone ending in `8003` hydrates to
   `WhatsApp ••••8003` while the full normalized phone remains absent.
3. Missing, malformed, or too-short provider phones fail closed to the generic
   label.
4. The authenticated API invokes the provider resolver, preserves counts and
   filters, and returns the corrected masked suffix.
5. Run focused Quote Leads/API tests and the full repository suite.

## Success Condition

The authenticated live Ali Quote Leads response shows the masked suffix of the
provider-confirmed WhatsApp participant and never derives a phone from the
internal Zernio conversation id.

## Rollback

Revert the Brief 289 merge commit and redeploy through the normal pipeline. No
schema, customer, conversation, quote, or data migration is introduced.
