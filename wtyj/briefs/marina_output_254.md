# OUTPUT 254 — Clear orphan escalation flags on resolve + delete (email + WhatsApp)

## What was done

Issue #23 follow-up. After Calvin's PARTIAL/FAIL verification + Sonia's read-only audit at issue #24, this brief addresses the **backend** half of the problem (the frontend localStorage migration is a separate concern at SR's repo).

Sonia's identified root cause confirmed in code:
- `delete_escalation(escalation_id)` did just `DELETE FROM pending_notifications` — no cleanup of conversation_status, WA booking state flags, or email_thread_state flags.
- `resolve_conversation_from_escalation` cleared `conversation_status` + WA flags only — never email_thread_state.flags.fully_escalated.

Result: deleted/resolved email escalations left orphan flags that drove `escalated=true` in the dashboard's email detail + `status='escalated'` in the Inbox list, while `/escalations` returned nothing for the customer — exactly Calvin's symptom.

Per-step shipped:
1. **New helper `email_clear_fully_escalated_flag(customer_email)`** at `wtyj/shared/state_registry.py:2139`. Walks every `subj:{customer_email}:*` thread in email_thread_state.json and clears `flags.fully_escalated=False` + removes `flags.awaiting_relay`. Best-effort (returns 0 on file-missing/parse-fail/no-match) — never raises.
2. **Extended `resolve_conversation_from_escalation`** to call the new helper when `esc_channel == "email"`. WA-side cleanup unchanged.
3. **Modified `delete_escalation`** to call `resolve_conversation_from_escalation(escalation_id)` BEFORE the DELETE. The resolve helper SELECTs `customer_id + channel` while the row still exists, then handles all three cleanups (conversation_status, WA flags, email flags). DELETE runs after.
4. **4 new tests** appended to `wtyj/tests/social/test_188_conversation_status.py` (per Brief 236 — that file already had `test_resolve_clears_fully_escalated` for the WA branch). Tests: (a) resolve clears email flag, (b) delete clears email flag + sets conversation_status='resolved', (c) delete clears WA flag + sets conversation_status='resolved', (d) regression: delete returns False for missing id.

**Brief-reviewer:** PASS round 1 zero issues. Anchors verified, chain ordering correct (SELECT → cleanup → DELETE), test pattern matches Brief 236 + Brief 188 existing test 4 style.

## Tests

1087 passing / 0 failures (1083 baseline + 4 new = 1087). Targeted file `wtyj/tests/social/test_188_conversation_status.py` runs 9/9 (was 5; added 4).

## Production verification needed (post-deploy)

After deploy, Calvin should verify:
1. A NEW deletion of an email escalation (via dashboard trash button → `DELETE /escalations/{id}`) — the conversation should NOT continue showing `escalated=true` in the email detail. Email Inbox row should NOT show `status='escalated'` after.
2. A NEW resolution of an email escalation (via `POST /escalations/{id}/resolve`) — same expected behavior.
3. **Existing orphan-flag conversations (like `calvin@adamus.com`) will NOT auto-correct** — Brief 254 fixes the write path, not the historical state. To clean up production orphans, either: (a) delete or resolve each affected escalation row (this brief's cleanup fires), or (b) a one-time sweep script (out of scope, deferred). Recommended: try option (a) on Calvin's `calvin@adamus.com` escalation (id=27) — delete it via the dashboard, then verify the orphan flags clear.

## Deployment

Source commit pending. Pure additive cleanup logic; no schema migration, no API contract change, no read-path change. Briefs 238-253 all preserved. The Email channel's Inbox + detail will continue to show `escalated=true` for any conversation with existing orphan flags until an operator clears them (delete/resolve), at which point Brief 254's cleanup runs.

## Acceptance per issue #23

Backend half (Brief 254's scope):
1. ✅ `delete_escalation` now clears all orphan flags before the DELETE.
2. ✅ `resolve_conversation_from_escalation` now covers email channel (was WA-only).
3. ✅ Regression test for missing-id case preserved.
4. ⏳ Calvin live verification on a fresh email escalation delete/resolve.

Frontend half (separate work at `unboks-org/unboks-dashboard-api`):
- SR's `useArchivedConversations` migration from localStorage to Brief 249's server-side endpoints — out of scope here, documented in earlier issue #23 comment.

## Out-of-scope (deferred)

- Backfill sweep for production orphan flags — defer; per-row cleanup runs on next delete/resolve.
- `flags.awaiting_relay` consistency sweep (Brief 254 clears it as a side effect; standalone sweep deferred).
- Frontend localStorage migration — separate frontend brief at SR's repo.
