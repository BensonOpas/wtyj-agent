# BRIEF 139 — Manifest API Error Handling: Don't Claim "Sold Out" on Config Errors
**Status:** Draft | **Files:** `agents/social/social_agent.py`, `agents/marina/email_poller.py` | **Depends on:** Brief 138 | **Blocks:** None

## Context

Live testing: klein_curacao 08:30 booking failed because the Google Calendar API returned 404 (broken calendar). The code told the customer "slot just filled up." The slot was free — the calendar was misconfigured. Then the customer tried another slot, Claude returned empty JSON (API hiccup), and the conversation died with no recovery.

Two problems to fix:

1. **Manifest failure = "sold out" regardless of cause.** Step 8 in both social_agent.py and email_poller.py treats all `create_or_update_manifest` failures the same — cancel hold, use `reply_hold_failed`, done. A 404 config error, a 500 server error, and a real capacity issue all produce the same customer experience.

2. **No recovery after manifest API error.** When the manifest fails, `booking_confirmed` stays true but `slot_checked` and `slot_available` are reset. The booking flow is dead — the customer can't retry without starting over.

NOTE: The four hardcoded "fully booked" strings in Step 7 (social_agent.py lines 476, 485; email_poller.py lines 914, 925) are NOT changed in this brief. They fire when `reply_hold_failed` is empty (first availability check, before the customer confirms). Replacing them with `reply_hold_failed` would show the booking summary instead of an unavailability message — a worse bug. These strings are an accepted Rule 3 exception for now, like the API failure fallback.

## Why This Approach

For manifest API errors (404, 500, 403, 401, config errors), reset the booking state so the customer can retry on their next message. The hold is cancelled, but `booking_confirmed` is reset and `awaiting_booking_confirmation` is set back to True. Marina will re-enter the confirmation flow on the next customer message.

For non-API errors (business logic), keep the current behavior — use `reply_hold_failed`, don't allow retry.

The API error detection checks the error string from gws_calendar for known HTTP error codes. The error format from gws CLI is JSON containing `"code": 404` etc.

## Source Material

### gws CLI error format (verified from live logs):
```
{"error": {"code": 404, "message": "Not Found", "reason": "notFound"}}
```
The error field in the `{'ok': False, 'error': ...}` dict contains this JSON as a string.

### gws_calendar.py internal errors (lines 95-96, 108-110):
```python
return {'ok': False, 'error': 'No service_key in fields.'}
return {'ok': False, 'error': f'Calendar ID not configured for: {service_key} at {start_time}'}
```

### Current manifest failure handling (social_agent.py lines 676-697):
```python
res = gws_calendar.create_or_update_manifest(fields)
if not res.get("ok"):
    bm_logger.log("whatsapp_manifest_failed", phone=phone,
                  error=res.get("error"))
    if flags.get("hold_id"):
        state_registry.cancel_hold(flags["hold_id"])
        # ... cleanup hold ...
    flags["slot_checked"] = False
    flags["slot_available"] = False
    reply_text = result.get("reply_hold_failed") or reply_text
    sheets_writer.log_hold_failed({ ... })
```

### Current manifest failure handling (email_poller.py lines 1135-1171):
Same pattern but with `th["flags"]` instead of `flags`, and `smtp_send` + `continue`.

## Instructions

### Step 1: Add API error detection + retry state in social_agent.py

Replace lines 676-697 (the manifest failure block inside Step 8). Change from:

```python
            res = gws_calendar.create_or_update_manifest(fields)
            if not res.get("ok"):
                bm_logger.log("whatsapp_manifest_failed", phone=phone,
                              error=res.get("error"))
                if flags.get("hold_id"):
                    state_registry.cancel_hold(flags["hold_id"])
                    _h_svc = flags.pop("hold_service_key", "")
                    _h_date = flags.pop("hold_date", "")
                    _h_dep = flags.pop("hold_slot_time", "")
                    flags.pop("hold_id", None)
                    if _h_svc and _h_date and _h_dep:
                        gws_calendar.remove_from_manifest(_h_svc, _h_date, _h_dep)
                flags["slot_checked"] = False
                flags["slot_available"] = False
                reply_text = result.get("reply_hold_failed") or reply_text
                sheets_writer.log_hold_failed({
                    "email": phone, "subject": "WhatsApp",
                    "service_name": fields.get("service_name"),
                    "date": fields.get("date"),
                    "guests": fields.get("guests"),
                    "error": res.get("error"),
                })
```

