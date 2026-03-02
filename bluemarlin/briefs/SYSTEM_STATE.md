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

## Still on OpenClaw (not yet migrated)
- `bluemarlin/src/social_drafter.py`
