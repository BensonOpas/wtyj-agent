# OUTPUT 055 — Multi-trip booking in one thread

## What was done

All 6 steps from BRIEF_055 executed exactly as written:

1. **client.json** — Added `"max_bookings_per_thread": 3` to `booking_rules`.

2. **email_poller.py** — Added `_BOOKING_FLAGS_TO_RESET` set, `_PERSISTENT_FIELDS` set, and `_maybe_reset_for_new_booking()` helper after `_detect_booking_ref`. The helper archives the current booking into `completed_bookings`, preserves customer identity fields (customer_name, phone), and clears all booking-related flags. Returns False (no reset) when `hold_created` is not set or max bookings reached.

3. **email_poller.py** — Inserted multi-trip reset call AFTER `marina_agent.process_message()` and BEFORE field merge. Gated on booking intent (`_BOOKING_INTENTS`) AND `hold_created` flag — non-booking messages (inquiry, social, off_topic) never trigger reset.

4. **email_poller.py** — Injected completed bookings summary into `agent_flags` BEFORE the marina_agent call. Builds human-readable summary lines and sets `_max_bookings_reached` flag when limit is hit.

5. **marina_agent.py** — Added `completed_bookings_section` and `max_bookings_section` variables in `_build_prompt()`, injected into prompt string after `{returning_customer_section}`.

6. **File headers** — Both `email_poller.py` and `marina_agent.py` updated from "Brief 054" to "Brief 055".

## Test results

```
PASS: test_reset_after_hold_created
PASS: test_no_reset_without_hold_created
PASS: test_max_bookings_blocks_reset
PASS: test_second_booking_archives_correctly
PASS: test_non_booking_flags_preserved
PASS: test_prompt_completed_bookings_section
PASS: test_prompt_max_bookings_reached
PASS: test_prompt_no_completed_without_data
PASS: test_completed_bookings_summary_format
PASS: test_intent_gating_prevents_non_booking_reset

10/10 tests passed.
```

## Anything unexpected

Nothing unexpected. All changes applied cleanly, all tests passed on first run.
