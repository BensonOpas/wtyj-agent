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
| Dedicated Mermaid tenant and TRACY behavior | Versioned `mermaid` tenant package, prompt boundaries, tests, runbooks, and loopback compose exist | Nr3 shows the existing `mermaid` tenant as active with agent name `TRACY`; the current live runtime is healthy and passed one controlled reply, while the reviewed hardening release and canonical-route recheck remain release gates |
| Unboks operator workspace | Tenant identity and expected runtime endpoints are defined | Authorized operator opened `mermaid` in Nr3 on `2026-09-03`; no separate `mermaid-demo` workspace was created |
| WhatsApp demo number | Dedicated Zernio number `+1 223 276 0075` was purchased on `2026-09-03` | Meta and Zernio show the number active; Nr3 reports connected/healthy with one exact strict account; inbox-only and one-reply canaries passed |
| Zernio | Tenant-bound authorization/status flow is implemented | Connected after moving only the dedicated number from Zernio's Default Profile to Mermaid's profile and completing a fresh Meta authorization; Nr3 status repair persisted the exact binding |
| Facebook demo Page | `Klein Curaçao Trip Desk Demo` exists with the disclosure and original artwork | Its WhatsApp action remains empty; add it only after the hardened runtime release and final live canary |
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
- Number selection: US `+1` inventory was selected at `$3/month`. Meta
  authorization, the exact provider binding, strict Nr3 reconciliation, an
  inbox-only canary, and one controlled live TRACY reply passed on
  `2026-09-03`.
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
  gluten-free FAQ/persona and unsupported-attachment handoff fields, preserves
  credentials/provider state, and runs with Mermaid stopped and concurrent
  config writers paused (`--apply --service-stopped`).
- [ ] A protected rollback snapshot covers Mermaid's config, environment,
  compose, state database, Nginx site, and running image.
- [ ] The legacy dashboard credential identified during review has been rotated
  through the protected operator process.
- [ ] The old-revision model rehearsal's `password`, `access_key`, and
  `whatsapp_connect_token` exposure has been remediated through protected
  rotation or confirmed expiry/non-auth status, with prior access rejected.
  Password reset alone does not invalidate persisted dashboard bearer sessions;
  coordinate session invalidation and operator re-login before activation.
- [ ] After the hardening release, `whatsapp_inbox` is deliberately enabled,
  `ai_auto_reply` and `facebook_dms` are false, and Mermaid's provider
  allowlist remains strict with exactly the already verified account.

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
- [ ] Add the `Send WhatsApp message` action only after the hardened Mermaid
  runtime is deployed and a final one-message/one-reply canary passes. Meta has
  already verified the dedicated demo number.
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
  Zernio lists `+1 223 276 0075` as Purchased and Active.
- [x] Complete Meta Embedded Signup using the dedicated `Mermaid Demo - Unboks`
  business portfolio and WhatsApp Business Account. The original Meta
  portfolio was already at its number limit; no existing consumer, WhatsApp
  Business app, public Mermaid, or other tenant number was moved or reused.
- [x] Move only the new number from Zernio's `Default Profile` to the dedicated
  Mermaid profile after Zernio returned the exact
  `whatsapp_number_pinned_to_profile` error.
- [x] Complete a fresh authorization and select only the BSP-provided
  `+1 223 276 0075` number under `Mermaid Demo - Unboks`.
- [x] Wait for provisioning and confirm Zernio created one active WhatsApp
  account with the exact Mermaid profile and number.
- [x] Refresh Nr3 status, then run its verified-account allowlist repair. Nr3
  reports `Connected`, `healthy`, and `Strict` with exactly one account.
- [x] Confirm the same account/profile is not assigned to Ali, Roberto, or
  Unboks and that the live Mermaid event ledger contains no foreign account.
- [x] Confirm refresh/reconciliation did not switch accounts, create a second
  connection, or enable Facebook DMs.

An authorization callback marked pending, a phone-selection screen, or a
queued allowlist repair is not `Connected`. Wait for the exact terminal status
and keep traffic disabled.

Forensic result on `2026-09-03`: Meta completed successfully and Zernio created
the correct account, but the deployed Nr3 callback rejected Zernio's standard
redirect because Nr3 expected the wrong state format. Refreshing status and
using Nr3's verified-account repair reconciled the provider truth safely. The
callback fix remains in control-panel PR #94. Current safe state is tenant
active, WhatsApp inbox enabled, AI auto-reply paused, Facebook DMs off,
connection healthy, and a strict one-account allowlist.

## Gate 5 - controlled activation

Named Unboks operator and one tester:

- [x] Enable only `whatsapp_inbox`. Keep `ai_auto_reply` and `facebook_dms`
  false.
- [x] Send one unique `Channel check <timestamp>` message from a tester number
  that is not any tenant's business number.
- [x] Verify it appears exactly once in Mermaid and receives no automatic
  reply. Runtime status was `paused / tenant_agent_paused`.
- [x] Verify no message from another tenant appears in Mermaid. The live audit
  contained only Mermaid's exact provider account; the other three tenant
  bindings were unchanged.
- [x] Enable `ai_auto_reply` deliberately and send one published-fact question.
- [x] Verify exactly one TRACY response is stored and delivered, with the
  correct virtual-assistant identity and no availability or booking claim.
  The live answer correctly gave Fishermen's Pier at 06:45 and return boarding
  at 15:20; runtime status was `replied / provider_send_ok`. AI was paused
  again after the proof.
- [ ] Exercise cancellation/refund escalation; the operator sees the handoff
  and the guest never sees `[ESCALATE]`.
- [ ] Exercise takeover and hand-back; TRACY remains muted during takeover and
  resumes only after hand-back.
- [ ] Exercise one duplicate inbound delivery; the guest still receives at
  most one automated reply.
- [ ] Exercise a safe failure/retry path and confirm no duplicate reply, stale
  spinner, cross-tenant record, or secret appears.
- [ ] Verify operator reply/guidance retries retain their original `request_id`,
  including a lost HTTP response after a provider-confirmed send.
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
