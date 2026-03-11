# BRIEF 009 — Marina intelligence improvements
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Fix three issues identified in Brief 008 end-to-end testing:
1. Date normalization too narrow — only handles "today", "tomorrow",
   YYYY-MM-DD. Common formats like "March 15" silently drop the date.
2. Off-topic detection too narrow — keyword list misses complaints,
   flight requests, and most real off-topic messages.
3. No complaint handling path — complaints fall into booking intent
   and get treated as booking inquiries.
## File to modify
bluemarlin/src/email_poller.py
## Files to read before making any changes
Read bluemarlin/src/email_poller.py in full before touching anything.
## Change 1 — normalize_date_to_yyyy_mm_dd (lines 241-255)
### Current behavior
Only handles "today", "tomorrow", and already-normalized YYYY-MM-DD.
Everything else returns "" causing the date to silently drop.
### Required behavior
Handle these additional formats, always in America/Curacao timezone:
- "March 15" or "15 March" -> "2026-03-15"
- "March 15 2026" or "15 March 2026" -> "2026-03-15"
- "15/03/2026" -> "2026-03-15"
- "03/15/2026" -> "2026-03-15"
- "15-03-2026" -> "2026-03-15"
- "march 20" (lowercase) -> current year if month is in future,
  next year if month has passed
### Implementation instructions
Install dateparser library:
  pip install dateparser --break-system-packages
Replace the normalize_date_to_yyyy_mm_dd function body with:
- Keep the "today" and "tomorrow" handling exactly as is
- Keep the YYYY-MM-DD regex check exactly as is
- After those checks, attempt dateparser.parse() with these settings:
  PREFER_DAY_OF_MONTH: first
  PREFER_DATES_FROM: future
  TIMEZONE: America/Curacao
  RETURN_TIME_AS_PERIOD: false
- If dateparser returns a valid date, return strftime("%Y-%m-%d")
- If dateparser returns None, return "" as before
- Wrap dateparser call in try/except — return "" on any exception
Add this import at the top of the function or at module level:
  import dateparser
Do not change the function signature.
Do not change the return type.
## Change 2 — detect_intent_and_fields (lines 178-199)
### Current behavior
Hard keyword list only catches: joke, riddle, funny, meme, weather,
crypto, politics. Everything else falls through to booking/general.
Complaints, flight requests, and abuse are all treated as bookings.
### Required behavior
Replace the narrow keyword regex with a Claude call that classifies
intent. Claude reads the message and returns one of four intents:
  booking   — customer wants to book or enquire about a charter
  complaint — customer is unhappy, wants refund, has a problem
  off_topic — message has nothing to do with boat charters
  general   — unclear but not hostile, treat as potential booking
### Implementation instructions
Replace the hard regex out-of-scope check with a call to
claude_client.complete() using this prompt:
  "You are an intent classifier for BlueMarlin Tours Curaçao.
  Read the customer message below and reply with exactly one word:
  - booking (if they want to book or ask about a charter)
  - complaint (if they are unhappy, want a refund, or have a problem)
  - off_topic (if the message has nothing to do with boat charters)
  - general (if unclear but not hostile)
  Reply with ONLY that one word. No punctuation. No explanation.
  Message:
  {text}"
Parse the response — strip whitespace and lowercase.
If the response is not one of the four valid intents, default to
"general" — never crash on unexpected Claude output.
Keep the existing field extraction call to extract_fields(text)
after intent classification — fields are still needed for booking
and general intents.
Keep the adults+kids merge logic exactly as is.
## Change 3 — intent dispatch block (lines 406-413)
### Current behavior
Two paths only: out_of_scope and booking/general.
No complaint path exists.
### Required behavior
Add a complaint path between out_of_scope and booking/general:
  elif intent == "complaint":
      reply_body = safe_complaint_reply()
      smtp_send(from_email, "Re: " + subj, reply_body,
                in_reply_to=msg.get("Message-ID"),
                references=msg.get("References"))
      log(f"Complaint -> sent empathetic reply to: {from_email}")
Add safe_complaint_reply() function near safe_out_of_scope_reply():
  def safe_complaint_reply():
      return (
          "Hi there,\n\n"
          "Thank you for reaching out, and I'm sorry to hear you've "
          "had a frustrating experience.\n\n"
          "I've flagged your message and our team will follow up with "
          "you directly as soon as possible.\n\n"
          "If your concern is about an upcoming or recent booking, "
          "please reply with your booking details and we'll prioritize it.\n\n"
          "Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
      )
Do not change the out_of_scope path.
Do not change the booking/general path.
Do not change any other part of the main loop.
## Change 4 — one visible bug fix
Line 511 leaks internal error details to the customer:
  f"(Internal note: {err})\n\n"
