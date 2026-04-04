# LESSONS — BlueMarlin Agent Briefs

**Owns:** The MISTAKES — what went wrong per brief, what to avoid, patterns to follow.
**Related:** For brief outcomes → `system_state.md`. For infrastructure gotchas → `infra.md` ("Things Claude Code Keeps Getting Wrong").

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

## Brief 071 — WhatsApp Escalation: Semi + Full + Fully-Escalated Guard
Date: 2026-03-11
Brief reviewer caught two critical issues: (1) full escalation handler didn't cancel soft holds — email_poller avoids this by checking `requires_human` before the hold-creation step, but WhatsApp's linear flow places escalation handlers after Step 7 (availability), so both semi and full escalation need hold cancellation; (2) tests that trigger semi-escalation need `sheets_writer.log_escalation` mocked since the WhatsApp version adds Sheets logging that email_poller's semi-escalation doesn't have. Also exposed a pre-existing conftest.py bug: `test_067_webhook.py` only set `WHATSAPP_VERIFY_TOKEN` before importing `webhook_server` → `whatsapp_client`, leaving `_PHONE_NUMBER_ID` cached as empty. This was masked when tests ran individually but failed when the full suite ran alphabetically (067 before 068). Fixed with `setdefault` in conftest.py.

## Brief 072 — WhatsApp: Multi-Trip Reset, Returning Customer, Anti-Loop
Date: 2026-03-11
Three review rounds needed — the brief reviewer caught two subtle data flow bugs. (1) The fully-escalated guard returns early, bypassing reply_times recording at the end of the function — without adding reply_times + state persistence to the early return path, anti-loop would never trigger on escalated threads. (2) `returning_booking` and `unknown_ref` were set on `flags` after `agent_flags = dict(flags)` was already copied, so marina_agent would never see them. Fix: dual-set to both dicts. Key lesson: when code has early-return paths, trace every piece of state that needs recording/persisting and verify it happens on ALL exit paths, not just the main one.

## Brief 073 — WhatsApp Hardening: Stale Reset + Cleanup + Edge Case Tests
Date: 2026-03-11
Cleanest brief in the WhatsApp series — the stale reset and cleanup patterns were direct mirrors of email_poller (Briefs 053/065) and mapped cleanly to WhatsApp's state model. The only execution surprise was the change detection test (Test 7): cancelling a hold mid-confirmation doesn't prevent post-validation from re-triggering a new booking summary + hold if all 4 required fields remain present. The fix was to also mock `check_availability` (return unavailable) — same pattern test_071 uses for semi-escalation hold tests. Key lesson: when testing a mid-flow cancellation, always check whether downstream steps will re-trigger the cancelled state. The `wa_get_booking_state` return signature change (adding `last_activity`) caused one regression in test_069's exact-dict assertion — a reminder to use key-specific assertions rather than full dict equality when testing interfaces that may evolve.

## Brief 075 — WhatsApp Live Test Harness
Date: 2026-03-12
First live test harness for WhatsApp — real Claude API calls against the full booking pipeline. Key discovery: `source config/bluemarlin.env` doesn't export variables (no `export` prefix in the file). The fix (`export $(grep ... | xargs)`) works but is fragile — consider adding `export` to each line in bluemarlin.env, or using `set -a` before sourcing. All 26 checks passed first try once the env was loaded correctly. The direct function call approach (calling `handle_incoming_whatsapp_message` directly) is faster and more reliable than HTTP injection — no webhook latency, no polling, deterministic message ordering.

## Brief 074 — WhatsApp: Semi-Escalation Promotion + Rate Limit Bump
Date: 2026-03-12
First brief driven by live conversation analysis rather than spec. The semi-escalation gap was subtle — the same "no guard for awaiting_relay" exists in email_poller.py, but email has the relay bridge (subject-line token matching) so it works end-to-end. WhatsApp lacks the bridge, making semi-escalation a broken promise. The brief reviewer caught incorrect test numbering in the source material (test_072 tests were referenced by wrong numbers), preventing a dead test. Key lesson: when porting a feature across channels, check whether the full end-to-end path exists in the new channel, not just the trigger. A feature that works in email because of a downstream mechanism (relay bridge) doesn't automatically work in WhatsApp just because the trigger code was copied.

