# BRIEF 172 — Reconnect sweep additions after SR's dashboard merge
**Status:** Draft | **Files:** state_registry.py, dashboard/api.py, Messages.tsx, Escalations.tsx, use-bluemarlin.ts, api.ts (dashboard), test_172 (new) | **Depends on:** 163, 165, 166, 167, 171 | **Blocks:** —

## Context

Benson ran the 9-brief sweep (163-171) back-to-back on 2026-04-09. On the dashboard repo specifically, I pushed 4 sweep commits to origin/master (`2c3d31e` Brief 163, `1af52df` Brief 165, `4ba7734` Brief 167, `c487c23` Brief 171) based on the tag `pre-brief-sweep-163` (`23fd2f6`).

**Meanwhile, SR (`calvin61`) independently made 18 local commits in Replit** on the same base (`23fd2f6`) — an extensive UX polish pass on the dashboard. SR's 6 real feature commits (plus 12 auto "Published your App" deploys) include:

1. `6b62b29` Add a delete option and make action buttons always visible with refined colors
2. `03b3c06` Remove the "all clear" message when no attention is needed
3. `9e41840` Improve recent activity display and auto-archive old posts
4. `679acab` Apply consistent styling and always-visible actions to all pages
5. `c2c9cb3` Update navigation order to match user preference
6. `01b62e1` Add ability to send emails and reply to customers directly from the escalation list
7. `06c4a9f` Differentiate between semi and full escalations with distinct visual cues and functionality
8. `2ca1bad` Add archive and delete functionality for escalations
9. `5af6eac` Add archiving and delete functionality to message conversations
10. `1dc248c` Allow users to unarchive and unhide conversations and escalations

SR's work and my sweep overlapped on all 5 files I touched (`Messages.tsx`, `Escalations.tsx`, `Overview.tsx`, `use-bluemarlin.ts`, `api.ts`). When Replit tried to pull my 4 commits into SR's local, it reported a merge conflict.

