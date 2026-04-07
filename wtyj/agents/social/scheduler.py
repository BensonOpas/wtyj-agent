# bluemarlin/agents/social/scheduler.py
# Created: Brief 111
# Purpose: Background scheduler for auto-publishing scheduled posts.

import os
import threading
import time as _time
from datetime import datetime, timezone

from shared import state_registry, bm_logger
from agents.social import social_publisher, graphics_engine


_PHOTOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'photos')


def start_scheduler():
    """Start the background scheduler thread. Call once at app startup."""
    thread = threading.Thread(target=_scheduler_loop, daemon=True)
    thread.start()
    bm_logger.log("scheduler_started")


def _scheduler_loop():
    """Check every 60s for scheduled posts that are due."""
    while True:
        _time.sleep(60)
        try:
            _publish_due_posts()
        except Exception as e:
            bm_logger.log("scheduler_error", error=str(e)[:200])


def _publish_due_posts():
    """Find all drafts with status='scheduled' and scheduled_at <= now, publish them."""
    due = state_registry.get_scheduled_due()
    for draft in due:
        try:
            result = execute_publish(draft)
            if result.get("ok"):
                bm_logger.log("scheduler_published", draft_id=draft["id"],
                              platforms=result.get("platforms", []))
        except Exception as e:
            bm_logger.log("scheduler_publish_failed", draft_id=draft["id"],
                          error=str(e)[:200])


def execute_publish(draft: dict) -> dict:
    """Shared publish logic used by both the API endpoint and the scheduler.
    Handles image resolution, upload, and multi-platform publishing.
    Returns dict with ok, platforms, post_url keys."""
    draft_id = draft["id"]

    # Auto-image: photo library → AI generation → text card fallback
    image_path = draft.get("image_path", "")
    if not image_path or not os.path.exists(image_path):
        image_path = _resolve_image(draft)
    if not image_path:
        return {"ok": False, "error": "Could not generate any image"}

    # Check dry run mode
    if state_registry.is_dry_run():
        platforms = draft.get("platforms", ["instagram"])
        bm_logger.log("dry_run_publish", draft_id=draft_id, platforms=platforms,
                      image_path=image_path)
        state_registry.update_draft_status(draft_id, "published")
        return {"ok": True, "platforms": platforms, "post_url": "", "dry_run": True}

    # Upload image once
    media_url = social_publisher.upload_media(image_path)
    if not media_url:
        return {"ok": False, "error": "Image upload failed"}

    platforms = draft.get("platforms", ["instagram"])
    hashtags = draft.get("hashtags") or []
    results = {}

    # Publish to Instagram
    if "instagram" in platforms:
        ig_account = social_publisher.get_instagram_account_id()
        if ig_account:
            ig_caption = draft.get("instagram_caption") or draft.get("facebook_caption") or ""
            ig_result = social_publisher.publish_to_instagram(
                caption=ig_caption, media_url=media_url,
                account_id=ig_account, hashtags=hashtags
            )
            if ig_result:
                results["instagram"] = ig_result
                state_registry.set_draft_published_info(
                    draft_id,
                    late_post_id=ig_result.get("post_id", ""),
                    instagram_url=ig_result.get("post_url", "")
                )

    # Publish to Facebook
    if "facebook" in platforms:
        fb_account = social_publisher.get_facebook_account_id()
        if fb_account:
            fb_caption = draft.get("facebook_caption") or draft.get("instagram_caption") or ""
            fb_result = social_publisher.publish_to_facebook(
                caption=fb_caption, media_url=media_url,
                account_id=fb_account, hashtags=hashtags
            )
            if fb_result:
                results["facebook"] = fb_result
                state_registry.set_draft_facebook_info(
                    draft_id,
                    late_post_id=fb_result.get("post_id", ""),
                    facebook_url=fb_result.get("post_url", "")
                )

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

    if not results:
        return {"ok": False, "error": "Publish failed on all platforms"}

    state_registry.update_draft_status(draft_id, "published")
    return {
        "ok": True,
        "platforms": list(results.keys()),
        "post_url": results.get("instagram", results.get("facebook", {})).get("post_url", ""),
    }


def _resolve_image(draft: dict) -> str:
    """Resolve the best image for a draft. Returns path or empty string."""
    from dashboard.api import _match_photo_to_draft, _generate_ai_image, _PHOTOS_DIR as photos_dir
    draft_id = draft["id"]

    # Try photo library
    photo = _match_photo_to_draft(draft)
    if photo:
        photo_path = os.path.join(photos_dir, photo["filename"])
        image_path = graphics_engine.generate_composite(draft_id, photo_path=photo_path, mode="photo_only")
        if image_path:
            state_registry.set_draft_photo_id(draft_id, photo["id"])
            state_registry.increment_photo_used_count(photo["id"])
            return image_path

    # Try AI generation
    prompt = draft.get("visual_suggestion") or draft.get("instagram_caption") or ""
    ai_path = _generate_ai_image(prompt, draft_id)
    if ai_path:
        image_path = graphics_engine.generate_composite(draft_id, photo_path=ai_path, mode="photo_only")
        if image_path:
            return image_path

    # Final fallback: branded text card
    return graphics_engine.generate_graphic(draft_id)
