# BRIEF 016 — Multi-label intent classification
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Replace the single-intent classifier in detect_intent_and_fields()
with a multi-label classifier that returns a list of intents.
Add 3 new intent labels: inquiry, cancellation, reschedule, social.
Remove the generic "general" label.
Update the dispatch block to handle multiple intents per message.
## Context
Currently detect_intent_and_fields() returns one intent string.
A message like "Love you guys! Can I book the sunset cruise?"
returns only "booking" — the social tone is ignored.
A message like "How much does the sunset cruise cost?" returns
"general" and Marina asks for booking fields — wrong response.
This brief fixes both problems.
## New intent label set
booking      — wants to book or is mid-booking process
inquiry      — pre-sales question: price, availability, what's included
cancellation — wants to cancel an existing booking
reschedule   — wants to change date/time of existing booking
complaint    — unhappy, wants refund, has a problem
social       — friendly chat, compliment, joke, banter about BlueMarlin
off_topic    — nothing to do with boat charters at all
Remove: general
## File to modify
bluemarlin/src/email_poller.py
## Files to read before making any changes
Read bluemarlin/src/email_poller.py in full before touching anything.
## Change 1 — detect_intent_and_fields()
### New function signature
def detect_intent_and_fields(text: str) -> tuple[list[str], dict]:
### New VALID_INTENTS set
VALID_INTENTS = {
    "booking", "inquiry", "cancellation",
    "reschedule", "complaint", "social", "off_topic"
}
### New prompt
Replace the entire prompt with:
  "You are an intent classifier for BlueMarlin Tours Curaçao.\n"
  "Read the customer message below and identify ALL intents present.\n"
  "A message can have more than one intent.\n\n"
  "Available intents:\n"
  "- booking (wants to book or is mid-booking process)\n"
  "- inquiry (asking about price, availability, or what's included)\n"
  "- cancellation (wants to cancel an existing booking)\n"
  "- reschedule (wants to change date or time of existing booking)\n"
  "- complaint (unhappy, wants refund, has a problem)\n"
  "- social (friendly chat, compliment, joke, or banter about BlueMarlin)\n"
  "- off_topic (nothing to do with boat charters at all)\n\n"
  "Reply with ONLY a JSON array of matching intent strings.\n"
  "Examples:\n"
  '  ["booking"]\n'
  '  ["social", "booking"]\n'
  '  ["complaint", "reschedule"]\n'
  '  ["inquiry"]\n'
  '  ["off_topic"]\n'
  "No explanation. No extra text. Only the JSON array.\n\n"
  "Message:\n"
  f"{text}"
### New response parsing
Replace the single-word parse with:
  try:
      raw = claude_client.complete(prompt) or "[]"
      raw = raw.strip()
      # Strip markdown code fences if present
      if raw.startswith("```"):
          raw = raw.split("```")[1]
          if raw.startswith("json"):
              raw = raw[4:]
      parsed = json.loads(raw)
      if not isinstance(parsed, list):
          raise ValueError("not a list")
      intents = [i.strip().lower() for i in parsed
                 if isinstance(i, str) and i.strip().lower() in VALID_INTENTS]
      if not intents:
          intents = ["inquiry"]
  except Exception:
      intents = ["inquiry"]
Default fallback is "inquiry" not "general" — safer than booking.
### Return type change
Return (intents, fields) where intents is a list of strings.
Keep the adults+kids merge logic exactly as is.
Keep the extract_fields() call exactly as is.
### Add json import
Add import json at the top of the file if not already present.
Check first — do not add a duplicate import.
## Change 2 — update dispatch block (around line 433)
### Update the intents unpacking line
Change:
  intent, fields = detect_intent_and_fields(body)
To:
  intents, fields = detect_intent_and_fields(body)
### Update the log line
Change:
  log(f"Merged fields: {merged}")
To:
  log(f"Intents: {intents} | Merged fields: {merged}")
