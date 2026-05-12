# BRIEF 266 — Wire Brief 264's `createPendingLearningFromOperatorReplies` toggle into the operator reply paths
**Status:** Draft | **Files:** `wtyj/dashboard/api.py`, `wtyj/tests/social/test_215_escalation_learning.py` | **Depends on:** Brief 263 (pending learning helper), Brief 264 (settings storage) | **Blocks:** issue #36 verification

## Context

Issue #36 P1 (Calvin live finding): Brief 264 shipped the Settings toggle `createPendingLearningFromOperatorReplies` but explicitly deferred the wire-up — toggling it ON does nothing today because the reply paths still call `save_escalation_learning(... status='approved')` (Brief 215 era auto-learn). Calvin tested the toggle, got no pending learnings, filed #36.

Audit:
- **Existing auto-learn pattern** in `dashboard/api.py` at 7 call sites — each operator reply path (Send & Resolve, hard-mode WA reply, soft-mode WA relay, email reply, guidance) does:
  ```python
  try:
      state_registry.save_escalation_learning(
          conversation_id=..., channel=...,
          source_question=state_registry._last_customer_message_for(...),
          human_answer=..., status="approved", ai_may_use=True)
  except Exception as _learn_exc:
      bm_logger.log("learning_write_failed", ...)
  ```
  Specific lines (from grep): `:3375` (reply hard WA), `:3428` (reply soft/relay WA), `:3471` (reply email), `:3558` (guidance WA), `:3630` (guidance email). **5 passive auto-learn sites total**.

Two other learning-create call sites in the same file are deliberately OUT of scope for Brief 266:
- `:553` — Brief 263's `/escalations/{id}/suggest-learning` endpoint (an explicit operator-triggered suggestion, always creates pending regardless of the toggle).
- `:3000` — `/escalations/{id}/resolve` endpoint's "Send & Resolve with saveAsLearning" branch. This site is already operator-gated (`body.saveAsLearning=true` required) AND accepts operator-controlled `body.autoUseNextTime` + `body.category` parameters. The toggle is for PASSIVE paths where the operator doesn't explicitly say "save this as a learning"; the resolve site is the operator's deliberate "yes, save this with these settings" choice and Brief 266 deliberately leaves it untouched so `body.autoUseNextTime=False` from the operator continues to be honored. If Calvin later wants the toggle to also override the resolve site's behavior, that's a separate product decision.
- **Toggle storage** is in `system_settings` per Brief 264, keyed `agent_learning_create_pending_from_replies` with value `"true"` / `"false"`. Read via `state_registry.get_setting(key, "")`.
- **Pending-learning helper** `state_registry.create_pending_learning(conversation_id, channel, source_question, suggested_text, created_by)` shipped in Brief 263 — inserts status='suggested' + ai_may_use=False (so prompt path excludes by construction).

Calvin's rules (#36 spec):
- Rule 4: when toggle ON, operator replies create pending learnings automatically.
- Rule 5: created learnings MUST be status pending/suggested only.
- Rule 6: not used by Agent until approved.
- Rule 7: dismissed/unapproved don't reach prompt path.

The product behavior shift Brief 266 implements: when the toggle is ON, the reply paths create pending rows INSTEAD OF approved rows. When the toggle is OFF, legacy auto-learn behavior is preserved (creates approved rows). This makes the toggle a real switch — not a "create both" duplicator.

## Why This Approach

Three options considered:

1. **Single helper `_create_learning_from_operator_reply` wraps the toggle read + the existing legacy save (chosen)** — replace each of the 5 passive auto-learn call sites with a call to the new helper. Helper does: empty-answer guard → duplicate guard → toggle read → either `create_pending_learning` (toggle ON) or legacy `save_escalation_learning(... status='approved')` (toggle OFF). One place for the toggle logic, easy to test, easy to extend later (e.g., if a third state is added). Backward compat: when toggle is OFF/unset, behavior is byte-identical to today.

2. **Inline the toggle check at every call site** — duplicates the `state_registry.get_setting` read + duplicate-guard logic across 5 sites. More LOC, more chances for a future call site to forget the wrap. Rejected.

3. **Create BOTH a pending row AND an approved row when toggle ON** — would let the operator review the pending row while the legacy auto-learn still feeds the prompt. Calvin's rule 5 explicitly says "Created learnings must be status pending/suggested ONLY" — the auto-approved row WOULD be used by the Agent before the operator reviews it, contradicting the spec. Rejected.

Trade-off accepted (option 1): when the toggle is ON, the legacy approved-row creation stops at every wired site. Existing tenants that have been relying on auto-learn-approved behavior would need to flip the toggle OFF (default) OR start approving pending rows explicitly. The default value is `false` (Brief 264 default), so existing tenants see no behavior change unless they opt in.

