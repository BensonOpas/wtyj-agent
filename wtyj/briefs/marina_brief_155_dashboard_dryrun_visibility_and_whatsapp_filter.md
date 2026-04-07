# BRIEF 155 — Dashboard: dry-run visibility, WhatsApp publish filter, Developer accordion

**Status:** Draft
**Files:**
- `wtyj/agents/social/social_publisher.py` (filter `whatsapp` out of `get_available_platforms`)
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/components/layout/AppLayout.tsx` (global dry-run banner)
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Settings.tsx` (move Publishing Mode toggle into a new "Developer" `AccordionSection`)

**Depends on:** Brief 142 (Docker), Brief 143 (Zernio WhatsApp DM ingestion)
**Blocks:** Demo to any prospective client where they need to see real social posts

---

## Context

User reported "when I approve a draft, it doesn't get posted." Investigation revealed:

1. `dry_run = true` in BlueMarlin's `system_settings` table. Confirmed via `GET /dashboard/api/settings/dry-run` → `{"dry_run":true}`. The setting was flipped on at some point and never flipped back.
2. The dry-run path in `wtyj/agents/social/scheduler.py:62-67` writes `status='published'` and returns `ok=true` WITHOUT calling Late SDK. So every "published" draft since this got flipped on has empty `late_post_id`, `instagram_url`, and `facebook_url` — all four (49–52) verified via the live API.
3. The dry-run state is only visible in the Settings page Publishing Mode panel — every other dashboard page shows "published" as if it worked. The user had no way to know publishes were silent failures unless they cross-checked Instagram manually.
4. WhatsApp shows up in the dashboard's per-draft platform picker because `social_publisher.get_available_platforms()` (`wtyj/agents/social/social_publisher.py:60-73`) returns every active Late account, and Zernio reports WhatsApp as connected (Brief 143 wired it for inbound DMs). Late's `posts.create` cannot publish to WhatsApp — it's a messaging channel, not a publishing surface. User explicitly asked: "delete the whatsapp button we don't post to whatsapp".

The user is NOT asking the brief to flip dry_run off — they will do that themselves via the dashboard once the new visibility is in place. The user IS asking to make dry_run visible everywhere AND move the toggle into a clearly-labeled "Developer" section so it can't be left on accidentally.

## Why This Approach

**Three small changes scoped tightly to what the user asked for. No defensive extras, no test additions, no automatic dry_run flip.**

### 1. Backend: filter WhatsApp out of `get_available_platforms`

WhatsApp DM ingestion via Zernio (Brief 143) keeps working — that path doesn't call `get_available_platforms`. The change ONLY affects which platforms appear in the dashboard's draft platform selector. One module-level constant `_DM_ONLY_PLATFORMS = {"whatsapp"}` makes the policy explicit and easy to extend if Late starts surfacing other DM-only platforms in `accounts.list`.

### 2. Frontend: dry-run banner on every dashboard page

Inject inside `AppLayout.tsx`, in the main column above the existing `<TopBar>`. AppLayout's outer element is a horizontal flex row (`flex h-screen overflow-hidden`) containing the sidebar and the main column — the banner CANNOT be a sibling of the sidebar (would become a flex item in the row). The correct injection point is the first child of the inner main column at line 245 (`<div className="flex-1 flex flex-col min-w-0 overflow-hidden">`), BEFORE the `<TopBar>` at line 246. The main column is `flex-col`, so the banner stacks naturally above the TopBar.

### 3. Frontend: move Publishing Mode toggle into a new "Developer" `AccordionSection`

The current Publishing Mode panel (Settings.tsx:490-516) is a standalone flat card with `border-l-emerald-500`. The user wants it inside a collapsible "Developer" accordion using the same `AccordionSection` component (Settings.tsx:48-111) that powers Assets & Connections (line 182) and Advanced View (line 519). The toggle UI itself stays the same — just gets wrapped in a new section.

