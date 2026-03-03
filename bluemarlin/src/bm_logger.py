# FILE: bm_logger.py
# CREATED: Before Brief 001 (original codebase)
# LAST MODIFIED: Brief 006
# DEPENDS ON: nothing
# IMPORTS FROM: nothing
# CALLERS: email_poller.py (original)
import json
import os
from datetime import datetime, timezone

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(_BASE_DIR, "..", "logs", "bluemarlin.log")
LOG_PATH = os.path.normpath(LOG_PATH)

def log(event: str, **fields):
    """
    Minimal structured log line (JSONL).
    Deterministic code should call this for side-effect milestones.
    """
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec
