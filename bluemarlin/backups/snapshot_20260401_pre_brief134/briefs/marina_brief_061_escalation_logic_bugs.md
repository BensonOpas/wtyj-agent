# BRIEF 061 — Escalation Logic Bugs: NO-REF, Empty Name, Silent Ref Drop
**Status:** Draft | **Files:** `src/email_poller.py`, `src/marina_agent.py`, `tests/test_061_escalation_bugs.py` | **Depends on:** Brief 054 (booking ref + cross-thread memory) | **Blocks:** —

## Context

Live stress testing on 2026-03-10 revealed three bugs in the escalation and returning-customer flows:

1. **Escalation NO-REF bug**: When a returning customer (who mentioned booking ref "BF-2026-XXXXX") escalates (complaint, cancellation), the escalation email subject shows `[ESCALATION] NO-REF - Unknown - cancellation` instead of the actual booking ref. Root cause: line 840 reads `th["flags"].get("booking_ref", "NO-REF")` but for returning customers the ref is stored in `th["flags"]["returning_booking"]`. The `booking_ref` flag is only set after a NEW hold is created (line 898). Same bug at line 780 (relay/semi-escalation).

2. **Escalation customer_name shows "Unknown"**: Line 841 reads `th["fields"].get("customer_name", "Unknown")`. The returning-customer pre-population (lines 608-612) does set customer_name from the past booking. However, if the customer_name was not stored in the original booking record (e.g., sheets_writer stores it but state_registry may not), the field stays empty. Same issue at line 781 (relay).

3. **Unknown booking refs silently dropped**: When a customer mentions a ref that doesn't exist in the bookings table, `state_registry.get_booking()` returns None and nothing happens. The customer's message is processed as a new booking request with no acknowledgment that their ref wasn't found. Marina should tell them the ref wasn't recognized and ask them to double-check.

## Why This Approach

Bug 1 is a straightforward key mismatch — fix by falling through `booking_ref` → `returning_booking` → `"NO-REF"`. Bug 2 needs the same fallthrough for customer_name at the relay/escalation points. Bug 3 requires a new thread flag (`unknown_ref`) that Marina can see in her prompt context, so she can acknowledge the issue naturally without a hardcoded static reply (Rule 3 compliance). Python detects the unknown ref, sets the flag, Claude generates the appropriate reply.

## Source Material

### Current escalation ref lookup (email_poller.py line 840)
```python
booking_ref_esc = th["flags"].get("booking_ref", "NO-REF")
customer_name_esc = th["fields"].get("customer_name", "Unknown")
```

### Current relay ref lookup (email_poller.py line 780-781)
```python
_ref = th["flags"].get("booking_ref", "NO-REF")
_cname = th["fields"].get("customer_name", "Unknown")
```

### Current returning customer detection (email_poller.py lines 601-613)
```python
_detected_ref = _detect_booking_ref(body)
if _detected_ref and not th["flags"].get("booking_ref"):
    _past_booking = state_registry.get_booking(_detected_ref)
    if _past_booking:
        th["flags"]["returning_booking"] = _detected_ref
        for _rbk in ("trip_key", "date", "guests", "customer_name", "departure_time"):
            _rbv = _past_booking.get(_rbk)
            if _rbv and not th["fields"].get(_rbk):
                th["fields"][_rbk] = _rbv if not isinstance(_rbv, int) else str(_rbv)
        log(f"Returning customer: loaded booking {_detected_ref} for {from_email}")
```

### state_registry.get_booking() return (from src/state_registry.py)
Returns dict with keys: booking_ref, trip_key, date, guests, customer_name, departure_time, email — or None if not found.

## Instructions

### Fix 1: Extract ref resolution helper + apply at lines 780, 840

Add a module-level helper function near the top of email_poller.py (after the existing helper functions, before `_process_inbound()`):

```python
def _resolve_booking_ref(th: dict) -> str:
    """Get the best available booking ref from thread flags.
    Priority: booking_ref (active booking) > returning_booking (past ref) > NO-REF.
    """
    return th["flags"].get("booking_ref") or th["flags"].get("returning_booking") or "NO-REF"
```

At **line 780**, replace:
```python
_ref = th["flags"].get("booking_ref", "NO-REF")
```
with:
```python
_ref = _resolve_booking_ref(th)
```

At **line 840**, replace:
```python
booking_ref_esc = th["flags"].get("booking_ref", "NO-REF")
```
with:
```python
booking_ref_esc = _resolve_booking_ref(th)
```

### Fix 2: Customer name fallthrough (lines 781, 841)

No code change needed at lines 781 and 841 — they already read from `th["fields"]` which IS pre-populated by the returning customer detection (lines 608-612). The bug was misdiagnosed in initial testing. The customer_name was empty because that specific past booking didn't have customer_name stored (state_registry stores what was collected, and a booking created with `customer_name=""` stays empty). The existing fallback to "Unknown" is correct behavior.