### Out of scope (per user)

- **Flipping dry_run off in the brief**: not requested. User will do it via the dashboard after deploy.
- **Regression test for the WhatsApp filter**: not requested.
- **Removing the dry-run feature entirely**: not requested — useful for tests/demos.
- **Filtering other DM-only platforms (telegram, x DMs, bluesky)**: not requested. Add only `whatsapp` to `_DM_ONLY_PLATFORMS`.
- **Approve+Publish collapse, auto-image regeneration, anything in the publish path**: out of scope.

---

## Source Material

### Confirmed live state (verified via curl 2026-04-07)

```
GET /dashboard/api/settings/dry-run        → {"dry_run":true}
GET /dashboard/api/platforms/available     → {"platforms":["facebook","instagram","linkedin","twitter","whatsapp"]}
GET /dashboard/api/drafts                  → 7 drafts: 1 pending, 2 approved, 4 "published" (all 4 with empty late_post_id)
```

### Current `social_publisher.get_available_platforms()` (wtyj/agents/social/social_publisher.py:60-73)

```python
def get_available_platforms() -> list:
    """Return list of connected platform names."""
    client = _get_client()
    if not client:
        return []
    try:
        resp = client.accounts.list()
        platforms = []
        for acc in resp.accounts:
            if acc.isActive and acc.platform not in platforms:
                platforms.append(acc.platform)
        return platforms
    except Exception:
        return []
```

### Current Publishing Mode panel (Settings.tsx:490-516) — to be moved into a new accordion

```tsx
{/* ── Publishing Mode ─────────────────────────────────────────── */}
<div className="flex items-center justify-between p-5 rounded-2xl border-l-4 border-t border-r border-b border-border/70 border-l-emerald-500 bg-card">
  <div className="flex items-center gap-4">
    <div className="w-10 h-10 rounded-xl bg-emerald-200 dark:bg-emerald-500/25 flex items-center justify-center shrink-0">
      <Zap className="w-5 h-5 text-emerald-700 dark:text-emerald-300" />
    </div>
    <div>
      <h3 className="text-base font-semibold text-foreground">Publishing Mode</h3>
      <p className="text-sm text-muted-foreground mt-0.5">
        {dryRunData?.dry_run ? "Dry run — posts are not published to social media" : "Live — posts are published to social media"}
      </p>
    </div>
  </div>
  <button
    onClick={() => toggleDryRun.mutate()}
    disabled={toggleDryRun.isPending}
    className={cn(
      "relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none",
      dryRunData?.dry_run ? "bg-amber-500" : "bg-emerald-500"
    )}
  >
    <span className={cn(
      "inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform",
      dryRunData?.dry_run ? "translate-x-1" : "translate-x-6"
    )} />
  </button>
</div>
```

### Existing `AccordionSection` shape (Settings.tsx:48-111)

```tsx
function AccordionSection({ title, subtitle, icon: Icon, iconColor, iconBg, closedIconBg, accentBorder, headerOpenBg, closedBg, contentBg, defaultOpen = false, children }: {
  title: string;
  subtitle?: string;
  icon: React.ElementType;
  iconColor: string;
  iconBg: string;
  closedIconBg: string;
  accentBorder: string;
  headerOpenBg: string;
  closedBg: string;
  contentBg: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) { ... }
```

### Existing Advanced View accordion (Settings.tsx:519-528) — example invocation

```tsx
<AccordionSection
  title="Advanced View"
  subtitle="System context, raw configuration"
  icon={Code}
  iconColor="text-purple-700 dark:text-purple-300"
  iconBg="bg-purple-200 dark:bg-purple-500/25"
  closedIconBg="bg-purple-100 dark:bg-purple-500/15"
  accentBorder="border-l-purple-500"
  headerOpenBg="bg-purple-50 dark:bg-purple-950/60"
  closedBg="bg-purple-50/60 dark:bg-card"
  contentBg="bg-purple-50/80 dark:bg-purple-950/30"
>
```

