# BRIEF 020 — Booking intake fixes
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Fix three booking intake problems found during live testing and analysis:
1. Date classification — vague/past/implausible dates handled correctly
2. Experience name matching — unknown experience asks for clarification
3. Guest count — natural language, babies, approximate counts, large groups
## Files to modify
- bluemarlin/src/email_poller.py
- bluemarlin/src/marina_extractor.py
## Files to read before making any changes
Read both files in full before touching anything.
---
## FIX 1 — Date classification (email_poller.py)
### Problem
is_date_ambiguous() fires on ANY date without a year, including
"March 20" which resolves correctly to a future date. This causes
Marina to ask for confirmation on dates that are perfectly clear.
Also: vague inputs like "this weekend", "next month", "Easter",
"Christmas" are passed to dateparser which may or may not resolve
them — Marina never asks for a specific date.
### Replace is_date_ambiguous() entirely with classify_date_input()
Remove is_date_ambiguous() and replace with:
def classify_date_input(date_val: str) -> str:
    """
    Classifies a date string into one of five categories:
      CLEAR_FUTURE      — resolved to a valid future date, proceed normally
      PAST              — resolved to a past date, ask if they meant next occurrence
      IMPLAUSIBLE       — resolved to a date more than 11 months away with no
                          explicit year — likely dateparser pushed it forward
      VAGUE_RESOLVABLE  — relative date that can be calculated from today
                          (next Friday, in two weeks) — confirm the specific date
      VAGUE_NEEDS_INPUT — too vague to resolve (this weekend, next month,
                          Easter, Christmas, summer) — ask for a specific date
    Returns one of the five string constants above.
    """
    from datetime import date as _date, timedelta
    from zoneinfo import ZoneInfo
    import datetime as _datetime
    if not date_val:
        return "VAGUE_NEEDS_INPUT"
    d = date_val.strip().lower()
    tz = ZoneInfo("America/Curacao")
    today = _datetime.datetime.now(tz).date()
    # today/tomorrow — always clear
    if d in ("today", "tomorrow"):
        return "CLEAR_FUTURE"
    # Vague inputs that need a specific date
    VAGUE_PATTERNS = [
        "this weekend", "next weekend", "next month", "this month",
        "next week", "easter", "christmas", "new year", "thanksgiving",
        "summer", "winter", "spring", "autumn", "fall",
        "holiday", "vacation", "soon", "sometime", "flexible",
        "any day", "anytime", "whenever"
    ]
    for pattern in VAGUE_PATTERNS:
        if pattern in d:
            return "VAGUE_NEEDS_INPUT"
    # Try to resolve the date
    resolved_str = normalize_date_to_yyyy_mm_dd(date_val)
    if not resolved_str:
        return "VAGUE_NEEDS_INPUT"
    try:
        resolved = _date.fromisoformat(resolved_str)
    except Exception:
        return "VAGUE_NEEDS_INPUT"
    # Past date
    if resolved < today:
        return "PAST"
    # Check if year was explicitly provided
    has_explicit_year = bool(re.search(r'\b(20\d{2})\b', date_val))
    # If no explicit year and date is more than 11 months away — implausible
    if not has_explicit_year:
        eleven_months = today + timedelta(days=335)
        if resolved > eleven_months:
            return "IMPLAUSIBLE"
    # Resolvable relative dates — "next Friday", "in two weeks"
    RESOLVABLE_PATTERNS = [
        "next friday", "next monday", "next tuesday", "next wednesday",
        "next thursday", "next saturday", "next sunday",
        "in two weeks", "in a week", "in 2 weeks", "in 3 weeks",
        "next friday", "this friday", "this saturday", "this sunday",
        "this monday", "this tuesday", "this wednesday", "this thursday"
    ]
    for pattern in RESOLVABLE_PATTERNS:
        if pattern in d:
            return "VAGUE_RESOLVABLE"
    return "CLEAR_FUTURE"
### Add date reply functions
Add these three functions near safe_date_confirmation_reply():
def safe_date_past_reply(resolved_date: str, original: str) -> str:
    """Fired when date resolved to the past."""
    from datetime import datetime, date as _date, timedelta
    try:
        dt = datetime.strptime(resolved_date, "%Y-%m-%d")
        # Suggest same date next year
        next_year = dt.replace(year=dt.year + 1)
        suggestion = next_year.strftime("%B %d, %Y")
    except Exception:
        suggestion = "a date next year"
    return (
        f"Hi there!\n\n"
        f"It looks like {original} has already passed — "
        f"did you mean {suggestion}, or did you have a different date in mind?\n\n"
        f"Just let me know and I'll check availability right away! 🌊\n\n"
        f"Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
    )
