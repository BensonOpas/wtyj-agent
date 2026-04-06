# BRIEF 103 — Dashboard Overview & Content Pipeline UX Overhaul
**Status:** Draft | **Depends on:** Brief 102 | **Blocks:** None

**Files:**
- `wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Overview.tsx`
- `wetakeyourjob-dashboard/artifacts/dashboard/src/pages/ContentPipeline.tsx`

## Context
First real usage of the dashboard exposed several UX issues:

1. **Overview feels 70% empty** — too much whitespace, KPI section is 6 bulky cards that clutter the eye
2. **Action cards aren't clickable** — clicking should open the draft in content pipeline for full review
3. **Content Pipeline tab order wrong** — should be Approved, Rejected, Published, Pending, All
4. **No "How to Use" guide** — operators won't know what Class A/B/C/D means or the approve→publish flow
5. **Visual Asset placeholder looks cheap** — big empty box with "No preview" when no image exists. Should hide entirely
6. **Season info placement** — good data but awkwardly placed next to "Today at a Glance" heading. Move to top of page as a subtle banner
7. **System Health** — keep as is

## Why This Approach
Considered building a real-time health check system (ping APIs, measure latency) — deferred because it requires backend work and the dashboard is still in dev/demo phase. Considered moving KPIs to the sidebar — rejected because sidebar is shared across all pages and KPIs are overview-specific. Considered removing System Health entirely — kept because it looks professional for demos even if data is static for now. The guide text is hardcoded in the component rather than pulled from config because it describes the system's workflow (not business-specific data) and won't change between clients. Tradeoff: if the workflow changes significantly, the guide text needs a code update.

## Source Material