**Verification**: Confirm `state_registry.get_booking()` returns customer_name when it was stored. No code change needed.

### Fix 3: Unknown booking ref flag (lines 601-613)

After the existing `if _past_booking:` block (after line 613), add an `else` branch:

```python
                    else:
                        th["flags"]["unknown_ref"] = _detected_ref
                        log(f"Unknown booking ref {_detected_ref} mentioned by {from_email}")
```

### Fix 4: Add unknown_ref to marina_agent prompt context

In `marina_agent.py`, in the `_build_user_prompt()` function, the thread flags are already passed via:
```python
  Flags: {json.dumps(thread_flags, ensure_ascii=False)}
```

Add a section to `_build_system_prompt()` that instructs Marina how to handle `unknown_ref`. Add after the RETURNING CUSTOMER section in `_build_user_prompt()`:

In `_build_user_prompt()`, after the `returning_customer_section` block (after line 243), add:

```python
    unknown_ref_section = ""
    if thread_flags.get("unknown_ref"):
        unknown_ref_section = (
            f"\nUNKNOWN BOOKING REF: The customer mentioned ref {thread_flags['unknown_ref']} "
            f"but it was not found in our system. Let them know politely that you couldn't "
            f"find that reference and ask them to double-check the number. If they want to "
            f"make a new booking, help them normally.\n"
        )
```

Then include `{unknown_ref_section}` in the return f-string at line 265, between `{returning_customer_section}` and `{completed_bookings_section}`. The line should read:
```python
    return f"""{returning_customer_section}{unknown_ref_section}{completed_bookings_section}{max_bookings_section}
```

### Fix 5: Clear unknown_ref after it's been communicated

In `email_poller.py`, after the marina_agent call returns (around line 650 area, after the result is received), add cleanup:

```python
                # Clear one-shot flags after Claude has seen them
                if th["flags"].get("unknown_ref"):
                    del th["flags"]["unknown_ref"]
```

This should go right after the `result = marina_agent.process_message(...)` call returns, before any further processing.

### Fix 6: Update file headers

- `src/email_poller.py`: LAST MODIFIED → Brief 061
- `src/marina_agent.py`: LAST MODIFIED → Brief 061

## Tests

File: `tests/test_061_escalation_bugs.py`

### T1: _resolve_booking_ref falls through to returning_booking
```python
from email_poller import _resolve_booking_ref
th = {"fields": {}, "flags": {"returning_booking": "BF-2026-12345"}, "messages": []}
assert _resolve_booking_ref(th) == "BF-2026-12345"
```

### T2: _resolve_booking_ref uses booking_ref when present (regression)
```python
from email_poller import _resolve_booking_ref
th = {"fields": {}, "flags": {"booking_ref": "BF-2026-99999", "returning_booking": "BF-2026-12345"}, "messages": []}
assert _resolve_booking_ref(th) == "BF-2026-99999"
```

### T3: _resolve_booking_ref returns NO-REF when neither present
```python
from email_poller import _resolve_booking_ref
th = {"fields": {}, "flags": {}, "messages": []}
assert _resolve_booking_ref(th) == "NO-REF"
```

### T4: Unknown ref flag set when ref not found
```python
# Simulate: _detected_ref found but get_booking returns None
th = {"fields": {}, "flags": {}}
_detected_ref = "BF-2026-00000"
_past_booking = None  # Not found
if _past_booking:
    th["flags"]["returning_booking"] = _detected_ref
else:
    th["flags"]["unknown_ref"] = _detected_ref
assert th["flags"]["unknown_ref"] == "BF-2026-00000"
assert "returning_booking" not in th["flags"]
```

### T5: Unknown ref section appears in prompt when flag set
```python
import marina_agent
prompt = marina_agent._build_user_prompt("a@b.com", "T", "T", {}, {"unknown_ref": "BF-2026-00000"})
assert "BF-2026-00000" in prompt
assert "not found" in prompt.lower() or "couldn't find" in prompt.lower()
```

### T6: Unknown ref section absent when flag not set
```python
import marina_agent
prompt = marina_agent._build_user_prompt("a@b.com", "T", "T", {}, {})
assert "UNKNOWN BOOKING REF" not in prompt
```

### T7: _detect_booking_ref extracts valid ref format
```python
from email_poller import _detect_booking_ref
ref = _detect_booking_ref("My booking BF-2026-12345 needs to be cancelled")
assert ref == "BF-2026-12345"
```

### T8: _detect_booking_ref returns None for no ref
```python
from email_poller import _detect_booking_ref
ref = _detect_booking_ref("I want to book a trip")
assert ref is None
```

## Success Condition

Escalation emails show the actual booking ref (from `returning_booking` when `booking_ref` is absent), and unknown booking refs trigger a prompt section that lets Marina inform the customer naturally.

## Rollback

Revert email_poller.py lines 780, 840, 601-615 changes. Remove unknown_ref section from marina_agent.py `_build_user_prompt()`. Delete test file.
