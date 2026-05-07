# BRIEF 222 — Conversation detail extras: humanTakeoverAt + learningStatus
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/tests/social/test_222_conversation_detail_fields.py` | **Depends on:** Brief 211 (`_conversation_status_fields` helper), Brief 213 (`human_takeover_at` column), Brief 215 (`escalation_learnings` table) | **Blocks:** TASK-021 Section 8 — SR's `ConversationDetail` interface fields

## Context

Brief 211 added 4 contract fields to `GET /messages/conversations/:phone` so SR's `EscalationReplyComposer` could decide what UI to render: `escalated`, `escalationResolved`, `escalationMode`, `aiMuted`. Brief 213 backed `escalationMode` + `aiMuted` with real storage (the `pending_notifications.mode` column + `conversation_status.ai_muted`/`human_takeover_at` columns).

But SR's product contract Section 8 lists more fields the frontend reads on the same endpoint, and `ConversationDetail` in `lib/api.ts:80-93` declares all of them as optional fields:

```typescript
export interface ConversationDetail {
  // ... fields covered by Brief 211 ...
  humanTakeoverAt?: string | null;
  humanGuidance?: string | null;
  humanResponder?: string | null;
  humanRespondedAt?: string | null;
  learningStatus?: LearningStatus;  // "none" | "suggested" | "approved" | "saved"
}
```

Today these all return `undefined` from our backend, so the frontend renders fall-back UI states. Two of these we have storage for already:

- `humanTakeoverAt` — Brief 213 added the `conversation_status.human_takeover_at` column when `/escalations/:id/takeover` runs. It's set, just not exposed on the conversation detail response.
- `learningStatus` — Brief 215 added the `escalation_learnings` table with statuses `suggested|approved|saved`. We can compute the per-conversation status by querying for the highest-precedence learning row.

The remaining three (`humanGuidance`, `humanResponder`, `humanRespondedAt`) need new storage and a meaningful operator-identity model — single-shared-password auth means all operators look identical today. Those land in a separate brief once the contract for "who is acting" is decided. This brief ships the two cheap ones and stubs the three harder ones as `null` so the frontend's optional-field handling stays well-defined.

## Why This Approach

**Considered:** ship all 5 fields in one brief by adding a `conversation_status.last_operator_action` JSON blob storing guidance + responder + timestamp. Rejected: that conflates three concepts (last-guidance text, last-responder identity, last-action timestamp) and locks in a shape before the operator-identity question is answered. Storage today doesn't track which operator did what; bolting a placeholder identity in here would freeze a bad model.

**Considered:** leave `humanGuidance/humanResponder/humanRespondedAt` un-set (key absent) so JSON.stringify drops them. Rejected: SR's TypeScript interface declares them with `?` which means undefined is allowed, but explicit `null` is more honest about WHY they're absent (we know about them, they're just not implemented yet). It also makes the "this field has no storage today" status visible in the API response — a future brief flipping null to a real value is a clean, observable change.

**Chosen:** extend `_conversation_status_fields()` in api.py to return all 5 new keys. Two are real (humanTakeoverAt, learningStatus); three are explicit `null` placeholders with code comments naming the follow-up. Two new state_registry helpers: `get_human_takeover_at(cid)` and `get_learning_status_for_conversation(cid)`. The `_conversation_status_fields` callers (already wired into both the WhatsApp path and the email path of `get_conversation`) automatically pick up the new fields with zero new wiring.

**learningStatus precedence:** when multiple `escalation_learnings` rows exist for the same conversation, return the highest-precedence status. Order (highest to lowest): `saved` > `approved` > `suggested` > `none`. Reasoning: `saved` is the operator explicitly promoting a learning to permanent knowledge, which is more durable than approved (auto-created on operator answer per Brief 215), which is more durable than suggested (an in-progress draft). Skip `deleted` rows — they don't represent active state.

## Instructions

### Step 1: Add `get_human_takeover_at` helper to state_registry

Insert near the existing `get_active_escalation_mode` helper (around `wtyj/shared/state_registry.py:1336-1349`):

```python
def get_human_takeover_at(conversation_id: str):
    """Brief 222: ISO timestamp of when the operator took over this
    conversation, or None if no active takeover. Reads
    conversation_status.human_takeover_at (set by /escalations/:id/takeover
    in Brief 213, cleared to NULL on /handback)."""
    if not conversation_id:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT human_takeover_at FROM conversation_status "
        "WHERE conversation_id = ?",
        (conversation_id,)).fetchone()
    conn.close()
    return row[0] if row and row[0] else None
