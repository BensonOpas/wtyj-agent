# OUTPUT 172 — Reconnect sweep additions after SR's dashboard merge

## What was done

Resolution of a merge conflict between the 9-brief sweep (briefs 163-171) and SR's 18 independent dashboard commits in Replit. Instead of hand-merging the conflicts in Replit's UI (high risk across 5 overlapping files), force-reset origin/master to the pre-sweep tag, let SR push cleanly, then surgically re-added the handful of sweep pieces SR couldn't have known about because they depend on sweep backend work.

### Part 1 — Merge resolution (before the brief)

1. On this Mac: `git push origin +23fd2f6...:master` to dashboard repo — force-reset origin to the pre-sweep tag. My 4 sweep dashboard commits (`2c3d31e`, `1af52df`, `4ba7734`, `c487c23`) preserved locally in branch `backup-sweep-dashboard-commits`.
2. In Replit: Benson aborted the merge, refreshed git state, pushed SR's 18 commits. Origin/master is now at `d430f61` — SR's version.
3. Backend repo unaffected — all 9 sweep brief commits still on main + deployed to VPS.

### Part 2 — Brief 172 execution

**Backend (`bluemarlin-agent`):**

- `wtyj/shared/state_registry.py` — added `delete_escalation(id) -> bool` helper. Hard-deletes a row from `pending_notifications` table. Returns True if a row was affected.
- `wtyj/dashboard/api.py` — added `DELETE /escalations/{escalation_id}` endpoint named `delete_escalation_endpoint` (to avoid collision with the state_registry function name import). Returns 404 if the row doesn't exist.
- `wtyj/tests/marina/test_172_reconnect.py` — 3 new tests: removes-row, nonexistent-returns-false, endpoint-source-guard.

**Frontend (`wetakeyourjob-dashboard`):**

- `artifacts/dashboard/src/lib/api.ts`:
  - Added `channel?: string` to the `Conversation` interface (fixes 12 pre-existing typecheck errors in Messages.tsx that referenced `conv.channel` without a type)
  - Added new `CustomerFile` interface matching the backend shape (id, display_name, identifiers, recent_interactions)
  - Added `deleteConversation` method (calls `DELETE /messages/conversations/{phone}` from Brief 165)
  - Added `getCustomerByIdentifier` method (calls `GET /customers/by-identifier/{type}/{value}` from Brief 167)
  - Added `deleteEscalation` method (calls the new `DELETE /escalations/{id}` from Brief 172)

- `artifacts/dashboard/src/hooks/use-bluemarlin.ts`:
  - Updated the `publish` mutation to use `refetchType: "all"` on both `drafts` and `status` query invalidations (Brief 165 refinement that forces stats cards to re-fetch immediately, not on the 30s `refetchInterval`)
  - Added `useDeleteConversation` hook — wraps `api.deleteConversation` with toast success/error + cache invalidation
  - Added `useCustomerByIdentifier` hook — React Query `useQuery` with `enabled: !!type_ && !!value` guard
  - Added `useDeleteEscalation` hook — same pattern as delete conversation

- `artifacts/dashboard/src/pages/Messages.tsx`:
  - Added `Clock` to the lucide-react icon imports
  - Added `useDeleteConversation` to the hook import
  - Replaced the `handleDelete` stub (which had a "API endpoint for delete coming soon" comment) with a real `deleteConv.mutate(phone)` call wrapped in a `window.confirm` prompt
  - Updated the system message rendering block to split `isBooking` into `isBookingConfirmed` (green `CheckCircle2`) and `isHoldPlaced` (amber `Clock`), plus a unified `isBookingEvent` for the click handler. This is the Brief 163 re-addition — tied to the backend change in `social_agent.py:716` where upfront/deposit bookings now write "Hold placed — awaiting payment" instead of "Booking confirmed".

- `artifacts/dashboard/src/pages/Escalations.tsx`:
  - Added `useCustomerByIdentifier` and `useDeleteEscalation` to the hook import
  - Replaced the `handleDeleteEscalation` stub with a real `deleteEsc.mutate(Number(id))` call wrapped in `window.confirm`
  - Added a `customerFile` lookup right after `const selected = ...`. Identifier type picked based on escalation channel: `"email"` for email escalations, `"wa_conversation_id"` for 24-char hex (Zernio), `"phone"` otherwise.
  - Updated the PHONE field display (previously `{parsed.phone || selected.customer_id}`) to prefer a real `phone` typed identifier from the customer file when available, with fallback to the old behavior. Also shows the customer `display_name` below the phone when known.