### Existing Settings.tsx imports (lines 1-15)

```tsx
import {
  useConfig, useGoogleDriveStatus, useGoogleDriveMutations, useGoogleDriveFolders,
  useScheduleSlots, useUpcomingSchedule, useScheduleSlotMutations, useDryRun,
} from "@/hooks/use-bluemarlin";
// ...
import {
  HardDrive, CheckCircle2, XCircle, ChevronDown, ChevronUp,
  Info, Code, Map, Ship, Sun, Palette, ArrowRight, ArrowLeft, FolderOpen,
  Settings as SettingsIcon, CalendarDays, Plus, Clock, X, Mail, BrainCircuit, RefreshCw, Zap,
} from "lucide-react";
```

`useDryRun`, `cn`, `Zap`, `AccordionSection` are all already in scope. `Wrench` is NOT yet imported and needs to be added.

### Existing AppLayout.tsx structure (key lines)

```tsx
// line 8: AlertTriangle is already imported from lucide-react
// line 22: import { useConversations } from "@/hooks/use-bluemarlin";
// ...
return (
  <div className="flex h-screen overflow-hidden">          // line 238 — outer horizontal row
    <aside className="hidden md:block w-56 ...">            // line 240 — sidebar
      <SidebarContent hideActions />
    </aside>

    {/* Main Column */}
    <div className="flex-1 flex flex-col min-w-0 overflow-hidden">  // line 245 — INSERTION POINT
      <TopBar onLogout={logout} />                          // line 246 — banner goes ABOVE this
      <header className="md:hidden ...">...</header>        // mobile header (line 249)
      <main className="flex-1 overflow-y-auto p-4 md:p-8">
        <Outlet />
      </main>
    </div>
  </div>
);
```

`AlertTriangle` (line 8) is already imported from lucide-react.

### `useDryRun` hook shape (use-bluemarlin.ts:487-502)

`useDryRun()` returns `{ data, isLoading, toggle }` where `toggle` is a `useMutation` whose `onSuccess` already calls `queryClient.setQueryData(["dry-run"], data)`. So the banner will react instantly to a toggle without needing `invalidateQueries`. **DO NOT add a redundant invalidate.**

---

## Instructions

### Step 1 — Read everything before editing

Read each in full, in this order:
- `wtyj/agents/social/social_publisher.py` (lines 1-100)
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/components/layout/AppLayout.tsx` (full file, ~289 lines)
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Settings.tsx` (lines 1-15 imports, 48-111 AccordionSection, 490-516 current Publishing Mode panel, 519-528 example Advanced View invocation)
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/hooks/use-bluemarlin.ts` (lines 487-502 — confirm `useDryRun` shape)

### Step 2 — Backend: filter WhatsApp from `get_available_platforms`

In `wtyj/agents/social/social_publisher.py`, just BEFORE the existing `def get_available_platforms()` at line 60, add a module-level constant:

```python
# DM-only platforms — Zernio reports them as "connected" because we use them
# for inbound DM ingestion (Brief 143), but Late's posts.create cannot publish
# content to them. Filter them out of the publish-target list. Brief 155.
_DM_ONLY_PLATFORMS = {"whatsapp"}
```

Then replace the body of `get_available_platforms` with:

```python
def get_available_platforms() -> list:
    """Return list of connected platform names that can receive published posts.
    DM-only platforms (e.g. whatsapp) are excluded — see _DM_ONLY_PLATFORMS."""
    client = _get_client()
    if not client:
        return []
    try:
        resp = client.accounts.list()
        platforms = []
        for acc in resp.accounts:
            if not acc.isActive:
                continue
            if acc.platform in _DM_ONLY_PLATFORMS:
                continue
            if acc.platform not in platforms:
                platforms.append(acc.platform)
        return platforms
    except Exception:
        return []
