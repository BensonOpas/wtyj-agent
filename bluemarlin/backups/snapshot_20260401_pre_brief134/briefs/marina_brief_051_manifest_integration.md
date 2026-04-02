# BRIEF 051 — Integration: rewire booking flow + payment fix
**Status:** Draft | **Files:** `src/email_poller.py`, `src/payment_stub.py` | **Depends on:** Brief 050 | **Blocks:** Brief 052

## Context

Brief 050 added the manifest foundation — new SQLite tables, new calendar functions (`create_or_update_manifest`, `update_manifest`, `remove_from_manifest`). But the booking flow in `email_poller.py` still calls `gws_calendar.create_hold()` (one event per customer) and `payment_stub.generate_payment_link(event_id, ...)` (event_id-based). This brief rewires the booking flow to use manifests and fixes the payment key.

## Why This Approach

The rewiring is surgical — only the call sites change, not the overall flow structure. Three specific changes:
1. **Step 3b**: Pass customer info to `create_soft_hold()` + store slot info in flags for cancellation use
2. **Step 5**: Generate `booking_ref` earlier, call `create_or_update_manifest` instead of `create_hold`, switch payment key to `booking_ref`
3. **Cancel sites**: Call `remove_from_manifest()` to keep the calendar event in sync

`payment_stub.py` must switch from `event_id` to `booking_ref` because with manifests, all customers on the same slot share one calendar event_id — using it as the payment key would cause collisions for same-price bookings.

## Source Material

### Current Step 3b — soft hold creation (email_poller.py lines 586-597)
```python
                    if avail.get("available"):
                        hold_id = state_registry.create_soft_hold(
                            _ck_trip,
                            fields_for_check.get("date", ""),
                            _ck_start,
                            _ck_guests,
                            avail.get("capacity", 20)
                        )
                        if hold_id is not None:
                            th["flags"]["hold_id"] = hold_id
                            log(f"Soft hold created for {from_email}: hold_id={hold_id}, "
                                f"spots_remaining={avail.get('spots_remaining')}")
```

### Current Step 5 — booking success path (email_poller.py lines 785-834)
```python
                        else:
                            th["flags"]["hold_created"] = True
                            if th["flags"].get("hold_id"):
                                state_registry.confirm_hold(th["flags"]["hold_id"])
                            th["flags"]["event_id"] = res.get("eventId")
                            th["flags"]["event_link"] = res.get("htmlLink")
                            event_id = th["flags"]["event_id"]
                            trip_key = fields_now.get("trip_key", "")
                            price_usd = (config_loader.get_trip(trip_key).get("price_adult_usd", 0)
                                         if trip_key else 0)
                            pay = payment_stub.generate_payment_link(event_id, price_usd)
                            pay_link = f"https://demo.pay/bluemarlin/{pay['payment_id']}"
                            th["flags"]["payment_id"] = pay.get("payment_id")
                            th["flags"]["payment_link"] = pay_link
                            th["flags"]["payment_status"] = pay.get("status")
                            reply_text = reply_text.replace("[PAYMENT_LINK]", pay_link)
                            booking_ref = f"BF-{time.strftime('%Y')}-{int(time.time()) % 100000:05d}"
                            th["flags"]["booking_ref"] = booking_ref
```

### Current cancel site 544 (change detection)
```python
                    if th["flags"].get("hold_id"):
                        state_registry.cancel_hold(th["flags"]["hold_id"])
                        th["flags"].pop("hold_id", None)
```

### Current cancel site 629 (semi-escalation)
```python
                    if th["flags"].get("hold_id"):
                        state_registry.cancel_hold(th["flags"]["hold_id"])
                        th["flags"].pop("hold_id", None)
```

### Current cancel site 767 (hold creation failed)
```python
                            if th["flags"].get("hold_id"):
                                state_registry.cancel_hold(th["flags"]["hold_id"])
```

### Current Step 5 — calendar call (email_poller.py line 756)
```python
                        res = gws_calendar.create_hold(fields_now)
```

### Current payment_stub.py — generate_payment_link signature (line 21)
```python
def generate_payment_link(event_id: str, amount_usd: int) -> dict:
```

