# Mermaid flat pickup demo price
**Status:** Deployed and verified | **Files:** tenant catalog, catalog validation, money snapshot, guest presentation, understanding, documents, payment, tests | **Depends on:** Tracy UX release 65825fb | **Blocks:** priced pickup demo

## Context
The user requested a simulated USD 75 pickup cost anywhere on the island. Treat this as one flat charge per booking. New quotes should include it when pickup is requested; existing quoted and paid amounts are immutable.

## Why This Approach
Keep the fee, currency, coverage and basis in the tenant catalog and snapshot the charge with the reservation. Reject a prompt-only price change because checkout and PDFs would still exclude pickup. Collection time remains pending; knowing the price does not establish a collection time.

## Instructions
- Validate the catalog's optional fixed pickup amount and explicit currency/basis/coverage. Keep USD 75 in configuration only.
- Add one pickup line to the monetary snapshot when requested, independent of party size or location; never add it for pier arrival. Reject unsupported currency conversion.
- Use the persisted snapshot in all existing booking presentation; unknown historical pickup charges remain excluded. Update all six guest locales and the natural-language contract.
- Preserve the current reservation and payment records. Deploy only Mermaid with backup and health checks.

## Tests
Check island locations and party sizes, pier exclusion, historical snapshots after a catalog change, six-language quote/receipt/checkout consistency, and isolated model replay with provider sends disabled.

## Success Condition
A new three-adult pickup booking shows USD 450 trip + USD 75 pickup = USD 525 consistently, while historical USD 450 bookings remain unchanged.

## Rollback
Restore the previous Mermaid image and catalog/client presentation configuration from the release backup, preserving current customer data and credentials.

## Release evidence
- All 223 Mermaid tests passed, including flat fees across locations and party sizes, pier exclusion, immutable historical pricing, all six locales, delivery reconciliation and checkout concurrency.
- An isolated five-turn real-model replay quoted USD 75 for the whole booking island-wide and completed a USD 525 simulated booking. No provider messages sent. Rendered quote and receipt in six languages; English layout visually checked, retaining two quote pages and one receipt page.
- Live source: `8053f5d3f0b51db6449d44284e648cbafcc018b8`; image: `wtyj-agent:tracy-pickup-8053f5d`; digest: `sha256:612d9e0f4ec8eb010f9f733e0bc2b6754cc506c35b7a9b4add2bae5eb010ba52`.
- Public health 200; watchdog healthy; inbox/auto-reply enabled; deployed behavioral file hashes match source. Six peer containers unchanged. Live catalog calculates three adults plus pickup at USD 525; original Calvin booking remains booked at USD 450 with no retroactive pickup charge.
- Backup: `/root/backups/tracy-pickup-8053f5d`; prior image: `wtyj-agent:tracy-ux-65825fb`. Maintenance marker removed after deployment.
