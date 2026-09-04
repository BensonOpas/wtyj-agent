# BRIEF — Mermaid model failure recovery (issue #342 A1)

**Status:** Implemented; integration and release verification pending.
**Base:** `5922be02aacdaeb5ae8223807de59207339404ea`.
**Scope:** Mermaid reservation contract, existing buffered Zernio WhatsApp worker,
durable retry state, and isolated deterministic tests. No live state changes,
customer sends, paid model calls, monitor changes, or deployment in this work.

## Evidence and authorization

The preserved 4 September baseline found six-language field retention and
new-message recovery, but only English failure copy, no regeneration of a failed
event, and no durable human-review task when the model was unavailable. Failed
fallback prose was cached as a completed reply. The buffered worker also marked
its delivered fallback `replied`, preventing recovery.

Issue #342 expressly authorizes a narrow exception to the general one-call and
no-classifier rules: bounded retries after model failure and whole-message,
explicit requests for a person recognized without a model. Ordinary conversation
still uses the model. Matching does not infer intent from arbitrary substrings,
classify general language, extract booking fields, or mutate business decisions.
Failure and offline-human copy is provided for EN/NL/DE/ES/PAP/PT. Papiamentu is a
draft consistency review, **not native Curaçao certification**.

## Implementation

`mermaid_model_recovery.py` records per-conversation/message generation attempts
and the generated structured result in SQLite. An active attempt has a lease;
attempt fencing prevents a late worker from replacing the newer generation.
Malformed output is a failed generation. Failed turns do not update intake,
seen-message flags, or the successful reply cache. A formerly cached fallback
without a corresponding completed model decision is ignored on explicit replay.

The existing durable worker retries transient failures at 5 then 10 seconds,
with a maximum of three model attempts per event. SDK retries are disabled only
for Mermaid, and its SDK request timeout is 30 seconds. A shared Mermaid circuit
limits probing during an outage. Billing, exhausted quota, invalid credentials,
and rejected requests are terminal for automatic event recovery and block new
provider attempts for 15 minutes; an explicit new message can probe after that
cooldown. Changed credentials clear that circuit. No credit purchase or account
reset is attempted. Error records retain a small cause category, not raw provider
error bodies or credentials.

One pending technical dashboard work item consolidates an ongoing model outage.
It is resolved after successful generation if no newer failure remains. This
path does not invoke per-customer HO/email/WhatsApp dispatchers. A human request
creates the existing deduplicated soft escalation through the existing workflow,
independently of the provider circuit. It does not mute the conversation or
unfreeze an existing reservation. Operator hard mode, tenant pause, account
ownership and all final-send guards stay authoritative.

The buffered worker distinguishes the outage notice from the recovered answer.
The notice uses a stable `mermaid-model-status:<batch>` provider idempotency key,
is stored once, and is sent at most once after confirmed delivery. Recovery uses
the original answer/quote key. The notice leaves inbound state `recovering` with
a future lease, or `processing_failed` for a non-retryable/exhausted event. It is
never recorded as successful model completion. A narrow recovery-query exclusion
prevents this typed notice from superseding its own failed message. Normal newer
assistant/operator replies still supersede stale recovery, avoiding old answers
after the conversation has moved on. No old terminal production event is scanned
or replayed automatically by this change.

Reply metadata adds `language` and `understanding_source` (`model`,
`explicit_human_request`, or `model_failure`). Failed replies additionally carry
`mermaid_generation_failure` for the worker; these are internal fields, not guest
prose. The marina integration also calls the Mermaid-only `user_prompt` supplied
by the companion A2 change, preserving credential redaction and avoiding legacy
business-context injection. Integrate that companion function before release.

## Verification

New regressions first reproduced the legacy English cached fallback through the
actual buffered worker. The final suite uses real isolated SQLite and workflow/
worker code, stubbed model and customer transport, and disabled staff dispatchers.
It covers all six localized failures and automatic recoveries; six offline human
requests with one staff task; bounds/backoff; quota/auth circuit and continued
new messages; concurrent duplicate/expired attempts; malformed output; a failed
notice delivery; recovery that creates one quote/reservation/provider action;
newer-message supersession; SDK retry configuration; and genuine mute/pause.
All 33 new cases and the existing soft-review, multilingual-intake, booking,
recovery and runtime-control suites pass: **219 tests** in 9.97 seconds locally.
The baseline reports remain unchanged.

Run from repository root using the production Python dependencies:

```sh
python -m pytest wtyj/tests/social/test_mermaid_model_recovery.py wtyj/tests/social/test_mermaid_soft_review.py wtyj/tests/agents/test_mermaid_multilingual_intake.py wtyj/tests/agents/test_mermaid_booking_ux.py wtyj/tests/social/test_message_reliability_p0.py wtyj/tests/test_mermaid_runtime_hardening.py -q
```

The root task owns combined-image tests, paid multilingual acceptance, language
review, deployment and rollback verification. No provider-level delivery claim
is made from the stubbed harness.

### Review correction: offline escalation summaries

Root review identified that the shared escalation creator invokes a separate
summary model. Disabling that dispatcher in the initial harness hid the extra
dependency. A Mermaid explicit-human-only `suppress_model_summary` opt-in now
skips the summary model and dispatches an operator alert only when the unresolved
work item is first created. Its insert/update decision is serialized. The
default remains unchanged for normal model-backed soft reviews and other
tenants. Six new buffered tests enable both dispatchers, assert zero summary or
understanding calls, and assert one alert across repeated requests; another
test preserves ordinary summary and alert dispatch. These tests reproduced the
hidden call before the correction. No real operator notification was sent.
The legacy deterministic Mermaid intake human-request route uses the same
opt-in; its regression likewise asserts no model summary and one alert.

### Integration correction: new structured selectors

The A2/A3/A5/A6 selectors are validated before a result can be cached as
generated. Present calendar/status/security selectors must be strings in their
schema enums, and a present guest-question excerpt must be a string. Legacy
results that omit the optional additions remain accepted. Sixteen new buffered
regressions first reproduced malformed values being cached as generated; after
the correction they are `invalid_response` failures with no business mutation,
and the same durable event regenerates and completes successfully.

## Rollback

Revert these source changes with the coordinated release. The two new Mermaid
tables are additive and may remain inert. Do not restore the whole database,
automatically replay terminal messages, clear genuine mutes, resolve guest
reviews, or unfreeze reservations as part of rollback.