```

No frontend change needed for the WhatsApp removal — `ContentPipeline.tsx` just maps over whatever the backend returns, so once `whatsapp` is gone from the list it stops appearing in the picker.

### Step 3 — Frontend: dry-run banner in AppLayout

**3a. Extend the existing import** at AppLayout.tsx line 22:

```tsx
// BEFORE
import { useConversations } from "@/hooks/use-bluemarlin";
// AFTER
import { useConversations, useDryRun } from "@/hooks/use-bluemarlin";
```

`AlertTriangle` is already imported from `lucide-react` at line 8 — do not duplicate.

**3b. Add the `DryRunBanner` component** between the existing `TopBar` definition (lines 80-133) and the `AppLayout` export (line 135):

```tsx
function DryRunBanner() {
  const { data, toggle } = useDryRun();
  if (!data?.dry_run) return null;
  return (
    <div className="w-full bg-amber-500 text-amber-950 px-4 py-2 flex items-center justify-between gap-3 text-sm font-medium border-b border-amber-600 shrink-0">
      <div className="flex items-center gap-2 min-w-0">
        <AlertTriangle className="w-4 h-4 shrink-0" />
        <span className="truncate">
          Dry-run mode is ON — posts are marked &quot;published&quot; but nothing is actually sent to social media.
        </span>
      </div>
      <button
        onClick={() => toggle.mutate()}
        disabled={toggle.isPending}
        className="ml-2 bg-amber-950 text-amber-100 px-3 py-1 rounded font-semibold hover:bg-amber-900 disabled:opacity-50 shrink-0"
      >
        {toggle.isPending ? "Turning off..." : "Turn off dry-run"}
      </button>
    </div>
  );
}
```

Notes:
- `shrink-0` is required because the parent column has `overflow-hidden` and `<main>` is `flex-1 overflow-y-auto` — without it the banner could be squeezed.
- No `sticky top-0 z-50` because TopBar already has `sticky top-0 z-20`. Stacking sticky elements inside the same scroll context is awkward; let the banner be a normal block at the top of the column.
- `border-b border-amber-600` separates the banner from TopBar visually.

**3c. Insert `<DryRunBanner />` into the main column** at AppLayout.tsx line 245:

```tsx
// BEFORE
{/* Main Column */}
<div className="flex-1 flex flex-col min-w-0 overflow-hidden">
  <TopBar onLogout={logout} />

// AFTER
{/* Main Column */}
<div className="flex-1 flex flex-col min-w-0 overflow-hidden">
  <DryRunBanner />
  <TopBar onLogout={logout} />
```

The banner appears on every route (because every route renders inside `<Outlet />` inside this main column) and on every screen size (TopBar is `hidden md:flex`, mobile `<header>` is `md:hidden`, but the banner has no breakpoint prefix so it shows on both).

### Step 4 — Frontend: Developer accordion in Settings

**4a. Add `Wrench` to the lucide-react imports** at Settings.tsx lines 11-15:

```tsx
// BEFORE
import {
  HardDrive, CheckCircle2, XCircle, ChevronDown, ChevronUp,
  Info, Code, Map, Ship, Sun, Palette, ArrowRight, ArrowLeft, FolderOpen,
  Settings as SettingsIcon, CalendarDays, Plus, Clock, X, Mail, BrainCircuit, RefreshCw, Zap,
} from "lucide-react";
// AFTER
import {
  HardDrive, CheckCircle2, XCircle, ChevronDown, ChevronUp,
  Info, Code, Map, Ship, Sun, Palette, ArrowRight, ArrowLeft, FolderOpen,
  Settings as SettingsIcon, CalendarDays, Plus, Clock, X, Mail, BrainCircuit, RefreshCw, Zap, Wrench,
} from "lucide-react";
```

**4b. Replace the existing Publishing Mode panel** (Settings.tsx:490-516, the entire `{/* ── Publishing Mode ──...── */}` block including its outer `<div>`) with a new `<AccordionSection>` titled "Developer". The toggle UI moves INSIDE the accordion content:

```tsx
{/* ── Developer ──────────────────────────────────────────────── */}
<AccordionSection
  title="Developer"
  subtitle="Dry-run mode and experimental settings"
  icon={Wrench}
  iconColor="text-slate-700 dark:text-slate-300"
  iconBg="bg-slate-200 dark:bg-slate-500/25"
  closedIconBg="bg-slate-100 dark:bg-slate-500/15"
  accentBorder="border-l-slate-500"
  headerOpenBg="bg-slate-50 dark:bg-slate-900/60"
  closedBg="bg-slate-50/60 dark:bg-card"
  contentBg="bg-slate-50/80 dark:bg-slate-900/30"
