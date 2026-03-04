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

## Still on OpenClaw (not yet migrated)
- None — OpenClaw fully removed from all active code paths.