## Instructions

1. **New helper `_create_learning_from_operator_reply` in `wtyj/dashboard/api.py`** placed near the existing `/escalations/{id}/suggest-learning` endpoint (Brief 263 block at line 552):
   ```python
   def _create_learning_from_operator_reply(conversation_id: str,
                                              channel: str,
                                              answer: str,
                                              source: str = "",
                                              operator: str = "",
                                              escalation_id: int = None) -> "int | None":
       """Brief 266: wire-up helper called from every operator reply/guidance/
       resolve path. Reads the Brief 264 toggle `agent_learning_create_pending_
       from_replies`:
       - "true"  -> create_pending_learning (Brief 263; status='suggested',
         ai_may_use=False). Operator must approve before the Agent uses it.
       - else    -> legacy save_escalation_learning(status='approved',
         ai_may_use=True). Existing Brief 215 auto-learn behavior preserved.

       Guards:
       - Skips when `answer` is empty or whitespace-only.
       - Skips when an existing learning row for the same conversation_id
         already carries this exact `answer` text in any non-deleted status
         (dedup against re-replies / re-runs).

       Wrapped in try/except by the caller pattern - this helper returns
       None on guard skip or exception, learning row id on success."""
       try:
           stripped = (answer or "").strip()
           if not stripped:
               return None
           # Duplicate guard: same conversation + same answer + status != deleted.
           # Catches re-replies and re-runs (existing pending/approved/saved
           # rows with the same text block re-create). A previously DISMISSED
           # row (status='deleted') is intentionally NOT a duplicate match -
           # if the operator dismissed it and now replies with the same text,
           # we re-create the pending row so they can re-review (Brief 263's
           # edit-before-approve flow). To enforce hard "never re-create after
           # dismiss," extend this WHERE clause - deferred until Calvin asks.
           conn = state_registry._get_conn()
           dup = conn.execute(
               "SELECT id FROM escalation_learnings "
               "WHERE conversation_id = ? AND human_answer = ? "
               "AND status != 'deleted' LIMIT 1",
               (conversation_id, stripped)).fetchone()
           conn.close()
           if dup:
               return None
           toggle = state_registry.get_setting(
               _AGENT_LEARNING_SETTING_CREATE_PENDING, "")
           src_q = ""
           try:
               src_q = state_registry._last_customer_message_for(
                   conversation_id, channel) or ""
           except Exception:
               src_q = ""
           if toggle == "true":
               row_id = state_registry.create_pending_learning(
                   conversation_id=conversation_id,
                   channel=channel,
                   source_question=src_q,
                   suggested_text=stripped,
                   created_by=operator or None,
               )
           else:
               row_id = state_registry.save_escalation_learning(
                   conversation_id=conversation_id, channel=channel,
                   source_question=src_q,
                   human_answer=stripped,
                   status="approved", ai_may_use=True,
                   created_by=operator or None,
               )
           bm_logger.log(
               "learning_created_from_reply",
               escalation_id=escalation_id,
               source=source,
               toggle="pending" if toggle == "true" else "approved",
               row_id=row_id)
           return row_id
       except Exception as exc:
           bm_logger.log("learning_write_failed",
                          error=str(exc)[:120],
                          escalation_id=escalation_id,
                          source=source)
           return None
   ```

2. **Replace 5 passive auto-learn call sites in the reply/guidance paths** with the helper. Pattern: anywhere the legacy `state_registry.save_escalation_learning(... human_answer=<reply>, status='approved', ai_may_use=True)` block fires AND the parameters are hardcoded (not operator-supplied), replace with one line:
   ```python
   _create_learning_from_operator_reply(
       conversation_id=<conv_id>, channel=<chan>,
       answer=<reply_text>, source="<source-tag>",
       escalation_id=escalation_id)
   ```
   The try/except wrapper is now inside the helper; remove the per-site try/except. Site list (exact line numbers from grep at execution time — verify before editing):
   - `:3375` — `/escalations/{id}/reply` hard-mode WhatsApp branch
   - `:3428` — `/escalations/{id}/reply` soft/relay-mode WhatsApp branch
   - `:3471` — `/escalations/{id}/reply` email branch
   - `:3558` — `/escalations/{id}/guidance` WhatsApp branch
   - `:3630` — `/escalations/{id}/guidance` email branch

   **DO NOT** modify:
   - `:553` — Brief 263's `/escalations/{id}/suggest-learning` (always creates pending; the toggle does not apply).
   - `:3000` — `/escalations/{id}/resolve` "Send & Resolve with saveAsLearning" branch. This site is already operator-gated by `body.saveAsLearning=true` AND accepts `body.autoUseNextTime` + `body.category` from the request body. Routing it through the helper would silently drop both fields (the helper has no parameters for them), breaking operator-controlled behavior. The resolve site stays as-is; the toggle covers only the passive auto-learn paths.

