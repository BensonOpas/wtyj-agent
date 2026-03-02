import sys
import social_registry

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 approve_post.py <content_id>")
        sys.exit(2)

    cid = sys.argv[1].strip()
    ok = social_registry.approve(cid)

    if ok:
        rec = social_registry.get(cid)
        print(f"APPROVED: {cid}")
        print(f"status={rec.get('status')} approved_at={rec.get('approved_at')}")
        sys.exit(0)

    rec = social_registry.get(cid)
    if not rec:
        print(f"NOT_FOUND: {cid}")
    else:
        print(f"NOT_APPROVED: {cid} (current_status={rec.get('status')})")
    sys.exit(1)

if __name__ == "__main__":
    main()
