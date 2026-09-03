# bluemarlin/agents/social/social_publisher.py
# Created: Brief 096
# Last modified: Brief 098
# Purpose: Publishes content to Instagram via Late API SDK (getlate.dev).

import os
from late import Late, LateAPIError
from shared import bm_logger, config_loader, tenant_guard


def _strict_publication_platforms() -> set[str] | None:
    """Return strict post opt-ins, or None for legacy/permissive tenants.

    Use the tenant guard's validated policy so an unavailable/mismatched
    required config can never be mistaken for a legacy tenant. Messaging
    accounts and social profile URLs do not authorize public posting.
    """
    try:
        policy = tenant_guard._get_allowlist_config()
        if policy.get("_invalid"):
            return set()
        if policy.get("mode") != "strict":
            return None
        raw = config_loader.get_raw()
        social = raw.get("social_content") if isinstance(raw, dict) else None
        platforms = social.get("platforms") if isinstance(social, dict) else None
        if not isinstance(platforms, list) or any(
            not isinstance(value, str) or not value.strip() for value in platforms
        ):
            return set()
        # Do not combine platform settings with a different ownership snapshot.
        if tenant_guard._get_allowlist_config() != policy:
            return set()
        if not policy.get("zernio_accounts"):
            return set()
        return set(platforms) - _EXCLUDED_PLATFORMS
    except Exception:
        return set()


def is_publish_platform_allowed(platform: str) -> bool:
    """Fail closed for strict tenants unless public posting is explicitly enabled."""
    platforms = _strict_publication_platforms()
    return platforms is None or (isinstance(platform, str) and platform in platforms)


def _account_is_allowed(account_id: str) -> bool:
    try:
        return tenant_guard.account_access_state(account_id, "outbound") is True
    except Exception:
        return False


def _publish_target_allowed(client, platform: str, account_id: str) -> bool:
    """Fresh authorization fence immediately before posts.create.

    Strict accounts must also be active accounts of the requested platform;
    the flat channel allowlist may otherwise contain only a WhatsApp account.
    Provider discovery is not an authorization cache: recheck after its I/O.
    """
    platforms = _strict_publication_platforms()
    if platforms is not None and platform not in platforms:
        return False
    if not _account_is_allowed(account_id):
        return False
    if platforms is not None:
        accounts = client.accounts.list().accounts
        if not any(
            acc.field_id == account_id and acc.platform == platform and acc.isActive
            for acc in accounts
        ):
            return False
    current_platforms = _strict_publication_platforms()
    if current_platforms is not None:
        # A transition from legacy to strict requires fresh provider validation.
        if platforms is None or platform not in current_platforms:
            return False
    return _account_is_allowed(account_id)


def _get_client():
    """Create a Late API client. Returns None if no API key."""
    api_key = os.environ.get("LATE_API_KEY", "")
    if not api_key:
        bm_logger.log("late_no_api_key")
        return None
    return Late(api_key=api_key)


def get_instagram_account_id() -> str:
    """Discover the connected Instagram account ID from Late. Returns ID or empty string."""
    if not is_publish_platform_allowed("instagram"):
        return ""
    client = _get_client()
    if not client:
        return ""
    try:
        resp = client.accounts.list()
        for acc in resp.accounts:
            if (acc.platform == "instagram" and acc.isActive
                    and is_publish_platform_allowed("instagram")
                    and _account_is_allowed(acc.field_id)):
                bm_logger.log("late_account_found",
                              account_id=acc.field_id,
                              username=acc.username or "")
                return acc.field_id
        bm_logger.log("late_no_instagram_account")
        return ""
    except Exception as e:
        bm_logger.log("late_accounts_error", error=str(e)[:200])
        return ""


def get_facebook_account_id() -> str:
    """Discover the connected Facebook page ID from Late. Returns ID or empty string."""
    if not is_publish_platform_allowed("facebook"):
        return ""
    client = _get_client()
    if not client:
        return ""
    try:
        resp = client.accounts.list()
        for acc in resp.accounts:
            if (acc.platform == "facebook" and acc.isActive
                    and is_publish_platform_allowed("facebook")
                    and _account_is_allowed(acc.field_id)):
                bm_logger.log("late_fb_account_found",
                              account_id=acc.field_id,
                              username=acc.username or "")
                return acc.field_id
        bm_logger.log("late_no_facebook_account")
        return ""
    except Exception as e:
        bm_logger.log("late_fb_accounts_error", error=str(e)[:200])
        return ""


