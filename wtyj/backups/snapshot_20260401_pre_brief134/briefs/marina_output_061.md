# OUTPUT 061 — Escalation Logic Bugs: NO-REF, Empty Name, Silent Ref Drop

## What Was Done

### Fix 1: Booking ref fallthrough
- Added `_resolve_booking_ref(th)` helper function to email_poller.py (after `_detect_booking_ref`)
- Priority: `booking_ref` (active) > `returning_booking` (past) > `"NO-REF"`
- Applied at line 787 (relay/semi-escalation) and line 847 (full escalation)
- Replaces `th["flags"].get("booking_ref", "NO-REF")` at both locations

### Fix 2: Customer name (no change needed)
- Confirmed: `th["fields"].get("customer_name", "Unknown")` is correct — returning customer pre-population already sets customer_name from past booking when available
- "Unknown" appears only when the original booking lacked a customer_name

### Fix 3: Unknown booking ref detection
- Added `else` branch to returning customer detection (after `if _past_booking:`)
- Sets `th["flags"]["unknown_ref"] = _detected_ref` when ref format is valid but not found in bookings table
- Logs the unknown ref for debugging

### Fix 4: Marina prompt context for unknown refs
- Added `unknown_ref_section` to `_build_user_prompt()` in marina_agent.py
- When `unknown_ref` flag is set, injects instruction telling Marina to inform customer the ref wasn't found
- Placed between `returning_customer_section` and `completed_bookings_section`

### Fix 5: One-shot flag cleanup
- After `marina_agent.process_message()` returns, deletes `unknown_ref` from thread flags
- Prevents the instruction from repeating on subsequent messages

### Fix 6: File headers
- Both `email_poller.py` and `marina_agent.py` updated to Brief 061

## Test Results

### Brief 061 tests — ALL PASS
```
test_061_escalation_bugs.py  10/10 passed
```

### Regression tests — ALL PASS
```
test_marina_tone.py          12/12 passed
test_046_hybrid_state_machine.py  28/28 passed
test_booking_ref.py          12/12 passed
test_multi_trip.py           10/10 passed
```

## Files Modified
| File | Changes |
|------|---------|
| `src/email_poller.py` | `_resolve_booking_ref()` helper, unknown ref else branch, one-shot cleanup, header |
| `src/marina_agent.py` | `unknown_ref_section` in `_build_user_prompt()`, header |
| `tests/test_061_escalation_bugs.py` | New — 10 tests |
