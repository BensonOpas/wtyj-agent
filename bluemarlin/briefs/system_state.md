# SYSTEM_STATE.md
# **Owns:** The HISTORY — what each brief did, its outcome, what callers must know.
# **Related:** For what's next → `roadmap.md`. For infrastructure → `infra.md`. For the vision → `master_plan.md`.
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

## Brief 010 — systemd service
**Status:** Stable
**What changed:** `email_poller.py` is now managed as a systemd service. Starts automatically on boot, restarts on failure with a 10-second delay, logs to journald.
**Files created (VPS only — not in Git):**
- `/etc/systemd/system/bluemarlin.service` — unit file
- `/root/bluemarlin/config/bluemarlin.env` — `ANTHROPIC_API_KEY` env var (chmod 600, covered by config/ gitignore)
**Service management:** `systemctl start|stop|restart|status bluemarlin` / `journalctl -u bluemarlin -f`
**Callers must know:** The poller is no longer started manually. To deploy a code change: push to Git, pull on VPS, then `systemctl restart bluemarlin`. To check for crashes: `journalctl -u bluemarlin -n 50`.
**EnvironmentFile note:** Leading `-` on `EnvironmentFile` means service starts even if `bluemarlin.env` is missing — degrades gracefully (intents fall back to `"general"`). After any fresh VPS provision, `bluemarlin.env` must be recreated manually before production use.
**Files affected:** None in Git. VPS-only files: `/etc/systemd/system/bluemarlin.service`, `/root/bluemarlin/config/bluemarlin.env`.
**Depends on:** systemd (Ubuntu built-in)

---

## Brief 011 — marina_extractor.py — special_requests field
**Status:** Stable
**What changed:** `special_requests` added as an 8th extraction field to `marina_extractor.py`. `ALLOWED_KEYS` updated. Extraction prompt updated with annotated field descriptions and a new rule: capture verbatim, omit entirely if not mentioned. Function signature, return type, and `claude_client` import block unchanged. Filter line (`clean = {k: v ...}`) unchanged — handles the new key automatically.
**Callers must know:** `extract_fields()` may now return a `special_requests` key (plain string, verbatim from customer message). Absent when no special requests are mentioned. `email_poller.py` is unaffected — unknown fields accumulate in `th["fields"]` and are ignored by existing logic. `special_requests` is now available in the thread state for future use but is not yet surfaced in the confirmation email, calendar hold payload, or `bm_logger` output.
**Files affected:** `bluemarlin/src/marina_extractor.py`
**Dependencies added:** None.
**Known flag:** `special_requests` is a dead field until a future brief surfaces it — confirmation email, calendar hold description, or structured log. Data is being captured; it is not being used yet.

---

## Brief 012 — email_poller.py — expand structured logging
**Status:** Stable
**What changed:** `bm_logger.log()` calls added at 6 key events in the main loop. Previously only `hold_created` was structured-logged (1 call). Now 6 events are logged:
1. `off_topic_received` — email, subject, body_snippet (first 200 chars)
2. `complaint_received` — email, subject, body_snippet (first 200 chars)
3. `missing_fields_requested` — email, subject, missing (list), fields_so_far (list of keys)
4. `booking_attempted` — email, subject, experience, date, guests, customer_name, phone, special_requests (logged immediately before `create_calendar_hold()`)
5. `hold_created` — expanded from 4 fields to 12: email, subject, event_id, html_link, payment_id, payment_link, experience, date, guests, customer_name, phone, special_requests
6. `hold_failed` — email, subject, error, experience, date, guests

**Callers must know:** No runtime behaviour changes — logging only. `bluemarlin/logs/bluemarlin.log` will now contain entries for all 6 event types in JSONL format. `missing` and `fields_so_far` are serialised as JSON arrays. `body_snippet` is capped at 200 chars — full body is never logged. `phone` and `customer_name` appear in `booking_attempted` and `hold_created` — the log file contains PII and must be treated accordingly. `special_requests` is now surfaced in structured logs (closes the dead-field flag from Brief 011 for logging purposes; confirmation email surfacing remains a future brief).
**Files affected:** `bluemarlin/src/email_poller.py`
**Dependencies added:** None.
**Depends on:** `bm_logger.py` (original, Brief 006)

---

## Brief 013 — sheets_writer.py (NEW) + email_poller.py — Google Sheets dashboard
**Status:** Stable
**What changed:**

`sheets_writer.py` — new file created. Appends rows to the BlueMarlin Operations Dashboard Google Sheet in real time. Four public functions:
- `log_hold_created(data)` → Bookings tab (13 cols, status=CREATED) + All Events tab
- `log_hold_failed(data)` → Bookings tab (13 cols, status=FAILED) + All Events tab
- `log_complaint(data)` → Complaints tab (6 cols, status=NEW) + All Events tab
- `log_event(event_type, data)` → All Events tab only (5 cols)

All four functions wrapped in `try/except` — never raise, never crash `email_poller.py`. `_get_service()` called fresh per write (no persistent connection). `KEY_PATH` resolves from `__file__`. `SPREADSHEET_ID` hardcoded as module constant.

`email_poller.py` — `import sheets_writer` added. Six call sites added, one immediately after each `bm_logger.log()` call: `off_topic_received`, `complaint_received`, `missing_fields_requested`, `booking_attempted`, `hold_failed`, `hold_created`. No existing logic changed. File header updated to `Brief 013`.

**Sheet structure (Spreadsheet ID: `1soG3zVnx-Y0WYWGJdgakXqpNeI6GAe6AD8DycOwwifE`):**
- Tab `Bookings`: Timestamp, Customer Name, Email, Experience, Date, Guests, Phone, Special Requests, Hold Status, Event Link, Payment Link, Error, Operator Notes
- Tab `Complaints`: Timestamp, Email, Subject, Message Preview, Status, Operator Notes
- Tab `All Events`: Timestamp, Event Type, Email, Subject, Details (JSON)

**Callers must know:** Each of the 6 structured log events now triggers one Google Sheets API call (~100–300ms latency). If Sheets API is unavailable, error is printed to stdout (→ journald) and `email_poller` continues normally. Test rows with `test@example.com` are live in the sheet — delete before go-live.
**Files affected:** `bluemarlin/src/sheets_writer.py` (new), `bluemarlin/src/email_poller.py`
**Dependencies added:** `google-api-python-client==2.191.0`, `google-auth==2.48.0` (plus transitive deps including `httplib2`, `cryptography`, `pyasn1`, `rsa`)
**Depends on:** `bluemarlin-calendar-key.json` (VPS config, gitignored), Google Sheets API (enabled on existing service account)

---

## Brief 014 — format_sheets.py (NEW) — Google Sheets dashboard formatting
**Status:** Stable
**What changed:** `format_sheets.py` created as a run-once manual formatting script. Applies the BlueMarlin color palette to all three dashboard tabs (Bookings, Complaints, All Events). Writes header rows and applies formatting via a single batched `batchUpdate` API call per tab. Not imported by any other module — no impact on the live booking loop.
**Format applied per tab:**
- Entire sheet background: deep navy `#1a2744`
- Header row: `#243460` background, white bold 11pt text, centered, frozen
- Header bottom border: `SOLID_MEDIUM` in `#2e7d9e`
- Body rows 1–1000: text `#e8edf5`, 10pt, vertically centered
- Column widths: Bookings 160px × 13, Complaints 200px × 6, All Events 160px × 4 + 400px for Details column
- Row height: 32px all rows
**To run:** `python3 bluemarlin/src/format_sheets.py` — prints `Formatted: {tab}` per tab, then `Done.`
**Idempotent:** safe to re-run; last-write-wins for all formatting. Will overwrite any manual header formatting.
**Files affected:** `bluemarlin/src/format_sheets.py` (new). No other files modified.
**Dependencies added:** None — `google-api-python-client` and `google-auth` already installed in Brief 013.
**Depends on:** `sheets_writer.py` (imports `KEY_PATH`, `SPREADSHEET_ID`, `_get_service`), `bluemarlin-calendar-key.json`

---

## Brief 015 — format_sheets.py — dashboard polish
**Status:** Stable
**What changed:** `format_sheets.py` updated with a revised color palette, per-column widths, text wrapping, alternating row banding, and deletion of extra empty columns. `_build_requests()` fully replaced with a 9-request version. Second `batchUpdate` call added to cap data row height at 80px.
**New color palette:**
- Sheet background fill: `#1a2030`
- Header background: `#2a3545`
- Header text: `#ffffff` bold 11pt, CENTER, CLIP wrap
- Body text: `#e8edf5` 10pt, MIDDLE, WRAP
- Odd rows: `#1e2530`, even rows: `#242f3d` (via banding)
- Header bottom border: `SOLID_MEDIUM` in `#3d8eb9`
**Column widths (individual per-column requests):**
- Bookings (13 cols): `[180,150,200,180,110,80,130,250,110,200,200,200,250]`
- Complaints (6 cols): `[180,200,200,300,110,250]`
- All Events (5 cols): `[180,150,200,200,400]`
**Row heights:** 40px all rows (Request 5), then second `batchUpdate` sets data rows 1–1001 to 80px max.
**Idempotency mechanisms:**
- Existing `bandedRangeId`s fetched from metadata and deleted (via `deleteBanding`) before `addBanding` — in same `batchUpdate` (atomic)
- `deleteDimension` guarded by `column_count > n` check — prevents 400 error on re-run
- All `repeatCell`, `updateSheetProperties`, `updateDimensionProperties`, `updateBorders` are last-write-wins
**Verified:** second run produces identical output, no errors. Column counts exact: Bookings 13, Complaints 6, All Events 5.
**Files affected:** `bluemarlin/src/format_sheets.py` only. No other files modified.
**Dependencies added:** None.

---

## Brief 016 — email_poller.py — multi-label intent classification
**Status:** Stable
**What changed:** `detect_intent_and_fields()` replaced with multi-label classifier. Returns `(list[str], dict)` instead of `(str, dict)`. Full intent dispatch block replaced.
**New intent label set (7 labels):** `booking`, `inquiry`, `cancellation`, `reschedule`, `complaint`, `social`, `off_topic`. `general` removed.
**Classifier:** Prompt updated to request JSON array. Response parsing handles markdown code fences, validates against `VALID_INTENTS`, defaults to `["inquiry"]` on any failure.
**Dispatch logic:**
- `off_topic` only fires if it is the sole intent (`intents == ["off_topic"]`)
- `social` only fires as pure-social if no actionable intent present alongside it
- `complaint`, `cancellation`/`reschedule`, `inquiry`, `booking` each handled independently — multiple can fire per message
- Booking flow unchanged — wrapped in `if "booking" in intents:`
**New reply functions added:** `safe_social_reply()`, `safe_inquiry_reply()`, `safe_change_request_reply(action: str)`
**New bm_logger events:** `social_received`, `cancellation_requested`, `reschedule_requested`, `inquiry_received`
**`import json` added** at module level (no duplicate).
**All 10 tests passed.**
**Files affected:** `bluemarlin/src/email_poller.py`
**Dependencies added:** None.