Replace this line with nothing — remove it entirely.
Internal errors must never be sent to customers.
## File header update
Update the file header at the top:
  # LAST MODIFIED: Brief 009
## Constraints
- Do not change any function signatures
- Do not change REQUIRED_FIELDS
- Do not change the booking/general intent path logic
- Do not change create_calendar_hold()
- Do not change safe_out_of_scope_reply()
- Do not touch any other file
- dateparser must be wrapped in try/except — never crash on bad input
- Claude intent classifier must default to "general" on bad output —
  never crash on unexpected response
## Test commands
Run all tests from the project root directory.
Report exact output of each test.
# Test 1 — imports cleanly
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
print('IMPORT OK')
"
# Test 2 — date normalization: YYYY-MM-DD passthrough
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
assert email_poller.normalize_date_to_yyyy_mm_dd('2026-03-20') == '2026-03-20', 'FAIL'
print('PASS — YYYY-MM-DD passthrough')
"
# Test 3 — date normalization: today and tomorrow
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
r1 = email_poller.normalize_date_to_yyyy_mm_dd('today')
r2 = email_poller.normalize_date_to_yyyy_mm_dd('tomorrow')
assert r1 and len(r1) == 10, f'FAIL today: {r1}'
assert r2 and len(r2) == 10, f'FAIL tomorrow: {r2}'
print('PASS — today:', r1, 'tomorrow:', r2)
"
# Test 4 — date normalization: natural language
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
r = email_poller.normalize_date_to_yyyy_mm_dd('March 20')
print('March 20 ->', r)
assert r and len(r) == 10, f'FAIL: got {r!r}'
assert r.endswith('-03-20'), f'FAIL: wrong month/day: {r}'
print('PASS')
"
# Test 5 — date normalization: returns empty on garbage
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
r = email_poller.normalize_date_to_yyyy_mm_dd('asdfghjkl')
assert r == '', f'FAIL: expected empty, got {r!r}'
print('PASS — garbage returns empty string')
"
# Test 6 — intent classifier: booking intent
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
intent, fields = email_poller.detect_intent_and_fields(
    'Hi I want to book the sunset cruise for 2 people on March 20'
)
print('Intent:', intent, 'Fields:', fields)
assert intent in ('booking', 'general'), f'FAIL: expected booking or general, got {intent}'
print('PASS')
"
# Test 7 — intent classifier: off_topic intent
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
intent, fields = email_poller.detect_intent_and_fields(
    'Hi can you help me book a flight to Amsterdam?'
)
print('Intent:', intent)
assert intent == 'off_topic', f'FAIL: expected off_topic, got {intent}'
print('PASS')
"
# Test 8 — intent classifier: complaint intent
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
intent, fields = email_poller.detect_intent_and_fields(
    'Your service is terrible and I want a refund. This is outrageous.'
)
print('Intent:', intent)
assert intent == 'complaint', f'FAIL: expected complaint, got {intent}'
print('PASS')
"
# Test 9 — intent classifier: handles bad Claude output gracefully
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
# Simulate by passing empty string — should not crash
intent, fields = email_poller.detect_intent_and_fields('')
print('Empty input intent:', intent)
assert intent in ('booking', 'general', 'off_topic', 'complaint'), f'FAIL: invalid intent {intent}'
print('PASS — no crash on empty input')
"
# Test 10 — internal note line removed from failure reply
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
assert 'Internal note:' not in content, 'FAIL: internal note still present'
print('PASS — internal note removed')
"
# Test 11 — safe_complaint_reply exists and returns a string
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
r = email_poller.safe_complaint_reply()
assert isinstance(r, str), 'FAIL: not a string'
assert len(r) > 0, 'FAIL: empty string'
assert 'Marina' in r, 'FAIL: Marina signature missing'
print('PASS — complaint reply:', r[:60])
"
## Definition of done
- [ ] email_poller.py modified in bluemarlin/src/
- [ ] File header updated (Brief 009)
- [ ] dateparser installed on VPS
- [ ] normalize_date_to_yyyy_mm_dd handles natural language dates
- [ ] detect_intent_and_fields uses Claude for intent classification
- [ ] safe_complaint_reply() added
- [ ] complaint intent path added to main loop
- [ ] Internal note line removed from failure reply
- [ ] All 11 tests pass with exact output shown
- [ ] OUTPUT_009.md written to bluemarlin/briefs/
- [ ] OUTPUT_009.md includes SYSTEM_STATE update block
- [ ] OUTPUT_009.md includes dependency impact block
- [ ] OUTPUT_009.md includes regression check block
