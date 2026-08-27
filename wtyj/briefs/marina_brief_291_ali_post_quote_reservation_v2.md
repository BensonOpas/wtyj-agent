# Brief 291 — Ali post-quote reservation flow V2

**Status:** owner approved
**Priority:** P0
**Controlling issue:** BensonOpas/wtyj-agent#255
**Dashboard companion:** unboks-org/unboks-dashboard-api#120

## Outcome

Extend the existing Ali reservation and customer-dossier implementation. Do
not create another dossier system. The server owns this strict sequence:

```text
official quote
→ reserve
→ manual availability approval
→ direct WhatsApp document collection
→ staff document review
→ automatic pre-contract delivery
→ customer signature
→ automatic booking-deposit link delivery
→ customer reports payment
→ staff verifies payment
→ automatic confidential dossier
→ final staff approval
→ automatic Nick confirmation
```

The implementation is tenant-bound to `ali-car-rental`, feature flagged, and
must preserve the legacy path as a rollback target until the V2 canary passes.

## Customer actions

Every delivered official quote retains exactly three choices: `Reserve this
car`, `Change something`, and `Ask a question`. Signed controls remain the
primary path. A bounded deterministic typed-reservation classifier may accept
unambiguous equivalents such as “book it”, “reserve it”, and “I want this car”
in EN/NL/PAP/DE. Questions, corrections, rejection, uncertainty, and bare
agreement with some other statement never create a reservation.

## Availability

Create one `availability_pending` reservation. Expose a provider-neutral
availability protocol with `check`, `hold`, `confirm`, `release`, and
`suggestAlternatives`; ship a manual provider first. Approval guarantees the
category only. Declines require truthful alternatives or a decline reason and
never claim availability.

## Active-client clock and reminders

The hold contains 24 hours of active client-action time. The clock runs only
while the next responsible party is the client. It pauses for staff, system,
Nick, media processing, human takeover, and all review/generation stages.
Persist the accumulated seconds, current clock state, pause reason, client
timezone, milestones sent, next reminder, client/outbound activity, opt-out,
and cancellation evidence.

Ali defaults are reminders at 3, 12, and 21 active-client hours, quiet hours
20:30–08:30 client-local, and expiry at 24 active-client hours. Jobs are
idempotent, progress-aware, coalesced, separated by at least three active
hours, and expose Continue / Help / Release actions. No reminder may be sent
while waiting on staff/system or after completion, expiry, cancellation, or
opt-out. Production reminder sending remains disabled until the complete
negative-intent suite passes.

## Negative intent

Run a structural gate before ordinary AI handling:

- global stop/unsubscribe: cancel reminders, release hold, close, set Ali
  `do_not_contact`, send exactly one acknowledgement, and suppress proactive
  sends;
- reservation decline: cancel only the current reservation;
- vehicle rejection/change: preserve the reservation conversation and route
  back to the quote-change flow;
- ambiguous negative: freeze the clock/reminders and ask one clarification.

Support EN/NL/PAP/DE. Persist only a sanitized classification, source message
identifier/hash, timestamp, decision source/confidence, and resulting action.
Never log message text or PII.

## Direct WhatsApp documents

Public document-upload links are forbidden in V2. After availability approval
send one preparation message, ask Passport or ID card, and request one file at
a time. Retain Zernio attachment metadata from `message.received`, validate
tenant/account/conversation ownership, and immediately download through the
authenticated `/v1/whatsapp/media/{mediaId}` endpoint using
`attachments[].payload.id` and the receiving account ID.

Validate MIME, magic bytes, size, structural safety, and quarantine status;
store only in tenant-private storage. Never expose provider media URLs, send
identity files to an LLM/OCR service, or log bytes/content. Deduplicate webhook
event, provider message, attachment ID, and SHA-256. Store extra or unexpected
files as `unclassified` for seven days and ask for classification. On download
failure, never acknowledge receipt; request resend and alert staff. Provide a
read-only missed-event recovery job using Zernio message history.

Staff can approve, reject-with-required-reason, request replacement, and
reclassify. All required files must be approved before automatic contract
generation.

## Strict states

The V2 state set includes:

```text
availability_pending, availability_declined, documents_collecting,
document_review_pending, document_replacement_required, documents_approved,
contract_sent, contract_signed, payment_link_sent, customer_reports_paid,
payment_verified, dossier_ready, final_approval_pending, confirmed,
hold_expired, cancelled, client_opted_out, technical_attention_required
```

Every mutation validates tenant, quote/reservation binding, current state,
permitted transition, idempotency key, actor, optimistic revision, timestamp,
and any required reason. Every transition and provider delivery appends a safe
immutable event.

## Contract, payment, dossier, confirmation

After document approval automatically generate/send the existing secure
mobile pre-contract. After signature automatically send the configured
tenant payment link. The booking deposit defaults to 15% of rental charges and
supplements and excludes the refundable security deposit; use integer cents.
The tenant may configure percent/fixed mode and value. Payment verification is
manual. Verification before a customer payment report requires a mandatory,
audited staff override reason.

Payment verification automatically generates the confidential A4/Letter
dossier. Audit preview/download/print. Final staff approval automatically
generates and sends Nick’s confirmation. Identity bytes purge 90 days after
rental end while minimal audit metadata remains.

## Dashboard

Expose one server-derived primary action with current stage, responsible
party, active-client time remaining, hold/clock state, completed steps,
exceptions, timeline, reminders, opt-out/cancellation, documents/review,
contract, deposit calculation, payment evidence, dossier, and confirmation.
Authenticated document access is mandatory. Tenant settings cover checklist,
ID types, deposit rule, security deposit, payment, contract, hold/reminders,
quiet hours/locales, availability, SLA/notifications, retention, and final
copy.

## Verification and rollout

Tests must cover every forbidden transition, concurrency/idempotency, typed
reserve safety, all negative intent classes and languages, exactly-one opt-out
acknowledgement, clock pause/resume and 3/12/21 milestones, quiet-hour
coalescing, media-only/captioned/multiple/reordered/duplicate attachments,
authenticated download failures and recovery, tenant isolation, replacement
and reclassification, automatic contract/payment/dossier progression,
payment override reason, retention, mobile dashboard, and final confirmation.

Roll out in stages: attachment observation, allowlisted synthetic WhatsApp
test, Ali-only V2 flag, negative-intent gate proof, reminder send proof,
complete sandbox reservation, new-reservation activation, then monitoring.
Never send a real-customer test message.