---

## Brief 017 — email_poller.py — warm confirmation email
**Status:** Stable
**What changed:** Booking confirmation email rewritten for warmth and personalisation. No logic changes — only the `confirm` string construction.
**Changes to confirm block:**
- Greeting: `"Hi,"` → `f"Hi {name},"`
- `social_opener` injected after greeting — fires when `"social" in intents`, empty string otherwise
- Hold-created line: `"you're one step closer to an unforgettable day on the water!"`
- Fields reordered: Package, Date, Guests (name removed from fields — already in greeting)
- `special_note` injected after fields — fires when `fields_now.get("special_requests")` is truthy, empty string otherwise
- Payment section reworded with 6-hour hold CTA; `payment_status` line removed
- Payment link prefixed with 💳 emoji
- Added: "If you have any questions at all, just reply to this email and we'll take care of you."
- Added: "See you on the water! 🐟"
- Sign-off unchanged
**`social_opener` and `special_note` are pure string expressions — cannot raise exceptions.**
**All 3 tests passed.**
**Files affected:** `bluemarlin/src/email_poller.py`
**Dependencies added:** None.

---

## Brief 018 — email_poller.py + marina_extractor.py — three bug fixes
**Status:** Stable
**Files affected:** `bluemarlin/src/email_poller.py`, `bluemarlin/src/marina_extractor.py`
**Dependencies added:** None.

**Fix 1 — Anti-loop constants (email_poller.py):**
- `MAX_REPLIES_PER_THREAD` 3 → 10
- `REPLY_WINDOW_SECONDS` 10 min → 60 min
- Reason: 3-reply/10-minute window was too tight for legitimate multi-turn bookings (missing fields → name/phone → confirm = 3 exchanges minimum).

**Fix 2 — Past date guard (email_poller.py, inside `create_calendar_hold()`):**
- Added immediately after `if not date_iso:` early-return block.
- Returns `{"ok": False, "error": "Requested date YYYY-MM-DD is in the past."}` before calling `calendar.js`.
- `_date` alias used (`from datetime import date as _date`) to avoid shadowing the `date` local variable defined later in the booking flow.
- Existing `hold_failed` dispatch handles this error shape correctly — Marina replies with 3 alternative dates.
- Known edge case: `date.today()` on a UTC VPS could reject a valid same-day Curaçao booking in the 4-hour window before UTC midnight. Accepted for demo system.

**Fix 3 — `special_requests` prompt tightened (marina_extractor.py):**
- Key annotation updated: "forward-looking preferences for the upcoming trip only ... Exclude complaints about past experiences."
- Rule updated: "capture ONLY forward-looking personal preferences ... Do NOT capture complaints about past experiences, negative feedback, or anything referring to a previous trip."
- Reason: "Last time the music was too loud" was being captured as `special_requests` due to "any personal context" wording. Intent classifier correctly handles complaints — extractor should not also grab them.
- `extract_fields()` will no longer return `special_requests` for complaint-only or past-experience text.

**All 7 tests passed.**

---

## Brief 019 — email_poller.py — ambiguous date confirmation flow
**Status:** Stable
**Files affected:** `bluemarlin/src/email_poller.py`
**Dependencies added:** None.

**New functions:**
- `is_date_ambiguous(date_val: str) -> bool` — Returns `True` when no 4-digit year (`20\d{2}`) is found in the string. `"today"` and `"tomorrow"` return `False`. Uses existing `re` import.
- `safe_date_confirmation_reply(resolved_date: str, original: str) -> str` — Formats resolved date to `"%B %d, %Y"` and returns a confirmation-request string with Marina signature. Falls back to raw `resolved_date` on any parse error. Never raises.
- `is_date_confirmation_yes(text: str) -> bool` — Returns `True` if message is exactly a confirmation word or starts with one followed by a space or comma. Confirm words: yes, yeah, yep, yup, correct, confirmed, sure, ok, okay, si, ja, affirmative, that's right, thats right, right, exactly.

**New thread flags:** `awaiting_date_confirmation`, `pending_date`, `pending_date_original` — stored in `th["flags"]`.

**Date confirmation intercept (Change 4a):** Runs immediately after `detect_intent_and_fields()`, before field merging. When `awaiting_date_confirmation` is set:
- Customer confirmed → lock date into `th["fields"]["date"]`, clear flag, fall through to normal booking flow.
- Customer sent a new date → if still ambiguous, ask again; if explicit year, lock it and fall through; if unparseable, ask again with original pending date.
- No date in message → ask again with original pending date.
- All `continue` branches save thread state before exiting.

**Ambiguity check (Change 4b):** Runs inside `if "booking" in intents:`, immediately before `missing = [f for f in REQUIRED_FIELDS if f not in merged]`. When `raw_date` is present, resolves, is ambiguous, and `awaiting_date_confirmation` is not already set — sends `safe_date_confirmation_reply()`, logs `date_confirmation_requested` to `bm_logger` and `sheets_writer`, saves state, `continue`.

**Thread state default:** Now includes `"flags": {}`. `th.setdefault("flags", {})` retained in intercept block as safety net for threads loaded from pre-019 state files.

**No changes to:** `normalize_date_to_yyyy_mm_dd()`, intent classifier, reply functions, or booking flow.

**All 5 tests passed.**

---

## Brief 020 — email_poller.py + marina_extractor.py — booking intake fixes
**Status:** Stable
**Files affected:** `bluemarlin/src/email_poller.py`, `bluemarlin/src/marina_extractor.py`
**Dependencies added:** None.

**email_poller.py changes:**
- `GROUP_BOOKING_THRESHOLD = 15` added after `REQUIRED_FIELDS` constant block.
- `is_date_ambiguous()` removed entirely — replaced by `classify_date_input()`.
- `classify_date_input(date_val: str) -> str` — 5-category classifier placed immediately after `normalize_date_to_yyyy_mm_dd()` (calls it internally). Returns one of: `CLEAR_FUTURE`, `PAST`, `IMPLAUSIBLE`, `VAGUE_RESOLVABLE`, `VAGUE_NEEDS_INPUT`. IMPLAUSIBLE threshold: >11 months (335 days) from today with no explicit year. VAGUE_PATTERNS list covers: this/next weekend, next/this month, next week, easter, christmas, new year, thanksgiving, summer, winter, spring, autumn, fall, holiday, vacation, soon, sometime, flexible, any day, anytime, whenever. RESOLVABLE_PATTERNS cover: next/this Mon–Sun, in two weeks, in a week, in 2/3 weeks.
- New reply functions added: `safe_large_group_reply(guests)`, `safe_date_past_reply(resolved_date, original)`, `safe_date_implausible_reply(resolved_date, original)`, `safe_date_vague_reply(original, resolvable_date="")`.
- `safe_date_confirmation_reply()` tone updated — less robotic, conversational.
- `experience_is_clear(exp: str) -> bool` added after `package_key_from_experience()` — returns `bool(package_key_from_experience(exp))`.
- `safe_experience_unclear_reply(provided: str) -> str` added — shows all 3 packages with duration and departure time.
- Date confirmation intercept (Brief 019): `is_date_ambiguous` reference updated to `classify_date_input(new_date) in ("VAGUE_RESOLVABLE", "VAGUE_NEEDS_INPUT")`.
- **Three-check block** inside `if "booking" in intents:`, in order before missing fields check:
  1. Date classification check — PAST → `safe_date_past_reply()` → continue; IMPLAUSIBLE → sets `awaiting_date_confirmation`, `safe_date_implausible_reply()` → continue; VAGUE_NEEDS_INPUT or VAGUE_RESOLVABLE → sets `awaiting_date_confirmation`, `safe_date_vague_reply()` → continue; CLEAR_FUTURE → fall through.
  2. Experience clarity check — unknown experience → sets `awaiting_experience_clarification`, `safe_experience_unclear_reply()` → continue; clear → fall through.
  3. Large group check — `int(guests) >= 15` → `safe_large_group_reply()`, `sheets_writer.log_complaint()` → continue; under threshold → fall through.
- New thread flag: `awaiting_experience_clarification`.
- New bm_logger events: `date_past_detected`, `date_implausible_detected`, `date_vague_detected`, `experience_unclear`, `large_group_detected`.

**marina_extractor.py changes:**
- `guests` field annotation updated: exact integer only. "Just me" = 1. "Me and my wife" = 2. Infants/babies not counted — added to `special_requests` instead. Approximate language ("around", "about", "roughly") → omit field entirely.
- `adults`/`kids` annotations updated: kids does not include infants.
- New rule in Rules block: extract ONLY a definite integer for guests; approximate language → omit; infant alongside count → not included, add "travelling with an infant" to special_requests.

**All 8 tests passed.**

---

## Brief 022 — client.json + config_loader.py
**Status:** Stable
**Files created:** `bluemarlin/config/client.json`, `bluemarlin/src/config_loader.py`
**What changed:** `client.json` created as the single source of truth for all BlueFinn business data (business info, trips, fleet, FAQ, booking rules, payment policy, common sense knowledge). `config_loader.py` created as the read-only interface to that file.
**Getters:** `get_business()`, `get_trips()`, `get_trip(trip_key)`, `get_faq()`, `get_faq_answer(question_key)`, `get_booking_rules()`, `get_payment()`, `get_fleet()`, `get_agent_signature()`, `get_common_sense_knowledge()`
**Callers must know:** Never raises. Caches parsed JSON in a module-level `_cache` dict after first read. Path resolves relative to `__file__` — works on both Mac and VPS without modification. All `[VERIFY]` items are preserved as literal placeholder strings in `client.json` — do not treat them as real values; they are awaiting BlueFinn confirmation before go-live.
**[VERIFY] items outstanding:**
1. Exact cancellation policy terms
2. Private charter pricing
3. All five `calendar_id` values — current `calendar.js` has three invented IDs that do not map to real BlueFinn trips
4. Vessel and departure point for snorkeling_3in1, west_coast_beach, and sunset_cruise trips
5. Whether there is shade on the boats
**Files affected:** `bluemarlin/config/client.json` (new), `bluemarlin/src/config_loader.py` (new)
**Depends on:** `bluemarlin/config/client.json` (stdlib only — no PyPI dependencies)

---

## Brief 023 — marina_agent.py — Unified Claude Call
**Status:** Stable
**Files created:** `bluemarlin/src/marina_agent.py`
**What changed:** Unified Claude call implemented as standalone module. One public function: `process_message(from_email, subject, body, thread_fields, thread_flags) -> dict`. Makes exactly one direct `anthropic.Anthropic()` call with `max_tokens=2048`. All business data injected from `config_loader`. `[VERIFY]` fields stripped before prompt injection via `_filter_verify()`. Returns structured dict with 8 required fields: `intents`, `fields`, `confidence`, `reply`, `clarifications_needed`, `requires_human`, `flags`, `internal_note`. Never raises — returns signed fallback on any failure. `email_poller.py` untouched.
**Callers must know:** `ANTHROPIC_API_KEY` must be set in environment. Model hardcoded as `claude-sonnet-4-6` — flag for Brief 024.
**Files affected:** `bluemarlin/src/marina_agent.py` (new)
**Depends on:** `config_loader.py` (Brief 022), `anthropic` (PyPI)
**Tests:** 8/8 pass

