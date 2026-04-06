# BRIEF 019 — Ambiguous date confirmation
# Read CODEX_CONTEXT.md before executing this brief
## Objective
When a customer provides a date without an explicit year (e.g. "January 1",
"March 20", "next Friday"), Marina must ask for confirmation before
proceeding. She must never silently assume a year and create a hold
without the customer confirming the date.
## Context
Currently normalize_date_to_yyyy_mm_dd() uses dateparser with
PREFER_DATES_FROM: future — it silently resolves "January 1" to
2027-01-01 without asking the customer. A customer saying "January 1"
almost certainly means the next upcoming one but Marina should confirm
before booking. This was caught in live testing.
## File to modify
bluemarlin/src/email_poller.py
## Files to read before making any changes
Read bluemarlin/src/email_poller.py in full before touching anything.
---
## Change 1 — Add date ambiguity helper function
Add this function near normalize_date_to_yyyy_mm_dd():
def is_date_ambiguous(date_val: str) -> bool:
    """
    Returns True if the date string does not contain an explicit 4-digit year.
    Examples:
      "January 1"       -> True  (no year)
      "March 20"        -> True  (no year)
      "next Friday"     -> True  (no year)
      "tomorrow"        -> False (relative, unambiguous)
      "today"           -> False (relative, unambiguous)
      "2026-04-15"      -> False (explicit year)
      "15/04/2026"      -> False (explicit year)
      "April 15 2026"   -> False (explicit year)
      "15 April 2026"   -> False (explicit year)
    """
    if not date_val:
        return False
    d = date_val.strip().lower()
    # Relative dates are unambiguous
    if d in ("today", "tomorrow"):
        return False
    # If a 4-digit year is present anywhere, it is unambiguous
    if re.search(r'\b(20\d{2})\b', date_val):
        return False
    return True
---
## Change 2 — Add date confirmation reply function
Add near the other safe reply functions:
def safe_date_confirmation_reply(resolved_date: str, original: str) -> str:
    from datetime import datetime
    try:
        dt = datetime.strptime(resolved_date, "%Y-%m-%d")
        friendly = dt.strftime("%B %d, %Y")
    except Exception:
        friendly = resolved_date
    return (
        f"Hi there,\n\n"
        f"Just to confirm — when you said \"{original}\", "
        f"did you mean {friendly}?\n\n"
        f"Please reply with Yes to confirm, or send the exact date "
        f"(e.g. 2026-04-15) if you meant a different date.\n\n"
        f"Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
    )
---
## Change 3 — Add date confirmation handler function
Add near the other helper functions:
def is_date_confirmation_yes(text: str) -> bool:
    """
    Returns True if the customer's message is a confirmation of the date.
    Handles: yes, yeah, yep, correct, confirmed, sure, ok, okay,
    si, ja, yep, affirmative — case insensitive.
    """
    t = (text or "").strip().lower()
    confirm_words = {
        "yes", "yeah", "yep", "yup", "correct", "confirmed",
        "sure", "ok", "okay", "si", "ja", "affirmative",
        "that's right", "thats right", "right", "exactly"
    }
    # Short message that is just a confirmation word
    if t in confirm_words:
        return True
    # Message starts with a confirmation word
    for word in confirm_words:
        if t.startswith(word + " ") or t.startswith(word + ","):
            return True
    return False
---
## Change 4 — Update booking dispatch in main loop
### Where to insert
Immediately after this line in the main loop:
  intents, fields = detect_intent_and_fields(body)
And before:
  # Merge fields (union only)
  merged = dict(th.get("fields", {}))
