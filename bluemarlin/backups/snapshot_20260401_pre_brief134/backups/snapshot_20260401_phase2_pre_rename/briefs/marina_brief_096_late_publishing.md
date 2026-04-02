# BRIEF 096 — Late Publishing Integration
**Status:** Draft | **Files:** `agents/social/social_publisher.py` (NEW), `agents/social/auto_poster.py`, `tests/social/test_094_auto_poster.py`, `tests/social/test_096_publisher.py` (NEW) | **Depends on:** Brief 095 (branded graphics), Brief 094 (auto_poster CLI) | **Blocks:** None

## Context
Briefs 092-095 built the content pipeline: generate drafts, create branded graphics, review, and learn from rejections. The `--publish` command is a stub. This brief replaces it with real Late API integration using the `late-sdk` Python package (v1.2.89, already installed). Approved drafts will actually appear on the BlueFinn Instagram account (@bluemarlincharters).

## Why This Approach
We use the `late-sdk` Python package instead of raw HTTP because: the SDK is officially maintained, handles auth/retries/rate-limiting, and the media upload flow (presigned URLs) is abstracted behind `client.media.upload()`. Raw HTTP was our initial plan but the presigned URL endpoint path was not straightforward — the SDK handles it correctly. The publisher is a separate module (`social_publisher.py`) so swapping Late for another service is a single-file change.

## Source Material

### Verified API responses (tested against real Late API 2026-03-16)

**List accounts:**
```python
from late import Late
client = Late(api_key=key)
resp = client.accounts.list()
# resp.accounts[0].field_id == "69b8689d6cb7b8cf4c7846ff"  (account ID, mapped from _id)
# resp.accounts[0].platform == "instagram"
# resp.accounts[0].username == "bluemarlincharters"
# resp.accounts[0].isActive == True
```

**Upload media:**
```python
result = client.media.upload("/path/to/image.jpg")
# result.files[0].url == "https://media.getlate.dev/temp/..._filename.jpg"
# result.files[0].type == "image"
# result.files[0].mimeType == "image/jpeg"
```

**Create post (SDK signature, verified from source):**
```python
post = client.posts.create(
    content="Caption text here",
    platforms=[{"platform": "instagram", "accountId": "69b8689d6cb7b8cf4c7846ff"}],
    media_items=[{"url": "https://media.getlate.dev/temp/...", "type": "image"}],
    publish_now=True,
)
# post.post.field_id == "post_xxx"
# post.post.platforms[0].platformPostUrl == "https://instagram.com/p/..."
```

### SDK error handling
```python
from late import LateAPIError, LateRateLimitError, LateValidationError
# LateAPIError — general API error (401, 500, etc.)
# LateRateLimitError — 429 rate limited
# LateValidationError — 400 bad request
```

### Environment variable
`LATE_API_KEY` — set in `config/bluemarlin.env` on VPS, exported locally for dev.

### Instagram account ID
`69b8689d6cb7b8cf4c7846ff` — discovered via API. Stored dynamically (discovered at runtime, not hardcoded).

## Instructions

### Step 1 — Create social_publisher.py

Create `agents/social/social_publisher.py`:

**File header:**
```python
# bluemarlin/agents/social/social_publisher.py
# Created: Brief 096
# Last modified: Brief 096
# Purpose: Publishes content to Instagram via Late API SDK (getlate.dev).
```

**Imports:**
```python
import os
from late import Late, LateAPIError
from shared import bm_logger
```

**`_get_client()` function:**
```python
def _get_client():
    """Create a Late API client. Returns None if no API key."""
    api_key = os.environ.get("LATE_API_KEY", "")
    if not api_key:
        bm_logger.log("late_no_api_key")
        return None
    return Late(api_key=api_key)
```

**`get_instagram_account_id()` function:**
```python
def get_instagram_account_id() -> str:
    """Discover the connected Instagram account ID from Late. Returns ID or empty string."""
    client = _get_client()
    if not client:
        return ""
    try:
        resp = client.accounts.list()
        for acc in resp.accounts:
            if acc.platform == "instagram" and acc.isActive:
                bm_logger.log("late_account_found",
                              account_id=acc.field_id,
                              username=acc.username or "")
                return acc.field_id
        bm_logger.log("late_no_instagram_account")
        return ""
    except Exception as e:
        bm_logger.log("late_accounts_error", error=str(e)[:200])
        return ""
```

**`upload_media(image_path)` function:**
```python
def upload_media(image_path: str) -> str:
    """Upload an image to Late media storage. Returns public URL or empty string."""
    if not os.path.exists(image_path):
        bm_logger.log("late_upload_file_not_found", path=image_path)
        return ""
    client = _get_client()
    if not client:
        return ""
    try:
        result = client.media.upload(image_path)
        if result.files:
            url = str(result.files[0].url)
            bm_logger.log("late_upload_ok", url=url[:100])
            return url
        bm_logger.log("late_upload_no_files")
        return ""
    except Exception as e:
        bm_logger.log("late_upload_failed", error=str(e)[:200])
        return ""
```

