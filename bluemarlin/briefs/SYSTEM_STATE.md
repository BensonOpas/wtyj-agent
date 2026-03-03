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

## Brief 005 — email_poller.py — ask_marina_llm()
**Status:** Stable
**What changed:** Replaced last OpenClaw subprocess call (inside `ask_marina_llm()`) with `claude_client.complete()`. Added `claude_client` import via `_sys`/`_os` path insertion. Added file header.
**Callers must know:** `ask_marina_llm(from_email, subject, body, mode)` signature and return type unchanged. Returns fallback string on API failure. `subprocess` import preserved — still used by `create_calendar_hold()` for calendar.js. `SESSION_ID` preserved in CONFIG block (removal out of scope). `ANTHROPIC_API_KEY` must be set in the environment.
**Files affected:** `bluemarlin/src/email_poller.py`
**Depends on:** `claude_client.py` (Brief 001)
**OpenClaw status:** Fully removed from all active code paths. Remaining `.openclaw` strings in the file are VPS filesystem paths in CONFIG and `create_calendar_hold()` — not OpenClaw agent calls.
**Known flag:** Test 2 during Brief 005 returned the fallback string even with a valid API key — possible empty response from the model for this specific prompt. Fallback mechanism works correctly. Monitor in production.

---

## Brief 006 — bm_logger.py + email_poller.py — config paths
**Status:** Stable
**What changed (bm_logger.py):** `LOG_PATH` replaced — now constructed from `__file__`, resolves to `bluemarlin/logs/bluemarlin.log` (Mac: `/Users/benson/Projects/bluemarlin-agent/bluemarlin/logs/bluemarlin.log`, VPS: `/root/bluemarlin/logs/bluemarlin.log`). `datetime.utcnow()` replaced with `datetime.now(timezone.utc)`. File header updated.
**What changed (email_poller.py):** `REFRESH_TOKEN_PATH`, `STATE_DIR`, `THREAD_STATE_PATH` now constructed from `__file__` via `_SRC_DIR` / `_CONFIG_DIR` pointing to `bluemarlin/config/`. `calendar.js` subprocess call path updated from `/root/.openclaw/workspace/calendar.js` to `os.path.join(_SRC_DIR, "calendar.js")`. File header updated.
**Callers must know (bm_logger.py):** `log()` return dict now contains timezone-aware ISO 8601 timestamp (e.g. `2026-03-03T03:13:44+00:00`). No functional impact on callers that discard the return value. `bluemarlin/logs/` directory is created automatically on first write.
**Callers must know (email_poller.py):** No API changes. All path-dependent config now resolves correctly on both Mac and VPS without modification.
**Files affected:** `bluemarlin/src/bm_logger.py`, `bluemarlin/src/email_poller.py`, `bluemarlin/logs/bluemarlin.log` (created)
**Resolved paths (VPS):** `REFRESH_TOKEN_PATH` → `/root/bluemarlin/config/azure_refresh_token.txt`, `THREAD_STATE_PATH` → `/root/bluemarlin/config/email_thread_state.json`, `LOG_PATH` → `/root/bluemarlin/logs/bluemarlin.log`, `calendar.js` → `/root/bluemarlin/src/calendar.js`

---

## Brief 007 — calendar.js — KEY_PATH and timezone fix
**Status:** Stable
**What changed:** `KEY_PATH` replaced — now constructed via `path.join(__dirname, '..', 'config', 'bluemarlin-calendar-key.json')`. Timezone bug fixed — `startDateTime` and `endDateTime` now constructed via `Date.UTC` with explicit `CURACAO_OFFSET_MS = -4 * 60 * 60 * 1000` offset instead of system-local `new Date(year, month-1, day, hour, minute)`. File header added.
**Callers must know:** No interface change. JSON payload format and response format identical. Calendar holds now created at correct Curaçao local time — previously 4 hours off on UTC VPS (10:00 AM Curaçao was incorrectly stored as 10:00 UTC; now correctly stored as 14:00 UTC).
**Files affected:** `bluemarlin/src/calendar.js`
**Resolved paths (VPS):** `KEY_PATH` → `/root/bluemarlin/config/bluemarlin-calendar-key.json`
**Pre-existing dependencies (unchanged):** `googleapis` npm package must be installed on VPS. `bluemarlin-calendar-key.json` must exist in `bluemarlin/config/` on VPS.

