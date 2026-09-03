# BRIEF 327 — Provision Mermaid TRACY as a real Unboks demo tenant

**Status:** In progress | **Tenant:** `mermaid` | **Runtime port:** `8102` |
**WhatsApp:** new dedicated Zernio-provisioned number, purchase pending |
**Provider:** Zernio

## Outcome

Create the same operational shape used by Ali Car Rental: a dedicated tenant
container, dashboard workspace, Nginx API route, Zernio-owned WhatsApp
connection, tenant-specific account allowlist, AI controls, inbox, escalation,
and human takeover. This is not a website demo. No Mermaid website or local
phone mockup is part of the deliverable.

The public Meta asset is a fictional, clearly disclosed demo Page named
`Klein Curaçao Trip Desk Demo`. It must not use Mermaid in the Page name and
must not replace, rename, connect, or otherwise alter Mermaid's existing public
Facebook Page or public WhatsApp number.

## Fixed identities

- Unboks tenant: `mermaid`, package-labelled `Mermaid Boat Trips Demo` and
  displayed in the workspace as `Mermaid Boat Trips Curaçao`.
- AI assistant: `TRACY`.
- Dedicated demo WhatsApp Business number: buy the cheapest suitable available
  Zernio number exclusively for Mermaid; prefer US `+1` inventory when it is
  still among the lowest-cost options at checkout. No number is assigned yet.
- Existing Mermaid public contact: `+599 9 560 1530`. It is a sourced business
  fact only and must not be migrated or connected during the demo setup.
- Runtime: `/root/clients/mermaid`, container `wtyj-mermaid`, loopback port
  `8102`, public API prefix `/api/mermaid/`.
- Tenant dashboard: `https://dashboard.unboks.org/login?workspace=mermaid`.

## Runtime configuration

1. Use the non-booking DM Q&A path with `features.booking_flow=false`. TRACY may
   answer published trip questions but cannot see seats, hold inventory,
   accept payment, or change/cancel bookings.
2. Load the dated first-party Mermaid fact snapshot and the explicit conflict
   rules in `clients/mermaid/config/client.json`. The reservation form remains
   the only authority for live availability and checkout.
3. Label the actual inbound channel in the model prompt. WhatsApp must never be
   described to the model as a Facebook DM.
4. Before provider authorization, install a strict empty Zernio allowlist. This
   is the safe pre-connection state and rejects every inbound/outbound account.
5. After Meta/Zernio verifies the dedicated number, select only that number in
   Nr3. The callback/selection flow auto-writes the verified connection account
   into the allowlist; repair is a recovery action only. A healthy connected
   state requires exactly the selected provider account ID.
6. Do not commit passwords, access keys, provider IDs, callback tokens, API
   keys, webhook secrets, customer records, or OTPs. The versioned config is a
   reviewed template; live generated credentials stay only on the VPS.
7. Include Mermaid in the normal deploy and rollback target sets at port 8102.

## Meta and Zernio setup

1. Create the fictional Facebook Page `Klein Curaçao Trip Desk Demo` with a
   clear demo disclosure. Do not clone Mermaid's Page identity or imagery.
2. Start the WhatsApp connection from Nr3 for tenant `mermaid`. Nr3 creates a
   tenant-bound Zernio profile and a single-use state-bound authorization URL.
3. In Mermaid's Zernio profile, choose `Get a new number`, review and approve
   the live price/capabilities, complete the purchase, and continue to Meta
   registration. Never reuse an existing WhatsApp or mobile-app account.
4. If Meta presents more than one number, select only the exact number on the
   Mermaid Zernio purchase record; otherwise fail closed.
5. Confirm Nr3 reports `connected`, the display number is the dedicated number,
   and the strict allowlist contains only the verified Zernio account.

## Verification

- Focused tests cover identity, facts, channel labels, strict-empty isolation,
  escalation-marker removal, notification creation, and deploy/rollback sets.
- Full backend tests must pass.
- Live health must return 200 on loopback port 8102 and the public API route.
- A controlled WhatsApp message must enter only the `mermaid` tenant, receive a
  TRACY answer grounded in the approved snapshot, and appear in the Unboks
  inbox.
- A cancellation/refund question must create a human-review escalation without
  leaking the internal `[ESCALATE]` marker.
- Human takeover must mute AI for the conversation; hand-back must restore it.
- Ali and Roberto health and routing must remain unchanged.

## Rollback

Turn off the Mermaid WhatsApp channel and AI replies in Nr3, preserve a redacted
audit record, disconnect only the Mermaid demo Zernio profile, stop
`wtyj-mermaid`, and restore the timestamped pre-TRACY `client.json` backup if
configuration rollback is needed. Never disconnect or edit an Ali, Roberto,
Unboks, or existing Mermaid public asset. Runtime code rollback uses the normal
`wtyj-agent:previous` process and includes port 8102 health verification.
