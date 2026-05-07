# BRIEF 215 — Operator-answer-as-approved-learning + /learning approve/save endpoints
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/tests/social/test_215_escalation_learning.py`, `wtyj/tests/social/test_212_dashboard_endpoint_polish.py` (the existing /learning alias test, which Brief 215 deliberately breaks the contract of and updates) | **Depends on:** Brief 210 (`/reply` email branch), Brief 212 (`/learning` alias from content_learnings — superseded), Brief 213 (mode column), Brief 214 (`/guidance` endpoint) | **Blocks:** Marina-uses-approved-learnings (separate later brief — read+inject half), but the storage + frontend approve/save UX works end-to-end after this

## Context

SR's product contract (Section 3) says every operator answer in either soft or hard escalation should be auto-stored as an approved learning entry, default `status="approved"` and `aiMayUseAutomatically=true`, so Marina can use it next time someone asks the same question. The frontend already calls these endpoints and falls back gracefully when they 404:

- `GET /learning` — list learning entries with a `status` field per row (`"none" | "suggested" | "approved" | "saved"`). SR's mapper is `unboks-org/unboks-dashboard-api/.../lib/api.ts:430-444`.
- `POST /learning/:id/approve` — flip status to "approved".
- `POST /learning/:id/save` — flip status to "saved" (permanent).
- `DELETE /learning/:id` — remove an entry.

Today the backend has `/learning` aliased (Brief 212) to `/learnings` which serves `content_learnings` rows. That table has a different domain (it's for content_agent's blog/post draft rules — `rule TEXT`, `source_draft_ids`) and a different shape (no `status`, no `human_answer`, no `conversation_id`). The two domains have been conflated by accident; Brief 215 splits them cleanly.

Field-shape SR's frontend expects per row (from `LearningEntry` interface at `lib/api.ts:130-140` plus the contract Section 3):
```
{ id, clientSlug?, conversationId, sourceQuestion, humanAnswer, category?,
  status: "none" | "suggested" | "approved" | "saved",
  aiMayUseAutomatically: bool, createdBy?, createdAt, updatedAt }