### Replace the entire intent dispatch block
Replace from the first if intent in ("out_of_scope", "off_topic"):
through to the end of the elif intent in ("booking", "general"): block
with this new multi-label dispatch:
  # --- Multi-label intent dispatch ---
  # off_topic: only fire if SOLE intent is off_topic
  if intents == ["off_topic"]:
      reply_body = safe_out_of_scope_reply()
      smtp_send(from_email, "Re: " + subj, reply_body,
                in_reply_to=msg.get("Message-ID"),
                references=msg.get("References"))
      log(f"Off-topic -> sent SAFE reply to: {from_email}")
      bm_logger.log("off_topic_received", email=from_email,
                    subject=subj, body_snippet=body[:200])
      sheets_writer.log_event("off_topic_received",
                              {"email": from_email, "subject": subj})
  else:
      # Handle each non-off_topic intent present
      # social: acknowledge warmly before anything else
      if "social" in intents and not any(
              i in intents for i in
              ("booking", "inquiry", "cancellation",
               "reschedule", "complaint")):
          # Pure social — no action needed, just warm reply
          reply_body = safe_social_reply()
          smtp_send(from_email, "Re: " + subj, reply_body,
                    in_reply_to=msg.get("Message-ID"),
                    references=msg.get("References"))
          log(f"Social -> sent warm reply to: {from_email}")
          bm_logger.log("social_received", email=from_email,
                        subject=subj, body_snippet=body[:200])
          sheets_writer.log_event("social_received",
                                  {"email": from_email, "subject": subj})
      # complaint: log and reply (can combine with other intents)
      if "complaint" in intents:
          reply_body = safe_complaint_reply()
          smtp_send(from_email, "Re: " + subj, reply_body,
                    in_reply_to=msg.get("Message-ID"),
                    references=msg.get("References"))
          log(f"Complaint -> sent empathetic reply to: {from_email}")
          bm_logger.log("complaint_received", email=from_email,
                        subject=subj, body_snippet=body[:200])
          sheets_writer.log_complaint({"email": from_email,
                                       "subject": subj,
                                       "body_snippet": body[:200]})
      # cancellation or reschedule: flag for human, send acknowledgement
      if "cancellation" in intents or "reschedule" in intents:
          action = "cancellation" if "cancellation" in intents else "reschedule"
          reply_body = safe_change_request_reply(action)
          smtp_send(from_email, "Re: " + subj, reply_body,
                    in_reply_to=msg.get("Message-ID"),
                    references=msg.get("References"))
          log(f"{action.title()} request -> sent acknowledgement to: {from_email}")
          bm_logger.log(f"{action}_requested", email=from_email,
                        subject=subj, body_snippet=body[:200])
          sheets_writer.log_event(f"{action}_requested",
                                  {"email": from_email, "subject": subj,
                                   "body_snippet": body[:200]})
      # inquiry: answer pre-sales question
      if "inquiry" in intents and "booking" not in intents:
          reply_body = safe_inquiry_reply()
          smtp_send(from_email, "Re: " + subj, reply_body,
                    in_reply_to=msg.get("Message-ID"),
                    references=msg.get("References"))
          log(f"Inquiry -> sent packages reply to: {from_email}")
          bm_logger.log("inquiry_received", email=from_email,
                        subject=subj, body_snippet=body[:200])
          sheets_writer.log_event("inquiry_received",
                                  {"email": from_email, "subject": subj})
      # booking: run the full booking flow (unchanged logic)
      if "booking" in intents:
          # IMPORTANT: Copy the entire existing booking flow here verbatim.
          # This means every line from the current
          # elif intent in ("booking", "general"): block
          # must be pasted inside this if "booking" in intents: block.
          # Do NOT rewrite or simplify any of it.
          # Do NOT change any variable names, logic, or bm_logger calls.
          # Only change: remove the elif condition and indent everything
          # one level deeper under if "booking" in intents:
## Change 3 — add new static reply functions
Add these functions near safe_out_of_scope_reply() and
safe_complaint_reply():
def safe_social_reply():
    return (
        "Hi there!\n\n"
        "Thank you so much — messages like yours make our day! 🌊\n\n"
        "If you'd like to join us on the water, we'd love to have you. "
        "Just let us know which experience interests you, your preferred "
        "date, and how many guests — and we'll get everything set up.\n\n"
        "Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
    )
def safe_inquiry_reply():
    return (
        "Hi there!\n\n"
        "Thanks for reaching out to BlueMarlin Tours Curaçao!\n\n"
        "Here's a quick overview of our experiences:\n\n"
        "🌅 Sunset Signature Cruise — 2.5 hours, departs 17:00\n"
        "   Perfect for couples and small groups. Drinks and sunset views.\n\n"
        "⚓ Half Day Private Charter — 4 hours, departs 09:00\n"
        "   Flexible itinerary. Great for families and private groups.\n\n"
        "🌊 Full Day West Coast Escape — 8 hours, departs 08:00\n"
        "   Full day on the water. Snorkeling, beaches, full experience.\n\n"
        "To check availability and hold your spot, just reply with:\n"
        "- Which experience you're interested in\n"
        "- Your preferred date\n"
        "- Number of guests\n\n"
        "Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
    )
def safe_change_request_reply(action: str):
    action_word = "cancel" if action == "cancellation" else "reschedule"
    return (
        f"Hi there,\n\n"
        f"Thank you for reaching out. I've received your request to "
        f"{action_word} your booking.\n\n"
        f"Our team will review your request and follow up with you "
        f"directly as soon as possible to confirm the changes.\n\n"
        f"If you have any urgent questions, please reply to this email "
        f"with your booking details and preferred alternative "
        f"(if rescheduling).\n\n"
        f"Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
    )
## Change 4 — file header update
  # LAST MODIFIED: Brief 016
## Constraints
- Do not change the booking flow logic at all — only wrap it in
  if "booking" in intents:
