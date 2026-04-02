# BRIEF 115 — Re-apply Functional Fixes After SR's Redesign
**Status:** Draft | **Depends on:** Brief 113-114 | **Blocks:** —

**Frontend files (~/Projects/wetakeyourjob-dashboard/):**
- `artifacts/dashboard/src/components/ui/status-badge.tsx`
- `artifacts/dashboard/src/pages/ContentPipeline.tsx`
- `artifacts/dashboard/src/lib/api.ts`
- `artifacts/dashboard/src/pages/Create.tsx`
- `artifacts/dashboard/src/pages/Messages.tsx`
- `artifacts/dashboard/src/pages/Overview.tsx`

## Context
SR pushed 43 design commits. We reverted our 3 functional fixes (Briefs 113-114) to let him push cleanly. Now we re-apply the functional logic on top of his design. DraftStatus already has "scheduled" in api.ts (applied pre-brief).

## Why This Approach
Re-applying on top is correct because SR's visual changes are more extensive (43 commits) and our functional fixes are surgical (type additions, payload wiring, UI element swaps). Cherry-picking would create merge conflicts. Asking SR to re-apply our code would require him to understand backend wiring.

## Source Material

### Fix 1 — status-badge.tsx (line 33, before `deleted` entry)
```tsx
scheduled: {
  dot: "bg-purple-500",
  text: "text-purple-600 dark:text-purple-400",
  bg: "bg-purple-500/10",
  border: "border-purple-500/20",
  label: "Scheduled",
},
```

### Fix 2 — ContentPipeline.tsx:180
Current: `{ pending: 0, approved: 1, rejected: 2, published: 3, deleted: 4 }`
Replace with: `{ pending: 0, approved: 1, rejected: 2, published: 3, scheduled: 4, deleted: 5 }`

### Fix 3 — api.ts createManualDraft type (line 525-531)
Add `platforms?: string[]` to the data type object.

### Fix 4 — Create.tsx:46-53 handleCreate
Current payload:
```tsx
{
  instagram_caption: igCaption.trim(),
  facebook_caption: fbCaption.trim() || undefined,
  hashtags: hashtagList,
  content_class: contentClass,
  visual_suggestion: visualSuggestion.trim() || undefined,
}
```
Add `platforms` to this object (local state `platforms` already exists at line 33).

### Fix 5 — Messages.tsx:478-485 system events → clickable
Replace the current basic amber pill:
```tsx
msg.role === "system" ? (
  <div key={idx} className="flex justify-center">
    <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-amber-500/10 border border-amber-500/20 text-xs text-amber-600 dark:text-amber-400 font-medium">
      <AlertTriangle className="w-3 h-3" />
      <span>{msg.text}</span>
      <span className="text-amber-500/50 ml-1">{format(new Date(msg.created_at), 'h:mm a')}</span>
    </div>
  </div>
)
```
With clickable version:
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
        className={cn(
          "inline-flex items-center gap-2 px-4 py-2 rounded-full border text-xs font-medium transition-all",
          colors,
          clickable && "cursor-pointer hover:scale-[1.02] hover:shadow-sm"
        )}
      >
        <Icon className="w-3 h-3" />
        <span>{msg.text}</span>
        <span className="opacity-50 ml-1">{format(new Date(msg.created_at), 'h:mm a')}</span>
      </button>
    </div>
  );
})()
```
Requires adding to Messages.tsx imports: `useRef` from react, `useNavigate` from react-router-dom, `CheckCircle2` and `Ticket` from lucide-react.
Requires adding inside the component: `const navigate = useNavigate();` and `const bookingInfoRef = useRef<HTMLDivElement>(null);`

### Fix 6 — Messages.tsx:507-522 booking info → add completed bookings
Replace the current booking info section:
```tsx
{/* Booking state */}
{Object.keys(detail.booking_state?.fields ?? {}).length > 0 && (
  <div className="shrink-0 mt-2 pt-3 border-t border-border">
    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Booking Info</p>
    <div className="flex flex-wrap gap-2">
      {Object.entries(detail.booking_state.fields).map(([key, val]) => (
        val ? (
          <span key={key} className="text-xs bg-muted/50 border border-border rounded-lg px-2.5 py-1">
            <span className="text-muted-foreground/60">{key.replace(/_/g, ' ')}:</span>{' '}
            <span className="text-foreground/80 font-medium">{String(val)}</span>
          </span>
        ) : null
      ))}
    </div>
  </div>
)}
```
With enhanced version:
```tsx
<div ref={bookingInfoRef} className="shrink-0 mt-2 pt-3 border-t border-border space-y-3">
  {(detail.booking_state?.completed_bookings ?? []).length > 0 && (
    <div>
      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Completed Bookings</p>
      <div className="space-y-2">
        {(detail.booking_state.completed_bookings as Record<string, unknown>[]).map((bk, i) => (
          <div key={i} className="flex items-center gap-3 p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/15">
            <Ticket className="w-4 h-4 text-emerald-500 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-foreground">{String(bk.experience || bk.trip_key || "Trip")}</p>
              <p className="text-xs text-muted-foreground">{String(bk.date || "")} {bk.guests ? `· ${bk.guests} guests` : ""} {bk.booking_ref ? `· ${bk.booking_ref}` : ""}</p>
            </div>
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
          </div>
        ))}
      </div>
    </div>
  )}
  {Object.keys(detail.booking_state?.fields ?? {}).length > 0 && (
    <div>
      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
        {(detail.booking_state?.completed_bookings ?? []).length > 0 ? "Current Booking" : "Booking Info"}
      </p>
      <div className="flex flex-wrap gap-2">
        {Object.entries(detail.booking_state.fields).map(([key, val]) => (
          val ? (
            <span key={key} className="text-xs bg-muted/50 border border-border rounded-lg px-2.5 py-1">
              <span className="text-muted-foreground/60">{key.replace(/_/g, ' ')}:</span>{' '}
              <span className="text-foreground/80 font-medium">{String(val)}</span>
            </span>
          ) : null
        ))}
      </div>
    </div>
  )}