### Fix 1 — KPI bar (rework "Today at a Glance")
Replace the 6 large KPI cards with a compact inline stats bar at the TOP of the page (before Actions Needed). Single row, small text, no cards — just numbers with labels and colored dots. Keep only 4 metrics: Pending, Approved, Published, Brand Rules. Drop Rejected and Deleted (they're visible in the content pipeline). Season info becomes a subtle pill in this top bar.

Current (6 large cards in their own section):
```
[Pending: 1] [Approved: 0] [Published: 7] [Rejected: 1] [Brand Rules: 0] [Deleted: 0]
```

New (compact bar at top of page):
```
● 1 Pending  ● 0 Approved  ● 7 Published  ● 0 Brand Rules    Low Season — awareness building
```

If status API fails, show nothing (the bar just disappears — not critical data). This is the fallback.

### Fix 2 — Action cards clickable
Make the ActionCard body clickable using `onClick` + `useNavigate()` (not a `<Link>`, because there is already a `<Link to="/content">` wrapping the Edit button at line 82-87, and nesting `<Link>` elements creates invalid HTML). Remove the existing Edit button's `<Link>` wrapper — the whole card body now navigates to `/content`, making a separate Edit link redundant. Add `e.stopPropagation()` on the Approve and Reject buttons so they don't trigger card navigation.

### Fix 3 — Content Pipeline tab order
Change from: Approved, Rejected, Pending, Published, All
To: Approved, Rejected, Published, Pending, All

(Move Published before Pending — published posts are more relevant than unreviewed pending ones.)

### Fix 4 — How to Use section
Add a collapsible "How This Works" section at the bottom of the Overview page. Collapsed by default. Contents:

```
HOW THIS WORKS

The AI reads your business data — trips, prices, availability, seasonal events — and generates
social media draft posts. Here's the flow:

1. Generate → AI creates draft posts tailored to your current availability and brand voice
2. Review → You approve, edit, or reject each draft
3. Publish → Approved posts get published to Instagram with a branded graphic

Content Classes:
• Class A (Evergreen) — Experience highlights, destination facts, brand storytelling
• Class B (Commercial) — Promotions, availability pushes, booking encouragement
• Class C (Operational) — Schedule changes, sold-out notices, weather updates
• Class D (Reactive) — Holiday content, local events, timely posts

Brand Learnings:
When you reject a draft with a reason, the AI learns from your feedback. Over time it builds
rules like "never use urgency language" or "keep sunset posts about the experience, not the price."
```

### Fix 5 — Hide Visual Asset when no image
In ContentPipeline.tsx, in the draft detail sheet: wrap the entire Visual Asset section (image + regenerate button + AI suggestion) in a conditional. Only show when the draft has an image (`image_path` is truthy) OR the draft status is `published`. When hidden, the sheet just shows the copy sections directly — no empty placeholder.

### Fix 6 — Season in top bar
The season text from `status.season` moves into the compact stats bar (Fix 1). Remove the old season pill from the "Today at a Glance" section header (that section header is being removed anyway).

## Instructions

### Overview.tsx

1. **Remove the KpiCard component and the "Today at a Glance" section entirely** (lines ~103-127 component, lines ~335-356 section).

2. **Add a compact stats bar** as the first element inside the return `<div>`, before the Actions Needed section:
   - Single row with `flex items-center gap-6` and subtle background (`rounded-xl bg-card/50 border border-border px-5 py-3 mb-6`)
   - Each stat: colored dot (w-2 h-2 rounded-full) + number (font-bold text-lg) + label (text-xs text-muted-foreground uppercase)
   - 4 stats: Pending (yellow), Approved (green), Published (blue), Brand Rules (primary)
   - Season text on the right side with `ml-auto` — show as subtle text, no pill/badge
   - If `statusLoading`: show `<Skeleton>` placeholders
   - If `statusError`: don't render the bar at all (fallback — bar just disappears)

3. **Make action card body clickable**: In the ActionCard component:
   - Add `useNavigate()` from react-router-dom. Add `onClick` to the outer `motion.div`: `onClick={() => navigate('/content')}` with `className` adding `cursor-pointer`.
   - Remove the `<Link to="/content">` wrapper around the Edit button (lines 82-87). Replace with a plain `<button>` styled the same way, with `onClick={(e) => { e.stopPropagation(); navigate('/content'); }}`.
   - Add `e.stopPropagation()` to the Approve button's `onClick` and the Reject button's `onClick` so they don't trigger card navigation.
   - The ActionCard props need `onApprove` and `onReject` to accept the event and stop propagation — or handle it inline in the button onClick.

4. **Add "How This Works" collapsible** at the bottom (after the Activity + System Health grid):
   - Add state: `const [showGuide, setShowGuide] = useState(false)`
   - Render a button: "How This Works" with a ChevronDown icon (rotates when open)
   - When open, show a card with the guide text from Source Material above
   - Use `<Collapsible>` from shadcn/ui if available, otherwise a simple conditional render

### ContentPipeline.tsx

5. **Reorder tabs**: swap Published and Pending triggers (Published before Pending).

6. **Hide Visual Asset section when no image**: Wrap the Visual Asset `<div className="space-y-3">` (containing the AuthImage, regenerate button, and AI suggestion) in:
   ```
   {(selectedDraft.image_path || selectedDraft.status === 'published') && ( ... )}
   ```
   When no image and not published, the section doesn't render — the sheet starts with Instagram Copy directly.

## Tests

### Assertions (verify in code)
1. The kpis array in Overview.tsx must have exactly 4 entries (Pending, Approved, Published, Brand Rules) — no Rejected, no Deleted
2. The stats bar renders nothing (returns null or empty fragment) when `statusError` is truthy
3. ContentPipeline.tsx TabsTrigger order: values must be ["approved", "rejected", "published", "pending", "all"]
4. Visual Asset section is wrapped in `{(selectedDraft.image_path || selectedDraft.status === 'published') && ...}`
5. No nested `<Link>` elements inside ActionCard (the Edit button's `<Link>` wrapper must be removed)
6. The "How This Works" section must be collapsed by default (`showGuide` initial state = false)

### Manual verification
7. Overview: clicking action card body navigates to /content
8. Overview: Approve/Reject buttons work without navigating away (stopPropagation)
9. Content Pipeline: pending draft without image — Visual Asset section hidden
10. Content Pipeline: published draft — Visual Asset section visible

## Success Condition
Overview page feels clean and purposeful. KPIs are visible without dominating. Action cards lead naturally to the full review. New operators can learn the workflow from the guide section.

## Rollback
Revert Overview.tsx and ContentPipeline.tsx.