def safe_date_implausible_reply(resolved_date: str, original: str) -> str:
    """Fired when date seems too far in the future."""
    from datetime import datetime
    try:
        dt = datetime.strptime(resolved_date, "%Y-%m-%d")
        friendly = dt.strftime("%B %d, %Y")
    except Exception:
        friendly = resolved_date
    return (
        f"Hi there!\n\n"
        f"Just making sure — are you planning for {friendly}? "
        f"That's quite a bit ahead, so I want to make sure I have "
        f"the right date before holding your spot!\n\n"
        f"If that's correct just say yes and I'll get it sorted. "
        f"Or if you meant a sooner date, just send it over 😊\n\n"
        f"Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
    )
def safe_date_vague_reply(original: str, resolvable_date: str = "") -> str:
    """Fired when date is too vague to use."""
    if resolvable_date:
        # We calculated a date — confirm it
        from datetime import datetime
        try:
            dt = datetime.strptime(resolvable_date, "%Y-%m-%d")
            friendly = dt.strftime("%B %d, %Y")
            return (
                f"Hi there!\n\n"
                f"Just to confirm — are you thinking {friendly}?\n\n"
                f"Say yes and I'll check availability, or send me "
                f"the exact date if you had something else in mind 😊\n\n"
                f"Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
            )
        except Exception:
            pass
    return (
        f"Hi there!\n\n"
        f"I'd love to help you book! Could you give me a specific date? "
        f"For example: April 15, or 2026-04-15.\n\n"
        f"Once I have that I can check availability and get your "
        f"spot held right away 🌊\n\n"
        f"Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
    )
### Update the ambiguous date check block inside booking dispatch
Find the block starting with:
  # --- Ambiguous date check ---
  raw_date = fields.get("date") or merged.get("date", "")
  resolved_date = normalize_date_to_yyyy_mm_dd(raw_date)
  if (raw_date
          and resolved_date
          and is_date_ambiguous(raw_date)
          and not th["flags"].get("awaiting_date_confirmation")):
Replace the entire block through # --- end ambiguous date check ---
with:
      # --- Date classification check ---
      raw_date = fields.get("date") or merged.get("date", "")
      if raw_date and not th["flags"].get("awaiting_date_confirmation"):
          date_class = classify_date_input(raw_date)
          resolved_date = normalize_date_to_yyyy_mm_dd(raw_date)
          if date_class == "PAST":
              reply_body = safe_date_past_reply(resolved_date or "", raw_date)
              smtp_send(from_email, "Re: " + subj, reply_body,
                        in_reply_to=msg.get("Message-ID"),
                        references=msg.get("References"))
              log(f"Past date detected: '{raw_date}' -> asking for correction")
              bm_logger.log("date_past_detected", email=from_email,
                            subject=subj, raw_date=raw_date)
              sheets_writer.log_event("date_past_detected",
                                      {"email": from_email, "subject": subj,
                                       "raw_date": raw_date})
              th["last_customer_hash"] = customer_hash
              th["reply_times"].append(now)
              threads[thread_key] = th
              im.uid("store", uid, "+FLAGS", r"(\Seen)")
              save_json(THREAD_STATE_PATH, state)
              continue
          elif date_class == "IMPLAUSIBLE":
              th["flags"]["awaiting_date_confirmation"] = True
              th["flags"]["pending_date"] = resolved_date
              th["flags"]["pending_date_original"] = raw_date
              reply_body = safe_date_implausible_reply(resolved_date, raw_date)
              smtp_send(from_email, "Re: " + subj, reply_body,
                        in_reply_to=msg.get("Message-ID"),
                        references=msg.get("References"))
              log(f"Implausible date: '{raw_date}' -> {resolved_date}")
              bm_logger.log("date_implausible_detected", email=from_email,
                            subject=subj, raw_date=raw_date,
                            resolved_date=resolved_date)
              sheets_writer.log_event("date_implausible_detected",
                                      {"email": from_email, "subject": subj,
                                       "raw_date": raw_date,
                                       "resolved_date": resolved_date})
              th["last_customer_hash"] = customer_hash
              th["reply_times"].append(now)
              threads[thread_key] = th
              im.uid("store", uid, "+FLAGS", r"(\Seen)")
              save_json(THREAD_STATE_PATH, state)
              continue
          elif date_class in ("VAGUE_NEEDS_INPUT", "VAGUE_RESOLVABLE"):
              th["flags"]["awaiting_date_confirmation"] = True
              th["flags"]["pending_date"] = resolved_date or ""
              th["flags"]["pending_date_original"] = raw_date
              reply_body = safe_date_vague_reply(
                  raw_date,
                  resolved_date if date_class == "VAGUE_RESOLVABLE" else ""
              )
              smtp_send(from_email, "Re: " + subj, reply_body,
                        in_reply_to=msg.get("Message-ID"),
                        references=msg.get("References"))
              log(f"Vague date ({date_class}): '{raw_date}' -> asking for specific date")
              bm_logger.log("date_vague_detected", email=from_email,
                            subject=subj, raw_date=raw_date,
                            classification=date_class)
              sheets_writer.log_event("date_vague_detected",
                                      {"email": from_email, "subject": subj,
                                       "raw_date": raw_date,
                                       "classification": date_class})
              th["last_customer_hash"] = customer_hash
              th["reply_times"].append(now)
              threads[thread_key] = th
              im.uid("store", uid, "+FLAGS", r"(\Seen)")
              save_json(THREAD_STATE_PATH, state)
              continue
          # CLEAR_FUTURE — proceed normally, no action needed
      # --- end date classification check ---
