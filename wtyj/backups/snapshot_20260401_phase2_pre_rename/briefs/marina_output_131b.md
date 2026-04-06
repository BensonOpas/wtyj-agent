# OUTPUT 131b — Separate DM Q&A Agent

## What was done

### `agents/social/dm_agent.py` — full rewrite
- Removed `marina_agent.process_message()` call entirely
- Added own Claude call (`claude-sonnet-4-6`, max_tokens=512) with Q&A-focused system prompt
- System prompt reads trips, FAQ, business info from config_loader — same data source as Marina
- Zero booking logic: no fields, no flags, no JSON schema, no `[BOOKING_REF]`
- BOOKING REDIRECT section: redirects to WhatsApp (wa.me/NUMBER) and email
- Returns plain text reply, not structured JSON
- Safety net: strips `[BOOKING_REF]` and `[PAYMENT_LINK]` from replies (defense in depth)
- Keeps: rate limiting (30/hr), history fetching, error handling
- Fallback on API error: "Hey, give me a sec — I'll get back to you!" (Rule 3 exception)

### `agents/marina/marina_agent.py` — reverted Brief 131 DM additions
- Removed `elif channel in ("instagram_dm", "facebook_dm"):` writing style block from `_build_system_prompt()`
- Reverted history section from `channel in ("whatsapp", "instagram_dm", "facebook_dm")` back to `channel == "whatsapp"`
- Reverted inbound section same way
- Removed DM fallback reply from `process_message()`
- Marina now only handles `channel="email"` and `channel="whatsapp"`

## Test results

- **Brief 131b tests: 10/10 passed**
- **Full social regression: 297/299 passed, 2 pre-existing failures** (test_070/073 stale dates). Deleted obsolete test_131_dm_agent.py (replaced by test_131b).

## Unexpected

- None. Clean rewrite + revert.
