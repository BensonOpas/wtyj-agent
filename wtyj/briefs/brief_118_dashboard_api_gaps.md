# BRIEF 118 — Dashboard API Gaps: Suggest Reply, Drive Sync, Dry-Run, Rule Edit
**Status:** Draft | **Depends on:** Brief 117 (complete, merged) | **Blocks:** —

**Frontend files (~/Projects/wetakeyourjob-dashboard/):**
- `artifacts/dashboard/src/pages/Messages.tsx`
- `artifacts/dashboard/src/pages/Settings.tsx`
- `artifacts/dashboard/src/pages/BrandTraining.tsx`
- `artifacts/dashboard/src/lib/api.ts`
- `artifacts/dashboard/src/hooks/use-bluemarlin.ts`

## Context
Four backend API endpoints have no frontend coverage:
1. Messages.tsx calls `/internal-api/suggest-reply` which doesn't exist on the real backend — it's a Replit-local endpoint that 404s in production. Fix: remove the suggest feature entirely (there is no backend for it).
2. Google Drive folder picker + sync: `getGoogleFolders`, `setGoogleFolder`, `syncGoogleDrive` exist in api.ts and hooks but Settings.tsx doesn't use them — it only shows connect/disconnect.
3. `GET/POST /settings/dry-run`: backend supports toggling dry-run mode but no UI exists.
4. `PUT /training/profile/{rule_id}`: backend supports editing brand rules but only delete + add exists in frontend.

## Why This Approach
Fix 1 removes dead code. Fixes 2-4 wire existing backend endpoints to UI. No new backend work needed. All API methods and hooks already exist except dry-run (needs new api.ts methods + hook) and updateBrandRule (needs new api.ts method + hook mutation).

## Source Material

### Fix 1 — Remove broken suggest-reply from Messages.tsx

**Remove the `handleSuggest` function (lines 207-240).** It calls `/internal-api/suggest-reply` which doesn't exist.

**Remove all state and UI related to suggest:**
- State: `suggestLoading` (find with grep, remove useState)
- The "Suggest" button in the email compose modal that calls `handleSuggest`
- The `Sparkles` and `Loader2` imports if only used by suggest (verify before removing)

Search for `suggestLoading`, `handleSuggest`, and `Suggest` in Messages.tsx to find all references.

### Fix 2 — Google Drive folder picker + sync in Settings.tsx

**In Settings.tsx**, the Assets & Connections accordion (line 162-226) shows Google Drive connect/disconnect. When connected and no folder selected, it says "Connected — no folder selected" but provides no way to pick one.

**Add to Settings.tsx imports (line 2):**
Add `useGoogleDriveFolders` to the existing import from `@/hooks/use-bluemarlin`.

**Add hooks in the component (after line 119):**
```tsx
const { data: driveFolders } = useGoogleDriveFolders(!!driveStatus?.connected);
const { setFolder, sync } = useGoogleDriveMutations();  // already destructures disconnect
```
Note: `disconnect` is already destructured from `useGoogleDriveMutations()` on line 119. Change that line to destructure all three:
```tsx
const { disconnect: driveDisconnect, setFolder: driveSetFolder, sync: driveSync } = useGoogleDriveMutations();
```