### Current payment_stub.py — mark_paid signature (line 51)
```python
def mark_paid(event_id: str):
```

## Instructions

### Step 1 — Update `payment_stub.py`: switch from event_id to booking_ref

**1a.** Replace the `generate_payment_link` function (lines 21-48):

Replace:
```python
def generate_payment_link(event_id: str, amount_usd: int) -> dict:
    """
    Deterministic payment link generator.
    One event_id -> exactly one payment link.
    """

    state = _load()

    if event_id in state["payments"]:
        return state["payments"][event_id]

    raw = f"{event_id}|{amount_usd}"
    payment_id = hashlib.sha256(raw.encode()).hexdigest()[:12]

    link = f"https://demo.pay/bluemarlin/{payment_id}"

    payment_record = {
        "payment_id": payment_id,
        "event_id": event_id,
        "amount_usd": amount_usd,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }

    state["payments"][event_id] = payment_record
    _save(state)

    return payment_record
```

With:
```python
def generate_payment_link(booking_ref: str, amount_usd: int) -> dict:
    """
    Deterministic payment link generator.
    One booking_ref -> exactly one payment link.
    """

    state = _load()

    if booking_ref in state["payments"]:
        return state["payments"][booking_ref]

    raw = f"{booking_ref}|{amount_usd}"
    payment_id = hashlib.sha256(raw.encode()).hexdigest()[:12]

    link = f"https://demo.pay/bluemarlin/{payment_id}"

    payment_record = {
        "payment_id": payment_id,
        "booking_ref": booking_ref,
        "amount_usd": amount_usd,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }

    state["payments"][booking_ref] = payment_record
    _save(state)

    return payment_record
```

**1b.** Replace the `mark_paid` function (lines 51-57):

Replace:
```python
def mark_paid(event_id: str):
    state = _load()
    if event_id in state["payments"]:
        state["payments"][event_id]["status"] = "paid"
        _save(state)
        return True
    return False
```

With:
```python
def mark_paid(booking_ref: str):
    state = _load()
    if booking_ref in state["payments"]:
        state["payments"][booking_ref]["status"] = "paid"
        _save(state)
        return True
    return False
```

### Step 2 — Update Step 3b: pass customer info + store slot in flags

In `email_poller.py`, replace the soft hold creation block (lines 586-597):

Replace:
```python
                    if avail.get("available"):
                        hold_id = state_registry.create_soft_hold(
                            _ck_trip,
                            fields_for_check.get("date", ""),
                            _ck_start,
                            _ck_guests,
                            avail.get("capacity", 20)
                        )
                        if hold_id is not None:
                            th["flags"]["hold_id"] = hold_id
                            log(f"Soft hold created for {from_email}: hold_id={hold_id}, "
                                f"spots_remaining={avail.get('spots_remaining')}")
```

With:
```python
                    if avail.get("available"):
                        hold_id = state_registry.create_soft_hold(
                            _ck_trip,
                            fields_for_check.get("date", ""),
                            _ck_start,
                            _ck_guests,
                            avail.get("capacity", 20),
                            customer_name=th["fields"].get("customer_name", ""),
                            customer_email=from_email,
                        )
                        if hold_id is not None:
                            th["flags"]["hold_id"] = hold_id
                            th["flags"]["hold_trip_key"] = _ck_trip
                            th["flags"]["hold_date"] = fields_for_check.get("date", "")
                            th["flags"]["hold_departure_time"] = _ck_start
                            log(f"Soft hold created for {from_email}: hold_id={hold_id}, "
                                f"spots_remaining={avail.get('spots_remaining')}")
```

### Step 3 — Update cancel site 544 (change detection)

Replace (lines 543-545):
```python
                    if th["flags"].get("hold_id"):
                        state_registry.cancel_hold(th["flags"]["hold_id"])
                        th["flags"].pop("hold_id", None)
```

With:
```python
                    if th["flags"].get("hold_id"):
                        state_registry.cancel_hold(th["flags"]["hold_id"])
                        _h_trip = th["flags"].pop("hold_trip_key", "")
                        _h_date = th["flags"].pop("hold_date", "")
                        _h_dep = th["flags"].pop("hold_departure_time", "")
                        th["flags"].pop("hold_id", None)
                        if _h_trip and _h_date and _h_dep:
                            gws_calendar.remove_from_manifest(_h_trip, _h_date, _h_dep)
```

