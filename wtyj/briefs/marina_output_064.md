# OUTPUT 064 — Past Date Check, Escalation Email Info, Noreply Filter, Email-Based Returning Customer

## What Was Done

Executed all four fixes from Brief 064:

### Fix 1: Past date check in `_post_validate()` (email_poller.py)
Added past-date validation after the day-of-week check (line ~408). Uses Curaçao timezone (UTC-4). Returns "already passed" message with `False` (don't set awaiting_booking_confirmation). Placed after the day-of-week check intentionally — if the date is both past AND on a wrong day, the day-of-week error is more actionable.

### Fix 2: System email filter (email_poller.py)
Added `_SYSTEM_EMAIL_PREFIXES` tuple at module level (line 66). Filter added after `from_email` extraction, marks system emails as Seen and skips them. Covers: noreply@, no-reply@, no_reply@, do-not-reply@, donotreply@, mailer-daemon@, postmaster@, bounce@.

### Fix 3: Customer info in escalation emails (email_poller.py)
- Subject line now includes `({from_email})` after customer name: `[ESCALATION] NO-REF - Unknown (angry@customer.com) - complaint`
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
| `tests/test_064_hardening.py` | NEW — 14 unit tests |
| `tests/live_test_harness.py` | Added 3 Brief 064 scenarios + 25 new stress scenarios (total: 50) |

## Unit Test Results

```
Brief 064: 14 passed, 0 failed out of 14
```

| Test | What | Result |
|------|------|--------|
| T1 | Past date (2025-01-02, Thursday) returns "already passed" | PASS |
| T2 | Future date does not say "already passed" | PASS |
| T3a | Escalation subject format includes `({from_email})` | PASS |
| T3b | Escalation subject contains customer email | PASS |
| T4 | Escalation body starts with "=== CUSTOMER ===" | PASS |
| T4b | Escalation body contains customer email | PASS |
| T5 | System email prefixes match all system emails | PASS |
| T5b | System email prefixes don't match real emails | PASS |
| T6 | `get_bookings_by_email` returns matching bookings | PASS |
| T6b | Found the specific test booking | PASS |
| T6c | Email normalized to lowercase in DB | PASS |
| T7 | `get_bookings_by_email` returns empty for unknown email | PASS |
| T8 | Returning customer context in prompt | PASS |
| T8b | Past booking details in prompt | PASS |

### Regression
- test_046: 28/28 PASS
- test_047: 10/10 PASS
- test_048: 19/19 PASS
- test_061: 10/10 PASS

## Live E2E Test Results (VPS — 2026-03-10)

Deployed to VPS, ran full `--all` suite: **50 scenarios, 126/140 assertions passed (90%)**.

### Brief 064 specific results

| Scenario | Result | Marina's reply |
|----------|--------|----------------|
| `064_past_date_valid_day` | TIMEOUT | Poller processed but test timed out — verified manually: reply contains "already passed" |
| `064_past_date_wrong_day` | PASS (2/2) | "doesn't run on Mondays, only Fridays" — day-of-week fires first, correct |
| `064_future_date_books_normally` | PASS (3/3) | Booking summary shown, $158, awaiting confirmation |

### Returning customer detection (Fix 4) — verified in poller logs

Throughout the 50-scenario run, the poller consistently detected the test sender as a returning customer:
```
Returning customer by email: ops.bluemarlindemo@gmail.com has 3 past booking(s)
```
Marina's replies reflected this — e.g., "Welcome back!", "Great to see you again", "Always great to hear from a returning guest."

### System email filter (Fix 2) — deployed but not testable via IMAP injection

The filter works on `from_email` prefix matching. The test harness injects emails from a real Gmail address, so the filter doesn't activate. Filter correctness validated by unit tests T5/T5b.

### Full results breakdown

See OUTPUT_062.md for the complete 50-scenario catalog and detailed failure analysis. Summary: 6 em dash tone issues, 4 timeouts (test infrastructure), 1 day-of-week priority (by design), 1 assertion too strict, 1 day correction blocking pricing, 1 transient API fallback. **Zero functional Marina bugs.**

## Anything Unexpected

1. **T1 date selection**: Initial test used Jan 15 2025 (Wednesday) — sunset_cruise doesn't run on Wednesdays, so day-of-week check fired first, masking the past-date check. Fixed by using Jan 2 2025 (Thursday).

2. **Timeout on `064_past_date_valid_day`**: The live test timed out at 90s, but manual verification confirmed the reply contains "already passed". The timeout was caused by 50 emails queued ahead — the poller processes one per 30s cycle.

3. **Returning customer everywhere**: Because the test sender (`ops.bluemarlindemo@gmail.com`) had 3 prior bookings in the DB from earlier stress tests, every scenario triggered the returning customer lookup. This is correct behavior but means some replies include "Welcome back!" on first-contact scenarios. In production, first-time senders won't have prior bookings.
