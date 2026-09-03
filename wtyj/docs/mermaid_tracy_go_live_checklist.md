# TRACY owner-action and go-live checklist

This is the shortest credible path from the Monday demonstration to a real
Mermaid WhatsApp service on Unboks. It deliberately separates repository work
from actions that only the Mermaid owner or an authorized account administrator
can perform.

No step in this checklist creates a Mermaid website. The only Page described
here is the fictional, clearly disclosed `Klein Curaçao Trip Desk Demo` Page.

## Current truth, checked 3 September 2026

| Capability | Repository evidence | External/live evidence required before claiming it is live |
|---|---|---|
| Dedicated Mermaid tenant and TRACY behavior | Versioned `mermaid` tenant package, prompt boundaries, tests, runbooks, and loopback compose exist | Nr3 was opened on `2026-09-03` and showed the existing `mermaid` tenant as active with agent name `TRACY`; runtime health, canonical routing, and cross-tenant rejection still require release verification |
| Unboks operator workspace | Tenant identity and expected runtime endpoints are defined | Authorized operator opened `mermaid` in Nr3 on `2026-09-03`; no separate `mermaid-demo` workspace was created |
| WhatsApp demo number | Dedicated Zernio number `+1 223 276 0075` was purchased on `2026-09-03` | Meta and Nr3 must show that exact number and an account uniquely owned by Mermaid's tenant |
| Zernio | Tenant-bound authorization/status flow is implemented | A fresh owner-authorized callback succeeds, strict allowlist persistence succeeds, and Nr3 reports connected |
| Facebook demo Page | `Klein Curaçao Trip Desk Demo` exists with the disclosure and original artwork | Verify its owning Meta business; keep its WhatsApp action empty until the dedicated number is connected |
| Facebook messages | Kept fail-closed by default | Separate Facebook messaging authorization and canary; otherwise `facebook_dms` remains off |
| Booking and payment | TRACY redirects to Mermaid's first-party reservation form | Mermaid's existing reservation system remains authoritative; no Unboks booking or payment integration is claimed |

Treat every external item as **not connected** until the evidence in the final
column has been observed in the provider and in Nr3. Configuration values,
screenshots, mock-ups, generated links, and callback URLs are not proof of a
live connection.

## Fixed identities

- Tenant slug: `mermaid`
- Tenant package label: `Mermaid Boat Trips Demo`
- Visible workspace business name: `Mermaid Boat Trips Curaçao`
- Assistant: `TRACY`
- Demo WhatsApp number: dedicated Zernio-provisioned `+1 223 276 0075`,
  purchased exclusively for Mermaid on `2026-09-03`.
- Number selection: US `+1` inventory was selected at `$3/month`; WhatsApp is
  not live until Meta authorization, exact provider binding, and canaries pass.
- Fictional Page: `Klein Curaçao Trip Desk Demo`
- Official public Mermaid number, read-only reference: `+599 9 560 1530`
- Official booking path:
  `https://reservations.mermaidboattrips.com/Reservations/`

The official public number, Calvin's existing WhatsApp and WhatsApp Business
accounts, every other Unboks tenant number, and Mermaid's existing Facebook or
Instagram profiles must not be connected, renamed, disconnected, migrated, or
otherwise mutated as part of the demo.

The normal public trial form was submitted for `Mermaid Demo`, email-verified,
approved in Nr3, and its eight-step business intake completed on `2026-09-03`.
The approval note explicitly says to use the existing `mermaid` tenant and not
create a duplicate. Nr3 still offers a final `Create workspace` action with
slug hint `mermaid-demo`, while the intended `mermaid` tenant already exists
and is active. Do not run that final action unless Nr3 first gains an explicit,
audited way to link this completed signup to the existing `mermaid` tenant.

## Gate 1 - reviewed Unboks release

Unboks delivery owner:

- [ ] The runtime and control-panel PRs are independently reviewed and merged
  through the normal Unboks release path.
- [ ] Web app and host worker use the same queue-protocol revision; no tenant
  lifecycle jobs are active during the coordinated upgrade.
- [ ] The hardened canonical Nginx route maps `/api/mermaid/` only to
  `127.0.0.1:8102`; unknown tenant slugs return 404 without an identity header.
- [ ] The Mermaid container is healthy and the dashboard profile identifies
  only `mermaid`.
- [ ] The live Mermaid content sync, if still needed, changes only the reviewed
  gluten-free FAQ/persona fields and preserves generated credentials and
  provider state.
- [ ] A protected rollback snapshot covers Mermaid's config, environment,
  compose, state database, Nginx site, and running image.
- [ ] The legacy dashboard credential identified during review has been rotated
  through the protected operator process.
- [ ] `whatsapp_inbox`, `ai_auto_reply`, and `facebook_dms` are all false, and
  Mermaid's provider allowlist is strict and empty before authorization.