### Also update safe_date_confirmation_reply to not sound robotic
Find safe_date_confirmation_reply() and replace the return string with:
    return (
        f"Hi there!\n\n"
        f"Just making sure — are you thinking {friendly}? "
        f"Say yes and I'll get your spot held right away, or "
        f"send me a different date if that's not right 😊\n\n"
        f"Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
    )
---
## FIX 2 — Experience name matching (email_poller.py)
### Problem
package_key_from_experience() returns "" when the experience name
doesn't match any keyword. When "" is returned, create_calendar_hold()
returns {"ok": False, "error": "Unknown package"}. Marina then fires
the hold_failed path which sends date alternatives — completely wrong.
The missing fields check uses REQUIRED_FIELDS = ["experience", "date",
"guests"] — but experience matching failure is different from experience
being missing. Customer DID provide an experience, it just didn't match.
### Add experience clarity check
Add this function near package_key_from_experience():
def experience_is_clear(exp: str) -> bool:
    """Returns True if experience maps to a known package key."""
    return bool(package_key_from_experience(exp))
### Add experience clarification reply function
def safe_experience_unclear_reply(provided: str) -> str:
    return (
        f"Hi there!\n\n"
        f"Thanks for reaching out! I want to make sure I book "
        f"the right experience for you 😊\n\n"
        f"We have three options:\n\n"
        f"🌅 Sunset Signature Cruise — 2.5 hours, departs 17:00\n"
        f"   Perfect for couples and small groups. Drinks and sunset views.\n\n"
        f"⚓ Half Day Private Charter — 4 hours, departs 09:00\n"
        f"   Flexible itinerary. Great for families and private groups.\n\n"
        f"🌊 Full Day West Coast Escape — 8 hours, departs 08:00\n"
        f"   Full day on the water. Snorkeling, beaches, full experience.\n\n"
        f"Which one sounds right for you?\n\n"
        f"Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
    )
### Add experience check inside booking dispatch
Inside if "booking" in intents:, immediately AFTER the date
classification check block and BEFORE the missing fields check:
      # --- Experience clarity check ---
      provided_experience = merged.get("experience", "")
      if (provided_experience
              and not experience_is_clear(provided_experience)
              and not th["flags"].get("awaiting_experience_clarification")):
          th["flags"]["awaiting_experience_clarification"] = True
          reply_body = safe_experience_unclear_reply(provided_experience)
          smtp_send(from_email, "Re: " + subj, reply_body,
                    in_reply_to=msg.get("Message-ID"),
                    references=msg.get("References"))
          log(f"Experience unclear: '{provided_experience}' -> asking for clarification")
          bm_logger.log("experience_unclear", email=from_email,
                        subject=subj, provided=provided_experience)
          sheets_writer.log_event("experience_unclear",
                                  {"email": from_email, "subject": subj,
                                   "provided": provided_experience})
          th["last_customer_hash"] = customer_hash
          th["reply_times"].append(now)
          threads[thread_key] = th
          im.uid("store", uid, "+FLAGS", r"(\Seen)")
          save_json(THREAD_STATE_PATH, state)
          continue
      # --- end experience clarity check ---
