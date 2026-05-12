# BRIEF 264 — Server-side Agent learning preference settings (GET/PUT `/settings/agent-learnings`)
**Status:** Draft | **Files:** `wtyj/dashboard/api.py`, `wtyj/tests/social/test_230_knowledge_files.py` | **Depends on:** Brief 263 (learning approval flow) | **Blocks:** issue #35 verification, SR Replit task

## Context

Issue #35 P1 (Calvin product request): Replit added Agent learning UI after Brief 263. Calvin wants two Settings toggles to live server-side per tenant (no localStorage fallback):
1. `showSuggestionAfterReplies` (default `true`) — frontend renders a "suggest as learning" affordance after every operator reply.
2. `createPendingLearningFromOperatorReplies` (default `false`) — when ON, an operator reply auto-creates a pending learning via Brief 263's `create_pending_learning`. **Must NOT auto-approve** — only creates `status='suggested'` rows for explicit operator review.

Calvin's spec is tight: two booleans, two endpoints (GET + PUT), defaults, validation, tenant isolation.

Backend audit:
- **`system_settings` table** at `wtyj/shared/state_registry.py:680` is a generic key-value store (TEXT key PK, TEXT value NOT NULL) with helpers `get_setting(key, default)` at line 3746 and `set_setting(key, value)` at line 3754. Tenant isolation is by construction (each container has its own DB file).
- **No existing `/settings/agent-learnings` endpoint** — Brief 264 adds new endpoints; no existing surface to extend.
- **Brief 263 prompt-path filter** at `state_registry.py:4310` (`get_approved_learnings_for_prompt`) filters `status IN ('approved', 'saved') AND ai_may_use_automatically = 1`. Auto-created pending learnings from Brief 264's `createPendingLearningFromOperatorReplies` toggle would carry `status='suggested'` + `ai_may_use=0`, so they're naturally excluded from the prompt path until an operator explicitly approves them. Calvin's rule 7-8 is satisfied by the existing filter — Brief 264 only stores the setting, it does NOT wire the auto-create logic into the reply path. **That wire-up is deferred to a follow-up brief** so this brief stays focused on Calvin's "no localStorage for tenant settings" core requirement.

## Why This Approach

Three options considered:

1. **Reuse `system_settings` key-value table; two new helpers, two new endpoints (chosen)** — zero schema change. Each setting is a row keyed by a stable string (`agent_learning_show_suggestion`, `agent_learning_create_pending_from_replies`). GET reads both keys with bool-parsing fallback to defaults. PUT validates booleans via Pydantic, sets both keys. ~50 LOC + 5 tests. The simplest possible persistence for two booleans.

2. **New dedicated table `agent_learning_settings` with two boolean columns** — would be cleaner structurally but adds schema migration for two booleans that fit fine in the existing key-value table. Brief 263 lesson: don't fork persistence when an existing table fits. Rejected.