Evidence to record: release commit, health timestamp, route/isolation result,
rollback label, and toggle state. Never record a password, token, callback
state, provider account ID, or customer message in public evidence.

## Gate 2 - Mermaid owner decisions

Mermaid owner:

- [x] Approve a newly purchased Zernio number dedicated exclusively to Mermaid;
  no existing WhatsApp, WhatsApp Business app, Cloud API, personal, or other
  tenant number will be migrated or reused.
- [x] At Zernio checkout, confirm the displayed recurring price, country,
  capabilities, billing terms, and any KYC requirement. Prefer a US `+1`
  number only if it is still the cheapest suitable option at purchase time.
  Confirmed US local, WhatsApp-capable, `$3/month`, no KYC shown.
- [x] Complete the paid number purchase using the Mermaid Zernio profile and
  retain the exact assigned E.164 number in protected operator records.
  Purchased `+1 223 276 0075` on `2026-09-03`.
- [ ] Approve the fictional Page name and its required `PRIVATE DEMO`
  disclosure. The Page must not use Mermaid's public Page name or imply it is an
  official profile.
- [ ] Name the people authorized to administer Meta assets, authorize Zernio,
  operate the Unboks inbox, and approve eventual use of the public Mermaid
  number.
- [ ] Approve the source-grounded rates and operational facts, including the
  conservative escalation treatment for cancellation, refund, scuba, allergy,
  accessibility, medical, and pregnancy questions.
- [ ] Choose the operating hours, human escalation recipient, response-time
  expectation, privacy/retention policy, and customer-facing language set for
  production. The demo currently supports English, Dutch, German, Spanish, and
  Portuguese; Papiamentu must not be promised without owner approval and
  quality review.

If the dedicated number already belongs to another provider setup, stop. Its
migration or coexistence plan is an outcome-changing owner decision, not a
routine Unboks configuration edit.

## Gate 3 - fictional Facebook Page

Authorized Meta administrator, in the owner's browser session:

- [x] Create `Klein Curaçao Trip Desk Demo` as a new Page. Do not rename or
  replace Mermaid's public Page.
- [x] Use the bio, disclosure, category, and original artwork from
  the [Facebook Page package](mermaid_tracy_facebook_page_package.md).
- [x] Add only clearly fictional demo contact data, using reserved `.example`
  email/link values and an address literally labelled `DEMO LOCATION` and
  `(fictional)`.
- [x] Remove the superseded `+599 9 686 5665` public-phone entry, then leave the
  public phone and WhatsApp action empty until the newly purchased Mermaid
  number exists and passes Meta/Zernio verification. Removed and verified in
  Facebook Contact info on `2026-09-03`.
- [x] Publish and pin the `PRIVATE DEMO` disclosure before any messaging test.
- [ ] Configure the messaging greeting from the Page package after the owning
  business and messaging path are verified.
- [ ] Keep Meta/Facebook native instant replies and automated rules off. Zernio
  and Unboks must remain the only intended automated reply path.
- [ ] Add the `Send WhatsApp message` action only after Meta has verified the
  dedicated demo number.
- [ ] Verify the Page is visible in Meta under the expected owning business and
  that no Mermaid public asset was modified.

Owner-only inputs: Meta login, MFA, business ownership proof, Page creation,
asset assignment, terms acceptance, and any business verification. These are
never placed in Git, copied into the runbook, or requested in chat.

## Gate 4 - WhatsApp and Zernio authorization

Unboks operator prepares the tenant-bound request; Mermaid's authorized Meta or
Zernio administrator completes authorization in their own browser:

- [x] Open the Mermaid tenant workspace, not Ali, Roberto, or Unboks. Verified
  in Nr3 on `2026-09-03`: slug `mermaid`, status active, agent `TRACY`.
- [x] In the Mermaid-bound Zernio profile, choose `Get a new number`, review the
  current price and capabilities, and complete the owner-approved purchase.
  Zernio now lists `+1 223 276 0075` as Purchased and Active; WhatsApp remains
  Off pending Meta authorization.
- [x] Continue from that purchase into Meta Embedded Signup. The flow was
  attempted twice on `2026-09-03`; the BSP-provided number appeared, but Meta
  returned a generic phone-number error both times. No existing consumer or
  WhatsApp Business mobile-app account was reused.
- [ ] The owner opens the link, signs in, completes MFA and business ownership
  checks, and authorizes only the intended demo assets.
- [ ] If more than one provider profile, Page, WhatsApp account, or phone number
  is shown, stop and identify ownership before selecting anything.
- [ ] Select only the new number shown on Mermaid's Zernio purchase record. If
  it is missing, if the public Mermaid number `+59995601530` appears as the
  intended selection, or if any existing user/tenant number appears, stop and
  keep every toggle off.
- [ ] Wait for Zernio's number provisioning and Meta registration to complete;
  purchased numbers are verified in that provider flow rather than through an
  existing phone or eSIM.
