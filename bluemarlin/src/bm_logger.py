import json
import os
from datetime import datetime

LOG_PATH = "/root/.openclaw/bluemarlin_demo.log"  # single audit file

def log(event: str, **fields):
    """
    Minimal structured log line (JSONL).
    Deterministic code should call this for side-effect milestones.
    """
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    rec = {
        "ts": datetime.utcnow().isoformat(),
        "event": event,
        **fields
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec
