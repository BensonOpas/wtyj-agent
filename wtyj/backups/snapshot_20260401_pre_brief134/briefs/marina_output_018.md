# OUTPUT_018 — Three bug fixes

## Files modified
- `bluemarlin/src/email_poller.py`
- `bluemarlin/src/marina_extractor.py`

## Files created
- `bluemarlin/briefs/OUTPUT_018.md` (this file)

## Changes made

### email_poller.py — file header
- `LAST MODIFIED` updated from `Brief 017` to `Brief 018`

### Fix 1 — Anti-loop constants (email_poller.py ~line 54)
```python
# Before
MAX_REPLIES_PER_THREAD = 3
REPLY_WINDOW_SECONDS = 10 * 60

# After
MAX_REPLIES_PER_THREAD = 10
REPLY_WINDOW_SECONDS = 60 * 60
```
A 3-reply / 10-minute window was too tight for legitimate multi-turn bookings
(missing fields → name/phone → confirm = 3 exchanges minimum). Now allows
10 replies per hour.

### Fix 2 — Past date guard (email_poller.py, inside create_calendar_hold())
Added immediately after the `if not date_iso:` early-return block:
```python
# Past date guard
try:
    from datetime import date as _date
    booking_date = _date.fromisoformat(date_iso)
    today = _date.today()
    if booking_date < today:
        return {
            "ok": False,
            "error": f"Requested date {date_iso} is in the past."
        }
except Exception:
    pass  # If date parsing fails here, let calendar.js handle it
```
`_date` alias used throughout to avoid shadowing the `date` local variable
defined later in the booking flow. No top-level `datetime` import added —
the local import inside the function is sufficient and matches the pattern
already used in `normalize_date_to_yyyy_mm_dd()`.

### marina_extractor.py — file header
- `LAST MODIFIED` updated from `Brief 011` to `Brief 018`

### Fix 3 — special_requests prompt tightened (marina_extractor.py)
Two updates to `extract_fields()` prompt:

**Key annotation** (in the Allowed keys list):
```
# Before
- special_requests (dietary needs, allergies, accessibility
  requirements, celebrations, drink preferences, or any
  other personal notes — capture verbatim as a single string)

# After
- special_requests (forward-looking preferences for the
  upcoming trip only: dietary needs, allergies, accessibility
  requirements, celebrations, drink preferences — capture
  verbatim. Exclude complaints about past experiences.)
```

**Rule** (in the Rules block):
```
# Before
- For special_requests: capture any personal context,
  dietary restrictions, accessibility needs, allergies,
  celebrations, or preferences verbatim. If none are
  mentioned, omit the field entirely.

# After
- For special_requests: capture ONLY forward-looking personal
  preferences for the upcoming trip — dietary restrictions,
  allergies, accessibility needs, celebrations, drink
  preferences, or specific requests for the day.
  Do NOT capture complaints about past experiences,
  negative feedback, or anything referring to a previous trip.
  Those are complaints, not special requests.
  If no forward-looking preferences are mentioned, omit
  the field entirely.
```

## Test results

```
# Test 1 — imports cleanly
IMPORT OK

# Test 2 — anti-loop constants updated
PASS — anti-loop constants updated

# Test 3 — past date guard present
PASS — past date guard present

# Test 4 — past date actually rejected
Result: {'ok': False, 'error': 'Requested date 2020-01-01 is in the past.'}
PASS — past date correctly rejected

# Test 5 — complaint not extracted as special_requests
Extracted fields: {'experience': 'half day charter', 'date': 'April 10', 'guests': 4}
PASS — complaint not extracted as special_requests

# Test 6 — real special_requests still captured
Extracted fields: {'experience': 'sunset cruise', 'special_requests': 'My wife has a shellfish allergy'}
PASS — real special_request captured: My wife has a shellfish allergy

# Test 7 — future date not rejected by past date guard
Future date result ok: False
PASS — future date not rejected by past date guard
```

All 7 tests pass. Test 7 `ok: False` is expected — calendar.js requires
Google credentials not available in the test environment; the important
assertion is that the `error` field does not contain "past".

## Assumptions
- `date.today()` uses the system clock (Mac/VPS local time). On Curaçao
  VPS (UTC-4), this is consistent with the booking timezone. If the VPS
  runs UTC, a booking for "today in Curaçao" submitted before midnight UTC
  could be rejected. Accepted as acceptable edge-case for a demo system.
- The `except Exception: pass` swallows any `fromisoformat` failure and
  defers to calendar.js — correct, since `date_iso` was already validated
  as `^\d{4}-\d{2}-\d{2}$` by `normalize_date_to_yyyy_mm_dd()`.

## Dependencies added
None.

## SYSTEM_STATE update block
```
Brief 018 — email_poller.py + marina_extractor.py — three bug fixes
  email_poller: MAX_REPLIES_PER_THREAD 3→10, REPLY_WINDOW_SECONDS 10min→60min
  email_poller: create_calendar_hold() rejects past dates before calling calendar.js
    — returns {"ok": False, "error": "Requested date YYYY-MM-DD is in the past."}
    — existing hold_failed dispatch handles this correctly (3 alt dates offered)
  marina_extractor: special_requests rule tightened — excludes past complaints
    — "any personal context" replaced with "forward-looking preferences only"
  No other logic changed in either file.
```

## Dependency impact
```
Files that import email_poller: none (standalone poller)
Files that import marina_extractor: email_poller.py (via detect_intent_and_fields)
What callers should expect differently:
  create_calendar_hold() may now return ok=False with "is in the past" error
  for dates that previously would have been passed to calendar.js.
  The hold_failed dispatch path already handles this shape — no caller changes needed.
  extract_fields() will no longer return special_requests for complaint-only text.
```

## Regression check block
```
# BRIEF_018 — email_poller.py + marina_extractor.py — three bug fixes
python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src')
import email_poller, marina_extractor
from datetime import date, timedelta
# Fix 1
assert email_poller.MAX_REPLIES_PER_THREAD == 10
assert email_poller.REPLY_WINDOW_SECONDS == 3600
# Fix 2
r = email_poller.create_calendar_hold({'experience': 'sunset', 'date': '2020-01-01', 'guests': 2, 'customer_name': 'T', 'phone': '1'})
assert r['ok'] == False and 'past' in r['error'].lower()
future = (date.today() + timedelta(days=30)).isoformat()
r2 = email_poller.create_calendar_hold({'experience': 'sunset', 'date': future, 'guests': 2, 'customer_name': 'T', 'phone': '1'})
assert 'past' not in (r2.get('error') or '').lower()
# Fix 3
from marina_extractor import extract_fields
r3 = extract_fields('Last time was bad. Book half day for 2 on May 1.')
assert r3.get('special_requests') != 'Last time was bad'
print('email_poller + marina_extractor Brief 018 regression OK')
"
```