Note: awaiting_experience_clarification flag is cleared automatically
when the customer's next message provides a recognizable experience name
— because merged.get("experience") will update and experience_is_clear()
will return True on the next pass.
---
## FIX 3 — Guest count handling (email_poller.py + marina_extractor.py)
### marina_extractor.py — update guests extraction rules
In the extract_fields() prompt, update the guests/adults/kids section:
Replace:
- guests (total number of people)
- adults (if specified separately)
- kids (if specified separately)
With:
- guests (total number of people — must be an exact integer.
  "Just me" = 1. "Me and my wife" = 2. "A family of 4" = 4.
  "Family of 4 plus a baby/infant/toddler" = 4 — do NOT count
  infants under 2 in the guest total; add them to special_requests
  instead. "Around 10" or "about 10" — do NOT extract guests,
  omit the field so Marina can ask for an exact number.)
- adults (if specified separately as an integer)
- kids (if specified separately as an integer — does not include infants)
Also add to the Rules block:
- For guests: extract ONLY a definite integer. If the customer uses
  approximate language ("around", "about", "roughly", "maybe",
  "approximately") do NOT extract guests — omit it entirely so
  Marina asks for an exact count. If an infant/baby is mentioned
  alongside a guest count, do NOT include the infant in the count —
  add "travelling with an infant" to special_requests instead.
### email_poller.py — add large group detection
Add this constant near REQUIRED_FIELDS:
GROUP_BOOKING_THRESHOLD = 15
Add this function near the other reply functions:
def safe_large_group_reply(guests: int) -> str:
    return (
        f"Hi there!\n\n"
        f"Wow, a group of {guests} — that sounds like an amazing trip! 🎉\n\n"
        f"For groups this size we like to make sure everything is "
        f"set up perfectly for you. One of our team will be in touch "
        f"shortly to discuss the best options and get everything "
        f"arranged.\n\n"
        f"We can't wait to have you all on board!\n\n"
        f"Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
    )
### Add large group check inside booking dispatch
Inside if "booking" in intents:, immediately AFTER the experience
clarity check and BEFORE the missing fields check:
      # --- Large group check ---
      guest_count = merged.get("guests")
      if guest_count is not None:
          try:
              guest_count = int(guest_count)
              if guest_count >= GROUP_BOOKING_THRESHOLD:
                  reply_body = safe_large_group_reply(guest_count)
                  smtp_send(from_email, "Re: " + subj, reply_body,
                            in_reply_to=msg.get("Message-ID"),
                            references=msg.get("References"))
                  log(f"Large group detected: {guest_count} guests -> flagging human")
                  bm_logger.log("large_group_detected", email=from_email,
                                subject=subj, guests=guest_count)
                  sheets_writer.log_complaint({
                      "email": from_email,
                      "subject": subj,
                      "body_snippet": f"Large group booking request: {guest_count} guests"
                  })
                  th["last_customer_hash"] = customer_hash
                  th["reply_times"].append(now)
                  threads[thread_key] = th
                  im.uid("store", uid, "+FLAGS", r"(\Seen)")
                  save_json(THREAD_STATE_PATH, state)
                  continue
          except (ValueError, TypeError):
              pass
      # --- end large group check ---
Note: large group uses sheets_writer.log_complaint() to surface it
in the Complaints tab — this puts it in front of the operator
alongside other items needing human attention.
---
## File header updates
email_poller.py: LAST MODIFIED: Brief 020
marina_extractor.py: LAST MODIFIED: Brief 020
## Constraints
- Remove is_date_ambiguous() entirely — replaced by classify_date_input()
- Do not change normalize_date_to_yyyy_mm_dd()
- Do not change package_key_from_experience() — only add experience_is_clear()
- Do not change the booking flow beyond the three new check blocks
- Do not change bm_logger, sheets_writer, or calendar.js calls
- All new functions must never raise exceptions
- All new check blocks must save thread state before continue
- GROUP_BOOKING_THRESHOLD = 15 not 20 — 15 gives operator earlier warning
- The three check blocks must be in this order inside booking dispatch:
    1. Date classification check
    2. Experience clarity check
    3. Large group check
    4. Missing fields check (existing, unchanged)
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
# Test 2 — classify_date_input() correct results
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
from datetime import date, timedelta
future = (date.today() + timedelta(days=30)).strftime('%B %d')
assert email_poller.classify_date_input('today') == 'CLEAR_FUTURE'
assert email_poller.classify_date_input('tomorrow') == 'CLEAR_FUTURE'
assert email_poller.classify_date_input('2020-01-01') == 'PAST'
assert email_poller.classify_date_input('this weekend') == 'VAGUE_NEEDS_INPUT'
assert email_poller.classify_date_input('next month') == 'VAGUE_NEEDS_INPUT'
assert email_poller.classify_date_input('Easter') == 'VAGUE_NEEDS_INPUT'
assert email_poller.classify_date_input('Christmas') == 'VAGUE_NEEDS_INPUT'
assert email_poller.classify_date_input('next Friday') == 'VAGUE_RESOLVABLE'
assert email_poller.classify_date_input('in two weeks') == 'VAGUE_RESOLVABLE'
# Explicit year — always CLEAR_FUTURE if in future
assert email_poller.classify_date_input('2026-06-15') == 'CLEAR_FUTURE'
print('PASS — classify_date_input() all cases correct')
"
# Test 3 — experience_is_clear() correct results
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
assert email_poller.experience_is_clear('sunset cruise') == True
assert email_poller.experience_is_clear('half day') == True
assert email_poller.experience_is_clear('full day west coast') == True
assert email_poller.experience_is_clear('the big boat') == False
assert email_poller.experience_is_clear('the one with snorkeling') == False
assert email_poller.experience_is_clear('') == False
print('PASS — experience_is_clear() all cases correct')
"
# Test 4 — marina_extractor infant handling
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
from marina_extractor import extract_fields
r = extract_fields('Family of 4 plus a baby on April 20 sunset cruise')
print('Result:', r)
assert r.get('guests') == 4 or str(r.get('guests')) == '4', \
    f'FAIL: expected guests=4, got {r.get(\"guests\")}'
