# Tracy wheelchair assistance
**Status:** In progress | **Issue:** #342 | **Base:** live `f30d973`

## Context
An initial booking enquiry supplied a date, a five-person party and a wheelchair
need. The model produced a useful welcome and reply, but the final workflow
replaced it with the generic review-queue sentence. Runtime evidence shows a
successful generation and delivery, not an outage.

The owner has since confirmed the business rule: ordinary wheelchair use is
welcome and does not require approval. Tracy must continue intake and save a
private crew-assistance note. Explicit requests for a person, specific unknown
equipment or transfer guarantees, and genuine operator takeover keep their
existing review behavior.

## Implementation
1. Add a structured `wheelchair_note` understanding route and deterministic,
   professional copy in all six supported languages. Standard written Curaçao
   Papiamentu is required. Do not reuse raw model staff-status prose.
2. Persist the intake facts and a private, revisioned wheelchair-assistance item
   before saying that the note was saved. A repeat delivery is idempotent. A
   material correction or trip-date change reopens the item for acknowledgment.
3. Continue the normal booking flow and ask only the next missing detail. Do not
   create an escalation, freeze a reservation, mute Tracy or claim staff read
   the note. Preserve real human-request and hard-takeover behavior.
4. Link the item to the reservation when one is created. Keep the underlying
   accessibility note in private intake/reservation state and out of customer
   PDFs, signed public pages and routine logs.
5. Expose staff-only conversation, customer and reservation markers; add a
   central unread queue and an optimistic acknowledgment endpoint recording who
   acknowledged the current revision and when.
6. Persist a 24-hour stale reset before the Mermaid-specific early return so a
   new session cannot silently reload old intake state.

## Verification
- Exact synthetic five-person wheelchair enquiry in all six languages: one
  welcome, note-saved acknowledgment, preserved date/counts/ages and next
  missing question; no escalation or pause.
- Existing conversation, duplicate event, repeated wording, relationship/detail
  correction and trip-date correction.
- Note-persistence failure cannot produce a false saved claim.
- Quote/booking creation retains and links the private note; public documents do
  not contain it.
- Queue, marker and acknowledgment API/UI, including stale revision conflict,
  actor/time audit and re-open after a material correction.
- Explicit human request, unrelated review, hard operator takeover and tenant
  pause retain their existing behavior.

## Release
Build from the exact live `f30d973` lineage, run the affected and Mermaid suites
inside the candidate image, then recreate only Mermaid with compare-and-swap
guards and a private rollback backup. Do not replay or send a synthetic message
to any real guest. Preserve the paused Codex monitor and all unrelated tenants.
