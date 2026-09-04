# BRIEF 342 — Authoritative Mermaid responses
**Status:** In progress | **Files:** Mermaid understanding, response policy, calendar, workflow and tenant config | **Depends on:** 5922be0 and issue #342 | **Blocks:** multilingual release acceptance

## Context
The unchanged 60-case baseline recorded 47 functional passes and 32 accepted
transcripts. Calendar prose contradicted valid stored dates, pickup journey
coverage was invented, and queued reviews were described as active staff work.
Legacy persona prose also contradicted the structured demo contract.

## Why This Approach
The model still understands language in one structured turn. New structured
calendar/status/security fields route to deterministic calendar and recorded
state. Critical wording and Curaçao weekday names come from tenant copy.
Rejected: repeatedly adding prose warnings while leaving conflicting legacy
instructions in the prompt. Rejected: matching free-form model replies or guest
keywords to infer these intents. The explicit outage human-request exception
is separately documented by the recovery workstream.

## Instructions
1. Remove legacy operational instructions from the Mermaid prompt; retain
   approved FAQ facts with current catalog authority.
2. Calculate calendar candidates in America/Curacao from operating weekdays.
   Never let generated weekday/date combinations become authoritative.
3. Derive payment, review and delivery copy from recorded state. A queued
   review is not proof that a person started work; no email delivery is assumed.
4. Record blocked override attempts without guest text or secrets. Escalate two
   distinct attempts within 24 hours or one actionable security report. This is
   an intentional change from the baseline's escalate-every-attempt assertion.
5. Owner clarification on 4 September 2026 confirms pickup and return are
   included in the configured per-vehicle rate ($75 car / $125 van).
   Preserve existing prices, vehicle capacities, timing and reservation money.
6. Prepare critical Papiamentu copy and a native-review packet; keep native
   acceptance pending until an actual qualified reviewer approves it.

## Tests
Calendar boundaries, closed days and Sunday in all six languages; truthful
queued/active/unpaid/paid/delivery states; isolated/repeated/actionable attacks,
duplicate safety and immutable reservation fields; published config authority.
Then the bounded 60-case suite and fresh paraphrases in a new evidence folder.

## Success Condition
Critical facts match the catalog and recorded state, with unresolved business
and native-language decisions reported as holds rather than passes.

## Rollback
Restore the preceding Mermaid image and backed-up policy/config files, leaving
customer, reservation, review and security audit records intact.
