# OUTPUT 156 — Discontinue LinkedIn + per-platform Twitter caption

## What was done

Executed Brief 156 end-to-end across both repos:

### Backend (wtyj/)

1. **`wtyj/agents/social/social_publisher.py`**
   - Renamed `_DM_ONLY_PLATFORMS` → `_EXCLUDED_PLATFORMS`
   - Added `"linkedin"` to the set with a comment explaining "Discontinued for our use case (Brief 156)"
   - Updated `get_available_platforms()` docstring + the one in-function reference
   - Added Twitter safety truncate to `publish_to_platform()`: when `platform == "twitter"` and `len(full_caption) > 240`, trim to last full word + `…`, log `late_twitter_truncated` event with original/final lengths

2. **`wtyj/shared/state_registry.py`**
   - Added `twitter_caption TEXT DEFAULT ''` to the `CREATE TABLE IF NOT EXISTS content_drafts` block (so new clean DBs get the column up front)
   - Added the matching `try: ALTER TABLE content_drafts ADD COLUMN twitter_caption TEXT DEFAULT '' except sqlite3.OperationalError: pass` migration block (for existing DBs)
   - Added `twitter_caption: str = ""` parameter to `save_content_draft()` and threaded it through the INSERT
   - Added `twitter_caption` to BOTH SELECT statements in `get_content_drafts()` (the `if status` and `else` branches)
   - Updated the dict construction with the +1 index shift starting at `r[5]` (verified each index against the SELECT column order)
   - Added `twitter_caption: str = None` parameter to `update_draft_content()` with the matching `if/append` block

3. **`wtyj/agents/social/content_agent.py`**
   - Added `"twitter_caption": ""` to `_DRAFT_DEFAULTS` so empty Claude responses get the field defaulted
   - Added a Twitter paragraph to PLATFORM RULES capping at 240 CHARACTERS (not words), explaining URLs count as 23 chars each, requiring it to be self-contained not a truncation
   - Added `twitter_caption` to the JSON RESPONSE FORMAT schema with the same constraint
   - Updated the `state_registry.save_content_draft(...)` call site to pass `twitter_caption=draft.get("twitter_caption", "")`

