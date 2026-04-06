# BRIEF 024 — email_poller.py Refactor — Unified Claude Call Integration
**Brief number:** 024
**Status:** Ready to execute
**Files modified:** bluemarlin/src/email_poller.py, bluemarlin/src/marina_agent.py
**Files created:** None
**Depends on:** Brief 001 (claude_client.py), Brief 022 (config_loader.py), Brief 023 (marina_agent.py)
**Blocks:** Brief 025 (calendar.js cleanup)

---

## CONTEXT

email_poller.py currently makes multiple Claude API calls per message and uses Python to classify intents, evaluate dates, match experience strings, and select replies. This is documented architectural drift.

marina_agent.py (Brief 023) is the replacement: one Claude call returns all of that as structured JSON.

This brief wires it in and removes the drift. Two files are touched:
1. email_poller.py — major refactor of the main loop and removal of all drift functions
2. marina_agent.py — one surgical amendment: add trip_key to the list of extractable fields in the prompt

---

## SOURCE MATERIAL

Files confirmed seen this session:
- email_poller.py — 1241 lines, LAST MODIFIED Brief 020
- marina_agent.py — 175 lines, LAST MODIFIED Brief 023
- config_loader.py — 94 lines, LAST MODIFIED Brief 022
- client.json — trip keys: klein_curacao, snorkeling_3in1, west_coast_beach, sunset_cruise, jet_ski

Current marina_agent.py prompt specifies extractable fields as:
experience, date, guests, customer_name, phone, special_requests

---

## PART 1 — AMENDMENT TO marina_agent.py

### What changes

In the prompt inside _build_prompt(), the fields list currently reads:
experience, date, guests, customer_name, phone, special_requests

Add one field to that list:
trip_key — the exact key from the trips list that matches the experience the customer is asking about. One of: klein_curacao, snorkeling_3in1, west_coast_beach, sunset_cruise, jet_ski. Only include if you are certain which trip they mean.

No other changes to marina_agent.py.

---

## PART 2 — REFACTOR OF email_poller.py

### What is removed entirely

These functions are deleted. No references to them may remain:
- detect_intent_and_fields()
- ask_marina_llm()
- classify_date_input()
- normalize_date_to_yyyy_mm_dd()
- is_date_confirmation_yes()
- experience_is_clear()
- package_key_from_experience()
- default_start_time_for_package()
- price_for_package()
- safe_out_of_scope_reply()
- safe_complaint_reply()
- safe_social_reply()
- safe_inquiry_reply()
- safe_change_request_reply()
- safe_large_group_reply()
- safe_date_confirmation_reply()
- safe_date_past_reply()
- safe_date_implausible_reply()
- safe_date_vague_reply()
- safe_experience_unclear_reply()

These constants are deleted:
- GROUP_BOOKING_THRESHOLD
- REQUIRED_FIELDS

These imports are removed:
- import claude_client
- import dateparser
- from marina_extractor import extract_fields (inside detect_intent_and_fields)

These are added:
- import marina_agent
- import config_loader (at module level)

### What is kept identical

These functions are not touched:
- oauth_token()
- imap_connect()
- smtp_send()
- extract_text()
- strip_quotes()
- stable_thread_key()
- normalize_subject()
- load_json()
- save_json()
- sha()
- log()

These integrations are not touched:
- state_registry (deduplication and anti-loop logic)
- bm_logger (all existing log calls)
- sheets_writer (all existing log calls)
- payment_stub (hold payment link generation)

The thread state structure is not changed:
- thread["fields"] — dict of collected booking fields
- thread["flags"] — dict of conversation state flags
- thread["last_customer_hash"]
- thread["reply_times"]

### What changes in create_calendar_hold()

Current behaviour: calls package_key_from_experience() to get a package key, then calls default_start_time_for_package() and price_for_package() for hardcoded values.

New behaviour:
- Accept trip_key directly from fields_now.get("trip_key"). If trip_key is missing or empty, return {"ok": False, "error": "No trip_key in fields — cannot create hold."}
- Look up start_time from the first element of config_loader.get_trip(trip_key).get("departures", [{}])[0].get("time", "09:00")
- Look up price from config_loader.get_trip(trip_key).get("price_adult_usd", 0)
- Pass trip_key as package_key to calendar.js (unchanged interface with calendar.js — Brief 025 will update calendar.js to use the new keys)

Remove the past-date guard from inside create_calendar_hold. That logic now belongs to Claude via marina_agent.

### New main loop behaviour

The main loop structure — IMAP connection, UNSEEN fetch, uid iteration, RFC822 fetch, from/subject/body extraction, deduplication via state_registry, anti-loop guard, thread state load/save, mark Seen — is unchanged.

What replaces the intent dispatch block is the following behaviour:

**Step 1 — Call marina_agent**
After deduplication and anti-loop pass, call:
marina_agent.process_message(
    from_email,
    subject,
    body,
    thread_fields (th["fields"]),
    thread_flags (th["flags"])
)
This is the only Claude call in the loop. Do not call claude_client, marina_extractor, or any other LLM function.

**Step 2 — Merge fields**
Merge result["fields"] into th["fields"]. Existing values are not overwritten unless the new value is non-empty. trip_key, experience, date, guests, customer_name, phone, special_requests are all valid field keys.