### Step 4 — Update cancel site 629 (semi-escalation)

Replace (lines 628-630):
```python
                    if th["flags"].get("hold_id"):
                        state_registry.cancel_hold(th["flags"]["hold_id"])
                        th["flags"].pop("hold_id", None)
```

With:
```python
                    if th["flags"].get("hold_id"):
                        state_registry.cancel_hold(th["flags"]["hold_id"])
                        _h_trip = th["flags"].pop("hold_trip_key", "")
                        _h_date = th["flags"].pop("hold_date", "")
                        _h_dep = th["flags"].pop("hold_departure_time", "")
                        th["flags"].pop("hold_id", None)
                        if _h_trip and _h_date and _h_dep:
                            gws_calendar.remove_from_manifest(_h_trip, _h_date, _h_dep)
```

### Step 5 — Rewire Step 5 booking success path

Replace the calendar call and everything after it in the success path (lines 756, 785-834). The full replacement block:

Replace:
```python
                        res = gws_calendar.create_hold(fields_now)
                        if not res.get("ok"):
                            bm_logger.log(
                                "hold_failed",
                                email=from_email, subject=subj,
                                error=res.get("error"),
                                experience=fields_now.get("experience"),
                                date=fields_now.get("date"),
                                guests=fields_now.get("guests"),
                            )
                            if th["flags"].get("hold_id"):
                                state_registry.cancel_hold(th["flags"]["hold_id"])
                            sheets_writer.log_hold_failed({
                                "email": from_email, "subject": subj,
                                "experience": fields_now.get("experience"),
                                "date": fields_now.get("date"),
                                "guests": fields_now.get("guests"),
                                "error": res.get("error"),
                            })
                            failure_reply = result.get("reply_hold_failed") or result["reply"]
                            smtp_send(from_email, "Re: " + subj, failure_reply,
                                      in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                            log(f"Hold create FAILED for {from_email}: {res.get('error')}")
                            im.uid("store", uid, "+FLAGS", r"(\Seen)")
                            th["reply_times"].append(now)
                            th["last_customer_hash"] = customer_hash
                            threads[thread_key] = th
                            save_json(THREAD_STATE_PATH, state)
                            continue
                        else:
                            th["flags"]["hold_created"] = True
                            if th["flags"].get("hold_id"):
                                state_registry.confirm_hold(th["flags"]["hold_id"])
                            th["flags"]["event_id"] = res.get("eventId")
                            th["flags"]["event_link"] = res.get("htmlLink")
                            event_id = th["flags"]["event_id"]
                            trip_key = fields_now.get("trip_key", "")
                            price_usd = (config_loader.get_trip(trip_key).get("price_adult_usd", 0)
                                         if trip_key else 0)
                            pay = payment_stub.generate_payment_link(event_id, price_usd)
                            pay_link = f"https://demo.pay/bluemarlin/{pay['payment_id']}"
                            th["flags"]["payment_id"] = pay.get("payment_id")
                            th["flags"]["payment_link"] = pay_link
                            th["flags"]["payment_status"] = pay.get("status")
                            reply_text = reply_text.replace("[PAYMENT_LINK]", pay_link)
                            booking_ref = f"BF-{time.strftime('%Y')}-{int(time.time()) % 100000:05d}"
                            th["flags"]["booking_ref"] = booking_ref
                            bm_logger.log(
                                "hold_created",
                                email=from_email, subject=subj,
                                event_id=th["flags"].get("event_id"),
                                html_link=th["flags"].get("event_link"),
                                payment_id=th["flags"].get("payment_id"),
                                payment_link=th["flags"].get("payment_link"),
                                experience=fields_now.get("experience"),
                                date=fields_now.get("date"),
                                guests=fields_now.get("guests"),
                                customer_name=fields_now.get("customer_name"),
                                phone=fields_now.get("phone"),
                                special_requests=fields_now.get("special_requests"),
                            )
                            sheets_writer.log_hold_created({
                                "booking_ref": booking_ref,
                                "email": from_email,
                                "subject": subj,
                                "customer_name": fields_now.get("customer_name"),
                                "experience": fields_now.get("experience"),
                                "trip_key": fields_now.get("trip_key"),
                                "date": fields_now.get("date"),
                                "guests": fields_now.get("guests"),
                                "departure_time": fields_now.get("departure_time"),
                                "phone": fields_now.get("phone"),
                                "special_requests": fields_now.get("special_requests"),
                                "total_price": int(fields_now.get("guests") or 0) * price_usd,
                                "html_link": th["flags"].get("event_link"),
                                "payment_link": th["flags"].get("payment_link"),
                                "payment_status": pay.get("status"),
                            })
                            log(f"Hold CREATED for {from_email}: eventId={res.get('eventId')}")
```

