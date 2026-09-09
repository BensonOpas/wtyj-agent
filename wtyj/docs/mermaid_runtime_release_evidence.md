# Mermaid runtime release evidence — 3 September 2026

Canonical repository: `BensonOpas/wtyj-agent`.
Foundation branch: `codex/mermaid-tracy-real-tenant`, PR #324, issue #323.
Reservations integration: PR #334, branch `codex/mermaid-whatsapp-reservations-demo`.

The unrelated local demo branch `codex/issue-881-mermaid-tracy-demo` and its
`ac921be` commit are not Unboks runtime evidence. No files from that checkout
belong in this release. The foundation below is the Python Unboks runtime.

## Verified foundation changes

- Account ownership is checked before inbound storage, provider history access,
  cached-contact reuse, and each outbound attempt. Invalid strict configuration
  stays unavailable rather than reusing a stale allowlist.
- Durable inbound and failed-event records, recovery claims, and worker fencing
  prevent expired workers from sending or overwriting newer state.
- Unsupported attachments and failed sends produce durable, dashboard-visible
  handoffs; a deleted notification marker cannot stand in for an actual work item.
- Operator text/media/guidance is prepared once per action and retained across
  retries. Provider confirmation, local transcript, notification completion, and
  media usage are committed consistently. Soft replies always use relay mode.
- Public business context uses an explicit shared projection before reaching
  the model or `/config`; credentials and internal provider fields are excluded.
- Strict social publishing requires explicit platform configuration and owned
  provider accounts; Mermaid's WhatsApp-only configuration permits no social
  publishing targets.
- The content-sync tool preserves credentials and current provider bindings,
  requires stopped-service acknowledgement, and preserves recovery material
  after an interrupted or raced atomic exchange.

## Verification record

Final complete backend suite after all code fixes: **2,468 passed**, six existing
`payment_stub.py` UTC deprecation warnings, 71.43 seconds (local Python 3.14).
The repository CI repeats the full suite on Python 3.12; its final result is
linked in PR #324 against the immutable commit. `git diff --check` passed.

Independent final review: 145 focused tests passed; a second reviewer's 97-test
group and both original model-leak reproductions passed. Both reviewers found
no remaining blockers in the reviewed boundaries. These counts overlap the
full suite and are not additional tests. Publishing checks passed 81 tests and
114 routing-compatibility tests; primary and auxiliary model calls were covered.

Initial integration run:
2,376 passed and two failures. Both failures were stale test assumptions:
an unconfigured mock looked AI-muted, and a provider fixture returned HTTP 201
without the message identity/delivery status now required for confirmation.
After correcting those fixtures, the affected suites and operator-outbox tests
passed together: 60 tests. These are regression tests using synthetic provider
responses, not live WhatsApp traffic.

## Remaining release gates

1. Commit and push the complete foundation; require full repository CI and
   independent review. Reservations merges that exact commit and retests its
   combined branch before building a dedicated Mermaid image.
2. Pair the backend with dashboard reply/guidance clients that preserve
   `request_id` across lost responses and retries. Rehearse on desktop/mobile.
3. Use the protected Mermaid-only release and three-field config sync in the
   [technical runbook](mermaid_tracy_real_tenant_runbook.md); keep rollback
   material outside Git. Do not trigger a shared multi-tenant deployment as a
   shortcut for this pilot.
4. Verify the live Reservations route, authenticated Mermaid profile, paused
   ingestion, one controlled reply, takeover/hand-back, and duplicate/recovery
   behavior before claiming the production 404 or final demo is resolved.

The prior dedicated-number canary is documented in the technical runbook. It
does not verify this new revision. This foundation work itself does not deploy,
enable AI, change provider resources, or prove the current production UI.

## Old-revision rehearsal remediation gate

The separate Reservations rehearsal was stopped after external model calls on
the old `00c70aa` revision used a staged configuration that retained nonempty
`password`, `access_key`, and `whatsapp_connect_token` fields. The old context
builder included those fields. Sender calls were mocked; no WhatsApp messages
were sent in that rehearsal. Treat the three fields as potentially disclosed
until protected remediation establishes rotation or expired/non-auth status.

Before activation, rebuild the staging configuration from the corrected
revision and a current protected snapshot, address the affected tenant
credentials, and verify the old credentials no longer authorize access. The
Nr3 dashboard-password reset path updates the password and environment but
does not itself rotate the runtime's persisted `data/session_token`. Also,
`access_key` participates in Nr3 tenant-generation fingerprints: keep lifecycle
jobs quiescent and re-read generation after a protected rotation. Do not rotate
shared provider/infrastructure credentials as a substitute for this scoped
remediation. Record field names and pass/fail only; never record their values.

Crash recovery can take up to 22 minutes. Zernio idempotency bridges retries
across the provider/local-commit gap; ambiguous direct-Meta sends require
operator attention. No strict exactly-once claim is made across those systems.
