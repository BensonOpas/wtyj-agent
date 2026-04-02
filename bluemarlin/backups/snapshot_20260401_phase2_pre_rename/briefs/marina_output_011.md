# OUTPUT_011 — marina_extractor.py — special_requests field

## Files modified
- `bluemarlin/src/marina_extractor.py`

## Files created
- `bluemarlin/briefs/OUTPUT_011.md` (this file)

## Changes made

### File header
- `LAST MODIFIED` updated from `Brief 002` to `Brief 011`

### Step 1 — ALLOWED_KEYS updated
Added `"special_requests"` as an 8th key:
```python
ALLOWED_KEYS = {
    "experience", "date", "guests",
    "adults", "kids", "customer_name", "phone",
    "special_requests"
}
```
The existing `clean = {k: v for k, v in result.items() if k in ALLOWED_KEYS}` filter line
was not touched — it already handles the new key correctly.

### Step 2 — Extraction prompt updated
- Replaced bare allowed-keys list with annotated version (descriptions per field)
- Added `special_requests` entry with verbatim-capture instruction
- Added rule to Rules block:
  > For special_requests: capture any personal context, dietary restrictions,
  > accessibility needs, allergies, celebrations, or preferences verbatim.
  > If none are mentioned, omit the field entirely.
- Function signature, return type, and claude_client import block unchanged

## Dependencies added
None.

## Assumptions
- `claude_client.extract()` returns a dict; the existing filter handles unknown keys —
  no change needed to that line
- `special_requests` is expected to be a plain string; Claude returns it verbatim
  from the message text (not a list, not structured)
- When no special requests are mentioned, Claude correctly omits the field per the
  "If none are mentioned, omit the field entirely" rule

## Test results

```
# Test 1 — imports cleanly
IMPORT OK

# Test 2 — special_requests extracted from clear message
Result: {'experience': 'sunset cruise', 'date': 'March 20', 'guests': 2,
         'customer_name': 'Sarah', 'phone': '+5999123456',
         'special_requests': 'I am diabetic and my partner uses a wheelchair'}
PASS — special_requests: I am diabetic and my partner uses a wheelchair

# Test 3 — special_requests omitted when none mentioned
Result: {'experience': 'half day charter', 'date': '2026-03-25', 'guests': 4}
PASS — special_requests correctly omitted

# Test 4 — celebration context captured
Result: {'experience': 'Sunset cruise', 'date': 'March 28', 'guests': 6,
         'customer_name': 'Carlos', 'phone': '+5999777888',
         'special_requests': 'Booking for my dads birthday, he loves Blue Label whiskey'}
PASS — celebration context captured: Booking for my dads birthday, he loves Blue Label whiskey

# Test 5 — special_requests is a string not a list
Result: {'experience': 'sunset cruise', 'date': 'April 5', 'guests': 2,
         'customer_name': 'Tom', 'phone': '+5999444555',
         'special_requests': 'I have a nut allergy and my wife is vegan'}
PASS — special_requests is string: I have a nut allergy and my wife is vegan

# Test 6 — all original fields still extracted correctly
Result: {'experience': 'full day west coast escape', 'date': '2026-04-10',
         'guests': 3, 'customer_name': 'James', 'phone': '+5999222333'}
PASS — all original fields present

# Test 7 — ALLOWED_KEYS contains special_requests
PASS — ALLOWED_KEYS updated: {'special_requests', 'guests', 'experience', 'date',
                               'kids', 'adults', 'customer_name', 'phone'}
```

All 7 tests pass.

## Flags and uncertainties
- `special_requests` content is verbatim from the customer message — downstream
  callers (email_poller.py) currently do not display or log this field; a future
  brief may need to surface it in the calendar hold payload or confirmation email
- Claude may occasionally include `special_requests` for borderline cases
  (e.g. "I prefer mornings"); the prompt says "omit if none mentioned" which
  covers clear cases but LLM judgement applies at the margins

## SYSTEM_STATE update block
```
Brief 011 — marina_extractor.py — special_requests added as 8th extraction field
  Callers that call extract_fields() may now receive a 'special_requests' key in
  the returned dict. The key is absent when no special requests are mentioned.
  Existing callers that only read known keys are unaffected.
```

## Dependency impact
```
Files that import marina_extractor: email_poller.py (Brief 005/006)
What callers should expect differently:
  extract_fields() may now return {'special_requests': '<verbatim string>', ...}
  email_poller.py currently ignores unknown fields in the merged dict so no
  breakage — but special_requests will accumulate in th["fields"] for the thread
  and will be available for future use (calendar hold, confirmation email, logging).
```

## Regression check block
```
# BRIEF_011 — marina_extractor.py — special_requests field extraction
# Tests: marina_extractor.py
source ~/.zshrc && python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src'); import marina_extractor
assert 'special_requests' in marina_extractor.ALLOWED_KEYS
r1 = marina_extractor.extract_fields(
    'Sunset cruise 2 people March 20. Diabetic passenger.')
assert 'special_requests' in r1, f'FAIL: {r1}'
r2 = marina_extractor.extract_fields(
    'Half day charter 4 people 2026-03-25.')
assert 'special_requests' not in r2 or r2.get('special_requests') in (None, ''), f'FAIL: {r2}'
print('marina_extractor special_requests regression OK')
"
```