To:

```python
            res = gws_calendar.create_or_update_manifest(fields)
            if not res.get("ok"):
                _manifest_error = str(res.get("error", ""))
                _manifest_error = str(res.get("error", ""))
                _is_api_error = any(s in _manifest_error for s in (
                    '"code": 404', '"code": 500', '"code": 403', '"code": 401',
                    "'code': 404", "'code': 500", "'code': 403", "'code': 401",
                    'Calendar ID not configured'))
                bm_logger.log("whatsapp_manifest_failed", phone=phone,
                              error=_manifest_error[:200],
                              error_type="api" if _is_api_error else "business")
                if flags.get("hold_id"):
                    state_registry.cancel_hold(flags["hold_id"])
                    _h_svc = flags.pop("hold_service_key", "")
                    _h_date = flags.pop("hold_date", "")
                    _h_dep = flags.pop("hold_slot_time", "")
                    flags.pop("hold_id", None)
                    if _h_svc and _h_date and _h_dep:
                        gws_calendar.remove_from_manifest(_h_svc, _h_date, _h_dep)
                flags["slot_checked"] = False
                flags["slot_available"] = False
                if _is_api_error:
                    # API/config error — allow customer to retry
                    _retry_count = flags.get("manifest_retry_count", 0) + 1
                    flags["manifest_retry_count"] = _retry_count
                    if _retry_count >= 2:
                        # Persistent failure — escalate instead of looping
                        _cname = fields.get("customer_name") or from_name or "Unknown"
                        state_registry.create_pending_notification(
                            'escalation', 'whatsapp', phone, _cname,
                            f"[SYSTEM] Manifest failure for {_cname} (WhatsApp: {phone})",
                            f"Booking failed {_retry_count} times due to API error.\n"
                            f"Error: {_manifest_error[:300]}\n"
                            f"Fields: {json.dumps(fields, indent=2, ensure_ascii=False)}")
                        bm_logger.log("whatsapp_manifest_escalated", phone=phone,
                                      retry_count=_retry_count)
                    flags["booking_confirmed"] = False
                    flags["awaiting_booking_confirmation"] = True
                reply_text = result.get("reply_hold_failed") or reply_text
                sheets_writer.log_hold_failed({
                    "email": phone, "subject": "WhatsApp",
                    "service_name": fields.get("service_name"),
                    "date": fields.get("date"),
                    "guests": fields.get("guests"),
                    "error": _manifest_error[:200],
                })
```

Also, in the SUCCESS path (the `else` block after `if not res.get("ok")`), add one line to clear the retry counter:
```python
                flags.pop("manifest_retry_count", None)
```
Add this right after `flags["hold_created"] = True` (line 699).

