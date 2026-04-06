# BRIEF 140 — Large Group Pre-Check: Escalate Before Availability Rejection
**Status:** Draft | **Files:** `agents/social/social_agent.py` | **Depends on:** Brief 139 | **Blocks:** None

## Context

Adversarial E2E test: customer requests 200 people on a 20-capacity sunset cruise. The system says "fully booked on that date" — wrong. The slot isn't full, the group is just too big. The customer thinks the date is unavailable when the real issue is group size.

Step 7 calls `check_availability(service_key, date, time, guests)`. Calendar returns `available: false` because 200 > 20. The code takes the "slot unavailable" path with the hardcoded "fully booked" message. The large group notification at Step 8 (line 790) never runs because the booking never reaches confirmation.

## Why This Approach

Add a capacity pre-check at the top of Step 7. If guests > service capacity, skip availability, escalate to operator, and send Marina's ORIGINAL conversational reply (not the post-validate booking summary). The key is using `reply` (line 412, Marina's raw response) instead of `reply_text` (which post-validate may have overwritten with the booking summary).

Why `reply` not `reply_text`: by the time Step 7 runs, post-validate has overwritten `reply_text` with a booking summary like "Just to confirm: 200 guests, $15,800 total..." That's wrong for a group that exceeds capacity. Marina's original `reply` is conversational — something like "Sure, let me check on that!" — which is appropriate while the escalation handles the actual request.

Why `reply` not `reply_hold_failed`: the `reply_hold_failed` field is only written when Marina gets the confirmation action context. In the primary scenario (first booking request), `awaiting_booking_confirmation` was false when the action context was built, so Marina didn't write `reply_hold_failed`.

## Source Material

### Variable timeline in the orchestrator:
- Line 344: `reply = result.get("reply", "")` — Marina's original conversational reply
- Line 412: `reply_text = reply` — copy to working variable
- Line 430-432: `reply_text = _pv_override` or `reply_text = result["reply"] + _pv_override` — post-validate may overwrite with booking summary
- Line 438: Step 7 begins — `reply_text` may now be the booking summary, but `reply` is still the original

### Step 7 structure (lines 438-490):
```python
    if (_booking_flow_on
            and flags.get("awaiting_booking_confirmation")
            and not flags.get("slot_checked")):
        _ck_svc = fields.get("service_key", "")
        _ck_deps = config_loader.get_service(_ck_svc).get("slots", []) if _ck_svc else []
        _ck_start = (fields.get("slot_time")
                     or (_ck_deps[0].get("time", "09:00") if _ck_deps else "09:00"))
        _ck_guests = int(fields.get("guests") or 1)
        avail = gws_calendar.check_availability(
            _ck_svc, fields.get("date", ""), _ck_start, _ck_guests)
        flags["slot_checked"] = True
        flags["slot_available"] = avail.get("available", False)
        ... (soft hold block + unavailable block)
```

### Service capacity access:
```python
config_loader.get_service(service_key).get("capacity", 20)
```

## Instructions

### Step 1: Add capacity pre-check in Step 7

In `social_agent.py`, replace lines 447-490 (everything inside the Step 7 `if` block after line 446). The current code starts at `avail = gws_calendar.check_availability(...)` and ends at the `bm_logger.log("whatsapp_slot_unavailable"...)` line.

Change from:
```python
        _ck_guests = int(fields.get("guests") or 1)
        avail = gws_calendar.check_availability(
            _ck_svc, fields.get("date", ""), _ck_start, _ck_guests)
        flags["slot_checked"] = True
        flags["slot_available"] = avail.get("available", False)
        flags["spots_remaining"] = avail.get("spots_remaining", 0)
        flags["trip_capacity"] = avail.get("capacity", 0)
        if avail.get("available"):
            hold_id = state_registry.create_soft_hold(
                ...entire existing hold block...
            )
            if hold_id is not None:
                ...existing hold success...
            else:
                ...existing hold race...
        else:
            ...existing unavailable...
```

