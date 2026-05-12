# BRIEF 267 — Wire Brief 266's learning helper into `/messages/conversations/{id}/email/reply` (Brief 225 Inbox-side email reply endpoint)
**Status:** Draft | **Files:** `wtyj/dashboard/api.py`, `wtyj/tests/social/test_215_escalation_learning.py` | **Depends on:** Brief 266 (toggle helper) | **Blocks:** issue #36 verification (round 2)

## Context

Calvin's live retest of Brief 266 (issue #36 round 2) FAILED. He set `createPendingLearningFromOperatorReplies=true`, replied via the dashboard's Email Inbox conversation detail, and saw no pending learning created.

Production investigation:

1. **Setting check on unboks**: `state_registry.get_setting("agent_learning_create_pending_from_replies", ...)` returns `'false'` on the live container. Calvin says he toggled it ON in the dashboard UI but the server has it OFF. Two possible explanations:
   - SR's Replit Settings UI hasn't yet wired the toggle to the Brief 264 PUT endpoint (still localStorage). This is SR's #35 task; it might land on a different timeline.
   - Or Calvin toggled on a different tenant URL than unboks's.
   Either way, the server-side toggle is currently "false" for unboks — explaining why ALL recent learning rows show `status='approved'` (the legacy toggle-OFF behavior).

2. **Helper deployed**: 6 occurrences of `_create_learning_from_operator_reply` in `/app/dashboard/api.py` on the live unboks container. Brief 266 IS live.

3. **Missing wire site**: `/messages/conversations/{conversation_id:path}/email/reply` at `dashboard/api.py:2074` (Brief 225 era) is the Inbox-side email-reply endpoint the dashboard frontend likely uses. Verified via grep — it never called `save_escalation_learning` (no learning auto-creation today, even with toggle OFF). Brief 266 only refactored the 5 sites that ALREADY had `save_escalation_learning` calls (the `/escalations/{id}/reply` family). When the operator replies from the Email INBOX (not from the Escalations detail), the request hits this Brief 225 endpoint and silently exits without creating a learning row regardless of the toggle state.

4. **No WhatsApp Inbox-side reply endpoint**: grep confirms no `/messages/conversations/{conversation_id}/whatsapp/reply` exists — WA dashboard replies go through `/escalations/{id}/reply` which Brief 266 already wired. WA path is correct.

5. **Recent learning rows**: rows 23-32 on unboks are all `status='approved'`, all from email replies. Row 24 was dismissed, row 25-26 approved versions of "Yes, we are open on Sundays..." appear twice — confirms the Brief 226-area `/escalations/{id}/reply` path was hit on those (legacy save_escalation_learning fires there, just with default-approved status because toggle is OFF).

