# BRIEF 127 — UI Polish Batch
**Status:** Draft | **Depends on:** Brief 126 | **Blocks:** —

**Files:**
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Settings.tsx`
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/ContentPipeline.tsx`
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Escalations.tsx`

## Context
Three UI fixes: (1) Publishing Mode text says "Instagram" but should say "social media" since Facebook is connected too. (2) Platform toggles should allow deselecting both + add LinkedIn as coming soon. (3) Escalation filters need Semi and Full tabs.

## Why This Approach
Frontend-only text/UI changes. No backend modifications.

## Source Material

### Fix 1 — Settings.tsx: Publishing Mode text (line 499)
Current: `{dryRunData?.dry_run ? "Dry run — posts are not published to Instagram" : "Live — posts are published to Instagram"}`
Replace with: `{dryRunData?.dry_run ? "Dry run — posts are not published to social media" : "Live — posts are published to social media"}`

### Fix 2 — ContentPipeline.tsx: Platform toggles

**2a — Remove "at least one" restriction (lines 548, 554, 568-570):**
Remove `isOnly` logic. Replace the button:
- Remove line 548: `const isOnly = isActive && draftPlatforms.length === 1;`
- Line 554: change `disabled={isOnly || updatePlatforms.isPending}` to `disabled={updatePlatforms.isPending}`
- Line 568: remove `isOnly && "opacity-60 cursor-not-allowed"`
- Line 570: remove `title={isOnly ? "At least one platform must be selected" : ""}`

**2b — Disable Publish Now when no platforms selected (line 620):**
Current: `disabled={publish.isPending}`
Replace with: `disabled={publish.isPending || (selectedDraft.platforms ?? ["instagram"]).length === 0}`

**2c — Add LinkedIn "coming soon" button after the platform loop (after line 577, inside the `<div className="flex gap-2">`):**
```tsx
<button
  disabled
  className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border bg-muted/20 border-border/50 text-muted-foreground/30 cursor-not-allowed"
  title="Coming soon"
>
  <Linkedin className="w-4 h-4" />
  LinkedIn
  <span className="text-[10px] uppercase tracking-wider">Soon</span>
</button>
```
Add `Linkedin` to the lucide-react import (line 15).

### Fix 3 — Escalations.tsx: Filter tabs

**3a — Update FILTERS (line 16):**
Current: `const FILTERS = ["Pending", "Resolved", "All"];`
Replace with: `const FILTERS = ["All", "Semi", "Full", "Pending", "Resolved"];`

**3b — Update default filter (line 52):**
Current: `const [activeFilter, setActiveFilter] = useState("Pending");`
Replace with: `const [activeFilter, setActiveFilter] = useState("All");`

**3c — Add counts for Semi and Full (lines 70-72):**
After `const resolvedCount = ...` add:
```tsx
const semiCount = visibleAll.filter((e) => isSemi(e.notification_type)).length;
const fullCount = visibleAll.filter((e) => !isSemi(e.notification_type)).length;
```

**3d — Update tabCount (lines 75-78):**
Replace with:
```tsx
  const tabCount = (f: string) => {
    if (f === "Pending") return pendingCount;
    if (f === "Resolved") return resolvedCount;
    if (f === "Semi") return semiCount;
    if (f === "Full") return fullCount;
    return allCount;
  };
```

**3e — Update filter logic (lines 81-84):**
Replace with:
```tsx
  const filtered = visibleAll.filter((e) => {
    if (activeFilter === "Pending") return e.status !== "resolved";
    if (activeFilter === "Resolved") return e.status === "resolved";
    if (activeFilter === "Semi") return isSemi(e.notification_type);
    if (activeFilter === "Full") return !isSemi(e.notification_type);
    return true;
  });
```

Note: `isSemi` is defined at line 113 inside the component. The counts need to be computed before it's used — but `isSemi` is a const function that doesn't depend on state, so it can be moved above the counts or used inline. Since `isSemi` is already defined as a const arrow function, move it above the count computations (before line 70).

## Tests
1. Settings Publishing Mode text contains "social media" not "Instagram"
2. ContentPipeline platform toggles have no `isOnly` restriction
3. ContentPipeline Publish Now disabled when `platforms.length === 0`
4. ContentPipeline has LinkedIn button with "Soon" label
5. Escalations FILTERS is `["All", "Semi", "Full", "Pending", "Resolved"]`
6. Escalations default filter is "All"
7. Escalations tabCount returns semiCount for "Semi" and fullCount for "Full"

## Success Condition
Publishing Mode says "social media". Can deselect all platforms, Publish Now darkens. LinkedIn shows as coming soon. Escalation tabs include Semi/Full filters defaulting to All.

## Rollback
Revert all 3 files.
