# Mermaid booking contact number
**Status:** Deployed and verified | **Files:** contact validation, tenant persona/catalog, understanding, workflow/store, quote, dashboard projection and tests | **Depends on:** reply-layout release 796d5a2 | **Blocks:** None

## Context
The user requires a phone number so the team can reach a guest about urgent trip changes, such as weather preventing departure. The current intake collects a name and transport but no guest-supplied contact number. A provider conversation identifier is not a verified or customer-selected callback number.

## Why This Approach
Collect one explicit international contact number after the reservation name, retain it in intake, include it in the confirmation summary and quote, and expose it through the authenticated reservation API. Reject silently copying sender metadata and reject a prompt-only requirement that the reservation store could bypass. Validate number format without claiming reachability or verification. Existing reservations remain readable and idempotent; they do not restart intake for general questions.

## Instructions
- Add tenant wording explaining the purpose naturally and requesting the country code. Capture a supplied number anywhere in the conversation, ask only if missing, and ask for the full number if the guest says to use the current WhatsApp number.
- Normalize common international punctuation and 00 prefixes without inferring a country. Python validates the structured field; the model understands the guest's language and intent in the existing one-call flow.
- Make contact required before a new summary can be approved and a new reservation created. Missing, invalid or corrected contact must not bypass fresh summary confirmation. Include contact in new summary identity while retaining legacy idempotency.
- Show the contact in the quote and authenticated reservation projection/search so it is available to the team. Keep existing money, pickup, documents and booking records unchanged.
- Verify missing/invalid contact, correction/reconfirmation, explicit early contact, legacy reads/replay, six-language presentation, the one-page quote and an isolated real-model journey. No customer sends and no automated cancellation alerts are part of this change.

## Tests
Focused integration checks for the complete contact step, storage gate, normalized contact, legacy compatibility, API visibility and quote pagination; then existing Mermaid regression coverage and isolated model replies.

## Success Condition
A new booking cannot be finalized without a customer-supplied contact number, and the customer and team can see the saved number.

## Rollback
Restore the previous Mermaid image plus client/catalog configuration from the deployment backup, retaining customer data and newly saved contact fields.

## Verification
- 323 Mermaid/status tests passed locally; 96 focused checks passed in the exact release image. Existing complete-booking fixtures and replay scripts now explicitly supply the contact number or include the new collection step.
- Seven isolated real-model turns covered the missing-contact question and purpose, a same-WhatsApp-number reply without copying metadata, formatted contact, correction/reconfirmation, a USD 300 quote, early Dutch contact and a local number without country code. One additional isolated turn checked simpler same-number wording after removing technical terminology from the guidance. No provider messages were sent.
- The contact appears in localized summaries and quotes across all six languages. Quote pagination checks passed, including long guest/address fixtures; the German contact quote was visually inspected as one page. Authenticated API tests cover contact visibility/search and null contact on historical records.
- Deployed source `45cfbb2` as `wtyj-agent:tracy-contact-45cfbb2`, digest `sha256:7747f2bb5bce7b7b6eee1beda452b9e04433edab0574a90d2a90e8531974414f`, catalog `mermaid-demo-v5-2026-09-03`. Backup: `/root/backups/tracy-contact-45cfbb2`. The live prompt and missing-contact gate were checked without creating a reservation. Exact runtime source hashes match, the existing reservation's monetary snapshot is unchanged, and all six peer containers are unchanged. Public health and watchdog are healthy.