With:
```python
                        # Generate booking_ref + set on soft hold BEFORE manifest creation
                        booking_ref = f"BF-{time.strftime('%Y')}-{int(time.time()) % 100000:05d}"
                        th["flags"]["booking_ref"] = booking_ref
                        if th["flags"].get("hold_id"):
                            state_registry.set_booking_ref(th["flags"]["hold_id"], booking_ref)
                        res = gws_calendar.create_or_update_manifest(fields_now)
                        if not res.get("ok"):
                            bm_logger.log(
                                "hold_failed",
                                email=from_email, subject=subj,
                                error=res.get("error"),
                                experience=fields_now.get("experience"),
                                date=fields_now.get("date"),
                                guests=fields_now.get("guests"),
                            )
                            if th["flags"].get("hold_id"):
                                state_registry.cancel_hold(th["flags"]["hold_id"])
                                _h_trip = th["flags"].pop("hold_trip_key", "")
                                _h_date = th["flags"].pop("hold_date", "")
                                _h_dep = th["flags"].pop("hold_departure_time", "")
                                th["flags"].pop("hold_id", None)
                                if _h_trip and _h_date and _h_dep:
                                    gws_calendar.remove_from_manifest(_h_trip, _h_date, _h_dep)
                            th["flags"]["slot_checked"] = False
                            th["flags"]["slot_available"] = False
                            sheets_writer.log_hold_failed({
                                "email": from_email, "subject": subj,
                                "experience": fields_now.get("experience"),
                                "date": fields_now.get("date"),
                                "guests": fields_now.get("guests"),
                                "error": res.get("error"),
                            })
                            failure_reply = result.get("reply_hold_failed") or result["reply"]
                            smtp_send(from_email, "Re: " + subj, failure_reply,
                                      in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                            log(f"Manifest create FAILED for {from_email}: {res.get('error')}")
                            im.uid("store", uid, "+FLAGS", r"(\Seen)")
                            th["reply_times"].append(now)
                            th["last_customer_hash"] = customer_hash
                            threads[thread_key] = th
                            save_json(THREAD_STATE_PATH, state)
                            continue
                        else:
                            th["flags"]["hold_created"] = True
                            if th["flags"].get("hold_id"):
                                state_registry.confirm_hold(th["flags"]["hold_id"])
                            th["flags"]["event_id"] = res.get("eventId")
                            th["flags"]["event_link"] = res.get("htmlLink")
                            trip_key = fields_now.get("trip_key", "")
                            price_usd = (config_loader.get_trip(trip_key).get("price_adult_usd", 0)
                                         if trip_key else 0)
                            pay = payment_stub.generate_payment_link(booking_ref, price_usd)
                            pay_link = f"https://demo.pay/bluemarlin/{pay['payment_id']}"
                            th["flags"]["payment_id"] = pay.get("payment_id")
                            th["flags"]["payment_link"] = pay_link
                            th["flags"]["payment_status"] = pay.get("status")
                            reply_text = reply_text.replace("[PAYMENT_LINK]", pay_link)
                            bm_logger.log(
                                "hold_created",
                                email=from_email, subject=subj,
                                event_id=th["flags"].get("event_id"),
                                html_link=th["flags"].get("event_link"),
                                payment_id=th["flags"].get("payment_id"),
                                payment_link=th["flags"].get("payment_link"),
                                experience=fields_now.get("experience"),
                                date=fields_now.get("date"),
                                guests=fields_now.get("guests"),
                                customer_name=fields_now.get("customer_name"),
                                phone=fields_now.get("phone"),
                                special_requests=fields_now.get("special_requests"),
                            )
                            sheets_writer.log_hold_created({
                                "booking_ref": booking_ref,
                                "email": from_email,
                                "subject": subj,
                                "customer_name": fields_now.get("customer_name"),
                                "experience": fields_now.get("experience"),
                                "trip_key": fields_now.get("trip_key"),
                                "date": fields_now.get("date"),
                                "guests": fields_now.get("guests"),
                                "departure_time": fields_now.get("departure_time"),
                                "phone": fields_now.get("phone"),
                                "special_requests": fields_now.get("special_requests"),
                                "total_price": int(fields_now.get("guests") or 0) * price_usd,
                                "html_link": th["flags"].get("event_link"),
                                "payment_link": th["flags"].get("payment_link"),
                                "payment_status": pay.get("status"),
                            })
                            log(f"Manifest CREATED/UPDATED for {from_email}: eventId={res.get('eventId')}")
```

