# BRIEF 144 — Multi-Platform Publishing: LinkedIn + Twitter/X
**Status:** Draft | **Files:** `agents/social/social_publisher.py`, `agents/social/scheduler.py`, `dashboard frontend ContentPipeline.tsx` | **Depends on:** Brief 143 | **Blocks:** None

## Context

LinkedIn and Twitter/X are connected in Zernio. The publishing code only handles Instagram and Facebook explicitly. The dashboard only shows Instagram and Facebook buttons. Need to support all Zernio-connected platforms.

## Why This Approach

Add a generic `publish_to_platform()` function that works for any Zernio platform. The Zernio SDK `client.posts.create()` already supports any platform — the code just needs to pass the platform name and account ID. Then add LinkedIn and Twitter to the `execute_publish` flow, and add icons/colors to the frontend.

## Source Material

### Zernio posts.create (already used for IG/FB):
```python
client.posts.create(
    content=caption,
    platforms=[{"platform": "instagram", "accountId": account_id}],
    media_items=[{"url": media_url, "type": "image"}],
    publish_now=True,
)
```
Same call works for any platform — just change `"platform"` to `"linkedin"`, `"twitter"`, etc.

### Current get_available_platforms (social_publisher.py line 60):
Already returns all connected platforms from Zernio dynamically.

### Current execute_publish (scheduler.py lines 78-110):
Hardcoded blocks for instagram and facebook. Needs linkedin and twitter blocks.

### Current frontend platform selector (ContentPipeline.tsx lines 540-574):
Dynamic — reads `connectedPlatforms` from API. But icons (line 548) and colors (line 563) only handle instagram and facebook.

## Instructions

### Step 1: Add generic publish function (social_publisher.py)

Add after `publish_to_facebook` (after line ~145):

```python
def publish_to_platform(platform: str, caption: str, media_url: str,
                        account_id: str, hashtags: list = None) -> dict | None:
    """Publish to any Zernio-connected platform. Returns {post_id, post_url} or None."""
    if not account_id:
        bm_logger.log("late_publish_no_account", platform=platform)
        return None
    client = _get_client()
    if not client:
        return None

    full_caption = caption
    if hashtags:
        full_caption = f"{caption}\n\n{' '.join(hashtags)}"

    try:
        result = client.posts.create(
            content=full_caption,
            platforms=[{"platform": platform, "accountId": account_id}],
            media_items=[{"url": media_url, "type": "image"}],
            publish_now=True,
        )
        post = result.post
        post_id = post.field_id if post else ""
        post_url = ""
        if post and post.platforms:
            for p in post.platforms:
                if hasattr(p, "platformPostUrl") and p.platformPostUrl:
                    post_url = str(p.platformPostUrl)
        bm_logger.log("late_published", platform=platform, post_id=post_id, post_url=post_url)
        return {"post_id": post_id, "post_url": post_url}
    except Exception as e:
        bm_logger.log("late_publish_failed", platform=platform, error=str(e)[:200])
        return None
```

Also add a helper to get any platform's account ID:

```python
def get_account_id(platform: str) -> str:
    """Get the active account ID for any connected platform."""
    client = _get_client()
    if not client:
        return ""
    try:
        resp = client.accounts.list()
        for acc in resp.accounts:
            if acc.platform == platform and acc.isActive:
                return str(acc.field_id)
        return ""
    except Exception:
        return ""
```

### Step 2: Add LinkedIn + Twitter to execute_publish (scheduler.py)

After the Facebook block (after line 110), add:

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

This handles any platform generically — LinkedIn, Twitter, TikTok, whatever Zernio supports.

### Step 3: Update frontend platform selector (ContentPipeline.tsx)

Change line 548 from:
```tsx
const Icon = platform === "instagram" ? Instagram : Facebook;
```
to:
```tsx
const Icon = platform === "instagram" ? Instagram
    : platform === "facebook" ? Facebook
    : platform === "linkedin" ? Linkedin
    : platform === "twitter" ? Twitter
    : Globe;
```

Add imports at the top of the file (with other lucide imports):
```tsx
import { Linkedin, Twitter, Globe } from "lucide-react";
```

Change lines 563-565 from:
```tsx
? platform === "instagram"
    ? "bg-gradient-to-r from-fuchsia-500/15 to-rose-500/15 border-fuchsia-500/30 text-fuchsia-400"
    : "bg-blue-500/15 border-blue-500/30 text-blue-400"
```
to:
```tsx
? platform === "instagram"
    ? "bg-gradient-to-r from-fuchsia-500/15 to-rose-500/15 border-fuchsia-500/30 text-fuchsia-400"
    : platform === "linkedin"
    ? "bg-blue-600/15 border-blue-600/30 text-blue-300"
    : platform === "twitter"
    ? "bg-sky-500/15 border-sky-500/30 text-sky-400"
    : "bg-blue-500/15 border-blue-500/30 text-blue-400"
```

## Tests

File: `tests/social/test_144_multi_platform_publish.py`

1. **test_get_available_platforms_returns_all** — Mock Zernio accounts with instagram, facebook, linkedin, twitter. Verify all 4 returned.

2. **test_get_account_id_finds_platform** — Mock Zernio accounts. Call `get_account_id("linkedin")`. Verify returns the correct account ID.

3. **test_publish_to_platform_generic** — Mock Zernio `posts.create`. Call `publish_to_platform("linkedin", ...)`. Verify the platform param is "linkedin" in the API call.

4. **test_execute_publish_multi_platform** — Mock Zernio accounts + posts.create. Set draft platforms to ["instagram", "linkedin"]. Call execute_publish. Verify both platforms published.

## Success Condition

Content can be published to LinkedIn and Twitter from the dashboard. Platform selector shows icons for all connected platforms. Backend handles any Zernio-connected platform generically. All 4 tests pass.

## Rollback

Revert `social_publisher.py`, `scheduler.py`, `ContentPipeline.tsx`.
