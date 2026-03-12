# LESSONS — BlueMarlin Agent Briefs

One entry per brief. What worked, what was tricky, what to watch for next time.

---

## Brief 055 — Multi-trip booking in one thread
**Date:** 2026-03-09

First draft had an unconditional reset on every message after hold_created — brief reviewer caught that this would break non-booking follow-ups ("Thanks!", FAQ questions) by wiping booking context. The fix was intent-gated reset: archive and reset only when Claude returns booking intent. Key design decision: reset fires AFTER the marina_agent call but BEFORE the field merge, so the old booking is archived from pre-merge state and Claude's new fields merge onto a clean slate. Also critical: `returning_booking` (Brief 054) must NOT be in the reset set — it's a detection flag, not a booking flow flag.

---

## Brief 054 — Booking ref in confirmation + cross-thread memory
**Date:** 2026-03-09

The booking_ref was already generated and stored in thread flags but the prompt never told Marina to include it — a classic "data exists, instruction missing" gap. The cross-thread memory design used a separate `bookings` table rather than reusing `trip_bookings` because the two serve different purposes (capacity tracking vs customer lookup). Brief reviewer caught a real bug: the initial design smuggled `customer_email` through thread flags via an underscore-prefixed key (`_booking_customer_email`) that would leak into the Claude prompt on exception — replaced with a clean function parameter. Key lesson: never inject temporary internal state into a dict that gets persisted or passed to external systems.

---

## Brief 053 — Stale thread reset on new conversation
**Date:** 2026-03-09

Live testing exposed a thread state persistence bug: subject-based thread keys (`sender+subject`) have no expiration, so a new email with the same subject as an old thread inherits stale fields. The root cause was not Claude hallucination — "Jan" was loaded from persisted thread state and injected into the prompt via THREAD CONTEXT. Key lesson: whenever state is keyed on user-controlled values (email subjects), always consider key collisions across time. The fix — detecting new emails (no In-Reply-To/References) and resetting threads older than 24h — is deterministic and doesn't affect active conversations. Extracting the logic into a testable function (`_maybe_reset_stale_thread`) was critical for getting real test coverage instead of inline re-implementations.

---

## Brief 052 — Sheets: Manifests summary tab
**Date:** 2026-03-09

Low-risk additive brief — new function, new tab config, one call site. Brief reviewer caught three issues before execution: (1) revenue approximation was undocumented — always state known limitations explicitly in the brief's "Why" section; (2) tests were all structural (string presence checks) with no behavioral assertions — monkey-patching `_append` to capture the row and asserting specific values was the right pattern; (3) the Manifests tab manual creation requirement was missing — follow the same documentation pattern as existing manual-setup requirements (Escalations tab).

---

## Brief 051 — Integration: rewire booking flow + payment fix
**Date:** 2026-03-09

Medium-risk brief that rewired the core booking path to use manifests. Three critical issues caught by the brief reviewer before execution: (1) `confirm_hold` was placed before `create_or_update_manifest` — if manifest creation failed, you'd be trying to cancel an already-confirmed hold; (2) Step 5 failure path didn't reset `slot_checked`/`slot_available` or pop `hold_id`, leaving stale state that would block retries; (3) cancel sites needed `remove_from_manifest()` calls to keep the calendar in sync. Key insight: store slot info (`hold_trip_key`, `hold_date`, `hold_departure_time`) in thread flags at soft-hold creation time, not at cancel time — `th["fields"]` may have changed if the customer modified their booking mid-thread.

---

## Brief 050 — Manifest foundation: tables + calendar functions
**Date:** 2026-03-09

Purely additive foundation brief — no existing behavior touched. Key design decision: manifest events are per-slot (trip_key + date + departure_time), not per-customer, so a separate `manifest_events` table with composite PK is the correct model rather than adding a column to `trip_bookings`. Adding `customer_name`/`customer_email` to the bookings table (rather than looking them up from thread state at manifest-build time) keeps the manifest builder self-contained. Brief reviewer caught a dead parameter (`booking_ref` in `create_or_update_manifest`) that would have caused confusion downstream — the function gets refs from SQLite via `get_slot_passengers()`, so passing it as a parameter was misleading.

---

## Brief 049 — Fix format_sheets.py + apply formatting to new dashboard
**Date:** 2026-03-09

Straightforward broken-import fix. `format_sheets.py` has been silently broken since Brief 032 removed `_get_service()` and `SPREADSHEET_ID` from `sheets_writer.py`. Key lesson: when a refactor removes symbols from a module, grep for all importers — `format_sheets.py` was a run-once script that nobody noticed was broken because it's never called by the poller. Also caught stale Bookings headers (13 cols vs 15 actually written) — always cross-check formatter headers against writer row structures after column layout changes.

---

## Brief 048 — Human speech optimization: multi-topic fix + prompt hardening
**Date:** 2026-03-09

