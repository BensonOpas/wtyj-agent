# BRIEF 165 — Dashboard quick wins bundle (delete endpoint + escalation reply subject + Urgent bar + stats refresh)
**Status:** Draft | **Files:** dashboard/api.py, state_registry.py, Messages.tsx, Escalations.tsx, Overview.tsx, use-bluemarlin.ts, test_165 (new) | **Depends on:** 163 | **Blocks:** —

## Context

Four independent small dashboard fixes bundled into one brief:

### Fix A — Delete conversation endpoint + trash button

Image #78 from Benson highlights trash-can icons on every Messages row. The frontend has a `useHiddenConversations` hook backed by localStorage (client-side soft hide), but the "delete" path doesn't exist — Benson noted "Atm doesnt work as teh API has no Delete endpoint". Adding `DELETE /messages/conversations/{phone}` backend + frontend trash button so operators can permanently remove test conversations from the Messages page.

### Fix B — Escalation Reply popup subject clear

Benson: "in dashboard full escalation replies, empty the subject, and add the customer email upon opening the pop up". Currently `Escalations.tsx:105` sets `subject: isSemi(...) ? "" : \`Re: ${cleanSubject(esc.subject)}\`` — semi is already empty, full prefills "Re: [...]". Benson wants both empty. Customer email (`To:` field) is already populated for full escalations via `parsed.email` at line 104.

### Fix C — Home "All clear" reflects escalations + unread too

`Overview.tsx:49-54` shows the UrgentBar "All clear — nothing needs your attention" when `drafts.length === 0`, but ignores open escalations and unread messages. Benson reported seeing "All clear" in the header while the cards show 2+ open escalations. Fix: pass `openEsc` and `unreadMsgs` to UrgentBar and only show "All clear" when all three counts are zero.

### Fix D — Social Media stats cards refresh after publish

`ContentPipeline.tsx:231-233` reads `status?.pending / approved / published` from `useStatus()`. The publish mutation at `use-bluemarlin.ts:78-85` calls `invalidate()` which invalidates `["status"]`. Should refresh automatically but Benson reported stale counts post-publish. Defensive fix: add explicit `refetchType: "all"` to the invalidation so TanStack Query force-refetches both active and inactive queries.

## Why This Approach

Bundling: all four are frontend-forward small fixes that share the same commit + deploy cycle. Separating into four briefs would triple the overhead for almost zero review benefit (no architecture changes, no cross-concern coupling). Brief-reviewer skipped for speed per Benson's "back2back" directive — test coverage provides safety.

Delete vs hide: the existing `useHiddenConversations` localStorage-only hide remains — that's a per-operator "don't show me this" affordance. The new delete is a "remove from the system" destructive action that affects everyone's view and the underlying data.

Soft-delete vs hard-delete: hard DELETE of the `whatsapp_threads` + `whatsapp_booking_state` rows. Rationale: the dashboard Messages page is not a legal archive — it's an operations view. Test pollution and old debugging threads should be fully removable. If audit trail is needed later, we can add soft-delete with a `deleted_at` column. Not now.

## Source Material

### Backend

`wtyj/dashboard/api.py:866-884` has GET conversation endpoints but no DELETE. `wtyj/shared/state_registry.py:625-632` has `wa_store_message`, line 687+ has `wa_list_conversations`. No `wa_delete_conversation` exists.

### Frontend

`Messages.tsx`:
- Existing `useHiddenConversations` (lines 19-44) — localStorage soft hide
- `ConversationRow` has buttons at lines 122-136 (Mark read/unread + EyeOff/hide)
- No trash button exists in master (Benson's screenshot showed one that doesn't exist in the pushed code)

`Escalations.tsx:95-112` — `openDetail` pre-fills `compose.subject` based on `isSemi`.

`Overview.tsx:36-100` — `UrgentBar` component takes `drafts, onOpen, loading`. Line 52 hardcodes "All clear — nothing needs your attention right now." when drafts empty.

`use-bluemarlin.ts:46-49` — `invalidate()` helper used by all draft mutations.

## Instructions

