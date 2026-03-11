# CLAUDE.md — BlueMarlin Agent
# Project: BlueMarlin (demo) | Client: BlueFinn Charters Curaçao
# Read this file completely before doing anything else in a session.

---

## WHAT THIS PROJECT IS

An autonomous email booking agent for a charter boat company in Curaçao.
Agent persona: **Marina**. Stack: Python 3.12.3, Ubuntu VPS, Claude Sonnet API
(`claude-sonnet-4-6`), SQLite WAL, Microsoft Outlook OAuth2, Google Calendar +
Sheets via gws CLI, systemd.

**Demo vs Live:** BlueMarlin is the demo project. BlueFinn Charters Curaçao is
the real client. Business data lives in `client.json` only — never in source.

---

## BEFORE YOU DO ANYTHING — READ THESE FILES

```
@briefs/master_plan.md
@briefs/system_state.md
@briefs/infra.md
```

If you are about to modify a file, read it first. Every time. No exceptions.

---

## YOUR TWO MODES

### PLAN MODE
Use /think and /brief commands. Do not freestyle.
**/think** — discuss the next step with the user. Read CLAUDE.md and
system_state.md first, then read any files relevant to what the user describes.
Think out loud, ask questions, flag risks. Do not write any files except
appending to the Decision Log in system_state.md when direction is confirmed.
End with: "Ready for /brief — suggested: /compact first."
**/brief** — write the brief. Read the Decision Log entry and every file the
brief will touch. Write to briefs/marina_brief_0xx_name.md using the mandatory template
below. Auto-invoke brief-reviewer when done. Patch if flagged, one retry max.
End with: "Brief approved — suggested: /compact before executing."
Brief format (mandatory):
```
# BRIEF 0XX — Title
**Status:** Draft | **Files:** list | **Depends on:** | **Blocks:**

## Context
What is the current behaviour and why does it need to change.

## Why This Approach
What was considered, what was rejected, what tradeoff this carries.
2–5 sentences. Not a summary of what the brief does — why THIS and not something else.

## Source Material
All data Claude Code needs to execute — paste it here, do not reference URLs.

## Instructions
Step-by-step. Specific. Every hardcoded value confirmed from source material.

## Tests
Assert specific known values (e.g. price == 120), not just types.
Tests can only pass if the brief was executed exactly as specified.

## Success Condition
One sentence: how to confirm this brief was executed correctly.

## Rollback
How to undo if something goes wrong.
```

### EXECUTE MODE
You receive a brief file path. You execute it and nothing else.

1. Read the brief completely before touching any file
2. Read every file listed in the brief header
3. Execute instructions exactly as written
4. Run the tests
5. Write `briefs/marina_output_0xx.md` with: what was done, test results, anything unexpected

**Ralph loop format for execution:**
```
/ralph-loop "Read briefs/marina_brief_0xx_name.md completely. Execute all instructions
exactly as written. Run all tests. Write briefs/marina_output_0xx.md with results.
Output <promise>DONE</promise> only when OUTPUT file is written and all tests pass."
--completion-promise "DONE" --max-iterations 10
```

Use `ultrathink` in the Ralph prompt for any brief touching marina_agent.py or
the Claude prompt logic.

---

## ARCHITECTURE — NON-NEGOTIABLE

These rules exist because of documented drift. Violating them has caused full
rework cycles. Do not rationalise exceptions.

**Rule 1 — ONE Claude call per inbound message**
`marina_agent.process_message()` is the single Claude API call. Never add a
second Claude call inside `email_poller.py`.

**Rule 2 — Python routes, Claude understands**
Python routes on structured values only. Python never reads reply content, never
pattern-matches language, never classifies intent. Claude does all of that.

**Rule 3 — No static reply templates**
Every `safe_X_reply()` function is debt. No new ones. Ever. If a brief would add
a hardcoded reply string, reframe it as a Claude-generated reply with context.

**Rule 4 — Business data lives in client.json**
Trip names, prices, departure times, calendar IDs, FAQ — all in `client.json`,
injected into the Claude prompt at call time. Never hardcode in source files.

**Rule 5 — No Python language classifiers**
No pattern matching lists, keyword checks, or rule-based language classifiers.
If language needs to be understood, Claude does it.

---

## ACTIVE SOURCE FILES

| File | Brief | Lines | Purpose |
|------|-------|-------|---------|
| `src/email_poller.py` | 031 | ~524 | Core orchestrator. IMAP → marina_agent → calendar → sheets → SMTP |
| `src/marina_agent.py` | 035 | ~237 | Single Claude call per message. Returns structured JSON |
| `src/gws_calendar.py` | 032 | — | Calendar hold + availability via gws CLI |
| `src/sheets_writer.py` | 032 | — | Sheets logging via gws CLI |
| `src/config_loader.py` | 022 | 94 | Read-only client.json interface. Caches on first read. Never raises |
| `src/state_registry.py` | 004 | 57 | SQLite WAL deduplication |
| `src/bm_logger.py` | 006 | 28 | Structured JSONL event logger |
| `src/payment_stub.py` | orig | 57 | Payment stub — demo.pay links only |

---

## KEY INTERFACES

### config_loader.py — public getters
`get_business()` `get_trips()` `get_trip(trip_key)` `get_faq()`
`get_faq_answer(key)` `get_booking_rules()` `get_payment()` `get_fleet()`
`get_agent_signature()` `get_common_sense_knowledge()`

Valid trip keys: `klein_curacao` `snorkeling_3in1` `west_coast_beach`
`sunset_cruise` `jet_ski`

### marina_agent.py — process_message() returns
`intents` `fields` `confidence` `reply` `reply_hold_failed`
`clarifications_needed` `requires_human` `flags` `internal_note`

Valid field keys: `experience` `date` (YYYY-MM-DD) `guests` `customer_name`
`phone` `special_requests` `trip_key` `departure_time` (HH:MM)

### Thread state flags
`awaiting_booking_confirmation` `booking_confirmed` `hold_created`
`slot_checked` `slot_available` `event_id` `event_link` `payment_id`
`payment_link` `payment_status` `booking_ref` (format: BF-YYYY-XXXXX)

---

## KNOWN OPEN ISSUES

- Fallback reply in marina_agent.py (lines 194–208) is a hardcoded string — accepted exception for API failure path only, not a routing template. Rule 3 does not apply.

---

## FILE HEADER FORMAT

Every source file must start with:
```python
# bluemarlin/src/filename.py
# Last modified: Brief 0XX
# Purpose: one line
```

---

## RULES YOU NEVER BREAK

- Never reference a file, function, or variable you have not read in this session
- Never write a brief that touches a file you have not read first
- Never hardcode business values — they go in client.json
- Never add Python logic that reads or classifies language
- Never add static reply strings
- Never tell Claude Code to fetch a URL — include source material inside the brief
- If uncertain about any API detail, write [VERIFY: what needs confirming] and stop
- /compact manually at 50% context usage — do not wait for automatic compaction

---

## Communication
When clarifying complex topics: named categories, one focused question per category.