>
  <div className="space-y-4">
    {/* Publishing Mode toggle */}
    <div className="flex items-center justify-between p-4 rounded-xl bg-muted/40 border border-border">
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-emerald-500/10 flex items-center justify-center shrink-0">
          <Zap className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
        </div>
        <div>
          <p className="text-sm font-semibold text-foreground">Publishing Mode</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {dryRunData?.dry_run ? "Dry run — posts are not published to social media" : "Live — posts are published to social media"}
          </p>
        </div>
      </div>
      <button
        onClick={() => toggleDryRun.mutate()}
        disabled={toggleDryRun.isPending}
        className={cn(
          "relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none shrink-0",
          dryRunData?.dry_run ? "bg-amber-500" : "bg-emerald-500"
        )}
      >
        <span className={cn(
          "inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform",
          dryRunData?.dry_run ? "translate-x-1" : "translate-x-6"
        )} />
      </button>
    </div>
  </div>
</AccordionSection>
```

Style notes:
- Slate color theme (consistent with the existing accordion color pattern but distinct from blue/teal/purple/emerald already in use).
- Inner toggle card uses `p-4 rounded-xl bg-muted/40 border border-border` matching the inner-card pattern of other accordions (e.g. the Google Drive sub-card at Settings.tsx:196-199).
- Icon row downgrades from `w-10 h-10`+`w-5 h-5` (top-level card) to `w-9 h-9`+`w-4 h-4` (inner card) — same downgrade other accordions use for nested items.
- Toggle button identical to the original.

### Step 5 — Local typecheck (dashboard repo)

```bash
cd ~/Projects/wetakeyourjob-dashboard
pnpm typecheck 2>&1 | tail -20
```

If `pnpm typecheck` is not the correct script, check `package.json` scripts and use whatever produces TypeScript errors. Expected: zero errors. If any error references AppLayout.tsx or Settings.tsx, fix before committing.

### Step 6 — Commit + push (both repos)

```bash
# Backend
cd /Users/benson/Projects/bluemarlin-agent
git add wtyj/agents/social/social_publisher.py wtyj/briefs/marina_brief_155_dashboard_dryrun_visibility_and_whatsapp_filter.md
git commit -m "Brief 155 — filter whatsapp from publish targets"
git push

# Dashboard
cd ~/Projects/wetakeyourjob-dashboard
git add artifacts/dashboard/src/components/layout/AppLayout.tsx artifacts/dashboard/src/pages/Settings.tsx
git commit -m "Brief 155 — dry-run banner + Developer accordion in Settings"
git push
```

### Step 7 — Deploy backend to VPS

```bash
ssh root@108.61.192.52 "
  cd /root && git pull
  cd /root/clients/bluemarlin && docker compose down
  cd /root/clients/adamus && docker compose down
  cd /root/clients/bluemarlin && docker compose build && docker compose up -d
  cd /root/clients/adamus && docker compose up -d
  docker ps --filter name=wtyj- --format 'table {{.Names}}\t{{.Status}}'
