# OUTPUT 054 — Booking ref in confirmation + cross-thread memory

## What was done

### Step 1: state_registry.py — bookings table + functions
- Added `bookings` table creation in `_get_conn()` after the `manifest_events` block
- Added `save_booking()` — upserts a booking record keyed on `booking_ref`, stores all fields, flags (payment_link, event_link), customer_email, status="confirmed"
- Added `get_booking()` — returns full booking dict by ref, or None
- Updated header to Brief 054

### Step 2: email_poller.py — save booking after hold success
- Added `state_registry.save_booking()` call after the manifest CREATED/UPDATED log line (after line 917)
- Passes `booking_ref`, `fields_now`, `th["flags"]`, and `from_email`

### Step 3: email_poller.py — detect booking ref in inbound message
- Added `_detect_booking_ref(body)` helper using `re.search(r'BF-\d{4}-\d{5}', body)`
- Added returning customer detection block before the marina_agent call: detects ref, looks up booking, sets `returning_booking` flag, pre-populates empty thread fields from past booking
- Updated header to Brief 054

### Step 4: marina_agent.py — prompt additions
- Added static `BOOKING REFERENCE:` section between `{action_context}` and `ESCALATION BEHAVIOUR:` — instructs Marina to include booking_ref in confirmation replies
- Added `returning_customer_section` variable built conditionally on `thread_flags.get("returning_booking")` — tells Marina the customer referenced a past booking with pre-loaded details
- Inserted `{returning_customer_section}` after `{fully_escalated_section}` in prompt f-string
- Updated header to Brief 054

### Step 5: File headers updated
- state_registry.py: Brief 050 → Brief 054
- email_poller.py: Brief 053 → Brief 054
- marina_agent.py: Brief 048 → Brief 054

## Test results

```
PASS: test_save_and_get_booking
PASS: test_get_booking_not_found
PASS: test_save_booking_upsert
PASS: test_detect_booking_ref_found
PASS: test_detect_booking_ref_not_found
PASS: test_detect_booking_ref_multiple
PASS: test_returning_customer_field_population
PASS: test_returning_customer_no_overwrite
PASS: test_prompt_contains_booking_ref_instruction
PASS: test_prompt_contains_returning_customer_section
PASS: test_prompt_no_returning_section_without_flag
PASS: test_booking_ref_instruction_unconditional

12/12 tests passed.
```

## Anything unexpected
Nothing unexpected. All instructions executed as written, all tests passed on first run.
