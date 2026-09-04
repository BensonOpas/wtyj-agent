# BRIEF — Keep Mermaid review acknowledgements and safe follow-ups deliverable
**Status:** Implemented | **Files:** agents/social/mermaid_reservation_workflow.py; agents/social/mermaid_understanding.py; shared/state_registry.py; tests/social/test_mermaid_soft_review.py; tests/agents/test_mermaid_multilingual_intake.py | **Depends on:** live short-checkout release 521379d | **Blocks:** reliable human-review replies

## Context
An accessibility question selected the Mermaid model's `request_human` action.
The workflow immediately set `ai_muted=True`, then created a notification with
`mode=soft` and returned its acknowledgement. The buffered WhatsApp final-send
guard correctly suppressed the now-muted conversation, dropping that same
acknowledgement. Subsequent messages were stored but skipped model/send work.

Read-only production evidence identified one affected conversation: its mute
timestamp was 2026-09-04T01:42:04.238161Z, immediately followed by the pending
soft `Mermaid reservation: human review` notification at 01:42:04.239769Z. Both
the question and follow-up had `human_takeover_ai_muted` status without an
outbound attempt. Its existing booked reservation was separately frozen for
human review. This was a conversation mute, not a tenant-wide pause or outage.

## Why This Approach
Automatic review creates a soft operator work item while TRACY acknowledges the
request and continues answering supported general questions. The existing
reservation freeze remains, and unresolved review prevents later approval from
creating a quote, checkout link or booking. The model receives the durable review
state, retains known guest details, and provides a natural acknowledgement;
existing multilingual fallback text no longer falsely claims TRACY is paused.

Reject weakening the final-send mute guard: that would let automation speak over
a real operator takeover. Also reject automatically clearing all mutes: only the
demonstrably incident-created mute may be repaired after deployment. Existing
reservations must never be automatically unfrozen.

A Mermaid-only opt-in to notification creation atomically preserves an existing
hard operator mode while updating its review information. Without this, a
takeover during model processing can be relabelled soft by notification dedup.
Other notification callers retain their existing behavior.

## Instructions
1. Remove automatic mute writes from the model and deterministic review paths
   in `agents/social/mermaid_reservation_workflow.py:374` and `:513`.
2. Derive pending review from the durable escalation mode and reservation freeze
   before model generation (`agents/social/mermaid_reservation_workflow.py:453`).
   Preserve safe conversational replies while blocking automated booking actions.
3. Clarify review semantics in `agents/social/mermaid_understanding.py:61`.
4. Add the opt-in hard-mode preservation transaction in
   `shared/state_registry.py:4690`. Keep webhook send guards unchanged.

## Tests
Five new tests exercise the actual WhatsApp buffer, Mermaid orchestrator,
SQLite state, stubbed model and stubbed provider. All five fail on the old code:
acknowledgements never send; follow-ups never reach the model; operator hard mode
is downgraded; and a concurrent tenant pause also gains an unintended mute.
After repair they verify acknowledgement plus safe follow-up delivery, no quote
from a later YES, existing reservation freeze, operator takeover during model
work, and a tenant pause immediately before send. The deterministic intake test
now expects a soft review without muting. No customer/provider messages are sent
during verification; notification dispatchers are disabled in isolated tests.
Additional cases cover later new-booking/cancel decisions, preserving saved
details, and an already-issued short checkout link plus signed callback staying
blocked after review freezes the reservation. The combined Mermaid and operator
control suites passed 301 tests locally. Final review added three contradictory
model-decision cases (`requires_human` with confirm/new-booking/cancel), all of
which retain the review acknowledgement instead of claiming an action Python
refused. The final soft-review suite has eleven passing cases.

## Success Condition
A review question receives its acknowledgement and safe follow-ups remain
answerable, while operator takeover, tenant pause and frozen-booking safeguards
continue to block their respective actions.

## Rollback
Revert this release's source changes and redeploy the prior image. Restore any
incident-specific state correction only from its audited backup if explicitly
needed; never replay customer messages or unfreeze bookings as a rollback side
effect.

## Incident State Repair
After an audited database backup and successful deployment, compare-and-set only
the demonstrated affected conversation: require its exact mute timestamp,
matching still-pending soft review notification, and absence of an unresolved
hard takeover inside one transaction. Clear `ai_muted` and `human_takeover_at`;
preserve the open review, booked reservation freeze, history and inbound event
rows. A changed timestamp or mode aborts the repair. Do not implicitly replay
the two suppressed messages.