Summary of the bug: Brief 266 wired 5 reply paths but the Email Inbox-side reply path (Brief 225's `/messages/conversations/{id}/email/reply`) was NOT among them because it never had a learning-create call to refactor in the first place. It's a NEW wire site, not a refactor of an existing one.

## Why This Approach

Three options considered:

1. **Wire the Brief 266 helper into `/messages/conversations/{id}/email/reply` (chosen)** — single new call to `_create_learning_from_operator_reply(...)` right after the operator's email is dispatched and the thread message is appended. Resolves the bug at the smallest surface. Same toggle-aware semantics: ON → pending row; OFF → approved row (consistent with what the `/escalations/{id}/reply` email branch already does after Brief 266).

2. **Force the unboks toggle to "true" via direct DB write so the retest works without backend changes** — would prove the toggle plumbing works end-to-end but doesn't fix the underlying Inbox-side endpoint gap. Calvin's #36 spec rule 1 says "Learning is escalation-based and channel-agnostic"; option 2 wouldn't satisfy "channel-agnostic" because the email Inbox reply still wouldn't auto-create. Rejected as a band-aid.

3. **Reject the Brief 225 endpoint and require the frontend to use `/escalations/{id}/reply` instead** — would force SR to change the frontend wiring for the Inbox email reply UX. Bigger blast radius; less honest about which endpoint is the canonical reply path today. Rejected.

Trade-off accepted (option 1): `/messages/conversations/{id}/email/reply` (Brief 225) is technically a "non-escalation reply" path — it lets the operator reply to any email conversation, escalated or not. Brief 266's helper will now fire on EVERY operator email reply from the dashboard, not just escalation-bound ones. Calvin's spec rule 1 says "escalation-based" but rule 2 expands to "It must work for Email, WhatsApp, and other escalation channels where operator replies are supported" — i.e., the operator-reply trigger matters more than the strict-escalation-context check. If Calvin later wants the helper to ONLY fire when the conversation IS in an escalation (check `pending_notifications` for the customer_id), that's a one-line guard in the helper (`if not state_registry.get_active_escalation_mode(conversation_id): return None`) — flagged for follow-up.

Production hotfix orthogonally: I will ALSO set `agent_learning_create_pending_from_replies="true"` on unboks's live `system_settings` row so Calvin's retest doesn't depend on SR's Replit Settings toggle UI being wired first. Documented separately in OUTPUT — this is operator-side data, not part of the brief's code diff.

## Instructions

1. **Wire the helper into `reply_to_email_conversation`** at `dashboard/api.py:2074-2126`. Add one call to `_create_learning_from_operator_reply` immediately after the successful `email_append_assistant_message` call (around line 2120, before the return statement):
   ```python
   matched = state_registry.email_append_assistant_message(
       customer_email, body, role="operator")
   bm_logger.log("dashboard_email_reply_sent",
                 thread_key=thread_key[:60],
                 email=customer_email[:60],
                 matched=matched or "(no thread match)")

   # Brief 266 + Brief 267: toggle-aware learning create from Inbox-side
   # email reply. Same helper as the /escalations/{id}/reply path - reads
   # the agent_learning_create_pending_from_replies toggle and routes to
   # create_pending_learning (status='suggested') or save_escalation_learning
   # (status='approved') accordingly. No escalation_id available at this
   # endpoint (the Brief 225 surface is conversation-scoped, not
   # escalation-scoped); helper accepts None.
   _create_learning_from_operator_reply(
       conversation_id=customer_email,
       channel="email",
       answer=body,
       source="messages_email_reply",
       escalation_id=None)

   return {"ok": True, "channel": "email"}
   ```

2. **No other code changes**. The helper, Brief 264 settings storage, Brief 263 endpoints, and Brief 215 prompt-path filter are all already in place. Brief 267 is a one-line wire at one site.

3. **Production toggle flip (operator-side, separate from code)**: after the deploy lands, run on the VPS:
   ```bash
   ssh root@108.61.192.52 'docker exec wtyj-unboks python3 -c "
   from shared import state_registry
   state_registry.set_setting(\"agent_learning_create_pending_from_replies\", \"true\")
   print(\"OK:\", state_registry.get_setting(\"agent_learning_create_pending_from_replies\"))"'
   ```
   This unblocks Calvin's retest immediately. SR's Replit Settings UI wire-up to the Brief 264 PUT endpoint remains a separate frontend task (#35).

## Tests

Append 1 test to `wtyj/tests/social/test_215_escalation_learning.py`. This is a targeted wire-up regression test for the new site; the Brief 266 helper's behavior is already covered by 6 existing tests.

1. **test_brief_267_inbox_email_reply_creates_pending_when_toggle_on** — end-to-end through `/messages/conversations/<email_key>/email/reply` with the toggle ON. Setup:
   - Set `agent_learning_create_pending_from_replies="true"`.
   - Seed an email thread in `email_thread_state.json` via monkeypatched path + JSON file with shape `subj:267_inbox_test@example.com:test subject` + at least one customer message.
   - Monkeypatch `smtp_send` (both `email_adapter.smtp_send` and `dashboard.api.smtp_send`) to return True without actually sending.
   - POST `/dashboard/api/messages/conversations/email::subj:267_inbox_test@example.com:test%20subject/email/reply` with body `{"body": "Brief 267 inbox reply text"}`.
   - Assert 200 status.
   - Assert a `status='suggested'` row exists in `escalation_learnings` with `conversation_id='267_inbox_test@example.com'` and `human_answer='Brief 267 inbox reply text'`.
   - Cleanup: wipe the test learning + reset the toggle.

## Success Condition

After Brief 267 deploys + the production toggle flip:
- Calvin sets the toggle ON (via curl or, once SR ships it, via the Settings UI).
- Calvin replies via the dashboard's Email Inbox conversation detail.
- `GET /escalation-learnings?status=pending` returns the new row with the reply text.
- WhatsApp reply via the dashboard's Escalations detail also creates a pending row (Brief 266 already covers this path; verified by the existing Test 5 in Brief 266's test suite).
- Both channels honor the toggle uniformly.
- All 4 containers healthy post-deploy.

## Rollback

```
ssh root@108.61.192.52 "bash /root/wtyj/scripts/rollback.sh all"
```

Canonical rollback. Brief 267 is a single-line addition to one endpoint; rollback restores the pre-267 behavior (Inbox email reply path doesn't create a learning row, regardless of toggle). The production toggle flip in step 3 of Instructions is a DB write to `system_settings` — survives a code rollback (data persists). If Calvin wants the toggle back to default-false after rollback: `state_registry.set_setting("agent_learning_create_pending_from_replies", "false")` via the same docker exec pattern.