**Add folder picker + sync button after the Google Drive connect/disconnect block (after line 206), inside the `driveStatus?.connected` condition.** Insert before the Asset Library link (line 209):
```tsx
{/* Folder picker */}
{driveStatus?.connected && (
  <div className="p-4 rounded-xl bg-muted/40 border border-border space-y-3">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm font-semibold text-foreground">Sync Folder</p>
        <p className="text-xs text-muted-foreground">
          {driveStatus.folder_id ? "Syncing from selected folder" : "Select a folder to sync photos from"}
        </p>
      </div>
      {driveStatus.folder_id && (
        <Button
          size="sm"
          variant="outline"
          onClick={() => driveSync.mutate()}
          disabled={driveSync.isPending}
          className="border-border"
        >
          <RefreshCw className={cn("w-3.5 h-3.5 mr-1.5", driveSync.isPending && "animate-spin")} />
          {driveSync.isPending ? "Syncing…" : "Sync Now"}
        </Button>
      )}
    </div>
    {driveFolders && driveFolders.length > 0 && (
      <div className="grid grid-cols-2 gap-2">
        {driveFolders.map((f) => (
          <button
            key={f.id}
            onClick={() => driveSetFolder.mutate(f.id)}
            disabled={driveSetFolder.isPending}
            className={cn(
              "flex items-center gap-2 p-3 rounded-lg border text-left text-sm transition-all",
              driveStatus.folder_id === f.id
                ? "border-blue-500 bg-blue-500/10 text-foreground font-medium"
                : "border-border bg-muted/30 text-muted-foreground hover:border-border/80"
            )}
          >
            <FolderOpen className="w-4 h-4 shrink-0" />
            <span className="truncate">{f.name}</span>
            {driveStatus.folder_id === f.id && <CheckCircle2 className="w-3.5 h-3.5 text-blue-400 ml-auto shrink-0" />}
          </button>
        ))}
      </div>
    )}
  </div>
)}
```

**Add `RefreshCw` to the lucide-react import** in Settings.tsx.

### Fix 3 — Dry-run toggle in Settings.tsx

**Add to api.ts** (after the `syncGoogleDrive` method, before `// --- Training ---`):
```tsx
// --- Settings ---

getDryRun: async (): Promise<{ dry_run: boolean }> => {
  const res = await fetch(`${BASE_URL}/settings/dry-run`, { headers: getHeaders() });
  return handleResponse(res);
},

toggleDryRun: async (): Promise<{ dry_run: boolean }> => {
  const res = await fetch(`${BASE_URL}/settings/dry-run`, {
    method: "POST",
    headers: getHeaders(),
  });
  return handleResponse(res);
},
```

**Add hook to use-bluemarlin.ts** (after `useGoogleDriveMutations`):
```tsx
export function useDryRun() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["dry-run"],
    queryFn: api.getDryRun,
  });
  const toggle = useMutation({
    mutationFn: api.toggleDryRun,
    onSuccess: (data) => {
      queryClient.setQueryData(["dry-run"], data);
      toast.success(data.dry_run ? "Dry-run mode ON — publishing disabled" : "Dry-run mode OFF — publishing is live");
    },
    onError: (err: unknown) => toast.error(`Toggle failed: ${getErrorMessage(err)}`),
  });
  return { data: query.data, isLoading: query.isLoading, toggle };
}
```

**Add to Settings.tsx**, import `useDryRun` from hooks. Add hook call:
```tsx
const { data: dryRunData, toggle: toggleDryRun } = useDryRun();
```

**Add dry-run toggle section before the Advanced View accordion** (before `{/* ── Advanced View */}`):
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
        {dryRunData?.dry_run ? "Dry run — posts are not published to Instagram" : "Live — posts are published to Instagram"}
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

**Add `Zap` to the lucide-react import** in Settings.tsx.

### Fix 4 — Edit brand rule in BrandTraining.tsx

**Add to api.ts** (after `deleteBrandRule`):
```tsx
updateBrandRule: async (id: number, rule: string): Promise<{ ok: boolean }> => {
  const res = await fetch(`${BASE_URL}/training/profile/${id}`, {
    method: "PUT",
    headers: getHeaders(),
    body: JSON.stringify({ rule }),
  });
  return handleResponse(res);
},
```

**Add mutation to use-bluemarlin.ts** in `useBrandProfileMutations` (after `addRule` mutation, before the return):
```tsx
const update = useMutation({
  mutationFn: ({ id, rule }: { id: number; rule: string }) => api.updateBrandRule(id, rule),
  onSuccess: () => {
    toast.success("Rule updated");
    queryClient.invalidateQueries({ queryKey: ["brand-profile"] });
  },
  onError: (err: unknown) => toast.error(`Failed to update rule: ${getErrorMessage(err)}`),
});
```
Update the return: `return { remove, addRule, update };`

