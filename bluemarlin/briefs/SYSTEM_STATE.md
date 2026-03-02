# SYSTEM_STATE.md
# Updated after each brief. Read this before writing any new brief.

---

## Brief 001 — claude_client.py
**Status:** Stable
**What changed:** New file created. Exposes `complete(prompt, system=None) -> str` and `extract(prompt) -> dict` wrapping the Anthropic API directly.
**Callers must know:** `ANTHROPIC_API_KEY` env var must be set. Both functions fail silently — `complete()` returns `""` and `extract()` returns `{}` on any error. Never raises.
**Files affected:** `bluemarlin/src/claude_client.py`
**Depends on:** anthropic (PyPI)

---

## Brief 002 — marina_extractor.py
**Status:** Stable
**What changed:** Replaced OpenClaw subprocess call with `claude_client.extract()`. Removed `import json`, `import subprocess`, `import re`, and `SESSION_ID`. Added file header.
**Callers must know:** `extract_fields(text: str)` signature and return type unchanged. Returns a dict filtered to `ALLOWED_KEYS` or `{}` on any failure. Internal mechanism changed from OpenClaw subprocess to direct Anthropic API call via `claude_client`. `ANTHROPIC_API_KEY` must be set in the environment.
**Files affected:** `bluemarlin/src/marina_extractor.py`
**Depends on:** `claude_client.py` (Brief 001)

---

## Brief 003 — social_drafter.py
**Status:** Stable
**What changed:** Replaced OpenClaw subprocess call with `claude_client.complete()`. Removed `import subprocess` and `SESSION_ID`. Added file header.
**Callers must know:** `draft_post(platform, context) -> dict` signature and return shape unchanged. Returns fallback-text draft on API failure. `ANTHROPIC_API_KEY` must be set in the environment.
**Files affected:** `bluemarlin/src/social_drafter.py`
**Depends on:** `claude_client.py` (Brief 001), `social_registry.py` (original)
**Known design issue:** `social_registry` content_id is keyed on generated text not input context. Duplicate drafts possible if same context is passed twice. Fix in future brief when social layer is built out.

---

## Brief 004 — state_registry.py
**Status:** Stable
**What changed:** Migrated from JSON flat file to SQLite. Fixed race condition via `INSERT OR IGNORE`. Fixed unbounded list growth. `DB_PATH` constructed from `__file__` — resolves to `bluemarlin/src/state_registry.db` (Mac: `/Users/benson/Projects/bluemarlin-agent/bluemarlin/src/state_registry.db`, VPS: `/root/bluemarlin/src/state_registry.db`). Database initialised on module import via module-level `_get_conn().close()`. WAL mode enabled on every connection.
**Callers must know:** `has_been_processed(content)` and `mark_as_processed(content)` signatures and return types unchanged. `state.json` is no longer read or written. Old processed hashes are not migrated — on first run after deployment, previously processed emails may be processed once more.
**Files affected:** `bluemarlin/src/state_registry.py`, `bluemarlin/src/state_registry.db` (created)
**Depends on:** nothing (sqlite3 is stdlib)
**Callers:** `email_poller.py` (original) — requires zero changes

---

## Still on OpenClaw (not yet migrated)
- None — migration complete.
