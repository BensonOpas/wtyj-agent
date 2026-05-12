# EXPLANATION 263 — Operator-approved learnings: extend Brief 215 system with suggest/edit/dismiss + audit fields + Calvin's endpoint naming

## In one sentence
Operators can now suggest, edit, approve, or dismiss a "learning" that the Agent picks up from an escalation, and the system records who approved each learning and when — without changing how the Agent already learns automatically from operator replies.

## What's changing and why

Calvin (frontend lead) asked for a workflow where the Agent does not blindly absorb every operator reply as a permanent lesson. Instead, an operator should be able to suggest a learning, edit it, and then either approve it or dismiss it. The Agent only uses learnings that an operator has explicitly approved, and dismissed learnings must never reach the Agent's prompt.

When we audited the codebase before building, we found that an earlier brief (Brief 215) had already shipped most of the foundation: a learnings table, endpoints to list and approve them, and the wiring that injects approved learnings into the Agent's prompt. Four pieces were missing: a way to edit a suggested learning before approving it, a way to "dismiss" a learning without hard-deleting the row, audit fields that record who approved or dismissed it and when, and a parallel set of endpoint paths that use Calvin's preferred vocabulary (pending / approved / dismissed). Brief 263 closes those four gaps. It does not rebuild anything, and it does not change the existing auto-learn behavior — that is a separate product decision Calvin can make later once the operator-approval flow is verified end-to-end.

## Step by step — what the code does now

ADD AUDIT COLUMNS TO THE LEARNINGS TABLE

When the system starts up and prepares the database, it now adds three new columns to the learnings table if they aren't already there: a timestamp for when a learning was approved, a timestamp for when a learning was dismissed, and the name of the operator who approved it. The migration is safe to run repeatedly — if the columns already exist, nothing happens.

RECORD WHO APPROVED OR DISMISSED A LEARNING, AND WHEN

