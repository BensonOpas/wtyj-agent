# BRIEF 137 — Booking Flow Guard: Email + Soft Hold Fix
**Status:** Draft | **Files:** `agents/social/social_agent.py`, `agents/marina/email_poller.py` | **Depends on:** Brief 135 | **Blocks:** None

## Context

Blind audit found two critical bugs in the booking_flow toggle:

1. Email poller has NO booking_flow check. `booking_flow: false` only works on WhatsApp. Email runs full booking — manifests, payment links, everything.
2. WhatsApp soft holds are created BEFORE the booking_flow check. Step 7 (availability + hold) at line 436 runs before Step 7.8 (toggle check) at line 621. Holds leak.

## Why This Approach

Add `_booking_flow_on` as an early guard in both files. Don't move existing code blocks — add the check at the points where booking logic begins. Guard Step 7 (soft hold), Step 7.8 (escalation), and Step 8 (confirmation) in social_agent. Guard Step 3b and Step 5 in email_poller.

## Source Material

### social_agent.py flow order:
- Line 436: Step 7 — availability + soft hold (NO guard)
- Line 489: `_skip_booking = False` initialized
- Line 491: Step 7.5 — semi-escalation
- Line 621: Step 7.8 — booking_flow check (TOO LATE)
- Line 657: Step 8 — booking confirmation

### email_poller.py flow order:
- Line 870: `awaiting_booking_confirmation` set by post-validate
- Line 872: Step 3b — availability + soft hold (NO guard)
- Line 1062: Step 5 — booking confirmation (NO guard)

### Escalation chat log pattern (email_poller.py lines 1007-1014):
```python
_esc_chat_lines = []
for _em in _esc_msgs:
    _esc_chat_lines.append(f"[{_em['role'].upper()} | {_em.get('created_at', '')}]")
    _esc_chat_lines.append(_em.get("text", ""))
    _esc_chat_lines.append("---")
```

## Instructions

### Step 1: Guard soft hold in `social_agent.py`

Read `_booking_flow_on` once, early, BEFORE Step 7. Add this line right after the post-validate section (after line 434, before line 436):

```python
_booking_flow_on = config_loader.get_raw().get("features", {}).get("booking_flow", True)
```

Then wrap Step 7 with the guard:
```python
    # Step 7: Availability pre-check + soft hold (SKIP when booking_flow is OFF)
    if _booking_flow_on and flags.get("awaiting_booking_confirmation")
            and not flags.get("slot_checked"):
```

Change the existing `if` at line 437 from:
```python
    if (flags.get("awaiting_booking_confirmation")
            and not flags.get("slot_checked")):
```
to:
```python
    if (_booking_flow_on
            and flags.get("awaiting_booking_confirmation")
            and not flags.get("slot_checked")):
```

This skips availability checks AND soft holds when booking is off. No code moves, no variable dependency issues.

Then REMOVE the duplicate `_booking_flow_on` read at line 622 (it's already defined above). The Step 7.8 block stays where it is — it uses the variable already set.

### Step 2: Guard email_poller.py — Step 3b

Read `_booking_flow_on` once near the top of the per-email processing loop. Add after the marina_agent call returns (around line 810, after `result = ...`):

```python
_booking_flow_on = config_loader.get_raw().get("features", {}).get("booking_flow", True)
```

Then guard Step 3b the same way. Change line 873 from:
```python
                if (th["flags"].get("awaiting_booking_confirmation")
                        and not th["flags"].get("slot_checked")):
```
to:
```python
                if (_booking_flow_on
                        and th["flags"].get("awaiting_booking_confirmation")
                        and not th["flags"].get("slot_checked")):
```

Also prevent `awaiting_booking_confirmation` from being set when booking is off. Add a guard around line 870:
```python
                if _booking_flow_on and _pv_set_awaiting:
                    th["flags"]["awaiting_booking_confirmation"] = True
```

### Step 3: Guard email_poller.py — Step 5 + escalation

Before Step 5 (line 1062), add the booking_flow escalation. Add a new block:

```python
                # Step 4.8: Booking flow toggle — if OFF, escalate booking intents
                if not _booking_flow_on:
                    if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
                        _fields_now = th["fields"]
                        if _fields_now.get("service_name") or _fields_now.get("date"):
                            _cname = _fields_now.get("customer_name", from_email)
                            # Build email thread history for context
                            _esc_history = th.get("messages", [])[-20:]
                            _esc_chat_lines = []
                            for _em in _esc_history:
                                _role = _em.get("role", "unknown").upper()
                                _esc_chat_lines.append(f"[{_role}]")
                                _esc_chat_lines.append(_em.get("text", ""))
                                _esc_chat_lines.append("---")
                            _esc_chat_log = "\n".join(_esc_chat_lines) or "(no messages logged)"
                            _esc_note = result.get("internal_note", "")
                            _esc_subject = (
                                f"[BOOKING REQUEST] {_cname} "
                                f"(Email: {from_email}) - {_esc_note or 'wants to book'}")
                            _esc_body = (
                                f"=== BOOKING REQUEST (booking_flow OFF) ===\n\n"
                                f"=== CUSTOMER ===\n"
                                f"Email: {from_email}\n"
                                f"Name: {_cname}\n\n"
                                f"=== COLLECTED FIELDS ===\n"
                                f"{json.dumps(_fields_now, indent=2, ensure_ascii=False)}\n\n"
                                f"=== EMAIL THREAD ===\n{_esc_chat_log}\n\n"
                                f"=== MARINA'S NOTE ===\n{_esc_note}"
                            )
                            state_registry.create_pending_notification(
                                'escalation', 'email', from_email, _cname,
                                _esc_subject, _esc_body)
                            bm_logger.log("booking_flow_off_escalated", email=from_email)
                            # Send Marina's conversational reply, then continue to next email
                            smtp_send(from_email, "Re: " + subj, reply_text,
                                      in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                            im.uid("store", uid, "+FLAGS", r"(\Seen)")
                            th["reply_times"].append(now)
                            th["last_customer_hash"] = customer_hash
                            threads[thread_key] = th
                            save_json(THREAD_STATE_PATH, state)
                            continue  # Skip to next email — don't enter Step 5
```

The `continue` skips the rest of the email processing loop (Step 5 booking flow), matching the email poller's existing pattern for early exits (see escalation at line 1055, manifest failure at line 1120).

### Step 4: Fix logger parameter names

In email_poller.py, replace `experience=` with `service_name=` in bm_logger calls (3 occurrences around lines 1072, 1096, 1155). Search for `experience=fields_now` and replace with `service_name=fields_now`.

## Tests

File: `tests/social/test_137_booking_flow_guard.py`

1. **test_wa_no_soft_hold_when_flow_off** — set booking_flow=false, set up state with awaiting_booking_confirmation=true + slot_checked=false, mock marina returning booking intent. Verify: `gws_calendar.check_availability` NOT called, `state_registry.create_soft_hold` NOT called, escalation created.
2. **test_wa_soft_hold_works_when_flow_on** — booking_flow=true, same setup. Verify: `check_availability` IS called (regression).
3. **test_wa_no_awaiting_flag_when_flow_off** — booking_flow=false, verify `awaiting_booking_confirmation` is NOT set in flags after post-validate.

## Success Condition

With `booking_flow: false`, neither WhatsApp nor email enters any part of the booking state machine. No soft holds, no availability checks, no manifests. All 3 tests pass.

## Rollback

Revert the two files.