3. **No schema change.** Brief 263's `escalation_learnings` columns + Brief 264's `system_settings` row are sufficient. Brief 266 only changes the dispatcher logic at the reply paths.

4. **No frontend changes required for Brief 266 to work.** The pending list view + approve/dismiss flow already ships in Brief 263. SR's Replit task to wire the Settings toggle UI lands in #35 separately. Brief 266 makes the toggle ACTUALLY DO SOMETHING when set; the UI to set it is Replit's.

## Tests

Append 6 tests to `wtyj/tests/social/test_215_escalation_learning.py` (canonical per-module file Brief 215 named, extended by Brief 263). All TestClient round-trips with controlled DB + toggle state.

1. **test_brief_266_toggle_off_creates_approved_legacy_behavior** — set `agent_learning_create_pending_from_replies` to empty (default OFF). Reply to an escalation via the existing helper or endpoint. Assert a learning is created with status='approved'. This proves backward compat — existing tenants with the toggle OFF see no behavior change.

2. **test_brief_266_toggle_on_creates_pending_not_approved** — `state_registry.set_setting("agent_learning_create_pending_from_replies", "true")`. Call `_create_learning_from_operator_reply(...)` directly with a non-empty answer. Assert the created row has status='suggested' AND ai_may_use_automatically=0 (direct SQL check). Assert `state_registry.list_escalation_learnings(status="suggested")` includes the row. Assert the prompt-path filter (`get_approved_learnings_for_prompt`) does NOT include the row.

3. **test_brief_266_empty_reply_skipped** — toggle ON. Call helper with `answer=""` and again with `answer="   \\n  "`. Assert no learning row created either time (`list_escalation_learnings()` count unchanged).

4. **test_brief_266_duplicate_answer_skipped** — toggle ON. Call helper twice with the same `(conversation_id, channel, answer)`. Assert only ONE row exists (second call returns None, no second row). Then call with a DIFFERENT answer on same conversation → assert a second row IS created (proves the guard is dup-by-text-not-by-conversation).

5. **test_brief_266_reply_endpoint_creates_pending_when_toggle_on** — end-to-end via the `/escalations/{id}/reply` endpoint (the canonical wire-up site). Seed an escalation, set the toggle ON, POST a reply, assert a status='suggested' row exists in `escalation_learnings`. Cleans up the toggle in tearDown.

6. **test_brief_266_resolve_site_unaffected_by_toggle** — regression guard that the `/escalations/{id}/resolve` site (intentionally NOT routed through the helper) still honors operator-supplied `body.autoUseNextTime=False` + `body.category="custom_cat"` even when the toggle is ON. Set `agent_learning_create_pending_from_replies=true`, POST to `/escalations/{id}/resolve` with `{saveAsLearning: true, resolutionNote: "Test note", autoUseNextTime: false, category: "custom_cat"}`. Assert: a row IS created (the `saveAsLearning=true` branch fired), status='approved' (NOT suggested - the toggle does not apply at this site), `ai_may_use_automatically=0` (operator's `autoUseNextTime=False` honored), category='custom_cat' (operator's choice honored). Proves the brief's "resolve site stays as-is" guarantee.

## Success Condition

After Brief 266 deploys:
- `agent_learning_create_pending_from_replies=true` AND operator replies via `/reply` / `/guidance` → a `status='suggested'` row appears in `escalation_learnings`, visible via `GET /escalation-learnings?status=pending` (Brief 263 endpoint).
- Same operator reply with toggle OFF → status='approved' row is created (legacy Brief 215 behavior preserved at the 5 wrapped sites).
- `/escalations/{id}/resolve` with `saveAsLearning=true` continues to honor operator-supplied `autoUseNextTime` + `category` parameters unchanged (NOT routed through the toggle helper - the resolve site is operator-gated, not passive).
- Empty/whitespace reply → no learning created.
- Same operator reply text on the same conversation twice → only one row exists.
- After the operator approves the pending row, the prompt path picks it up. After dismiss, the prompt path excludes it.
- All 4 production containers healthy post-deploy.

## Rollback

```
ssh root@108.61.192.52 "bash /root/wtyj/scripts/rollback.sh all"
```

Canonical rollback per `wtyj/briefs/infra.md:188`. Brief 266 is purely additive in helper terms (one new helper) + a 1-to-1 call-site swap (5 sites). Schema unchanged. Revert restores Brief 215 legacy auto-learn-approved behavior at every site. Any pending rows already created via the toggle survive the rollback as orphan suggested-state rows in the DB; they remain visible via the Brief 263 endpoints but no new ones are created post-rollback. No data loss possible.
