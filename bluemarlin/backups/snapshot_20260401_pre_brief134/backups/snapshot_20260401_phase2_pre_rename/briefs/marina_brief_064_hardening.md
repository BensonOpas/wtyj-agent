# BRIEF 064 — Past Date Check, Escalation Email Info, Noreply Filter, Email-Based Returning Customer
**Status:** Draft | **Files:** `src/email_poller.py`, `src/state_registry.py`, `src/marina_agent.py`, `tests/test_064_hardening.py` (NEW) | **Depends on:** Briefs 061, 063 | **Blocks:** —

## Context

Live stress testing (Briefs 062-063) revealed four issues:
1. Past date not caught — `_post_validate()` checks day-of-week but not if date is in the past
2. Escalation emails missing customer info — subject shows "NO-REF - Unknown - complaint" with no email
3. No system email filter — Marina replies to noreply@, mailer-daemon@, etc.
4. No cross-thread returning customer memory — customer who books then emails again (new subject) gets zero context

## Why This Approach

All four are small, localized changes to existing code paths. Past date check extends the existing `_post_validate()` validation chain. Escalation email fix matches the semi-escalation format that already includes customer info. Noreply filter is a simple prefix check. Email-based lookup uses the existing `bookings` table which already has `customer_email` populated.

## Source Material

See plan file at /Users/benson/.claude/plans/imperative-bubbling-bear.md for full details including E2E verification results.

## Instructions

### Step 1: Past date check in `_post_validate()` (email_poller.py)

After the day-of-week check block (after line 400 `except ValueError: pass`), before the departure time check (line 402), insert a past-date check using Curaçao timezone (UTC-4).

### Step 2: System email filter (email_poller.py)

Add `_SYSTEM_EMAIL_PREFIXES` tuple near other constants (~line 63). Add filter after `from_email` extraction (line 451) and before BM-003 duplicate detection (line 453).

### Step 3: Customer info in escalation email (email_poller.py)

Add customer email to subject line and CUSTOMER section to body top, matching semi-escalation relay format.

### Step 4: Email-based returning customer lookup

- `state_registry.py`: Add `get_bookings_by_email()`, normalize email in `save_booking()`
- `email_poller.py`: After booking ref detection block (~line 623), add email-based lookup for fresh threads
- `marina_agent.py`: Add `past_customer_bookings_section` in `_build_user_prompt()`

### Step 5: Update file headers

### Step 6: Write tests

## Tests

T1: Past date returns "already passed"
T2: Future date still builds summary
T3: Escalation subject contains customer email
T4: Escalation body starts with "=== CUSTOMER ==="
T5: System email prefixes match expected patterns
T6: get_bookings_by_email returns matching bookings
T7: get_bookings_by_email returns empty for unknown email
T8: Returning customer context in prompt when bookings exist
T9-T12: Regression tests pass

## Success Condition

All tests pass. Past dates rejected, escalation emails include customer info, system emails skipped, returning customers recognized by email.

## Rollback

Revert changes to email_poller.py, state_registry.py, marina_agent.py. Delete test file.