The existing helper that flips a learning's status now also stamps an audit trail. When a learning becomes "approved," the system records the current timestamp and the operator's name (or leaves the name blank if the call didn't provide one). When a learning is "dismissed," the system records a dismissal timestamp. When a learning becomes "approved," the system also flips the internal "Agent may use this automatically" flag to on — which is the exact flag the Agent's prompt path checks before pulling the learning in.

CREATE A NEW PENDING LEARNING

A new helper lets an operator create a learning in "pending" state. The text is recorded, but the "Agent may use this" flag stays off, so the Agent will not see it in its prompt until someone approves it.

EDIT A PENDING LEARNING'S TEXT

A new helper lets an operator change the wording of a pending learning before approving it. If the learning has already been approved or dismissed, the helper refuses the edit and returns a failure — once a learning has been decided on, its text is frozen. To change an approved learning, the operator has to dismiss it and start over.

TRANSLATE BETWEEN INTERNAL AND EXTERNAL STATUS NAMES

The internal database uses the words "suggested," "approved," "saved," and "deleted." Calvin's frontend uses "pending," "approved," and "dismissed." Two small translation helpers map between the two vocabularies in both directions. The internal "saved" status (a Brief 215 distinction) maps to "approved" externally — the frontend doesn't need to know the difference, and the Agent's prompt path treats them the same.

RESHAPE A LEARNING ROW FOR THE FRONTEND

A new helper takes a row from the database and reshapes it into the JSON shape Calvin's frontend expects: an id (as a string), the escalation id it came from, the current external status, the suggested text, the approved text (only populated once the learning is approved), the created/updated timestamps, the new approved-at and dismissed-at timestamps, and the operator's name (the approver if present, otherwise whoever created it).

LIST LEARNINGS BY EXTERNAL STATUS

A new endpoint accepts a status filter using Calvin's vocabulary ("pending," "approved," or "dismissed"), translates it to the internal name, fetches the matching rows, and returns them in the new shape.

SUGGEST A LEARNING TIED TO AN ESCALATION

A new endpoint lets an operator submit a suggested learning attached to an escalation id. The endpoint works in two modes. If the escalation id is a real number and matches a row in the pending notifications table, the system uses that row's customer id and channel as the conversation context. If the id doesn't match a row, the system treats the path id as a raw conversation key and uses the channel provided in the request body — and if no channel is provided in that fallback case, the request fails with a clear error. Either way, the new learning is created in "pending" state, then the system re-fetches it and returns it in the frontend shape.

EDIT A PENDING LEARNING'S TEXT VIA HTTP

A new endpoint accepts a new text body and updates the learning's text. If the learning is no longer in "pending" state, the endpoint returns a "conflict" response with a clear message — the frontend can use that signal to show the operator that the learning is already locked in.

APPROVE A PENDING LEARNING VIA HTTP

A new endpoint marks a learning as approved. The operator name from the request body is recorded as the approver. The approval timestamp is stamped automatically. The "Agent may use this" flag is flipped on, so on the next inbound message, the Agent's prompt-builder will include this learning.

DISMISS A PENDING LEARNING VIA HTTP

A new endpoint soft-rejects a learning: the row stays in the database for audit purposes, but its status is set to "deleted" and the dismissal timestamp is stamped. This is distinct from the older hard-delete endpoint, which permanently removes the row. The frontend can choose which one to call depending on whether the operator wants to "dismiss" (recoverable, auditable) or "permanently delete" (gone for good).

THE LOAD-BEARING PROMPT-PATH CHECK

The function that feeds approved learnings into the Agent's prompt was not changed. It already filters for learnings whose status is approved or saved AND whose "Agent may use this" flag is on. That filter correctly excludes both pending learnings (status "suggested," flag off) and dismissed learnings (status "deleted"). This is the security guarantee Calvin asked for: a dismissed learning cannot reach the Agent, ever, because the prompt-path query won't return it.

LEGACY ENDPOINTS STILL WORK

The original Brief 215 endpoints at the older path names continue to work exactly as before. They return the older response shape (with field names like "humanAnswer" and "conversationId"). One small side-effect: the legacy approve endpoint now also stamps the approval timestamp, but with an empty operator name (because the legacy endpoint has no body to extract a name from). No caller that reads the older shape will break.

## Edge cases

- If an operator suggests a learning against an escalation id that is not a number and doesn't provide a channel in the body, the request fails with a clear "channel required" error. This is intentional — the system needs to know which channel the conversation is on to file the learning correctly.
- If an operator tries to edit a learning that has already been approved or dismissed, the system refuses with a "conflict" response. The text on approved learnings is frozen by design. To change it, the operator must dismiss the existing learning and create a new one.
- The legacy approve endpoint stamps the new approval timestamp with an empty operator name. This is documented as intentional. Every approval gets an audit timestamp regardless of which endpoint triggered it; the legacy path simply has no operator name to record because it accepts no body.
- If the schema migration is run on a database that already has the new columns, the system silently does nothing — the migration is safe to re-run on every boot.
- Dismissed rows stay in the table forever (until someone hard-deletes them via the older endpoint). This is the intended audit behavior, but it does mean the table grows over time. No cleanup job exists yet.
- The "auto-learn from every operator reply" default behavior is unchanged. The existing system still creates new learnings with status "approved" when an operator replies through the normal escalation flow. Calvin's spec implies this default should eventually flip to "suggested," but that is a separate product decision and is deliberately deferred. Until that flip happens, the new operator-approval workflow runs in parallel with the older auto-approve behavior — both produce valid learnings; only the path differs.
- The internal "saved" status (a Brief 215 distinction) is preserved. Externally it appears as "approved." The frontend doesn't see the distinction, and the Agent's prompt path treats both as approved.

## What did NOT change

The Agent's prompt-building code was not touched. The Agent still pulls in approved learnings exactly the same way it did before — same query, same filter, same wiring. The auto-learn default (where an operator's reply through the existing escalation flow becomes an approved learning automatically) was deliberately preserved; flipping that default is a separate product call Calvin can make once he has confirmed the new approval flow works end-to-end. The older `/learning/*` endpoints were not modified at the API surface — any existing dashboard caller that reads the older response shape will continue to work without change. No customer-facing behavior in WhatsApp, DMs, or email was touched. The booking flow, Marina's prompt, and customer data handling are all untouched. This brief is purely additive backend plumbing plus three new database columns.