**`publish_to_instagram(caption, media_url, account_id, hashtags=None)` function:**
```python
def publish_to_instagram(caption: str, media_url: str, account_id: str,
                         hashtags: list = None) -> dict | None:
    """Publish a post to Instagram via Late. Returns {post_id, post_url} or None."""
    if not account_id:
        bm_logger.log("late_publish_no_account")
        return None
    client = _get_client()
    if not client:
        return None

    # Append hashtags to caption
    full_caption = caption
    if hashtags:
        full_caption = f"{caption}\n\n{' '.join(hashtags)}"

    try:
        result = client.posts.create(
            content=full_caption,
            platforms=[{"platform": "instagram", "accountId": account_id}],
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
        bm_logger.log("late_published", post_id=post_id, post_url=post_url)
        return {"post_id": post_id, "post_url": post_url}
    except Exception as e:
        bm_logger.log("late_publish_failed", error=str(e)[:200])
        return None
```

### Step 2 — Update cmd_publish in auto_poster.py

**2a.** Update the import line to include social_publisher:
```python
from agents.social import content_agent, graphics_engine, social_publisher
```

**2b.** Replace the entire `cmd_publish()` function with:

```python
def cmd_publish():
    """Publish approved drafts to Instagram via Late API."""
    approved = state_registry.get_content_drafts(status="approved")
    if not approved:
        print("No approved drafts to publish.")
        return

    # Discover Instagram account
    account_id = social_publisher.get_instagram_account_id()
    if not account_id:
        print("ERROR: No Instagram account found. Check LATE_API_KEY and Late dashboard.")
        return

    published = 0
    failed = 0
    for draft in approved:
        print(f"Publishing #{draft['id']} [{draft['content_class']}]...")

        # Auto-generate graphic if missing
        image_path = draft.get("image_path", "")
        if not image_path or not os.path.exists(image_path):
            print("  Generating graphic...")
            image_path = graphics_engine.generate_graphic(draft["id"])
            if not image_path:
                print("  SKIP — could not generate graphic (no caption).")
                failed += 1
                continue

        # Upload image to Late
        print("  Uploading image...")
        media_url = social_publisher.upload_media(image_path)
        if not media_url:
            print("  SKIP — image upload failed.")
            failed += 1
            continue

        # Publish
        caption = draft.get("instagram_caption") or draft.get("facebook_caption") or ""
        hashtags = draft.get("hashtags") or []
        result = social_publisher.publish_to_instagram(
            caption=caption, media_url=media_url,
            account_id=account_id, hashtags=hashtags
        )
        if result:
            state_registry.update_draft_status(draft["id"], "published")
            post_url = result.get("post_url", "")
            print(f"  → Published! {post_url}")
            published += 1
        else:
            print("  SKIP — publish failed (check logs).")
            failed += 1

    print(f"\nDone. {published} published, {failed} failed.")
```

**2c.** Update auto_poster.py header to `# Last modified: Brief 096`.

### Step 3 — Update test_094 publish tests

The new `cmd_publish()` no longer prints "stub" and now imports `social_publisher` (which requires the `late` package). Two tests in `test_094_auto_poster.py` must be updated:

**3a.** Update `test_cmd_publish_stub` — rename to `test_cmd_publish_with_mocked_publisher`. Mock `social_publisher.get_instagram_account_id` to return `"acc_test"`, mock `social_publisher.upload_media` to return `"https://cdn/test.jpg"`, mock `social_publisher.publish_to_instagram` to return `{"post_id": "p1", "post_url": "https://ig/test"}`, and mock `graphics_engine.generate_graphic` to return a temp path. Save a draft, approve it. Call `cmd_publish()` with capsys. Assert stdout contains "Published" (not "stub"). Assert draft status is "published".

**3b.** Update `test_cmd_publish_empty` — this test is still valid (no approved drafts → "No approved drafts"). No changes needed to its logic, but it will now import the `late` package transitively. Add `os.environ.setdefault("LATE_API_KEY", "sk_test_key_for_testing")` to the test file setup if not already present (the conftest.py pattern). Actually, the existing setup already sets WhatsApp env vars before import. Add `LATE_API_KEY` to the existing `os.environ.setdefault` block at the top of test_094.

### Step 4 — Create test file

Create `tests/social/test_096_publisher.py`:

**File header:**
```python
# bluemarlin/tests/social/test_096_publisher.py
# Created: Brief 096
# Purpose: Tests for Late publishing integration
```

**Setup:**
```python
import json
import os
import sys
import glob
import tempfile
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from PIL import Image

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_token_067")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "990622044139349")
os.environ.setdefault("LATE_API_KEY", "sk_test_key_for_testing")
```

