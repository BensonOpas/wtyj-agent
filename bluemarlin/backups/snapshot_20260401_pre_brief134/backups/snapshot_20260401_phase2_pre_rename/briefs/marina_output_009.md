# OUTPUT_009 — Marina intelligence improvements

## Files modified
- `bluemarlin/src/email_poller.py`

## Files created
- `bluemarlin/briefs/OUTPUT_009.md` (this file)

## Changes made

### File header
- `LAST MODIFIED` updated from `Brief 006` to `Brief 009`

### Change 1 — normalize_date_to_yyyy_mm_dd (lines ~253–268)
- Added `import dateparser` at module level (after `import smtplib, base64`)
- Kept `today` / `tomorrow` / YYYY-MM-DD paths exactly unchanged
- Added `dateparser.parse()` fallback with settings:
  - `PREFER_DAY_OF_MONTH: "first"`
  - `PREFER_DATES_FROM: "future"`
  - `TIMEZONE: "America/Curacao"`
  - `RETURN_TIME_AS_PERIOD: False`
- Wrapped in `try/except`; returns `""` on any exception or `None` result

### Change 2 — detect_intent_and_fields (lines ~179–207)
- Removed hard keyword regex (`joke|riddle|...`) and booking-word heuristic
- Added `claude_client.complete()` call with 4-way intent classifier prompt
- Valid intents: `booking`, `complaint`, `off_topic`, `general`
- Defaults to `"general"` if Claude returns unexpected output or raises
- Kept `extract_fields(text)` call and adults+kids merge logic unchanged
- Function signature unchanged; return type unchanged

### Change 3 — safe_complaint_reply() and complaint dispatch (lines ~243–253, ~455–461)
- Added `safe_complaint_reply()` function immediately before `package_key_from_experience()`
- Added `elif intent == "complaint":` path in main loop dispatch block, between
  the `out_of_scope`/`off_topic` branch and the `booking`/`general` branch
- Updated `if intent == "out_of_scope":` to `if intent in ("out_of_scope", "off_topic"):`
  so that both the legacy label and the new Claude-returned label are handled

### Change 4 — internal note removed (line ~553)
- Removed `f"(Internal note: {err})\n\n"` from the booking failure reply
- The customer now receives only the public-facing message and alternatives

## Dependencies added
- `dateparser==1.3.0` (installed via `pip3 install dateparser --break-system-packages`)
  - Also pulled in: `python-dateutil`, `pytz`, `regex`, `six`, `tzlocal`

## Assumptions
- `ANTHROPIC_API_KEY` is set in the runtime environment (required for the Claude intent classifier)
- When the API key is absent or Claude returns unexpected output, intent defaults to `"general"` — system degrades gracefully
- `"off_topic"` is the canonical return value for non-charter messages going forward; `"out_of_scope"` retained in dispatch condition for backward compatibility
- `dateparser` with `PREFER_DATES_FROM: "future"` correctly advances "March 20" to the next occurrence when March 20 has not yet passed, or to next year if it has — tested as 2026-03-20 with today = 2026-03-03

## Test results

```
# Test 1 — imports cleanly
IMPORT OK

# Test 2 — YYYY-MM-DD passthrough
PASS — YYYY-MM-DD passthrough

# Test 3 — today and tomorrow
PASS — today: 2026-03-03 tomorrow: 2026-03-04

# Test 4 — natural language date
March 20 -> 2026-03-20
PASS

# Test 5 — garbage returns empty string
PASS — garbage returns empty string

# Test 6 — booking intent
Intent: booking Fields: {'experience': 'sunset cruise', 'date': 'March 20', 'guests': 2}
PASS

# Test 7 — off_topic intent
Intent: off_topic
PASS

# Test 8 — complaint intent
Intent: complaint
PASS

# Test 9 — handles bad Claude output gracefully
Empty input intent: general
PASS — no crash on empty input

# Test 10 — internal note line removed
PASS — internal note removed

# Test 11 — safe_complaint_reply exists and returns a string
PASS — complaint reply: Hi there,

Thank you for reaching out, and I'm sorry to hear
```

All 11 tests pass.

## Flags and uncertainties
- Tests 6–9 require `ANTHROPIC_API_KEY` to be set; without it `claude_client.complete()` returns `""` and intent defaults to `"general"` for all messages
- Claude intent classifier is non-deterministic — edge cases near classification boundaries may occasionally return an unexpected word, defaulting to `"general"`
- `dateparser` with `PREFER_DATES_FROM: "future"` may behave unexpectedly for ambiguous formats (e.g., `"03/15"` — interpreted as month/day vs day/month depending on locale); the `TIMEZONE` setting mitigates timezone drift

## SYSTEM_STATE update block
```
Brief 009 — email_poller.py — normalize_date_to_yyyy_mm_dd now handles natural language dates
  via dateparser; callers of create_calendar_hold() benefit automatically.

Brief 009 — email_poller.py — detect_intent_and_fields now classifies via Claude API;
  returns one of {booking, complaint, off_topic, general}; callers must handle "off_topic"
  and "complaint" in dispatch logic (main loop updated accordingly).

Brief 009 — email_poller.py — safe_complaint_reply() added; complaint emails now receive
  an empathetic holding reply rather than falling into the booking path.

Brief 009 — email_poller.py — internal error details no longer leaked to customers in
  booking-failure reply.
```

## Dependency impact
```
Files that import email_poller: none (it is the top-level runner)
What callers should expect differently: N/A — email_poller is invoked as __main__
```

## Regression check block
```
# BRIEF_009 — email_poller.py — date normalization handles natural language dates
# Tests: (inline test commands)
source ~/.zshrc && python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src'); import email_poller
assert email_poller.normalize_date_to_yyyy_mm_dd('2026-03-20') == '2026-03-20'
assert email_poller.normalize_date_to_yyyy_mm_dd('today') != ''
assert email_poller.normalize_date_to_yyyy_mm_dd('March 20').endswith('-03-20')
assert email_poller.normalize_date_to_yyyy_mm_dd('asdfghjkl') == ''
print('date normalization OK')
"

# BRIEF_009 — email_poller.py — Claude intent classifier returns valid intents
# Tests: (inline test commands — requires ANTHROPIC_API_KEY)
source ~/.zshrc && python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src'); import email_poller
intent, _ = email_poller.detect_intent_and_fields('I want to book a sunset cruise')
assert intent in ('booking', 'general', 'off_topic', 'complaint'), f'bad intent: {intent}'
intent2, _ = email_poller.detect_intent_and_fields('')
assert intent2 in ('booking', 'general', 'off_topic', 'complaint')
print('intent classifier OK')
"

# BRIEF_009 — email_poller.py — safe_complaint_reply and internal note removal
source ~/.zshrc && python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src'); import email_poller
r = email_poller.safe_complaint_reply()
assert isinstance(r, str) and 'Marina' in r
with open('bluemarlin/src/email_poller.py') as f:
    assert 'Internal note:' not in f.read()
print('complaint reply and note removal OK')
"
```
