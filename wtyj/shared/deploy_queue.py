"""Deploy queue: tracks pushes blocked from production deploy by off-hours.
Atomic file writes via temp + rename, locked with fcntl.flock on a sidecar
lock file. All read-modify-write operations go through _with_lock() to
prevent concurrent claim/enqueue/complete from racing."""
from __future__ import annotations
import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

QUEUE_PATH = os.environ.get("DEPLOY_QUEUE_PATH",
                             "/root/wtyj_deploy_queue.json")
HISTORY_MAX = 30
_BRIEF_RE = re.compile(r"\bBrief\s+(\d+)", re.IGNORECASE)


def _empty_state() -> dict:
    return {"queued": [], "in_progress": None, "history": []}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def extract_brief_number(commit_message: str) -> Optional[int]:
    m = _BRIEF_RE.search(commit_message or "")
    return int(m.group(1)) if m else None


@contextmanager
def _with_lock():
    """Acquire exclusive fcntl lock on a sidecar lock file. Released on FD
    close (including unclean process exit). Lock duration is microseconds —
    only the read-modify-write sequence."""
    lock_path = QUEUE_PATH + ".lock"
    os.makedirs(os.path.dirname(QUEUE_PATH) or ".", exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _read_unlocked() -> dict:
    try:
        with open(QUEUE_PATH, "r") as f:
            data = json.load(f)
        for k, default in (("queued", []), ("in_progress", None), ("history", [])):
            data.setdefault(k, default)
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return _empty_state()


def _write_unlocked(state: dict) -> None:
    target_dir = os.path.dirname(QUEUE_PATH) or "."
    os.makedirs(target_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".deploy_queue.", suffix=".json",
                                dir=target_dir)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, QUEUE_PATH)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def read_state() -> dict:
    """Read-only access (no lock needed for read-only consumers like the
    control panel)."""
    return _read_unlocked()


def enqueue(sha: str, short_sha: str, subject: str) -> dict:
    """Add to queue. Idempotent on (sha) — same SHA already queued or
    currently in_progress.acknowledged_briefs returns existing state."""
    with _with_lock():
        state = _read_unlocked()
        if any(e["sha"] == sha for e in state["queued"]):
            return state
        in_prog = state.get("in_progress") or {}
        ack = in_prog.get("acknowledged_briefs", [])
        if any(e["sha"] == sha for e in ack):
            return state
        state["queued"].append({
            "sha": sha,
            "short_sha": short_sha,
            "brief": extract_brief_number(subject),
            "subject": subject,
            "queued_at": _now_iso(),
        })
        _write_unlocked(state)
        return state


def claim_for_deploy() -> Optional[dict]:
    """Atomically: if in_progress is None and queue non-empty, MOVE all
    queued entries into in_progress.acknowledged_briefs, set deploy_sha to
    the latest queued entry, clear queued, and return the in_progress dict.
    New pushes that arrive during deploy land in queued (now empty) and
    are NOT swept by complete_deploy."""
    with _with_lock():
        state = _read_unlocked()
        if state.get("in_progress"):
            return None
        if not state["queued"]:
            return None
        latest = state["queued"][-1]
        in_progress = {
            "deploy_sha": latest["sha"],
            "deploy_short_sha": latest["short_sha"],
            "deploy_brief": latest["brief"],
            "deploy_subject": latest["subject"],
            "started_at": _now_iso(),
            "acknowledged_briefs": list(state["queued"]),
        }
        state["in_progress"] = in_progress
        state["queued"] = []
        _write_unlocked(state)
        return in_progress


def complete_deploy(status: str, duration_s: int) -> None:
    """Move in_progress.acknowledged_briefs to history with the same
    deployed_at timestamp + status. Clear in_progress. Queue is untouched
    (any pushes that arrived during the deploy stay in queued)."""
    with _with_lock():
        state = _read_unlocked()
        in_prog = state.get("in_progress")
        if not in_prog:
            return
        deployed_at = _now_iso()
        deploy_sha = in_prog["deploy_sha"]
        for entry in in_prog.get("acknowledged_briefs", []):
            state["history"].insert(0, {
                "sha": entry["sha"],
                "short_sha": entry["short_sha"],
                "brief": entry["brief"],
                "subject": entry["subject"],
                "deployed_at": deployed_at,
                "duration_s": duration_s,
                "status": status,
                "deployed_via_sha": deploy_sha,
            })
        state["history"] = state["history"][:HISTORY_MAX]
        state["in_progress"] = None
        _write_unlocked(state)