assert 'infant' in str(r.get('special_requests', '')).lower() or \
       'baby' in str(r.get('special_requests', '')).lower(), \
    f'FAIL: infant not in special_requests: {r.get(\"special_requests\")}'
print('PASS — infant not counted in guests, noted in special_requests')
"
# Test 5 — marina_extractor approximate count not extracted
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
from marina_extractor import extract_fields
r = extract_fields('Around 10 people for the full day trip on May 5')
print('Result:', r)
assert r.get('guests') is None or r.get('guests') == '', \
    f'FAIL: approximate count should not be extracted, got {r.get(\"guests\")}'
print('PASS — approximate guest count not extracted')
"
# Test 6 — large group threshold constant present
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
assert email_poller.GROUP_BOOKING_THRESHOLD == 15
print('PASS — GROUP_BOOKING_THRESHOLD = 15')
"
# Test 7 — all new functions exist and return strings
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
r1 = email_poller.safe_date_past_reply('2025-01-01', 'January 1')
r2 = email_poller.safe_date_implausible_reply('2027-06-01', 'next June')
r3 = email_poller.safe_date_vague_reply('this weekend', '')
r4 = email_poller.safe_date_vague_reply('next Friday', '2026-03-13')
r5 = email_poller.safe_experience_unclear_reply('the big boat')
r6 = email_poller.safe_large_group_reply(20)
assert all(isinstance(r, str) and len(r) > 0 for r in [r1,r2,r3,r4,r5,r6])
assert all('Marina' in r for r in [r1,r2,r3,r4,r5,r6])
print('PASS — all new reply functions return valid strings')
"
# Test 8 — new symbols present in source
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
symbols = [
    'classify_date_input', 'experience_is_clear',
    'safe_date_past_reply', 'safe_date_implausible_reply',
    'safe_date_vague_reply', 'safe_experience_unclear_reply',
    'safe_large_group_reply', 'GROUP_BOOKING_THRESHOLD',
    'awaiting_experience_clarification', 'large_group_detected',
    'CLEAR_FUTURE', 'VAGUE_NEEDS_INPUT', 'VAGUE_RESOLVABLE',
    'IMPLAUSIBLE', 'PAST'
]
for s in symbols:
    assert s in content, f'FAIL: {s} not in source'
    print(f'  {s} — found')
print('PASS — all new symbols present in source')
"
---
## Definition of done
- [ ] email_poller.py modified — Brief 020
- [ ] marina_extractor.py modified — Brief 020
- [ ] is_date_ambiguous() removed, classify_date_input() added
- [ ] safe_date_past_reply() added
- [ ] safe_date_implausible_reply() added
- [ ] safe_date_vague_reply() added
- [ ] safe_date_confirmation_reply() tone updated (less robotic)
- [ ] experience_is_clear() added
- [ ] safe_experience_unclear_reply() added
- [ ] GROUP_BOOKING_THRESHOLD = 15 added
- [ ] safe_large_group_reply() added
- [ ] Three check blocks in correct order inside booking dispatch
- [ ] marina_extractor guests rule updated — infants, approximate counts
- [ ] All 8 tests pass
- [ ] OUTPUT_020.md written to bluemarlin/briefs/
- [ ] OUTPUT_020.md includes SYSTEM_STATE update block
- [ ] OUTPUT_020.md includes regression check block
