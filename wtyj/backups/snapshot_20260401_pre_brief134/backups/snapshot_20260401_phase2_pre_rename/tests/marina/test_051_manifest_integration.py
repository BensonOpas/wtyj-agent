"""Tests for Brief 051 — Manifest integration."""
import os
import hashlib
import inspect
import json

from agents.marina import payment_stub


# ── payment_stub: booking_ref API ──

def test_payment_link_param_is_booking_ref():
    """T1: generate_payment_link parameter is booking_ref not event_id."""
    sig = inspect.signature(payment_stub.generate_payment_link)
    params = list(sig.parameters.keys())
    assert params[0] == "booking_ref"


def test_mark_paid_param_is_booking_ref():
    """T2: mark_paid parameter is booking_ref not event_id."""
    sig = inspect.signature(payment_stub.mark_paid)
    params = list(sig.parameters.keys())
    assert params[0] == "booking_ref"


def test_payment_record_has_booking_ref():
    """T3: generate_payment_link returns booking_ref in record."""
    pay = payment_stub.generate_payment_link("BF-2099-99999", 120)
    assert "booking_ref" in pay and pay["booking_ref"] == "BF-2099-99999"
    # cleanup
    _cleanup_payment("BF-2099-99999")


def test_payment_record_no_event_id():
    """T4: payment record does NOT have event_id key."""
    pay = payment_stub.generate_payment_link("BF-2099-99999", 120)
    assert "event_id" not in pay
    _cleanup_payment("BF-2099-99999")


def test_payment_id_deterministic():
    """T5: payment_id is deterministic from booking_ref."""
    pay = payment_stub.generate_payment_link("BF-2099-99999", 120)
    expected_id = hashlib.sha256("BF-2099-99999|120".encode()).hexdigest()[:12]
    assert pay["payment_id"] == expected_id
    _cleanup_payment("BF-2099-99999")


def test_different_refs_different_ids():
    """T6: two different booking_refs with same amount get different payment_ids."""
    pay1 = payment_stub.generate_payment_link("BF-2099-99999", 120)
    pay2 = payment_stub.generate_payment_link("BF-2099-88888", 120)
    assert pay1["payment_id"] != pay2["payment_id"]
    _cleanup_payment("BF-2099-99999")
    _cleanup_payment("BF-2099-88888")


def test_mark_paid_existing():
    """T7: mark_paid works with booking_ref."""
    payment_stub.generate_payment_link("BF-2099-99999", 120)
    result = payment_stub.mark_paid("BF-2099-99999")
    assert result is True
    _cleanup_payment("BF-2099-99999")


def test_mark_paid_missing():
    """T8: mark_paid returns False for missing."""
    result = payment_stub.mark_paid("BF-NONEXISTENT")
    assert result is False


# ── email_poller.py source verification ──

def _read_email_poller():
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "email_poller.py")) as f:
        return f.read()


def test_create_or_update_manifest_in_source():
    """T9: create_or_update_manifest is called."""
    ep_src = _read_email_poller()
    assert "gws_calendar.create_or_update_manifest(fields_now)" in ep_src


def test_no_create_hold_in_booking_flow():
    """T10: old create_hold call is removed from Step 5."""
    ep_src = _read_email_poller()
    assert "gws_calendar.create_hold(fields_now)" not in ep_src


def test_payment_stub_uses_booking_ref():
    """T11: payment_stub uses booking_ref."""
    ep_src = _read_email_poller()
    assert "payment_stub.generate_payment_link(booking_ref," in ep_src


def test_booking_ref_before_manifest():
    """T12: booking_ref generated before manifest call."""
    ep_src = _read_email_poller()
    pos_ref = ep_src.find('booking_ref = f"BF-{time.strftime')
    pos_manifest = ep_src.find("gws_calendar.create_or_update_manifest")
    assert 0 < pos_ref < pos_manifest


def test_set_booking_ref_before_manifest():
    """T13: set_booking_ref called before manifest."""
    ep_src = _read_email_poller()
    pos_set_ref = ep_src.find("state_registry.set_booking_ref(")
    pos_manifest = ep_src.find("gws_calendar.create_or_update_manifest")
    assert 0 < pos_set_ref < pos_manifest


def test_customer_name_in_create_soft_hold():
    """T14: customer_name passed to create_soft_hold."""
    ep_src = _read_email_poller()
    assert 'customer_name=th["fields"].get("customer_name"' in ep_src


def test_customer_email_in_create_soft_hold():
    """T15: customer_email passed to create_soft_hold."""
    ep_src = _read_email_poller()
    assert "customer_email=from_email" in ep_src


def test_hold_trip_key_stored():
    """T16: hold_trip_key stored in flags."""
    ep_src = _read_email_poller()
    assert 'th["flags"]["hold_trip_key"]' in ep_src


def test_hold_date_stored():
    """T17: hold_date stored in flags."""
    ep_src = _read_email_poller()
    assert 'th["flags"]["hold_date"]' in ep_src


def test_hold_departure_time_stored():
    """T18: hold_departure_time stored in flags."""
    ep_src = _read_email_poller()
    assert 'th["flags"]["hold_departure_time"]' in ep_src


def test_remove_from_manifest_count():
    """T19: remove_from_manifest called 3 times."""
    ep_src = _read_email_poller()
    assert ep_src.count("gws_calendar.remove_from_manifest(") == 3


def test_email_poller_header():
    """T20: email_poller header says Brief."""
    ep_src = _read_email_poller()
    assert "Last modified: Brief" in ep_src


def test_payment_stub_header():
    """T21: payment_stub has file header."""
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "payment_stub.py")) as f:
        ps_src = f.read()
    assert "Last modified: Brief" in ps_src


def test_slot_checked_reset_count():
    """T22: slot_checked reset in failure path."""
    ep_src = _read_email_poller()
    assert ep_src.count('th["flags"]["slot_checked"] = False') >= 4


def test_hold_id_popped_in_failure():
    """T23: hold_id popped in Step 5 failure."""
    ep_src = _read_email_poller()
    _fail_section = ep_src[ep_src.find("Manifest create FAILED")-1200:ep_src.find("Manifest create FAILED")]
    assert 'th["flags"].pop("hold_id"' in _fail_section


def test_confirm_hold_after_manifest_success():
    """T24: confirm_hold only in success branch."""
    ep_src = _read_email_poller()
    pos_manifest = ep_src.find("gws_calendar.create_or_update_manifest")
    pos_confirm = ep_src.find("state_registry.confirm_hold", pos_manifest)
    pos_else = ep_src.find("else:", pos_manifest)
    assert pos_confirm > pos_else > pos_manifest


# ── Cleanup helper ──

def _cleanup_payment(ref):
    try:
        with open("payment_state.json", "r") as f:
            pstate = json.load(f)
        pstate["payments"].pop(ref, None)
        with open("payment_state.json", "w") as f:
            json.dump(pstate, f, indent=2)
    except Exception:
        pass
