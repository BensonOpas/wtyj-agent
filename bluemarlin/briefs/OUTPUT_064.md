# OUTPUT 064 — Past Date Check, Escalation Email Info, Noreply Filter, Email-Based Returning Customer

## What Was Done

Executed all four fixes from Brief 064:

### Fix 1: Past date check in `_post_validate()` (email_poller.py)
Added past-date validation after the day-of-week check (line ~408). Uses Curaçao timezone (UTC-4). Returns "already passed" message with `False` (don't set awaiting_booking_confirmation).

### Fix 2: System email filter (email_poller.py)
Added `_SYSTEM_EMAIL_PREFIXES` tuple at module level (line 66). Filter added after `from_email` extraction, marks system emails as Seen and skips them. Covers: noreply@, no-reply@, no_reply@, do-not-reply@, donotreply@, mailer-daemon@, postmaster@, bounce@.

### Fix 3: Customer info in escalation emails (email_poller.py)
- Subject line now includes `({from_email})` after customer name
- Body now starts with `=== CUSTOMER ===` section containing Email, Name, Phone before the chat log

### Fix 4: Email-based returning customer lookup
- **state_registry.py**: Added `get_bookings_by_email()` — queries bookings table by normalized email, returns newest first. Normalized `customer_email` to lowercase in `save_booking()`.
- **email_poller.py**: After booking ref detection block, added email-based lookup for fresh threads (no detected ref, no completed bookings). Sets `_past_customer_bookings` flag with up to 3 recent bookings.
- **marina_agent.py**: Added `past_customer_bookings_section` in `_build_user_prompt()` — tells Claude this is a returning customer with their booking history.

### File headers updated
All three source files updated to Brief 064.

## Files Modified

| File | Change |
|------|--------|
| `src/email_poller.py` | Past date check, system email filter, escalation email format, email-based returning customer lookup, header |
| `src/state_registry.py` | `get_bookings_by_email()`, email normalization in `save_booking()`, header |
| `src/marina_agent.py` | `past_customer_bookings_section` in `_build_user_prompt()`, header |
| `tests/test_064_hardening.py` | NEW — 14 tests |

## Test Results

```
Brief 064: 14 passed, 0 failed out of 14
```

- T1: Past date (2025-01-02) returns "already passed" — PASS
- T2: Future date does not say "already passed" — PASS
- T3: Escalation subject contains customer email — PASS
- T4: Escalation body starts with "=== CUSTOMER ===" — PASS
- T4b: Escalation body contains customer email — PASS
- T5: System email prefixes match all system emails — PASS
- T5b: System email prefixes don't match real emails — PASS
- T6: get_bookings_by_email returns matching bookings — PASS
- T6b: Found the specific test booking — PASS
- T6c: Email normalized to lowercase in DB — PASS
- T7: get_bookings_by_email returns empty for unknown email — PASS
- T8: Returning customer context in prompt — PASS
- T8b: Past booking details in prompt — PASS

### Regression
- test_046: 28/28 PASS
- test_047: 10/10 PASS
- test_048: 19/19 PASS
- test_061: 10/10 PASS

Older test suites (035, 036, 038, 040, 043-045) have pre-existing failures from prompt changes in later briefs — not regressions.

## Anything Unexpected

T1 initially failed because the test date (2025-01-15) was a Wednesday, which doesn't pass the day-of-week check for sunset_cruise (runs Tue/Thu/Fri/Sat). The day-of-week check fires before the past date check. Fixed by using 2025-01-02 (a Thursday).
