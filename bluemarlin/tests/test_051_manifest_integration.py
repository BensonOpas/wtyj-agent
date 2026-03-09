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