Three bugs from live testing, one architectural fix. The multi-topic issue (answers to side questions dropped when `_post_validate` overrides) was solved by appending overrides instead of replacing when non-booking intents are present. The date-clearing bug was deeper than expected: the brief reviewer caught that the field merge logic silently discards empty strings, so Claude's `date: ""` would never reach thread state — required a merge logic fix alongside the prompt instruction. Key lesson: when adding a new clearing mechanism, trace the value through every layer (extraction → merge → validation) to verify it survives.

---

## Brief 047 — Treat reschedule intent as booking-active
**Date:** 2026-03-09

Live testing caught what unit tests couldn't: Claude classified a mid-thread date change as `reschedule` instead of `booking`, bypassing Python's entire validation path. The fix was a `_BOOKING_INTENTS` set that widens three intent gates. Key lesson: when Python gates on Claude's intent labels, always consider which other labels could appear for the same user action — the model's intent taxonomy and the code's routing assumptions must match.

---

## Brief 046 — Hybrid refactor: Python state machine + simplified Claude prompt
**Date:** 2026-03-08

After Briefs 044 and 045 each patched one prompt compliance failure and exposed the next, the root cause was clear: 62 lines of state machine logic in Claude's prompt (FIRST/SECOND/THIRD checks, confirmation handling, slot-unavailable alternatives) was too complex for reliable compliance. The fix was architectural — move all deterministic validation (day-of-week, departure time, summary generation, flag management) to Python, and simplify Claude to field extraction + conversational reply + confirmation detection. Key insight: always-overwrite field merge (instead of accumulate-only) prevents dead-ends after slot-unavailable responses. Brief reviewer caught a critical dead-end bug in the initial design (slot_checked not reset + stale field overwrite) before execution.

---

## Brief 045 — Slot-unavailable alternative = change, not confirmation
**Date:** 2026-03-09

Marina interpreted a customer picking a slot-unavailable alternative as a booking confirmation instead of a change. The prompt's "change" handler covered date/departure changes but didn't explicitly address the slot-unavailable-then-pick-alternative flow. Also added a Python safety net: strip literal `[PAYMENT_LINK]` before sending any booking reply — prevents placeholders from reaching customers regardless of prompt compliance failures.

---

## Brief 044 — Departure time before booking summary for multi-departure trips
**Date:** 2026-03-09

Marina sent a full booking summary (with `[PAYMENT_LINK]` and confirmation flag) while simultaneously asking for departure time on a multi-departure trip. The prompt explicitly told her departure_time was optional before the summary. Fix: add a THIRD pre-summary check that gates on departure_time for multi-departure trips and auto-selects for single-departure trips. Brief reviewer correctly caught that the mid-confirmation re-run instruction also needed updating to include the new THIRD check — same class of gap that created the original bug.

---

## Brief 043 — Fix relay detection + poisoned relay bug
**Date:** 2026-03-09

Two root causes for relay failure: (1) Python's legacy `email` module does NOT auto-decode RFC 2047 headers — `msg.get("Subject")` returns raw `=?utf-8?q?...?=` strings, not decoded text. Gmail encodes reply subjects even when the original was ASCII. Always decode headers before string matching. (2) Thread flags passed to marina_agent must be filtered per-context — relay flags like `awaiting_relay` are meaningful only when the relay handler is processing an actual relay reply, not when a customer sends a follow-up on the same thread. The RELAY MODE prompt injection fired for customer messages, garbling the reply.

---

## Brief 042 — Operator email hardening
**Date:** 2026-03-08

Live testing surfaced two gaps in the relay/escalation system: (1) operator replies to [ESCALATION] alerts looped back through the poller as new "customer" messages — fix was a one-line drop guard; (2) [RELAY] subject detection was a magic string with no thread specificity — replaced with UUID relay token embedded in the subject, stored per-thread, and matched exactly on reply. The output reviewer correctly flagged that the guard fires *after* `mark_as_processed`, not before — the code is correct but the documentation was wrong, which is an easy thing to miss when the anchor is visual rather than positional.

---

## Brief 041 — Semi-escalation prompt fix
**Date:** 2026-03-08

Live testing caught what unit tests missed: Marina was using "contact us at info@..." as a fallback for specific unanswerable questions instead of triggering semi_escalation. The fix was prompt-only — the relay infrastructure (Brief 040) was already correct. Key lesson: when adding a new behavior path (relay system), explicitly prohibit the existing fallback behavior that would compete with it, otherwise the model defaults to the pattern it already knows.

---

## Brief 040 — Escalation system: semi + full
**Date:** 2026-03-08

Two reviewer passes needed: (1) format_sheets.py anchor had a double-space (`ALL_EVENTS_WIDTHS =  [...]`) that a single-space anchor would miss — always copy-paste exact whitespace from Read tool output when anchoring edits in files with aligned spacing; (2) relay block's `smtp_send` to customer was unguarded — any optional path that depends on a flag value (like `relay_customer_email`) that might be absent needs a try/except or an explicit guard before the send; (3) `semi_escalation` must cancel the soft hold created in Step 3b to avoid capacity leaks — whenever a `continue` path bypasses the normal booking flow, check whether Step 3b already ran and clean up any side effects.

---

## Brief 039 — Capacity-aware booking with soft holds
**Date:** 2026-03-08