```

### Step 2: Add `get_learning_status_for_conversation` helper to state_registry

Insert near the existing `list_escalation_learnings` helper (after the `update_escalation_learning_status` block, around `wtyj/shared/state_registry.py:2540+`):

```python
def get_learning_status_for_conversation(conversation_id: str) -> str:
    """Brief 222: the highest-precedence escalation_learning status for
    this conversation. Used by /messages/conversations/:phone to surface
    an at-a-glance learningStatus field on the conversation detail.
    Precedence: saved > approved > suggested > none. Skip deleted rows."""
    if not conversation_id:
        return "none"
    conn = _get_conn()
    rows = conn.execute(
        "SELECT status FROM escalation_learnings "
        "WHERE conversation_id = ? AND status != 'deleted'",
        (conversation_id,)).fetchall()
    conn.close()
    statuses = {r[0] for r in rows}
    for s in ("saved", "approved", "suggested"):
        if s in statuses:
            return s
    return "none"
```

### Step 3: Extend `_conversation_status_fields` in api.py

Update the helper at `wtyj/dashboard/api.py:982-994` to include 5 more fields:

```python
def _conversation_status_fields(customer_id: str) -> dict:
    """Brief 211: derive escalation-state fields the SR frontend reads on
    /messages/conversations/:phone to gate its EscalationReplyComposer.
    Brief 213: escalationMode + aiMuted now backed by real storage
    (pending_notifications.mode + conversation_status.ai_muted).
    Brief 222: humanTakeoverAt + learningStatus added (real storage);
    humanGuidance + humanResponder + humanRespondedAt return null
    placeholders pending an operator-identity model."""
    cid = customer_id or ""
    status = state_registry.get_conversation_status(cid)
    return {
        "escalated": status == "open",
        "escalationResolved": status == "resolved",
        "escalationMode": state_registry.get_active_escalation_mode(cid),
        "aiMuted": state_registry.get_ai_muted(cid),
        "humanTakeoverAt": state_registry.get_human_takeover_at(cid),
        "learningStatus": state_registry.get_learning_status_for_conversation(cid),
        # Brief 222: placeholders — no storage for these today. A later
        # brief tied to operator-identity work will populate them.
        "humanGuidance": None,
        "humanResponder": None,
        "humanRespondedAt": None,
    }
```

The two existing call sites at `api.py:1013` (email branch) and `api.py:1026` (WhatsApp/DM branch) require no change — they already do `result.update(_conversation_status_fields(...))` / `response.update(...)`.

### Step 4: Test file `wtyj/tests/social/test_222_conversation_detail_fields.py`

Mirror the test harness pattern at `wtyj/tests/social/test_211_dashboard_contract_fields.py` (login + auth helper, `TestClient` from `agents.social.webhook_server.app`).

Required tests (4):

1. **`test_get_human_takeover_at_helper_returns_none_when_unset`** — call `state_registry.get_human_takeover_at("nonexistent_conv")` → returns None. Plus call after `set_conversation_status(..., status="open")` with no takeover — still None (column defaults to NULL).
2. **`test_get_human_takeover_at_returns_iso_timestamp_when_set`** — seed via `state_registry.set_ai_muted("222_takeover_phone", True, "whatsapp")` (which Brief 213 wires to also stamp `human_takeover_at`). Then `get_human_takeover_at("222_takeover_phone")` returns a non-empty ISO string.
3. **`test_learning_status_precedence`** — seed 3 learnings on `"222_learning_phone"` with statuses `suggested`, `approved`, `saved`. Helper returns `"saved"` (highest precedence). Drop the saved row (status=deleted), helper returns `"approved"`. Drop the approved row, returns `"suggested"`. Drop all, returns `"none"`.
4. **`test_get_conversation_returns_new_contract_fields`** — full integration: seed a conversation with takeover + an approved learning, call `GET /dashboard/api/messages/conversations/222_integration_phone`, assert response has `humanTakeoverAt` non-empty string, `learningStatus == "approved"`, and `humanGuidance == None`, `humanResponder == None`, `humanRespondedAt == None`.

For all tests: clean up seeded rows in a try/finally so repeated runs don't accumulate state. Test 4 needs a `whatsapp_threads` row stored via `wa_store_message` so `get_conversation` returns a populated response.

## Tests

4 tests covering the two new helpers (Tests 1-3 are unit-level on state_registry; Test 4 is integration via the FastAPI endpoint asserting the response shape). All assertions check real return values, not source strings.

## Success Condition

`python3 -m pytest wtyj/tests/ -q` passes at **1005 / 0** (1001 baseline + 4 new). Live verification post-deploy: hit `GET /api/unboks/dashboard/api/messages/conversations/<phone>` for any conversation in the unboks tenant — response includes `humanTakeoverAt`, `learningStatus`, `humanGuidance`, `humanResponder`, `humanRespondedAt` keys (all may be null but the keys must be present).

## Rollback

`git revert <commit>` and redeploy. Restores Brief 211's 4-field response shape. Two state_registry helpers are added but unused after revert — harmless dead code that revert removes. No schema changes, no migration to undo.