- [ ] Refresh Nr3 status. It must prove an active WhatsApp account, exact
  tenant-bound profile ownership, exact phone selection, and successful strict
  allowlist persistence.
- [ ] Confirm the Mermaid allowlist is `strict` with exactly one account and
  that the same provider account or profile is not assigned to any other
  tenant.
- [ ] Confirm callback replay, duplicate delivery, or page refresh did not
  switch accounts, create a second connection, or enable a channel.

An authorization callback marked pending, a phone-selection screen, or a
queued allowlist repair is not `Connected`. Wait for the exact terminal status
and keep traffic disabled.

Live Nr3 safety observation on `2026-09-03`: its deployed UI briefly accepted
WhatsApp Off -> On even though the connection card still showed no phone, no
provider account, and an empty strict allowlist. The toggle was immediately
restored to Off. Do not attempt activation again until the pre-connection
activation guard in control-panel PR #94 is deployed and verified. Current safe
state is tenant active, WhatsApp Off, all other channels Off, connection
pending, strict allowlist empty.

## Gate 5 - controlled activation

Named Unboks operator and one tester:

- [ ] Enable only `whatsapp_inbox`. Keep `ai_auto_reply` and `facebook_dms`
  false.
- [ ] Send one unique `Channel check <timestamp>` message from a tester number
  that is not any tenant's business number.
- [ ] Verify it appears exactly once in Mermaid, receives no automatic reply,
  and does not appear in Ali, Roberto, or Unboks.
- [ ] Verify no message from another tenant appears in Mermaid.
- [ ] Enable `ai_auto_reply` deliberately and send one published-fact question.
- [ ] Verify exactly one TRACY response is stored and delivered, with the
  correct virtual-assistant identity and no availability or booking claim.
- [ ] Exercise cancellation/refund escalation; the operator sees the handoff
  and the guest never sees `[ESCALATE]`.
- [ ] Exercise takeover and hand-back; TRACY remains muted during takeover and
  resumes only after hand-back.
- [ ] Exercise one duplicate inbound delivery; the guest still receives at
  most one automated reply.
- [ ] Exercise a safe failure/retry path and confirm no duplicate reply, stale
  spinner, cross-tenant record, or secret appears.
- [ ] Run desktop and mobile browser checks with no console error, failed
  request, obstructing overlay, or broken responsive layout.

If any item fails, turn AI off first, then turn the inbox off if identity or
routing is uncertain. Preserve the audit trail and return to the labelled
simulation. Do not improvise with the public Mermaid number.

## Gate 6 - production operating approval

Mermaid owner and Unboks delivery owner together:

- [ ] Review the canary evidence and explicitly approve continued traffic.
- [ ] Confirm named inbox coverage, escalation recipient, after-hours behavior,
  incident contact, pause authority, retention policy, and change owner.
- [ ] Confirm the official booking link and current published prices immediately
  before activation.
- [ ] Decide whether the dedicated demo Page and number remain a pilot or
  whether a separate cutover to an official Mermaid number should be planned.
- [ ] Keep Facebook DMs off until Facebook messaging has its own authorization,
  ownership check, strict binding, isolation test, and reply-count canary.
- [ ] Monitor the first controlled traffic window and define an explicit end
  time or handoff to the on-duty operator.

## Future move from the dedicated pilot number to an official Mermaid number

The Unboks tenant, TRACY knowledge, safety rules, and operator workspace can be
kept. The provider identity cannot simply be edited in JSON. Use a new owner-
authorized cutover:

1. Pause AI and both message channels.
2. Confirm whether the official number currently uses the consumer WhatsApp
   app, WhatsApp Business app, Cloud API, or another provider. The owner chooses
   a supported migration/coexistence path and accepts any service interruption.
3. Return Mermaid to a strict empty allowlist before replacing the connection.
4. Create a fresh tenant-bound authorization and select only the newly approved
   official account and exact number.
5. Prove unique ownership, persist the strict account binding, and repeat every
   inbox-only, isolation, duplicate, reply, escalation, takeover, failure, and
   mobile/desktop canary above.
6. Enable ongoing traffic only after joint approval. Disconnect the demo asset
   only when rollback no longer depends on it.

No production-number mutation, provider migration, paid activation, or business
ownership change occurs without the Mermaid owner's explicit participation.

## Evidence packet

Store only sanitized evidence:

- reviewed Git commit and PR links;
- complete automated test summary;
- Mermaid and unknown-slug health/isolation results;
- desktop and mobile screenshots with synthetic data only;
- normalized-number match shown without account IDs or tokens;
- strict allowlist status recorded as a count, not the provider identifier;
- one-message/one-reply, escalation, takeover, hand-back, duplicate, and
  recovery results; and
- owner approvals and remaining decisions without credentials or verification
  codes.

Never include environment files, live `client.json`, raw callbacks, provider
responses, tokens, account/profile IDs, OTPs, passwords, real customer data, or
credential-bearing backups in an issue, PR, screenshot, or meeting deck.