### Step 6 — Update file headers

**email_poller.py line 4:** Change `# LAST MODIFIED: Brief 048` to `# LAST MODIFIED: Brief 051`

**payment_stub.py:** Add file header at line 1 (currently has none):
Insert before `import hashlib`:
```python
# FILE: payment_stub.py
# CREATED: Before Brief 001 (original codebase)
# LAST MODIFIED: Brief 051
# DEPENDS ON: nothing
# CALLERS: email_poller.py
```

## Tests

```python
#!/usr/bin/env python3
"""Tests for Brief 051 — Manifest integration."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        print(f"  {name} PASS")
        passed += 1
    else:
        print(f"  {name} FAIL")
        failed += 1

print("Running Brief 051 tests...")

# ── payment_stub: booking_ref API ──

import payment_stub
import inspect

# T1: generate_payment_link parameter is booking_ref not event_id
sig = inspect.signature(payment_stub.generate_payment_link)
params = list(sig.parameters.keys())
check("T1: generate_payment_link param is booking_ref", params[0] == "booking_ref")

# T2: mark_paid parameter is booking_ref not event_id
sig2 = inspect.signature(payment_stub.mark_paid)
params2 = list(sig2.parameters.keys())
check("T2: mark_paid param is booking_ref", params2[0] == "booking_ref")

# T3: generate_payment_link returns booking_ref in record
pay = payment_stub.generate_payment_link("BF-2099-99999", 120)
check("T3: payment record has booking_ref key", "booking_ref" in pay and pay["booking_ref"] == "BF-2099-99999")

# T4: payment record does NOT have event_id key
check("T4: payment record has no event_id key", "event_id" not in pay)

# T5: payment_id is deterministic from booking_ref
import hashlib
expected_id = hashlib.sha256("BF-2099-99999|120".encode()).hexdigest()[:12]
check("T5: payment_id deterministic from booking_ref", pay["payment_id"] == expected_id)

# T6: two different booking_refs with same amount get different payment_ids
pay2 = payment_stub.generate_payment_link("BF-2099-88888", 120)
check("T6: different booking_refs different payment_ids", pay["payment_id"] != pay2["payment_id"])

# T7: mark_paid works with booking_ref
result = payment_stub.mark_paid("BF-2099-99999")
check("T7: mark_paid returns True for existing", result is True)

# T8: mark_paid returns False for missing
result2 = payment_stub.mark_paid("BF-NONEXISTENT")
check("T8: mark_paid returns False for missing", result2 is False)

# ── email_poller.py source verification ──

with open(os.path.join(os.path.dirname(__file__), "..", "src", "email_poller.py")) as f:
    ep_src = f.read()

# T9: create_or_update_manifest is called (not create_hold)
check("T9: create_or_update_manifest in source",
      "gws_calendar.create_or_update_manifest(fields_now)" in ep_src)

# T10: old create_hold call is removed from Step 5
check("T10: no create_hold call in booking flow",
      "gws_calendar.create_hold(fields_now)" not in ep_src)

# T11: payment_stub uses booking_ref
check("T11: payment_stub.generate_payment_link(booking_ref",
      "payment_stub.generate_payment_link(booking_ref," in ep_src)

# T12: booking_ref generated before manifest call
# Find positions — booking_ref generation must come before create_or_update_manifest
pos_ref = ep_src.find('booking_ref = f"BF-{time.strftime')
pos_manifest = ep_src.find("gws_calendar.create_or_update_manifest")
check("T12: booking_ref before create_or_update_manifest", 0 < pos_ref < pos_manifest)

# T13: set_booking_ref called before manifest
pos_set_ref = ep_src.find("state_registry.set_booking_ref(")
check("T13: set_booking_ref before manifest", 0 < pos_set_ref < pos_manifest)

# T14: customer_name passed to create_soft_hold
check("T14: customer_name= in create_soft_hold call",
      "customer_name=th[\"fields\"].get(\"customer_name\"" in ep_src)

# T15: customer_email passed to create_soft_hold
check("T15: customer_email= in create_soft_hold call",
      "customer_email=from_email" in ep_src)

# T16: hold_trip_key stored in flags
check("T16: hold_trip_key stored", 'th["flags"]["hold_trip_key"]' in ep_src)

# T17: hold_date stored in flags
check("T17: hold_date stored", 'th["flags"]["hold_date"]' in ep_src)

# T18: hold_departure_time stored in flags
check("T18: hold_departure_time stored", 'th["flags"]["hold_departure_time"]' in ep_src)

# T19: remove_from_manifest called at cancel sites
remove_count = ep_src.count("gws_calendar.remove_from_manifest(")
check("T19: remove_from_manifest called 3 times", remove_count == 3)

# T20: file header says Brief 051
check("T20: email_poller header says Brief 051", "Brief 051" in ep_src)

# T21: payment_stub has file header
with open(os.path.join(os.path.dirname(__file__), "..", "src", "payment_stub.py")) as f:
    ps_src = f.read()
check("T21: payment_stub header says Brief 051", "Brief 051" in ps_src)

# T22: Step 5 failure path resets slot_checked (retry safety)
check("T22: slot_checked reset in failure path",
      ep_src.count('th["flags"]["slot_checked"] = False') >= 4)

# T23: Step 5 failure path pops hold_id (retry safety)
# The failure branch must pop hold_id — search for pop("hold_id") between manifest call and FAILED log
_fail_section = ep_src[ep_src.find("Manifest create FAILED")-1200:ep_src.find("Manifest create FAILED")]
check("T23: hold_id popped in Step 5 failure", 'th["flags"].pop("hold_id"' in _fail_section)

# T24: confirm_hold only in success branch (after manifest succeeds)
# confirm_hold should appear AFTER create_or_update_manifest, not before
pos_manifest = ep_src.find("gws_calendar.create_or_update_manifest")
pos_confirm = ep_src.find("state_registry.confirm_hold", pos_manifest)
pos_else = ep_src.find("else:", pos_manifest)
check("T24: confirm_hold after manifest success (in else branch)", pos_confirm > pos_else > pos_manifest)

# ── Cleanup test payment state ──
import json
try:
    with open("payment_state.json", "r") as f:
        pstate = json.load(f)
    for k in ["BF-2099-99999", "BF-2099-88888"]:
        pstate["payments"].pop(k, None)
    with open("payment_state.json", "w") as f:
        json.dump(pstate, f, indent=2)
except Exception:
    pass

print(f"\n{passed}/{passed+failed} tests passed.")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("All tests passed.")
```

## Success Condition

All 24 tests pass. `email_poller.py` calls `create_or_update_manifest` instead of `create_hold`, generates `booking_ref` before the calendar call, passes customer info to `create_soft_hold`, and calls `remove_from_manifest` at all 3 cancel sites. `payment_stub.py` uses `booking_ref` as the key instead of `event_id`.

## Rollback

```bash
git checkout HEAD -- bluemarlin/src/email_poller.py bluemarlin/src/payment_stub.py
```