### Insert this block
  # --- Date confirmation intercept ---
  th.setdefault("flags", {})
  if th["flags"].get("awaiting_date_confirmation"):
      pending_date = th["flags"].get("pending_date", "")
      pending_original = th["flags"].get("pending_date_original", "")
      if is_date_confirmation_yes(body):
          # Customer confirmed — lock the date and clear the flag
          th["flags"]["awaiting_date_confirmation"] = False
          if "fields" not in th:
              th["fields"] = {}
          th["fields"]["date"] = pending_date
          # Also merge any new fields from this message
          new_fields = fields or {}
          th["fields"].update(
              {k: v for k, v in new_fields.items()
               if v is not None and v != "" and k != "date"}
          )
          log(f"Date confirmed: {pending_date}")
          # Fall through to normal booking flow with confirmed date
      else:
          # Customer did not confirm — check if they sent a new date
          new_date = fields.get("date")
          if new_date:
              resolved = normalize_date_to_yyyy_mm_dd(new_date)
              if resolved:
                  if is_date_ambiguous(new_date):
                      # Still ambiguous — ask again with new date
                      th["flags"]["pending_date"] = resolved
                      th["flags"]["pending_date_original"] = new_date
                      reply_body = safe_date_confirmation_reply(
                          resolved, new_date)
                      smtp_send(from_email, "Re: " + subj, reply_body,
                                in_reply_to=msg.get("Message-ID"),
                                references=msg.get("References"))
                      log(f"Date re-asked (still ambiguous): {resolved}")
                      th["last_customer_hash"] = customer_hash
                      th["reply_times"].append(now)
                      threads[thread_key] = th
                      im.uid("store", uid, "+FLAGS", r"(\Seen)")
                      save_json(THREAD_STATE_PATH, state)
                      continue
                  else:
                      # Explicit year provided — use it directly
                      th["flags"]["awaiting_date_confirmation"] = False
                      th["fields"]["date"] = resolved
                      log(f"Date updated with explicit year: {resolved}")
                      # Fall through to normal booking flow
              else:
                  # Could not parse new date — ask again
                  reply_body = safe_date_confirmation_reply(
                      pending_date, pending_original)
                  smtp_send(from_email, "Re: " + subj, reply_body,
                            in_reply_to=msg.get("Message-ID"),
                            references=msg.get("References"))
                  log(f"Date confirmation re-asked (unparseable): {pending_date}")
                  th["last_customer_hash"] = customer_hash
                  th["reply_times"].append(now)
                  threads[thread_key] = th
                  im.uid("store", uid, "+FLAGS", r"(\Seen)")
                  save_json(THREAD_STATE_PATH, state)
                  continue
          else:
              # No date in message — ask again
              reply_body = safe_date_confirmation_reply(
                  pending_date, pending_original)
              smtp_send(from_email, "Re: " + subj, reply_body,
                        in_reply_to=msg.get("Message-ID"),
                        references=msg.get("References"))
              log(f"Date confirmation re-asked (no date in reply): {pending_date}")
              th["last_customer_hash"] = customer_hash
              th["reply_times"].append(now)
              threads[thread_key] = th
              im.uid("store", uid, "+FLAGS", r"(\Seen)")
              save_json(THREAD_STATE_PATH, state)
              continue
### Where to insert the ambiguity check
Inside the booking dispatch block, immediately after:
  if "booking" in intents:
      missing = [f for f in REQUIRED_FIELDS if f not in merged]
And before the missing fields check, add:
      # --- Ambiguous date check ---
      raw_date = fields.get("date") or merged.get("date", "")
      resolved_date = normalize_date_to_yyyy_mm_dd(raw_date)
      if (raw_date
              and resolved_date
              and is_date_ambiguous(raw_date)
              and not th["flags"].get("awaiting_date_confirmation")):
          # Date is ambiguous — ask for confirmation before proceeding
          th["flags"]["awaiting_date_confirmation"] = True
          th["flags"]["pending_date"] = resolved_date
          th["flags"]["pending_date_original"] = raw_date
          reply_body = safe_date_confirmation_reply(resolved_date, raw_date)
          smtp_send(from_email, "Re: " + subj, reply_body,
                    in_reply_to=msg.get("Message-ID"),
                    references=msg.get("References"))
          log(f"Ambiguous date detected: '{raw_date}' -> asking confirmation for {resolved_date}")
          bm_logger.log("date_confirmation_requested", email=from_email,
                        subject=subj, raw_date=raw_date,
                        resolved_date=resolved_date)
          sheets_writer.log_event("date_confirmation_requested", {
              "email": from_email,
              "subject": subj,
              "raw_date": raw_date,
              "resolved_date": resolved_date,
          })
          th["last_customer_hash"] = customer_hash
          th["reply_times"].append(now)
          threads[thread_key] = th
          im.uid("store", uid, "+FLAGS", r"(\Seen)")
          save_json(THREAD_STATE_PATH, state)
          continue
      # --- end ambiguous date check ---