4. **`wtyj/agents/social/scheduler.py`**
   - Replaced the generic platform branch (was `for _plat in platforms: ... _plat_caption = draft.get("instagram_caption") ...`) with a per-platform routing block: when `_plat == "twitter"`, prefer `draft.get("twitter_caption")` first, then fall back to `instagram_caption` (publish_to_platform's safety truncate handles overflow)
   - Updated the comment to remove "LinkedIn, Twitter" → "Twitter, etc. — LinkedIn discontinued in Brief 156"

5. **`wtyj/tests/social/test_144_multi_platform_publish.py`**
   - Renamed `test_get_available_platforms_returns_all` → `test_get_available_platforms_filters_excluded`
   - Rewrote the body to mock 5 platforms (instagram, facebook, whatsapp, linkedin, twitter), assert whatsapp and linkedin are filtered out, assert `len(platforms) == 3`

### Frontend (wetakeyourjob-dashboard/artifacts/dashboard/)

1. **`src/lib/api.ts`** — added `twitter_caption: string;` to the `Draft` interface (between `facebook_caption` and `hashtags`)

2. **`src/pages/Create.tsx`** — removed `linkedin` from the `Linkedin` import block, removed the `p === "linkedin" ? Linkedin` icon branch, removed the `p === "linkedin" ? "bg-cyan-500/15..."` styling branch

3. **`src/pages/ContentPipeline.tsx`** — same surgery: removed `Linkedin` from the import, removed the `platform === "linkedin"` icon branch and styling branch in the platform picker map

4. **`src/pages/Messages.tsx`** — removed `Linkedin` from the import and removed all 3 `linkedin_dm` channel branches (color, icon, label)

## Test results

Backend social regression suite:

```
$ python3 -m pytest tests/social/ -q --tb=line
351 passed in 3.05s
```

Same pass count as Brief 155 (351 / 0). The renamed test
`test_get_available_platforms_filters_excluded` passes cleanly with the
new assertions (whatsapp and linkedin both filtered, len == 3).

**One stale-data hiccup, same as Brief 155:** the first run failed on
`test_073_whatsapp_hardening.py::test_change_detection_cancels_hold` due
to leftover `129_large_group` / `129_normal_group` rows in the local
`wtyj/data/state_registry.db`. The brief explicitly anticipated this and
included the cleanup one-liner. Cleanup → re-run → 351 / 0.

This will keep happening on every fresh run until either:
- a separate brief makes the test_129 fixtures self-clean
- the local DB is regularly wiped

Out of scope for Brief 156. Noted as a recurring papercut.

Frontend dashboard typecheck:

```
$ pnpm typecheck
src/pages/ContentPipeline.backup.tsx(112,9): pre-existing
src/pages/Messages.tsx (12 errors): pre-existing — Conversation type
                                    missing `channel` property
```

Zero new errors introduced by Brief 156 edits. Notable: Messages.tsx
error count dropped from 15 (before Brief 156) to 12 (after) because
removing the linkedin_dm branches removed 3 of the offending lines as
a side effect. The remaining 12 errors are pre-existing — the
`Conversation` interface in api.ts genuinely doesn't have a `channel`
field, so every `conv.channel === ...` line errors. Out of scope to fix.

## Live deploy verification

VPS deploy:

```
$ ssh root@108.61.192.52 "cd /root && git pull && cd /root/clients/bluemarlin && docker compose down && docker compose build && docker compose up -d && cd /root/clients/adamus && docker compose down && docker compose up -d"
```

Both containers up and healthy:
- `wtyj-bluemarlin` Up
- `wtyj-adamus` Up
- `curl localhost:8001/health` → `{"status":"ok"}`
- `curl localhost:8002/health` → `{"status":"ok"}`

Schema migration auto-applied on container startup:

```
$ docker exec wtyj-bluemarlin python3 -c "..."
has twitter_caption: True
all columns: [..., 'twitter_caption']  # appended at end via ALTER TABLE
```

Linkedin filter verified live:

```
$ curl /dashboard/api/platforms/available
{"platforms":["facebook","instagram","twitter"]}
```

Three platforms, no linkedin, no whatsapp.

## Unexpected findings

### 1. Recurring `test_073` stale-data papercut
Same as Brief 155. Worth a follow-up brief to make `test_129` clean
up its own confirmed bookings — they have no `expires_at` so they
persist forever once created. Either add cleanup at end of test_129
or change the test fixtures to use `expires_at` so they auto-prune.

### 2. Frontend `Linkedin` import removal was fully clean
TypeScript correctly flagged unused imports if I'd left them after
removing the conditional branches. All three files (Create,
ContentPipeline, Messages) had the import on a single line where it
was easy to surgically delete. No collateral edits needed.

### 3. The schema migration ordering doesn't match the CREATE TABLE
When I added the column to both the CREATE TABLE block AND the
ALTER TABLE migration, I noticed that for FRESH databases the column
sits in CREATE-TABLE order (right after facebook_caption, position 5)
but for EXISTING databases the column sits at the END (position 21,
last column) because ALTER TABLE always appends. This is fine because
the SELECT statement uses explicit column names — the dict
construction doesn't care about physical column order in the file,
only the order I list them in the SELECT, which is consistent.
Verified live: BlueMarlin (existing DB) has twitter_caption at
position 21 and the API returns it correctly because the SELECT pulls
it out by name.

### 4. The reviewer caught a real false premise in round 1
Brief 156 round 1 referenced `test_get_available_platforms_filters_whatsapp`
as if Brief 155 had added it. It hadn't — Brief 155 only added the
production constant. This is the same shape of false premise that bit
Brief 154's wording-change assumption. Patched in round 1; the
reviewer also flagged the off-by-one prose wording in Step 4b
explanation (the proposed code was correct, only the prose was
misleading). Both fixed pre-execution.

## Files modified

| Repo | File | Change |
|------|------|--------|
| wtyj | `wtyj/agents/social/social_publisher.py` | rename + linkedin + safety truncate |
| wtyj | `wtyj/shared/state_registry.py` | schema + 3 fn signatures |
| wtyj | `wtyj/agents/social/content_agent.py` | defaults + prompt + save call |
| wtyj | `wtyj/agents/social/scheduler.py` | per-platform caption routing |
| wtyj | `wtyj/tests/social/test_144_multi_platform_publish.py` | rename + rewrite test |
| wtyj | `wtyj/briefs/marina_brief_156_*.md` | new brief file |
| dash | `artifacts/dashboard/src/lib/api.ts` | Draft.twitter_caption |
| dash | `artifacts/dashboard/src/pages/Create.tsx` | remove linkedin |
| dash | `artifacts/dashboard/src/pages/ContentPipeline.tsx` | remove linkedin |
| dash | `artifacts/dashboard/src/pages/Messages.tsx` | remove linkedin_dm |

## Commits

- Backend: `1b938a5` on `main`
- Dashboard: `9ab1e2b` on `master`

## Open follow-ups (not blocking)

1. **`test_129` self-cleanup** — recurring stale-data papercut on every fresh local run. Worth a 5-line fix in a future brief.
2. **Dashboard `Conversation.channel` type** — pre-existing TypeScript errors in `Messages.tsx`. The `channel` property exists at runtime but isn't declared in the `Conversation` interface in `api.ts`. Cosmetic — the runtime JSX works, TypeScript just complains. Worth fixing when next touching the messages page.
3. **`Linkedin` icon import in lucide-react bundle** — Removing the import lines doesn't remove the icon from the bundle (Vite tree-shakes only at build time, not source-time). Not worth tracking unless we ever do a bundle-size audit.
4. **Live publish test for Twitter** — pending user action. Will see real X post or another `late_publish_failed` log line if Twitter still rejects despite the per-platform caption.
