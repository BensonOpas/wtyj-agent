# BRIEF 212 — Dashboard endpoint polish: /learning aliases, /schedule/slots body shape, /ai-editor proxy
**Status:** Draft | **Files:** `wtyj/dashboard/api.py`, `wtyj/tests/social/test_212_dashboard_endpoint_polish.py` | **Depends on:** Brief 211 (composer-render contract) | **Blocks:** SR's AI Editor button (translate/style/fix in the reply composer) returning a real result instead of "AI Editor not available"

## Context

Three small contract gaps caught during the dashboard E2E. None of them block the visible reply UX (Brief 211 closed that), but each silently degrades a frontend feature that SR shipped:

**Gap A — Learning entries: path mismatch.** SR's frontend at `unboks-org/unboks-dashboard-api/.../lib/api.ts:430-444` calls:
```ts
GET    /learning?status=...    fetchLearningEntries
DELETE /learning/:id           deleteLearningEntry
```
My backend serves the plural path: `GET /learnings` (`wtyj/dashboard/api.py:394`) and `DELETE /learnings/:id` (line 405). Frontend gets 404, falls through to its empty-list fallback, learning entries never render.

The two `POST /learning/:id/approve` and `POST /learning/:id/save` endpoints SR also calls are deliberately **out of scope for Brief 212** — those aren't aliases, they're new features that need backing storage and a clear semantic for "approve" vs "save" that I do not have without further conversation. Defer to Tier 2.

**Gap B — Schedule slots: body shape mismatch.** SR's frontend at `lib/api.ts:471-476`:
```ts
saveScheduleSlots(slots: ScheduleSlot[]) → PUT /schedule/slots, body = JSON.stringify(slots)
```
My backend's PUT handler at `wtyj/dashboard/api.py:747-750` expects a Pydantic body of shape `{slots: [...]}` (model `ScheduleSlotsRequest`). FastAPI returns 422 when SR posts the raw array. Method matches; only the wrapper differs.

**Gap C — AI Editor: missing entirely.** SR's reply composer has an AI Editor panel (Translate / Style / Fix tabs) at `unboks-org/.../components/inbox/AIEditorPanel.tsx`. The button calls `POST /ai-editor` with payload from `lib/api.ts:407-417`:
```ts
{action: "translate"|"style"|"fix", text: string,
 targetLanguage?: "English"|"Dutch"|"Spanish"|"Papiamento"|"Swedish"|"Portuguese",
 style?: "professional"|"warmer"|"shorter"|"friendlier"|"direct",
 context?: {conversationId?, escalationMode?, channel?}}
→ {text: string}
```
My backend has no such route — frontend falls through to its "AI Editor not available" notice. Since the call payload is action+text only and the response is text-only, this is a thin Claude proxy: one `marina_agent`-equivalent call mapped per action, not a feature with state.

## Why This Approach