```

Plus SR's resolve endpoint contract (Section 2 of his contract, Brief 213's `/resolve` stub still ignores body params):
```
POST /escalations/:id/resolve
Body: { resolutionNote?, saveAsLearning?, autoUseNextTime?, category? }
```
When `saveAsLearning: true`, a learning entry should be created from the operator's last interaction.

The Marina-actually-uses-the-approved-learnings half (read + inject into Marina's prompt at reply time) is **deferred to a later brief** so this brief stays bounded. Brief 215 is the storage + endpoints + auto-creation half; entries will accumulate, operator can approve/save/delete them, but Marina won't yet read them when generating new replies. That's a deliberate scope split — the Marina prompt-injection half touches `marina_agent._build_system_prompt` which is the most sensitive code in the project and warrants its own brief with focused review.

## Why This Approach

- **New table `escalation_learnings`, NOT extending `content_learnings`.** Two unrelated domains were conflated. `content_learnings` is content_agent territory (blog/post drafts have different shape: a single `rule` string, no per-customer context, no status workflow). `escalation_learnings` needs `conversation_id`, `source_question`, `human_answer`, `status`, `ai_may_use_automatically`, `category`. Sharing the table means awkward NULLable columns on every existing row and SQL queries that have to filter "domain". Cleaner: separate table. The runtime cost of a second table is zero.
- **Repoint `/learning` (singular) at the new table.** Brief 212 made `/learning` an alias for `/learnings` (content_learnings) under the assumption there was one learning concept. SR's contract makes clear there are two. After Brief 215: `/learning` (singular) → `escalation_learnings`; `/learnings` (plural) → `content_learnings` (unchanged for content_agent backward compat, used internally only). Brief 212's test that asserted `/learning == /learnings` payload no longer holds — update that test to assert /learning returns escalation_learnings shape (or remove the equality assertion).
- **Hook auto-creation at four call sites: /reply WhatsApp + /reply email + /guidance WhatsApp + /guidance email.** All four already have a "successful send" point where status flips to `replied`. Add one helper call (`save_escalation_learning(...)`) at each, after the send succeeds and status flip. If the helper raises, log + continue — never block the customer reply on a learning-write failure (best-effort durability).
- **`source_question` is the latest customer-role message in the conversation; `human_answer` is `req.text` (operator's text).** Per SR's contract: "If operator replies to Marina in soft escalation, that GUIDANCE is approved learning. If operator replies directly to customer in hard escalation, that ANSWER is approved learning." Both are the operator's text → both are `req.text`. The customer's question is the most recent message in their channel before the operator wrote — extract via `wa_get_history(customer_id, limit=5)` for whatsapp/dm, or via `email_get_conversation(thread_key).messages` for email; pick the latest `role="user"` (or `"customer"`) entry's text. If none found, fall back to empty string — frontend tolerates empty `sourceQuestion` (it just won't show a question header on the row).
- **Default status="approved" + ai_may_use_automatically=true.** Per SR's contract Section 3: "If a human operator answers an escalation, that answer is valuable. It should improve Marina for next time. Default: status = approved, aiMayUseAutomatically = true."
- **`/resolve` accepts body params optionally.** Brief 213's `/resolve` handler today ignores body. Update it to accept `ResolveRequest` body with optional `saveAsLearning`, `autoUseNextTime`, `category`, `resolutionNote`. When `saveAsLearning=True`, create a learning row by lifting `source_question` + `human_answer` from the most recent operator+customer turn pair. When false (or omitted), just mark resolved (current behavior).
- **Rejected: store learning rows on the existing `pending_notifications` table** as a denormalized field. Tempting (one fewer table) but the lifecycle is different — escalations resolve and disappear from the active list; learning entries persist as a corpus. Different cardinalities and different access patterns.
- **Rejected: implement Marina-reads-approved-learnings in this brief.** Adding a `_format_approved_learnings()` block to `marina_agent._build_system_prompt` would extend an already-long prompt and changes the most sensitive code in the project. Both the brief size and the risk surface argue for splitting. Brief 215 ships storage; a follow-up brief ships read+inject after we have a corpus to read from.
- **Rejected: bundle DM (IG/FB) auto-creation in this brief.** /reply and /guidance currently 400 / 501 on DM channels. There's no operator-answered DM event yet to learn from. Adding the hook costs nothing for now but tests would have nothing meaningful to assert. Defer until DM channels actually get an operator-reply path.

## Instructions

### Step 1 — New `escalation_learnings` table in `wtyj/shared/state_registry.py`

Add a new `CREATE TABLE IF NOT EXISTS escalation_learnings` block inside `_get_conn()`. Place it adjacent to the existing `content_learnings` CREATE at line ~304 so the two are visually paired:

```python
# Brief 215: escalation-derived learning entries (operator answers stored
# as approved knowledge for Marina to reuse in future similar replies).
# Distinct from content_learnings (content_agent's draft rules).
conn.execute(
    "CREATE TABLE IF NOT EXISTS escalation_learnings ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "conversation_id TEXT NOT NULL, "
    "channel TEXT NOT NULL, "
    "source_question TEXT NOT NULL DEFAULT '', "
    "human_answer TEXT NOT NULL, "
    "status TEXT NOT NULL DEFAULT 'approved', "
    "ai_may_use_automatically INTEGER NOT NULL DEFAULT 1, "
    "category TEXT, "
    "created_by TEXT, "
    "created_at TEXT NOT NULL, "
    "updated_at TEXT NOT NULL"
    ")"
)
```

### Step 2 — Helpers in `wtyj/shared/state_registry.py`

Add five helpers in a new section after the existing `deactivate_learning` (around line 2260):

```python
# ── Brief 215: Escalation learnings (operator answers as approved knowledge) ──

