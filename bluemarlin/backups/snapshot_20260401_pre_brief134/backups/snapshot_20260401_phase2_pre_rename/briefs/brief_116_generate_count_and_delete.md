# BRIEF 116 — Configurable Draft Count + Delete Button
**Status:** Draft | **Files:** ContentPipeline.tsx | **Depends on:** Brief 115 | **Blocks:** —

## Context
Two UX gaps in the Social Media page:
1. Generate dialog is hardcoded to 3 drafts — user can't choose how many.
2. No way to delete drafts. The backend `DELETE /drafts/{id}` exists, the hook `remove` exists in `useDraftMutations()`, but there's no UI button. Rejected/published/deleted drafts show "No actions available".

## Why This Approach
Frontend-only changes. Backend and hooks already support both features. The generate dialog gets a simple counter (1–10). The delete button goes on every non-published status as a secondary action — pending, approved, rejected, scheduled. Published drafts are the record of what went live, so no delete there.

## Source Material

### Fix 1 — Generate count picker
**File:** `ContentPipeline.tsx`

**Current state (lines 732-764):** Generate confirm dialog has hardcoded "Generate 3 new posts?" title and description, with `generate.mutate(3)`.

**Change:** Add a `generateCount` state (default 3). Add a row of buttons (1, 3, 5, 10) in the dialog. Update the title dynamically. Pass `generateCount` to `generate.mutate()`.

Add state at line 48 (after `generateConfirmOpen`):
```tsx
const [generateCount, setGenerateCount] = useState(3);
```

Replace the generate dialog (lines 732-764) with:
```tsx
{/* ── Generate Confirm Dialog ───────────────────────────────── */}
<Dialog open={generateConfirmOpen} onOpenChange={setGenerateConfirmOpen}>
  <DialogContent className="bg-card border-border text-foreground sm:max-w-sm">
    <DialogHeader>
      <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center mb-3">
        <Sparkles className="w-5 h-5 text-primary" />
      </div>
      <DialogTitle className="text-lg font-display">Generate {generateCount} new post{generateCount === 1 ? "" : "s"}?</DialogTitle>
      <DialogDescription className="text-foreground/60 mt-1">
        Our system will write new social media drafts based on your current availability, brand voice, and recent content.
      </DialogDescription>
    </DialogHeader>
    <div className="flex items-center justify-center gap-2 py-2">
      {[1, 3, 5, 10].map((n) => (
        <button
          key={n}
          onClick={() => setGenerateCount(n)}
          className={cn(
            "w-10 h-10 rounded-lg text-sm font-semibold transition-all",
            generateCount === n
              ? "bg-primary text-primary-foreground shadow-sm"
              : "bg-muted/50 text-muted-foreground hover:bg-muted border border-border"
          )}
        >
          {n}
        </button>
      ))}
    </div>
    <DialogFooter className="mt-2 flex gap-2 sm:flex-row">
      <Button
        variant="outline"
        className="flex-1 border-border"
        onClick={() => setGenerateConfirmOpen(false)}
      >
        No, cancel
      </Button>
      <Button
        className="flex-1 bg-primary text-primary-foreground hover:bg-primary/90"
        onClick={() => {
          setGenerateConfirmOpen(false);
          generate.mutate(generateCount);
        }}
      >
        <Sparkles className="w-4 h-4 mr-2" />
        Yes, generate
      </Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
```

### Fix 2 — Delete button on drafts
**File:** `ContentPipeline.tsx`

**Current state (line 37):** `remove` is not destructured from `useDraftMutations()`.

**Change 2a:** Add `remove` to the destructure at line 37:
```tsx
const { approve, reject, publish, update, generate, generateGraphics, remove, updatePlatforms, schedule, unschedule } = useDraftMutations();
```

**Change 2b:** Add `Trash2` to lucide-react import (line 14):
Add `Trash2` after `Facebook,`.