To:
```python
        _ck_guests = int(fields.get("guests") or 1)
        _svc_capacity = config_loader.get_service(_ck_svc).get("capacity", 20) if _ck_svc else 20
        if _ck_guests > _svc_capacity:
            # Group exceeds capacity — escalate, don't check availability
            flags["slot_checked"] = True
            flags["slot_available"] = False
            flags["awaiting_booking_confirmation"] = False
            _cname = fields.get("customer_name") or from_name or "Unknown"
            state_registry.create_pending_notification(
                'escalation', 'whatsapp', phone, _cname,
                f"[LARGE GROUP] {_cname} (WhatsApp: {phone}) — {_ck_guests} guests exceeds {_svc_capacity} capacity",
                (f"=== LARGE GROUP — EXCEEDS CAPACITY ===\n"
                 f"Customer: {_cname}\nPhone: {phone}\n"
                 f"Service: {fields.get('service_name', _ck_svc)}\n"
                 f"Date: {fields.get('date', '?')}\n"
                 f"Guests: {_ck_guests} (capacity: {_svc_capacity})\n\n"
                 f"Group exceeds standard capacity. Contact customer to discuss options."))
            bm_logger.log("whatsapp_large_group_exceeds_capacity", phone=phone,
                          guests=_ck_guests, capacity=_svc_capacity,
                          service_key=_ck_svc)
            # Use Marina's original conversational reply (not the booking summary)
            reply_text = reply
        else:
            avail = gws_calendar.check_availability(
                _ck_svc, fields.get("date", ""), _ck_start, _ck_guests)
            flags["slot_checked"] = True
            flags["slot_available"] = avail.get("available", False)
            flags["spots_remaining"] = avail.get("spots_remaining", 0)
            flags["trip_capacity"] = avail.get("capacity", 0)
            if avail.get("available"):
                hold_id = state_registry.create_soft_hold(
                    _ck_svc,
                    fields.get("date", ""),
                    _ck_start,
                    _ck_guests,
                    avail.get("capacity", 20),
                    customer_name=fields.get("customer_name", ""),
                    customer_email=fields.get("email") or phone,
                )
                if hold_id is not None:
                    flags["hold_id"] = hold_id
                    flags["hold_service_key"] = _ck_svc
                    flags["hold_date"] = fields.get("date", "")
                    flags["hold_slot_time"] = _ck_start
                    bm_logger.log("whatsapp_soft_hold_created", phone=phone,
                                  hold_id=hold_id, service_key=_ck_svc)
                else:
                    flags["slot_available"] = False
                    flags["awaiting_booking_confirmation"] = False
                    flags["slot_checked"] = False
                    _unavail_name = _pv_service.get("display_name", _ck_svc)
                    reply_text = (
                        f"Unfortunately the {_unavail_name} is fully booked on that date. "
                        f"Would you like to try a different date?"
                    )
                    bm_logger.log("whatsapp_soft_hold_race", phone=phone, service_key=_ck_svc)
            else:
                flags["awaiting_booking_confirmation"] = False
                flags["slot_checked"] = False
                _unavail_name = _pv_service.get("display_name", _ck_svc)
                reply_text = (
                    f"Unfortunately the {_unavail_name} is fully booked on that date. "
                    f"Would you like to try a different date?"
                )
                bm_logger.log("whatsapp_slot_unavailable", phone=phone, service_key=_ck_svc,
                              spots=avail.get("spots_remaining", 0))
```

The existing availability check + soft hold code moves into the `else` block with one extra indentation level. No logic changes to the existing code.

## Tests

File: `tests/social/test_140_large_group_pre_check.py`

1. **test_wa_large_group_exceeds_capacity_escalates** — guests=200, capacity=20. Mock Marina with `reply="Sounds great, let me check!"`. Verify: escalation created with "[LARGE GROUP]" subject containing "exceeds" and "200", `awaiting_booking_confirmation` reset to False, `check_availability` NOT called, reply_text is Marina's original reply (not a booking summary, not "fully booked").

2. **test_wa_normal_group_checks_availability** — guests=4, capacity=20. Verify: `check_availability` IS called (regression).

3. **test_wa_group_at_capacity_checks_normally** — guests=20, capacity=20. Verify: `check_availability` IS called. Pre-check only fires for guests > capacity, not >=.

4. **test_wa_group_one_over_escalates** — guests=21, capacity=20. Verify: escalation created, `check_availability` NOT called.

5. **test_wa_large_group_reply_is_not_booking_summary** — guests=50, capacity=20. Mock Marina `reply="Hey, I can help with the sunset cruise!"`. Mock post-validate to set `reply_text` to a booking summary. Verify: after Step 7, `reply_text` is Marina's original reply ("Hey, I can help"), NOT the booking summary.

## Success Condition

A group larger than the service capacity gets escalated and receives Marina's conversational reply. The customer does NOT see "fully booked" or a booking summary. Normal groups still go through availability check. All 5 tests pass.

## Rollback

Revert `social_agent.py`.
