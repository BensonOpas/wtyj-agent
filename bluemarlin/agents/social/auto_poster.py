# bluemarlin/agents/social/auto_poster.py
# Created: Brief 094
# Last modified: Brief 094
# Purpose: CLI entry point for content pipeline — generate, review, publish, distill.

import argparse
import sys
import os

# Ensure bluemarlin package root is on sys.path
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

from agents.social import content_agent
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
    """Publish approved drafts (stub mode — logs but doesn't post to real platforms)."""
    approved = state_registry.get_content_drafts(status="approved")
    if not approved:
        print("No approved drafts to publish.")
        return

    count = 0
    for draft in approved:
        print(f"Publishing #{draft['id']} [{draft['content_class']}]...")
        print(f"  IG: {(draft.get('instagram_caption') or '')[:100]}")
        print(f"  FB: {(draft.get('facebook_caption') or '')[:100]}")
        print(f"  Tags: {' '.join(draft.get('hashtags') or [])}")
        bm_logger.log("content_published_stub",
                      draft_id=draft["id"],
                      platform="instagram+facebook")
        state_registry.update_draft_status(draft["id"], "published")
        print("  → Published (stub).")
        count += 1

    print(f"Published {count} drafts (stub mode).")


def cmd_distill():
    """Distill brand learnings from rejected drafts."""
    learnings = content_agent.distill_learnings()
    if not learnings:
        print("No new learnings (need more rejections with reasons).")
        return
    for l in learnings:
        print(f"  NEW RULE: {l['rule']}")
    print(f"Distilled {len(learnings)} new brand learnings.")


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
    parser.add_argument("--status", action="store_true", help="Show pipeline status counts")
    args = parser.parse_args()

    if not any([args.generate, args.review, args.publish, args.distill, args.status]):
        parser.print_help()
        return

    if args.status:
        cmd_status()
    if args.generate:
        cmd_generate(args.count)
    if args.review:
        cmd_review()
    if args.publish:
        cmd_publish()
    if args.distill:
        cmd_distill()


if __name__ == "__main__":
    main()