- Do not change safe_out_of_scope_reply()
- Do not change safe_complaint_reply()
- Do not change create_calendar_hold()
- Do not change normalize_date_to_yyyy_mm_dd()
- Do not change extract_fields() call or adults+kids merge
- The json import must not be duplicated
- All new reply functions must never raise exceptions
- The intent classifier must default to ["inquiry"] on any failure
## Test commands
# Test 1 — imports cleanly
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
print('IMPORT OK')
"
# Test 2 — returns list not string
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
intents, fields = email_poller.detect_intent_and_fields(
    'I want to book the sunset cruise for 2 people on March 20'
)
print('Intents:', intents, 'Type:', type(intents).__name__)
assert isinstance(intents, list), f'FAIL: expected list, got {type(intents)}'
assert 'booking' in intents, f'FAIL: booking not in {intents}'
print('PASS')
"
# Test 3 — multi-label: social + booking
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
intents, fields = email_poller.detect_intent_and_fields(
    'You guys are amazing! Can I book the sunset cruise for March 25 for 2 people?'
)
print('Intents:', intents)
assert isinstance(intents, list), 'FAIL: not a list'
assert 'booking' in intents, f'FAIL: booking missing from {intents}'
print('PASS — multi-label detected')
"
# Test 4 — inquiry intent
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
intents, fields = email_poller.detect_intent_and_fields(
    'Hi, how much does the half day charter cost?'
)
print('Intents:', intents)
assert isinstance(intents, list), 'FAIL: not a list'
assert 'inquiry' in intents, f'FAIL: inquiry missing from {intents}'
assert 'booking' not in intents, f'FAIL: booking should not be in {intents}'
print('PASS')
"
# Test 5 — cancellation intent
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
intents, fields = email_poller.detect_intent_and_fields(
    'Hi I need to cancel my booking for March 20 please.'
)
print('Intents:', intents)
assert isinstance(intents, list), 'FAIL: not a list'
assert 'cancellation' in intents, f'FAIL: cancellation missing from {intents}'
print('PASS')
"
# Test 6 — off_topic only
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
intents, fields = email_poller.detect_intent_and_fields(
    'Can you help me book a flight to Amsterdam?'
)
print('Intents:', intents)
assert isinstance(intents, list), 'FAIL: not a list'
assert 'off_topic' in intents, f'FAIL: off_topic missing from {intents}'
print('PASS')
"
# Test 7 — complaint intent
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
intents, fields = email_poller.detect_intent_and_fields(
    'Your service is terrible and I want a refund.'
)
print('Intents:', intents)
assert isinstance(intents, list), 'FAIL: not a list'
assert 'complaint' in intents, f'FAIL: complaint missing from {intents}'
print('PASS')
"
# Test 8 — default fallback on empty input
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
intents, fields = email_poller.detect_intent_and_fields('')
print('Empty input intents:', intents)
assert isinstance(intents, list), 'FAIL: not a list'
assert len(intents) > 0, 'FAIL: empty list returned'
print('PASS — no crash on empty input')
"
# Test 9 — new reply functions exist and return strings
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
r1 = email_poller.safe_social_reply()
r2 = email_poller.safe_inquiry_reply()
r3 = email_poller.safe_change_request_reply('cancellation')
r4 = email_poller.safe_change_request_reply('reschedule')
assert all(isinstance(r, str) and len(r) > 0 for r in [r1,r2,r3,r4])
assert 'Marina' in r1 and 'Marina' in r2 and 'Marina' in r3
print('PASS — all reply functions return valid strings')
print('Social:', r1[:50])
print('Inquiry:', r2[:50])
print('Cancel:', r3[:50])
"
# Test 10 — VALID_INTENTS contains all 7 labels
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
# Re-run detect to trigger VALID_INTENTS initialization
intents, _ = email_poller.detect_intent_and_fields('test')
print('PASS — function runs without error')
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
for label in ['booking','inquiry','cancellation','reschedule',
              'complaint','social','off_topic']:
    assert label in content, f'FAIL: {label} not in source'
    print(f'  {label} — found')
print('PASS — all 7 labels present in source')
"
## Definition of done
- [ ] email_poller.py modified in bluemarlin/src/
- [ ] File header updated (Brief 016)
- [ ] json import added if not present (no duplicate)
- [ ] detect_intent_and_fields() returns list not string
- [ ] VALID_INTENTS has all 7 labels
- [ ] Prompt updated for multi-label JSON array output
- [ ] Response parsing handles JSON array with fallback
- [ ] Dispatch block handles all 7 intents
- [ ] Booking flow unchanged, wrapped in if "booking" in intents:
- [ ] safe_social_reply() added
- [ ] safe_inquiry_reply() added
- [ ] safe_change_request_reply(action) added
- [ ] All 10 tests pass with exact output shown
- [ ] OUTPUT_016.md written to bluemarlin/briefs/
- [ ] OUTPUT_016.md includes SYSTEM_STATE update block
- [ ] OUTPUT_016.md includes dependency impact block
- [ ] OUTPUT_016.md includes regression check block
