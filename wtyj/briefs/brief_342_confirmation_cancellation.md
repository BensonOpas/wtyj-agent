# BRIEF 342 A3 — One guest confirmation and atomic unpaid cancellation
**Status:** Implemented locally; pending combined audit review and release | **Files:** agents/social/mermaid_reservation_workflow.py; agents/social/mermaid_reservation_store.py; agents/social/mermaid_demo_payment.py; tests/agents/test_mermaid_confirmation_cancellation.py | **Depends on:** 5922be0 and the companion issue 342 structured-contract change

## Context
The preserved 60-conversation baseline exposed two separate booking failures.
BASE025 supplied every guest fact, but the model described its own next question
as `has_open_question=true`. Python consequently withheld the canonical summary
until the guest had already confirmed once. BASE049–054 requested cancellation
of unpaid quotes; a generic model review flag sent all six languages to staff
instead of cancelling. The old cancellation handler also returned “cancelled”
when payment won after the model's initial reservation snapshot.

The baseline files under `output/baseline-60-2026-09-04/` remain unchanged. This
brief covers A3 only; the root issue implementation owns prompt/schema changes,
critical state language, calendar/security policy, model recovery and full rerun.

## Why This Approach
The companion contract supplies `guest_question_excerpt`, a required string
containing an exact excerpt from the latest guest message, or an empty string.
The workflow checks that provenance instead of interpreting the model's reply
or classifying languages in Python. Legacy contracts retain their conservative
question flag behavior. Complete guest facts receive the canonical summary;
one unchanged affirmative action then advances once. A real guest question
keeps its answer and prevents confirmation on that turn.

Cancellation is authoritative only after SQLite commits. Its immediate write
transaction checks reservation state, actual payment rows/payment reference,
the existing reservation freeze, and operator mute/unresolved soft or hard
review in the same tenant database, then changes state, appends one audit event
and deletes all checkout tokens together. The payment writer uses the same
SQLite transaction ordering: only one action can win. A typed paid/frozen
outcome makes the workflow return review and persist the review phase instead
of claiming cancellation. Existing unpaid reservations may cancel despite the
model's generic review flag, but explicit human requests and existing review
remain protected. No-reservation contradictory review decisions remain review.

Token creation also takes the write lock before its state read, preventing a
mint already in progress from inserting a token after cancellation. Previously
issued signed checkout GET/POST requests reject cancelled state; a cancellation
winning after the callback's first read also returns unavailable. Closing a paid
checkout reports the already-paid state without implying a refund or cancellation.

The intake phase remains `cancellation_requested`, with an empty success reply
and no processed-message marker, until the handler commits cancellation or its
required review. A database/revocation error therefore leaves the same provider
event retryable. Only the authoritative outcome sets the final phase, processed
marker and cached reply. This closes the previous failure window where an
aborted cancellation was already marked cancelled and duplicate on retry.

Rejected: parsing model prose or adding multilingual confirmation/cancellation
keyword lists; cancelling based only on the model snapshot; deleting tokens in
a later transaction; revoking a paid booking; changing final-send pause/mute
guards or clearing any human review/freeze. The workflow rechecks conversation
review and mute immediately before cancellation; the store repeats these checks
inside its write transaction so an operator takeover cannot slip between the
check and state change. Missing state tables in legacy standalone store usage
are skipped; no migration or additional state table is introduced.

## Instructions
1. Integrate this commit with the parent-owned `guest_question_excerpt` schema
   and model instruction. Python accepts only an exact guest-text substring.
2. Keep cancellation changes in the Mermaid reservation store and checkout.
   No other tenant, real payment flow, operator mute or control-panel setting changes.
3. Preserve terminal cancelled state on later YES messages; an explicit new
   booking remains the only existing route to fresh intake.
4. Keep the six existing localized unpaid-cancellation messages. The parent
   owns any stronger shared state/review wording introduced by A4/A5.

## Tests
The initial fourteen focused regressions failed before implementation, including
the actual BASE025 pattern, six unpaid locales, stale signed checkout, a paid
winner after model generation, and transactional token deletion. The final
focused file adds both genuine SQLite payment/cancel winner orders, a held token
mint overlapping cancellation, injected token-delete failure and rollback,
duplicate confirmation/cancellation, guest-question evidence, stale YES after
cancellation, callback/cancellation overlap, paid checkout wording, and existing
soft/hard/frozen review protection. All tests use isolated SQLite/files, model
stubs and disabled notification dispatchers; no paid model or provider calls.

The focused file plus reservation-store, demo-payment, checkout-concurrency,
live-release and actual soft-review webhook suites pass: 78 tests, including
five added operator-write ordering and handler/store-gap regressions. Companion
multilingual intake, demo end-to-end, contact, pickup, handoff-durability and
dashboard reservation tests pass: 106 tests. Two additional workflow-level
fault-injection regressions cover model and deterministic cancellation retries
after token revocation aborts, and the paid-race test checks the cached review
payload. Combined parent tests
and the complete real-model audit remain release gates owned by the root task.

## Success Condition
One canonical summary plus one unambiguous YES produces one reservation/quote.
Guest questions still receive answers without implicit booking. Unpaid
cancellation produces cancelled state and no usable checkout token; a payment
winner stays paid/booked and receives review. Existing operator control remains.

## Rollback
Revert this commit together with the companion contract change and deploy the
previous reviewed image if required. Do not restore cancelled reservations or
revoked links, replay customer messages, reverse payments, clear review or
unmute conversations as part of rollback. No schema migration is introduced.