---

## Brief 024 — email_poller.py refactor — unified Claude call integration
**Status:** Stable
**Files modified:** `bluemarlin/src/email_poller.py`, `bluemarlin/src/marina_agent.py`
**What changed:** `email_poller.py` refactored from 1241 to 452 lines. All drift removed — 19 functions deleted, 2 constants deleted (`REQUIRED_FIELDS`, `GROUP_BOOKING_THRESHOLD`), `dateparser` and `claude_client` imports removed. Python is now a pure orchestrator: one `marina_agent.process_message()` call per message, routes on structured values, persists state, calls calendar and payment APIs. `marina_agent.py` amended to extract `trip_key` in addition to existing fields.
**Architecture:** All language decisions now belong to Claude via `marina_agent`. Python never interprets reply content or message meaning. Reply is sent exactly as returned from `marina_agent` — Python routes on structured values only.
**Known items deferred to Brief 025:**
- Anti-loop stop message still contains old BlueMarlin package names
- `smtp_send` From header still says BlueMarlin Tours Curaçao
- `calendar.js` package keys not yet updated to match `client.json` trip keys
**Depends on:** `marina_agent.py` (Brief 023), `config_loader.py` (Brief 022), `state_registry.py` (Brief 004), `calendar.js` (original)
**Tests:** 8/8 pass

---

## Brief 025 — calendar.js + email_poller.py — BlueFinn cleanup
**Status:** Stable
**Files modified:** `bluemarlin/src/calendar.js`, `bluemarlin/src/email_poller.py`
**What changed:** `calendar.js` updated from invented BlueMarlin package keys to real BlueFinn trip keys (`klein_curacao`, `snorkeling_3in1`, `west_coast_beach`, `sunset_cruise`, `jet_ski`). All five calendar IDs are `[VERIFY]` placeholders — any hold attempt will fail gracefully with "Calendar ID not yet configured for: `<trip_key>`" until BlueFinn provides real IDs. `DURATIONS_HOURS` updated to match real trip durations (`snorkeling_3in1` is 4hrs placeholder, unconfirmed). `email_poller.py` From header corrected to BlueFinn Charters Curaçao. Anti-loop message updated to BlueFinn trip names. Unicode escape sequences corrected to literal characters.
**Outstanding before go-live:** BlueFinn must provide all five Google Calendar IDs so `[VERIFY]` placeholders in `calendar.js` and `client.json` can be replaced.
**Depends on:** `email_poller.py` (Brief 024), `client.json` (Brief 022)
**Tests:** 8/8 pass

---

## Brief 026 — Inject real calendar IDs
**Status:** Stable
**Files modified:** `bluemarlin/src/calendar.js`, `bluemarlin/config/client.json`
**What changed:** All five Google Calendar IDs injected with real values provided by BlueFinn. `[VERIFY]` placeholders removed from both files. `[VERIFY]` guard in `calendar.js` updated from `calendarId.startsWith("[VERIFY")` to `!calendarId.endsWith("@group.calendar.google.com")` — equivalent safety, no placeholder string in source. Calendar hold creation is now fully operational for all five trips.
**Calendar IDs set:**
- `klein_curacao`: `ed9e5c8b2357d2e21b99af2617c58836204443ed7e8d7352661426cca41cf4cb@group.calendar.google.com`
- `snorkeling_3in1`: `649576fb0d0eb17fc895981db2f5e2339ac045edf3a4292d40eff57786fa06db@group.calendar.google.com`
- `west_coast_beach`: `a85ac414af5903971715705bb8f0975a0be07ca637017c1184f1ba7cd4ab1c00@group.calendar.google.com`
- `sunset_cruise`: `a3df969d58e35c9603fe6ae6672446ec2f430ed3304f9c5aaf2178391e67defe@group.calendar.google.com`
- `jet_ski`: `903f29c1161ed6d1378b7d4b1f7ef0597ce6707e2648fd98b82b081542919f08@group.calendar.google.com`
**Outstanding `[VERIFY]` items remaining in `client.json` (non-calendar):** cancellation policy, private charter pricing, vessel names for snorkeling/west coast/sunset, shade on boats, `snorkeling_3in1` duration.
**Depends on:** `calendar.js` (Brief 025), `client.json` (Brief 022)
**Tests:** 8/8 pass

---

## Brief 027 — marina_agent.py + email_poller.py — departure_time field + date format enforcement
**Status:** Stable
**Files modified:** `bluemarlin/src/marina_agent.py`, `bluemarlin/src/email_poller.py`
**What changed:** Two live bugs fixed. `marina_agent` now enforces YYYY-MM-DD date format — Claude converts natural language dates before returning; unresolvable dates are omitted and added to `clarifications_needed`. New `departure_time` field added to extractable fields — HH:MM format, only when customer explicitly chooses a departure from available options. `create_calendar_hold` now uses `fields_now.get("departure_time")` with config first-departure as fallback.
**Bugs fixed:**
- "Invalid time value" in `calendar.js` caused by natural language dates ("April 20") instead of YYYY-MM-DD
- Multi-departure trips always used `departures[0]` regardless of customer choice
**Depends on:** `marina_agent.py` (Brief 023), `email_poller.py` (Brief 024)
**Tests:** 8/8 pass

---

## Brief 028 — Booking reference + Sheets data rework
**Status:** Stable
**Files modified:** `bluemarlin/src/sheets_writer.py`, `bluemarlin/src/email_poller.py`
**What changed:** Booking reference generated at hold creation time (format `BF-YYYY-XXXXX`). Stored in thread flags and passed to Sheets. `sheets_writer.py` fully reworked: `log_hold_created` updated to 15-column Bookings row including `booking_ref`, `trip_key`, `departure_time`, `total_price`, `payment_status`. `log_hold_failed` updated to matching 15-column structure. `log_escalation` added — writes to new Escalations tab (6 columns: Timestamp, Customer Name, Email, Intent, Fields Collected JSON, Internal Note) and All Events. `log_complaint` removed (unused since Brief 024). `email_poller.py` human_required block now calls `log_escalation` with full context instead of `log_event`.
**Manual action required:** Escalations tab must be created in Google Sheet before live use. SPREADSHEET_ID: `1soG3zVnx-Y0WYWGJdgakXqpNeI6GAe6AD8DycOwwifE`
**Depends on:** `email_poller.py` (Brief 027), `sheets_writer.py` (Brief 013)
**Tests:** 10/10 pass

---

## Brief 029 — marina_agent.py + email_poller.py — Prompt fixes: confirmation step, escalation, vague date
**Status:** Stable
**Files modified:** `bluemarlin/src/marina_agent.py`, `bluemarlin/src/email_poller.py`
**What changed:** Three live bugs fixed via prompt additions to `_build_prompt()`.
1. **Booking confirmation step:** when all required fields present, Marina sends a booking summary and asks "Shall I lock this in for you?" before any hold is created. Sets `awaiting_booking_confirmation: true` in flags. On customer confirmation, sets `booking_confirmed: true`. `email_poller` booking trigger now requires `booking_confirmed` flag before calling `create_calendar_hold`. `departure_time` is not required to trigger the summary. `flags` field description updated to show explicit key names (`awaiting_booking_confirmation`, `booking_confirmed`) with conditions — generic placeholder was causing model to return `flags: {}`.
2. **Escalation to The Crew:** complaints and cancellations set `requires_human: true`. Marina acknowledges warmly, tells customer "The Crew will be in touch shortly." No detail gathering. No promises.
3. **Vague date enforcement:** date field description replaced in full — vague or unresolvable dates must be omitted and added to `clarifications_needed`. Never infer, guess, or pick a date the customer has not explicitly stated.
**Depends on:** `marina_agent.py` (Brief 027), `email_poller.py` (Brief 028)
**Tests:** 10/10 pass

---

## Brief 030 — marina_agent.py + email_poller.py — Hold failure reply
**Status:** Stable
**Files modified:** `bluemarlin/src/marina_agent.py`, `bluemarlin/src/email_poller.py`
**What changed:** Fixed bug where hold failure sent a false confirmation to the customer. Claude now writes two replies when `booking_confirmed` is true: `reply` (assumes hold success, contains `[PAYMENT_LINK]` placeholder) and `reply_hold_failed` (apologetic, no payment link, offers alternative date). `email_poller` picks the correct reply based on hold outcome. `[PAYMENT_LINK]` is replaced with the real payment URL at send time in the hold success path. `reply_hold_failed` is optional — if absent or empty, falls back to `result["reply"]`. `reply_hold_failed` is NOT added to `_REQUIRED_RESPONSE_FIELDS` — fallback validation unaffected.
**Depends on:** `marina_agent.py` (Brief 029), `email_poller.py` (Brief 029)
**Tests:** 10/10 pass

---

## Brief 031 — calendar.js + email_poller.py + marina_agent.py — Availability pre-check before booking summary
**Status:** Stable
**Files modified:** `bluemarlin/src/calendar.js`, `bluemarlin/src/email_poller.py`, `bluemarlin/src/marina_agent.py`
**What changed:** Availability pre-check before booking summary is sent. `calendar.js` now supports two commands via `input.command` routing: `createHold` (existing, unchanged default) and `checkAvailability` (new — read-only, no hold created, returns `{available, reason?, error?}`). `email_poller` runs `check_calendar_availability()` immediately after `marina_agent` sets `awaiting_booking_confirmation`, before sending the summary to the customer. If slot is unavailable, customer receives `reply_hold_failed` instead of the summary. If available, summary sends as normal. `slot_checked` and `slot_available` flags stored in thread state — guard prevents re-checking on subsequent messages in the same thread. `marina_agent` prompt updated to always write `reply_hold_failed` alongside the summary reply (previously only on `booking_confirmed`) so Python can choose the correct one based on actual availability.
**Depends on:** `marina_agent.py` (Brief 030), `email_poller.py` (Brief 030), `calendar.js` (Brief 026)
**Tests:** 10/10 pass

---

## Brief 032 — gws Migration: calendar.js → gws_calendar.py, sheets_writer.py gws rewrite
**Status:** Stable
**Files modified:** `bluemarlin/src/email_poller.py`, `bluemarlin/src/sheets_writer.py`
**Files created:** `bluemarlin/src/gws_calendar.py`
**Files deleted:** `bluemarlin/src/calendar.js`
**What changed:** Replaced `calendar.js` (Node.js/googleapis) and the googleapis Python client in `sheets_writer.py` with gws CLI subprocess calls. `gws_calendar.py` implements `check_availability(trip_key, date, start_time)` and `create_hold(fields_now)` using `gws calendar events list` and `gws calendar events insert`. `sheets_writer.py` internals rewritten — `_append(tab, row)` now calls `gws sheets spreadsheets values append`; public function signatures (`log_hold_created`, `log_hold_failed`, `log_escalation`, `log_event`) and all row structures unchanged from Brief 028. `email_poller.py` updated to `import gws_calendar` and call its functions directly — `subprocess` removed from email_poller imports. Node.js is no longer in the production path.
**Auth:** `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` env var points to service account JSON key. Set in subprocess env on every gws call in both `gws_calendar.py` and `sheets_writer.py`.
**Manual VPS prerequisites before live use:** `npm install -g @googleworkspace/cli`, set `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` in systemd service environment.
**Depends on:** Brief 031
**Tests:** 10/10 pass