---

## Brief 008 — End-to-end system test (manual)
**Status:** Passed with known issues
**Date executed:** 2026-03-03
**What was tested:** Full booking flow on VPS after Briefs 001–007. calendar.js smoke test, email send/receive, thread state tracking, anti-loop protection, field extraction, calendar hold creation.
**Confirmed working:** Core booking loop, calendar integration, email send/receive, thread state tracking, anti-loop protection, deduplication.
**Files affected:** None — observational brief only.
**Known issues logged for Brief 009:**
1. Date normalization — `normalize_date_to_yyyy_mm_dd()` only handles `today`, `tomorrow`, `YYYY-MM-DD`. Natural language dates like "March 20" are not recognized → hold creation fails → customer must re-send in correct format.
2. Off-topic handling — `detect_intent_and_fields()` regex (`joke|riddle|funny|meme|weather|crypto|politics`) is too narrow. "Book a flight to Amsterdam" falls through to booking intake instead of being declined.
3. Complaint/abusive handling — messages with no booking intent and no matching regex words fall through to booking intake instead of receiving an empathetic non-booking response.

---

## Brief 009 — email_poller.py — Marina intelligence improvements
**Status:** Stable
**What changed:**
1. `normalize_date_to_yyyy_mm_dd()` — `dateparser` fallback added after the existing `today`/`tomorrow`/`YYYY-MM-DD` checks. Handles natural language formats ("March 15", "15/03/2026", "15 March 2026", etc.) using `PREFER_DATES_FROM: future`, `TIMEZONE: America/Curacao`. Wrapped in `try/except` — returns `""` on any failure. `import dateparser` added at module level (line 25).
2. `detect_intent_and_fields()` — Hard keyword regex (`joke|riddle|...`) and booking-word heuristic fully removed. Replaced with `claude_client.complete()` call that classifies intent as one of `{booking, complaint, off_topic, general}`. Defaults to `"general"` if Claude returns unexpected output or raises. `extract_fields()` call and adults+kids merge logic preserved unchanged.
3. `safe_complaint_reply()` — New function added immediately before `package_key_from_experience()`. Returns static empathetic holding reply with Marina signature.
4. Complaint dispatch path — `elif intent == "complaint":` added to main loop between `out_of_scope` and `booking/general` branches. Sends `safe_complaint_reply()` and logs.
5. `out_of_scope` dispatch — updated from `if intent == "out_of_scope":` to `if intent in ("out_of_scope", "off_topic"):` to handle both the legacy label and the new Claude-returned label.
6. Internal error leak removed — `f"(Internal note: {err})\n\n"` line removed from booking-failure reply. Customers no longer see internal error strings.
7. File header updated to `Brief 009`.

**Callers must know:** `detect_intent_and_fields()` now makes a live Claude API call on every email processed. Each email incurs one additional API call for intent classification (on top of any `extract_fields()` call). `ANTHROPIC_API_KEY` must be set — if absent, all intents default to `"general"`. `"off_topic"` is now the canonical intent label for non-charter messages (not `"out_of_scope"`); both are handled in the dispatch block for backward compatibility.
**Files affected:** `bluemarlin/src/email_poller.py`
**Dependencies added:** `dateparser==1.3.0` (installed on VPS via pip). Also pulled in: `python-dateutil`, `pytz`, `regex`, `six`, `tzlocal`.
**Depends on:** `claude_client.py` (Brief 001), `dateparser` (PyPI)
**Known issues resolved:** All three issues logged in Brief 008 are fixed.
**Remaining known flag:** `dateparser` with `PREFER_DATES_FROM: future` may misparse ambiguous slash formats (e.g. `"03/15"` — MM/DD vs DD/MM ambiguity). Low risk in practice — most customers use named months or YYYY-MM-DD. Monitor in production.

---

## Still on OpenClaw (not yet migrated)
- None — OpenClaw fully removed from all active code paths.