def save_escalation_learning(conversation_id: str, channel: str,
                              source_question: str, human_answer: str,
                              status: str = "approved",
                              ai_may_use: bool = True,
                              category: str = None,
                              created_by: str = None) -> int:
    """Brief 215: persist an operator answer as an approved learning entry.
    Default status='approved' + ai_may_use=True per SR's contract Section 3.
    Returns the new row id."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO escalation_learnings "
        "(conversation_id, channel, source_question, human_answer, status, "
        "ai_may_use_automatically, category, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (conversation_id, channel, source_question or "", human_answer,
         status, 1 if ai_may_use else 0, category, created_by, now, now))
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def list_escalation_learnings(status: str = None) -> list:
    """Brief 215: return escalation learning entries newest-first.
    Skip rows with status='deleted'. Optional status filter."""
    conn = _get_conn()
    if status:
        rows = conn.execute(
            "SELECT id, conversation_id, channel, source_question, human_answer, "
            "status, ai_may_use_automatically, category, created_by, "
            "created_at, updated_at FROM escalation_learnings "
            "WHERE status = ? ORDER BY created_at DESC",
            (status,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, conversation_id, channel, source_question, human_answer, "
            "status, ai_may_use_automatically, category, created_by, "
            "created_at, updated_at FROM escalation_learnings "
            "WHERE status != 'deleted' ORDER BY created_at DESC").fetchall()
    conn.close()
    return [{
        "id": r[0], "conversationId": r[1], "channel": r[2],
        "sourceQuestion": r[3], "humanAnswer": r[4],
        "status": r[5], "aiMayUseAutomatically": bool(r[6]),
        "category": r[7], "createdBy": r[8],
        "createdAt": r[9], "updatedAt": r[10],
    } for r in rows]


def update_escalation_learning_status(learning_id: int, new_status: str) -> bool:
    """Brief 215: flip status. Allowed: suggested|approved|saved|deleted."""
    if new_status not in ("suggested", "approved", "saved", "deleted"):
        return False
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE escalation_learnings SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, now, learning_id))
    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def delete_escalation_learning(learning_id: int) -> bool:
    """Brief 215: hard-delete an escalation learning row. Mirrors the
    existing delete_escalation pattern (operator-controlled removal)."""
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM escalation_learnings WHERE id = ?", (learning_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def _last_customer_message_for(conversation_id: str, channel: str) -> str:
    """Brief 215: look up the most recent customer-role message text for
    this conversation, used as `source_question` when auto-creating a
    learning entry from an operator answer. Returns '' on miss."""
    if not conversation_id:
        return ""
    if channel == "email":
        thread_key = _find_email_thread_key_for(conversation_id)
        if not thread_key:
            return ""
        conv = email_get_conversation(thread_key)
        for m in reversed(conv.get("messages", []) or []):
            if m.get("role") in ("user", "customer"):
                return (m.get("text") or m.get("body") or "")[:1000]
        return ""
    # whatsapp / dm path
    history = wa_get_full_history(conversation_id, limit=10)
    for m in reversed(history):
        if m.get("role") == "user":
            return (m.get("text") or "")[:1000]
    return ""
```

### Step 3 — Auto-creation hook in `/reply` and `/guidance` (4 call sites)

In `wtyj/dashboard/api.py`, after each successful send + `update_notification_status(escalation_id, "replied")` call, add a try/except that calls `save_escalation_learning`. Wrap in try/except so a learning-write failure NEVER blocks the operator reply.

The four sites:

(a) `/reply` WhatsApp branch (around line 1340-1342, after `update_notification_status(escalation_id, "replied")`):
```python
try:
    state_registry.save_escalation_learning(
        conversation_id=customer_id, channel="whatsapp",
        source_question=state_registry._last_customer_message_for(customer_id, "whatsapp"),
        human_answer=req.text,
        status="approved", ai_may_use=True)
except Exception as _learn_exc:
    bm_logger.log("learning_write_failed", error=str(_learn_exc)[:120],
                  escalation_id=escalation_id, source="reply_whatsapp")
```

(b) `/reply` email branch (around line 1372-1374, after `update_notification_status`):
```python
try:
    state_registry.save_escalation_learning(
        conversation_id=customer_id, channel="email",
        source_question=state_registry._last_customer_message_for(customer_id, "email"),
        human_answer=req.text,
        status="approved", ai_may_use=True)
except Exception as _learn_exc:
    bm_logger.log("learning_write_failed", error=str(_learn_exc)[:120],
                  escalation_id=escalation_id, source="reply_email")
```

(c) `/guidance` WhatsApp branch (after `update_notification_status` — Brief 214 set this at the bottom of the WhatsApp branch):
```python
try:
    state_registry.save_escalation_learning(
        conversation_id=customer_id, channel="whatsapp",
        source_question=state_registry._last_customer_message_for(customer_id, "whatsapp"),
        human_answer=req.text,
        status="approved", ai_may_use=True)
except Exception as _learn_exc:
    bm_logger.log("learning_write_failed", error=str(_learn_exc)[:120],
                  escalation_id=escalation_id, source="guidance_whatsapp")
```

(d) `/guidance` email branch (after `update_notification_status` — Brief 214):
```python
try:
    state_registry.save_escalation_learning(
        conversation_id=customer_id, channel="email",
        source_question=state_registry._last_customer_message_for(customer_id, "email"),
        human_answer=req.text,
        status="approved", ai_may_use=True)
except Exception as _learn_exc:
    bm_logger.log("learning_write_failed", error=str(_learn_exc)[:120],
                  escalation_id=escalation_id, source="guidance_email")
```

### Step 4 — Repoint `/learning` (singular) at the new table

Replace the Brief 212 `/learning` GET alias at `wtyj/dashboard/api.py:418-420`:

```python
# Brief 215: /learning is now the SR-domain endpoint backed by
# escalation_learnings. /learnings (plural) still serves content_learnings
# for content_agent backward compat.
@router.get("/learning", dependencies=[Depends(_check_auth)])
async def list_escalation_learning_endpoint(status: str = None):
    return state_registry.list_escalation_learnings(status=status)
```

Replace the DELETE alias at `:423-428`:

```python
@router.delete("/learning/{learning_id}", dependencies=[Depends(_check_auth)])
async def delete_escalation_learning_endpoint(learning_id: int):
    ok = state_registry.delete_escalation_learning(learning_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Learning not found")
    return {"ok": True}
```

### Step 5 — POST /learning/:id/approve and /save

Insert after the new DELETE handler:

```python
@router.post("/learning/{learning_id}/approve", dependencies=[Depends(_check_auth)])
async def approve_learning(learning_id: int):
    ok = state_registry.update_escalation_learning_status(learning_id, "approved")
    if not ok:
        raise HTTPException(status_code=404, detail="Learning not found")
    return {"ok": True, "id": learning_id, "status": "approved"}


@router.post("/learning/{learning_id}/save", dependencies=[Depends(_check_auth)])
async def save_learning(learning_id: int):
    ok = state_registry.update_escalation_learning_status(learning_id, "saved")
    if not ok:
        raise HTTPException(status_code=404, detail="Learning not found")
    return {"ok": True, "id": learning_id, "status": "saved"}
```

### Step 6 — `/resolve` accepts body params

Replace the existing `resolve_escalation` handler at `wtyj/dashboard/api.py:1019-1027` (the Brief 213-era stub):

```python
class ResolveRequest(BaseModel):
    resolutionNote: str = ""
    saveAsLearning: bool = False
    autoUseNextTime: bool = True
    category: str = ""


@router.post("/escalations/{escalation_id}/resolve", dependencies=[Depends(_check_auth)])
async def resolve_escalation(escalation_id: int, req: ResolveRequest = None):
    """Brief 213 + 215: mark an escalation resolved. Optionally save the
    operator's resolutionNote as an approved learning entry."""
    ok = state_registry.update_notification_status(escalation_id, "resolved")
    if not ok:
        raise HTTPException(status_code=404, detail="Escalation not found")
    state_registry.resolve_conversation_from_escalation(escalation_id)

    body = req or ResolveRequest()
    learning_entry_id = None
    if body.saveAsLearning and body.resolutionNote.strip():
        # Look up the conversation context to fill source_question
        esc = next((e for e in state_registry.get_all_escalations()
                    if e["id"] == escalation_id), None)
        if esc:
            try:
                learning_entry_id = state_registry.save_escalation_learning(
                    conversation_id=esc["customer_id"],
                    channel=esc.get("channel", "whatsapp"),
                    source_question=state_registry._last_customer_message_for(
                        esc["customer_id"], esc.get("channel", "whatsapp")),
                    human_answer=body.resolutionNote.strip(),
                    status="approved",
                    ai_may_use=body.autoUseNextTime,
                    category=body.category or None)
            except Exception as _learn_exc:
                bm_logger.log("learning_write_failed", error=str(_learn_exc)[:120],
                              escalation_id=escalation_id, source="resolve")
    return {"ok": True, "learningEntryId": learning_entry_id}