---

## Brief 039 — Capacity-aware booking with soft holds
**Status:** Stable
**Files modified:** `bluemarlin/config/client.json`, `bluemarlin/src/state_registry.py`, `bluemarlin/src/gws_calendar.py`, `bluemarlin/src/email_poller.py`, `bluemarlin/src/marina_agent.py`
**What changed:** Availability tracking moved from Google Calendar (binary) to SQLite capacity tracking. `trip_bookings` table added to `state_registry.py` (schema: trip_key, date, departure_time, guests, status, expires_at). Five new public functions: `expire_stale_holds`, `get_spots_remaining`, `create_soft_hold` (atomic with `BEGIN IMMEDIATE`), `confirm_hold`, `cancel_hold`. `check_availability()` in `gws_calendar.py` rewritten — pure SQLite, no gws CLI call, returns `{available, spots_remaining, capacity}`. `create_hold()` now resolves `calendar_id` from departure-level objects (not the removed `CALENDARS` dict). `CALENDARS` and `DURATIONS_HOURS` dicts removed from `gws_calendar.py` — values now read from `config_loader`. In `client.json`: `capacity` field added to all 5 trips; `calendar_id` moved from trip level to each departure object; Klein Curaçao 08:30 departure gets its own calendar_id; jet_ski expanded to 12 hourly departures (08:00–19:00) with `duration_hours: 1`. In `email_poller.py`: Step 3b creates a soft hold when booking summary fires; date-change detection cancels old soft hold and resets slot_checked; Step 4 confirms/cancels the soft hold based on calendar event outcome. In `marina_agent.py`: `spots_remaining` and `trip_capacity` added to thread context; AVAILABILITY CONTEXT instructions added to prompt.
**Callers must know:** `check_availability()` signature changed: now takes `new_guests: int = 1` as 4th arg; returns `{available, spots_remaining, capacity}` — `reason` and `error` fields removed. `create_hold()` now requires departure-level `calendar_id` in `client.json` — any trip without it will return an error. Capacity values in client.json are booking ceilings (not vessel max_guests). Soft holds expire after 24h if not confirmed. The `CALENDARS` and `DURATIONS_HOURS` module-level dicts no longer exist in `gws_calendar.py`.
**Known open items:** `slot_checked` not reset on date change is now mitigated by the date-change cancellation block in email_poller, but the underlying `slot_checked` flag still persists — low priority.
**Tests:** 8/8 tests + schema checks pass

---

## Brief 040 — Escalation system: semi + full
**Status:** Stable
**Files modified:** `bluemarlin/config/client.json`, `bluemarlin/src/marina_agent.py`, `bluemarlin/src/email_poller.py`, `bluemarlin/src/sheets_writer.py`, `bluemarlin/src/format_sheets.py`
**What changed:** Two-mode escalation added. (1) Semi-escalation: marina_agent returns `semi_escalation: true` (top-level field, not in flags) + `relay_question: str`. email_poller cancels any pending soft hold, sets `awaiting_relay: true` on thread, sends holding reply to customer, sends relay alert email to `demo_support_email` with `Reply-To: EMAIL_ADDR`. Incoming relay reply detected by `from_email == demo_support_email && "[RELAY]" in subject`; customer thread found via booking_ref; marina_agent called in relay mode (prompt section injected when `awaiting_relay` in thread_flags); reformulated reply sent to customer. (2) Full escalation: `requires_human: true` path now also sets `fully_escalated: true`, sends full alert (chat log + fields + internal note) to `demo_support_email`, and updates `log_escalation` to include `messages_json` as 7th column. (3) Messages log: `th["messages"]` list accumulates all inbound/outbound messages. (4) Fully escalated guard: before Step 1, if `fully_escalated`, calls marina_agent for holding reply then skips all booking flow. (5) client.json: `support_email` and `demo_support_email` added to business section. (6) smtp_send: `reply_to=None` parameter added.
**Callers must know:** `marina_agent.process_message()` may now return `semi_escalation` (bool) and `relay_question` (str) as optional top-level fields — not in `_REQUIRED_RESPONSE_FIELDS`. `smtp_send()` now accepts `reply_to=None` keyword arg. `sheets_writer.log_escalation()` now writes 7 columns (was 6) — the 7th is `messages_json`. `th["messages"]` is now accumulated in thread state. Relay emails from `demo_support_email` with `[RELAY]` in subject are handled before normal processing and `continue`d without saving the relay email's own thread.
**Known open items:** T2 relay test content assertion checks only that one of four keywords appears in the reply — "board" trivially passes. Format_sheets.py broken import (pre-existing, since Brief 032) still not fixed.
**Tests:** 5/5 tests pass

---

## Brief 046 — Hybrid refactor: Python state machine + simplified Claude prompt
**Status:** Stable
**Files modified:** `bluemarlin/src/marina_agent.py`, `bluemarlin/src/email_poller.py`
**What changed:** Moved all deterministic booking validation from Claude's prompt to Python. (1) marina_agent.py: replaced 62-line BOOKING CONFIRMATION BEHAVIOUR with 12-line BOOKING BEHAVIOUR section; removed AVAILABILITY CONTEXT (12 lines); removed spots_remaining/trip_capacity from THREAD CONTEXT; added `action_context: str = ""` parameter to `_build_prompt()` and `process_message()`; simplified reply/reply_hold_failed/flags descriptions in JSON spec; added `needs_child_ages` flag. (2) email_poller.py: added 5 helper functions (`_day_matches`, `_suggest_dates`, `_build_booking_summary`, `_build_action_context`, `_post_validate`); field merge changed to always-overwrite; Python now manages `awaiting_booking_confirmation` flag (strips Claude's SET attempts, allows Claude's CLEAR); post-validation (Step 3a) runs after field/flag merge, may override Claude's reply with data-driven messages; Step 3b trigger changed from Claude-set to Python-set flag; slot-unavailable/race branches now reset `awaiting_booking_confirmation` and `slot_checked`, override reply; Step 5 simplified to use pre-set `reply_text`.
**Callers must know:** `process_message()` now accepts optional `action_context: str = ""` parameter — backward compatible. Python controls `awaiting_booking_confirmation` flag (set via `_post_validate`, cleared by Claude). Python generates booking summaries, day-of-week errors, departure options, and slot-unavailable messages from client.json data. Claude still handles field extraction, confirmation detection, child pricing detection (`needs_child_ages` flag), escalation, and conversational replies.
**Known open items:** Child pricing in `_build_booking_summary` uses adult rate for all guests (only affects klein_curacao). Follow-up brief needed for tiered pricing with `children_count`/`children_ages` fields.
**Tests:** 28/28 tests pass

---

## Brief 047 — Treat reschedule intent as booking-active in Python validation
**Status:** Stable
**Files modified:** `bluemarlin/src/email_poller.py`
**What changed:** Added `_BOOKING_INTENTS = {"booking", "reschedule"}` constant. Widened three intent gates (`_post_validate`, Step 3a, Step 5) from `"booking" in intents` to `any(i in _BOOKING_INTENTS for i in intents)`. When Claude classifies a mid-thread date change as `reschedule`, Python's booking validation (day-of-week, departure time, summary generation) and hold-creation flow now trigger correctly.
**Callers must know:** `_BOOKING_INTENTS` is the single source of truth for which intents activate the booking validation path. To add future booking-related intents, add to this set.
**Tests:** 10/10 tests pass (+ 28/28 Brief 046 regression)

---

## Brief 048 — Human speech optimization: multi-topic fix + prompt hardening
**Status:** Stable
**Files modified:** `bluemarlin/src/email_poller.py`, `bluemarlin/src/marina_agent.py`
**What changed:** (1) `_post_validate` override messages no longer include signatures. Step 3a now appends overrides to Claude's reply when non-booking intents are present (preserving answers to side questions), or replaces with signature when booking-only. (2) Field merge logic now handles intentional clears: `date: ""` from Claude deletes the existing date field instead of being silently skipped. (3) Prompt hardened: guests field requires explicitly stated number ("We" doesn't count); date-clearing instruction for rejected dates; multi-topic guidance tells Claude to answer non-booking questions in its reply.
**Callers must know:** `_post_validate` and `_build_booking_summary` return messages WITHOUT signatures. Step 3a handles signature addition. Field merge now treats `""` as intentional clear for existing fields.
**Tests:** 19/19 tests pass (+ 28/28 Brief 046, 10/10 Brief 047)

---

## Brief 049 — Fix format_sheets.py + apply formatting to new dashboard
**Status:** Stable
**Files modified:** `bluemarlin/src/format_sheets.py`
**What changed:** Fixed broken imports — `_get_service()` and `SPREADSHEET_ID` were removed from `sheets_writer.py` in Brief 032 but format_sheets still imported them. Added local service initialization using `google-api-python-client` directly. Updated `BOOKINGS_HEADERS` from 13 columns to 15 to match actual data written by `sheets_writer.log_hold_created()` (added Booking Ref, Trip Key, Departure Time, Total Price, Payment Status). Spreadsheet ID resolved via `config_loader.get_business()` — points to new sheet (`1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I`), not the banned old sheet.
**Depends on:** `config_loader.py` (Brief 022), `config/bluemarlin-calendar-key.json`
**Tests:** 20/20 pass

---

## Brief 050 — Manifest foundation: tables + calendar functions
**Status:** Stable
**Files modified:** `bluemarlin/src/state_registry.py`, `bluemarlin/src/gws_calendar.py`
**What changed:** Added `manifest_events` SQLite table (PK: trip_key, date, departure_time) to track per-slot calendar events. Added `customer_name` and `customer_email` columns to `trip_bookings` (ALTER TABLE migration). Extended `create_soft_hold()` with optional `customer_name`/`customer_email` kwargs. Five new functions in state_registry: `set_booking_ref()`, `get_manifest_event()`, `save_manifest_event()`, `delete_manifest_event()`, `get_slot_passengers()`. Four new functions in gws_calendar: `_build_manifest_body()`, `create_or_update_manifest()`, `update_manifest()`, `remove_from_manifest()`. Old `create_hold()` untouched.
**Callers must know:** New manifest functions are not yet wired into the booking flow — that happens in Brief 051. `create_soft_hold()` is backward compatible (new kwargs have defaults). `create_or_update_manifest()` reads passenger info from `state_registry.get_slot_passengers()` — caller must call `set_booking_ref()` before invoking if the ref should appear in the manifest.
**Depends on:** `config_loader.py` (Brief 022), `state_registry.py` (Brief 039)
**Tests:** 31/31 pass

