# BRIEF 117 — Remove Brand Rules from Settings
**Status:** Draft | **Files:** Settings.tsx | **Depends on:** — | **Blocks:** —

## Context
Settings page has a "Brand Rules" accordion that shows learnings (rules distilled from rejections). Brand Training page already has a "Brand Profile" section showing all brand rules (visual + from analysis). Having both is confusing — "Brand Rules" in Settings shows 0 while "Brand Profile" in Brand Training shows 7. User wants to remove Brand Rules from Settings and keep Brand Training as the single place for brand rules.

## Why This Approach
Delete, don't merge. Brand Training already covers everything Brand Rules did (view, add, delete rules). The "Update Brand Rules" (distill) button can live in Brand Training if needed later. For now, removing the duplicate.

## Source Material

### Edit 1 — Remove `useLearnings, useLearningMutations` from import (line 3)
Current:
```tsx
  useLearnings, useLearningMutations,
```
Delete this entire line.

### Edit 2 — Remove `BrainCircuit` and `Quote` from lucide-react import (lines 13, 15)
Current line 13: `BrainCircuit, HardDrive, CheckCircle2, XCircle, ChevronDown, ChevronUp,`
Replace with: `HardDrive, CheckCircle2, XCircle, ChevronDown, ChevronUp,`

Current line 15: `Settings as SettingsIcon, Quote, CalendarDays, Plus, Clock, X, Mail,`
Replace with: `Settings as SettingsIcon, CalendarDays, Plus, Clock, X, Mail,`

### Edit 3 — Remove `Trash2` from lucide-react import (line 14)
Current: `Info, Code, Map, Ship, Sun, Palette, ArrowRight, ArrowLeft, FolderOpen, Trash2,`
Replace with: `Info, Code, Map, Ship, Sun, Palette, ArrowRight, ArrowLeft, FolderOpen,`

### Edit 4 — Remove `formatDistanceToNow` from date-fns import (line 20)
Current: `import { formatDistanceToNow, format } from "date-fns";`
Replace with: `import { format } from "date-fns";`

### Edit 5 — Remove learnings hooks (lines 121-122)
Delete:
```tsx
  const { data: learnings, isLoading: learningsLoading } = useLearnings();
  const { distill, remove } = useLearningMutations();
```

### Edit 6 — Remove Brand Rules accordion section (lines 165-223)
Delete the entire block from `{/* ── Brand Rules */}` through the closing `</AccordionSection>` and the blank line after it. The next line after deletion should be `{/* ── Assets & Connections */}`.

## Tests
Code-level assertions (verify after applying):
1. No `BrainCircuit` in Settings.tsx
2. No `Quote` in Settings.tsx
3. No `Trash2` in Settings.tsx
4. No `useLearnings` or `useLearningMutations` in Settings.tsx
5. No `formatDistanceToNow` in Settings.tsx
6. No `Brand Rules` text in Settings.tsx
7. No `distill` or `learnings` variable in Settings.tsx
8. `format` import from date-fns is preserved (used by Schedule section)
9. Assets & Connections accordion is the first accordion after the page header

## Success Condition
Settings page loads with 5 accordion sections (Assets & Connections, Schedule & Automation, Capacity & Availability, Email Integration, Advanced View). No Brand Rules section.

## Rollback
Revert Settings.tsx in the frontend repo.