Key changes:
- Detect API errors by checking error string for known HTTP codes + config errors (both double-quote JSON and single-quote Python dict formats)
- For API errors: reset `booking_confirmed=False`, `awaiting_booking_confirmation=True` so customer can retry
- Circuit breaker: after 2 failures, create an escalation so the operator knows something is broken
- Track retry count in `manifest_retry_count` flag, clear on success
- `reply_hold_failed` is still used for the customer-facing reply (it's available here because Step 8 only fires when `booking_confirmed=True`, which means Marina had the confirmation action context and wrote `reply_hold_failed`)

### Step 2: Same API error handling in email_poller.py

Apply the same pattern to email_poller.py Step 5 manifest failure (lines 1135-1171).

Change the block starting at line 1136 (`if not res.get("ok"):`) to match the social_agent.py pattern:

```python
                        if not res.get("ok"):
                            _manifest_error = str(res.get("error", ""))
                            _is_api_error = any(s in _manifest_error for s in (
                                '"code": 404', '"code": 500', '"code": 403', '"code": 401',
                                "'code': 404", "'code': 500", "'code': 403", "'code': 401",
                                'Calendar ID not configured'))
                            bm_logger.log(
                                "hold_failed",
                                email=from_email, subject=subj,
                                error=_manifest_error[:200],
                                error_type="api" if _is_api_error else "business",
                                service_name=fields_now.get("service_name"),
                                date=fields_now.get("date"),
                                guests=fields_now.get("guests"),
                            )
                            if th["flags"].get("hold_id"):
                                state_registry.cancel_hold(th["flags"]["hold_id"])
                                _h_svc = th["flags"].pop("hold_service_key", "")
                                _h_date = th["flags"].pop("hold_date", "")
                                _h_dep = th["flags"].pop("hold_slot_time", "")
                                th["flags"].pop("hold_id", None)
                                if _h_svc and _h_date and _h_dep:
                                    gws_calendar.remove_from_manifest(_h_svc, _h_date, _h_dep)
                            th["flags"]["slot_checked"] = False
                            th["flags"]["slot_available"] = False
                            if _is_api_error:
                                _retry_count = th["flags"].get("manifest_retry_count", 0) + 1
                                th["flags"]["manifest_retry_count"] = _retry_count
                                if _retry_count >= 2:
                                    _cname = fields_now.get("customer_name", from_email)
                                    state_registry.create_pending_notification(
                                        'escalation', 'email', from_email, _cname,
                                        f"[SYSTEM] Manifest failure for {_cname} (Email: {from_email})",
                                        f"Booking failed {_retry_count} times due to API error.\n"
                                        f"Error: {_manifest_error[:300]}\n"
                                        f"Fields: {json.dumps(fields_now, indent=2, ensure_ascii=False)}")
                                    bm_logger.log("email_manifest_escalated", email=from_email,
                                                  retry_count=_retry_count)
                                th["flags"]["booking_confirmed"] = False
                                th["flags"]["awaiting_booking_confirmation"] = True
                            failure_reply = result.get("reply_hold_failed") or result["reply"]
                            sheets_writer.log_hold_failed({
                                "email": from_email, "subject": subj,
                                "service_name": fields_now.get("service_name"),
                                "date": fields_now.get("date"),
                                "guests": fields_now.get("guests"),
                                "error": _manifest_error[:200],
                            })
                            smtp_send(from_email, "Re: " + subj, failure_reply,
                                      in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                            log(f"Manifest create FAILED for {from_email}: {_manifest_error[:100]}")
                            im.uid("store", uid, "+FLAGS", r"(\Seen)")
                            th["reply_times"].append(now)
                            th["last_customer_hash"] = customer_hash
                            threads[thread_key] = th
                            save_json(THREAD_STATE_PATH, state)
                            continue
```

Also, in the email_poller SUCCESS path (the `else` block after `if not res.get("ok")`), add one line to clear the retry counter:
```python
                            th["flags"].pop("manifest_retry_count", None)
```
Add this right after `th["flags"]["hold_created"] = True`.

## Tests

File: `tests/social/test_139_error_handling.py`

1. **test_wa_manifest_api_error_allows_retry** — Set up booking state with `booking_confirmed=True`, `awaiting_booking_confirmation=True`, `slot_checked=True`, `hold_id` set. Mock Marina with `reply_hold_failed="Sorry about that!"`. Mock `create_or_update_manifest` to return `{'ok': False, 'error': '{"code": 404, "message": "Not Found"}'}`. Verify: `booking_confirmed` reset to False, `awaiting_booking_confirmation` set to True, `manifest_retry_count` set to 1.

2. **test_wa_manifest_business_error_no_retry** — Same setup but manifest returns `{'ok': False, 'error': 'No service_key in fields.'}`. Verify: `booking_confirmed` stays True (not reset), no `manifest_retry_count` flag.

3. **test_wa_manifest_api_error_escalates_after_2** — Set up state with `manifest_retry_count=1` already. Mock manifest to return 404 again. Verify: escalation created with "[SYSTEM] Manifest failure" subject, `manifest_retry_count` now 2.

4. **test_wa_manifest_api_error_hold_cancelled** — Mock manifest to return 404. Verify: `cancel_hold` was called, hold flags cleared, `slot_checked` reset to False.

5. **test_wa_manifest_success_clears_retry_count** — Set up state with `manifest_retry_count=1`. Mock manifest to return `{'ok': True, 'eventId': 'e1', 'htmlLink': 'http://cal/e1'}`. Verify: booking succeeds (hold_created=True) AND `manifest_retry_count` is no longer in flags (cleared).

6. **test_wa_manifest_api_error_single_quote_detection** — Mock manifest to return `{'ok': False, 'error': str({'code': 404, 'message': 'Not Found'})}` (single-quote Python dict format). Verify: detected as API error (booking_confirmed reset, awaiting_booking_confirmation set to True).

## Success Condition

Manifest API errors (404, 500, 403, 401, config errors) allow the customer to retry on their next message. After 2 consecutive API failures, an escalation is created. Non-API errors keep the current behavior. All 6 tests pass.

## Rollback

Revert `social_agent.py` and `email_poller.py`.