---
## Change 5 — Thread state default
Find the thread state initialization block:
  th = threads.get(thread_key, {
      "fields": {},
      "last_customer_hash": "",
      "reply_times": []
  })
Replace with:
  th = threads.get(thread_key, {
      "fields": {},
      "flags": {},
      "last_customer_hash": "",
      "reply_times": []
  })
---
## File header update
  # LAST MODIFIED: Brief 019
## Constraints
- Do not change normalize_date_to_yyyy_mm_dd()
- Do not change the intent classifier
- Do not change the required fields check logic
- Do not change bm_logger or sheets_writer call sites
- Do not change any existing reply functions
- All new functions must never raise exceptions
- The date confirmation intercept must run BEFORE field merging
- The ambiguity check must run BEFORE the missing fields check
- Both checks must use continue to exit the loop cleanly
- Thread state must be saved before every continue
- The date confirmation intercept (Change 4 first block) sits at the same indentation level as the existing "intents, fields = detect_intent_and_fields(body)" line — inside the for uid in uids: loop, inside the else: block of the anti-loop guard
- The ambiguity check (Change 4 second block) sits inside "if 'booking' in intents:" and immediately before "missing = [f for f in REQUIRED_FIELDS if f not in merged]" — it must be indented one level deeper than the booking intent check
---
## Test commands
# Test 1 — imports cleanly
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
print('IMPORT OK')
"
# Test 2 — is_date_ambiguous() correct results
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
assert email_poller.is_date_ambiguous('January 1') == True
assert email_poller.is_date_ambiguous('March 20') == True
assert email_poller.is_date_ambiguous('next Friday') == True
assert email_poller.is_date_ambiguous('today') == False
assert email_poller.is_date_ambiguous('tomorrow') == False
assert email_poller.is_date_ambiguous('2026-04-15') == False
assert email_poller.is_date_ambiguous('April 15 2026') == False
assert email_poller.is_date_ambiguous('15/04/2026') == False
print('PASS — is_date_ambiguous() all cases correct')
"
# Test 3 — is_date_confirmation_yes() correct results
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
assert email_poller.is_date_confirmation_yes('yes') == True
assert email_poller.is_date_confirmation_yes('Yes') == True
assert email_poller.is_date_confirmation_yes('yeah') == True
assert email_poller.is_date_confirmation_yes('si') == True
assert email_poller.is_date_confirmation_yes('ja') == True
assert email_poller.is_date_confirmation_yes('no') == False
assert email_poller.is_date_confirmation_yes('actually March 20 2026') == False
print('PASS — is_date_confirmation_yes() all cases correct')
"
# Test 4 — safe_date_confirmation_reply() returns valid string
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
r = email_poller.safe_date_confirmation_reply('2027-01-01', 'January 1')
print(r)
assert 'January 01, 2027' in r, 'FAIL: friendly date missing'
assert 'January 1' in r, 'FAIL: original date missing'
assert 'Marina' in r, 'FAIL: signature missing'
print('PASS — safe_date_confirmation_reply() valid')
"
# Test 5 — is_date_ambiguous present in source
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
assert 'is_date_ambiguous' in content
assert 'awaiting_date_confirmation' in content
assert 'pending_date' in content
assert 'is_date_confirmation_yes' in content
print('PASS — all new symbols present in source')
"
## Definition of done
- [ ] email_poller.py modified — Brief 019
- [ ] is_date_ambiguous() added
- [ ] safe_date_confirmation_reply() added
- [ ] is_date_confirmation_yes() added
- [ ] Date confirmation intercept added before field merging
- [ ] Ambiguity check added inside booking dispatch before missing fields check
- [ ] Thread state default includes flags: {}
- [ ] All 5 tests pass
- [ ] OUTPUT_019.md written to bluemarlin/briefs/
- [ ] OUTPUT_019.md includes SYSTEM_STATE update block
- [ ] OUTPUT_019.md includes regression check block
