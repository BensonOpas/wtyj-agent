# Mermaid reservation demo — deployed 3 September 2026

## Actual deployed state

- Backend revision: `70decedc6883bc4d62670d303699b1bd7c582b8b`.
- Dedicated image: `wtyj-agent:mermaid-reservations-70deced`.
- Image digest: `sha256:13778d9b8db0a45bfcbe15795fd73e9f7ed6381f49479c6b9470b74f95a79fe5`.
- Frontend revision: `b8a38e1fa54073bb136eae50ebb5cca943de96d7`.
- Tenant: `mermaid`; dedicated demo WhatsApp: `+1 223 276 0075`.
- Activated and freshly read back at approximately 22:38 UTC: WhatsApp inbox
  true, AI auto-reply true, Facebook DMs false, strict one-account binding.
- Only Mermaid's container was replaced. Other running tenant containers and
  their image/container identities matched the pre-release snapshot.

This is the authorized reservation **demo**, not a real inventory/payment
integration: assumed seats, signed no-money checkout, quote PDF, payment receipt
with demo booking code, and reminders disabled. The customer stays in WhatsApp
for intake and documents; the payment-only simulation opens its signed page.
No synthetic test reservations were copied into the live database.

## Evidence

- Combined local backend suite: **2,544 passed**, six existing UTC deprecations.
- Combined Python 3.12 CI succeeded: GitHub Actions run `33813456732`.
  Main/shared deployment jobs were intentionally skipped.
- Reviewed foundation `f4e08c9e51b7c167cd27cd489905b45bdcf494db` and its CI
  are incorporated. The combined release retains public configuration
  projection, final prompt credential redaction, account guards and worker fences.
- Exact-image isolated real-model canary passed all six languages and the
  ordinary short-answer journey (Saturday, 2, 0, none, name, pier).
- Quote generation, signed simulated checkout, receipt generation and repeated
  callback idempotency passed. Provider sender was mocked: **zero real WhatsApp
  sends** in this isolated canary. This is not a claim of device-level delivery.
- PDF pages were rendered and visually inspected; the German date label column
  was widened to prevent a broken word.
- Public health, authenticated client profile, agent status, Reservations,
  catalog and public-config endpoints returned 200.
- Protected UI login, Today, Reservations and Trip & Pricing passed desktop
  and mobile browser checks with no JavaScript errors. The prior Reservations
  service-unavailable error is resolved.

## Credential remediation

An initial old-revision rehearsal could include mounted credentials in model
context. It was stopped; it sent no WhatsApp messages. Before activation the
supported Nr3 password reset completed, then Mermaid's access key, connect token
and persisted dashboard session were rotated while its service was stopped and
tenant lifecycle jobs were quiescent. Provider ownership/bindings were preserved.

The old password and session were rejected with 401; the old connect token was
rejected by the actual validator. The new credentials and fresh tenant generation
validated. The final isolated model canary also checked every outgoing model
payload against configured credential values before dispatch. No credential
values belong in this document, Git, screenshots or task output.

Existing dashboard sessions need fresh authentication. Supported recovery:
`https://icp.unboks.org/password/forgot?workspace=mermaid`, or the authorized
Nr3 tenant temporary-password process.

## Routing limitation recorded separately

Mermaid's explicit `^~ /api/mermaid/` route maps only to port 8102 and identifies
Mermaid. Its credentials were rejected against unknown, Ali and Despertares
profile routes. However, the pre-existing shared Nginx regex fallback still maps
unknown tenant slugs to the Unboks backend: an unknown-slug health check returned
200. No cross-tenant data access was demonstrated. Follow-up issue **#335**
records the shared-router correction; this release did not change shared Nginx.
Do not describe the whole platform's unknown-slug routing as fail-closed.

## Recovery

Protected post-remediation snapshot:
`/root/backups/mermaid-reservations/release-70deced` (config, environment, compose,
consistent database backup, image/container manifest and enabled Nginx snapshot).
Preserve the live database/delivery audit during a code rollback. Do not restore
pre-remediation credentials or the old vulnerable prompt builder. Pause AI first
if the live flow misbehaves; retain the strict provider binding and isolate any
follow-up release to Mermaid.

Backend PR #334 remains the source integration record; deployment of its exact
branch image is not a claim that the backend PRs were merged to main. A fresh
authorized inbound WhatsApp booking is the remaining device-level smoke test.