### Step 1: Backend — `wa_delete_conversation` in state_registry.py

Add after `wa_save_booking_state` (around line 685):

```python
def wa_delete_conversation(phone: str) -> int:
    """Brief 165: hard-delete all messages + booking state for a phone number.
    Returns the total number of rows deleted across all tables.
    Used by the dashboard delete-conversation endpoint — no audit trail.
    """
    conn = _get_conn()
    total = 0
    for sql in (
        "DELETE FROM whatsapp_threads WHERE phone = ?",
        "DELETE FROM whatsapp_booking_state WHERE phone = ?",
    ):
        cur = conn.execute(sql, (phone,))
        total += cur.rowcount
    conn.commit()
    conn.close()
    return total
```

### Step 2: Backend — DELETE endpoint in dashboard/api.py

After `get_conversation` (line 884):

```python
@router.delete("/messages/conversations/{phone}", dependencies=[Depends(_check_auth)])
async def delete_conversation(phone: str):
    """Brief 165: hard-delete a conversation (messages + booking state).
    Returns the count of rows deleted for operator feedback."""
    count = state_registry.wa_delete_conversation(phone)
    return {"ok": True, "deleted_rows": count, "phone": phone}
```

### Step 3: Backend — test file `wtyj/tests/social/test_165_dashboard_quick_wins.py`

```python
"""Tests for Brief 165 — dashboard quick wins bundle.

Covers:
- wa_delete_conversation helper deletes both tables
- DELETE /messages/conversations/{phone} endpoint returns deleted count
"""
import os
from unittest.mock import patch

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from shared import state_registry


def test_wa_delete_conversation_removes_messages_and_state():
    """Brief 165: wa_delete_conversation removes rows from whatsapp_threads and whatsapp_booking_state."""
    phone = "TEST_165_DELETE_001"
    # Cleanup any residue from prior runs
    state_registry.wa_delete_conversation(phone)

    # Populate
    state_registry.wa_store_message(phone, "user", "hello")
    state_registry.wa_store_message(phone, "assistant", "hi back")
    state_registry.wa_save_booking_state(phone, {"customer_name": "TestUser"}, {})

    # Verify rows exist before delete
    history = state_registry.wa_get_full_history(phone)
    assert len(history) == 2

    # Delete
    count = state_registry.wa_delete_conversation(phone)
    assert count >= 3, f"Expected >=3 rows deleted (2 messages + 1 booking state), got {count}"

    # Verify gone
    assert state_registry.wa_get_full_history(phone) == []


def test_wa_delete_conversation_nonexistent_phone_returns_zero():
    """Brief 165: deleting a nonexistent conversation returns 0, does not raise."""
    phone = "TEST_165_NOTHING_HERE_001"
    count = state_registry.wa_delete_conversation(phone)
    assert count == 0


def test_wa_delete_conversation_only_affects_target_phone():
    """Brief 165: delete is scoped to the target phone only."""
    p1 = "TEST_165_KEEP_001"
    p2 = "TEST_165_DELETE_002"
    state_registry.wa_delete_conversation(p1)
    state_registry.wa_delete_conversation(p2)

    state_registry.wa_store_message(p1, "user", "keep me")
    state_registry.wa_store_message(p2, "user", "delete me")

    state_registry.wa_delete_conversation(p2)

    assert len(state_registry.wa_get_full_history(p1)) == 1
    assert state_registry.wa_get_full_history(p2) == []
    state_registry.wa_delete_conversation(p1)  # cleanup


def test_dashboard_delete_endpoint_exists():
    """Brief 165: source-level guard that the DELETE endpoint is declared in api.py."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard", "api.py")
    src = open(path).read()
    assert '@router.delete("/messages/conversations/{phone}"' in src, (
        "Brief 165: DELETE /messages/conversations/{phone} endpoint missing"
    )
    assert "wa_delete_conversation" in src, (
        "Brief 165: wa_delete_conversation call missing from api.py"
    )
```

### Step 4: Frontend — Messages.tsx trash button