---

## Brief 052 — Sheets: Manifests summary tab
**Status:** Stable
**Files modified:** `bluemarlin/src/sheets_writer.py`, `bluemarlin/src/format_sheets.py`, `bluemarlin/src/email_poller.py`
**What changed:** New `log_manifest_update()` function in sheets_writer.py appends an 11-column manifest summary row to the Manifests tab after each successful booking. format_sheets.py gains `MANIFESTS_HEADERS`, `MANIFESTS_WIDTHS`, and a Manifests entry in the `TABS` list. email_poller.py Step 5 success path calls `state_registry.get_slot_passengers()` to compute aggregated counts, then calls `sheets_writer.log_manifest_update()`.
**Callers must know:** Revenue is an approximation (`total_guests * price_adult_usd`). The "Manifests" tab must be created manually in Google Sheets before the first booking is logged.
**Depends on:** Brief 051 (manifest integration)
**Tests:** 28/28 pass

---

## Brief 051 — Integration: rewire booking flow + payment fix
**Status:** Stable
**Files modified:** `bluemarlin/src/email_poller.py`, `bluemarlin/src/payment_stub.py`
**What changed:** Booking flow now uses manifest-style calendar events. Step 3b passes `customer_name`/`customer_email` to `create_soft_hold()` and stores slot info (`hold_trip_key`/`hold_date`/`hold_departure_time`) in thread flags. Step 5 generates `booking_ref` before manifest creation, calls `create_or_update_manifest()` instead of `create_hold()`, confirms the hold only after manifest succeeds. All 3 cancel sites call `remove_from_manifest()` and pop slot flags. `payment_stub.py` switched from `event_id` to `booking_ref` as the payment key to prevent collisions when multiple customers share a manifest event.
**Callers must know:** `payment_stub.generate_payment_link(booking_ref, amount)` — first param is now `booking_ref`, not `event_id`. `mark_paid(booking_ref)` same. Old `create_hold()` still exists in gws_calendar.py but is no longer called by email_poller.
**Depends on:** Brief 050 (manifest foundation)
**Tests:** 24/24 pass

---

## Still on OpenClaw (not yet migrated)
- None — OpenClaw fully removed from all active code paths.

---

## Decision Log (ARCHIVED — moved to marina_lessons.md)
Entries below are historical (Briefs 033-044). All future decision + lesson entries go in `marina_lessons.md`.
Format: full story for problem briefs, short summary for smooth ones.
One entry per brief. Old format:
Brief 0XX — [title]
Decision: [what was decided and why]
Outcome: [what happened]

Brief 033 — Thread key via Message-ID/In-Reply-To
Decision: Replace subject-based thread keying with Message-ID index lookup. Store message_id_index in state file. Fallback to sender+subject for first messages.
Outcome: complete — 7/7 tests pass

Brief 034 — Fill [VERIFY] placeholders in client.json
Decision: Replace all 8 [VERIFY] items with plausible demo values. No source code changes. Vessel assignments: snorkeling_3in1=TopCat, west_coast_beach=Red Dragon, sunset_cruise=Kailani. Cancellation: 48h full refund, 24h no refund.
Outcome: complete — 9/9 tests pass

Brief 035 — Marina prompt polish: language adaptation + trip key mapping
Decision: Add LANGUAGE detection instruction and trip_key mapping table to marina_agent.py prompt. Remove 3 resolved items from CLAUDE.md Known Open Issues. Formally accept fallback reply exception in CLAUDE.md. No logic changes.
Outcome: complete — 9/9 tests pass

Brief 036 — Marina prompt bug fixes: language body-only, day-of-week validation, reply_hold_failed scope
Decision: Three prompt fixes following stress test (14 scenarios). Fix 1: language from body text only. Fix 2: day-of-week check before booking summary. Fix 3: reply_hold_failed only on booking confirmation paths.
Outcome: complete — 7/7 tests pass

Brief 037 — Extended stress test: 8 new edge case scenarios
Decision: Add S15–S22 to test_marina_stress.py to test arithmetic guest counts, implicit confirmation, missing trip name, relative dates, and child pricing. Test-only — no prompt changes. Failures documented for 038.
Outcome: complete — 6/6 tests pass

Brief 038 — Marina prompt: child age pricing + day-of-week on mid-confirmation date change
Decision: Two prompt fixes from Brief 037 stress test. Fix 1: SECOND pre-summary check asks child ages before pricing. Fix 2: mid-confirmation date-change handler re-validates day of week before resetting.
Outcome: complete — 7/7 tests pass

Brief 039 — Capacity-aware booking with soft holds
Decision: Replace binary gws CLI availability check with SQLite capacity tracking. `trip_bookings` table added to state_registry. `check_availability()` is now pure SQLite — no gws call. Soft hold (24h TTL) created at booking summary time; confirmed on calendar event success; cancelled on failure or customer date change. `calendar_id` moved from trip level to departure level in client.json; `CALENDARS` and `DURATIONS_HOURS` dicts removed from gws_calendar.py. Klein Curaçao gains independent vessel-level capacity per departure. Jet ski expanded to 12 explicit hourly departures (08:00–19:00).
Outcome: complete — 8/8 tests + schema checks pass

Brief 045 — Slot-unavailable alternative = change, not confirmation + [PAYMENT_LINK] safety net
Decision: Two fixes. (1) Prompt addition in marina_agent.py: new bullet in the awaiting_booking_confirmation handler — when a slot was unavailable and Marina offered alternatives, the customer picking one is a CHANGE, not a confirmation. Must update fields, reset awaiting_booking_confirmation, re-run FIRST/SECOND/THIRD checks, send new summary. Must NOT set booking_confirmed. (2) Safety net in email_poller.py: strip literal `[PAYMENT_LINK]` from reply_text before booking smtp_send — ensures the placeholder never reaches a customer.
Outcome: complete — 6/6 tests pass

Brief 044 — Departure time before booking summary for multi-departure trips
Decision: Prompt-only fix in marina_agent.py. Replaced "departure_time is NOT a required field" instruction with a THIRD pre-summary check: for trips with multiple departures (klein_curacao, jet_ski), ask for departure_time BEFORE sending the booking summary and do NOT set awaiting_booking_confirmation until resolved. For single-departure trips (snorkeling_3in1, west_coast_beach, sunset_cruise), auto-select — no question needed. Also updated mid-confirmation re-run instruction to include THIRD check.
Outcome: complete — 8/8 tests pass

Brief 043 — Fix relay detection + poisoned relay bug
Decision: Two fixes to email_poller.py. (1) Subject decoding: added `_decode_subj()` helper using `email.header.decode_header` — decodes RFC 2047 encoded subjects before relay/escalation detection. Gmail was encoding reply subjects as `=?utf-8?q?...?=`, causing `"[RELAY-" in subj` to fail silently. (2) Poisoned relay: both marina_agent call sites (fully_escalated guard + Step 1) now strip relay flags (`awaiting_relay`, `relay_token`, `relay_question`, `relay_customer_email`, `relay_reply_subject`) from a copy of thread flags before calling marina_agent. Only the relay handler passes full flags. This prevents RELAY MODE from firing when a customer sends another message on an `awaiting_relay` thread.
Outcome: complete — 6/6 tests pass

Brief 042 — Operator email hardening: escalation guard + relay token auth
Decision: Two fixes to email_poller.py only. (1) Escalation reply guard: inbound from demo_support_email with [ESCALATION] in subject is dropped immediately — escalation is one-way, no reply loop. (2) Relay token auth: replaced [RELAY] magic-string subject detection with [RELAY-<12-char-hex-token>] per relay. Token generated at relay alert send time (uuid.uuid4().hex[:12]), stored in th["flags"]["relay_token"], embedded in alert subject, extracted on reply via regex, matched against stored token for exact thread lookup. Eliminates booking_ref fallback, handles multiple concurrent relays, unforgeable without knowing the UUID.
Outcome: complete — 5/5 tests pass

Brief 041 — Semi-escalation prompt fix: prohibit contact-info fallback
Decision: Prompt-only fix in marina_agent.py. Added CONTACT INFO RULE block between ESCALATION BEHAVIOUR and SEMI-ESCALATION — explicitly restricts info@bluefinncharters.com and phone number to complaints/refunds/cancellations only, bans using them as a fallback for factual questions. Replaced SEMI-ESCALATION body with stronger version: "you MUST set semi_escalation: true", four named trigger categories (equipment specs, dietary/allergy, accessibility, yes/no operational), prohibition on contact info, prohibition on partial answers.
Outcome: complete — 4/4 tests pass

Brief 052 — Sheets: Manifests summary tab
Decision: Add Manifests tab to Google Sheets dashboard. New `log_manifest_update()` in sheets_writer.py appends an 11-column summary row (trip, date, departure, guests, capacity, confirmed/pending counts, revenue, calendar link, booking ref) after each successful manifest creation. format_sheets.py gains MANIFESTS_HEADERS/WIDTHS + TABS entry. Revenue is an approximation (total_guests * price_adult_usd — child pricing not tracked per-booking). Manifests tab must be created manually in Google Sheets before first use.
Outcome: complete — 28/28 tests pass

Brief 051 — Integration: rewire booking flow + payment fix
Decision: Rewire email_poller.py Step 5 to use create_or_update_manifest instead of create_hold. Generate booking_ref before manifest creation so it appears in the manifest description. Switch payment_stub from event_id to booking_ref to prevent collisions. Add remove_from_manifest at all 3 cancel sites. Brief reviewer caught 3 bugs in initial Step 5 failure path: hold_id not popped, slot_checked/slot_available not reset, confirm_hold before manifest success — all fixed before execution.
Outcome: complete — 24/24 tests pass

Brief 050 — Manifest foundation: tables + calendar functions
Decision: Replace per-customer calendar events with manifest-style events (one per departure slot). This brief adds the foundation: manifest_events SQLite table, customer_name/customer_email in trip_bookings, and four new gws_calendar functions (create_or_update_manifest, update_manifest, remove_from_manifest, _build_manifest_body). Purely additive — no existing behavior changed. Wiring into booking flow deferred to Brief 051.
Outcome: complete — 31/31 tests pass

Brief 049 — Fix format_sheets.py + apply formatting to new dashboard
Decision: format_sheets.py was broken since Brief 032 removed _get_service() and SPREADSHEET_ID from sheets_writer.py. Added local service init using google-api-python-client. Updated Bookings headers from 13 to 15 columns to match sheets_writer.log_hold_created(). Points to new sheet via config_loader.
Outcome: complete — 20/20 tests pass

Brief 048 — Human speech optimization: multi-topic fix + prompt hardening
Decision: Three fixes from live testing. (1) Append _post_validate overrides to Claude's reply when non-booking intents present — preserves answers to side questions. (2) Field merge handles empty-string clears so date rejection works. (3) Prompt hardened against guest hallucination and vague date changes.
Outcome: complete — 19/19 tests pass

