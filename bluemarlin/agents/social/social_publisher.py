# bluemarlin/agents/social/social_publisher.py
# Created: Brief 096
# Last modified: Brief 098
# Purpose: Publishes content to Instagram via Late API SDK (getlate.dev).

import os
from late import Late, LateAPIError
from shared import bm_logger


def _get_client():
    """Create a Late API client. Returns None if no API key."""
    api_key = os.environ.get("LATE_API_KEY", "")
    if not api_key:
        bm_logger.log("late_no_api_key")
        return None
    return Late(api_key=api_key)


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


def publish_to_instagram(caption: str, media_url: str, account_id: str,
                         hashtags: list = None) -> dict | None:
    """Publish a post to Instagram via Late. Returns {post_id, post_url} or None."""
    if not account_id:
        bm_logger.log("late_publish_no_account")
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


def delete_post(late_post_id: str) -> bool:
    """Delete a published post from Instagram via Late. Returns True on success."""
    if not late_post_id:
        bm_logger.log("late_delete_no_post_id")
        return False
    client = _get_client()
    if not client:
        return False
    try:
        client.posts.delete(late_post_id)
        bm_logger.log("late_post_deleted", post_id=late_post_id)
        return True
    except Exception as e:
        bm_logger.log("late_delete_failed", post_id=late_post_id, error=str(e)[:200])
        return False