```

### Step 7 — Update Brief 212's `/learning` alias test

`wtyj/tests/social/test_212_dashboard_endpoint_polish.py::test_learning_singular_alias_get_returns_same_as_plural` asserts equality between `/learning` and `/learnings`. After Brief 215 they serve different domains. Replace the test's body to assert that `/learning` now returns the escalation_learnings shape (`status` field present) and that `/learnings` still returns content_learnings (unchanged). Keep the test name the same so test counts line up.

Likewise `test_learning_singular_alias_delete_works` deletes via the singular path expecting the content_learnings row to deactivate. After Brief 215, `DELETE /learning/:id` operates on `escalation_learnings`. Update the test: seed an escalation_learning row, DELETE via the singular path, assert the row is gone via `list_escalation_learnings`.

## Tests (10)

In new file `wtyj/tests/social/test_215_escalation_learning.py`. Use TestClient + real state_registry + cleanup helpers (mirror `test_213` and `test_214` patterns).

1. **`test_save_escalation_learning_round_trip`** — call `save_escalation_learning(...)`, then `list_escalation_learnings()`, assert the row is present with the exact fields.
2. **`test_update_escalation_learning_status_invalid_value_returns_false`** — call with `new_status="garbage"`, assert returns False, row unchanged.
3. **`test_get_learning_returns_escalation_learnings_with_status_field`** — seed an escalation learning, GET `/learning`, assert response is a list and the row has a `status` field equal to "approved".
4. **`test_post_learning_approve_flips_status`** — seed with status="suggested", POST `/learning/:id/approve`, assert 200 + DB row status is "approved".
5. **`test_post_learning_save_flips_status`** — POST `/learning/:id/save`, assert 200 + DB row status is "saved".
6. **`test_delete_learning_removes_row`** — seed, DELETE `/learning/:id`, assert 200 + row is no longer in list.
7. **`test_reply_whatsapp_creates_approved_learning`** — seed escalation, POST `/reply` (mock send_whatsapp_message + marina_agent), assert one new row in `escalation_learnings` with status="approved", channel="whatsapp", `humanAnswer` matches operator's text.
8. **`test_guidance_email_creates_approved_learning`** — seed soft-mode email escalation, POST `/guidance` with mocks, assert one new row with channel="email", `humanAnswer == operator's coaching text`.
9. **`test_resolve_with_save_as_learning_creates_row`** — POST `/resolve` with `{saveAsLearning:true, resolutionNote:"set expectations clearly", category:"complaint"}`, assert response includes `learningEntryId`, DB row exists with that note + category.
10. **`test_resolve_without_save_as_learning_creates_no_row`** — POST `/resolve` with `{}`, assert escalation marked resolved, NO new learning row was added.

