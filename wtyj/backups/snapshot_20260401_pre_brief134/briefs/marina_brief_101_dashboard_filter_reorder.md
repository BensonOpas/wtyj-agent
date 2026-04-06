# BRIEF 101 — Dashboard Content Pipeline Filter Reorder
**Status:** Draft | **Files:** `wetakeyourjob-dashboard/artifacts/dashboard/src/pages/ContentPipeline.tsx` | **Depends on:** None | **Blocks:** None

## Context
The Content Pipeline page in the operator dashboard has status filter tabs in this order: All, Pending, Approved, Rejected, Published. The operator wants Approved first (what needs publishing next), then Rejected (what was turned down), then Pending (new drafts to review), then Published (what went live), then All at the end.

## Why This Approach
Reorder only. No logic changes, no new features. The tab order should reflect the operator's workflow priority: check what's approved and ready to publish, review rejections, then look at new pending drafts.

## Source Material
Current tab order in ContentPipeline.tsx lines 107-112:
```
All → Pending → Approved → Rejected → Published
```

Requested order:
```
Approved → Rejected → Pending → Published → All
```

## Instructions
1. In `ContentPipeline.tsx`, reorder the `<TabsTrigger>` elements inside the `<TabsList>` to: Approved, Rejected, Pending, Published, All.
2. No other changes.

## Tests
1. Visual: tabs render in new order (Approved first, All last).
2. Each tab still filters correctly when clicked.
3. Default selection remains "all" (no change to initial state).

## Success Condition
Content Pipeline page shows filter tabs in order: Approved, Rejected, Pending, Published, All.

## Rollback
Revert the tab order in ContentPipeline.tsx.