**In BrandTraining.tsx**, add edit functionality to each rule. Add state:
```tsx
const [editingRule, setEditingRule] = useState<{ id: number; text: string } | null>(null);
```

Add `update` to destructure: `const { remove: removeRule, addRule, update: updateRule } = useBrandProfileMutations();`

Add `Pencil` to the lucide-react import.

Replace the rule row (lines 208-229) with a version that supports inline edit:
```tsx
<div key={rule.id} className="flex items-start gap-3 p-3 rounded-lg bg-muted/30 border border-border group">
  <meta.icon className={cn("w-3.5 h-3.5 mt-0.5 shrink-0", meta.color)} />
  <div className="flex-1 min-w-0">
    {editingRule?.id === rule.id ? (
      <div className="space-y-2">
        <Textarea
          value={editingRule.text}
          onChange={(e) => setEditingRule({ ...editingRule, text: e.target.value })}
          className="text-sm min-h-[60px] bg-background"
        />
        <div className="flex gap-2">
          <Button size="sm" onClick={() => { updateRule.mutate({ id: rule.id, rule: editingRule.text }); setEditingRule(null); }} disabled={updateRule.isPending} className="bg-primary text-primary-foreground hover:bg-primary/90 text-xs h-7">Save</Button>
          <Button size="sm" variant="ghost" onClick={() => setEditingRule(null)} className="text-xs h-7">Cancel</Button>
        </div>
      </div>
    ) : (
      <>
        <p className="text-sm text-foreground/80">{rule.rule}</p>
        <div className="flex items-center gap-2 mt-1">
          <span className={cn(
            "text-xs px-1.5 py-0.5 rounded",
            rule.source === "manual" ? "bg-blue-500/10 text-blue-400" : "bg-muted text-muted-foreground/60"
          )}>
            {rule.source}
          </span>
        </div>
      </>
    )}
  </div>
  {editingRule?.id !== rule.id && (
    <div className="flex items-center gap-1 shrink-0">
      <button
        onClick={() => setEditingRule({ id: rule.id, text: rule.rule })}
        className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded text-muted-foreground/60 hover:text-primary hover:bg-primary/10"
        title="Edit rule"
      >
        <Pencil className="w-3.5 h-3.5" />
      </button>
      <button
        onClick={() => removeRule.mutate(rule.id)}
        disabled={removeRule.isPending}
        className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded text-muted-foreground/60 hover:text-rose-400 hover:bg-rose-500/10"
        title="Remove rule"
      >
        <Trash2 className="w-3.5 h-3.5" />
      </button>
    </div>
  )}
</div>
```

## Tests
Code-level assertions (verify after applying):
1. No `/internal-api/suggest-reply` in Messages.tsx
2. No `handleSuggest` function in Messages.tsx
3. No `suggestLoading` state in Messages.tsx
4. Settings.tsx imports `useGoogleDriveFolders` and `useDryRun`
5. Settings.tsx renders "Sync Folder" text and "Sync Now" button
6. Settings.tsx renders "Publishing Mode" section with toggle
7. api.ts has `getDryRun` and `toggleDryRun` methods
8. api.ts has `updateBrandRule` method
9. use-bluemarlin.ts `useDryRun` hook exists
10. use-bluemarlin.ts `useBrandProfileMutations` returns `update`
11. BrandTraining.tsx has `editingRule` state and `Pencil` import
12. BrandTraining.tsx renders `<Textarea` for inline editing

## Success Condition
All four gaps closed: suggest-reply removed, Drive folder picker + sync shown, dry-run toggle visible, brand rules editable inline.

## Rollback
Revert all 5 frontend files.
