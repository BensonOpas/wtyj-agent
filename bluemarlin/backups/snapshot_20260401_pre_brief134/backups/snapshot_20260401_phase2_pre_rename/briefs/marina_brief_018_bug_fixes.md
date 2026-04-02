# BRIEF 018 — Three bug fixes
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Fix three bugs found during live testing:
1. Anti-loop guard fires too early on legitimate multi-turn bookings
2. Past dates are not caught — Marina creates holds for dates already passed
3. Complaint context extracted as special_requests instead of being
   left for the intent classifier
## Files to modify
- bluemarlin/src/email_poller.py
- bluemarlin/src/marina_extractor.py
## Files to read before making any changes
Read both files in full before touching anything.
---
## Fix 1 — Anti-loop constants (email_poller.py)
### Current values (around line 54)
MAX_REPLIES_PER_THREAD = 3
REPLY_WINDOW_SECONDS = 10 * 60
### Replace with
MAX_REPLIES_PER_THREAD = 10
REPLY_WINDOW_SECONDS = 60 * 60
### Why
A legitimate multi-turn booking requires:
- First reply: ask for missing fields
- Second reply: ask for name/phone
- Third reply: confirm hold
That is already 3 exchanges. Edge cases with rescheduling,
clarifications, or slow customers can easily hit 5-6.
10 replies per hour is the correct threshold for a real
booking conversation.
---
## Fix 2 — Past date guard (email_poller.py)
### Where to add
Inside create_calendar_hold(), after this existing block:
  if not date_iso:
      return {"ok": False, "error": "Date not recognized..."}
### Add immediately after that block
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
### Why
normalize_date_to_yyyy_mm_dd() correctly parses dates but does
not validate them against today. A customer sending "March 1"
in April would get a hold created for a past date.
The guard returns the same error dict shape as other failures
so the existing hold_failed path handles it correctly —
Marina will reply with 3 alternative dates.
### Important
The import `from datetime import date as _date` must use
the alias `_date` to avoid shadowing the `date` variable
already used later in the booking flow
(line: `date = normalize_date_to_yyyy_mm_dd(...)`).
Check the file carefully before adding the import.
If `datetime` is already imported at the top of the file,
do not add a duplicate import — just use `datetime.date`
with the alias inside the function instead.
---
## Fix 3 — special_requests prompt (marina_extractor.py)
### Current rule in extract_fields() prompt
- For special_requests: capture any personal context,
  dietary restrictions, accessibility needs, allergies,
  celebrations, or preferences verbatim. If none are
  mentioned, omit the field entirely.
### Replace the special_requests rule with
- For special_requests: capture ONLY forward-looking personal
  preferences for the upcoming trip — dietary restrictions,
  allergies, accessibility needs, celebrations, drink
  preferences, or specific requests for the day.
  Do NOT capture complaints about past experiences,
  negative feedback, or anything referring to a previous trip.
  Those are complaints, not special requests.
  If no forward-looking preferences are mentioned, omit
  the field entirely.
### Also update the allowed keys annotation for special_requests
Change:
  - special_requests (dietary needs, allergies, accessibility
    requirements, celebrations, drink preferences, or any
    other personal notes — capture verbatim as a single string)
To:
  - special_requests (forward-looking preferences for the
    upcoming trip only: dietary needs, allergies, accessibility
    requirements, celebrations, drink preferences — capture
    verbatim. Exclude complaints about past experiences.)
### Why
"Last time the music was too loud" was being captured as a
special_request because the prompt said "any personal context."
The intent classifier correctly identifies complaints — but
marina_extractor was also grabbing the text and storing it
as a booking preference. The fix tightens the extraction rule
so only forward-looking preferences are captured.
---
## File header updates
email_poller.py: LAST MODIFIED: Brief 018
marina_extractor.py: LAST MODIFIED: Brief 018
## Constraints
- Do not change any logic outside the three specific fixes
- Do not change the intent classifier
- Do not change any reply functions
- Do not change the booking flow
- Do not change REQUIRED_FIELDS
- Past date guard must use alias _date to avoid variable shadowing
- Do not add duplicate imports
---
## Test commands
# Test 1 — imports cleanly
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
import marina_extractor
print('IMPORT OK')
"
# Test 2 — anti-loop constants updated
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
assert 'MAX_REPLIES_PER_THREAD = 10' in content, 'FAIL: MAX_REPLIES_PER_THREAD not updated'
assert 'REPLY_WINDOW_SECONDS = 60 * 60' in content, 'FAIL: REPLY_WINDOW_SECONDS not updated'
print('PASS — anti-loop constants updated')
"
# Test 3 — past date guard present
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
assert 'is in the past' in content, 'FAIL: past date guard missing'
assert '_date' in content, 'FAIL: _date alias missing'
print('PASS — past date guard present')
"
# Test 4 — past date actually rejected
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
result = email_poller.create_calendar_hold({
    'experience': 'sunset signature cruise',
    'date': '2020-01-01',
    'guests': 2,
    'customer_name': 'Test',
    'phone': '+5999000000'
})
print('Result:', result)
assert result.get('ok') == False, 'FAIL: past date should be rejected'
assert 'past' in result.get('error', '').lower(), 'FAIL: error message should mention past'
print('PASS — past date correctly rejected')
"
# Test 5 — complaint not extracted as special_requests
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
from marina_extractor import extract_fields
result = extract_fields(
    'Last time the music was too loud, not great. '
    'I want to book the half day charter for 4 people on April 10.'
)
print('Extracted fields:', result)
assert result.get('special_requests') != 'Last time the music was too loud, not great', \
    'FAIL: complaint extracted as special_requests'
print('PASS — complaint not extracted as special_requests')
"
# Test 6 — real special_requests still captured
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
from marina_extractor import extract_fields
result = extract_fields(
    'I want to book the sunset cruise. My wife has a shellfish allergy.'
)
print('Extracted fields:', result)
assert 'special_requests' in result, 'FAIL: real special_request not captured'
print('PASS — real special_request captured:', result.get('special_requests'))
"
# Test 7 — future date still accepted (no false positive)
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
from datetime import date, timedelta
future = (date.today() + timedelta(days=30)).isoformat()
result = email_poller.create_calendar_hold({
    'experience': 'sunset signature cruise',
    'date': future,
    'guests': 2,
    'customer_name': 'Test',
    'phone': '+5999000000'
})
print('Future date result ok:', result.get('ok'))
# ok may be False due to calendar API in test env — just check it is NOT the past error
assert 'past' not in (result.get('error') or '').lower(), \
    'FAIL: future date incorrectly flagged as past'
print('PASS — future date not rejected by past date guard')
"
---
## Definition of done
- [ ] email_poller.py modified — Brief 018
- [ ] marina_extractor.py modified — Brief 018
- [ ] MAX_REPLIES_PER_THREAD = 10
- [ ] REPLY_WINDOW_SECONDS = 60 * 60
- [ ] Past date guard added to create_calendar_hold()
- [ ] _date alias used — no variable shadowing
- [ ] special_requests prompt tightened — excludes past complaints
- [ ] All 7 tests pass
- [ ] OUTPUT_018.md written to bluemarlin/briefs/
- [ ] OUTPUT_018.md includes SYSTEM_STATE update block
- [ ] OUTPUT_018.md includes regression check block