"
```

### Step 8 — Verify backend filter via curl

```bash
curl -sf -X POST 'https://api.wetakeyourjob.com/dashboard/api/login' \
  -H 'Content-Type: application/json' -d '{"password":"123"}' -o /tmp/dash_login.json
TOKEN=$(python3 -c 'import json; print(json.load(open("/tmp/dash_login.json"))["token"])')

curl -sf 'https://api.wetakeyourjob.com/dashboard/api/platforms/available' \
  -H "Authorization: Bearer $TOKEN" -o /tmp/dash_platforms_after.json
cat /tmp/dash_platforms_after.json
# Expected: {"platforms":["facebook","instagram","linkedin","twitter"]}  (no "whatsapp")
```

### Step 9 — Wait for Replit auto-deploy + manual UI verification

Replit auto-pulls from git on push to main. Within ~2 minutes, hard-refresh `https://bluemarlindashboard.replit.app/` and verify:

1. **Amber dry-run banner appears at the top of every page** (because dry_run is still true). The "Turn off dry-run" button is visible.
2. **Settings page** — old standalone Publishing Mode panel is gone. New "Developer" slate-themed accordion appears in its place. Click to expand → shows the Publishing Mode toggle inside. Toggle still works.
3. **ContentPipeline page** — open draft 53 (pending) or any approved draft. Platform picker shows ONLY Facebook, Instagram, LinkedIn, Twitter. No WhatsApp button.

Once verified visually, tell the user to flip the toggle off via the Developer accordion if they want to actually publish — or via the banner's "Turn off dry-run" button. The brief does NOT flip dry_run automatically (per user instruction).

---

## Tests

No new automated tests. The existing `test_get_available_platforms_returns_all` in `wtyj/tests/social/test_144_multi_platform_publish.py` (line 31) mocks accounts for `instagram, facebook, linkedin, twitter` — none of which are in `_DM_ONLY_PLATFORMS`, so it remains green. Run the social regression once after the backend change to confirm:

```bash
cd /Users/benson/Projects/bluemarlin-agent
python3 -m pytest wtyj/tests/social/ -q --tb=short
```

Expected: same pass count as before, zero new failures.

Manual verification per Step 9.

---

## Success Condition

**One sentence:** WhatsApp is no longer in the dashboard's publish-platform picker, an amber dry-run banner appears at the top of every dashboard page while dry_run is on, and the Publishing Mode toggle now lives inside a collapsible "Developer" `AccordionSection` styled the same way as the other settings accordions.

---

## Rollback

Each change is independent and revertible:

```bash
# Backend
cd /Users/benson/Projects/bluemarlin-agent
git revert <commit-sha>
ssh root@108.61.192.52 "cd /root && git pull && cd /root/clients/bluemarlin && docker compose down && docker compose build && docker compose up -d && cd /root/clients/adamus && docker compose down && docker compose up -d"

# Dashboard
cd ~/Projects/wetakeyourjob-dashboard
git revert <commit-sha>
git push
# Replit auto-deploys the revert
```

---

## Risks I want flagged before execution

1. **Color inventory (verified during round 1 review).** Settings.tsx accordions currently use: **blue** (Assets & Connections, line 182), **indigo** (Schedule & Automation, line 295), **amber** (Capacity & Availability, line 379), **rose** (Email Integration, line 406), **purple** (Advanced View, line 519), and **emerald** by the standalone Publishing Mode panel being replaced. **Slate is verified unused** — that's why the brief picks it. If for some reason slate doesn't work, fallback to one of: **orange**, **teal**, **cyan**, **sky**, **zinc**, **stone**, **neutral**, **gray** (all confirmed unused). DO NOT use rose or indigo as fallbacks — they clash.
2. **`pnpm typecheck` may not be the right script name.** Verify in dashboard repo's `package.json` scripts before assuming.
3. **Replit auto-deploy lag.** If the banner doesn't appear after ~2 minutes of pushing the dashboard repo, that's a Replit deploy issue, not a brief issue.