**Step 3 — Persist flags**
Merge result["flags"] into th["flags"]. result["flags"] may be empty. Python does not interpret the flag values. It stores them and passes them back to marina_agent on the next message in the thread.

**Step 4 — requires_human check**
If result["requires_human"] is True:
- Send result["reply"] via smtp_send
- Log to bm_logger with event "human_required" and internal_note
- Log to sheets_writer
- Mark seen, persist state, continue to next message
- Do not proceed to booking flow

**Step 5 — Booking flow**
If "booking" in result["intents"] AND all three of experience, date, guests are present in th["fields"] AND th["flags"].get("hold_created") is not True:
Call create_calendar_hold(th["fields"])

If hold fails:
- Send result["reply"] via smtp_send as-is
- Log to bm_logger with event "hold_failed", the calendar error, and the fields that were attempted
- Log to sheets_writer
- Mark seen, persist state, continue

If hold succeeds:
- Set th["flags"]["hold_created"] = True
- Set th["flags"]["event_id"] = result from calendar.js
- Set th["flags"]["event_link"] = result from calendar.js
- Generate payment link via payment_stub (unchanged)
- Set th["flags"]["payment_id"], payment_link, payment_status
- Log to bm_logger "hold_created" with all fields (unchanged)
- Log to sheets_writer (unchanged)
- Send result["reply"] via smtp_send

If hold already created (hold_created flag is True):
- Send result["reply"] via smtp_send
- No new hold is created

**Step 6 — All other intents**
For inquiry, social, complaint, cancellation, reschedule, off_topic:
- Send result["reply"] via smtp_send
- Log to bm_logger using result["intents"][0] as event name and result["internal_note"] as the note
- Log to sheets_writer

**Step 7 — Persist state**
Mark Seen. Append now to reply_times. Update last_customer_hash. Save thread state. Identical to current behaviour.

---

## IMPORTANT CONSTRAINT

Python reads result["reply"], result["intents"], result["fields"], result["flags"], result["requires_human"], result["internal_note"]. Python does not evaluate the content of these fields for language meaning. It routes based on the structured values only. The reply is sent exactly as returned from marina_agent. Python does not append to, prepend to, or modify the reply string.

---

## TESTS

All tests must pass before this brief is considered complete.

**Test 1 — email_poller.py imports without error**
Import email_poller from bluemarlin/src. Assert no ImportError. Assert that claude_client is not imported by email_poller. Assert that marina_agent is imported by email_poller.

**Test 2 — removed functions are gone**
Import email_poller. Assert that none of the following exist as attributes: detect_intent_and_fields, ask_marina_llm, classify_date_input, is_date_confirmation_yes, package_key_from_experience, experience_is_clear, safe_complaint_reply, safe_social_reply, safe_inquiry_reply, safe_large_group_reply, safe_date_past_reply.

**Test 3 — kept functions are intact**
Import email_poller. Assert that all of the following exist: oauth_token, imap_connect, smtp_send, extract_text, strip_quotes, stable_thread_key, create_calendar_hold.

**Test 4 — create_calendar_hold returns error when trip_key missing**
Call create_calendar_hold({"experience": "sunset", "date": "2026-04-20", "guests": 2}) — no trip_key in fields. Assert result["ok"] is False. Assert "trip_key" in result["error"].

**Test 5 — create_calendar_hold looks up config values**
Mock config_loader.get_trip to return {"departures": [{"time": "17:30"}], "price_adult_usd": 79} for "sunset_cruise". Call create_calendar_hold({"trip_key": "sunset_cruise", "date": "2026-04-20", "guests": 2, "customer_name": "Test", "phone": "+59991234567"}). Assert the payload passed to calendar.js contains start_time "17:30" and price_usd 79. (Intercept the subprocess.run call — do not require calendar.js to actually run.)

**Test 6 — marina_agent trip_key amendment**
Call marina_agent.process_message with body "I want to book the sunset cruise on April 20 for 2 people." Assert result["fields"].get("trip_key") == "sunset_cruise".

**Test 7 — GROUP_BOOKING_THRESHOLD and REQUIRED_FIELDS constants are not present in email_poller**
Import email_poller. Assert hasattr(email_poller, "GROUP_BOOKING_THRESHOLD") is False. Assert hasattr(email_poller, "REQUIRED_FIELDS") is False.

**Test 8 — no dateparser import in email_poller**
Read the source of email_poller.py as text. Assert "import dateparser" not in the source. Assert "import claude_client" not in the source.

---

## SUCCESS CONDITION

All 8 tests pass. email_poller.py starts without error on the VPS (verified by systemctl status after restart). No references to removed functions remain in email_poller.py. marina_agent.py returns trip_key in fields when the trip is identifiable.

---

## ROLLBACK

The full content of email_poller.py as of Brief 020 is preserved in bluemarlin/briefs/ARCHIVE_PRE_022.md. If the refactored file causes a startup failure on the VPS, restore from that archive and restart the service. No other files are at risk. config_loader.py, marina_agent.py (except the one-line prompt amendment), calendar.js, state_registry.py, bm_logger.py, sheets_writer.py, payment_stub.py are not modified.