Import social_publisher AFTER env vars are set:
```python
from agents.social import social_publisher
from agents.social.auto_poster import cmd_publish
from agents.social import graphics_engine
from shared import state_registry
```

**Helpers:**
- `_cleanup_all()` — deletes content_drafts, content_learnings, and graphics files
- `_make_temp_jpg()` — creates a 100x100 JPEG in tempdir, returns path

**Mock helpers:**
```python
def _mock_account(field_id="acc_test", platform="instagram", username="testuser", is_active=True):
    """Create a mock SocialAccount."""
    acc = MagicMock()
    acc.field_id = field_id
    acc.platform = platform
    acc.username = username
    acc.isActive = is_active
    return acc

def _mock_accounts_response(accounts):
    """Create a mock AccountsListResponse."""
    resp = MagicMock()
    resp.accounts = accounts
    return resp

def _mock_upload_response(url="https://media.getlate.dev/temp/test.jpg"):
    """Create a mock MediaUploadResponse."""
    resp = MagicMock()
    file_obj = MagicMock()
    file_obj.url = url
    resp.files = [file_obj]
    return resp

def _mock_post_response(post_id="post_123", post_url="https://instagram.com/p/test"):
    """Create a mock PostCreateResponse."""
    resp = MagicMock()
    resp.post = MagicMock()
    resp.post.field_id = post_id
    platform = MagicMock()
    platform.platformPostUrl = post_url
    resp.post.platforms = [platform]
    return resp
```

**Tests (10 total):**

1. **`test_get_instagram_account_id_found`** — Mock `Late` constructor to return a mock client whose `accounts.list()` returns `_mock_accounts_response([_mock_account()])`. Call `social_publisher.get_instagram_account_id()`. Assert returns `"acc_test"`.

2. **`test_get_instagram_account_id_no_instagram`** — Mock `accounts.list()` to return only a Facebook account (`_mock_account(platform="facebook")`). Assert returns `""`.

3. **`test_get_instagram_account_id_no_api_key`** — Patch `social_publisher.os.environ.get` to return `""` for `LATE_API_KEY`. Assert returns `""`.

4. **`test_upload_media_success`** — Create a temp JPEG. Mock `Late` constructor. Mock `client.media.upload()` to return `_mock_upload_response("https://cdn/test.jpg")`. Call `social_publisher.upload_media(temp_path)`. Assert returns `"https://cdn/test.jpg"`. Cleanup.

5. **`test_upload_media_file_not_found`** — Call `social_publisher.upload_media("/nonexistent/path.jpg")`. Assert returns `""`.

6. **`test_publish_to_instagram_success`** — Mock `Late` constructor. Mock `client.posts.create()` to return `_mock_post_response()`. Call `social_publisher.publish_to_instagram("Caption.", "https://cdn/img.jpg", "acc_1", ["#test"])`. Assert returns dict with `post_id == "post_123"` and `"instagram"` in `post_url`.

7. **`test_publish_to_instagram_no_account`** — Call `social_publisher.publish_to_instagram("caption", "url", "", [])`. Assert returns None.

8. **`test_publish_to_instagram_api_error`** — Mock `client.posts.create()` to raise `Exception("API error")`. Assert returns None.

9. **`test_publish_caption_includes_hashtags`** — Mock `Late` constructor. Mock `client.posts.create()` to return `_mock_post_response()`. Call `social_publisher.publish_to_instagram("Caption.", "url", "acc_1", ["#Tag1", "#Tag2"])`. Extract the `content` kwarg from `client.posts.create.call_args`. Assert it contains both "#Tag1" and "#Tag2".

10. **`test_cmd_publish_full_flow`** — Save a draft with caption "Test post.", approve it. Mock `social_publisher.get_instagram_account_id` to return `"acc_test"`. Mock `social_publisher.upload_media` to return `"https://cdn/test.jpg"`. Mock `social_publisher.publish_to_instagram` to return `{"post_id": "p1", "post_url": "https://ig/p/test"}`. Mock `graphics_engine.generate_graphic` to return a temp file path. Call `cmd_publish()` with capsys. Assert stdout contains "Published". Assert draft status is "published" in DB. Cleanup.

## Tests
Run: `cd bluemarlin && python3 -m pytest tests/social/test_096_publisher.py -v`

All 10 tests must pass. All tests mock the Late SDK — no real API calls during testing.

## Success Condition
`auto_poster.py --publish` uploads branded graphics to Late and publishes them to Instagram. Posts appear on @bluemarlincharters. Drafts without images auto-generate graphics. All errors logged via bm_logger.

## Rollback
1. Delete `agents/social/social_publisher.py`
2. Revert `agents/social/auto_poster.py` to Brief 095 version
3. Delete `tests/social/test_096_publisher.py`