### Overview.tsx — no re-apply needed

SR's Overview.tsx `UrgentBar` returns `null` when `drafts.length === 0` (instead of showing "All clear"). This satisfies Benson's earlier "Home dashboard still says 'All clear' while cards show open escalations" complaint by simply not showing the banner when there are no drafts. Brief 172 correctly left Overview.tsx alone.

## Test results

```
$ python3 -m pytest wtyj/tests/marina/test_172_reconnect.py -v
3 passed in 0.03s

$ python3 -m pytest wtyj/tests/ -q --tb=line
812 passed, 6 warnings in 4.92s
```

**812 passing / 0 failures.** Baseline was 809 (post-sweep). 809 + 3 = 812. ✓

## Frontend typecheck

```
$ cd artifacts/dashboard && pnpm typecheck
src/pages/ContentPipeline.backup.tsx(112,9): error TS2741: Property 'scheduled' is missing...
```

**1 pre-existing error** (in a `.backup.tsx` file from Brief 155 era). Down from **13 errors** before Brief 172 — the 12 Messages.tsx `conv.channel` errors all resolved via the `channel?: string` addition to the Conversation interface.

## Unexpected findings

### 1. Name collision between state_registry helper and endpoint function

Initially drafted the endpoint as `async def delete_escalation(escalation_id: int)`, but `state_registry.delete_escalation` is already imported in the same file. Python wouldn't have thrown an error (FastAPI identifies routes by decorator + path, not function name), but it's visually confusing and could cause linter warnings or autocomplete weirdness. Renamed to `delete_escalation_endpoint` to match FastAPI convention where the route handler has a suffix when the underlying function shares a name.

### 2. SR's archive vs delete flow is well-designed

The delete button in SR's Messages.tsx is only rendered when `isHidden` is true — i.e., you can only permanently delete a conversation after first archiving it. This is a nice two-step UX: hide first (localStorage, reversible), then delete (backend, permanent). My original Brief 165 added a one-step trash button. SR's version is better. Brief 172 wires SR's existing button to the backend rather than adding another one.

### 3. Typecheck dropped from 13 to 1

The 12 Messages.tsx typecheck errors about `conv.channel` had been present since Brief 156 era (when LinkedIn was removed but the Conversation type wasn't updated). Brief 171 was supposed to fix this with `channel?: string` but got reverted in the merge dance. Brief 172's re-addition closes the loop. The only remaining typecheck error is in `ContentPipeline.backup.tsx` which is a genuine backup file — not load-bearing.

## Deployment

- Backend committed `262b3de`, pushed to main, deployed to both containers, both healthy
- Dashboard committed `fd00a69`, pushed to master, Replit auto-deploys
- Verified: `curl http://localhost:8001/health` and `/8002/health` return `{"status":"ok"}` post-deploy

## Files modified

| Repo | File | Change |
|------|------|--------|
| bluemarlin-agent | `wtyj/shared/state_registry.py` | `delete_escalation(id)` helper |
| bluemarlin-agent | `wtyj/dashboard/api.py` | `DELETE /escalations/{escalation_id}` endpoint |
| bluemarlin-agent | `wtyj/tests/marina/test_172_reconnect.py` | **NEW** — 3 tests |
| bluemarlin-agent | `wtyj/briefs/marina_brief_172_reconnect_sweep_after_sr_merge.md` | **NEW** — brief |
| wetakeyourjob-dashboard | `artifacts/dashboard/src/lib/api.ts` | Conversation.channel + 3 new methods + CustomerFile interface |
| wetakeyourjob-dashboard | `artifacts/dashboard/src/hooks/use-bluemarlin.ts` | 3 new hooks + publish refetchType |
| wetakeyourjob-dashboard | `artifacts/dashboard/src/pages/Messages.tsx` | Clock import + real handleDelete + isHoldPlaced rendering |
| wetakeyourjob-dashboard | `artifacts/dashboard/src/pages/Escalations.tsx` | customerFile lookup + real handleDeleteEscalation + PHONE field resolution |

## Brief 172 is complete.