</div>
```

### Fix 7 — Overview.tsx UrgentBar → Review button (7 edits)

**Edit 7a — Imports (line 1):** Replace:
`import { useStatus, useDrafts, useDraftMutations, useConversations, useEscalations } from "@/hooks/use-bluemarlin";`
With:
`import { useStatus, useDrafts, useConversations, useEscalations } from "@/hooks/use-bluemarlin";`

**Edit 7b — Remove unused imports (lines 11-14):** Delete these 4 lines:
```
import { Button } from "@/components/ui/button";
(keep line 12 — ClassBadge)
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
```
Also remove `XCircle` from the lucide-react import (line 9).

**Edit 7c — UrgentBar signature (lines 39-46):** Replace with:
```tsx
function UrgentBar({ drafts, onOpen, loading }: {
  drafts: Draft[];
  onOpen: (d: Draft) => void;
  loading: boolean;
}) {
```

**Edit 7d — UrgentBar buttons (lines 96-111):** Replace the `<div className="flex items-center gap-2 shrink-0">` block with:
```tsx
<button
  onClick={() => onOpen(draft)}
  className="h-7 px-3 text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90 rounded-md transition-colors shadow-sm shrink-0"
>
  Review
</button>
```

**Edit 7e — Remove state + handlers (lines 176-234):** Replace lines 176-234:
```tsx
  const { approve, reject } = useDraftMutations();

  const [localDismissed, setLocalDismissed] = useState<Set<number>>(new Set());
  const [approvingId, setApprovingId] = useState<number | null>(null);
  ...
  const confirmReject = () => { ... };
```
With just:
```tsx
  const [activityExpanded, setActivityExpanded] = useState(false);
```
(Keep the lines after 234 — `const cards = [...]` etc. Move `activityExpanded` state if it was on line 184.)

**Edit 7f — UrgentBar call site (lines 338-346):** Replace with:
```tsx
<UrgentBar
  drafts={allPending ?? []}
  onOpen={(d) => navigate(`/social?draft=${d.id}`)}
  loading={pendingLoading}
/>
```

**Edit 7g — Delete reject dialog (lines 412-437):** Remove the entire `{/* Reject dialog */}` block.

## Tests
Code-level assertions (verify after applying):
1. `DraftStatus` type in api.ts:3 is `"pending" | "approved" | "rejected" | "published" | "deleted" | "scheduled"`
2. `statusConfig` in status-badge.tsx has 6 entries including `scheduled` with `dot: "bg-purple-500"`
3. `statusOrder` in ContentPipeline.tsx:180 has `scheduled: 4, deleted: 5`
4. `createManualDraft` data type in api.ts includes `platforms?: string[]`
5. `handleCreate` in Create.tsx passes `platforms` in the mutation object
6. Messages.tsx system event at line ~478 uses a `<button>` (not `<div>`) with conditional `onClick`
7. Messages.tsx has `bookingInfoRef` and renders `completed_bookings` array
8. Overview.tsx UrgentBar has no `onApprove` or `onReject` props; button text is "Review"
9. Overview.tsx has no `Dialog` import

## Success Condition
All 9 assertions above are true. No TypeScript compile errors.

## Rollback
Revert all 6 files in the frontend repo.
