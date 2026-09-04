# Mermaid pickup time
**Status:** Deployed and verified | **Files:** tenant catalog and version, catalog helpers, guest experience, understanding, workflow, tests, runtime overlay | **Depends on:** short checkout release 521379d | **Blocks:** none

## Context
The user requested one island-wide pickup time, one hour before the trip. The approved catalog has a 06:45 arrival/check-in time and no outbound departure time. Use check-in as the explicit reference: 05:45 pickup in Curaçao local time. The existing flat USD 75 simulation remains unchanged.

## Why This Approach
Keep the lead time in tenant configuration and derive the displayed time once in Python for the model and all customer surfaces. Reject model-only arithmetic and a guessed boat departure time because they could produce different times in chat and documents. This is the current demo schedule, not evidence of a real driver dispatch or a traffic guarantee.

## Instructions
- Add a validated same-day pickup lead time to the service catalog and bump the catalog version. Expose its derived local pickup time to the understanding prompt.
- Replace pending-time language for included pickup in all six locales through the shared transport presentation. Preserve unpriced historical pickup as excluded/unconfirmed and preserve all monetary snapshots.
- In the one-call conversation contract, give the pickup time proactively when pickup is discussed, ask for missing accommodation details, and avoid time-selection or extra confirmation loops. Answer timing questions for booked pickup reservations without restarting intake.
- Keep pier guests on the existing 06:45 check-in instructions. Apply the current schedule to newly rendered documents and replies; do not resend or replace previously delivered PDFs.
- Overlay only changed runtime files on the current image. Merge only the reviewed catalog fields and client workflow version into live configuration; preserve account credentials, controls, records and short checkout routing.

## Tests
Verify time calculation and invalid configuration, island-wide timing and pier exclusion, all six languages across summary/quote/receipt/checkout, unchanged historical money, and an isolated real-model replay of pickup selection and a booked guest's timing question. Inspect newly rendered PDF layouts.

## Success Condition
Tracy naturally states 05:45 pickup, consistently across booking surfaces, while pier check-in remains 06:45 and customer amounts and state remain unchanged.

## Rollback
Restore the prior Mermaid image and catalog/client configuration from the release backup and restart only Mermaid. Keep current customer data and public short-link routing intact.

## Verification
- 251 Mermaid and availability/status tests passed, including six-language PDF/checkout timing, configured offset validation, pier exclusion and unchanged historical monetary snapshots.
- Seven real-model turns passed in a disposable container with only the Anthropic key and no provider send credentials. Tracy gave 05:45 while asking for the missing accommodation, included it in the summary and quote, answered a booked guest's pickup question directly, kept a self-driving guest on 06:45, and quoted pickup timing/cost for Westpunt without opting the guest in. Simulated receipt delivery was mocked; no customer sends.
- English and German rendered quote/receipt layouts checked: two quote pages and one receipt page, readable transport text with no clipping.
- Deployment is coordinated with the concurrent Mermaid handoff-acknowledgment incident fix to avoid one change overwriting the other. The runtime overlay here contains pickup changes only; the combined release must preserve the incident fix too.

## Live release
- Pickup source `fe207b9` and the soft-review acknowledgment repair are deployed together at `33272b1272c6a13ebd6f0d6492d8cdd1703112c3`, image `wtyj-agent:tracy-soft-review-33272b1`, digest `sha256:83f8afba5e5c43c86f365349e2a45f93b1d037c94ad5011ab0431e87d8a7152e`.
- The release owner verified the exact image with 243 focused checks, seven pickup model turns and three handoff model turns, with provider sends disabled. Minimal live catalog/client v3 changes preserve credentials, pricing and other configuration; maintenance is removed and peer containers are unchanged.
- Independently verified the public checkout by signed GET: 05:45 is displayed, public health is 200, and the existing booked USD 600 reservation has identical intake and monetary-snapshot hashes before and after the change. No customer messages or payment POSTs were sent by this task.
- Backup: `/root/backups/tracy-soft-review-33272b1272c6`; release evidence: `/root/releases/tracy-soft-review-20260904`. Roll back the combined image/configuration using that backup, preserving current customer data. Do not deploy the pickup-only overlay over this combined release, which would remove the handoff repair.
