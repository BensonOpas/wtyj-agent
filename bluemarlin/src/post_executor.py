import sys
import hashlib
from datetime import datetime
import social_registry
import bm_logger

def deterministic_platform_post_id(platform: str, content_id: str) -> str:
    raw = f"{platform}|{content_id}".encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()[:16]

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 post_executor.py <content_id>")
        sys.exit(2)

    cid = sys.argv[1].strip()
    rec = social_registry.get(cid)
    if not rec:
        print(f"NOT_FOUND: {cid}")
        sys.exit(1)

    # Never repost if already posted
    if rec.get("platform_post_id"):
        print(f"ALREADY_POSTED: {cid} platform_post_id={rec.get('platform_post_id')}")
        sys.exit(0)

    if rec.get("status") != "approved":
        print(f"BLOCKED: {cid} (status={rec.get('status')}) — needs approval")
        sys.exit(1)

    platform = rec.get("platform") or "unknown"
    platform_post_id = deterministic_platform_post_id(platform, cid)

    ok = social_registry.mark_posted(cid, platform_post_id)

    # ---- BM-015: Structured logging for publish ----
    bm_logger.log(
        "social_post_published",
        content_id=cid,
        platform=platform,
        platform_post_id=platform_post_id
    )
    # ---- end BM-015 ----
    if not ok:
        rec2 = social_registry.get(cid) or {}
        print(f"FAILED_TO_POST: {cid} status={rec2.get('status')}")
        sys.exit(1)

    rec3 = social_registry.get(cid) or {}
    print(f"POSTED: {cid}")
    print(f"platform={platform}")
    print(f"platform_post_id={rec3.get('platform_post_id')}")
    print(f"posted_at={rec3.get('posted_at')}")
    sys.exit(0)

if __name__ == "__main__":
    main()
