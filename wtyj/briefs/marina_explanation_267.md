# EXPLANATION 267 — Wire Brief 266's learning helper into `/messages/conversations/{id}/email/reply` (Brief 225 Inbox-side email reply endpoint)

## In one sentence

When an operator replies to a customer from the Email Inbox tab of the dashboard, the system now creates an auto-learning row (pending or approved depending on the toggle) — which it previously did not, regardless of how the toggle was set.

## What's changing and why

The previous fix (Brief 266) was supposed to make every dashboard reply create a learning row, with the toggle deciding whether that row lands as "pending review" or "auto-approved." Calvin's live retest of that fix failed. Production investigation turned up two separate problems sitting on top of each other.

First, the operator's reply from the Email Inbox tab of the dashboard goes through a different reply endpoint than the reply from the Escalations tab. Brief 266 fixed the Escalations-tab path because that path already had old learning-creation code to refactor. The Inbox-tab path (the one customers actually saw used) had never created a learning row in any form, so Brief 266's search for places to update missed it entirely. The result: an operator could toggle the setting all day long, reply via the Inbox tab, and never see anything happen in the learnings queue.

Second, the server-side toggle for unboks was sitting at "false" even though Calvin had flipped the toggle in the Settings screen. The Settings screen on the operator dashboard is not yet wired to actually save the value to the backend — it only keeps it in the browser's local storage. The frontend wire-up is a separate task on Calvin's plate. So even after this code change ships, the toggle has to be flipped by hand on the server until the Settings UI is finished.

Brief 267 adds one missing call to the Inbox-tab email reply path, so it now behaves exactly like the Escalations-tab email reply path: every operator reply records a learning row, and the toggle decides whether that row needs human review first or is auto-approved.

## Step by step — what the code does now

STEP: Operator sends a reply from the Email Inbox tab

When the operator types a reply in the dashboard's Email Inbox conversation view and hits send, the dashboard sends that reply text to the server's Inbox-side email reply endpoint. The server sends the email out through the customer's mail thread and records the operator's message in the conversation history. This part is unchanged.

STEP: Server now records a learning row from that reply

Immediately after the email is sent and the message is appended to the thread, the server now calls the same shared learning helper that the Escalations-tab reply path already uses. It passes along the customer's email address as the conversation identifier, the reply text as the answer, and a tag identifying that this came from the messages-email-reply endpoint. Because the Inbox tab is not escalation-scoped, there is no escalation identifier to attach — that field is left empty.

STEP: The helper checks the toggle and routes the row

The shared helper reads the `agent_learning_create_pending_from_replies` setting from the tenant's settings store. If the setting is "true," it writes a row with status "suggested" — meaning it shows up in the pending-review queue waiting for a human to approve, edit, or dismiss. If the setting is "false" (the legacy default), it writes a row with status "approved" — meaning the agent can use it immediately as an example. The Inbox tab now behaves the same way the Escalations tab does on this point.

STEP: Operator-side toggle fix (run by hand, not in the code)

Because the Settings screen on the dashboard does not yet save the toggle to the server, an operator command is documented in the brief that flips the unboks setting to "true" directly on the live container. After that command runs, the toggle is "true" server-side and Calvin's retest works regardless of where he clicked in the dashboard UI. Once the Settings screen gets wired up to the server later, this manual step goes away.

STEP: New regression test

One new test runs the full flow end-to-end with the toggle on. It seeds an email conversation, stubs out the outbound mail send so no real email goes out, posts a reply to the Inbox-side endpoint, and then checks the learnings table to confirm a "suggested" row appeared with the operator's exact reply text. This test guards against the same gap reopening if the endpoint gets refactored later.

## Edge cases

- If the toggle is off when the operator replies via the Inbox tab, the row is written as "approved" — same as the existing Escalations-tab behavior, no review step. This is the legacy default and is intentional.
- If the operator replies to an email conversation that was never escalated (i.e., the agent handled it fine and the operator is just chiming in), the system still creates a learning row from that reply. The brief accepts this as a trade-off: the toggle's spirit is "operator replies are signal," not "only escalation replies are signal." If Calvin later wants to restrict learning creation to escalated conversations only, a one-line check in the helper can do that.
- WhatsApp Inbox replies are not affected — there is no separate Inbox-side WhatsApp reply endpoint. All WhatsApp dashboard replies already flow through the Escalations endpoint, which Brief 266 covered.
- If the toggle is set to "true" on the dashboard's Settings screen today, the server doesn't see it, because the Settings screen only writes to the browser's local storage. Until the Settings UI gets wired to the backend, the toggle has to be flipped on the server by hand. The brief documents the exact command.
- The Inbox-side endpoint has no escalation identifier to attach to the learning row. The row is created without one. This is acceptable — the row still has the conversation identifier, channel, answer text, and source tag.
- If the email send itself fails, the learning row is not created (the new call sits after the send-and-append step). That matches the Escalations-tab path's order of operations.

## What did NOT change

Marina's prompt, the booking flow, the customer-facing reply text, the customer's mail thread storage, the Escalations-tab reply path, the Brief 266 helper itself, the Brief 264 settings endpoints, the WhatsApp dashboard reply path, and the prompt-side filter that hides "suggested" rows from the agent's context — none of these were touched. This brief is one new call on one endpoint plus one new test. The fallback reply strings noted in the project's known-issues list (Marina's name) were not modified.

## Architectural lesson surfaced by this miss

Brief 266 found its work-list by grepping the backend for an existing helper call (`save_escalation_learning`) and refactoring every site that already used it. That is a lossy way to find "all the places operator replies happen" — it only finds places that already learned from replies. The Inbox-tab reply endpoint had no learning code in the first place, so it was invisible to the grep. The more reliable starting point is the frontend: trace every reply button in the operator dashboard to the backend endpoint it actually calls, and confirm each of those endpoints calls the learning helper. The backend-grep approach should be a check, not the primary discovery method, when fanning out a behavior change across multiple reply paths.
