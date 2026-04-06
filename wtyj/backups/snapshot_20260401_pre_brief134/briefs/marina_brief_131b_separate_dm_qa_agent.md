# BRIEF 131b — Separate DM Q&A Agent
**Status:** Draft | **Files:** `agents/social/dm_agent.py`, `agents/marina/marina_agent.py` | **Depends on:** Brief 130 | **Blocks:** Brief 132

## Context

Brief 131 used `marina_agent.process_message()` for DMs. Live testing showed Marina enters the full booking flow (collects dates, guests, confirms with `[BOOKING_REF]` placeholder) despite prompt instructions to redirect. Root cause: Marina's 300-line booking prompt overrides a small redirect paragraph. Different job needs different prompt.

## Why This Approach

**Rejected:** Marina with stripped schema for DM channels — causes prompt spaghetti, every Marina update risks leaking into DMs.

**Chosen:** Separate Q&A Claude call in dm_agent.py. Reads same client.json data via config_loader. Zero booking logic. Plain text response (not structured JSON). Marina stays untouched for email + WhatsApp.

**Tradeoff:** Two prompts to maintain, but they share data (client.json), not logic. Trip/price updates propagate automatically to both.

## Source Material

### config_loader functions to use:
- `get_business()` → `{name, agent_name, email, whatsapp, phone, languages, ...}`
- `get_trips()` → `{trip_key: {display_name, price_pp, ...}, ...}`
- `get_faq()` → `{question_key: answer, ...}`
- `get_common_sense_knowledge()` → `{marina_persona, curacao_timezone, currency, ...}`

### Current dm_agent.py (Brief 131):
- Calls `marina_agent.process_message()` — this is what we're replacing
- Has rate limiting via `_is_rate_limited()` — keep this
- Has history fetching via `dm_get_history()` — keep this

### Current marina_agent.py additions from Brief 131 to revert:
- Lines 180-227: `elif channel in ("instagram_dm", "facebook_dm"):` writing style block in `_build_system_prompt()`
- Lines 448-461: `channel in ("whatsapp", "instagram_dm", "facebook_dm")` in history section (revert to `== "whatsapp"`)
- Lines 463-469: same pattern in inbound section (revert to `== "whatsapp"`)
- Lines 546-548: DM fallback reply in `process_message()`

## Instructions

### Step 1: Rewrite `agents/social/dm_agent.py`

Replace the entire file. The new version:
- Has its own Claude call with a Q&A-focused system prompt
- Builds prompt from config_loader (business, trips, FAQ, common_sense)
- Includes conversation history
- Returns plain text reply
- Strips `[BOOKING_REF]` and `[PAYMENT_LINK]` as safety net
- Keeps rate limiting and error handling
- Fallback reply on API failure: `"Hey, give me a sec — I'll get back to you!"` (Rule 3 exception)

The system prompt should:
- Introduce the agent by name from `business.agent_name`
- Include all trips with display_name and price_pp
- Include FAQ answers
- Have a casual DM writing style (short, no sign-offs, no forced enthusiasm)
- Have a BOOKING REDIRECT section: "You cannot process bookings in DMs. When someone wants to book, redirect to WhatsApp (wa.me/NUMBER) or email (ADDRESS). Do NOT collect booking details."
- Have language rule from common_sense_knowledge
- NOT include any JSON schema, booking fields, flags, or escalation logic

### Step 2: Revert marina_agent.py Brief 131 additions

**2a.** Remove the `elif channel in ("instagram_dm", "facebook_dm"):` block (lines 180-227) from `_build_system_prompt()`. The `else:` block for email should follow directly after the WhatsApp block.

**2b.** In `_build_user_prompt()`, revert the history section (line 450) from `channel in ("whatsapp", "instagram_dm", "facebook_dm")` back to `channel == "whatsapp"`.

**2c.** In `_build_user_prompt()`, revert the inbound section (line 464) from `channel in ("whatsapp", "instagram_dm", "facebook_dm")` back to `channel == "whatsapp"`.

**2d.** Remove the DM fallback reply (lines 546-548) from `process_message()`.

**2e.** Revert header to `# Last modified: Brief 131b` (to track the revert).

## Tests

File: `tests/social/test_131b_dm_qa_agent.py`

1. **test_dm_does_not_call_marina** — mock `marina_agent.process_message`, call `handle_incoming_dm()` with a mocked anthropic response, verify marina was NOT called
2. **test_dm_reply_is_plain_text** — verify reply is a string, not JSON, no `{` characters
3. **test_dm_strips_booking_placeholders** — mock Claude response containing `[BOOKING_REF]`, verify it's stripped from the reply
4. **test_dm_prompt_has_trip_data** — mock the Claude call, capture the system prompt, verify it contains trip names from client.json
5. **test_dm_prompt_has_booking_redirect** — verify system prompt contains "wa.me/" and the business email
6. **test_dm_prompt_has_no_booking_schema** — verify system prompt does NOT contain "booking_confirmed", "awaiting_booking_confirmation", "reply_hold_failed"
7. **test_dm_rate_limiting** — store 30 assistant messages, verify handle_incoming_dm returns empty
8. **test_dm_fallback_on_api_error** — set empty API key, verify returns fallback string
9. **test_marina_whatsapp_unchanged** — call marina `_build_prompt(channel="whatsapp")`, verify it still has WhatsApp style (regression)
10. **test_marina_no_dm_channel** — call marina `_build_prompt(channel="instagram_dm")`, verify it falls through to email style (no DM-specific block)

## Success Condition

DMs use their own Claude call with a Q&A prompt. No booking flow, no placeholders in replies. Marina reverted to email + WhatsApp only. All 10 tests pass.

## Rollback

Restore marina_agent.py from git (Brief 131 version). Restore dm_agent.py from git (Brief 131 version).