Brief 047 — Treat reschedule intent as booking-active
Decision: Widen intent gates in _post_validate, Step 3a, and Step 5 from "booking" to _BOOKING_INTENTS (booking + reschedule). Live Test 5 showed Claude classifying a mid-thread date change as reschedule, bypassing Python's validation entirely.
Outcome: complete — 10/10 tests pass

Brief 046 — Hybrid refactor: Python state machine + simplified Claude prompt
Decision: Move all deterministic booking validation (day-of-week, departure time gating, summary generation, awaiting_booking_confirmation flag management) from the Claude prompt to Python. Claude's 62-line BOOKING CONFIRMATION BEHAVIOUR block replaced with 12-line BOOKING BEHAVIOUR section. Five new helper functions in email_poller.py. Python builds data-driven booking summaries, departure options, day-of-week errors, and slot-unavailable messages from client.json. Claude still handles field extraction, confirmation detection, child pricing detection, and conversational replies. action_context parameter added to process_message for Python-to-Claude state instructions.
Outcome: complete — 28/28 tests pass

Brief 053 — Stale thread reset on new conversation
Decision: Thread keys based on sender+subject had no expiration. A new email with the same subject as a weeks-old thread inherited stale fields (customer_name, phone, departure_time from a different booking), causing Claude to produce nonsensical replies. Fix: `_maybe_reset_stale_thread()` detects new emails (no In-Reply-To/References headers) hitting threads older than 24h and resets them to fresh state. Replies to active conversations are unaffected. `last_activity` timestamp added to thread persist for reliable age tracking.
Outcome: complete — 9/9 tests pass

Brief 055 — Multi-trip booking in one thread
Decision: After a completed booking (hold_created=True), the thread was stuck — no way to start a fresh booking. Fix: intent-gated reset that fires AFTER the marina_agent call when booking intent is detected alongside hold_created. Archives the completed booking into `th["completed_bookings"]`, resets fields (preserving customer_name and phone) and booking flags, then merges Claude's new fields onto the clean slate. Non-booking follow-ups ("Thanks!", FAQ questions) pass through unchanged. Max 3 bookings per thread via `max_bookings_per_thread` in client.json.
Outcome: complete — 10/10 tests pass

Brief 054 — Booking ref in confirmation + cross-thread memory
Decision: booking_ref (BF-YYYY-XXXXX) was generated but never shown to the customer. Added `bookings` SQLite table for cross-thread memory. `save_booking()` stores full booking context after hold confirmation. `_detect_booking_ref()` extracts refs from inbound message bodies (structured pattern match, not language classification). Returning customer context injected into marina_agent prompt before the Claude call. Static BOOKING REFERENCE instruction added to prompt so Marina includes the ref in confirmation replies.
Outcome: complete — 12/12 tests pass

