# bluemarlin/agents/social/auto_poster.py
# Created: Brief 094
# Last modified: Brief 096
# Purpose: CLI entry point for content pipeline — generate, review, publish, distill.

import argparse
import sys
import os

# Ensure bluemarlin package root is on sys.path
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

from agents.social import content_agent, graphics_engine, social_publisher
from shared import state_registry, bm_logger


def cmd_generate(count):
    """Generate new draft posts via Claude."""
    drafts = content_agent.generate_drafts(count=count)
    if not drafts:
        print("No drafts generated (check API key or logs).")
        return
    for d in drafts:
        cap = (d.get("instagram_caption") or "")[:70]
        print(f"  #{d['id']} [{d['content_class']}] {cap}...")
    print(f"Generated {len(drafts)} drafts.")


def cmd_review():
    """Review pending drafts interactively — approve, reject, or skip."""
    pending = state_registry.get_content_drafts(status="pending")
    if not pending:
        print("No pending drafts.")
        return

    approved = 0
    rejected = 0
    skipped = 0

    for draft in pending:
        print(f"\n--- Draft #{draft['id']} [Class {draft['content_class']}] ---")
        print(f"IG: {draft.get('instagram_caption') or '(none)'}")
        print(f"FB: {draft.get('facebook_caption') or '(none)'}")
        print(f"Tags: {' '.join(draft.get('hashtags') or [])}")
        print(f"Visual: {draft.get('visual_suggestion') or '(none)'}")
        print(f"Reason: {draft.get('reasoning') or '(none)'}")
        print()

        choice = input("[a]pprove / [r]eject / [s]kip? ").strip().lower()
        if choice.startswith("a"):
            state_registry.update_draft_status(draft["id"], "approved")
            print("Approved.")
            approved += 1
        elif choice.startswith("r"):
            reason = input("Rejection reason: ").strip()
            state_registry.update_draft_status(draft["id"], "rejected", rejection_reason=reason)
            print("Rejected.")
            rejected += 1
        else:
            print("Skipped.")
            skipped += 1

    print(f"\nReview complete. {approved} approved, {rejected} rejected, {skipped} skipped.")


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


def cmd_distill():
    """Distill brand learnings from rejected drafts."""
    learnings = content_agent.distill_learnings()
    if not learnings:
        print("No new learnings (need more rejections with reasons).")
        return
    for l in learnings:
        print(f"  NEW RULE: {l['rule']}")
    print(f"Distilled {len(learnings)} new brand learnings.")


def cmd_graphics():
    """Generate branded graphics for drafts that need images."""
    results = graphics_engine.generate_all_pending_graphics()
    if not results:
        print("No drafts need graphics (all pending/approved drafts already have images).")
        return
    for draft_id, path in results:
        print(f"  #{draft_id} → {path}")
    print(f"Generated {len(results)} graphics.")


def cmd_status():
    """Show pipeline status counts."""
    pending = len(state_registry.get_content_drafts(status="pending"))
    approved = len(state_registry.get_content_drafts(status="approved"))
    rejected = len(state_registry.get_content_drafts(status="rejected"))
    published = len(state_registry.get_content_drafts(status="published"))
    learnings = len(state_registry.get_active_learnings())
    print("Content Pipeline Status:")
    print(f"  Pending:    {pending}")
    print(f"  Approved:   {approved}")
    print(f"  Rejected:   {rejected}")
    print(f"  Published:  {published}")
    print(f"  Learnings:  {learnings} active")


def main():
    parser = argparse.ArgumentParser(description="BluMarlin Content Pipeline")
    parser.add_argument("--generate", action="store_true", help="Generate new draft posts")
    parser.add_argument("--count", type=int, default=3, help="Number of drafts to generate (default: 3)")
    parser.add_argument("--review", action="store_true", help="Review pending drafts interactively")
    parser.add_argument("--publish", action="store_true", help="Publish approved drafts (stub)")
    parser.add_argument("--distill", action="store_true", help="Distill brand learnings from rejections")
    parser.add_argument("--graphics", action="store_true", help="Generate branded graphics for drafts")
    parser.add_argument("--status", action="store_true", help="Show pipeline status counts")
    args = parser.parse_args()

    if not any([args.generate, args.review, args.publish, args.distill, args.status, args.graphics]):
        parser.print_help()
        return

    if args.status:
        cmd_status()
    if args.generate:
        cmd_generate(args.count)
    if args.review:
        cmd_review()
    if args.graphics:
        cmd_graphics()
    if args.publish:
        cmd_publish()
    if args.distill:
        cmd_distill()


if __name__ == "__main__":
    main()
