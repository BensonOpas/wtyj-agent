# OUTPUT_016 — Multi-label intent classification

## Files modified
- `bluemarlin/src/email_poller.py`

## Files created
- `bluemarlin/briefs/OUTPUT_016.md` (this file)

## Changes made

### File header
- `LAST MODIFIED` updated from `Brief 013` to `Brief 016`

### json import
- Already present on line 20 (`import imaplib, email, urllib.request, urllib.parse, json, ...`)
- No duplicate added

### detect_intent_and_fields() — full replacement
New signature: `def detect_intent_and_fields(text: str) -> tuple[list[str], dict]:`

New `VALID_INTENTS` set (7 labels, "general" removed):
```python
VALID_INTENTS = {
    "booking", "inquiry", "cancellation",
    "reschedule", "complaint", "social", "off_topic"
}
```

New prompt requests a JSON array of all matching intents with 5 examples.

New response parsing:
- `json.loads()` the response
- Strips markdown code fences if present
- Filters to only valid intent strings
- Defaults to `["inquiry"]` on any failure (empty list, parse error, exception)

Return type: `(intents, fields)` where `intents` is `list[str]`.
Adults+kids merge logic and `extract_fields()` call unchanged.

### New reply functions added (after safe_complaint_reply())
- `safe_social_reply()` — warm acknowledgement, invite to book
- `safe_inquiry_reply()` — lists all 3 packages with details, asks for booking fields
- `safe_change_request_reply(action: str)` — acknowledges cancel/reschedule request,
  flags for human follow-up; `action_word` derived from action arg

### Dispatch block — full replacement
Changed `intent, fields = detect_intent_and_fields(body)` →
`intents, fields = detect_intent_and_fields(body)`

Changed log line: `log(f"Intents: {intents} | Merged fields: {merged}")`

New multi-label dispatch logic:
- `if intents == ["off_topic"]:` — only fires safe_out_of_scope_reply when sole intent
- `else:` — handles all other combinations:
  - `if "social" in intents and not any(i in intents for i in ("booking","inquiry","cancellation","reschedule","complaint")):` — pure social reply
  - `if "complaint" in intents:` — always fires empathetic reply (combinable)
  - `if "cancellation" in intents or "reschedule" in intents:` — acknowledgement reply
  - `if "inquiry" in intents and "booking" not in intents:` — packages overview reply
  - `if "booking" in intents:` — full booking flow (verbatim, indented one level deeper)

Booking flow logic is completely unchanged — only wrapped in `if "booking" in intents:`
and indented 4 additional spaces.

## Test results

```
# Test 1 — imports cleanly
IMPORT OK

# Test 2 — returns list not string
Intents: ['booking'] Type: list
PASS

# Test 3 — multi-label: social + booking
Intents: ['social', 'booking']
PASS — multi-label detected

# Test 4 — inquiry intent
Intents: ['inquiry']
PASS

# Test 5 — cancellation intent
Intents: ['cancellation']
PASS

# Test 6 — off_topic only
Intents: ['off_topic']
PASS

# Test 7 — complaint intent
Intents: ['complaint']
PASS

# Test 8 — default fallback on empty input
Empty input intents: ['inquiry']
PASS — no crash on empty input

# Test 9 — new reply functions exist and return strings
PASS — all reply functions return valid strings
Social: Hi there!

Thank you so much — messages like yours
Inquiry: Hi there!

Thanks for reaching out to BlueMarlin T
Cancel: Hi there,

Thank you for reaching out. I've receiv

# Test 10 — VALID_INTENTS contains all 7 labels
PASS — function runs without error
  booking — found
  inquiry — found
  cancellation — found
  reschedule — found
  complaint — found
  social — found
  off_topic — found
PASS — all 7 labels present in source
```

All 10 tests pass.

## Flags and uncertainties
- Smart/curly quotes (U+2018/U+2019) were introduced during the Edit operation inside
  f-string expressions on the `have_summary.append()` lines; fixed post-edit with a
  Python script that replaced them with straight ASCII apostrophes.
- The booking flow `"Curaçao"` string literals already used `\u00e7` escape in the
  original; updated to match in the new booking block.
- `"✅"` emoji in the confirm message uses `\u2705` escape for safety.

## SYSTEM_STATE update block
```
Brief 016 — email_poller.py — detect_intent_and_fields() upgraded to multi-label
  Returns tuple[list[str], dict]; VALID_INTENTS now has 7 labels (removed "general")
  New prompt requests JSON array; parses with json.loads(); fallback ["inquiry"]
  New reply functions: safe_social_reply(), safe_inquiry_reply(), safe_change_request_reply()
  Dispatch block fully replaced: multi-label if/if logic, booking flow unchanged
  off_topic fires only when sole intent; complaint/cancel/reschedule combinable
  No changes to marina_extractor.py, sheets_writer.py, bm_logger.py, or any other file.
```

## Dependency impact
```
Files that import email_poller: none (standalone poller)
What callers should expect differently:
  detect_intent_and_fields() now returns list[str] not str — any caller must unpack
  as (intents, fields) not (intent, fields). No external callers exist currently.
```

## Regression check block
```
# BRIEF_016 — email_poller.py — multi-label intent, all 7 labels, 3 new reply fns
python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src')
import email_poller
intents, fields = email_poller.detect_intent_and_fields('I want to book the sunset cruise')
assert isinstance(intents, list) and 'booking' in intents
intents2, _ = email_poller.detect_intent_and_fields('Hi how much does it cost?')
assert isinstance(intents2, list) and 'inquiry' in intents2
assert callable(email_poller.safe_social_reply)
assert callable(email_poller.safe_inquiry_reply)
assert callable(email_poller.safe_change_request_reply)
assert 'Marina' in email_poller.safe_social_reply()
assert 'Marina' in email_poller.safe_inquiry_reply()
assert 'cancel' in email_poller.safe_change_request_reply('cancellation')
assert 'reschedule' in email_poller.safe_change_request_reply('reschedule')
print('email_poller Brief 016 regression OK')
"
```
