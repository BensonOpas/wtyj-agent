# OUTPUT_019 — Ambiguous date confirmation

## Files modified
- `bluemarlin/src/email_poller.py`

## Files created
- `bluemarlin/briefs/OUTPUT_019.md` (this file)

## Changes made

### File header
- `LAST MODIFIED` updated from `Brief 018` to `Brief 019`

### Change 1 — is_date_ambiguous() (added after normalize_date_to_yyyy_mm_dd())
```python
def is_date_ambiguous(date_val: str) -> bool:
```
Returns `True` when no 4-digit year (`20\d{2}`) is found in the string.
"today" and "tomorrow" return `False` — they are unambiguous relative dates.
Uses `re.search(r'\b(20\d{2})\b', date_val)` — the existing `re` import covers this.

### Change 2 — safe_date_confirmation_reply(resolved_date, original) (added before package_key_from_experience)
Formats `resolved_date` to `"%B %d, %Y"` (e.g. "January 01, 2027") using
`datetime.strptime`. Falls back to raw `resolved_date` string on any parse error.
Returns a string asking the customer to confirm or send an explicit date.

### Change 3 — is_date_confirmation_yes(text) (added before package_key_from_experience)
Returns `True` if the stripped, lowercased message is exactly a confirmation word,
or starts with one followed by a space or comma. Confirm words: yes, yeah, yep, yup,
correct, confirmed, sure, ok, okay, si, ja, affirmative, that's right, thats right,
right, exactly.

### Change 4a — Date confirmation intercept (in main loop, after detect_intent_and_fields, before field merge)
When `th["flags"]["awaiting_date_confirmation"]` is set:
- If customer confirmed (is_date_confirmation_yes) → lock date into `th["fields"]["date"]`, clear flag, fall through to normal booking flow
- If customer sent a new date:
  - If new date is still ambiguous → update pending_date, ask again, `continue`
  - If new date has explicit year → lock it, clear flag, fall through
  - If new date cannot be parsed → ask again with original pending date, `continue`
- If no date in message → ask again with original pending date, `continue`

All `continue` branches save thread state before exiting.

### Change 4b — Ambiguous date check (inside `if "booking" in intents:`, before missing fields check)
When `raw_date` is present and `is_date_ambiguous(raw_date)` and not already
`awaiting_date_confirmation`:
- Sets `awaiting_date_confirmation = True`, stores `pending_date` + `pending_date_original`
- Sends `safe_date_confirmation_reply()`
- Logs `date_confirmation_requested` to bm_logger and sheets_writer
- Saves state, `continue` — does NOT proceed to missing fields check

### Change 5 — Thread state default (added `"flags": {}`)
```python
th = threads.get(thread_key, {
    "fields": {},
    "flags": {},
    "last_customer_hash": "",
    "reply_times": []
})
```
Ensures new threads always have a `flags` dict without requiring `setdefault` everywhere.
The `th.setdefault("flags", {})` in the intercept block is retained as a safety net
for threads loaded from old JSON state files that pre-date this change.

## Test results

```
# Test 1 — imports cleanly
IMPORT OK

# Test 2 — is_date_ambiguous() correct results
PASS — is_date_ambiguous() all cases correct

# Test 3 — is_date_confirmation_yes() correct results
PASS — is_date_confirmation_yes() all cases correct

# Test 4 — safe_date_confirmation_reply() returns valid string
Hi there,

Just to confirm — when you said "January 1", did you mean January 01, 2027?

Please reply with Yes to confirm, or send the exact date (e.g. 2026-04-15) if you meant a different date.

Warm regards,
Marina
BlueMarlin Tours Curaçao

PASS — safe_date_confirmation_reply() valid

# Test 5 — all new symbols present in source
PASS — all new symbols present in source
```

All 5 tests pass.

## Assumptions
- `re` is already imported at the top of the file — `is_date_ambiguous` uses it without a new import
- The `\b(20\d{2})\b` pattern matches years 2000–2099. This is correct for BlueMarlin's booking horizon.
- "15/04/2026" triggers the year pattern correctly because `2026` matches `\b20\d{2}\b`
- `datetime.strptime` inside `safe_date_confirmation_reply` uses a local import to keep the function self-contained and exception-safe
- Threads loaded from state files before Brief 019 will not have `"flags"` — the `th.setdefault("flags", {})` in the intercept handles this safely
- The ambiguity check reads `fields.get("date") or merged.get("date", "")` — `fields` is the current message's extracted fields; `merged` is the accumulated thread fields. If date was previously confirmed (locked into `th["fields"]`), it comes through in `merged` with an explicit YYYY-MM-DD format, so `is_date_ambiguous` returns False and the check is skipped correctly.

## Dependencies added
None.

## SYSTEM_STATE update block
```
Brief 019 — email_poller.py — ambiguous date confirmation flow
  New functions: is_date_ambiguous(), safe_date_confirmation_reply(), is_date_confirmation_yes()
  New thread flags: awaiting_date_confirmation, pending_date, pending_date_original
  Date confirmation intercept runs before field merging in main loop
  Ambiguity check runs inside booking dispatch before missing fields check
  Thread state default now includes "flags": {}
  No changes to normalize_date_to_yyyy_mm_dd(), intent classifier, reply functions, or booking flow
```

## Dependency impact
```
Files that import email_poller: none (standalone poller)
What callers should expect differently:
  Customers who send "March 20" (no year) will now receive a confirmation
  request before any hold is created. The thread's flags dict tracks this state
  across email turns. Explicit YYYY-MM-DD dates are unaffected.
```

## Regression check block
```
# BRIEF_019 — email_poller.py — ambiguous date helpers all correct
python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src')
import email_poller
# is_date_ambiguous
assert email_poller.is_date_ambiguous('March 20') == True
assert email_poller.is_date_ambiguous('2026-04-15') == False
assert email_poller.is_date_ambiguous('today') == False
assert email_poller.is_date_ambiguous('April 15 2026') == False
# is_date_confirmation_yes
assert email_poller.is_date_confirmation_yes('yes') == True
assert email_poller.is_date_confirmation_yes('no') == False
# safe_date_confirmation_reply
r = email_poller.safe_date_confirmation_reply('2027-03-20', 'March 20')
assert 'March 20, 2027' in r and 'Marina' in r
# source symbols
with open('bluemarlin/src/email_poller.py') as f: content = f.read()
assert 'awaiting_date_confirmation' in content
assert 'pending_date' in content
print('email_poller Brief 019 regression OK')
"
```