Brief 040 — Escalation system: semi + full
Decision: Two-mode escalation. Semi-escalation: marina_agent returns `semi_escalation: true` + `relay_question`; email_poller sends holding reply to customer + relay alert (Reply-To: Marina's inbox) to demo_support_email; relay reply from human detected via `[RELAY]` in subject + sender match, marina_agent reformulates in relay mode. Full escalation: existing `requires_human: true` path extended to set `fully_escalated: true` on thread + send chat log alert to demo_support_email + update log_escalation to include messages_json. Messages log (`th["messages"]`) accumulates all inbound/outbound for both paths. Fully escalated threads still call marina_agent (one Claude call per Rule 1) but skip all booking flow. Semi-escalation cancels any soft hold created during Step 3b to prevent capacity leak. `reply_to=EMAIL_ADDR` (not a hardcoded string) on relay alerts.
Outcome: complete — 5/5 tests pass

Brief 056 — SSH key auth: Claude Code → VPS
Decision: INFRA.md incorrectly stated SSH from Claude Code was blocked. Never tested. Root cause was a malformed authorized_keys entry on VPS. Fixed with ssh-copy-id from Mac. Key auth now works — Claude Code Bash tool can SSH and deploy autonomously.
Outcome: complete — verified in session, briefs 053–055 deployed via SSH

Brief 057 — Anti Email-Spam: SPF/DKIM/DMARC + Message-ID Header
Decision: Marina's outbound emails landing in spam. Added Message-ID header to SMTP sends (email_poller.py). Documented SPF, DKIM, and DMARC DNS records in INFRA.md for the domain.
Outcome: complete — emails no longer flagged as spam

Brief 058 — Fix: Booking Ref Missing from Confirmation Reply
Decision: Brief 054 instructed Marina to include booking_ref from thread_flags, but booking_ref is generated after the marina_agent call — impossible to satisfy. Fixed using the existing [PAYMENT_LINK] placeholder pattern: Marina writes [BOOKING_REF] in her reply, Python replaces it after successful hold creation at line 955. Also strips the placeholder on the non-success path at line 1020.
Outcome: complete — 6/6 new tests pass, 12/12 Brief 054 tests still pass

Brief 059 — Marina Tone Polish
Decision: Prompt-only change. Added comprehensive WRITING STYLE section to marina_agent.py prompt: write as a real person, mirror sender tone, avoid stock phrases (10 banned), avoid AI habits (em dashes, decorative bold, semicolons), emoji rule (confirmations only), self-check before output. Updated marina_persona in client.json to reflect hospitality focus and tone mirroring.
Outcome: complete — 6/6 tests pass

Brief 060 — Marina Tone v2: Python Templates + Claude Prompting
Decision: Python-side template improvements for booking summary and validation reply strings. Claude prompt hardened with tone mirroring and stock phrase bans. Improved natural language quality of system-generated replies.
Outcome: complete — 12/12 tests pass

Brief 061 — Escalation Logic Bugs: NO-REF, Empty Name, Silent Ref Drop
Decision: Three escalation path fixes. (1) Booking ref fallthrough — `_resolve_booking_ref()` now checks completed_bookings list. (2) Empty customer name — defaults to "Unknown" instead of empty string. (3) Silent ref drop — booking ref preserved through escalation flow.
Outcome: complete — 10/10 tests pass

Brief 062 — Live Test Harness: Automated E2E Testing
Decision: Created standalone `tests/live_test_harness.py` — IMAP APPEND injection, thread state polling, pattern-based assertions. Zero src/ imports (copies oauth_token, imap_connect, normalize_subject directly). 50 scenarios total: 6 core, 3 Brief 064, 41 stress. CLI flags: --dry-run, --064, --stress, --all, --scenario, --cleanup.
Outcome: complete — 50 scenarios, 126/140 assertions pass (90%), zero functional bugs

Brief 064 — Past Date Check, Escalation Email Info, Noreply Filter, Email-Based Returning Customer
Decision: Four hardening fixes from live stress testing. (1) Past date check in `_post_validate()` after day-of-week — rejects dates in the past using Curaçao timezone. (2) System email filter — `_SYSTEM_EMAIL_PREFIXES` tuple skips noreply@, mailer-daemon@, etc. before processing. (3) Escalation email format — subject now includes customer email, body starts with `=== CUSTOMER ===` section (email, name, phone). (4) Email-based returning customer lookup — `get_bookings_by_email()` in state_registry.py, email normalization in `save_booking()`, cross-thread memory via `_past_customer_bookings` flag injected into marina_agent prompt.
Outcome: complete — 14/14 tests pass

Brief 065 — Production Hardening: Rate Limiting, Thread Cleanup, Monitoring, OAuth Auto-Refresh
Decision: Four production-readiness fixes. (1) Per-sender rate limiting — 20 emails/sender/hour tracked in thread state JSON, silent skip on limit hit. (2) Thread state cleanup — `_cleanup_stale_data()` archives threads >30d to JSONL, prunes processed_hashes to 5000, cleans expired sender_rates. (3) Monitoring — token usage logged via bm_logger after each Claude call, heartbeat file written after each poll cycle, error alerting via smtp_send after 3 consecutive failures. (4) OAuth auto-refresh — saves rotated refresh_token back to disk, raises RuntimeError on missing access_token. Multi-operator routing deferred.
Outcome: complete — 12/12 tests pass, regression 28/28 + 19/19 + 14/14

Brief 067 — WhatsApp Webhook Server + VPS Infrastructure
Decision: Stand up full HTTPS webhook infrastructure for Meta WhatsApp Cloud API. FastAPI webhook server (`agents/social/webhook_server.py`) behind nginx reverse proxy with Let's Encrypt SSL on `api.wetakeyourjob.com`. Separate systemd service (`bluemarlin-social`) on port 8001. GET handler for Meta verification (token match → return challenge), POST handler logs payloads via bm_logger. No agent logic yet — minimum viable webhook for Meta verification. VPS infra: nginx, certbot, firewall ports 80/443 opened, env vars for Meta/WhatsApp credentials.
Outcome: complete — 7/7 local tests pass, 3/3 live curl verification pass

Brief 068 — WhatsApp Message Pipeline: Parse, Dedup, Reply
Decision: Close the inbound-to-outbound loop. `whatsapp_client.py` parses Meta payloads into normalized message objects and sends replies via WhatsApp Cloud API (urllib.request, stdlib). `social_agent.py` stub returns hardcoded test reply (Rule 3 accepted temporary exception — replaced by Claude Q&A in next brief). `webhook_server.py` POST handler uses FastAPI BackgroundTasks for non-blocking processing. SQLite dedup via `whatsapp_processed` table in state_registry. Status updates (sent/delivered) correctly filtered. Permanent System User token verified working.
Outcome: complete — 10/10 local tests pass, 7/7 regression pass, live pipeline confirmed (reply sent + delivered)

Brief 069 — WhatsApp Channel Support: marina_agent + State Foundation
Decision: Replace WhatsApp stub with marina_agent.py (same Claude brain as email). Added `channel="whatsapp"` parameter to `_build_system_prompt`, `_build_user_prompt`, `_build_prompt`, `process_message` — WhatsApp gets short/casual writing style, no signature, conversation history section. Added `messages` parameter for multi-turn context. WhatsApp fallback = empty string (silence > canned response). state_registry.py gets `whatsapp_threads` table (conversation history, 24h window, 10-message limit) and `whatsapp_booking_state` table (fields/flags/completed_bookings per phone). social_agent.py rewritten as thin wrapper: fetches state + history, calls marina_agent, merges + persists fields/flags, strips booking placeholders. webhook_server.py stores user + assistant messages after successful reply. All defaults preserve email backward compatibility — email_poller.py untouched.
Outcome: complete — 17/17 tests pass, 10/10 regression (068), 7/7 regression (067)

Brief 070 — WhatsApp Booking Orchestrator
Decision: Add full booking flow to social_agent.py — duplicates booking helpers from email_poller.py (Option B: WhatsApp gets own orchestrator, email untouched). Helpers: `_day_matches`, `_suggest_dates`, `_build_booking_summary`, `_build_action_context`, `_post_validate`. Full 10-step orchestrator in `handle_incoming_whatsapp_message`: action_context → marina_agent call → field/flag merge → change detection → post-validation (day-of-week, past date, multi-departure, summary) → availability + soft hold → booking confirmation (manifest, booking_ref, payment link, Sheets) → placeholder replacement → persist. ~5 new Rule 3 instances (accepted debt, same pattern as email_poller.py). Escalation/relay/multi-trip deferred to Briefs 071-072.
Outcome: complete — 16/16 tests pass, 17/17 regression (069), 10/10 regression (068), 7/7 regression (067)

Brief 071 — WhatsApp Escalation: Semi + Full + Fully-Escalated Guard
Decision: Add three escalation paths to social_agent.py — same patterns as email_poller.py adapted for WhatsApp. Fully-escalated guard: early return before booking flow, calls marina_agent with filtered flags (relay flags removed), returns holding reply. Semi-escalation: cancels any soft hold, sets relay flags (awaiting_relay, relay_token, relay_question), overrides reply with Claude's holding reply, logs to Sheets + bm_logger. Full escalation: cancels any soft hold, sets fully_escalated flag, logs to Sheets + bm_logger. Both escalation handlers clear awaiting_booking_confirmation and reset slot flags. Relay flag filtering added before all marina_agent calls to prevent RELAY MODE prompt injection. No cross-channel relay bridge (operator reply → WhatsApp delivery) — relay state stored in whatsapp_booking_state flags for future brief. Also fixed pre-existing conftest.py test isolation bug (env vars not set before whatsapp_client import).
Outcome: complete — 8/8 tests pass, 16/16 regression (070), 17/17 regression (069), 10/10 regression (068), 7/7 regression (067)

Brief 072 — WhatsApp: Multi-Trip Reset, Returning Customer, Anti-Loop
Decision: Port three production-critical features from email_poller.py to social_agent.py. (1) Multi-trip reset: when hold_created + new booking intent, archive current booking to completed_bookings, reset fields (preserve customer_name/phone), clear booking flags. Uses existing `_BOOKING_FLAGS_TO_RESET` and `_PERSISTENT_FIELDS` constants. (2) Returning customer: booking ref detection via `BF-\d{4}-\d{5}` regex in message text (pre-populates fields from past booking), phone-based lookup via `get_bookings_by_email(phone)` (injects summary into agent_flags). Dual-set to both `flags` and `agent_flags` since agent_flags is copied before detection runs. Completed bookings summary + max_bookings_reached injected into agent_flags for marina_agent prompt. (3) Anti-loop: 15 replies/hr per phone, reply_times stored in flags JSON, filtered from agent_flags. Returns empty string when limit hit (webhook_server skips empty replies). Anti-loop fires before fully-escalated guard — reply_times recording added to fully-escalated early return path to prevent bypass.
Outcome: complete — 11/11 tests pass, 8/8 regression (071), 16/16 regression (070), 17/17 regression (069), 10/10 regression (068), 7/7 regression (067)

Brief 073 — WhatsApp Hardening: Stale Reset + Cleanup + Edge Case Tests
Decision: Three production gaps closed. (1) Stale conversation reset: `_maybe_reset_stale_conversation()` detects >24h inactivity gap via `last_activity` field (now returned by `wa_get_booking_state`), archives booking if hold_created, resets fields (preserves customer identity via `_PERSISTENT_FIELDS`), clears all booking + escalation + rate-limit flags. Mirrors email_poller's Brief 053 pattern. (2) Stale data cleanup: `wa_cleanup_stale_data()` in state_registry deletes whatsapp_threads >30d and whatsapp_processed >7d. Called hourly via `_maybe_run_cleanup()` in webhook_server (module-level timestamp guard, same pattern as email_poller). (3) Four previously-untested edge cases now covered: change detection (cancel hold on mid-confirmation detail change), manifest creation failure (cancel hold, use reply_hold_failed, log to Sheets), hold race condition (create_soft_hold returns None after available check), empty reply early exit (return "" immediately, DB state unchanged).
Outcome: complete — 10/10 tests pass, 11/11 regression (072), 8/8 regression (071), 16/16 regression (070), 17/17 regression (069, 1 assertion updated), 10/10 regression (068), 7/7 regression (067)

Brief 074 — WhatsApp: Semi-Escalation Promotion + Rate Limit Bump
Decision: Two fixes from first live WhatsApp conversation analysis. (1) Semi-escalation promoted to full escalation: `semi_escalation=True` now sets `fully_escalated=True` instead of orphaned relay flags (`awaiting_relay`, `relay_token`, `relay_question`). Without a relay-back bridge (email uses `[RELAY-xxx]` subject matching, WhatsApp has no equivalent), semi-escalation created flags that would never be resolved and promised relay answers that could never be delivered. Sheets intent changed to `"semi_to_full_escalation"`, internal_note preserves relay question with "(no relay bridge)" prefix for operator context. Hold cancellation, Sheets logging, and bm_logger logging preserved. `import uuid` removed (only used for relay_token). (2) Rate limit bumped from 15 to 25 replies/hour. First live conversation (Calvin Adamus) hit the limit after 10 booking exchanges + 5 post-booking chat messages in 16 minutes. WhatsApp's real-time pace requires higher limit than email's 10/thread/hr. 25 covers a full booking (10-15) + post-booking (5-8) + buffer.
Outcome: complete — 6/6 tests pass, 10/10 regression (073), 11/11 regression (072, 3 updated), 8/8 regression (071, 3 updated), 16/16 regression (070), 17/17 regression (069), 10/10 regression (068), 7/7 regression (067)

Brief 075 — WhatsApp Live Test Harness
Decision: Created `tests/social/live_test_whatsapp.py` — 6 conversation scenarios with real Claude API calls (not mocked). Tests the full WhatsApp pipeline: field extraction, booking flow (multi-turn), day-of-week rejection, escalation, Spanish language, and prompt injection security. Mocks only Google Sheets/Calendar writes and outbound WhatsApp send. Runs on VPS where `ANTHROPIC_API_KEY` is available. Modeled after the email live test harness (Brief 062) but adapted for WhatsApp's direct function call pattern instead of IMAP injection.
Outcome: complete — 26/26 checks pass on VPS

Brief 076 — WhatsApp Message Debouncing + Rate Limit 50
Decision: Two changes to address rapid-fire message problem observed in Calvin Adamus's live conversation (6 messages in 3 seconds → 6 parallel Claude calls → 6 contradictory replies). (1) Message debouncing in webhook_server.py: per-phone buffer with 2-second debounce window (resets on each new message) and 5-second hard cap. Messages concatenated with `\n` separator, processed as single Claude call on flush. Dedup happens at buffer-add time, not flush time. Non-text messages filtered before buffering. (2) Rate limit bumped from 25 to 50 replies/hour — rapid-fire conversations easily burn through 25 in 15 minutes. Also fixed regression in test_068 and test_069 integration tests (FastAPI TestClient's synchronous BackgroundTasks now only buffers messages, timer doesn't fire synchronously — fixed by manual flush in tests).
Outcome: complete — 7/7 new tests pass, 92/92 full social regression pass

Brief 077 — WhatsApp Operator Notification + Relay Bridge
Decision: Bridge the gap between WhatsApp social agent and email poller for escalation/relay delivery. (1) Shared SQLite queue: `pending_notifications` table with CRUD functions in state_registry.py — social agent writes, email poller reads and sends via existing SMTP. Chosen over giving social agent direct SMTP access (avoids second OAuth consumer) or HTTP API (over-engineered for volume). (2) Semi-escalation reverted from promote-to-full back to proper relay: sets `awaiting_relay`, `relay_token` (12-char hex), `relay_question` — operator receives `[RELAY-{token}]` email, replies, email_poller detects token, reformulates via marina_agent, sends back to WhatsApp via `wa_send_text_message`. (3) Full escalation now queues `[ESCALATION]` email with structured body (customer info, chat log, booking fields, internal note). (4) Email poller extended: processes pending notifications after IMAP logout, and WhatsApp relay detection added to relay handler (checks `get_relay_by_token` when email thread not found). Also updated test_071 semi-escalation assertions (3 tests) that the brief missed.
Outcome: complete — 8/8 new tests pass, 92/92 full social regression pass (100/100 total)

Brief 078 — WhatsApp Live Stress Tests: Weird E2E Scenarios
Decision: 13 new live test scenarios with real Claude API calls to prove WhatsApp production readiness beyond happy-path testing. Covers: mid-booking guest change (3 turns), Klein departure disambiguation (2 turns), multi-trip sequential booking (4 turns), semi-escalation relay, booking + side question combo, stream-of-consciousness ramble, emoji-heavy slang, Dutch language, returning customer by ref, rapid topic switch (3 turns), social engineering attempt, code injection safety, and exact price accuracy. Added `check_availability` to mock list for deterministic tests. Discovered: Papiamentu (local language) returns empty reply — not in supported languages list, potential future fix via client.json. Extreme slang can intermittently return empty — toned down to reliable level while keeping informal style.
Outcome: complete — 72/72 checks pass on VPS, combined with Brief 075: 98 live checks across 19 scenarios

Brief 092 — Content Agent Core + Draft Store
Decision: Phase 1 Milestone B begins. Created content_agent.py in agents/social/ — single Claude call generates draft social media posts from client.json data + calendar availability. System prompt reads client-specific values (brand_voice, content_boundaries, cta_default, emoji_style, hashtag_style) from new social_content section in client.json. Structural rules (priority stack, content classification A/B/C/D, platform rules, demand-state logic) stay in source. Draft store: content_drafts table in state_registry.py with CRUD functions (save, get, update_status). Availability summary function queries trip_bookings for next N days, parses days_available from config, avoids cross-agent import from gws_calendar. Response defaults pattern from marina_agent — missing fields get defaults instead of rejecting. Content class validation (A/B/C/D only). Follows same architecture as marina_agent: one Claude call, structured JSON, resilient parsing.
Outcome: complete — 14/14 tests pass, 121/121 social regression pass

Brief 093 — Rejection Learning
Decision: Added brand learning layer to content agent. New content_learnings table in state_registry.py stores distilled rules with source_draft_ids and active flag. Active learnings injected into _build_system_prompt() as "BRAND LEARNINGS (from operator feedback — follow these strictly)" section — only appears when learnings exist, deactivated learnings excluded. New distill_learnings() function: separate Claude call that reads all rejected drafts, builds rejection summary, asks Claude to identify patterns and propose rules, includes existing learnings to prevent duplicates. Manual trigger — operator runs when enough rejection data exists. Learning loop complete: reject → distill → learn → generate better.
Outcome: complete — 12/12 tests pass, 133/133 social regression pass

Brief 094 — Auto Poster + CLI Review
Decision: Created auto_poster.py as the CLI entry point for the content pipeline. Five commands: --generate (calls content_agent.generate_drafts), --review (interactive approve/reject/skip of pending drafts via stdin), --publish (stub-publishes approved drafts — logs + marks as published, real API integration in later brief), --distill (calls content_agent.distill_learnings), --status (pipeline counts). Uses argparse, sys.path setup for standalone execution. Full demo flow now runnable from command line: generate → review → publish → distill. Stub publisher logs to bm_logger and updates SQLite — real Late/Buffer API swap is a single-file change in a future brief.
Outcome: complete — 10/10 tests pass, 143/143 social regression pass

Brief 095 — Branded Graphics Engine
Decision: Created graphics_engine.py for generating 1080x1350 branded JPEG images from draft caption text using Pillow. Template: solid brand primary_color background, headline text (first 1-2 sentences) centered in white, accent color bar at bottom, optional logo. Brand colors/logo_path/font_path all from client.json social_content.brand_graphics — Python defaults are generic (dark grey/white), not client-specific. Uses Pillow's load_default(size=N) for font (no external font download). Added image_path column to content_drafts table + set_draft_image_path() function. Updated get_content_drafts() to return image_path. Added --graphics flag to auto_poster.py for batch generation.
Outcome: complete — 10/10 tests pass, 153/153 social regression pass

Brief 096 — Late Publishing Integration
Decision: Created social_publisher.py using late-sdk Python package (v1.2.89). Three functions: get_instagram_account_id() discovers connected IG account at runtime via SDK, upload_media() uploads JPEG to Late's media storage, publish_to_instagram() creates post with caption + hashtags + image via publishNow=True. Replaced stub cmd_publish() in auto_poster.py with real flow: discover account → auto-generate graphic if missing → upload image → publish → update status. SDK verified against real API — accounts endpoint confirmed, media upload confirmed, post creation signature verified from SDK source. Updated test_094 publish test to mock new publisher functions.
Outcome: complete — 10/10 tests pass, 163/163 social regression pass

Brief 097 — Graphics Overhaul
Decision: Fixed three live-testing issues. (1) Bundled Inter Bold .ttf font (420KB, SIL license) with full Latin Extended support — ç, ñ, ü now render correctly. (2) Replaced flat solid background with vertical gradient (primary_color → gradient_bottom_color). (3) Increased text sizes from 54/42pt to 72/58/46pt, widened margins, repositioned text to upper 40% with 15% top breathing room. Added brand name ("BlueFinn Charters Curaçao") in muted text above thicker accent bar (12px, was 8). All config-driven via client.json brand_graphics section.
Outcome: complete — 12/12 tests pass, 165/165 social regression pass

Brief 098 — Seasonal Awareness + Post-Publication Control
Decision: Two features in one brief. Part A: Added seasonal_calendar to client.json with Curaçao high/low season (Dec-Apr / May-Nov) and 8 events. New _build_seasonal_context() in content_agent.py determines current season via month wrap-around, finds upcoming events within 30 days (handles Dec→Jan year boundary), injected as === SEASONAL CONTEXT === in user prompt. Part B: Added late_post_id and instagram_url columns to content_drafts (ALTER TABLE). cmd_publish now stores both when publishing. Added delete_post() to social_publisher.py (Late SDK posts.delete). Added --delete CLI command to auto_poster.py.
Outcome: complete — 10/10 tests pass, 175/175 social regression pass

Brief 099 — Dashboard API Endpoints
Decision: Created dashboard/api.py with FastAPI router — 15 REST endpoints wrapping existing content pipeline functions. Mounted on existing webhook_server.py (same process, no new systemd service). Auth: password from DASHBOARD_PASSWORD env var, session token in memory, Bearer header on all endpoints. CORS middleware for React dev server. Fixed import-time env var bug (DASHBOARD_PASSWORD read at call time, not import time). All endpoints return JSON — React dashboard (Brief 100) consumes them.
Outcome: complete — 12/12 tests pass, 187/187 social regression pass

Brief 100 — WhatsApp Email Collection + Escalation Email Fix
Decision: Two related fixes. (1) Added email to WhatsApp booking intake fields. Marina now asks for email during booking flow ("And your email for the confirmation?"). Email stored as customer_email in bookings instead of phone number. Falls back to phone when no email provided. Email added to _PERSISTENT_FIELDS so it survives multi-trip and stale resets. (2) Channel-aware escalation: on WhatsApp without email, Marina asks for email first (needs_escalation_email flag), holds escalation until email provided (awaiting_escalation_email state). On WhatsApp with email, escalation fires normally. Email channel unchanged. Both new flags added to _BOOKING_FLAGS_TO_RESET. Escalation notification now includes customer email when available. Updated 2 pre-existing tests broken by the WhatsApp fallback reply change and new WHATSAPP CHANNEL text in escalation prompt.
Outcome: complete — 8/8 tests pass, 195/195 social regression pass

---

Brief 130 — Zernio DM Webhook + Storage Layer
Decision: Foundation for IG/FB DM integration via Zernio API. Added `channel` column (default 'whatsapp') and `sender_name` column to `whatsapp_threads` table via ALTER TABLE migration. New `dm_store_message()` and `dm_get_history()` functions filter by channel. Created `agents/social/zernio_dm_client.py` with HMAC-SHA256 webhook signature verification, flexible payload parser (handles multiple Zernio payload structures), DM reply sender, and typing indicator. New `POST /webhooks/zernio` endpoint in webhook_server.py — verifies signature, dedupes via existing `whatsapp_processed` table, stores DM messages with channel='instagram_dm' or 'facebook_dm'. No agent processing or replies yet (Brief 131). Known interim side-effect: `wa_list_conversations()` returns DM conversations alongside WhatsApp ones (Brief 132 adds channel filtering). Env var `ZERNIO_WEBHOOK_SECRET` required on VPS before deployment.
Outcome: complete — 12/12 tests pass, 288/288 social regression pass

---

Brief 131 — DM Agent + Reply Path
Decision: Close the DM loop — IG/FB DMs now processed through Marina and replies sent back via Zernio. Created `agents/social/dm_agent.py` as a thin Q&A wrapper: fetches conversation history, calls `marina_agent.process_message()` with `channel="instagram_dm"` or `"facebook_dm"`, rate limits at 30 replies/hr per conversation. No booking state machine — booking requests are redirected to WhatsApp/email via prompt instructions. Added DM-specific writing style in `marina_agent.py _build_system_prompt()` with BOOKING REQUESTS section containing wa.me/ link and email from client.json. Extended `_build_user_prompt()` to handle DM channels (conversation history + inbound message format, same as WhatsApp). DM fallback reply added (Rule 3 accepted exception). Webhook handler in `webhook_server.py` now calls `handle_incoming_dm()`, sends typing indicator, sends reply via Zernio, and stores assistant message.
Outcome: complete — 10/10 tests pass, 296/298 social regression pass (2 pre-existing stale date failures in test_070/073)

---

Brief 131b — Separate DM Q&A Agent
Decision: Live testing showed Marina enters full booking flow in DMs despite redirect instructions (collected dates, guests, sent [BOOKING_REF] placeholder). Root cause: Marina's 300-line booking prompt overrides a small redirect paragraph. Fix: separate Claude call in dm_agent.py with Q&A-only system prompt. Reads same client.json data (trips, FAQ, business info) via config_loader but has zero booking logic — no fields, no flags, no JSON schema, no placeholders. Plain text response. Booking redirect to WhatsApp + email (the "booking trilogy" — website form coming later). Reverted all Brief 131 DM additions from marina_agent.py — Marina only handles email + WhatsApp. Safety net strips [BOOKING_REF] and [PAYMENT_LINK] from replies.
Outcome: complete — 10/10 tests pass, 297/299 social regression pass

---

Brief 133 — Payment Timing + Hardcoded Cleanup
Decision: Four generalization fixes for Phase 2 multi-tenant. (1) `payment.timing` flag in client.json — "upfront"/"deposit" generates payment link, "none"/"at_service" strips [PAYMENT_LINK] from confirmation. (2) Hardcoded `info@bluefinncharters.com` in marina_agent.py prompt → reads from `business.email` config. (3) Charter-specific prompt examples ("boat trips", "BBQ", "Klein Curacao", "BlueFinn team") → generic tone examples. (4) Booking ref prefix "BF-" → configurable via `booking_rules.booking_ref_prefix`. Returning customer regex now dynamic. All changes are config-driven — zero new logic.
Outcome: complete — 9/9 tests pass, regression pending

---

Brief 134 — Rename trips→services, generalize config
Decision: Massive mechanical rename across the entire codebase. trips→services, trip_key→service_key, departures→slots, departure_time→slot_time, vessel→resource, departure_point→location, experience→service_name, price_adult_usd→price, fleet→resources. DB migration via ALTER TABLE RENAME in _get_conn(). JSON blob migration for whatsapp_booking_state. Dashboard frontend also renamed. Kept: guests (generic enough), booking_ref, capacity.
Outcome: complete — 308 social pass, 304 marina pass (24 pre-existing failures unchanged). Zero new failures from rename. Deployed to VPS with DB auto-migration.

---

Brief 135 — Feature Toggles: Booking Flow + Terminology + Random Ref
Decision: Three toggles for Tier 1 client support. (1) `features.booking_flow` — when false, booking intents create a detailed escalation (chat log, collected fields, Marina's note) instead of entering the booking state machine. Qualify first, then escalate. (2) `terminology` section in client.json — service_label, party_size_label, slot_label injected into Marina's prompt and DM agent. Changes per client. (3) Random 6-char alphanumeric booking ref (A-Z0-9, 2.2B combinations) replaces prefix-based BF-YYYY-XXXXX format. Returning customer regex updated with DB verification to avoid false positives.
Outcome: complete — 7/7 tests pass, regression pending

---

Brief 136 — Test Debt Cleanup
Decision: Archived 5 stale test files, fixed 30 test failures across 11 files. All mechanical — missing imports, old booking ref format (BF- prefix → 6-char alphanumeric), stale dates, renamed variables from Brief 134. No source code changes.
Outcome: complete — 614 tests, 0 failures

---

Brief 137 — Booking Flow Guard: Email + Soft Hold Fix
Decision: Blind audit found two critical bugs. (1) Email poller had NO booking_flow check — emails ran the full booking flow regardless of toggle. Fixed: added `_booking_flow_on` guard before Step 3b and Step 5, added Step 4.8 escalation for booking intents when flow is off. (2) WhatsApp soft holds leaked before the booking_flow check — Step 7 ran before Step 7.8. Fixed: moved `_booking_flow_on` read before Step 7, added it to the condition. Also guarded `awaiting_booking_confirmation` flag in email poller, fixed 3 logger params (`experience=` → `service_name=`).
Outcome: complete — 617 tests, 0 failures. Deployed.

---

Brief 138 — DM Booking: Route DMs Through Booking Orchestrator
Decision: Route Instagram/Facebook DMs through the WhatsApp booking orchestrator (`handle_incoming_whatsapp_message`) when `booking_flow` is ON. Conversation_id serves as the "phone" key — all state functions accept any string. Reply delivered via Zernio DM API (`send_dm_reply`). When `booking_flow` is OFF, DMs continue using the Q&A agent (`dm_agent.py`). Critical detail: user message stored AFTER orchestrator call to prevent Marina seeing it twice. Only file changed: `webhook_server.py`.
Outcome: complete — 7/7 new tests pass, 624 total tests pass, 0 failures
