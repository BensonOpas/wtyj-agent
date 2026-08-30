# Brief 318 — Rental dashboard operations contract

## Context

Premium Rental Dashboard V2 currently derives lifecycle stage, responsible party, and operator action in the browser by matching English `next_action` text. That is unsafe: copy changes can change behavior, waiting states can appear as staff work, and the UI can expose actions that the server has not authorized.

Ali's approved workflow must remain unchanged:

```text
Pre-quote conversation
→ vehicle discovery/selection
→ rental details
→ customer confirms the summary
→ official quote is prepared and delivered
→ customer reserves
→ automatic availability approval (Ali demo policy)
→ WhatsApp document collection
→ automatic pre-contract
→ client signs
→ staff reviews the signed file
→ payment
→ dossier
→ final approval
→ confirmation
```

Future rental tenants may replace Ali's automatic availability with a manual/API/calendar gate and may require document review before contract generation. The dashboard therefore needs one stable, tenant-neutral operations contract sourced from the actual workflow state, not Ali-specific frontend branches.

## Why

- The server already owns valid transitions and responsibility.
- The browser must present workflow state, never infer workflow policy from prose.
- A reusable contract lets every rental tenant use the same dashboard while keeping tenant-specific gates in configuration and server workflow adapters.
- The Today queue must contain staff-owned work only; client/system/agent waiting states belong in counts and filters, not the action queue.

## Implementation

### 1. Add the operations projection to Quote Leads

Update `wtyj/agents/social/ali_quote_workflow.py` so every quote-lead row contains an additive `operations` object with contract version 1:

- `lifecycle`: `pre_quote`, `post_quote`, `confirmed`, or `closed`
- `stage`: stable machine-readable stage
- `responsibleParty`: `staff`, `client`, `system`, or `agent`
- `operatorAction`: stable enum, or `none`
- `actionLabel`: human-readable server copy
- `actionTarget`: `conversation`, `customer`, `documents`, `agreement_payment`, `dossier`, or `none`
- `actionPriority`: `critical`, `high`, `normal`, or `none`
- `clientTimeRemainingSeconds`: V2 client clock, otherwise null
- `exception`: null or a structured technical/escalation reason
- `progress`: current index, total, completed stages, and ordered stage keys
- `capabilities`: workflow-derived booleans, including whether dossier printing is contextually available

For post-quote reservations, use the authoritative Ali Reservation V2 case when present. Load active dashboard cases in one tenant-scoped batch, then use each case's `state`, `responsibleParty`, `nextAction`, clock, and revision. Never derive a post-quote action from English `next_action` copy.

For pre-quote leads, derive the contract only from structured fields already owned by the server: projected status, missing fields, unread count, quote delivery state, escalation presence, and deterministic phase flags.

Keep existing Quote Leads fields for backward compatibility.

### 2. Preserve tenant workflow policy

- Ali automatic availability must project directly to document collection; do not show an availability approval action when the workflow has already skipped that gate.
- Ali automatic pre-contract generation must remain a system-owned waiting step.
- Manual/API/calendar availability tenants can project `availability_pending` as a staff action without frontend changes.
- Document-review-before-contract tenants can project `document_review_pending` as a staff action without frontend changes.
- No state transitions are added or changed in this brief.

### 3. Tests

Extend `wtyj/tests/agents/test_ali_quote_leads.py` with behavioral tests proving:

- an incomplete pre-quote lead is agent/client work, not staff action;
- an active escalation is staff-owned `answer_customer` work;
- quote processing is system-owned and has no operator action;
- a failed quote delivery is staff-owned technical recovery;
- Ali V2 `documents_collecting` is client-owned and does not expose availability approval;
- V2 `prepayment_approval_pending`, `customer_reports_paid`, `final_approval_pending`, and `technical_attention_required` map to the correct stable operator actions;
- confirmed reservations map to Ready for pickup without a fake staff action;
- the API returns the additive contract without changing existing counts or legacy fields.

## Success criteria

- The frontend can render all Rental Dashboard V2 queues and actions without inspecting English `next_action` text.
- Ali's approved pre-quote and post-quote behavior is unchanged.
- The contract is tenant-neutral and can be returned by another rental workflow implementation without changing the dashboard.
- Existing Quote Leads consumers remain compatible.
- Focused tests and the full relevant regression suite pass.

## Rollback

Revert the additive `operations` projection and its tests. Existing Quote Leads fields remain untouched, so rollback does not require a data migration.
