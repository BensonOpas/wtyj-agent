# LESSONS — BlueMarlin Agent Briefs

One entry per brief. What worked, what was tricky, what to watch for next time.

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
