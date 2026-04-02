# OUTPUT_023 — marina_agent.py — Unified Claude Call

## Files created
- `bluemarlin/src/marina_agent.py`
- `bluemarlin/briefs/OUTPUT_023.md` (this file)

## Files modified
None. email_poller.py untouched.

## Changes made

### bluemarlin/src/marina_agent.py

One public function: `process_message(from_email, subject, body, thread_fields, thread_flags) -> dict`

**API call:**
- Uses `anthropic.Anthropic()` directly — not claude_client
- Model: `claude-sonnet-4-6`
- `max_tokens=2048`
- Exactly one call per invocation

**Prompt injection:**
- Marina persona and business details from `config_loader.get_business()` + `get_common_sense_knowledge()`
- All five trips from `config_loader.get_trips()` — `[VERIFY...]` fields stripped per trip via `_filter_verify()`
- All FAQ entries from `config_loader.get_faq()` — `[VERIFY...]` answers skipped
- Booking rules from `config_loader.get_booking_rules()`
- Payment policy from `config_loader.get_payment()`
- Today's date in Curaçao timezone (UTC-4, computed via `datetime.now(timezone(timedelta(hours=-4)))`)
- `thread_fields` and `thread_flags` serialised as JSON
- Inbound message: from_email, subject, body

**Response structure (8 required fields):**
`intents`, `fields`, `confidence`, `reply`, `clarifications_needed`, `requires_human`, `flags`, `internal_note`

**JSON parsing:**
- Strips markdown code fences with regex before `json.loads()`
- Validates all 8 required fields present — falls back if any missing

**Fallback:**
- Returned on any exception or unparseable response — never raises
- Fallback reply is natural language asking for date/guests/experience
- Signed with `config_loader.get_agent_signature()`

**Note on local testing:**
- `ANTHROPIC_API_KEY` is set in `~/.zshrc` but not exported to subprocess environments by default
- Tests must be run with the key in environment: `source ~/.zshrc && python3 ...`

## Test results

| # | Test | Result |
|---|------|--------|
| 1 | Returns valid structure (dict, reply >20 chars, intents list, requires_human bool) | PASS |
| 2 | "Book Klein Curacao April 15 for 4" → "booking" in intents | PASS |
| 3 | "Sunset cruise April 20 2026 for 2 guests" → fields.guests == 2 | PASS |
| 4 | "Trip for 20 people" → requires_human is True | PASS |
| 5 | Availability question → reply contains "BlueFinn" or "Marina" | PASS |
| 6 | "Yes that date works" with thread_fields + awaiting_date_confirmation → dict with reply | PASS |
| 7 | "What is the capital of France?" → "off_topic" in intents | PASS |
| 8 | Empty subject and body → dict with reply key, no exception | PASS |

## Regression check block
```
source ~/.zshrc && python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src')
from marina_agent import process_message

r1 = process_message('g@e.com','q','How much is the sunset cruise?',{},{})
assert isinstance(r1['reply'], str) and len(r1['reply']) > 20
assert isinstance(r1['intents'], list)
assert isinstance(r1['requires_human'], bool)

r2 = process_message('g@e.com','','I want to book Klein Curacao on April 15 for 4 people',{},{})
assert 'booking' in r2['intents']

r4 = process_message('g@e.com','','We need a trip for 20 people',{},{})
assert r4['requires_human'] is True

r8 = process_message('g@e.com','','',{},{})
assert 'reply' in r8

print('marina_agent Brief 023 regression OK')
"
```
