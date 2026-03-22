# BRIEF 114 — Overview: Replace Approve/Decline with Review Button
**Status:** Draft | **Depends on:** — | **Blocks:** —

**Frontend files (~/Projects/wetakeyourjob-dashboard/):**
- `artifacts/dashboard/src/pages/Overview.tsx`

## Context
The Overview "Needs Attention" bar shows pending drafts with Approve and Decline buttons. No one should approve or reject a draft without reading the full content first. Replace both buttons with a single "Review" button that navigates to the draft detail view in Social Media.

## Why This Approach
The Approve/Decline buttons on Overview are dangerous — a business owner might approve a post based on a one-line preview without reading the full caption, hashtags, or seeing the image. The proper workflow is: see notification → click Review → read full draft in Social Media → approve/reject there.

## Source Material
**Current UrgentBar row (Overview.tsx lines 82-111):**
Each draft row has:
- Left side: clickable caption text → `onOpen(draft)` → navigates to `/social?draft=${draft.id}`
- Right side: "Decline" button → `onReject(draft)`, "Approve" button → `onApprove(draft)`

**Target:** Replace the two buttons (lines 95-110) with a single "Review" button that calls `onOpen(draft)`, same as clicking the caption text.

## Instructions
1. In `Overview.tsx`, in the UrgentBar component, replace the `<div className="flex items-center gap-2 shrink-0">` block (lines 95-110) containing the Decline and Approve buttons with a single Review button:
   ```tsx
   <button
     onClick={() => onOpen(draft)}
     className="h-7 px-3 text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90 rounded-md transition-colors shadow-sm"
   >
     Review
   </button>
   ```

2. Remove unused props from the UrgentBar function signature and call site:
   - Remove `onApprove`, `onReject`, `approving`, `rejecting` from UrgentBar props
   - Remove `handleApprove`, `openReject`, `approvingId`, `rejectingId` from the call site (and the state/handlers that only served them)

3. Clean up: if `handleApprove`, `openReject`, `approvingId`, `rejectingId`, `localDismissed`, `rejectDialogOpen`, `rejectTarget`, `rejectReason`, `confirmReject`, and the reject Dialog are ONLY used by the UrgentBar, remove them all. If the reject Dialog is still used elsewhere on the page, keep it.

## Tests
Frontend-only, visual change. Verify:
1. Overview "Needs Attention" bar shows "Review" button (not Approve/Decline)
2. Clicking "Review" navigates to `/social?draft={id}` and opens the draft detail view
3. Approve/reject workflow happens in Social Media, not Overview

## Success Condition
No approve/decline buttons on Overview. Single "Review" button per draft that navigates to the full draft view.

## Rollback
Revert `artifacts/dashboard/src/pages/Overview.tsx` in the frontend repo.