3. **JSON-blob single-row pattern (like Brief 262's `source_of_truth`)** — works but overkill for two booleans. The blob pattern shines for nested arrays (SotBlock); for flat key-value config, the existing `system_settings` is the right primitive. Rejected.

Trade-off accepted (option 1): `system_settings` stores all values as TEXT, so booleans round-trip as `"true"` / `"false"` strings. The helpers parse on the way out (`value == "true"` → Python `True`). Frontend never sees the string form — the API surface is pure JSON booleans.

## Instructions

1. **No schema change**. Reuse `system_settings` table via existing `state_registry.get_setting` / `set_setting`.

2. **New constants in `wtyj/dashboard/api.py`** placed near the other settings-related endpoints (e.g., adjacent to `/settings/blocked-conversations` at `api.py:3036` or `/source-of-truth` at the Brief 262 block):
   ```python
   _AGENT_LEARNING_SETTING_SHOW = "agent_learning_show_suggestion"
   _AGENT_LEARNING_SETTING_CREATE_PENDING = "agent_learning_create_pending_from_replies"
   _AGENT_LEARNING_DEFAULTS = {
       "showSuggestionAfterReplies": True,
       "createPendingLearningFromOperatorReplies": False,
   }
   ```

3. **New helper `_read_agent_learning_settings()`** in `wtyj/dashboard/api.py`:
   ```python
   def _read_agent_learning_settings() -> dict:
       """Brief 264: read both Agent learning toggles from system_settings,
       parse stored TEXT values back to Python bools, fall back to
       defaults when key is missing. Returns the camelCase shape the
       frontend expects."""
       show_raw = state_registry.get_setting(
           _AGENT_LEARNING_SETTING_SHOW, "")
       create_raw = state_registry.get_setting(
           _AGENT_LEARNING_SETTING_CREATE_PENDING, "")
       return {
           "showSuggestionAfterReplies": (
               show_raw == "true" if show_raw
               else _AGENT_LEARNING_DEFAULTS["showSuggestionAfterReplies"]
           ),
           "createPendingLearningFromOperatorReplies": (
               create_raw == "true" if create_raw
               else _AGENT_LEARNING_DEFAULTS["createPendingLearningFromOperatorReplies"]
           ),
       }
   ```

4. **New endpoints in `wtyj/dashboard/api.py`** placed near the existing `/source-of-truth` endpoints (Brief 262) — both are "tenant settings" surfaces:
   ```python
   @router.get("/settings/agent-learnings",
               dependencies=[Depends(_check_auth)])
   async def get_agent_learning_settings():
       """Brief 264: load tenant Agent learning preference settings.
       Returns defaults for any setting not yet saved."""
       return _read_agent_learning_settings()


   class AgentLearningSettingsRequest(BaseModel):
       showSuggestionAfterReplies: bool
       createPendingLearningFromOperatorReplies: bool


   @router.put("/settings/agent-learnings",
               dependencies=[Depends(_check_auth)])
   async def put_agent_learning_settings(req: AgentLearningSettingsRequest):
       """Brief 264: save tenant Agent learning preference settings.
       Pydantic enforces booleans on the way in; helper stringifies
       for system_settings storage. Returns the canonical saved state."""
       state_registry.set_setting(
           _AGENT_LEARNING_SETTING_SHOW,
           "true" if req.showSuggestionAfterReplies else "false")
       state_registry.set_setting(
           _AGENT_LEARNING_SETTING_CREATE_PENDING,
           "true" if req.createPendingLearningFromOperatorReplies else "false")
       return _read_agent_learning_settings()
   ```
   Pydantic's `bool` field rejects non-boolean payloads with HTTP 422 (FastAPI default Pydantic validation response). Calvin's spec rule 5 says "Invalid payload returns safe 400" - Brief 264 ships **422 (the industry-standard validation-error status code)** rather than overriding to 400. The "safe" qualifier in the spec is satisfied: no crash, no info leak, structured detail in the response body. If Calvin objects to 422 specifically and wants 400, that's a future one-line override via a custom validation exception handler; document the deliberate 422 choice in OUTPUT and flag for follow-up.

5. **NO downstream wire-up** in this brief. The `createPendingLearningFromOperatorReplies` setting being `true` does NOT yet cause operator replies to auto-create pending learnings — that requires hooking into the reply path (`/reply` and `/guidance` endpoints, the operator-takeover flow, etc.) which Brief 264 explicitly defers. Calvin's spec rule 6 ("Do not change existing learning approval semantics") is satisfied because no behavioral change ships in this brief beyond the new storage surface.

## Tests

Append 5 tests to `wtyj/tests/social/test_230_knowledge_files.py` (canonical per-module file for backend tenant-config endpoints — Brief 230 named it; Brief 260's `/knowledge/cloud-connections` and Brief 262's `/source-of-truth` tests already extend it). Same pattern: real TestClient round-trips with controlled DB state.

1. **test_brief_264_get_returns_defaults_on_fresh_tenant** — wipe `system_settings` rows for the two keys. GET `/settings/agent-learnings`. Assert response is exactly `{"showSuggestionAfterReplies": true, "createPendingLearningFromOperatorReplies": false}`. Proves the default-on-empty contract.

2. **test_brief_264_put_persists_both_booleans** — PUT `/settings/agent-learnings` with body `{"showSuggestionAfterReplies": false, "createPendingLearningFromOperatorReplies": true}`. Assert 200 + response echoes the saved values. Then GET → assert same shape returned. Round-trip persistence.

3. **test_brief_264_put_validates_non_boolean_rejected** — PUT with `{"showSuggestionAfterReplies": "yes", "createPendingLearningFromOperatorReplies": false}`. Assert 422 (FastAPI/Pydantic validation error). After failure, GET returns the prior state (no partial save).

4. **test_brief_264_partial_settings_use_defaults_for_missing_key** — directly set ONE key via `state_registry.set_setting(...)` and leave the other unset. GET should return the saved value for the set key AND the default for the missing key. Proves the per-key default-fallback works (not just whole-tenant default-on-empty).

5. **test_brief_264_no_downstream_wire_up_yet** — load-bearing assertion that Brief 264 does NOT change the reply path. Set `createPendingLearningFromOperatorReplies=true` via PUT. Then directly call `state_registry.list_escalation_learnings(status="suggested")` before and after the PUT — assert the count is unchanged (no learnings auto-created by toggling the setting alone). Proves the deferred-wire-up scope decision is honest.

## Success Condition

After Brief 264 deploys:
- `curl -X GET https://api.unboks.org/api/unboks/dashboard/api/settings/agent-learnings` with auth → returns `{"showSuggestionAfterReplies": true, "createPendingLearningFromOperatorReplies": false}` on a fresh tenant.
- `curl -X PUT` with a valid body → 200, both keys persist; subsequent GET returns the saved state.
- BlueMarlin / Adamus / Consulta Despertares / unboks each carry independent settings (per-container DB isolation).
- Invalid payload (`"yes"`, `null`, missing key) returns 422 with a clear Pydantic validation detail; no partial save.
- All 4 production containers healthy post-deploy.
- Frontend contract documented in OUTPUT so SR can wire the two toggles.
- Setting `createPendingLearningFromOperatorReplies=true` does NOT yet cause auto-create at the reply path — documented as a follow-up brief if Calvin wants the wire-up next.

## Rollback

```
ssh root@108.61.192.52 "bash /root/wtyj/scripts/rollback.sh all"
```

Canonical rollback per `wtyj/briefs/infra.md:188`. Pure additive change (two new endpoints, two new helpers, no schema migration). The new `system_settings` rows survive a rollback on disk but are unused by the rolled-back code — harmless. If a tenant has already PUT settings, a rollback orphans the rows in the DB but causes no functional breakage. The frontend's localStorage stub (if SR keeps one as a transitional fallback) continues to work during any rollback window. Worst case: re-deploy after fixing; saved settings survive.