**Current state (lines 598-627):** Footer actions section. Pending has Reject/Edit/Approve. Approved has Publish/Schedule. Scheduled has unschedule. Rejected/published/deleted shows "No actions available".

**Change 2c:** Replace the "No actions available" block (line 625-627):
```tsx
{!isEditing && (selectedDraft.status === 'rejected' || selectedDraft.status === 'published' || selectedDraft.status === 'deleted') && (
  <Button variant="outline" className="w-full border-border text-muted-foreground" disabled>No actions available</Button>
)}
```
With:
```tsx
{!isEditing && selectedDraft.status === 'published' && (
  <Button variant="outline" className="w-full border-border text-muted-foreground" disabled>No actions available</Button>
)}

{!isEditing && (selectedDraft.status === 'rejected' || selectedDraft.status === 'deleted') && (
  <Button
    variant="outline"
    onClick={() => { remove.mutate(selectedDraft.id); backToList(); }}
    disabled={remove.isPending}
    className="w-full border-rose-500/30 text-rose-400 hover:bg-rose-500/10"
  >
    <Trash2 className="w-4 h-4 mr-2" />
    {remove.isPending ? "Deleting..." : "Delete Draft"}
  </Button>
)}
```

**Change 2d:** Add delete as secondary action for pending drafts (line 598-604). After the existing 3 buttons, add a delete row:
After line 603 (`</>`), before the next `{!isEditing && selectedDraft.status === 'approved'` block, insert:
```tsx
{!isEditing && selectedDraft.status === 'pending' && (
  <Button
    variant="ghost"
    onClick={() => { remove.mutate(selectedDraft.id); backToList(); }}
    disabled={remove.isPending}
    className="w-full text-rose-400/60 hover:text-rose-400 hover:bg-rose-500/10 text-xs mt-1"
  >
    <Trash2 className="w-3.5 h-3.5 mr-1.5" />
    {remove.isPending ? "Deleting..." : "Delete"}
  </Button>
)}
```

**Change 2e:** Add delete as secondary action for approved drafts (line 606-611). After the Publish+Schedule buttons, add:
```tsx
{!isEditing && selectedDraft.status === 'approved' && (
  <Button
    variant="ghost"
    onClick={() => { remove.mutate(selectedDraft.id); backToList(); }}
    disabled={remove.isPending}
    className="w-full text-rose-400/60 hover:text-rose-400 hover:bg-rose-500/10 text-xs mt-1"
  >
    <Trash2 className="w-3.5 h-3.5 mr-1.5" />
    {remove.isPending ? "Deleting..." : "Delete"}
  </Button>
)}
```

**Change 2f:** Add delete as secondary action for scheduled drafts (line 613-623). After the unschedule button, add:
```tsx
{!isEditing && selectedDraft.status === 'scheduled' && (
  <Button
    variant="ghost"
    onClick={() => { remove.mutate(selectedDraft.id); backToList(); }}
    disabled={remove.isPending}
    className="w-full text-rose-400/60 hover:text-rose-400 hover:bg-rose-500/10 text-xs mt-1"
  >
    <Trash2 className="w-3.5 h-3.5 mr-1.5" />
    {remove.isPending ? "Deleting..." : "Delete"}
  </Button>
)}
```

## Tests
Code-level assertions (verify after applying):
1. `generateCount` state exists with default value 3
2. Generate dialog shows 4 count buttons (1, 3, 5, 10)
3. `generate.mutate(generateCount)` uses the state variable, not hardcoded 3
4. Dialog title is dynamic: "Generate {n} new post(s)?"
5. `remove` is destructured from `useDraftMutations()`
6. `Trash2` is imported from lucide-react
7. Delete button appears for pending, approved, rejected, scheduled, deleted statuses
8. Delete button does NOT appear for published status
9. Published drafts still show "No actions available"

## Success Condition
User can pick how many posts to generate (1/3/5/10), and can delete any non-published draft.

## Rollback
Revert ContentPipeline.tsx in the frontend repo.
