# BRIEF 156 — Discontinue LinkedIn + per-platform Twitter caption

**Status:** Draft
**Files:**
- `wtyj/agents/social/social_publisher.py` (add `linkedin` to exclusion set, rename to `_EXCLUDED_PLATFORMS`)
- `wtyj/shared/state_registry.py` (add `twitter_caption` column + migration + save/get/update wiring)
- `wtyj/agents/social/content_agent.py` (prompt rule + JSON schema field + parser pass-through)
- `wtyj/agents/social/scheduler.py` (use `twitter_caption` for twitter, fall back with safety truncate)
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/lib/api.ts` (add `twitter_caption` to `Draft` interface)
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/ContentPipeline.tsx` (remove linkedin branches)
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Create.tsx` (remove linkedin branches)
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Messages.tsx` (remove linkedin_dm branches)

**Depends on:** Brief 155 (`_DM_ONLY_PLATFORMS` exists, ready to extend), Brief 142 (Docker)
**Blocks:** Demo to any client where Twitter posting must work

---

## Context

Two issues from the user's live demo session today:

1. **LinkedIn is discontinued.** User no longer wants LinkedIn as a publish target. The platform picker on draft cards still shows it because Late/Zernio reports it as connected (and Brief 155's `_DM_ONLY_PLATFORMS` filter only excludes whatsapp). Same shape of fix as Brief 155: extend the exclusion set, no schema changes.

2. **Twitter publishing fails on long captions.** A real publish attempt tried to post a 315-character Sunset Cruise caption to X. Late returned: `Tweet text is too long (315 characters). Twitter's limit is 280 characters. Note: URLs count as 23 characters.` The post failed on Twitter while Instagram and Facebook succeeded — partial publish.

   Root cause: `content_agent.py` generates one `instagram_caption` and one `facebook_caption` per draft, both intended to be ~150–200 words. The publish path's generic platform branch (`scheduler.py:112+`) reuses `instagram_caption` for any non-IG/FB platform, including Twitter — so a 200-word IG caption goes verbatim to Twitter and Twitter's API rejects it.

   The user picked Option B from my proposal: **add a per-platform `twitter_caption` field**, generate it specifically with a tight character cap, and use it at publish time when the platform is Twitter. Keep IG/FB rich captions intact.

## Why This Approach

### LinkedIn

**Same one-line filter pattern as Brief 155.** Reusing `_EXCLUDED_PLATFORMS` (renamed from `_DM_ONLY_PLATFORMS`) keeps the filter list in one place and easy to extend if more platforms get retired later.

### Twitter

**Three options were on the table** (per the proposal in chat):
- **A**: prompt rule globally capping captions at 240 chars → makes IG/FB shorter than they need to be
- **B**: per-platform `twitter_caption` field → cleanest, IG/FB keep full captions
- **C**: auto-truncate at publish time → lossy, doesn't fix root cause

**User picked B.** This brief implements B + adds C as a safety net (truncate if Claude over-shoots Twitter's limit) so the publish never fails entirely.

The schema already supports per-platform captions (`instagram_caption`, `facebook_caption` are separate columns and follow a clear pattern). Adding `twitter_caption` follows the same shape:
- New column with `ALTER TABLE` migration (existing migrations live in `_get_conn` lines 260-307 — same place)
- New `_DRAFT_DEFAULTS` entry in `content_agent.py`
- New JSON schema field in the prompt RESPONSE FORMAT
- New `state_registry.save_content_draft` parameter
- New select column in `get_content_drafts`
- Update path: `scheduler.execute_publish` checks `draft.get("twitter_caption")` first when publishing to twitter

**Safety net: truncate at publish.** If `twitter_caption` is empty (old draft, Claude omission) or somehow >280 chars, `publish_to_platform` truncates the caption to 240 chars on the last full word + `…` and logs a `late_twitter_truncated` event so we can spot it in logs.

### Out of scope

- **Disconnecting LinkedIn from Zernio/Late.** User does this manually in the Late dashboard if they want. Filter at our backend is enough for the dashboard not to expose it.
- **Frontend twitter_caption editor.** v1 just shows IG and FB captions. The user can see the twitter_caption in the draft API response if they look for it, but no dedicated UI textbox yet. Add later if needed.
- **Migrating existing drafts.** The DB was wiped this morning per the demo reset. No backfill needed; the next drafts the user generates will have `twitter_caption` from creation.
- **Re-generating twitter_caption from existing IG caption.** No "regenerate" button in this brief — keep scope tight.
- **Removing LinkedIn from Messages.tsx as a serious feature.** Yes the brief includes that line removal but only as cleanup; we don't actually have an inbound LinkedIn DM ingestion path.

---

## Source Material

### Current `social_publisher.py:58-83` (post-Brief-155)

```python
# DM-only platforms — Zernio reports them as "connected" because we use them
# for inbound DM ingestion (Brief 143), but Late's posts.create cannot publish
# content to them. Filter them out of the publish-target list. Brief 155.
_DM_ONLY_PLATFORMS = {"whatsapp"}


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

### Current `content_drafts` schema (state_registry.py:184-198 + ALTER TABLE migrations 260-297)

```python
"CREATE TABLE IF NOT EXISTS content_drafts ("
"id INTEGER PRIMARY KEY AUTOINCREMENT, "
"content_class TEXT NOT NULL, "
"instagram_caption TEXT, "
"facebook_caption TEXT, "
"hashtags_json TEXT DEFAULT '[]', "
"visual_suggestion TEXT DEFAULT '', "
"reasoning TEXT DEFAULT '', "
"status TEXT DEFAULT 'pending', "
"rejection_reason TEXT DEFAULT '', "
"created_at TEXT NOT NULL, "
"approved_at TEXT, "
"published_at TEXT"
")"
```

The migration block at lines 260-297 has 8 prior `try: ALTER TABLE ... ADD COLUMN ... except sqlite3.OperationalError: pass` blocks for `content_drafts` (image_path, late_post_id, instagram_url, photo_id, scheduled_at, platforms_json, facebook_url, late_facebook_post_id). The new `twitter_caption` migration follows the same shape.

### Current `save_content_draft` (state_registry.py:868-885)

```python
def save_content_draft(content_class: str, instagram_caption: str,
                       facebook_caption: str, hashtags: list,
                       visual_suggestion: str, reasoning: str) -> int:
    """Save a content draft. Returns row id."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO content_drafts "
        "(content_class, instagram_caption, facebook_caption, hashtags_json, "
        "visual_suggestion, reasoning, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
        (content_class, instagram_caption, facebook_caption,
         json.dumps(hashtags, ensure_ascii=False), visual_suggestion, reasoning,
         datetime.now(timezone.utc).isoformat())
    )
    draft_id = cur.lastrowid
    conn.commit()
    conn.close()
    return draft_id
```

### Current `get_content_drafts` (state_registry.py:888-925) — both SELECT statements + dict construction

The function has TWO SQL paths (with/without status filter) that BOTH need the new column added to the SELECT list. The dict construction at lines 910-924 also needs the new field.

### Current `update_draft_content` (state_registry.py:960-988)

```python
def update_draft_content(draft_id: int, instagram_caption: str = None,
                         facebook_caption: str = None, hashtags: list = None) -> bool:
    """Update draft content fields. Only works on pending drafts."""
    sets = []
    params = []
    if instagram_caption is not None:
        sets.append("instagram_caption = ?")
        params.append(instagram_caption)
    if facebook_caption is not None:
        sets.append("facebook_caption = ?")
        params.append(facebook_caption)
    if hashtags is not None:
        sets.append("hashtags_json = ?")
        params.append(json.dumps(hashtags, ensure_ascii=False))
    ...
```

### Current `content_agent.py` `_DRAFT_DEFAULTS` (line 22-26 area)

```python
_DRAFT_DEFAULTS = {
    "instagram_caption": "",
    "facebook_caption": "",
    ...
}
```

### Current `content_agent.py` PLATFORM RULES (lines 219-222)

```
PLATFORM RULES:
Instagram (primary): shorter captions, punchy, visual-first. Max 150 words.
Facebook (secondary): slightly longer, more informational, same core message. Max 200 words.
Both get the same concept but adapted per platform.
```

### Current `content_agent.py` RESPONSE FORMAT (lines 242-253)

```
{{
  "drafts": [
    {{
      "content_class": "<A|B|C|D>",
      "instagram_caption": "<caption for Instagram — max 150 words>",
      "facebook_caption": "<caption for Facebook — max 200 words, slightly more informational>",
      "hashtags": ["#Tag1", "#Tag2"],
      "visual_suggestion": "<description of ideal accompanying image>",
      "reasoning": "<why this post, why now, what it achieves>"
    }}
  ]
}}
```

### Current `content_agent.py` save call (lines 387-394)

```python
draft_id = state_registry.save_content_draft(
    content_class=draft["content_class"],
    instagram_caption=draft.get("instagram_caption", ""),
    facebook_caption=draft.get("facebook_caption", ""),
    hashtags=draft.get("hashtags", []),
    visual_suggestion=draft.get("visual_suggestion", ""),
    reasoning=draft.get("reasoning", ""),
)
```

### Current `scheduler.py` generic platform publish branch (lines 112-125)

```python
# Publish to other connected platforms (LinkedIn, Twitter, etc.)
for _plat in platforms:
    if _plat in ("instagram", "facebook"):
        continue  # Already handled above
    _plat_account = social_publisher.get_account_id(_plat)
    if _plat_account:
        _plat_caption = draft.get("instagram_caption") or draft.get("facebook_caption") or ""
        _plat_result = social_publisher.publish_to_platform(
            platform=_plat, caption=_plat_caption, media_url=media_url,
            account_id=_plat_account, hashtags=hashtags
        )
        if _plat_result:
            results[_plat] = _plat_result
```

This is THE bug for Twitter — line 118 unconditionally uses `instagram_caption` for any non-IG/FB platform. Twitter gets the IG caption verbatim and Late rejects on length.

### Current frontend `Draft` interface (api.ts:16-35)

```ts
export interface Draft {
  id: number;
  content_class: ContentClass;
  instagram_caption: string;
  facebook_caption: string;
  hashtags: string[];
  visual_suggestion: string;
  reasoning: string;
  ...
}
```

### LinkedIn references in frontend (verified via grep)

```
Create.tsx:154        : p === "linkedin" ? Linkedin
Create.tsx:166                              : p === "linkedin"
ContentPipeline.tsx:550   : platform === "linkedin" ? Linkedin
ContentPipeline.tsx:569                                : platform === "linkedin"
Messages.tsx:99         : conv.channel === "linkedin_dm" ? "text-cyan-400 bg-cyan-500/10"
Messages.tsx:106        : conv.channel === "linkedin_dm" ? <Linkedin className="w-2.5 h-2.5" />
Messages.tsx:112        : conv.channel === "linkedin_dm" ? "LinkedIn"
```

All three files import `Linkedin` from `lucide-react`. After removing the conditional branches, the `Linkedin` import should be removed too (TypeScript will warn about unused import otherwise).

### Hashtag-counting in publish_to_platform (social_publisher.py:182-214)

```python
def publish_to_platform(platform: str, caption: str, media_url: str,
                        account_id: str, hashtags: list = None) -> dict | None:
    ...
    full_caption = caption
    if hashtags:
        full_caption = f"{caption}\n\n{' '.join(hashtags)}"
    try:
        result = client.posts.create(
            content=full_caption,
            platforms=[{"platform": platform, "accountId": account_id}],
            ...
        )
```

Twitter safety truncate must apply to `full_caption` (caption + hashtags) AFTER hashtags are joined, not just to the caption alone.

---

## Instructions

### Step 1 — Read the actual files before editing

Read these in full first:
- `wtyj/agents/social/social_publisher.py` (lines 1-110)
- `wtyj/shared/state_registry.py` (lines 180-310 schema area, 860-990 draft functions)
- `wtyj/agents/social/content_agent.py` (lines 1-50 imports/defaults, 195-260 prompt, 360-410 parser)
- `wtyj/agents/social/scheduler.py` (lines 60-135 publish path)
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/lib/api.ts` (lines 1-50)
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/ContentPipeline.tsx` (lines 540-580 platform render)
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Create.tsx` (lines 145-180 platform render)
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Messages.tsx` (lines 90-130 channel branches)

### Step 2 — Backend: rename + extend `_EXCLUDED_PLATFORMS`

In `wtyj/agents/social/social_publisher.py`, replace the `_DM_ONLY_PLATFORMS` block at line ~58:

```python
# Platforms that show up as "connected" in Late but should NOT appear as
# publish targets in our dashboard:
#   - whatsapp: Zernio uses it for inbound DM ingestion (Brief 143). Late's
#     posts.create cannot publish content to messaging channels.
#   - linkedin: Discontinued for our use case (Brief 156).
# Brief 155 introduced the filter for whatsapp. Brief 156 added linkedin
# and renamed the constant.
_EXCLUDED_PLATFORMS = {"whatsapp", "linkedin"}
```

Then update the only reference in `get_available_platforms`:

```python
def get_available_platforms() -> list:
    """Return list of connected platform names that can receive published posts.
    Excluded platforms (DM-only or discontinued) are filtered — see _EXCLUDED_PLATFORMS."""
    client = _get_client()
    if not client:
        return []
    try:
        resp = client.accounts.list()
        platforms = []
        for acc in resp.accounts:
            if not acc.isActive:
                continue
            if acc.platform in _EXCLUDED_PLATFORMS:
                continue
            if acc.platform not in platforms:
                platforms.append(acc.platform)
        return platforms
    except Exception:
        return []
```

### Step 3 — Backend: schema migration for `twitter_caption`

In `wtyj/shared/state_registry.py`, add a new ALTER TABLE in the migration block (the place at lines 260-307 where existing `try: conn.execute("ALTER TABLE content_drafts ADD COLUMN ...") except sqlite3.OperationalError: pass` lives). Add this AFTER the `late_facebook_post_id` migration (line ~297) but BEFORE the `service_bookings` migrations (line ~301):

```python
try:
    conn.execute("ALTER TABLE content_drafts ADD COLUMN twitter_caption TEXT DEFAULT ''")
except sqlite3.OperationalError:
    pass
```

Also add `twitter_caption TEXT DEFAULT ''` to the `CREATE TABLE IF NOT EXISTS content_drafts` block at lines 184-198 — INSIDE the column list, after `facebook_caption TEXT`. So new clean DBs get the column in the original schema; existing DBs get it via the ALTER.

Final CREATE block should look like:
```python
"CREATE TABLE IF NOT EXISTS content_drafts ("
"id INTEGER PRIMARY KEY AUTOINCREMENT, "
"content_class TEXT NOT NULL, "
"instagram_caption TEXT, "
"facebook_caption TEXT, "
"twitter_caption TEXT DEFAULT '', "
"hashtags_json TEXT DEFAULT '[]', "
...
```

### Step 4 — Backend: thread `twitter_caption` through save / get / update

In `wtyj/shared/state_registry.py`:

**4a. `save_content_draft` (line ~868)** — add `twitter_caption: str = ""` parameter and include it in the INSERT:

```python
def save_content_draft(content_class: str, instagram_caption: str,
                       facebook_caption: str, hashtags: list,
                       visual_suggestion: str, reasoning: str,
                       twitter_caption: str = "") -> int:
    """Save a content draft. Returns row id."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO content_drafts "
        "(content_class, instagram_caption, facebook_caption, twitter_caption, "
        "hashtags_json, visual_suggestion, reasoning, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
        (content_class, instagram_caption, facebook_caption, twitter_caption,
         json.dumps(hashtags, ensure_ascii=False), visual_suggestion, reasoning,
         datetime.now(timezone.utc).isoformat())
    )
    draft_id = cur.lastrowid
    conn.commit()
    conn.close()
    return draft_id
```

**4b. `get_content_drafts` (line ~888)** — add `twitter_caption` to BOTH SELECT statements (both branches of the `if status / else`) and include it in the dict construction. The current SELECT lists 20 columns; the new SELECT lists 21. Add `twitter_caption` right after `facebook_caption`:

```python
"SELECT id, content_class, instagram_caption, facebook_caption, twitter_caption, "
"hashtags_json, visual_suggestion, reasoning, status, rejection_reason, "
"created_at, approved_at, published_at, image_path, late_post_id, instagram_url, photo_id, "
"platforms_json, facebook_url, late_facebook_post_id, scheduled_at "
"FROM content_drafts ..."
```

**Index shift rules (verified by reviewer in round 1):**
- `r[0]` id, `r[1]` content_class, `r[2]` instagram_caption, `r[3]` facebook_caption — **all UNCHANGED**
- `r[4]` is the NEW twitter_caption (inserted)
- Everything that USED to be at `r[4]` (hashtags_json) and beyond shifts by +1: hashtags_json `r[4]→r[5]`, visual_suggestion `r[5]→r[6]`, reasoning `r[6]→r[7]`, status `r[7]→r[8]`, rejection_reason `r[8]→r[9]`, created_at `r[9]→r[10]`, approved_at `r[10]→r[11]`, published_at `r[11]→r[12]`, image_path `r[12]→r[13]`, late_post_id `r[13]→r[14]`, instagram_url `r[14]→r[15]`, photo_id `r[15]→r[16]`, platforms_json `r[16]→r[17]`, facebook_url `r[17]→r[18]`, late_facebook_post_id `r[18]→r[19]`, scheduled_at `r[19]→r[20]`.

Use the proposed dict construction below verbatim (do NOT recompute indices yourself):

```python
return [
    {
        "id": r[0], "content_class": r[1], "instagram_caption": r[2],
        "facebook_caption": r[3], "twitter_caption": r[4] or "",
        "hashtags": json.loads(r[5] or "[]"),
        "visual_suggestion": r[6], "reasoning": r[7], "status": r[8],
        "rejection_reason": r[9], "created_at": r[10], "approved_at": r[11],
        "published_at": r[12], "image_path": r[13],
        "late_post_id": r[14], "instagram_url": r[15],
        "photo_id": r[16] if len(r) > 16 else 0,
        "platforms": json.loads(r[17]) if len(r) > 17 and r[17] else ["instagram"],
        "facebook_url": r[18] if len(r) > 18 else "",
        "late_facebook_post_id": r[19] if len(r) > 19 else "",
        "scheduled_at": r[20] if len(r) > 20 else None,
    }
    for r in rows
]
```

**Critical:** count the indices CAREFULLY when updating. Off-by-one errors here would silently corrupt every draft API response.

**4c. `update_draft_content` (line ~960)** — add `twitter_caption: str = None` parameter and the matching `if` block to update it:

```python
def update_draft_content(draft_id: int, instagram_caption: str = None,
                         facebook_caption: str = None, hashtags: list = None,
                         twitter_caption: str = None) -> bool:
    sets = []
    params = []
    if instagram_caption is not None:
        sets.append("instagram_caption = ?")
        params.append(instagram_caption)
    if facebook_caption is not None:
        sets.append("facebook_caption = ?")
        params.append(facebook_caption)
    if twitter_caption is not None:
        sets.append("twitter_caption = ?")
        params.append(twitter_caption)
    if hashtags is not None:
        sets.append("hashtags_json = ?")
        params.append(json.dumps(hashtags, ensure_ascii=False))
    ...
```

### Step 5 — Backend: `content_agent.py` prompt + parser

**5a. `_DRAFT_DEFAULTS`** (around line 22-26): add `"twitter_caption": "",`.

**5b. PLATFORM RULES section** (lines 219-222): replace with:

```
PLATFORM RULES:
Instagram (primary): shorter captions, punchy, visual-first. Max 150 words.
Facebook (secondary): slightly longer, more informational, same core message. Max 200 words.
Twitter/X: tight, atmospheric, ≤240 CHARACTERS TOTAL including any hashtags or mentions. NOT words — characters. URLs, if any, count as 23 characters each (Twitter auto-shortens). The Twitter caption is a separate field and must be a self-contained version of the same idea — not a truncation of the Instagram caption.
All three captions get the same concept but adapted per platform.
```

**5c. RESPONSE FORMAT JSON schema** (lines 242-253): add the new field:

```
{{
  "drafts": [
    {{
      "content_class": "<A|B|C|D>",
      "instagram_caption": "<caption for Instagram — max 150 words>",
      "facebook_caption": "<caption for Facebook — max 200 words, slightly more informational>",
      "twitter_caption": "<caption for Twitter/X — MAXIMUM 240 characters total INCLUDING hashtags. Self-contained, atmospheric, not a truncation of Instagram.>",
      "hashtags": ["#Tag1", "#Tag2"],
      "visual_suggestion": "<description of ideal accompanying image>",
      "reasoning": "<why this post, why now, what it achieves>"
    }}
  ]
}}
```

**5d. The save call at line 387-394** — pass `twitter_caption` through:

```python
draft_id = state_registry.save_content_draft(
    content_class=draft["content_class"],
    instagram_caption=draft.get("instagram_caption", ""),
    facebook_caption=draft.get("facebook_caption", ""),
    twitter_caption=draft.get("twitter_caption", ""),
    hashtags=draft.get("hashtags", []),
    visual_suggestion=draft.get("visual_suggestion", ""),
    reasoning=draft.get("reasoning", ""),
)
```

### Step 6 — Backend: scheduler `execute_publish` uses `twitter_caption` for X

In `wtyj/agents/social/scheduler.py`, replace the generic platform branch (lines 112-125):

```python
# Publish to other connected platforms (Twitter, etc.) — LinkedIn discontinued in Brief 156
for _plat in platforms:
    if _plat in ("instagram", "facebook"):
        continue  # Already handled above
    _plat_account = social_publisher.get_account_id(_plat)
    if not _plat_account:
        continue
    # Twitter/X: prefer the dedicated twitter_caption (≤240 chars).
    # If empty, fall back to instagram_caption (publish_to_platform will
    # safety-truncate to 240 chars + ellipsis if needed).
    if _plat == "twitter":
        _plat_caption = (
            draft.get("twitter_caption")
            or draft.get("instagram_caption")
            or draft.get("facebook_caption")
            or ""
        )
    else:
        _plat_caption = draft.get("instagram_caption") or draft.get("facebook_caption") or ""
    _plat_result = social_publisher.publish_to_platform(
        platform=_plat, caption=_plat_caption, media_url=media_url,
        account_id=_plat_account, hashtags=hashtags
    )
    if _plat_result:
        results[_plat] = _plat_result
```

### Step 7 — Backend: safety truncate in `publish_to_platform`

In `wtyj/agents/social/social_publisher.py`, modify `publish_to_platform` (~line 182):

After the line `full_caption = f"{caption}\n\n{' '.join(hashtags)}"` (or the bare `full_caption = caption` if no hashtags), but BEFORE the `client.posts.create` call, add:

```python
    # Twitter safety truncate — Twitter/X rejects posts >280 chars (URLs count
    # as 23 chars each post-shortening). Trim to 240 chars on the last full
    # word + ellipsis. This is a fallback — content_agent should already cap
    # twitter_caption at 240 chars per Brief 156 prompt rule, but Claude can
    # over-shoot by a few chars and we don't want a partial publish.
    _TWITTER_MAX = 240
    if platform == "twitter" and len(full_caption) > _TWITTER_MAX:
        truncated = full_caption[:_TWITTER_MAX]
        # Trim to last whole word
        last_space = truncated.rfind(" ")
        if last_space > _TWITTER_MAX - 40:  # don't lose more than 40 chars to word boundary
            truncated = truncated[:last_space]
        full_caption = truncated.rstrip() + "…"
        bm_logger.log("late_twitter_truncated", original_len=len(caption),
                      final_len=len(full_caption))
```

`_TWITTER_MAX` and the fallback live inside the function to keep the change scoped — no module-level constant needed.

### Step 8 — Frontend: `Draft` interface

In `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/lib/api.ts`, add `twitter_caption: string;` to the `Draft` interface (around line 20 after `facebook_caption`):

```ts
export interface Draft {
  id: number;
  content_class: ContentClass;
  instagram_caption: string;
  facebook_caption: string;
  twitter_caption: string;
  hashtags: string[];
  ...
}
```

No code consumes `twitter_caption` in the frontend yet; this is just for type-completeness so future TypeScript work doesn't have to add it.

### Step 9 — Frontend: remove LinkedIn branches

**9a. `Create.tsx`** — open the file. Around line 154 and 166 there are `p === "linkedin" ? Linkedin : ...` and `: p === "linkedin"` conditional branches. Read the file 10 lines before and after each to understand the conditional chain, then remove the linkedin branches cleanly. Then remove `Linkedin` from the `lucide-react` import block at the top of the file.

**9b. `ContentPipeline.tsx`** — same operation at lines 550 and 569. Remove the linkedin branches and the `Linkedin` import.

**9c. `Messages.tsx`** — remove the `linkedin_dm` channel handling at lines 99, 106, 112 (channel color, icon, label). Remove the `Linkedin` import.

**Critical:** in all three files, after removing the conditional branches, run `pnpm typecheck` from `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/` and confirm no new TypeScript errors. The pre-existing errors in `ContentPipeline.backup.tsx` and the `Messages.tsx` `Conversation.channel` ones are out of scope and should remain unchanged.

### Step 10 — Run social regression locally

```bash
cd /Users/benson/Projects/bluemarlin-agent/wtyj
python3 -m pytest tests/social/ -q --tb=short
```

**Expected:** all pre-existing tests pass. The schema migration should auto-apply when `_get_conn()` is called by any test, so existing tests don't need updates.

If `test_073_whatsapp_hardening.py::test_change_detection_cancels_hold` fails again, it's the same stale-data bug from Brief 155 — clean it via the same one-liner:

```bash
python3 -c "import sqlite3; c=sqlite3.connect('/Users/benson/Projects/bluemarlin-agent/wtyj/data/state_registry.db'); c.execute('DELETE FROM service_bookings WHERE customer_email IN (\"129_large_group\",\"129_normal_group\")'); c.commit()"
```

Then re-run the suite.

### Step 11 — Commit + push (both repos)

```bash
# Backend
cd /Users/benson/Projects/bluemarlin-agent
git add wtyj/agents/social/social_publisher.py \
        wtyj/agents/social/scheduler.py \
        wtyj/agents/social/content_agent.py \
        wtyj/shared/state_registry.py \
        wtyj/briefs/marina_brief_156_linkedin_off_and_twitter_caption.md
git commit -m "Brief 156 — discontinue linkedin + per-platform twitter_caption"
git push

# Dashboard
cd ~/Projects/wetakeyourjob-dashboard
git add artifacts/dashboard/src/lib/api.ts \
        artifacts/dashboard/src/pages/ContentPipeline.tsx \
        artifacts/dashboard/src/pages/Create.tsx \
        artifacts/dashboard/src/pages/Messages.tsx
git commit -m "Brief 156 — remove linkedin branches + twitter_caption type"
git push
```

### Step 12 — Deploy backend to VPS

```bash
ssh root@108.61.192.52 "
  set -e
  cd /root && git pull
  cd /root/clients/bluemarlin && docker compose down
  cd /root/clients/adamus && docker compose down
  cd /root/clients/bluemarlin && docker compose build && docker compose up -d
  cd /root/clients/adamus && docker compose up -d
  sleep 8
  docker ps --filter name=wtyj- --format 'table {{.Names}}\t{{.Status}}'
"
```

**Schema migration runs on container start** when any code path first calls `_get_conn()`. The email poller calls it within seconds of startup so the migration applies automatically.

### Step 13 — Verify backend changes via curl

```bash
# Login
curl -sf -X POST 'https://api.wetakeyourjob.com/dashboard/api/login' \
  -H 'Content-Type: application/json' -d '{"password":"123"}' -o /tmp/dl.json
TOKEN=$(python3 -c 'import json; print(json.load(open("/tmp/dl.json"))["token"])')

# Verify linkedin is gone from platforms list
curl -sf 'https://api.wetakeyourjob.com/dashboard/api/platforms/available' \
  -H "Authorization: Bearer $TOKEN"
# Expected: {"platforms":["facebook","instagram","twitter"]}  (no linkedin, no whatsapp)
```

### Step 14 — User-driven live tests

1. **Generate fresh drafts** via dashboard. Confirm the new drafts have a `twitter_caption` field in the API response (curl `/drafts` and look at `twitter_caption` length — should be ≤240 chars).
2. **Open the dashboard ContentPipeline page.** Confirm the platform picker on draft cards no longer shows LinkedIn. Only Facebook, Instagram, X (Twitter) should appear.
3. **Open the Settings page.** Confirm the Developer accordion still works, dry-run banner still shows (if dry-run is on).
4. **Flip dry_run off** if you haven't.
5. **Approve a draft, set platforms = [facebook, instagram, twitter], click Publish Now.** Watch the result:
   - Should succeed on all 3
   - Twitter post should appear on the X profile
   - The Twitter caption should be different from the Instagram caption (shorter, atmospheric)
6. **Search bluemarlin.log** on VPS for `late_twitter_truncated` events — if Claude consistently exceeds 240, we'll see them. Acceptable as a safety net catch.

---

## Tests

No new test files. Manual verification per Step 14 is the main test plan.

**Critical existing test that WILL break and must be updated as part of this brief:**

`wtyj/tests/social/test_144_multi_platform_publish.py:31-42` — `test_get_available_platforms_returns_all`. The current body mocks `_mock_accounts("instagram", "facebook", "linkedin", "twitter")` and asserts `"linkedin" in platforms` AND `len(platforms) == 4`. After Brief 156 filters `linkedin`, both assertions fail. This is the test that round-1 reviewer flagged — Brief 155's `_DM_ONLY_PLATFORMS` introduction NEVER added a regression test for the filter behavior, so the test_144 assertions still expect pre-Brief-155 behavior.

**Update required (rename + rewrite the body):**

Open `wtyj/tests/social/test_144_multi_platform_publish.py` and replace `test_get_available_platforms_returns_all` (lines 31-42) with:

```python
# --- Test 1: get_available_platforms filters excluded platforms (Brief 155 + 156) ---
@patch("agents.social.social_publisher._get_client")
def test_get_available_platforms_filters_excluded(mock_client):
    """Brief 156 — get_available_platforms must exclude DM-only and discontinued
    platforms (whatsapp from Brief 155, linkedin from Brief 156)."""
    from agents.social.social_publisher import get_available_platforms
    client = MagicMock()
    client.accounts.list.return_value = _mock_accounts(
        "instagram", "facebook", "whatsapp", "linkedin", "twitter"
    )
    mock_client.return_value = client

    platforms = get_available_platforms()
    assert "instagram" in platforms
    assert "facebook" in platforms
    assert "twitter" in platforms
    assert "whatsapp" not in platforms, "whatsapp must be filtered (DM-only)"
    assert "linkedin" not in platforms, "linkedin must be filtered (discontinued)"
    assert len(platforms) == 3
```

The other tests in the same file (`test_get_account_id_finds_platform`, `test_publish_to_platform_generic`, `test_execute_publish_multi_platform`) bypass the filter via direct draft `platforms` lists, so they remain green without modification. The reviewer verified this in round 1.

Run the social regression after the test update + all backend changes:
```bash
python3 -m pytest wtyj/tests/social/ -q --tb=short
```
Expected: same pass count as Brief 155 (351 social tests passing). Zero new failures, zero pre-existing regressions.

If `test_073_whatsapp_hardening.py::test_change_detection_cancels_hold` fails due to the same `129_large_group` / `129_normal_group` stale data from Brief 155's run, clean it the same way:
```bash
python3 -c "import sqlite3; c=sqlite3.connect('/Users/benson/Projects/bluemarlin-agent/wtyj/data/state_registry.db'); c.execute('DELETE FROM service_bookings WHERE customer_email IN (\"129_large_group\",\"129_normal_group\")'); c.commit()"
```

---

## Success Condition

**One sentence:** A draft generated by content_agent has a `twitter_caption` ≤240 chars distinct from `instagram_caption`, publishing to platforms=[facebook, instagram, twitter] succeeds on all three with a real X post URL persisted, AND the dashboard's draft platform picker no longer shows LinkedIn.

---

## Rollback

Each change is independent and revertible:

```bash
# Backend (one commit per phase if needed)
cd /Users/benson/Projects/bluemarlin-agent
git revert <commit-sha>
ssh root@108.61.192.52 "cd /root && git pull && cd /root/clients/bluemarlin && docker compose down && docker compose build && docker compose up -d && cd /root/clients/adamus && docker compose down && docker compose up -d"

# Dashboard
cd ~/Projects/wetakeyourjob-dashboard
git revert <commit-sha>
git push
# Replit auto-deploys
```

The schema migration (`twitter_caption` column) is idempotent — `ALTER TABLE` is wrapped in `try/except sqlite3.OperationalError`. A revert leaves the column in place but unused, which is harmless. To fully undo the column, manually `ALTER TABLE content_drafts DROP COLUMN twitter_caption` on each client's DB — but this is only needed if you actively want to repurpose the column name.

---

## Risks I want flagged before execution

1. **Off-by-one in `get_content_drafts` index updates.** Adding `twitter_caption` between `facebook_caption` and `hashtags_json` shifts indices `r[4]`–`r[19]` by +1 in the dict construction. A wrong index would corrupt every draft API response — `image_path` could end up returning `late_post_id`'s value, etc. The reviewer should specifically verify these indices match the column order in the SELECT statement.

2. **Claude prompt compliance with character limits.** LLMs are bad at exact counts. The 240-char rule will be honored ~95% of the time but Claude will occasionally write 245-260 chars. The safety truncate in Step 7 catches this — but the truncation produces ugly tweets ("…"). If we see frequent truncations in `late_twitter_truncated` log events, a follow-up is to rewrite the prompt more aggressively or pull the limit down to 200.

3. **Frontend `Linkedin` import removal.** Each of the 3 frontend files (Create, ContentPipeline, Messages) imports `Linkedin` from `lucide-react`. After removing the conditional branches, the import becomes unused and TypeScript will warn. Must remove the import too — easy to forget on one of the three files.

4. **Twitter still rejects despite the safety truncate.** Edge case: a 240-char caption with emoji that count as 2 chars in Twitter's UTF-16 weighting could still exceed 280 weighted chars. The truncate uses Python `len` which counts code points, not Twitter's weighted chars. If Twitter still rejects after the safety net, we need to also account for emoji weight — out of scope for v1 unless it shows up in practice.

5. **Existing draft tests touching captions.** I haven't searched all tests for `instagram_caption` and `facebook_caption` references. If any test asserts the dict keys exhaustively (e.g. `assert set(draft.keys()) == {...}`), adding `twitter_caption` will break it. The reviewer should grep `assert.*draft.keys` to flag any.

6. **LinkedIn-related runtime data on the VPS.** The DB was wiped this morning but there COULD be lingering content_learnings or training_examples that mention LinkedIn. Out of scope to clean — they're text strings, not platform identifiers, and don't affect runtime.
