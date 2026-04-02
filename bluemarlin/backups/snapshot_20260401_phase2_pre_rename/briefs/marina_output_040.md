# OUTPUT 040 — Escalation system: semi + full

**Status:** Complete — all 5 tests pass
**Date:** 2026-03-08
**Brief:** BRIEF_040_escalation_system.md

## What Was Done

### Step 1 — config/client.json
Added `support_email` and `demo_support_email` fields to the `"business"` object after `spreadsheet_id`.

### Step 2 — src/marina_agent.py
- 2a: Added `relay_mode_section` and `fully_escalated_section` variables after `signature = config_loader.get_agent_signature()`, built conditionally on `thread_flags`.
- 2b: Injected both sections into the f-string return (between the `You are Marina...` opener and `PERSONA:`).
- 2c: Replaced ESCALATION BEHAVIOUR section — updated to include refund requests, changed the exact reply text to include `info@bluefinncharters.com`, added the full SEMI-ESCALATION instruction block.
- 2d: Added `semi_escalation` and `relay_question` as top-level JSON response fields (siblings of `flags`/`reply`).
- 2e: Updated file header to Brief 040.

### Step 3 — src/email_poller.py
- 3a: Added `from datetime import datetime, timezone` import.
- 3b: Added `reply_to=None` parameter to `smtp_send()` signature and `if reply_to: msg["Reply-To"] = reply_to` header injection.
- 3c: Added `"messages": []` to thread default dict.
- 3d: Added `demo_support_email` load from `config_loader.get_business()` at top of `main()`.
- 3e: Added relay detection block (`[RELAY]` from demo_support_email), inbound message append to chat log, and fully_escalated guard — all inserted between the anti-loop guard and Step 1.
- 3f: Replaced Step 4 (requires_human) block — now appends to `th["messages"]`, sets `fully_escalated: True`, builds and sends full escalation alert email to `demo_support_email`, passes `messages_json` to `log_escalation`.
- 3g: Added semi-escalation handler between Step 3b and Step 4 — cancels soft hold, sets `awaiting_relay` flags, sends relay alert to `demo_support_email` with `reply_to=EMAIL_ADDR`, sends holding reply to customer, appends to `th["messages"]`.
- 3h: Added `th["messages"].append(...)` after smtp_send in Step 5 (booking) and Step 6 (all other intents).
- 3i: Updated file header to Brief 040.

### Step 4 — src/sheets_writer.py
Added `data.get('messages_json', '')` as 7th column in `row_escalations`. Updated file header to Brief 040.

### Step 5 — src/format_sheets.py
Added `ESCALATIONS_HEADERS` (7 columns) and `ESCALATIONS_WIDTHS` after `ALL_EVENTS_WIDTHS`. Added `Escalations` entry to `TABS` list. Updated file header to Brief 040. Pre-existing broken import on line 11 (`from sheets_writer import KEY_PATH, SPREADSHEET_ID, _get_service`) left untouched per brief.

## Test Results

```
Running Brief 040 tests...
  T1 PASS: semi_escalation=True, relay_question="A guest's father uses a wheelchair and is joining the Klein Curaçao trip on 2026-04-15 (3 guests total). They would like to know: Is the boat accessible for wheelchair users, and is there a ramp or lift for boarding?"
  T2 PASS: relay reformulation reply="Great news, John! 📷 You're absolutely welcome to bring your DSLR on board — and we even have a fresh"...
  T3 PASS: requires_human=True, reply contains production email
  T4 PASS: holding reply='Hi there! Thank you so much for following up — I completely understand the wait can feel frustrating'...
  T5 PASS: Escalations row has 7 columns, messages_json in col 7

All 5 tests passed.
```

## Unexpected / Noteworthy

- The ANTHROPIC_API_KEY must be sourced from `~/.zshrc` before running tests (not auto-exported to subprocesses). Tests were run with `source ~/.zshrc && python3 ...`.
- T1: Claude correctly identified wheelchair accessibility as unanswerable from the FAQ and produced a detailed `relay_question` including the booking context.
- T4: Claude correctly produced a warm holding reply without re-escalating or setting booking flags, consistent with the FULLY ESCALATED THREAD prompt instruction.
- No issues with any of the 8 email_poller edits or the 5 marina_agent edits.