## Brief 076 — WhatsApp Message Debouncing + Rate Limit 50
Date: 2026-03-12
Debounce via `threading.Timer` worked cleanly — the per-phone buffer with 2s window + 5s hard cap is the right tradeoff for WhatsApp's rapid-fire typing pattern. The brief correctly anticipated test_067 was safe (empty `changes` → no buffer activity), but missed that test_068 and test_069 integration tests POST real messages through the webhook, which now get buffered instead of processed synchronously. Fix: cancel timer and flush manually in integration tests. Key lesson: when changing the processing model (sync → async/deferred), trace ALL tests that send messages through the full pipeline, not just the ones in the brief's test list.

## Brief 077 — WhatsApp Operator Notification + Relay Bridge
Date: 2026-03-12
Cross-process communication via shared SQLite table was the right call — no new dependencies, no second SMTP consumer, email poller picks up notifications within its existing poll cycle (~30s latency, invisible for "let me check with the team" scenarios). The brief listed test_074 for semi-escalation assertion updates but missed test_071, which also had 3 tests asserting `fully_escalated is True` for semi-escalation paths. Key lesson: when reverting a behavioral change (semi → promote-to-full back to proper relay), grep ALL test files for the old assertion pattern, not just the file where the behavior was originally changed. The import of `wa_send_text_message` in email_poller.py means the email poller process now needs WhatsApp env vars (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`) — a deployment consideration to document.

## Brief 078 — WhatsApp Live Stress Tests
Date: 2026-03-12
Live tests with real Claude calls expose things unit tests can't: (1) multi-departure trips (jet ski has 12 slots) trigger departure disambiguation that blocks confirmation — always specify a departure time in multi-turn booking test messages; (2) extreme slang/emoji input intermittently returns empty reply — Claude may refuse to engage with messages that feel too low-effort or ambiguous, tone down to reliably slangy but comprehensible; (3) Papiamentu (Curaçao's local language) returns empty — it's not in the supported languages list, a real gap for a Curaçao business. Adding `check_availability` to the mock list was critical — without it, tests depend on real Google Calendar state and fail non-deterministically. Output reviewer caught 4 missing state assertions that the brief specified but implementation skipped — always cross-check every "Check state" line in the brief against the actual test code.

## Brief 092 — Content Agent Core + Draft Store
Date: 2026-03-16
First Milestone B brief. The `_build_client_context()` pattern from marina_agent.py was duplicated (not shared) in content_agent.py — acceptable for now since the two agents may diverge, but worth extracting to shared/ if a third consumer appears. The config vs source tradeoff was the key design decision: structural rules (priority stack, classification definitions) that apply to ALL clients stay in Python source, while client-specific values (brand_voice, content_boundaries, emoji_style) are read from client.json at prompt build time. This keeps the system scalable without over-configuring. The `get_availability_summary()` function in state_registry.py avoids a cross-agent import from gws_calendar.py by querying trip_bookings directly — cleaner dependency graph.

## Brief 093 — Rejection Learning
Date: 2026-03-16
Key design: raw rejections in the USER prompt (contextual), distilled learnings in the SYSTEM prompt (persistent rules). This mirrors marina_agent's pattern where thread context goes in user prompt and behavioral rules go in system prompt. The distillation is a manual trigger — not automatic after each rejection — because automatic would waste Claude calls with only 1-2 rejections. The existing learnings are included in the distill prompt to prevent duplicates, which is the same anti-repetition pattern used for recent drafts in generation.

## Brief 094 — Auto Poster + CLI Review
Date: 2026-03-16
Straightforward CLI wrapper — no new business logic, just argparse + print + stdin. The `sys.path.insert` at the top of auto_poster.py is necessary because it runs standalone (not imported as a module), same pattern as the live test harnesses. The stub publisher is intentionally minimal — one `bm_logger.log` + one `update_draft_status` per draft. When we plug in the real Late/Buffer API, only `cmd_publish` changes. The review mode uses `builtins.input` which required `patch("builtins.input")` in tests — straightforward but easy to forget the "builtins." prefix.

## Brief 095 — Branded Graphics Engine
Date: 2026-03-16
Brief reviewer caught a critical font fallback bug: `ImageFont.load_default()` (no size arg) returns a bitmap font that doesn't support `.getlength()` or `.size`, crashing `_draw_wrapped_text`. Fix: always use `load_default(size=N)` (Pillow 10+) which returns a proper FreeTypeFont. This eliminated the need for an external font download entirely. Also caught that Python default colors should be generic (not client-specific) — the original brief had BlueFinn's navy/gold as fallback defaults in source code, violating the config-driven principle. Changed to generic dark grey/white with client colors in client.json only.

## Brief 096 — Late Publishing Integration
Date: 2026-03-16
The research agent's API endpoints were partially fabricated — the presigned URL path was wrong (404). Always verify external API endpoints against the real API before writing a brief. The Late SDK (`late-sdk` on PyPI) was the right choice: it abstracts the presigned URL flow entirely via `client.media.upload()`. Key gotcha: the SDK uses `field_id` (not `id` or `_id`) for account IDs due to Pydantic field name mapping. The brief reviewer correctly caught that replacing `cmd_publish()` would break existing test_094 assertions — always check which tests call functions you're replacing.

## Brief 130 — Zernio DM Webhook + Storage Layer
Date: 2026-04-01

### What happened
Built the Zernio webhook endpoint to receive Instagram/Facebook DMs. HMAC signature verification, payload parsing, dedup, storage in the existing `whatsapp_threads` table with a new `channel` column. All tests passed locally.

Output reviewer caught a runtime bug: `bm_logger.log("webhook_received", source="zernio", event=payload.get("event"))` would crash because `log(event, **fields)` uses `event` as its first positional parameter. Passing `event=` as a kwarg creates a conflict — Python raises `TypeError: log() got multiple values for argument 'event'`.

We fixed it in `zernio_dm_client.py` (renamed to `webhook_event=`), but the identical pattern existed in `webhook_server.py` — we missed it. The output reviewer caught the second instance.

After deploying, a real DM test revealed another issue: the Zernio webhook payload puts `account.id` at the top level, not inside `message.accountId` like our parser expected. The send-reply call failed with "accountId is required." Fixed by checking both locations.

### The principle
When you fix a pattern bug in one file, grep for the same pattern across ALL modified files before committing. `bm_logger.log()` has a positional parameter named `event` — never pass `event=` as a kwarg anywhere.

When building a webhook parser from documentation, the real payload WILL differ. Log the raw payload, write flexible parsers that check multiple field locations, and test with a real webhook before declaring victory.

### What to watch for
Any future `bm_logger.log()` call — never use `event=` as a kwarg. The `webhook_event=` rename pattern is the workaround.

Schema migration with `ALTER TABLE ADD COLUMN` + `try/except sqlite3.OperationalError` is the right pattern for SQLite — idempotent, no migration system needed.

---

## Brief 131 — DM Agent + Reply Path (superseded by 131b)
Date: 2026-04-01

### What happened
Wired up `dm_agent.py` to call `marina_agent.process_message()` with `channel="instagram_dm"`. Added DM-specific writing style block and booking redirect instructions to Marina's prompt. Brief reviewer caught that `contact_for_booking` is under `private_charters` in client.json, not under `business` — the field `business.email` has the same value and is the correct path.

Deployed to VPS. Tested with a real Instagram DM. Marina responded but immediately entered the full booking flow — asked for date, guest count, time slot, confirmed the booking with `[BOOKING_REF]` as literal text. The redirect paragraph was completely ignored.

### Why it failed
Marina's system prompt is 300+ lines of booking logic. The JSON response schema requires booking fields (`experience`, `date`, `guests`, `trip_key`), confirmation flags (`booking_confirmed`, `awaiting_booking_confirmation`), and placeholders (`[BOOKING_REF]`, `[PAYMENT_LINK]`). A single paragraph saying "redirect bookings to WhatsApp/email" cannot override the agent's core identity.

The problem isn't the paragraph — it's the architecture. Asking a booking agent to not book is a contradiction. The entire prompt trains Claude to extract booking fields and confirm bookings. Adding "but not on this channel" is fighting the prompt's own weight.

### What we did
See Brief 131b — complete rewrite with separate Claude call.

### The principle
Always verify config field paths by reading client.json before writing code that accesses them. Field names in nested JSON sections (`private_charters.contact_for_booking` vs `business.email`) are easy to confuse.

---

## Brief 131b — Separate DM Q&A Agent
Date: 2026-04-01

### What happened
After Brief 131's live test failure (Marina entering booking flow in DMs), we considered two approaches: (1) strip the booking schema from Marina's prompt for DM channels, or (2) build a separate Claude call with a Q&A-only prompt. The user initially preferred option 1 (less code to maintain), but after discussing the maintenance burden of channel-conditional prompt spaghetti, chose option 2.

Built `dm_agent.py` with its own Claude call. System prompt reads trips, FAQ, and business info from the same client.json via config_loader — same data, different personality. No booking fields, no flags, no JSON schema, no `[BOOKING_REF]` placeholder. Returns plain text. Marina's code was fully reverted to email + WhatsApp only.

### Why this approach works
The two agents share data (client.json) but not logic. When trip prices change, both agents pick it up automatically. When Marina's booking flow gets updated, DMs aren't affected — that's a feature. The DM prompt is ~60 lines vs Marina's ~300. Maintaining two focused prompts is easier than maintaining one swiss-army-knife prompt with channel exceptions.

### The principle
When the job is fundamentally different (Q&A vs booking), use a different prompt. Don't try to suppress an agent's core behavior with a paragraph of exceptions. Two prompts sharing one data source is the right pattern for multi-channel AI systems.

This also established the "booking trilogy" concept: WhatsApp, Email, and Website (future) are the three channels that handle full bookings. Everything else (IG DM, FB DM, X DM) redirects to the trilogy.

### What to watch for
Any future channel that doesn't need booking flow should use the DM agent pattern, not Marina. The temptation will be to add `elif channel == "new_channel"` to Marina's prompt — resist it. If the channel is Q&A, use the Q&A agent.

---

## Brief 133 — Payment Timing + Hardcoded Cleanup
Date: 2026-04-01

### What happened
Four generalization fixes to make the codebase work for non-charter businesses: (1) `payment.timing` config flag, (2) hardcoded BlueFinn email → config, (3) generic prompt examples, (4) configurable booking ref prefix.

Brief reviewer caught a critical scoping bug: the instructions said to move `trip_key` into the payment timing conditional. But `trip_key` is used by the sheets logging code that runs AFTER the conditional, regardless of payment timing. Moving it inside would cause `NameError` for any non-upfront booking.

Same issue with `pay.get("status")` — referenced in sheets logging but `pay` only exists in the upfront/deposit branch. And `[BOOKING_REF]` replacement was ambiguously positioned — could be interpreted as inside or outside the conditional.

### Why it failed
When wrapping existing code in a new conditional, every variable defined inside the original block becomes scoped to the conditional branch. Any downstream code that references those variables outside the conditional will break. The reviewer caught this by tracing the variable usage beyond the modified lines.

Also discovered: `config_loader.get_raw()` returns a mutable cached dict. Modifying it in tests (`raw["payment"]["timing"] = "none"`) permanently mutates the cached config, leaking between tests. Test 1 changed timing to "none" and test 2 (which expected "upfront") failed because the config was still mutated.

### What we did
Moved `trip_key` and `price_usd` computation outside the conditional (needed by logging regardless). Moved `[BOOKING_REF]` replacement outside (always needed). Only the payment link generation (`payment_stub.generate_payment_link` + `[PAYMENT_LINK]` replacement) is inside the conditional. Changed `pay.get("status")` to `flags.get("payment_status")`. Tests use try/finally to restore config values.

### The principle
When adding a conditional around existing code: trace EVERY variable defined in that block to ALL downstream references. If anything uses it after the conditional, it must be defined before or outside it.

When patching cached data in tests: always restore the original value in a finally block. Mutable shared state is a test isolation trap.

### What to watch for
Any future conditional wrapping of the booking confirmation path — the sheets logging at lines 685-720 (social_agent.py) references `trip_key`, `price_usd`, `booking_ref`, and flag values. All must remain accessible regardless of which branch executes.

---

## Brief 134 — Rename trips→services
Date: 2026-04-01

### What happened
Massive mechanical rename: 150+ occurrences across 50+ files. Used a Python
script for the first pass (dict key strings in .get() calls and SQL), then
regex for Python variable names, then manual fixes for edge cases.

### Why some things went wrong
Regex replacing `trip` as a standalone word caught too many things — variable
names inside function signatures (`def _build_booking_summary(fields, trip):`
became `...fields, service):` but the body still used `trip`), prompt text
that contained the word "trip" as natural language, and f-string variables
inside the booking summary. Each fix uncovered more missed spots.

Initially thought 24 marina tests broke from the rename. Spent time
investigating before realizing they were all pre-existing failures — verified
by running the same tests against the backup.

### The principle
For large mechanical renames: do the string replacements (dict keys, SQL)
with a script first. Then handle function signatures manually by reading
each function. Then run tests and fix what breaks. Don't use broad regex
on variable names — too many false positives.

Always check if test failures are pre-existing before fixing them. Run the
backup code with the same tests first.

### What to watch for
The dashboard frontend is a separate repo and needs its own rename. Don't
deploy backend renames without checking the frontend field names match.

---

## Brief 135 — Feature Toggles
Date: 2026-04-02

### What happened
Added booking flow toggle, terminology system, and random booking refs.
All clean — reviewer caught 4 issues in the brief (hex vs alphanumeric,
thin escalation body, unused terminology keys, vague DM agent instructions),
all fixed before execution.

### The principle
`config_loader.get_raw()` returns a shallow copy of the cached dict. In
tests, modifying the returned dict doesn't affect the cache. To test
config-driven behavior, modify `config_loader._cache` directly with
try/finally cleanup. This is a recurring pattern — documented in infra.md
under "Things Claude Code Keeps Getting Wrong."

Terminology interpolation works because the prompt is an f-string — but
only if the terminology variables are defined in the same function scope
as the f-string. If they're in a different function, they won't interpolate.

### What to watch for
The booking ref regex `\b[A-Z0-9]{6}\b` can match random 6-char strings
in URLs, color codes, or message content. The DB verification check
(`state_registry.get_booking(ref)`) prevents false positives but adds a
DB query per potential match. At current volume this is fine.

---

## Brief 138 — DM Booking: Route DMs Through Booking Orchestrator

### Decision
Route Instagram/Facebook DMs through the existing WhatsApp booking
orchestrator when `booking_flow` is ON. One function rewrite in
`webhook_server.py`, zero changes to the orchestrator, marina_agent,
dm_agent, or state_registry.

### Outcome
Clean execution. The orchestrator already worked with any string as the
"phone" key — conversation_id dropped in without friction. The booking
flow toggle (`features.booking_flow`) now controls all three channels
(WhatsApp, email, DMs) uniformly.

### Key technique: message storage ordering
The brief reviewer caught a critical bug before execution: the original
code stored the user message BEFORE calling the agent, but the
orchestrator reads `wa_get_history` internally. If we store before,
Marina sees the message twice — once in CONVERSATION HISTORY and once
as INBOUND MESSAGE. The WhatsApp path (`_flush_buffer`) stores AFTER
the orchestrator call. The DM booking path must do the same.

The DM Q&A path (booking_flow=false) stores BEFORE, matching its
original behavior — the DM agent uses `dm_get_history` and has always
worked with store-before ordering. Two different storage orders for two
different paths, each matching their channel's pattern.

### What to watch for
The orchestrator's internal `wa_store_message` calls for system notes
(booking confirmations, stale resets, escalations) store with
`channel='whatsapp'` even for DM conversations. This is a minor data
inconsistency — system notes are internal and not displayed to
customers. If the dashboard ever shows system notes by channel, this
will need fixing (pass channel through to the orchestrator or use
`dm_store_message` for system notes).

---

## Brief 139 — Manifest API Error Handling

### What happened
Live DM test (Brief 138): booked Klein Curaçao for April 6, 08:30
departure. The Google Calendar for that slot returned 404 (calendar
deleted or service account lost access). The code treated it as "slot
filled up" — told the customer the slot was taken. Customer tried the
08:00 slot, Claude returned empty JSON (separate API hiccup), and the
fallback said "I'll get right back to you" — but there's no mechanism
to get back. Conversation died.

### The deeper problem
The manifest failure handler (Step 8) treated ALL errors the same:
404 config error, 500 transient error, business logic error — all
showed the same "slot filled up" customer message. No distinction,
no retry, no escalation for persistent failures.

### What we did
Added API error detection: check the error string for HTTP codes
(404, 500, 403, 401) and config errors. For API errors: reset
booking_confirmed and awaiting_booking_confirmation so the customer
can retry. Track retry count; after 2 failures, create a [SYSTEM]
escalation. Clear count on success (circuit breaker doesn't leak
across bookings). For business errors: unchanged.

Also changed the fallback from "give me a moment" to "could you
send that again?" — prompts retry instead of promising a callback
that never comes.

### The brief reviewer caught a critical flaw
First version of the brief tried to replace the hardcoded "fully
booked" strings in Step 7 with Marina's `reply_hold_failed`. But
`reply_hold_failed` is only written when Marina gets the confirmation
action context — which only happens when `awaiting_booking_confirmation`
was already True BEFORE the Claude call. On the FIRST availability
check, it's set AFTER the call by post-validate. So `reply_hold_failed`
is empty, and the fallback would show the booking summary prompt for
an unavailable slot. Worse than the hardcoded string.

### Principle
Not all errors are the same to the customer. "Slot filled up" is an
honest business outcome. "Calendar API returned 404" is a system
problem the customer shouldn't see. Distinguish them.

### What to watch for
- The API error detection uses string matching on the error message.
  If gws CLI changes its error format, the detection silently fails
  and all errors become "business" errors. Defensive: also check for
  single-quote Python dict format (`'code': 404`).
- The four hardcoded "fully booked" strings in Step 7 are accepted
  Rule 3 exceptions. They can't use `reply_hold_failed` because it's
  empty at that point. Future fix: add `reply_hold_failed` to the
  non-confirmation action context too.

---

## Brief 140 — Large Group Pre-Check

### Decision
Groups exceeding service capacity get escalated instead of seeing
"fully booked." Pre-check at the top of Step 7 before the availability
call. Customer gets Marina's original conversational reply.

### Key technique: `reply` vs `reply_text`
The orchestrator has two reply variables. `reply` (line 344) is
Marina's raw Claude response — never modified. `reply_text` (line 412)
is the working copy that post-validate may overwrite with a booking
summary. For the large group path, we use `reply` because `reply_text`
would show a booking summary for an impossible booking, and
`reply_hold_failed` isn't available (not in the action context on
first requests).

### What to watch for
The pre-check uses `>` not `>=`. A group of exactly 20 on a 20-capacity
boat goes through normal availability. This is intentional — if the
slot is empty, 20 fits. If partially filled, `check_availability`
handles it correctly.
