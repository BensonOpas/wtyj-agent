# BRIEF 263 — Operator-approved learnings: extend Brief 215 system with suggest/edit/dismiss + audit fields + Calvin's endpoint naming
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/tests/social/test_215_escalation_learning.py` | **Depends on:** Brief 215 (foundation), Brief 219 (prompt path), Brief 222 (status precedence), Brief 230 (prompt integration) | **Blocks:** issue #32 verification

## Context

Issue #32 P1 (Calvin product request): Agent must not auto-learn from every human escalation reply — operator must explicitly approve, edit, or dismiss a suggested learning before the Agent uses it. Calvin's rule 1: *"Check existing escalation learning tables/endpoints first."*

Audit (verified in code):

**Existing Brief 215 era system** is substantial. Table `escalation_learnings` at `state_registry.py:449` with columns:
```
id, conversation_id, channel, source_question, human_answer, status,
ai_may_use_automatically, category, created_by, created_at, updated_at
```
Valid statuses per `update_escalation_learning_status` at `state_registry.py:4176`: `suggested | approved | saved | deleted`. Default insert status (`save_escalation_learning`): `approved` — i.e., the system today AUTO-LEARNS from every operator reply.

Existing endpoints at `dashboard/api.py:419-445`:
- `GET /learning?status=...` — list, filter by status
- `DELETE /learning/{id}` — hard delete
- `POST /learning/{id}/approve` — flip to status=approved
- `POST /learning/{id}/save` — flip to status=saved

Prompt path at `state_registry.py:4220` (`get_approved_learnings_for_prompt`): returns rows with `status IN ('approved', 'saved') AND ai_may_use_automatically = 1`. Wired into Marina at `marina_agent.py:331-...` and dm_agent at `dm_agent.py:30-...`, gated by `client.json::features.approved_learnings_in_prompt`.

**Calvin's #32 spec gaps** vs existing:
1. **Status naming**: spec uses `pending` / `approved` / `dismissed`; existing uses `suggested` / `approved` / `saved` / `deleted`. Mapping needed: `pending ≡ suggested`, `dismissed ≡ deleted` (or a new soft-reject distinct from hard delete).
2. **PATCH endpoint** for editing learning text before approval: doesn't exist.
3. **Dismiss endpoint** (`POST /escalation-learnings/{id}/dismiss`): doesn't exist (only `DELETE` hard-removes today).
4. **Suggest endpoint** (`POST /escalations/{id}/suggest-learning`): doesn't exist. Today, learnings are created only as side-effects of `/reply` / `/guidance` flows with default status=approved.
5. **Audit fields** `approved_at`, `dismissed_at`, `approved_by`: not stored separately. `updated_at` carries the most recent timestamp regardless of which transition; `created_by` captures the initial operator but not the approver if those differ.
6. **Endpoint path naming**: Calvin's spec wants `/escalation-learnings/*`; existing is `/learning/*`. Backward compat requires both work.
7. **Response shape mapping**: Calvin's spec wants `id` (string), `escalationId`, `suggestedText`, `approvedText`, `approvedAt`, `dismissedAt`, `operator`. Existing returns `id` (int), `conversationId`, `humanAnswer`, `createdBy`. Mapping layer needed.

**Auto-learn default product decision (out of scope for Brief 263, flagged for follow-up):** Calvin's rule "Agent must not auto-learn from every human reply" implies the CURRENT default (`save_escalation_learning(... status='approved')`) is the wrong default going forward. Changing it from `'approved'` to `'suggested'` would mean every operator reply now requires explicit approval before the Agent uses it — a behavioral shift on every active tenant. Deferring this default-flip to a separate brief is the right call because: (a) it needs Calvin's explicit confirmation on every tenant (BlueMarlin photos OAuth flow may already depend on the auto-learn behavior), (b) the migration question for existing tenants' learnings is non-trivial, (c) Brief 263 first delivers the missing endpoints + audit columns so Calvin can verify the operator-approval flow works end-to-end before the default flip.

## Why This Approach

Three options considered:

1. **Extend Brief 215 with new endpoints + audit columns + status-term mapping at the API boundary; preserve auto-learn default (chosen)** — closes Calvin's surface gaps (suggest/edit/dismiss endpoints, audit fields, alias paths) WITHOUT changing the existing auto-learn behavior. Frontend can wire the operator-approval UI immediately; the backend supports both auto-created `approved` rows (legacy) and operator-created `suggested` rows (new). The default-flip is a separate product decision Calvin can make explicitly later.

2. **Full rename + status migration + default-flip in this brief (rejected)** — would rename `suggested` → `pending` and `deleted` → `dismissed` at the schema level, change `save_escalation_learning` default to `pending`, migrate all existing `approved` rows. Bigger blast radius; couples a product-policy decision (don't auto-learn) with a backend refactor. Calvin's spec is "extend or document," not "rebuild." Rejected as over-scope.

3. **New parallel table `learning_suggestions` for the operator-approval flow; keep `escalation_learnings` as-is for auto-learn (rejected)** — would mean two tables doing similar work with subtle differences. Brief 261 lesson applies: grep the existing system, extend it, don't fork. Rejected.

Trade-off accepted (option 1): the `dismissed` state maps to `deleted` internally, which is a hard delete in the existing system. Brief 263 reuses the `deleted` status as a soft-rejection marker (the row stays in the table, just filtered out everywhere `status != 'deleted'` is checked) — this matches the existing semantics of `list_escalation_learnings` at `state_registry.py:4163` which already skips `status='deleted'`. The existing `DELETE /learning/{id}` endpoint hard-removes the row; the new `POST /escalation-learnings/{id}/dismiss` endpoint soft-rejects via `UPDATE status='deleted'`. Both behaviors coexist; frontend chooses based on UX intent (Dismiss vs Permanently Delete). The existing `update_escalation_learning_status` already validates `deleted` as an allowed status, so this is a name change at the API boundary only.

## Instructions

1. **Schema migration in `state_registry.py`** — extend the existing `escalation_learnings` table with three audit columns. Place idempotent `ALTER TABLE` statements adjacent to the existing Brief 220+ pattern (after the `CREATE TABLE escalation_learnings` block at line 461):
   ```python
   # Brief 263: operator-approval audit fields per issue #32.
   try:
       conn.execute("ALTER TABLE escalation_learnings ADD COLUMN approved_at TEXT")
   except sqlite3.OperationalError:
       pass
   try:
       conn.execute("ALTER TABLE escalation_learnings ADD COLUMN dismissed_at TEXT")
   except sqlite3.OperationalError:
       pass
   try:
       conn.execute("ALTER TABLE escalation_learnings ADD COLUMN approved_by TEXT")
   except sqlite3.OperationalError:
       pass
   ```
   All three nullable TEXT; populated only when their corresponding state transition fires. Idempotent — re-runs on tables that already have the columns are no-ops.

2. **Extend `update_escalation_learning_status`** at `state_registry.py:4174` to record the timestamps + operator:
   ```python
   def update_escalation_learning_status(learning_id: int, new_status: str,
                                          operator: str = "") -> bool:
       """Brief 215 + Brief 263: flip status. Allowed:
       suggested|approved|saved|deleted. Brief 263 also records:
       - approved_at + approved_by when new_status='approved'
       - dismissed_at when new_status='deleted' (soft-reject via /dismiss)
       The 'saved' status is preserved unchanged from Brief 215."""
   ```
   - On `new_status == 'approved'`: SET `approved_at = now()`, `approved_by = operator or '<empty>'` (operator is free-form, frontend chooses; absent body keeps current created_by as the approver).
   - On `new_status == 'deleted'`: SET `dismissed_at = now()`.
   - Other statuses: just `status` + `updated_at` (existing behavior preserved).

   **Observable side-effect on the legacy `/learning/{id}/approve` endpoint** (Instruction 7 below claims those endpoints are unchanged at the API surface — clarifying here): the legacy `/learning/{id}/approve` continues to call `update_escalation_learning_status(id, "approved")` (no `operator` kwarg), so the new helper will record `approved_at = now()` but `approved_by = ''`. That's intentional — every approval gets the audit timestamp regardless of which endpoint triggered it; the legacy path simply leaves the operator field empty because it has no body to extract one from. No breaking change to the legacy response shape; no breaking change to any caller that doesn't read `approved_at` / `approved_by`. If preserving byte-identical DB writes for the legacy path matters, the legacy handler can be changed to call `state_registry._raw_update_status(id, "approved")` instead — out of scope for Brief 263; flagged for follow-up if Calvin objects.

3. **New helper `create_pending_learning`** in `state_registry.py` adjacent to `save_escalation_learning`:
   ```python
   def create_pending_learning(conversation_id: str, channel: str,
                                source_question: str, suggested_text: str,
                                created_by: str = None) -> int:
       """Brief 263: create a NEW learning in status='suggested' (pending
       per issue #32 vocabulary). Default insert path for the operator-
       approval flow. Distinct from save_escalation_learning which
       defaults to status='approved' (the legacy auto-learn path)."""
       return save_escalation_learning(
           conversation_id=conversation_id,
           channel=channel,
           source_question=source_question,
           human_answer=suggested_text,
           status="suggested",
           ai_may_use=False,  # not Agent-usable until approved
           category=None,
           created_by=created_by,
       )
   ```
   Note: `ai_may_use_automatically` is set to False on creation. Approval can flip it to True via a future explicit op; for now Brief 263 leaves that to the existing `update_escalation_learning_status` semantics (status='approved' alone is sufficient per `get_approved_learnings_for_prompt`).

4. **New helper `edit_escalation_learning_text`** in `state_registry.py`:
   ```python
   def edit_escalation_learning_text(learning_id: int, new_text: str) -> bool:
       """Brief 263: edit the human_answer text. Allowed only when the
       row's current status is 'suggested' (pending). Returns False if
       the row doesn't exist or if status is approved/saved/deleted -
       i.e., once a learning is approved, the text is frozen (operator
       must dismiss and create a new one to change it)."""
   ```
   SELECT status, return False if not 'suggested', else UPDATE human_answer + updated_at.

5. **New helpers `_learning_status_external_to_internal` + `_learning_status_internal_to_external` + `_learning_row_to_external_shape`** in `dashboard/api.py` (near the existing `/learning` endpoint block at line 419):
   - Internal-to-external status mapping:
     - `suggested` → `pending`
     - `approved` → `approved`
     - `deleted` → `dismissed`
     - `saved` → `saved` (preserve the Brief 215 distinction; frontend sees both `approved` and `saved` but treats both as "approved" in the operator-UX sense per the existing prompt-path filter)
   - External-to-internal (for filtering on GET):
     - `pending` → `suggested`
     - `approved` → `approved` (returns both `approved` and `saved` rows when filter is `approved` — matches the prompt-path filter)
     - `dismissed` → `deleted`
   - Row reshape (existing camelCase Brief 215 shape → Calvin's spec shape):
     ```python
     {
         "id": str(row["id"]),
         "escalationId": row["conversationId"],  # nearest existing field
         "status": <internal-to-external>,
         "suggestedText": row["humanAnswer"],
         "approvedText": row["humanAnswer"] if status in ("approved","saved") else None,
         "createdAt": row["createdAt"],
         "updatedAt": row["updatedAt"],
         "approvedAt": row.get("approvedAt"),    # NEW Brief 263 column
         "dismissedAt": row.get("dismissedAt"),  # NEW Brief 263 column
         "operator": row.get("approvedBy") or row["createdBy"],
     }
     ```
   `list_escalation_learnings` must be extended to SELECT and return the new `approvedAt` / `dismissedAt` / `approvedBy` fields. Existing `humanAnswer` / `conversationId` / etc. preserved unchanged for the legacy `/learning` endpoint.

6. **New endpoints in `dashboard/api.py`** under the `/escalation-learnings/*` and `/escalations/{id}/suggest-learning` paths. Place adjacent to the existing `/learning` block at line 419:
   ```python
   @router.get("/escalation-learnings", dependencies=[Depends(_check_auth)])
   async def list_escalation_learnings_endpoint(status: str = None):
       """Brief 263: alias of /learning with Calvin's #32 status terms
       (pending/approved/dismissed) and reshaped response per #32 spec."""
       internal_status = _learning_status_external_to_internal(status) if status else None
       rows = state_registry.list_escalation_learnings(status=internal_status)
       return [_learning_row_to_external_shape(r) for r in rows]
   ```
   ```python
   class SuggestLearningRequest(BaseModel):
       suggestedText: str
       sourceQuestion: str = ""
       channel: str = ""           # optional override if escalation_id is non-numeric or row missing
       operator: str = ""

   @router.post("/escalations/{escalation_id}/suggest-learning",
                 dependencies=[Depends(_check_auth)])
   async def suggest_learning_for_escalation(escalation_id: str, req: SuggestLearningRequest):
       """Brief 263: operator creates a NEW pending learning suggestion
       for an escalation. Resolution rule for conversation_id + channel:
       1. If `escalation_id` parses as int AND a pending_notifications row
          exists with that id: SELECT customer_id + channel from that row
          (table schema at state_registry.py:292 - columns id, customer_id,
          channel, etc.). conversation_id := customer_id from that row.
       2. Otherwise (non-numeric escalation_id OR no matching row):
          conversation_id := escalation_id (treat the path param as a
          raw conversation key); channel := req.channel (must be non-empty
          in this branch, else HTTP 400 "channel required when escalation
          row not found").
       This dual-mode resolution lets operators suggest a learning either
       (a) tied to a real escalation row (the common case, frontend sends
       the numeric id from /escalations) or (b) ad-hoc on a conversation
       that isn't currently escalated."""
       conversation_id = ""
       channel = ""
       try:
           esc_id_int = int(escalation_id)
       except ValueError:
           esc_id_int = None
       if esc_id_int is not None:
           conn = state_registry._get_conn()
           row = conn.execute(
               "SELECT customer_id, channel FROM pending_notifications WHERE id = ?",
               (esc_id_int,)).fetchone()
           conn.close()
           if row:
               conversation_id = row[0]
               channel = row[1]
       if not conversation_id:
           # Fallback: use the path param as the conversation key + body channel
           conversation_id = escalation_id
           channel = req.channel
           if not channel:
               raise HTTPException(status_code=400,
                                    detail="channel required when escalation row not found")
       row_id = state_registry.create_pending_learning(
           conversation_id=conversation_id,
           channel=channel,
           source_question=req.sourceQuestion,
           suggested_text=req.suggestedText,
           created_by=req.operator or None,
       )
       # Re-fetch the row + reshape for response
       rows = state_registry.list_escalation_learnings(status="suggested")
       row_dict = next((r for r in rows if r["id"] == row_id), None)
       if not row_dict:
           raise HTTPException(status_code=500,
                                detail="learning created but not retrievable")
       return _learning_row_to_external_shape(row_dict)
   ```
   ```python
   class PatchLearningRequest(BaseModel):
       suggestedText: str

   @router.patch("/escalation-learnings/{learning_id}",
                 dependencies=[Depends(_check_auth)])
   async def patch_learning(learning_id: int, req: PatchLearningRequest):
       """Brief 263: edit the suggested text before approval. Allowed
       only when status='suggested'. Returns 409 Conflict if the row
       has already been approved/dismissed."""
       ok = state_registry.edit_escalation_learning_text(learning_id, req.suggestedText)
       if not ok:
           raise HTTPException(status_code=409,
                                detail="Learning not editable (approved or dismissed)")
       # Re-fetch the row and reshape
       ...
   ```
   ```python
   class ApproveLearningRequest(BaseModel):
       operator: str = ""

   @router.post("/escalation-learnings/{learning_id}/approve",
                 dependencies=[Depends(_check_auth)])
   async def approve_learning_v2(learning_id: int, req: ApproveLearningRequest = ApproveLearningRequest()):
       """Brief 263: approve a pending learning. Records approved_at +
       approved_by audit fields. Sets ai_may_use_automatically=True so
       the prompt path picks up the row."""
       ok = state_registry.update_escalation_learning_status(
           learning_id, "approved", operator=req.operator)
       if not ok:
           raise HTTPException(status_code=404, detail="Learning not found")
       ...
   ```
   ```python
   @router.post("/escalation-learnings/{learning_id}/dismiss",
                 dependencies=[Depends(_check_auth)])
   async def dismiss_learning(learning_id: int):
       """Brief 263: soft-reject a pending learning. Sets status='deleted'
       (soft) + dismissed_at. Row stays in the table for audit but is
       filtered out everywhere status!='deleted' is checked."""
       ok = state_registry.update_escalation_learning_status(
           learning_id, "deleted")
       if not ok:
           raise HTTPException(status_code=404, detail="Learning not found")
       ...
   ```

7. **Preserve existing `/learning/*` endpoints** at `api.py:419-445` UNCHANGED. They continue to serve the Brief 215 surface. Brief 263 is purely additive at the API layer.

8. **`get_approved_learnings_for_prompt`** at `state_registry.py:4220` UNCHANGED. The filter `status IN ('approved', 'saved') AND ai_may_use_automatically = 1` correctly excludes `suggested` (pending) and `deleted` (dismissed) rows, so the prompt path never picks up unapproved learnings — exactly Calvin's spec rule 7.

## Tests

Append 6 tests to `wtyj/tests/social/test_215_escalation_learning.py` (canonical per-module file; Brief 215 named it). All tests are real TestClient round-trips.

1. **test_brief_263_suggest_learning_creates_pending_row** — POST `/escalations/123/suggest-learning` with body `{"suggestedText": "Bakery hours are 7-19 Mon-Sat", "channel": "whatsapp", "operator": "calvin"}`. Assert 200 + response `status="pending"` + `id` returned as string. Then GET `/escalation-learnings?status=pending` and assert the row appears with the expected suggestedText.

2. **test_brief_263_patch_edits_pending_text** — create a pending row via the helper. PATCH `/escalation-learnings/{id}` with `{"suggestedText": "Bakery hours are 7-20 Mon-Sat"}`. Assert 200 + response carries the updated text. GET round-trip confirms persistence.

3. **test_brief_263_patch_rejects_approved_row** — create + approve a learning. PATCH the (now-approved) row → assert 409 Conflict with the "not editable" detail. GET confirms the approved text didn't change.

4. **test_brief_263_approve_records_approved_at_and_operator** — POST `/escalation-learnings/{id}/approve` with `{"operator": "calvin"}`. Assert 200 + response has `approvedAt` non-null AND `operator="calvin"`. Direct SQL inspection confirms `approved_at` + `approved_by` columns populated.

5. **test_brief_263_dismiss_records_dismissed_at_and_excludes_from_prompt** — create + approve a learning, then dismiss it via `/escalation-learnings/{id}/dismiss`. Assert 200 + response `status="dismissed"` + `dismissedAt` non-null. Then call `get_approved_learnings_for_prompt(channel)` and assert the dismissed row is NOT returned (load-bearing — proves Calvin's rule 7).

6. **test_brief_263_legacy_learning_endpoints_unchanged** — POST to legacy `/learning/{id}/approve` (Brief 215 path) and GET `/learning` (Brief 215 shape with `humanAnswer` / `conversationId` / etc.). Assert both work unchanged. The Brief 215 contract is preserved for any existing dashboard caller that reads the legacy shape.

## Success Condition

After Brief 263 deploys:
- `GET /api/{tenant}/dashboard/api/escalation-learnings?status=pending` returns operator-pending learnings with the spec-shaped JSON (id as string, escalationId, status, suggestedText, approvedText, approvedAt, dismissedAt, operator).
- `POST /api/{tenant}/dashboard/api/escalations/{id}/suggest-learning` creates a new pending row from the body's suggestedText.
- `PATCH /api/{tenant}/dashboard/api/escalation-learnings/{id}` edits the text while status=pending; rejects with 409 once status=approved or dismissed.
- `POST /api/{tenant}/dashboard/api/escalation-learnings/{id}/approve` records approved_at + approved_by; subsequent `get_approved_learnings_for_prompt` returns the row.
- `POST /api/{tenant}/dashboard/api/escalation-learnings/{id}/dismiss` records dismissed_at; `get_approved_learnings_for_prompt` does NOT return the row.
- Existing `/learning/*` endpoints continue to work with the Brief 215 shape — no breaking change.
- All 4 production containers healthy post-deploy.
- Frontend contract for SR documented in OUTPUT.

## Rollback

```
ssh root@108.61.192.52 "bash /root/wtyj/scripts/rollback.sh all"
```

Canonical rollback per `wtyj/briefs/infra.md:188`. Schema migration is additive (idempotent ALTER TABLE ADD COLUMN); the new columns survive a rollback on disk but are unused by the rolled-back code — harmless. The new endpoints 404 after rollback; the legacy `/learning/*` endpoints (Brief 215) remain functional. No data loss possible.
