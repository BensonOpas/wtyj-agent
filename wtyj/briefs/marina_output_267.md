# OUTPUT 267 — Wire Brief 225 Inbox email reply path into the learning helper

## What was done

P0 follow-up after Calvin's live retest of Brief 266 FAILED with the toggle ON. Production investigation surfaced two distinct issues:

**Issue 1 — toggle isn't actually ON on the server**: `state_registry.get_setting("agent_learning_create_pending_from_replies")` on the live unboks container returns `'false'`. Calvin says he toggled ON in the dashboard UI but the server-side value is OFF. The likely cause: SR's Replit Settings UI for the Brief 264 toggle hasn't yet been wired to the backend PUT endpoint — the toggle state lives in browser localStorage only until SR ships the wiring (their #35 task). This is a frontend gap, not a Brief 266 bug.

**Issue 2 — Brief 266 missed a wire site**: `/messages/conversations/{conversation_id:path}/email/reply` (Brief 225 era, `dashboard/api.py:2074`) is the canonical Email Inbox reply endpoint. The Replit frontend's `replyToEmail()` hook routes here when the operator clicks Reply in the Email Inbox conversation detail. The endpoint NEVER created any learning row historically (verified by grep — no `save_escalation_learning` call). Brief 266 only refactored the 5 sites that ALREADY had `save_escalation_learning` calls in the `/escalations/{id}/reply` family. The Inbox-side email reply path was silently a no-op for auto-learn purposes regardless of toggle state.

Brief 267 fixes Issue 2 by adding one call to the existing Brief 266 helper right after `email_append_assistant_message` fires at the Brief 225 endpoint. Same toggle-aware semantics: ON → pending row (status='suggested', ai_may_use=0); OFF → approved row (legacy Brief 215 behavior preserved).

Brief 267 fixes Issue 1 operator-side (not code) via a direct `system_settings` write after deploy:
```bash
ssh root@108.61.192.52 'docker exec wtyj-unboks python3 -c "
from shared import state_registry
state_registry.set_setting(\"agent_learning_create_pending_from_replies\", \"true\")
print(\"OK:\", state_registry.get_setting(\"agent_learning_create_pending_from_replies\"))"'
```

This unblocks Calvin's retest immediately without waiting for SR's Replit wire-up.

## Files changed

- `wtyj/dashboard/api.py` — one call to `_create_learning_from_operator_reply` added to `reply_to_email_conversation` (line ~2120, immediately after `email_append_assistant_message`, before `return`).
- `wtyj/tests/social/test_215_escalation_learning.py` — 1 new test `test_brief_267_inbox_email_reply_creates_pending_when_toggle_on`.
- Source commit: `cd87a9c` ([HOTFIX] Brief 267).

## WhatsApp

No equivalent `/messages/conversations/{conversation_id}/whatsapp/reply` endpoint exists (grep verified). Dashboard WhatsApp replies route through `/escalations/{escalation_id}/reply` which Brief 266 already wired. WA path is correct; no Brief 267 work needed for WhatsApp.

## Tests / build result

1137 passing / 0 failures (1136 Brief 266 baseline + 1 new Brief 267 = 1137).

The new test mocks `smtp_send` at both `email_adapter` and `dashboard.api` module-namespace import sites, seeds an `email_thread_state.json` thread via monkeypatched path, sets the toggle ON, POSTs to the URL-encoded Brief 225 endpoint, and asserts a single `status='suggested'` row appears in `escalation_learnings` with the exact reply text.

## Production health

Source commit `cd87a9c` deployed via CI. All 4 containers expected healthy on the new image. The Brief 266 helper definition is unchanged; only the call-site count incremented from 5 to 6.

## Replit / frontend contract

**No frontend changes required for Brief 267 itself.** The Replit frontend already routes Email Inbox replies through the Brief 225 endpoint — they just weren't doing anything learning-wise until this brief.

**SR's Replit task #35 (Settings toggle UI → Brief 264 PUT endpoint) IS still required** for the toggle UX to work end-to-end without the operator-side `docker exec` workaround. Until SR ships that wiring, operators can flip the toggle via curl:

```bash
curl -sX PUT https://api.unboks.org/api/unboks/dashboard/api/settings/agent-learnings \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"showSuggestionAfterReplies":true,"createPendingLearningFromOperatorReplies":true}'
```

## Calvin retest steps

1. **Verify the toggle is now ON** on unboks (I'll flip it via `docker exec` after the deploy lands):
   ```bash
   curl -sH "Authorization: Bearer <token>" \
     https://api.unboks.org/api/unboks/dashboard/api/settings/agent-learnings
   # Expected: {"showSuggestionAfterReplies":..., "createPendingLearningFromOperatorReplies":true}
   ```

2. **Reply via the dashboard's Email Inbox**:
   - Open an email conversation in the Inbox (not the Escalations tab).
   - Click Reply, type something, send.
   - Within seconds: `curl -sH "Authorization: Bearer <token>" 'https://api.unboks.org/api/unboks/dashboard/api/escalation-learnings?status=pending'`
   - **Expected**: response contains a row with `suggestedText` = your reply text, `status="pending"`, `escalationId` = the customer email address.

3. **Reply via the Escalations tab** (Brief 266 already wired):
   - Open an escalation in Escalations, reply.
   - Same `?status=pending` GET should show a new row.

4. **WhatsApp side** (Brief 266 already wired): reply to a WA escalation via the Escalations tab. New pending row appears.

5. **Approve / Dismiss flow** (Brief 263): POST `/escalation-learnings/<id>/approve` or `/dismiss`. Status transitions verified.

If a reply still doesn't produce a pending row, please grab the exact endpoint URL the frontend hit (browser dev tools → Network tab → look for the POST request to /dashboard/api/...) — that pins down whether SR's frontend is hitting an endpoint I still haven't wired.

## Out of scope (still deferred)

- **SR's Replit Settings UI → Brief 264 PUT endpoint wire-up** (issue #35 frontend task).
- **Hard-block re-suggest after dismiss** (one-line SQL extension; documented in Brief 266 helper docstring).
- **Strict escalation-context gate** — currently the helper fires on every Inbox email reply regardless of whether the conversation has an active escalation. If Calvin wants stricter "only fire if `get_active_escalation_mode(conv_id) is not None`" semantics, that's a one-line guard in the helper.