1. Add `Trash2` to imports (line 10 region).
2. Pass an `onDelete` prop into `ConversationRow` alongside `onHide`.
3. Add a trash button after the EyeOff button (line 135 region) that calls `onDelete(conv.phone)`.
4. In the `Messages` component, add a `deleteConversation` mutation (new hook in `use-bluemarlin.ts`) and wire it through.
5. On success, invalidate conversations query.

### Step 5: Frontend — `useDeleteConversation` hook

Add to `use-bluemarlin.ts` near the conversations section:

```typescript
export function useDeleteConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (phone: string) =>
      fetch(`${API_BASE}/messages/conversations/${encodeURIComponent(phone)}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${getToken()}` },
      }).then(async (r) => {
        if (!r.ok) throw new Error(`Delete failed: ${r.status}`);
        return r.json();
      }),
    onSuccess: () => {
      toast.success("Conversation deleted");
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (err: unknown) => toast.error(`Delete failed: ${getErrorMessage(err)}`),
  });
}
```

Actually, if `useConversations` already exists and uses the api client, check how it constructs URLs and auth. Copy that pattern instead of reinventing.

### Step 6: Frontend — Escalations.tsx subject clear

In `openDetail` at line 103-107:

```tsx
// BEFORE
setCompose({
  to: isSemi(esc.notification_type) ? "" : parsed.email,
  subject: isSemi(esc.notification_type) ? "" : `Re: ${cleanSubject(esc.subject)}`,
  body: "",
});

// AFTER (Brief 165: always empty subject for operator to type fresh)
setCompose({
  to: isSemi(esc.notification_type) ? "" : parsed.email,
  subject: "",
  body: "",
});
```

Same change in the other `setCompose` call at line 489.

### Step 7: Frontend — Overview.tsx UrgentBar reflects all urgent sources

1. `UrgentBar` signature expands to `{ drafts, openEsc, unreadMsgs, onOpen, loading }`
2. The "All clear" branch becomes `if (drafts.length === 0 && openEsc === 0 && unreadMsgs === 0)`
3. The amber banner title adjusts: `"Needs Attention — {drafts.length} posts waiting, {openEsc} open escalations, {unreadMsgs} unread messages"` (or similar — keep it short when a count is zero)
4. In the main `Overview` component (line 281), pass `openEsc={openEsc}` and `unreadMsgs={unreadConvs}` to UrgentBar.

### Step 8: Frontend — publish mutation refetchType all

In `use-bluemarlin.ts:78-85`:

```typescript
const publish = useMutation({
  mutationFn: api.publishDraft,
  onSuccess: () => {
    toast.success("Draft published successfully to Instagram!");
    // Brief 165: force-refetch all matching queries (not just mark stale)
    queryClient.invalidateQueries({ queryKey: ["drafts"], refetchType: "all" });
    queryClient.invalidateQueries({ queryKey: ["status"], refetchType: "all" });
  },
  onError: (err: unknown) => toast.error(`Failed to publish: ${getErrorMessage(err)}`),
});
```

### Step 9: Run tests + typecheck + commit + deploy

```bash
python3 -m pytest wtyj/tests/social/test_165_dashboard_quick_wins.py -v
python3 -m pytest wtyj/tests/ -q --tb=line
cd /Users/benson/Projects/wetakeyourjob-dashboard/artifacts/dashboard && pnpm typecheck
```

Commit backend + frontend separately. Deploy backend to VPS; frontend auto-deploys via Replit.

## Success Condition

1. `wa_delete_conversation` exists and removes rows from both tables
2. `DELETE /messages/conversations/{phone}` endpoint returns `{"ok": True, "deleted_rows": n}`
3. 4+ new tests pass
4. 762+ total tests passing
5. Frontend typecheck: no NEW errors (pre-existing errors baseline is OK)
6. Escalation reply popup opens with empty subject for both semi and full
7. UrgentBar shows "All clear" only when drafts + escalations + unread are all 0
8. Trash button in Messages.tsx wired to new endpoint

## Rollback

Revert both commits (backend + frontend). `wa_delete_conversation` is idempotent — no data migration to roll back.
