# BRIEF 113 — Output Review Fixes
**Status:** Draft | **Depends on:** Briefs 111-112 | **Blocks:** —

**Backend files (~/Projects/bluemarlin-agent/):**
- `bluemarlin/dashboard/api.py`
- `bluemarlin/tests/social/test_113_session_fixes.py` (NEW)

**Frontend files (~/Projects/wetakeyourjob-dashboard/):**
- `artifacts/dashboard/src/lib/api.ts`
- `artifacts/dashboard/src/pages/Create.tsx`
- `artifacts/dashboard/src/pages/ContentPipeline.tsx`
- `artifacts/dashboard/src/components/ui/status-badge.tsx`

## Context
Output review of this session's work found 3 blocking issues:
1. `DraftStatus` type missing "scheduled" — TypeScript considers `draft.status === "scheduled"` always false
2. Create page platform toggle is dead UI — toggles render but never send platforms to backend
3. Zero tests for 6 new API endpoints, 3 new DB functions, 5 system event calls

## Why This Approach
Straightforward fixes — type addition, field addition, and tests. No architectural decisions.

## Source Material

**DraftStatus (api.ts:13):** `"pending" | "approved" | "rejected" | "published" | "deleted"` — missing `"scheduled"`

**Record<DraftStatus> mappings that must include "scheduled":**
- `ContentPipeline.tsx:180` — `statusOrder` record: `{ pending: 0, approved: 1, rejected: 2, published: 3, deleted: 4 }`
- `status-badge.tsx:4` — `statusConfig` record: missing `scheduled` entry (has fallback `?? statusConfig.pending` at line 43, but TypeScript will error)

**ManualDraftRequest (api.py:910-915):** missing `platforms` field. Default should NOT be hardcoded — read from `client.json` via `config_loader.get_raw().get("social_content", {}).get("platforms", ["instagram"])`.

**handleCreate (Create.tsx:43-58):** does not include `platforms` in mutation payload.

**createManualDraft data type (api.ts):** missing `platforms` field.

## Instructions

### Fix 1 — DraftStatus type + downstream Records (frontend repo)

1. In `artifacts/dashboard/src/lib/api.ts:13`, change to:
   ```ts
   export type DraftStatus = "pending" | "approved" | "rejected" | "published" | "deleted" | "scheduled";
   ```

2. In `artifacts/dashboard/src/pages/ContentPipeline.tsx:180`, change to:
   ```ts
   const statusOrder: Record<DraftStatus, number> = { pending: 0, approved: 1, rejected: 2, published: 3, scheduled: 4, deleted: 5 };
   ```

3. In `artifacts/dashboard/src/components/ui/status-badge.tsx`, add after the `deleted` entry (line 39):
   ```ts
   scheduled: {
     dot: "bg-purple-500",
     text: "text-purple-600 dark:text-purple-400",
     bg: "bg-purple-500/10",
     border: "border-purple-500/20",
     label: "Scheduled",
   },
   ```

### Fix 2 — Wire Create page platforms

1. In `bluemarlin/dashboard/api.py:910-915`, add `platforms: list = []` to `ManualDraftRequest` (empty = use config default)

2. In `bluemarlin/dashboard/api.py`, after line 930 (`update_draft_status`), add:
   ```python
   plats = req.platforms or config_loader.get_raw().get("social_content", {}).get("platforms", ["instagram"])
   state_registry.update_draft_platforms(draft_id, plats)
   ```

3. In `artifacts/dashboard/src/lib/api.ts`, in `createManualDraft` data type, add `platforms?: string[]`

4. In `artifacts/dashboard/src/pages/Create.tsx:46-53`, add `platforms` to the mutation payload

### Fix 3 — Tests (backend repo)

Write `bluemarlin/tests/social/test_113_session_fixes.py` with 8 tests:

1. **test_wa_list_conversations** — `wa_store_message("111", "user", "hello")`, `wa_store_message("222", "user", "world")`, `wa_save_booking_state("111", {"customer_name": "Alice"}, {}, [])`. Call `wa_list_conversations()`. Assert: len==2, result[0]["phone"]=="222", result[1]["phone"]=="111", result[1]["customer_name"]=="Alice".

2. **test_wa_get_full_history** — Insert 5 messages for "333": `wa_store_message("333", "user", f"msg{i}")` for i in 1..5. Call `wa_get_full_history("333")`. Assert: len==5, result[0]["text"]=="msg1", result[4]["text"]=="msg5", result[0]["role"]=="user".

3. **test_get_all_escalations** — `create_pending_notification("escalation", "email", "a@b.com", "Customer A", "subj A", "body A")`, then same for "Customer B". Call `get_all_escalations()`. Assert: len==2, result[0]["customer_name"]=="Customer B" (newest first).

4. **test_create_pending_notification** — `id = create_pending_notification("escalation", "whatsapp", "555", "Test Customer", "test subject", "test body")`. Assert: id > 0. `esc = get_all_escalations()`. Assert: esc[0]["status"]=="pending", esc[0]["customer_name"]=="Test Customer", esc[0]["channel"]=="whatsapp".

5. **test_update_notification_status** — Create notification, get id. `ok = update_notification_status(id, "resolved")`. Assert: ok is True. `esc = get_all_escalations()`. Assert: esc[0]["status"]=="resolved".

6. **test_manual_draft_with_platforms** — `id = save_content_draft(content_class="D", instagram_caption="manual test", facebook_caption="fb", hashtags=["#test"], visual_suggestion="", reasoning="manual")`. `update_draft_status(id, "approved")`. `update_draft_platforms(id, ["instagram", "facebook"])`. `drafts = get_content_drafts()`. `d = next(x for x in drafts if x["id"]==id)`. Assert: d["status"]=="approved", d["platforms"]==["instagram", "facebook"].

7. **test_schedule_slots_roundtrip** — `save_schedule_slots([{"day_of_week": "Tuesday", "time_utc": "16:00"}, {"day_of_week": "Friday", "time_utc": "10:00"}])`. `slots = get_schedule_slots()`. Assert: len==2, slots[0]["day_of_week"]=="Tuesday", slots[0]["time_utc"]=="16:00", slots[1]["day_of_week"]=="Friday".

8. **test_system_event_in_history** — `wa_store_message("777", "system", "Booking confirmed: test")`. `history = wa_get_full_history("777")`. Assert: len==1, history[0]["role"]=="system", history[0]["text"]=="Booking confirmed: test".

## Tests
8 tests as listed above. Each asserts specific known values.

## Success Condition
1. TypeScript compiles with no errors — DraftStatus includes "scheduled", all Records updated
2. Create page platform toggles send selected platforms to backend, draft gets correct platforms_json
3. All 8 tests pass: `cd bluemarlin && pytest tests/social/test_113_session_fixes.py -v`

## Rollback
**Backend repo (bluemarlin-agent):** `git revert` the api.py commit. Delete `tests/social/test_113_session_fixes.py`. Redeploy VPS.
**Frontend repo (wetakeyourjob-dashboard):** `git revert` the commit touching api.ts, Create.tsx, ContentPipeline.tsx, status-badge.tsx. Pull in Replit.
