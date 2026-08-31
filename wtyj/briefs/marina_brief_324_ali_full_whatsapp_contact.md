# BRIEF 324 — Show Ali's full WhatsApp contact in the authenticated customer workspace
**Status:** Approved by owner | **Files:** `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/tests/agents/test_ali_quote_leads.py` | **Depends on:** Brief 289, Brief 323 | **Blocks:** none

## Context

Ali's authenticated Customers workspace currently shows only a masked WhatsApp
suffix such as `WhatsApp ••••6231`. The owner rejected this privacy presentation:
the number is operational customer-contact data supplied by the connected
WhatsApp provider, and staff need it to communicate with the customer. The
existing grey, masked presentation also looks disabled even though the rental
file and conversation are active.

The earlier identity fix remains important: internal Zernio conversation ids
are routing keys and must never be mistaken for customer phone numbers.

## Why This Approach

Expose only the provider-confirmed participant number at the existing
authenticated Quote Leads API boundary. Canonicalize valid provider values to
an E.164-style `+<digits>` display and populate the existing phone fields, so
the Customers UI renders the real number without a frontend or schema change.
Malformed or unresolved provider values continue to fail closed to the generic
`WhatsApp conversation` label.

Keeping the mask was rejected by the owner because it prevents normal customer
service. Deriving a number from the conversation id was rejected because it can
show a false number. Persisting another phone copy was rejected because the
provider resolver remains the canonical source and the authenticated read model
can hydrate it on demand.

## Instructions

1. Replace the suffix-mask helper in
   `wtyj/agents/social/ali_quote_workflow.py:1371` with a provider-number
   normalizer that accepts only 9–15 digits and returns `+<digits>`.
2. Update `hydrate_quote_lead_contact_identities()` to populate both existing
   phone fields with that full provider-confirmed number.
3. Preserve the generic fallback for missing or malformed provider contacts.
4. Preserve the rule that `list_quote_leads()` never treats its internal
   conversation id as a phone number.
5. Change no customer, conversation, quote, reservation, or document data.

## Tests

1. A provider-confirmed WhatsApp contact is returned in full E.164-style form
   in both existing phone fields.
2. The authenticated Quote Leads endpoint returns the full provider-confirmed
   number.
3. Missing, malformed, and too-short provider values retain the generic label
   and an empty normalized field.
4. A digit-heavy internal Zernio conversation id is never shown as a phone.
5. Run the focused Quote Leads tests and the full backend suite.

## Success Condition

Ali staff see the complete provider-confirmed WhatsApp number in Customers,
while unresolved contacts and internal routing ids never appear as phone
numbers.

## Rollback

Revert Brief 324 and redeploy. No schema or customer-data rollback is required
because the change affects only the authenticated read projection.
