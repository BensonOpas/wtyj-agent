# BRIEF 102 — Dashboard Polish: Draft Editing, Reject Reason, Image Text, AI Label
**Status:** Draft | **Depends on:** None | **Blocks:** None

**Files:**
- `bluemarlin/shared/state_registry.py` (new function)
- `bluemarlin/dashboard/api.py` (new endpoint)
- `wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Overview.tsx` (reject dialog + label fix)
- `wetakeyourjob-dashboard/artifacts/dashboard/src/pages/ContentPipeline.tsx` (edit mode + image text)
- `wetakeyourjob-dashboard/artifacts/dashboard/src/lib/api.ts` (new API call)
- `wetakeyourjob-dashboard/artifacts/dashboard/src/hooks/use-bluemarlin.ts` (new mutation)

## Context
Four issues found during first live dashboard testing:

1. **No draft editing** — operator can only approve or reject. No way to tweak a caption before approving. Backend has no update endpoint.
2. **Overview page rejects without asking for a reason** — `handleReject` in Overview.tsx sends hardcoded `"Rejected from overview"` instead of prompting the operator. This breaks the rejection learning pipeline (learnings are distilled from rejection reasons).
3. **Image placeholder says "Generating graphic..."** — misleading. Graphics don't exist until publish. Should say something accurate.
4. **System Health says "GPT-4o"** — SR's leftover. Should say "Claude".

## Why This Approach
All four are small, independent fixes in the same area (dashboard). No architectural changes. The edit endpoint is a simple UPDATE on existing columns — no new tables, no new fields.

## Source Material

**Fix 1 — Draft editing:**

Backend — new function in `state_registry.py`:
```python
def update_draft_content(draft_id: int, instagram_caption: str = None,
                         facebook_caption: str = None, hashtags: list = None) -> bool:
```
Only updates non-None fields. Only works on drafts with status "pending".

Backend — new endpoint in `dashboard/api.py`:
```
PUT /drafts/{draft_id}
Body: {"instagram_caption": "...", "facebook_caption": "...", "hashtags": [...]}
All body fields optional. Returns {"ok": true}.
Returns 400 if draft is not pending.
```

Frontend — `api.ts`: add `updateDraft(id, data)` method.
Frontend — `use-bluemarlin.ts`: add `update` mutation to `useDraftMutations`.
Frontend — `ContentPipeline.tsx`: add edit toggle to draft detail sheet. When in edit mode:
- Instagram caption and Facebook caption fields become editable textareas
- Hashtags become an editable text input (comma-separated)
- "Save" button calls updateDraft, then exits edit mode and refetches
- "Cancel" button exits edit mode without saving
- Edit button (pencil icon) in the sheet header toggles edit mode
- Only show edit toggle when draft status is "pending"

**Fix 2 — Overview reject reason:**

Current code (Overview.tsx line 196-199):
```javascript
const handleReject = (draft: Draft) => {
    reject.mutate({ id: draft.id, reason: "Rejected from overview" }, {
```

Fix: add a reject dialog (same pattern as ContentPipeline.tsx). Add state for `rejectTarget` (draft or null), `rejectReason` (string), `rejectDialogOpen` (boolean). The reject button sets the target and opens the dialog. Confirm sends the reason. Cancel clears.

**Fix 3 — Image placeholder text:**

In `ContentPipeline.tsx` line 239, `fallbackText="Generating graphic..."` → change to `fallbackText="No preview — graphic generates on publish"`.

In `auth-image.tsx` line 48, default fallback `"No image available"` stays as-is (it's fine for other contexts).

**Fix 4 — AI label:**

In `Overview.tsx` line 377:
```jsx
<SystemRow label="AI Agent" status="ok" note="GPT-4o" />
```
Change `"GPT-4o"` to `"Claude"`.

## Instructions

### Backend (bluemarlin-agent repo)

1. In `state_registry.py`, add `update_draft_content()` after `update_draft_status()`:
   - Build UPDATE query dynamically from non-None params
   - WHERE clause: `id = ? AND status = 'pending'`
   - Return True if row updated, False otherwise

2. In `dashboard/api.py`:
   - Add `UpdateDraftRequest` Pydantic model with optional fields: `instagram_caption`, `facebook_caption`, `hashtags`
   - Add `PUT /drafts/{draft_id}` endpoint that calls `update_draft_content()`
   - Return 400 if draft is not pending (check via rowcount)

### Frontend (wetakeyourjob-dashboard repo)

3. In `api.ts`, add `updateDraft` method:
   ```typescript
   updateDraft: async (id: number, data: { instagram_caption?: string; facebook_caption?: string; hashtags?: string[] }): Promise<{ ok: boolean }>
   ```

4. In `use-bluemarlin.ts`, add `update` mutation to `useDraftMutations()`:
   - On success: invalidate `["drafts"]` queries (prefix matching covers individual draft queries too), toast "Draft updated"

5. In `ContentPipeline.tsx`:
   - Add state: `isEditing` (boolean), `editCaption` (string), `editFbCaption` (string), `editHashtags` (string)
   - When opening edit mode, populate edit state from selectedDraft
   - In the sheet, when `isEditing && selectedDraft.status === "pending"`: render textareas instead of display divs for captions, text input for hashtags (comma-separated)
   - Add Edit button (pencil icon) next to draft ID in sheet header — only visible when status is "pending"
   - Add Save/Cancel buttons in footer when editing
   - Save parses hashtags from comma-separated string, calls updateDraft, exits edit mode
   - Change `fallbackText` on line 239 from `"Generating graphic..."` to `"No preview — graphic generates on publish"`

6. In `Overview.tsx`:
   - Add state: `rejectDialogOpen`, `rejectTarget` (Draft | null), `rejectReason` (string)
   - Change `handleReject` to open the dialog instead of mutating directly
   - Add `confirmReject` function that calls `reject.mutate` with the entered reason, dismisses the card, closes dialog
   - Add Dialog component (import from ui/dialog) — same pattern as ContentPipeline's reject dialog
   - Line 377: change `"GPT-4o"` to `"Claude"`

## Tests

### Backend tests (file: `bluemarlin/tests/social/test_102_dashboard_polish.py`)

1. `test_update_draft_content_caption` — create draft, update instagram_caption, verify it changed
2. `test_update_draft_content_partial` — update only facebook_caption, verify instagram_caption unchanged
3. `test_update_draft_content_hashtags` — update hashtags, verify stored correctly as JSON
4. `test_update_draft_content_not_pending` — approve a draft, try to update, verify returns False
5. `test_update_draft_content_nonexistent` — try to update draft ID 9999, verify returns False
6. `test_api_update_draft_endpoint` — mock state_registry, call PUT /drafts/1, verify 200
7. `test_api_update_draft_not_pending` — mock returns False, verify 400 response

### Frontend verification (manual)
8. Content Pipeline: open pending draft → pencil icon visible → click → fields become editable → edit caption → Save → caption updated
9. Content Pipeline: open approved draft → no pencil icon
10. Overview: click Reject on action card → dialog appears with textarea → enter reason → Confirm → draft rejected with reason
11. Overview: System Health shows "Claude" not "GPT-4o"
12. Content Pipeline: draft without image shows "No preview — graphic generates on publish"

## Success Condition
Operator can edit pending draft captions before approving. Rejecting from any page asks for a reason. No misleading text in the UI.

## Rollback
- Backend: remove `update_draft_content()` from state_registry and PUT endpoint from api.py
- Frontend: revert ContentPipeline.tsx, Overview.tsx, api.ts, use-bluemarlin.ts