Plus the two pre-existing Brief 212 tests in `test_212_dashboard_endpoint_polish.py` get updated as part of Step 7 (count stays the same — neither added nor removed).

Baseline: 972 (Brief 214). Target: 982 passing / 0 failures.

## Success Condition

After deploy:
1. Operator sends a hard-mode reply via `/reply` → backend writes a new row to `escalation_learnings` with status="approved", visible immediately in `GET /learning`.
2. Operator sends a soft-mode `/guidance` → same row creation.
3. Operator clicks "Approve" or "Save permanently" on a learning entry in the dashboard → backend `POST /learning/:id/approve` or `/save` succeeds and the row's status flips.
4. Operator clicks "Resolve" with the "save this as a learning" checkbox → backend creates the learning row + marks resolved.
5. Live verification (post-deploy):
   ```bash
   ssh root@108.61.192.52 'docker exec wtyj-unboks python3 -c "
   from shared import state_registry
   rows = state_registry.list_escalation_learnings()
   print(\"escalation_learnings count:\", len(rows))
   if rows:
       r = rows[0]
       print(\"  first row keys:\", sorted(r.keys()))
       print(\"  status:\", r.get(\"status\"), \"ai_may_use:\", r.get(\"aiMayUseAutomatically\"))
   "'
   ```

## Rollback

`git revert <commit>`, push, canary redeploys. The new `escalation_learnings` table is NOT dropped by revert (SQLite ALTER TABLE DROP is destructive); rows simply become unreferenced — no data corruption. The `/learning` endpoint reverts to its Brief 212 alias behavior (returns content_learnings rows again). Frontend's NOT_CONNECTED_STATUSES set handles the brief disruption with the calm "will be connected" notice while the revert is in flight.

The only data-loss-risk path: `DELETE /learning/:id` after revert would target content_learnings (Brief 212 behavior), so a frontend trying to delete an escalation-learning row would silently delete a content_learning row instead. Mitigation: don't revert mid-day; revert during off-hours; tell SR to pause the dashboard during the window.
