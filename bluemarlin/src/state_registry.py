# FILE: state_registry.py
# CREATED: Before Brief 001 (original codebase)
# LAST MODIFIED: Brief 004
# DEPENDS ON: nothing
# IMPORTS FROM: nothing
# CALLERS: email_poller.py (original)
import hashlib
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "state_registry.db"
)


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS processed_hashes ("
        "hash TEXT PRIMARY KEY, "
        "created_at TEXT NOT NULL"
        ")"
    )
    return conn


def generate_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def has_been_processed(content: str) -> bool:
    content_hash = generate_content_hash(content)
    conn = _get_conn()
    row = conn.execute(
        "SELECT count(*) FROM processed_hashes WHERE hash = ?",
        (content_hash,)
    ).fetchone()
    conn.close()
    return row[0] > 0


def mark_as_processed(content: str):
    content_hash = generate_content_hash(content)
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO processed_hashes (hash, created_at) VALUES (?, ?)",
        (content_hash, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()


# Initialise database on module load so the file exists as soon as the module is imported
_get_conn().close()