Rather than hand-merge 22 commits across 5 files in the Replit UI (high risk of breaking SR's coherent UX pass), the decision was: **force-reset origin/master to the pre-sweep state**, let SR push their 18 commits cleanly as the new origin/master, then surgically re-apply ONLY the additive sweep pieces that SR couldn't have known about because they depend on sweep backend work. My 4 dashboard commits are preserved in a local branch `backup-sweep-dashboard-commits` on the Mac for reference.

Origin/master is now at `d430f61` (SR's "Published your App" from the latest push). The backend (bluemarlin-agent) is unchanged — it still has all 9 sweep briefs committed and deployed. All the backend endpoints (customer file, hold reaper, DELETE /messages/conversations/{phone}, GET /customers/by-identifier/{type}/{value}, merged list_conversations with email threads) are live.

**Brief 172's job: reconnect the dashboard to those backends + re-apply the 3 sweep additions that SR's version didn't include.**

## What SR built that needs backend wiring

### 1. Conversation delete button (Messages.tsx)

SR added an archive/unarchive UI (localStorage-based soft hide, via `useHiddenConversations` at lines 19-53) plus a Trash2 delete button that only appears when a conversation is archived (lines 147-155). The button calls `handleDelete(conv.phone)` at line 203:

```tsx
const handleDelete = (_phone: string) => {
  // API endpoint for delete coming soon — UI placeholder
};
```

**This is a stub.** The backend `DELETE /messages/conversations/{phone}` endpoint already exists (from Brief 165 — still deployed). Brief 172 replaces the stub with a real call via a new `useDeleteConversation` hook.

### 2. Escalation delete button (Escalations.tsx)

SR added the same archive → delete UX pattern to Escalations.tsx. Line 156-158:

```tsx
const handleDeleteEscalation = (_id: string) => {
  // API endpoint for delete coming soon — UI placeholder
};
```

**This is also a stub.** There is NO backend escalation delete endpoint yet — Brief 172 must add one alongside the wiring. This is new work outside the original sweep scope but it's small: a `state_registry.delete_escalation(id)` helper + `DELETE /escalations/{id}` endpoint.

## What's missing from SR's version and needs re-adding

### 3. Brief 163 — amber Clock tag for "Hold placed" system messages

SR's Messages.tsx at lines 395-410 has the OLD system message rendering:

```tsx
msg.role === "system" ? (() => {
  const isEscalation = /escalat|relay/i.test(msg.text);
  const isBooking = /booking confirmed/i.test(msg.text);
  const clickable = isEscalation || isBooking;
  const Icon = isBooking ? CheckCircle2 : AlertTriangle;
  const colors = isBooking
    ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-600 dark:text-emerald-400"
    : "bg-amber-500/10 border-amber-500/20 text-amber-600 dark:text-amber-400";
  // ...
```

SR's version only knows about `booking confirmed` → green CheckCircle2. After Brief 163 deployed, the backend (BlueMarlin with `payment.timing=upfront`) writes the text `"Hold placed — awaiting payment: ..."` as a system message instead of `"Booking confirmed: ..."`. SR's regex won't match that text, so the dashboard renders a generic amber AlertTriangle (works but not ideal). Brief 172 adds a third state for `/hold placed/i` → amber `Clock` icon with clickable scroll-to-booking-info.

### 4. Brief 167 — real phone number in escalation PHONE field

SR's Escalations.tsx at line 582 still has the old logic:

```tsx
<p className="text-sm font-mono text-foreground">{parsed.phone || selected.customer_id}</p>
```

`selected.customer_id` for Zernio escalations is the 24-char hex conversation_id — what JR flagged as ugly in Image #73. Brief 167 added `useCustomerByIdentifier` that looks up the customer file (from Brief 166) and returns a real phone identifier when one is linked. Brief 172 re-adds the hook call and updates the PHONE field to prefer the real phone when available, falling back to the hex otherwise.

### 5. Brief 171 — `channel?: string` on the Conversation TypeScript type

SR's `api.ts` at lines 72-80 defines Conversation without a `channel` field, but SR's Messages.tsx lines 108-122 USES `conv.channel` for the channel badge (Instagram/Facebook/Twitter/Email/WhatsApp icons and colors). This causes **12 TypeScript errors** on every typecheck run. The runtime works because the backend (post-Brief-171) returns the field anyway, but the type mismatch is noise and a correctness trap. Brief 172 adds `channel?: string` to the interface — the same one-line fix from Brief 171.

### 6. Brief 165 — publish mutation `refetchType: "all"`

SR's `use-bluemarlin.ts` at lines 78-85 has the publish mutation calling the generic `invalidate()` helper, which marks queries stale but doesn't force-refetch inactive ones. Brief 165 added `refetchType: "all"` so the Social Media stats cards flip immediately post-publish. Brief 172 re-adds this refinement.

## Why This Approach

**Rejected — hand-merge the 22 commits in Replit's conflict editor.** The conflicts spanned 5 files with overlapping feature areas (archive/delete in Messages + Escalations, UrgentBar rewrite, publish mutation, imports). Estimated 40+ conflict hunks. High risk of mis-merging a line and breaking SR's cohesive UX vision.

**Rejected — cherry-pick my 4 sweep commits on top of SR's branch.** Cherry-pick would still hit the same conflicts as the pull (because the tree changes are the same). Worse: cherry-picks don't preserve the "SR's version wins" policy I want to apply.

**Chosen — force-reset origin to pre-sweep, let SR push cleanly, then surgically add only the ADDITIVE sweep pieces.** This preserves SR's work exactly as they wrote it, and I only add back the handful of things SR couldn't have known to build (because they depend on backend work SR didn't see). The additive bits don't conflict with SR's code — they're insertions of new imports, new function calls, and new JSX branches that coexist cleanly.

Tradeoff: I temporarily lost my 4 dashboard commits from origin/master history. They're recoverable from the local `backup-sweep-dashboard-commits` branch + the `pre-brief-sweep-163` tag if ever needed. The backend commits are unaffected.

## Source Material

### Dashboard — SR's version (on origin/master now, also checked out locally)

**Messages.tsx**:
- Imports at lines 8-12: `Archive, ArchiveRestore, Trash2, Instagram, Facebook, Twitter, Globe, Mail` + others — but NO `Clock`, NO `useDeleteConversation`
- Line 4: `import { useConversations, useConversation } from "@/hooks/use-bluemarlin";` — no `useDeleteConversation`
- Lines 58-68: `ConversationRowProps` has `onUnhide` and `onDelete?` (optional)
- Lines 108-122: `conv.channel` references that cause typecheck errors
- Line 203: `handleDelete` stub
- Lines 395-410: old system message rendering

**Escalations.tsx**:
- Line 3: imports don't include `useCustomerByIdentifier`
- Line 10: imports include `Clock` (already), `Archive`, `ArchiveRestore`, `Trash2`, `Shield`
- Line 156-158: `handleDeleteEscalation` stub
- Line 582: PHONE field

**use-bluemarlin.ts**:
- Lines 78-85: publish mutation without `refetchType`
- No `useDeleteConversation`, `useDeleteEscalation`, `useCustomerByIdentifier` hooks

**api.ts**:
- Lines 72-80: Conversation interface without `channel?`
- No `deleteConversation`, `deleteEscalation`, `getCustomerByIdentifier` methods
- No `CustomerFile` interface

**Overview.tsx** (SR's version):
- Line 36: `UrgentBar({ drafts, onOpen, loading })` — no escalations/unread props
- Line 49: `if (drafts.length === 0) return null;` — SR's version simply returns nothing if no drafts, rather than showing "All clear". Benson's earlier spec is satisfied by this (no stale "All clear" message). **No re-apply needed for Overview.tsx.**

### Backend — unchanged from Brief 165/167

- `state_registry.wa_delete_conversation(phone)` exists (Brief 165)
- `DELETE /messages/conversations/{phone}` endpoint exists (Brief 165)
- `state_registry.customer_lookup(type_, value)` + `customer_get_full(id)` exist (Brief 166)
- `GET /customers/by-identifier/{type_}/{value}` endpoint exists (Brief 167)

**Missing**: escalation delete. Pending_notifications has `update_notification_status` (used for resolve) but no hard delete helper.

### Baseline

Backend: 809 tests passing.
Frontend typecheck: 13 pre-existing errors (1 in ContentPipeline.backup.tsx, 12 on Messages.tsx:108-122 for `conv.channel`). Adding `channel?` on the Conversation interface removes 12 of them.

## Instructions

### Step 1: Backend — add `delete_escalation` helper in state_registry.py

**File:** `wtyj/shared/state_registry.py`

Add a new helper alongside the existing `update_notification_status` / escalation helpers (grep for `get_all_escalations` to locate):

```python
def delete_escalation(escalation_id: int) -> bool:
    """Brief 172: hard-delete a pending_notifications row. Returns True if a
    row was deleted. Used by the dashboard Escalations page trash button (SR's
    UX — archive first, then from archive view you can delete permanently)."""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM pending_notifications WHERE id = ?", (escalation_id,))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed
```

### Step 2: Backend — add DELETE endpoint in dashboard/api.py

**File:** `wtyj/dashboard/api.py`

Add after the existing `resolve_escalation` endpoint (search for `resolve_escalation`):

```python
@router.delete("/escalations/{escalation_id}", dependencies=[Depends(_check_auth)])
async def delete_escalation(escalation_id: int):
    """Brief 172: hard-delete an escalation. SR built an archive-first UX
    (localStorage hide, then trash button visible only in archive view).
    This endpoint handles the actual permanent delete."""
    ok = state_registry.delete_escalation(escalation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Escalation not found")
    return {"ok": True, "id": escalation_id}
```

### Step 3: Backend tests in wtyj/tests/marina/test_172_reconnect.py

```python
"""Tests for Brief 172 — reconnect sweep additions after SR merge.

Covers the new escalation delete endpoint + helper. The other sweep reconnection
work is frontend-only; the existing brief 165 + 167 tests still cover the
backend delete/lookup paths."""
import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from shared import state_registry


def test_delete_escalation_removes_row():
    """Brief 172: delete_escalation removes a pending_notifications row."""
    nid = state_registry.create_pending_notification(
        "escalation", "whatsapp", "TEST_B172_ID", "Test B172",
        "subj", "body"
    )
    assert nid > 0

    ok = state_registry.delete_escalation(nid)
    assert ok is True

    rows = [e for e in state_registry.get_all_escalations() if e["id"] == nid]
    assert rows == []


def test_delete_escalation_nonexistent_returns_false():
    ok = state_registry.delete_escalation(99999999)
    assert ok is False


def test_dashboard_delete_escalation_endpoint_declared():
    """Brief 172: source-level guard that the endpoint is declared in api.py."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard", "api.py")
    src = open(path).read()
    assert '@router.delete("/escalations/{escalation_id}"' in src, (
        "Brief 172: DELETE /escalations/{escalation_id} endpoint missing"
    )
    assert "state_registry.delete_escalation" in src
```

### Step 4: Frontend — `api.ts` additions

**File:** `/Users/benson/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/lib/api.ts`

Add `channel?: string` to the Conversation interface:

```tsx
export interface Conversation {
  phone: string;
  customer_name: string;
  last_message: string;
  last_message_role: string;
  last_message_at: string;
  status: string;
  message_count: number;
  channel?: string;  // Brief 171/172: 'whatsapp' | 'email' | 'instagram_dm' | 'facebook_dm' | 'twitter_dm'
}
```

Add a new `CustomerFile` interface after the `Conversation` interface:

```tsx
export interface CustomerFile {
  id: number;
  display_name: string;
  summary: string;
  notes: string;
  first_seen: string;
  last_seen: string;
  identifiers: { type: string; value: string; first_seen: string }[];
  recent_interactions: { channel: string; summary: string; created_at: string }[];
}
```

Add three new API methods — locate the existing `getConversation` method (around line 540) and add after it:

```tsx
  deleteConversation: async (phone: string): Promise<{ ok: boolean; deleted_rows: number; phone: string }> => {
    const res = await fetch(`${BASE_URL}/messages/conversations/${encodeURIComponent(phone)}`, {
      method: "DELETE",
      headers: getHeaders(),
    });
    return handleResponse(res);
  },

  // Brief 167: resolve a customer file by identifier for PHONE field display.
  getCustomerByIdentifier: async (type_: string, value: string): Promise<CustomerFile | null> => {
    const res = await fetch(`${BASE_URL}/customers/by-identifier/${encodeURIComponent(type_)}/${encodeURIComponent(value)}`, {
      headers: getHeaders(),
    });
    return handleResponse<CustomerFile | null>(res);
  },
```

Locate the existing `resolveEscalation` method (search `resolveEscalation`) and add after it:

```tsx
  deleteEscalation: async (id: number): Promise<{ ok: boolean; id: number }> => {
    const res = await fetch(`${BASE_URL}/escalations/${id}`, {
      method: "DELETE",
      headers: getHeaders(),
    });
    return handleResponse(res);
  },
```

### Step 5: Frontend — `use-bluemarlin.ts` additions

**File:** `/Users/benson/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/hooks/use-bluemarlin.ts`

**Edit 5a:** Update the `publish` mutation (around line 78-85) to force-refetch:

```tsx
  const publish = useMutation({
    mutationFn: api.publishDraft,
    onSuccess: () => {
      toast.success("Draft published successfully to Instagram!");
      // Brief 165/172: force-refetch all matching queries (active and inactive)
      // so the Social Media stats cards flip immediately post-publish.
      queryClient.invalidateQueries({ queryKey: ["drafts"], refetchType: "all" });
      queryClient.invalidateQueries({ queryKey: ["status"], refetchType: "all" });
    },
    onError: (err: unknown) => toast.error(`Failed to publish: ${getErrorMessage(err)}`),
  });
```

**Edit 5b:** Add three new hooks after the existing `useConversation` hook (around line 250-256):

```tsx
// Brief 166/172: hard-delete a conversation from the Messages page (SR's trash button).
export function useDeleteConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (phone: string) => api.deleteConversation(phone),
    onSuccess: (data) => {
      toast.success(`Conversation deleted (${data.deleted_rows} rows)`);
      queryClient.invalidateQueries({ queryKey: ["conversations"], refetchType: "all" });
    },
    onError: (err: unknown) => toast.error(`Delete failed: ${getErrorMessage(err)}`),
  });
}

// Brief 167/172: resolve a customer file by identifier (conversation_id → real phone + display name).
export function useCustomerByIdentifier(type_: string | undefined, value: string | undefined) {
  return useQuery({
    queryKey: ["customer-by-identifier", type_, value],
    queryFn: () => api.getCustomerByIdentifier(type_!, value!),
    enabled: !!type_ && !!value,
  });
}

// Brief 172: hard-delete an escalation from the Escalations page (SR's trash button).
export function useDeleteEscalation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteEscalation(id),
    onSuccess: () => {
      toast.success("Escalation deleted");
      queryClient.invalidateQueries({ queryKey: ["escalations"], refetchType: "all" });
    },
    onError: (err: unknown) => toast.error(`Delete failed: ${getErrorMessage(err)}`),
  });
}
```

### Step 6: Frontend — `Messages.tsx` changes

**File:** `/Users/benson/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Messages.tsx`

**Edit 6a:** Add `Clock` to the lucide-react imports (line 10). Current line:
```tsx
  AlertTriangle, User, Archive, ArchiveRestore, Eye, Circle, CheckCircle, CheckCircle2, Ticket,
```
Change to:
```tsx
  AlertTriangle, User, Archive, ArchiveRestore, Eye, Circle, CheckCircle, CheckCircle2, Clock, Ticket,
```

**Edit 6b:** Import `useDeleteConversation` alongside the existing hook import (line 4). Current:
```tsx
import { useConversations, useConversation } from "@/hooks/use-bluemarlin";
```
Change to:
```tsx
import { useConversations, useConversation, useDeleteConversation } from "@/hooks/use-bluemarlin";
```

**Edit 6c:** Wire `handleDelete` to the real hook. Find the stub (around line 203):
```tsx
  const handleDelete = (_phone: string) => {
    // API endpoint for delete coming soon — UI placeholder
  };
```
Replace with:
```tsx
  const deleteConv = useDeleteConversation();
  const handleDelete = (phone: string) => {
    if (window.confirm(`Permanently delete this conversation? This cannot be undone.`)) {
      deleteConv.mutate(phone);
    }
  };
```

**Edit 6d:** Update the system message rendering block (around lines 395-410). Current:
```tsx
              msg.role === "system" ? (() => {
                const isEscalation = /escalat|relay/i.test(msg.text);
                const isBooking = /booking confirmed/i.test(msg.text);
                const clickable = isEscalation || isBooking;
                const Icon = isBooking ? CheckCircle2 : AlertTriangle;
                const colors = isBooking
                  ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-600 dark:text-emerald-400"
                  : "bg-amber-500/10 border-amber-500/20 text-amber-600 dark:text-amber-400";
                return (
                  <div key={idx} className="flex justify-center">
                    <button
                      onClick={clickable ? () => {
                        if (isEscalation) navigate("/escalations");
                        else if (isBooking) bookingInfoRef.current?.scrollIntoView({ behavior: "smooth" });
                      } : undefined}
```

Replace with (Brief 163 restored — adds `isHoldPlaced` as a third state):
```tsx
              msg.role === "system" ? (() => {
                const isEscalation = /escalat|relay/i.test(msg.text);
                const isBookingConfirmed = /booking confirmed/i.test(msg.text);
                const isHoldPlaced = /hold placed/i.test(msg.text);
                const isBookingEvent = isBookingConfirmed || isHoldPlaced;
                const clickable = isEscalation || isBookingEvent;
                let Icon = AlertTriangle;
                let colors = "bg-amber-500/10 border-amber-500/20 text-amber-600 dark:text-amber-400";
                if (isBookingConfirmed) {
                  Icon = CheckCircle2;
                  colors = "bg-emerald-500/10 border-emerald-500/20 text-emerald-600 dark:text-emerald-400";
                } else if (isHoldPlaced) {
                  Icon = Clock;
                  // amber (default) for pending-payment state
                }
                return (
                  <div key={idx} className="flex justify-center">
                    <button
                      onClick={clickable ? () => {
                        if (isEscalation) navigate("/escalations");
                        else if (isBookingEvent) bookingInfoRef.current?.scrollIntoView({ behavior: "smooth" });
                      } : undefined}
```

### Step 7: Frontend — `Escalations.tsx` changes

**File:** `/Users/benson/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Escalations.tsx`

**Edit 7a:** Add `useCustomerByIdentifier` and `useDeleteEscalation` to the hook import (line 3). Current:
```tsx
import { useEscalations, useEscalationMutations, useSuggestReply, useEscalationReply } from "@/hooks/use-bluemarlin";
```
Change to:
```tsx
import { useEscalations, useEscalationMutations, useSuggestReply, useEscalationReply, useCustomerByIdentifier, useDeleteEscalation } from "@/hooks/use-bluemarlin";
```

**Edit 7b:** Wire `handleDeleteEscalation` to the real hook. Find (around line 156):
```tsx
  const handleDeleteEscalation = (_id: string) => {
    // API endpoint for delete coming soon — UI placeholder
  };
```
Replace with:
```tsx
  const deleteEsc = useDeleteEscalation();
  const handleDeleteEscalation = (id: string) => {
    if (window.confirm(`Permanently delete this escalation? This cannot be undone.`)) {
      deleteEsc.mutate(Number(id));
    }
  };
```

**Edit 7c:** Add `customerFile` lookup after `const selected = ...` (around line 93):
```tsx
  const selected = allEscalations.find((e) => e.id === selectedId);

  // Brief 167/172: resolve the customer file for the selected escalation so
  // we can show a real phone number + display name instead of the Zernio hex.
  const customerLookupType = selected?.channel === "email"
    ? "email"
    : (selected && /^[a-f0-9]{24}$/i.test(selected.customer_id) ? "wa_conversation_id" : "phone");
  const { data: customerFile } = useCustomerByIdentifier(
    selected ? customerLookupType : undefined,
    selected?.customer_id,
  );
```

**Edit 7d:** Update the PHONE field display (around line 581). Current:
```tsx
                      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Phone</p>
                      <p className="text-sm font-mono text-foreground">{parsed.phone || selected.customer_id}</p>
```
Replace with:
```tsx
                      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Phone</p>
                      <p className="text-sm font-mono text-foreground">
                        {/* Brief 167/172: prefer resolved real phone from customer file */}
                        {customerFile?.identifiers?.find(i => i.type === "phone")?.value
                          || parsed.phone
                          || selected.customer_id}
                      </p>
                      {customerFile?.display_name && (
                        <p className="text-[10px] text-muted-foreground mt-0.5">{customerFile.display_name}</p>
                      )}
```

### Step 8: Run tests + typecheck + commit + deploy

```bash
# Backend
python3 -m pytest wtyj/tests/marina/test_172_reconnect.py -v --tb=short
python3 -m pytest wtyj/tests/ -q --tb=line
# Expected: 812 total (809 baseline + 3 new)

# Frontend typecheck — should drop from 13 to 1 (the backup file error)
cd /Users/benson/Projects/wetakeyourjob-dashboard/artifacts/dashboard && pnpm typecheck
```

```bash
# Backend commit
cd /Users/benson/Projects/bluemarlin-agent
git add wtyj/shared/state_registry.py wtyj/dashboard/api.py \
        wtyj/tests/marina/test_172_reconnect.py \
        wtyj/briefs/marina_brief_172_reconnect_sweep_after_sr_merge.md
git commit -m "Brief 172: escalation delete endpoint + helper"
git push origin main

# Dashboard commit
cd /Users/benson/Projects/wetakeyourjob-dashboard
git add artifacts/dashboard/src/lib/api.ts \
        artifacts/dashboard/src/hooks/use-bluemarlin.ts \
        artifacts/dashboard/src/pages/Messages.tsx \
        artifacts/dashboard/src/pages/Escalations.tsx
git commit -m "Brief 172: reconnect sweep additions on top of SR's merge"
git push origin master

# Deploy backend
ssh root@108.61.192.52 "cd /root && git pull && cd /root/clients/bluemarlin && docker compose down && docker compose build && docker compose up -d && cd /root/clients/adamus && docker compose down && docker compose up -d"
```

## Tests

Backend test coverage (3 new tests):
1. `test_delete_escalation_removes_row` — creates a pending_notification, deletes via helper, verifies gone
2. `test_delete_escalation_nonexistent_returns_false` — delete nonexistent id returns False
3. `test_dashboard_delete_escalation_endpoint_declared` — source-level guard

Frontend: rely on typecheck + the existing Brief 165/167 backend tests that cover the endpoints my frontend calls.

Must-not-regress:
- All 809 existing backend tests continue to pass (only additions to state_registry + api.py, no behavioral changes to existing code).
- Frontend typecheck drops from 13 errors to 1 (the pre-existing ContentPipeline.backup.tsx unrelated error).
- SR's archive UI, escalation filters, semi-vs-full visual differentiation all still work unchanged (only non-conflicting additions to 4 files).

## Success Condition

1. `delete_escalation` helper exists in state_registry.py, deletes by id
2. `DELETE /escalations/{id}` endpoint in dashboard/api.py
3. Backend: 812 tests passing / 0 failures
4. `Clock` imported in Messages.tsx
5. `handleDelete` in Messages.tsx calls `deleteConv.mutate(phone)` with confirm prompt
6. `handleDeleteEscalation` in Escalations.tsx calls `deleteEsc.mutate(Number(id))` with confirm prompt
7. `channel?: string` on Conversation interface in api.ts
8. Three hooks (`useDeleteConversation`, `useDeleteEscalation`, `useCustomerByIdentifier`) in use-bluemarlin.ts
9. `publish` mutation uses `refetchType: "all"`
10. Messages.tsx system message rendering has `isHoldPlaced` state with Clock icon
11. Escalations.tsx PHONE field prefers real phone from customer file
12. Frontend typecheck: 1 pre-existing error only (down from 13)
13. Both containers healthy post-deploy

## Rollback

Revert both commits (backend + dashboard). SR's work remains untouched on origin/master. The `backup-sweep-dashboard-commits` local branch still has the original 4 sweep commits if ever needed for reference.
