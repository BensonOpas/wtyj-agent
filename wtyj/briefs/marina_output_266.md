# OUTPUT 266 — Wire `createPendingLearningFromOperatorReplies` toggle into reply paths

## What was done

P1 for issue #36. Brief 264 shipped the Settings toggle but explicitly deferred the wire-up; Calvin tested the toggle ON, got no pending learnings, filed #36. Brief 266 wires the toggle into 5 passive operator-reply paths via a single helper.

New helper `_create_learning_from_operator_reply` in `wtyj/dashboard/api.py` (placed after Brief 263's `/escalations/{id}/suggest-learning` endpoint at line ~565). Reads the Brief 264 toggle and routes:
- `agent_learning_create_pending_from_replies = "true"` → `state_registry.create_pending_learning` (Brief 263 helper; status='suggested', ai_may_use=False). Operator must explicitly approve before the Agent uses it.
- Anything else (toggle off / unset / default) → legacy `state_registry.save_escalation_learning(status='approved', ai_may_use=True)` (Brief 215 auto-learn behavior preserved).

Guards inside the helper:
- Empty/whitespace answer → skip (no row created).
- Duplicate (same conversation_id + same answer text in any non-deleted status) → skip. Dismissed (deleted) rows are NOT a duplicate match — operator can re-create after dismiss via a fresh reply (documented in the helper's docstring; matches Brief 263's edit-before-approve flow).

Refactored 5 passive auto-learn call sites to use the helper:
- `/escalations/{id}/reply` — hard-mode WhatsApp branch (line ~3375 pre-refactor)
- `/escalations/{id}/reply` — soft/relay-mode WhatsApp branch (line ~3428)
- `/escalations/{id}/reply` — email branch (line ~3471)
- `/escalations/{id}/guidance` — WhatsApp branch (line ~3558)
- `/escalations/{id}/guidance` — email branch (line ~3630)

The per-site try/except wrappers are removed (helper handles error path internally; never raises, never blocks the customer-facing reply).

## Exact reply paths wired

| Endpoint | Source tag (in bm_logger) | Channel |
|---|---|---|
| `POST /escalations/{id}/reply` (hard WA) | `reply_whatsapp_hard` | whatsapp |
| `POST /escalations/{id}/reply` (soft WA) | `reply_whatsapp` | whatsapp |
| `POST /escalations/{id}/reply` (email) | `reply_email` | email |
| `POST /escalations/{id}/guidance` (WA) | `guidance_whatsapp` | whatsapp |
| `POST /escalations/{id}/guidance` (email) | `guidance_email` | email |

## Deliberately UNCHANGED

- **`POST /escalations/{id}/suggest-learning`** (Brief 263) — explicit operator-triggered suggest, always creates pending regardless of the toggle. Not touched.
- **`POST /escalations/{id}/resolve` "Send & Resolve with saveAsLearning"** — operator-gated by `body.saveAsLearning=true` AND honors `body.autoUseNextTime` + `body.category` from the request body. Routing through the helper would silently drop both parameters. Test 6 is the regression guard that catches any future attempt to refactor this site into the helper.

## Channels covered

Email + WhatsApp + WA-soft (relay mode). The helper is channel-agnostic — any future channel that adds an operator-reply path can adopt it with a single call.

## Duplicate / empty suppression behavior

- **Empty answer**: `(answer or "").strip()` → if empty, helper returns `None` immediately. No DB write, no bm_logger event.
- **Duplicate answer**: `SELECT id FROM escalation_learnings WHERE conversation_id = ? AND human_answer = ? AND status != 'deleted'`. If a row exists, helper returns `None`.
- **Dismissed re-creation allowed**: status='deleted' rows are explicitly excluded from the dedup match. Operator can re-create a suggestion they previously dismissed by replying with the same text. Documented in the helper docstring.
- **Different answer text**: NOT deduped. Same conversation, two different replies → two rows.

## Tests / build result

**1136 passing / 0 failures** (1130 Brief-265 baseline + 6 new Brief 266 = 1136).

6 new tests in `wtyj/tests/social/test_215_escalation_learning.py`:
1. `test_brief_266_toggle_off_creates_approved_legacy_behavior` — proves backward compat for OFF state (Brief 215 behavior preserved).
2. `test_brief_266_toggle_on_creates_pending_not_approved` — proves toggle ON creates status='suggested' + ai_may_use=0 + prompt path excludes.
3. `test_brief_266_empty_reply_skipped` — empty + whitespace-only answers create no rows.
4. `test_brief_266_duplicate_answer_skipped` — same text twice → 1 row; different text → 2 rows.
5. `test_brief_266_reply_endpoint_creates_pending_when_toggle_on` — end-to-end through the `/reply` endpoint with toggle ON.
6. `test_brief_266_resolve_site_unaffected_by_toggle` — **load-bearing regression guard**: with toggle ON, the resolve site still creates approved (not suggested), honors operator-supplied `autoUseNextTime=False`, honors operator-supplied `category='custom_cat'`. Proves the brief's "resolve site stays as-is" guarantee.

## Production health

CI queued post-commit `918807a`. All 4 containers expected healthy on the new image. No schema migration — Brief 263's `escalation_learnings` columns + Brief 264's `system_settings` row provide everything Brief 266 needs.

## Replit / frontend contract

**No frontend changes required.** The Brief 263 endpoints (`GET /escalation-learnings?status=pending`, PATCH, approve, dismiss) already exist; SR's pending list UI consumes them. Brief 266 just makes the existing toggle ACTUALLY DO SOMETHING when set.

The Brief 264 toggle UI (two checkboxes in Settings) lives at Replit per the #35 plan. Brief 266 doesn't change the toggle schema or endpoint — it just makes the `createPendingLearningFromOperatorReplies` value functional.

## Calvin retest steps

1. **Set the toggle ON**:
   ```bash
   TOKEN=$(curl -sX POST https://api.unboks.org/api/unboks/dashboard/api/login \
     -H "Content-Type: application/json" \
     -d '{"password": "<dashboard pw>"}' | jq -r .token)
   curl -sX PUT https://api.unboks.org/api/unboks/dashboard/api/settings/agent-learnings \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"showSuggestionAfterReplies":true,"createPendingLearningFromOperatorReplies":true}'
   ```

2. **Reply to an email escalation**:
   - Trigger an email escalation on the unboks tenant (e.g., have a test customer email through; let Marina escalate).
   - Open the escalation in the dashboard. Reply via the dashboard with some answer text.
   - Then: `curl -sH "Authorization: Bearer $TOKEN" 'https://api.unboks.org/api/unboks/dashboard/api/escalation-learnings?status=pending'`
   - **Expected**: the response contains a row with `suggestedText` = your reply text and `status="pending"`.

3. **Reply to a WhatsApp escalation**:
   - Same dance for a WhatsApp escalation (or send via guidance instead of reply).
   - GET `?status=pending` again → new row appears for the WA conversation.

4. **Verify Agent prompt path excludes pending**:
   - Set unboks's `client.json::features.approved_learnings_in_prompt: true` if not already.
   - Send a customer WhatsApp message that would normally have used the prompt path. The PENDING rows from steps 2-3 must NOT influence Marina's reply (her prompt should NOT include them as approved knowledge).

5. **Approve the pending row**:
   - POST `/escalation-learnings/{id}/approve` with `{operator: "calvin"}`. Status flips to "approved" + ai_may_use_automatically=1.
   - Next customer message → Marina's prompt now includes the approved learning.

6. **Dismiss instead**:
   - On a different pending row, POST `/escalation-learnings/{id}/dismiss` (no body). Status='deleted' (soft) + dismissed_at populated. Prompt path still excludes.

7. **Turn toggle OFF**:
   - PUT `/settings/agent-learnings` with `createPendingLearningFromOperatorReplies: false`.
   - Reply to a new escalation. GET `?status=pending` → no new row (toggle OFF preserves legacy approved behavior).
   - GET `?status=approved` → a new approved row IS created (Brief 215 auto-learn unchanged when toggle is OFF).

8. **Resolve site regression check** (proves the operator's explicit choices on Send & Resolve are NOT overridden by the toggle):
   - Toggle ON.
   - POST `/escalations/{id}/resolve` with `{saveAsLearning: true, resolutionNote: "Resolution text", autoUseNextTime: false, category: "custom_cat"}`.
   - GET `/learning` (Brief 215 legacy endpoint) → the row should appear with `status="approved"`, `aiMayUseAutomatically=false`, `category="custom_cat"`. Operator's choices honored despite toggle being ON.

## Out of scope (still deferred)

- **422 → 400 override on the `/settings/agent-learnings` validation path** (Brief 264 deferred item; unrelated to #36).
- **Brief 215 default-flip** — `save_escalation_learning`'s default `status='approved'` for callers OUTSIDE Brief 266's helper. The 5 wired sites now respect the toggle; the suggest-learning endpoint and resolve site keep their existing semantics. If Calvin wants ALL auto-create paths (including resolve) to require explicit approval, that's a separate product decision per tenant.
- **Re-suggest after dismiss "hard block"** — Brief 266's dedup currently lets an operator re-suggest a previously-dismissed text. If Calvin wants the dedup to ALSO match dismissed rows (so a once-dismissed text can never re-appear as pending), one-line change to the SQL WHERE clause; flagged in the helper docstring.
