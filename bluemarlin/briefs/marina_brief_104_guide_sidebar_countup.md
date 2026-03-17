# BRIEF 104 — Guide to Sidebar + Stats Bar Count-Up Animation
**Status:** Draft | **Depends on:** Brief 103 | **Blocks:** None

**Files:**
- `wetakeyourjob-dashboard/artifacts/dashboard/src/components/layout/AppLayout.tsx`
- `wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Overview.tsx`

## Context
Two polish items from user feedback on Brief 103:
1. "How This Works" guide is at the bottom of Overview — should be a help icon in the sidebar that opens a popup/modal. Accessible from any page, not just Overview.
2. Stats bar numbers should count up on page load (0 → actual value) for a dopamine hit. Only on initial load, not on refetch.

## Why This Approach
Guide in sidebar: it's system-level help, not page-specific. A Dialog component handles click-outside-to-close automatically. Alternative considered: a separate /help page — rejected because it's too heavy for a small guide. A sidebar icon + modal is the lightest approach.

Count-up: a simple useEffect with requestAnimationFrame. No external animation library needed. Framer Motion is already installed but a raw RAF loop is simpler for number counting. Alternative: CSS counter — rejected because it can't interpolate number values smoothly.

## Source Material

### Fix 1 — Guide in sidebar
In AppLayout.tsx, after the "Coming Soon" items section (line 182), add a HelpCircle button. Style it like the nav items but as a standalone button (not a Link since it opens a modal, not a page). On click, open a Dialog with the guide content (same text from Brief 103).

Remove the "How This Works" section from Overview.tsx entirely.

The existing `<Link to="/content">` Edit button in ActionCard was already removed in Brief 103 (replaced with onClick). No nested Link issue.

### Fix 2 — Count-up animation on stats bar
In Overview.tsx, create a `useCountUp(target, duration)` hook:
- Takes target number and duration in ms (default 800ms)
- Returns the current animated value
- Uses useEffect + requestAnimationFrame
- Eases with `Math.min(1, elapsed / duration)` squared (ease-out)
- Only runs once when target first becomes non-zero (not on refetch)
- Returns 0 while loading

Apply to each StatPill's value prop.

## Instructions

### AppLayout.tsx

1. Add imports: `HelpCircle` from lucide-react, `Dialog, DialogContent, DialogHeader, DialogTitle` from ui/dialog, `useState`.

2. In the `AppLayout` component (not SidebarContent — needs state), add: `const [guideOpen, setGuideOpen] = useState(false)`.

3. In `SidebarContent`, after the comingSoonItems map block (after the closing `</div>` at line 182), add a help button:
```tsx
<div className="mt-4 px-3">
  <button
    onClick={() => setGuideOpen(true)}
    className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors w-full"
  >
    <HelpCircle className="w-4 h-4" />
    <span className="font-medium text-sm">How This Works</span>
  </button>
</div>
```

Note: `SidebarContent` is a nested function inside `AppLayout`, so it has access to `setGuideOpen` via closure.

4. After the `</div>` that closes the main layout (line 269), but inside the return, add the Dialog:
```tsx
<Dialog open={guideOpen} onOpenChange={setGuideOpen}>
  <DialogContent>
    {/* guide content from Brief 103 */}
  </DialogContent>
</Dialog>
```

### Overview.tsx

5. Remove the entire "How This Works" section (the `<section>` with `showGuide` state, the button, and the collapsible content).

6. Remove the `showGuide` state declaration.

7. Remove `HelpCircle` and `ChevronDown` from the lucide imports (if unused elsewhere).

8. Add a `useCountUp` hook above the component:
```tsx
function useCountUp(target: number | undefined, duration = 800): number {
  const [value, setValue] = useState(0);
  const hasAnimated = useRef(false);

  useEffect(() => {
    if (target == null || target === 0 || hasAnimated.current) {
      if (target != null) setValue(target);
      return;
    }
    hasAnimated.current = true;
    const start = performance.now();
    const animate = (now: number) => {
      const elapsed = now - start;
      const progress = Math.min(1, elapsed / duration);
      const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
      setValue(Math.round(eased * target));
      if (progress < 1) requestAnimationFrame(animate);
    };
    requestAnimationFrame(animate);
  }, [target, duration]);

  return value;
}
```

9. Add `useRef` to the React imports.

10. In the stats bar section, replace raw `status?.pending` etc with count-up values:
```tsx
const pendingCount = useCountUp(status?.pending);
const approvedCount = useCountUp(status?.approved);
const publishedCount = useCountUp(status?.published);
const learningsCount = useCountUp(status?.learnings);
```
Then use these in the StatPill `value` props instead of `status?.pending` etc.

11. Update `StatPill` to accept `number` (not `number | undefined`) since the countUp hook always returns a number. Or keep the prop as-is and pass the countUp value.

## Tests

### Assertions
1. AppLayout.tsx: no `<Link>` wrapping the HelpCircle button (it's a `<button>` + Dialog, not navigation)
2. Overview.tsx: no `showGuide` state, no "How This Works" section in JSX
3. Overview.tsx: `useCountUp` hook uses `useRef` to prevent re-animation on refetch
4. Stats bar passes countUp values to StatPill, not raw status values

### Manual verification
5. Sidebar: HelpCircle icon + "How This Works" label visible below Coming Soon section
6. Click it: modal opens with guide content (workflow, classes, learnings)
7. Click outside modal: closes
8. Overview: numbers count up from 0 on first page load
9. Navigate away and back: numbers appear instantly (no re-animation)

## Success Condition
Guide is accessible from any page via sidebar. Stats bar numbers animate on first load only.

## Rollback
Revert AppLayout.tsx and Overview.tsx.