# Platforms that show up as "connected" in Late but should NOT appear as
# publish targets in our dashboard:
#   - whatsapp: Zernio uses it for inbound DM ingestion (Brief 143). Late's
#     posts.create cannot publish content to messaging channels.
#   - linkedin: Discontinued for our use case (Brief 156).
# Brief 155 introduced the filter for whatsapp. Brief 156 added linkedin
# and renamed the constant.
_EXCLUDED_PLATFORMS = {"whatsapp", "linkedin"}


def get_available_platforms() -> list:
    """Return list of connected platform names that can receive published posts.
    Excluded platforms (DM-only or discontinued) are filtered — see _EXCLUDED_PLATFORMS."""
    if _strict_publication_platforms() == set():
        return []
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
            if (not is_publish_platform_allowed(acc.platform)
                    or not _account_is_allowed(acc.field_id)):
                continue
            if acc.platform not in platforms:
                platforms.append(acc.platform)
        return platforms
    except Exception:
        return []


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
        if not _publish_target_allowed(client, "instagram", account_id):
            return None
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


def publish_to_facebook(caption: str, media_url: str, account_id: str,
                        hashtags: list = None) -> dict | None:
    """Publish a post to Facebook via Late. Returns {post_id, post_url} or None."""
    if not account_id:
        bm_logger.log("late_fb_publish_no_account")
        return None
    client = _get_client()
    if not client:
        return None

    full_caption = caption
    if hashtags:
        full_caption = f"{caption}\n\n{' '.join(hashtags)}"

    try:
        if not _publish_target_allowed(client, "facebook", account_id):
            return None
        result = client.posts.create(
            content=full_caption,
            platforms=[{"platform": "facebook", "accountId": account_id}],
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
        bm_logger.log("late_fb_published", post_id=post_id, post_url=post_url)
        return {"post_id": post_id, "post_url": post_url}
    except Exception as e:
        bm_logger.log("late_fb_publish_failed", error=str(e)[:200])
        return None


def get_account_id(platform: str) -> str:
    """Get an owned active account, including DM-only platforms used by routing."""
    client = _get_client()
    if not client:
        return ""
    try:
        resp = client.accounts.list()
        for acc in resp.accounts:
            if (acc.platform == platform and acc.isActive
                    and _account_is_allowed(acc.field_id)):
                return str(acc.field_id)
        return ""
    except Exception:
        return ""


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

    # Twitter safety truncate — Twitter/X rejects posts >280 chars (URLs count
    # as 23 chars each post-shortening). Trim to 240 chars on the last full
    # word + ellipsis. This is a fallback — content_agent should already cap
    # twitter_caption at 240 chars per Brief 156 prompt rule, but Claude can
    # over-shoot by a few chars and we don't want a partial publish.
    _TWITTER_MAX = 240
    if platform == "twitter" and len(full_caption) > _TWITTER_MAX:
        truncated = full_caption[:_TWITTER_MAX]
        last_space = truncated.rfind(" ")
        if last_space > _TWITTER_MAX - 40:  # don't lose more than 40 chars to word boundary
            truncated = truncated[:last_space]
        full_caption = truncated.rstrip() + "…"
        bm_logger.log("late_twitter_truncated", original_len=len(caption),
                      final_len=len(full_caption))

    try:
        if not _publish_target_allowed(client, platform, account_id):
            return None
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


def delete_post(late_post_id: str) -> bool:
    """Delete a legacy tenant's post; strict callers lack an owned receipt here.

    A bare provider post ID proves neither tenant ownership nor platform. Until
    this API accepts a tenant-bound receipt, strict deployments deny deletion.
    """
    if not late_post_id:
        bm_logger.log("late_delete_no_post_id")
        return False
    client = _get_client()
    if not client:
        return False
    try:
        if _strict_publication_platforms() is not None:
            return False
        client.posts.delete(late_post_id)
        bm_logger.log("late_post_deleted", post_id=late_post_id)
        return True
    except Exception as e:
        bm_logger.log("late_delete_failed", post_id=late_post_id, error=str(e)[:200])
        return False
