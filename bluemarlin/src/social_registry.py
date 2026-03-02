import hashlib
import json
import os
from datetime import datetime

SOCIAL_STATE_FILE = "social_state.json"


def _load():
    if not os.path.exists(SOCIAL_STATE_FILE):
        return {"posts": {}}
    with open(SOCIAL_STATE_FILE, "r") as f:
        return json.load(f)


def _save(data):
    with open(SOCIAL_STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _content_id(platform: str, text: str) -> str:
    raw = f"{platform}|{text}".encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()[:12]


def create_draft(platform: str, text: str, meta: dict | None = None) -> dict:
    """
    Deterministic draft creator:
    Same platform+text -> same content_id -> same stored draft (no duplicates).
    """
    meta = meta or {}
    state = _load()
    cid = _content_id(platform, text)

    if cid in state["posts"]:
        return state["posts"][cid]

    rec = {
        "content_id": cid,
        "platform": platform,
        "text": text,
        "status": "draft",              # draft -> approved -> posted -> failed
        "created_at": datetime.utcnow().isoformat(),
        "approved_at": None,
        "posted_at": None,
        "platform_post_id": None,
        "meta": meta,
    }

    state["posts"][cid] = rec
    _save(state)
    return rec


def approve(content_id: str) -> bool:
    state = _load()
    rec = state["posts"].get(content_id)
    if not rec:
        return False
    if rec.get("status") != "draft":
        return False
    rec["status"] = "approved"
    rec["approved_at"] = datetime.utcnow().isoformat()
    _save(state)
    return True


def mark_posted(content_id: str, platform_post_id: str) -> bool:
    """
    Deterministic posting finalizer:
    If platform_post_id exists already -> never repost.
    """
    state = _load()
    rec = state["posts"].get(content_id)
    if not rec:
        return False

    # If already posted, do nothing (idempotent)
    if rec.get("platform_post_id"):
        return True

    if rec.get("status") != "approved":
        return False

    rec["status"] = "posted"
    rec["posted_at"] = datetime.utcnow().isoformat()
    rec["platform_post_id"] = platform_post_id
    _save(state)
    return True


def get(content_id: str) -> dict | None:
    state = _load()
    return state["posts"].get(content_id)
