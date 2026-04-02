# BRIEF 012 — email_poller.py — expand structured logging
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Add bm_logger.log() calls at every key event in the main loop
so that all bookings, complaints, off-topic messages, and
missing field requests are recorded in structured JSONL format.
This data feeds the Google Sheets dashboard in Brief 013.
## Context
Currently only hold_created is logged via bm_logger.
Everything else is plain print() calls going to journald only.
The Google Sheets dashboard needs structured data for:
- Every complaint received
- Every off-topic message
- Every booking attempt (success or failure)
- Every missing fields request
- Every hold created (already exists, needs special_requests added)
## File to modify
bluemarlin/src/email_poller.py
## Files to read before making any changes
Read bluemarlin/src/email_poller.py in full before touching anything.
Read bluemarlin/src/bm_logger.py to confirm the log() signature.
## Changes required — add bm_logger.log() calls at these exact points
### CHANGE 1 — off_topic_received
Current code at the out_of_scope/off_topic branch (around line 445):
  log(f"Out-of-scope -> sent SAFE reply to: {from_email}")
Add this line immediately after that log() call:
  bm_logger.log(
      "off_topic_received",
      email=from_email,
      subject=subj,
      body_snippet=body[:200]
  )
### CHANGE 2 — complaint_received
Current code at the complaint branch (around line 452):
  log(f"Complaint -> sent empathetic reply to: {from_email}")
Add this line immediately after that log() call:
  bm_logger.log(
      "complaint_received",
      email=from_email,
      subject=subj,
      body_snippet=body[:200]
  )
### CHANGE 3 — missing_fields_requested
Current code after the ask smtp_send call (around line 480):
  smtp_send(from_email, "Re: " + subj, ask, ...)
  log(f"Booking intent -> requested missing fields ...")
Add this line immediately after that log() call:
  bm_logger.log(
      "missing_fields_requested",
      email=from_email,
      subject=subj,
      missing=missing,
      fields_so_far=list(merged.keys())
  )
### CHANGE 4 — booking_attempted
Find the line that calls create_calendar_hold(fields_now).
Add this line immediately BEFORE that call:
  bm_logger.log(
      "booking_attempted",
      email=from_email,
      subject=subj,
      experience=fields_now.get("experience"),
      date=fields_now.get("date"),
      guests=fields_now.get("guests"),
      customer_name=fields_now.get("customer_name"),
      phone=fields_now.get("phone"),
      special_requests=fields_now.get("special_requests")
  )
### CHANGE 5 — hold_created (update existing log call)
Find the existing bm_logger.log("hold_created", ...) call.
It currently logs: event_id, payment_id, email, subject.
Replace it with:
  bm_logger.log(
      "hold_created",
      email=from_email,
      subject=subj,
      event_id=th["flags"].get("event_id"),
      html_link=th["flags"].get("event_link"),
      payment_id=th["flags"].get("payment_id"),
      payment_link=th["flags"].get("payment_link"),
      experience=fields_now.get("experience"),
      date=fields_now.get("date"),
      guests=fields_now.get("guests"),
      customer_name=fields_now.get("customer_name"),
      phone=fields_now.get("phone"),
      special_requests=fields_now.get("special_requests")
  )
### CHANGE 6 — hold_failed
Find the block that handles res.get("ok") == False after
create_calendar_hold(). It currently calls log() with the error.
Add this line immediately after that log() call:
  bm_logger.log(
      "hold_failed",
      email=from_email,
      subject=subj,
      error=res.get("error"),
      experience=fields_now.get("experience"),
      date=fields_now.get("date"),
      guests=fields_now.get("guests")
  )
### CHANGE 7 — file header update
Update the file header at the top:
  # LAST MODIFIED: Brief 012
## Constraints
- Do not change any existing logic
- Do not change any function signatures
- Do not change any reply messages
- Do not change the existing local log() function
- Only add bm_logger.log() calls — nothing else
- body[:200] is the correct slice for body_snippet —
  never log the full body to avoid storing sensitive data
- Do not touch any other file
## Test commands
Run all tests from the project root directory.
Report exact output of each test.
Note: Tests 2-6 make live API calls and send real emails.
Run them only if ANTHROPIC_API_KEY is set in the environment.
# Test 1 — imports cleanly
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
print('IMPORT OK')
"
# Test 2 — bm_logger calls present in source for all 6 events
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
events = [
    'off_topic_received',
    'complaint_received',
    'missing_fields_requested',
    'booking_attempted',
    'hold_created',
    'hold_failed'
]
for event in events:
    assert event in content, f'FAIL: {event} not found in source'
    print(f'PASS — {event} found')
print('ALL EVENTS PRESENT')
"
# Test 3 — bm_logger.log call count increased
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
count = content.count('bm_logger.log(')
print(f'bm_logger.log() call count: {count}')
assert count >= 6, f'FAIL: expected at least 6 calls, found {count}'
print('PASS')
"
# Test 4 — body_snippet uses 200 char slice not full body
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
assert 'body[:200]' in content, 'FAIL: body[:200] not found'
print('PASS — body_snippet correctly sliced')
"
# Test 5 — special_requests present in hold_created log call
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
assert 'special_requests' in content, 'FAIL: special_requests not in file'
assert 'hold_created' in content, 'FAIL: hold_created not in file'
print('PASS — special_requests and hold_created both present in file')
"
## Definition of done
- [ ] email_poller.py modified in bluemarlin/src/
- [ ] File header updated (Brief 012)
- [ ] off_topic_received logged with email, subject, body_snippet
- [ ] complaint_received logged with email, subject, body_snippet
- [ ] missing_fields_requested logged with email, subject, missing, fields_so_far
- [ ] booking_attempted logged before create_calendar_hold()
- [ ] hold_created updated with full field set including special_requests
- [ ] hold_failed logged with email, subject, error, experience, date, guests
- [ ] All tests pass with exact output shown
- [ ] OUTPUT_012.md written to bluemarlin/briefs/
- [ ] OUTPUT_012.md includes SYSTEM_STATE update block
- [ ] OUTPUT_012.md includes dependency impact block
- [ ] OUTPUT_012.md includes regression check block