Two review cycles were needed: (1) `{N}` inside an f-string in the prompt raises `NameError` — always use `{{N}}` for literal braces inside Python f-strings in marina_agent.py prompt sections; (2) `create_soft_hold` using raw `sqlite3.connect()` bypasses `_get_conn()`'s table creation — always route through `_get_conn()` for schema guarantees, then set `isolation_level = None` if manual transaction control is needed. Brief reviewer caught both before execution; test suite cleanly validated all 8 scenarios including concurrent race.

## Brief 058 — Fix: Booking Ref Missing from Confirmation Reply
Date: 2026-03-10
When introducing a new value that is generated AFTER the marina_agent call (like booking_ref), never instruct Marina to read it from thread_flags — it will not be there. Use the [PLACEHOLDER] pattern already established by [PAYMENT_LINK]: Marina writes the placeholder, Python replaces it post-hold. Also always add a strip on the non-success path to prevent raw placeholders reaching customers.

## Brief 059 — Marina Tone Polish
Date: 2026-03-10
Prompt-only change with big output impact. The comprehensive writing style guide (stock phrase bans, AI habit bans, tone mirroring, length matching, self-check) significantly improved reply naturalness. Token cost is ~500 extra tokens per call, acceptable for demo. The emoji rule (confirmations only) was a user-specified compromise — watch for edge cases in live testing.

## Brief 064 — Past Date Check, Escalation Email Info, Noreply Filter, Email-Based Returning Customer
Date: 2026-03-10
Four small, localized fixes from live stress testing. The past-date check must go after the day-of-week check — if the date falls on an invalid day, the day-of-week error is more actionable than "already passed". Test design caught this: the initial test date (Jan 15 2025, a Wednesday) triggered the day-of-week check first, masking the past-date check. Email normalization in `save_booking()` is critical — without it, `get_bookings_by_email()` won't match case-variant emails. The escalation email format change is a "data was available but not surfaced" pattern — `from_email` was already in scope at the escalation code path, just never included in the outbound email.

## Brief 065 — Production Hardening: Rate Limiting, Thread Cleanup, Monitoring, OAuth Auto-Refresh
Date: 2026-03-10
All four fixes were localized to existing files with no architectural changes — the cleanest brief in the series. The `now` variable placement was the only tricky part: sender rate limiting runs before the original `now = int(time.time())` definition, so it needed an early assignment at the top of the `for uid` loop. The `_cleanup_stale_data()` function's safety guarantee (hold_created threads preserved) prevents accidental data loss during archival. OAuth auto-refresh is a "data was already there, just not saved" pattern — Microsoft returns a new refresh_token on every exchange, we just weren't reading it.

## Brief 067 — WhatsApp Webhook Server + VPS Infrastructure
Date: 2026-03-11
First greenfield infrastructure brief — standing up nginx, SSL, FastAPI, systemd from scratch on a VPS that previously only ran a Python poller. Two blockers hit during execution: (1) Ubuntu Noble blocks system-wide pip installs by default (`externally-managed-environment`) — used `--break-system-packages` to match existing install pattern; (2) VPS firewall (ufw) only had port 22 open, so certbot's HTTP challenge failed — had to open ports 80 and 443 first. Key lesson for future VPS infra briefs: always check firewall rules before attempting any public-facing service setup.

## Brief 068 — WhatsApp Message Pipeline: Parse, Dedup, Reply
Date: 2026-03-11
Cleanest multi-file brief in the social agent series — parse, dedup, stub agent, and send all worked first try with zero test failures. The brief reviewer flagged the hardcoded reply as a Rule 3 violation; patched by documenting it as a temporary verification fixture (same class as marina_agent.py's accepted API-failure fallback). Key discovery: Meta sends status webhooks (sent/delivered) back through the same endpoint immediately after our reply — the status filtering logic in `parse_webhook_payload` correctly handled these without any extra work. Using `urllib.request` (stdlib) for outbound API calls avoided dependency issues on the VPS.

## Brief 069 — WhatsApp Channel Support: marina_agent + State Foundation
Date: 2026-03-11
The `channel` parameter approach worked cleanly — marina_agent.py stays as the single Claude brain for both email and WhatsApp with zero duplication. Key design tradeoff: conversation history is stored only on successful reply (webhook_server stores user+assistant after send succeeds). This means failed API calls leave no trace in history, which is arguably correct — no response means nothing to remember. The conditional writing style block in `_build_system_prompt` keeps the two styles fully isolated without any shared template logic. All 17 tests passed first try with zero regression across 067/068.

## Brief 070 — WhatsApp Booking Orchestrator
Date: 2026-03-11
First brief review caught fabricated trip data in Source Material — all departure times, prices, capacities, and operating days were wrong vs client.json. Key lesson: always read client.json before writing any brief that references trip data, never rely on memory. After correction, the pure-function helpers (`_day_matches`, `_suggest_dates`, `_post_validate`) worked cleanly against real config_loader data. The simplified function signatures (taking `fields` and `flags` directly instead of `th` dict) made tests simpler without losing any behavior. All 50 tests passed first try after the brief rewrite.