- **Aliases over rename.** Adding `@router.get("/learning")` next to the existing `@router.get("/learnings")` (and same for DELETE) is two lines of FastAPI per route, with the alias handler simply calling through to the canonical handler. Renaming `/learnings` → `/learning` would also work but breaks any existing client of the plural path. I checked: no internal callers (only SR's frontend hits these) — but cheap to keep both. Aliases also survive any future SR-side rename without coordination.
- **Schedule body shape.** Two clean options: (1) make the Pydantic model accept the raw array, (2) keep PUT signature but also accept the wrapped form. I'm taking option 1 — change the handler param from `req: ScheduleSlotsRequest` (model with `slots: list`) to `req: list = Body(...)` so FastAPI parses the raw body as a JSON array. Test 125 etc. don't call this endpoint, so no internal regression risk. Frontend matches what's been documented in TS for at least Brief 200 era.
- **AI Editor as a thin Claude proxy, not a refactor of marina_agent.** This is a tooling endpoint for operators (translate / restyle / fix grammar of THEIR draft text). It is NOT inside the Rule 1 path ("one Claude call per inbound customer message"). Operators are not customers; the input text is not from the customer; the output is sent only to the dashboard, not relayed to a customer until the operator clicks Send (which goes through `/escalations/:id/reply`, a separate path I shipped in Brief 210). So a separate Claude call here doesn't violate Rule 1.
- **Rejected: build a generic `/ai-text` endpoint that takes a free-form prompt.** Tempting (more flexible) but bad — would let any frontend feature (or compromised token) drive arbitrary Claude calls billed to our key. Constrained shape (action enum + bounded language + bounded style) is safer.
- **Rejected: route `/ai-editor` into `marina_agent.process_message`.** Marina's pipeline is built for customer conversations and threads booking-state through. Reusing it for an operator's draft-edit would mean either creating fake conversations or polluting the call signature. Cleaner to write a small dedicated `agents/ai_editor.py` (or inline) that builds an action-specific prompt and calls `anthropic.messages.create` directly.
- **Rejected: bundle `POST /learning/:id/approve` and `POST /learning/:id/save` into this brief.** Earlier audit listed them as "Tier 3 polish" but on closer inspection they are full features — `approve` writes to the learnings table with a status transition, `save` (different semantic) commits the entry permanently with operator metadata. Without a clear understanding of what SR's `learningStatus` state machine looks like backend-side, getting it wrong silently corrupts learnings data. These belong in a Tier 2 brief alongside the soft/hard mode work.

## Instructions

### Step 1 — `/learning` GET + DELETE aliases in `wtyj/dashboard/api.py`

After the existing `@router.delete("/learnings/{learning_id}")` block at line 405, add two alias decorators that delegate to the existing handlers. Keep both decorators above each respective handler so FastAPI registers both routes.

```python
# Brief 212: /learning singular aliases for SR's frontend
# (frontend calls /learning, backend has historically served /learnings)
@router.get("/learning", dependencies=[Depends(_check_auth)])
async def list_learning_alias():
    return state_registry.get_active_learnings()


@router.delete("/learning/{learning_id}", dependencies=[Depends(_check_auth)])
async def deactivate_learning_alias(learning_id: int):
    ok = state_registry.deactivate_learning(learning_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Learning not found or already inactive")
    return {"ok": True}
```

Place them right after the existing `@router.delete("/learnings/{learning_id}")` block. Do not touch the plural-path handlers.

### Step 2 — Fix PUT `/schedule/slots` body shape

Current handler at `wtyj/dashboard/api.py:747`:
```python
@router.put("/schedule/slots", dependencies=[Depends(_check_auth)])
async def update_schedule_slots(req: ScheduleSlotsRequest):
    state_registry.save_schedule_slots(req.slots)
    return {"ok": True, "slots": state_registry.get_schedule_slots()}
```

Change to accept a raw JSON array:
```python
from fastapi import Body  # already imported at top of file? check.

@router.put("/schedule/slots", dependencies=[Depends(_check_auth)])
async def update_schedule_slots(slots: list = Body(...)):
    state_registry.save_schedule_slots(slots)
    return {"ok": True, "slots": state_registry.get_schedule_slots()}
```

`Body(...)` (with ellipsis) marks the body required. The `ScheduleSlotsRequest` model at line 717 can be left in place (used elsewhere?) or deleted if unused — check via grep. Likely unused after this change.

### Step 3 — POST `/ai-editor` Claude proxy

New endpoint, near the bottom of the file (after the existing `/messages/suggest-reply` at line 1045, before the escalation-reply handler at 1163, in the same general area as other dashboard-ops endpoints).

```python
# Brief 212: AI Editor proxy for SR's reply composer
# Operator-facing tool — translate, restyle, or fix grammar of an
# operator's draft. NOT in the customer reply path (Rule 1 protected
# customer-message Claude calls; this is operator-message tooling).

class AIEditorRequest(BaseModel):
    action: str  # "translate" | "style" | "fix"
    text: str
    targetLanguage: str = ""  # required for "translate"
    style: str = ""  # required for "style"
    context: dict = {}  # optional metadata: conversationId, escalationMode, channel


_AI_EDITOR_VALID_ACTIONS = {"translate", "style", "fix"}
_AI_EDITOR_VALID_LANGUAGES = {"English", "Dutch", "Spanish", "Papiamento", "Swedish", "Portuguese"}
_AI_EDITOR_VALID_STYLES = {"professional", "warmer", "shorter", "friendlier", "direct"}


def _build_ai_editor_prompt(action: str, text: str, target_language: str, style: str) -> str:
    """Build the user-message prompt for the chosen action. Keep instructions
    crisp and tight so the model returns the rewritten text only, no preamble."""
    if action == "fix":
        return (
            "Rewrite the following text to fix any grammar, spelling, or "
            "punctuation issues. Do not change the meaning, tone, or "
            "language. Return only the rewritten text — no preamble, no "
            "quotation marks, no explanation.\n\n"
            f"Text:\n{text}"
        )
    if action == "translate":
        return (
            f"Translate the following text into {target_language}. Preserve "
            "the tone, register, and any names. Return only the translation "
            "— no preamble, no quotation marks, no explanation.\n\n"
            f"Text:\n{text}"
        )
    if action == "style":
        return (
            f"Rewrite the following text in a more {style} style. Keep the "
            "same language, factual content, and any names. Return only "
            "the rewritten text — no preamble, no quotation marks, no "
            "explanation.\n\n"
            f"Text:\n{text}"
        )
    raise ValueError(f"unknown action: {action}")


@router.post("/ai-editor", dependencies=[Depends(_check_auth)])
async def ai_editor(req: AIEditorRequest):
    """Operator-facing AI tool: translate / restyle / fix grammar on a draft.
    Brief 212. Not in the customer reply path."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    if req.action not in _AI_EDITOR_VALID_ACTIONS:
        raise HTTPException(status_code=400, detail=f"invalid action: {req.action}")
    if req.action == "translate":
        if not req.targetLanguage or req.targetLanguage not in _AI_EDITOR_VALID_LANGUAGES:
            raise HTTPException(status_code=400, detail="targetLanguage required for translate")
    if req.action == "style":
        if not req.style or req.style not in _AI_EDITOR_VALID_STYLES:
            raise HTTPException(status_code=400, detail="style required for style action")

    prompt = _build_ai_editor_prompt(req.action, req.text.strip(),
                                     req.targetLanguage, req.style)
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        rewritten = (resp.content[0].text if resp.content else "").strip()
    except Exception as exc:
        bm_logger.log("ai_editor_error", error=str(exc)[:200], action=req.action)
        raise HTTPException(status_code=500, detail=f"AI editor failed: {str(exc)[:120]}")

    if not rewritten:
        raise HTTPException(status_code=500, detail="AI editor returned empty result")

    bm_logger.log("ai_editor_used", action=req.action, length=len(req.text))
    return {"text": rewritten}
```

Notes on model choice: use `claude-sonnet-4-5` (matches model ID used elsewhere in the codebase — verify by grep). The endpoint is bounded (action enum, language enum, style enum) so user-supplied text is the only free-form input, and it's plumbed straight through.

### Step 4 — Verify imports

`anthropic` and `BaseModel` are already imported at the top of `wtyj/dashboard/api.py` (lines 12, 16). `Body` from FastAPI: confirm present in the existing `from fastapi import` line at line 14. If absent, add it.

## Tests (6)

In `wtyj/tests/social/test_212_dashboard_endpoint_polish.py`. Mirror the pattern in `test_125_escalation_reply.py` (TestClient, real state, cleanup helper).

1. **`test_learning_singular_alias_get_returns_same_as_plural`** — seed a learning via state_registry.save_learning (or whatever helper exists), GET both `/learning` and `/learnings`, assert equal.
2. **`test_learning_singular_alias_delete_works`** — seed a learning, DELETE `/learning/:id`, assert 200 + the row is no longer active. Cleanup.
3. **`test_schedule_slots_put_accepts_raw_array`** — PUT `/schedule/slots` with body `[{"day_of_week":"Tuesday","time_utc":"16:00"}]` (raw array, not wrapped), assert 200 and the slots are saved.
4. **`test_ai_editor_fix_returns_rewritten_text`** — patch `dashboard.api.anthropic`, mock Claude returns "fixed text", POST `/ai-editor` with `{action:"fix", text:"i has a draft"}`, assert 200 and response text matches the mock.
5. **`test_ai_editor_translate_requires_target_language`** — POST `/ai-editor` with `{action:"translate", text:"hello"}` (no targetLanguage), assert 400.
6. **`test_ai_editor_invalid_action_returns_400`** — POST with `action:"sing"`, assert 400.

Plus full regression: 949 baseline + 6 new = **955 passing / 0 failures**.

## Success Condition

Post-deploy, three live checks:

1. SR's frontend GET `/learning` no longer returns 404. Confirmable via curl from the VPS:
   ```bash
   ssh root@108.61.192.52 'docker exec wtyj-unboks curl -s -H "Authorization: Bearer $(cat /app/data/session_token)" http://localhost:8001/dashboard/api/learning | head -c 100'
   ```
   Expect `[]` or a JSON array, NOT `404`.

2. SR's frontend can save schedule slots without a 422.

3. SR opens an escalation in the dashboard, types a draft in the reply composer, clicks the AI Editor "Fix" tab, sees the rewritten text appear (instead of "AI Editor not available").

## Rollback

`git revert <commit>`, push, canary redeploys. All three changes are purely additive (no schema, no removed routes). Reverting restores the prior 404 / 422 behavior with zero data loss. The AI Editor endpoint specifically logs each call via `bm_logger`, so usage is audit-traceable post-revert.
