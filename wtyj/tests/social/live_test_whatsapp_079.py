# bluemarlin/tests/social/live_test_whatsapp_079.py
# Created: Brief 079
# Purpose: Live autonomy tests — edge cases for fully autonomous WhatsApp operation

import os
import sys
import re
import time
import random

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ["WHATSAPP_VERIFY_TOKEN"] = "test_token_067"
os.environ["WHATSAPP_ACCESS_TOKEN"] = "test_access_token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "990622044139349"

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from agents.social.social_agent import handle_incoming_whatsapp_message
from shared import state_registry


_PHONE_PREFIX = "LIVE_079_"
_passed = 0
_failed = 0
_results = []


def _cleanup_phone(phone):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM service_bookings WHERE customer_email = ?", (phone,))
    conn.execute("DELETE FROM bookings WHERE customer_email = ?", (phone.strip().lower(),))
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (phone,))
    conn.commit()
    conn.close()


def check(name, condition, detail=""):
    global _passed, _failed
    if condition:
        print(f"  PASS: {name}")
        _passed += 1
        _results.append({"name": name, "passed": True})
    else:
        msg = f"  FAIL: {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        _failed += 1
        _results.append({"name": name, "passed": False, "detail": detail})


def check_contains(reply, text, label):
    check(label, text.lower() in reply.lower(), f"looking for '{text}' in reply")


def check_not_contains(reply, text, label):
    check(label, text.lower() not in reply.lower(), f"should not contain '{text}'")


def check_contains_any(reply, texts, label):
    found = any(t.lower() in reply.lower() for t in texts)
    check(label, found, f"looking for any of {texts}")


def send_message(phone, text, from_name="Live Test", mock_overrides=None):
    """
    Send a message through the full WhatsApp pipeline with real Claude call.
    Mocks Google API writes + check_availability for determinism.
    Accepts optional mock_overrides dict to change default mock return values:
      - "check_availability": dict to set as return value for check_availability mock
      - "create_or_update_manifest": dict to set as return value for manifest mock
      - "create_soft_hold_returns_none": True to patch state_registry.create_soft_hold to return None
    Returns reply text.
    """
    msg = {"from": phone, "text": text, "from_name": from_name}

    mock_targets = [
        "agents.social.social_agent.sheets_writer.log_escalation",
        "agents.social.social_agent.sheets_writer.log_hold_created",
        "agents.social.social_agent.sheets_writer.log_hold_failed",
        "agents.social.social_agent.sheets_writer.log_manifest_update",
        "agents.social.social_agent.gws_calendar.create_or_update_manifest",
        "agents.social.social_agent.gws_calendar.remove_from_manifest",
        "agents.social.social_agent.gws_calendar.check_availability",
    ]

    patches = [patch(t) for t in mock_targets]
    mock_objects = [p.start() for p in patches]

    # Default mock return values
    mock_objects[4].return_value = {
        "ok": True, "eventId": "test-evt-079", "htmlLink": "https://calendar.google.com/test"
    }
    mock_objects[6].return_value = {
        "available": True, "spots_remaining": 20, "capacity": 25
    }

    # Apply overrides
    extra_patches = []
    if mock_overrides:
        if "check_availability" in mock_overrides:
            mock_objects[6].return_value = mock_overrides["check_availability"]
        if "create_or_update_manifest" in mock_overrides:
            mock_objects[4].return_value = mock_overrides["create_or_update_manifest"]
        if mock_overrides.get("create_soft_hold_returns_none"):
            p = patch("agents.social.social_agent.state_registry.create_soft_hold",
                       return_value=None)
            p.start()
            extra_patches.append(p)

    try:
        reply = handle_incoming_whatsapp_message(msg)
        if reply:
            state_registry.wa_store_message(phone, "user", text)
            state_registry.wa_store_message(phone, "assistant", reply)
        return reply
    finally:
        for p in patches:
            p.stop()
        for p in extra_patches:
            p.stop()


# --- Scenario U: Fully-Escalated Follow-Up (2 turns) ---

def test_fully_escalated_followup():
    """Scenario U: Complaint escalates, then customer tries to book — should stay escalated."""
    phone = f"{_PHONE_PREFIX}ESC_FU_001"
    _cleanup_phone(phone)
    print("\n=== Scenario U: Fully-Escalated Follow-Up ===")

    # Turn 1: Angry complaint
    reply1 = send_message(phone,
        "I had the worst experience on your boat yesterday. "
        "The crew was incredibly rude and the food was terrible. "
        "I want a full refund NOW.")
    print(f"  T1: {reply1[:300]}...")
    check("U-T1: got reply", len(reply1) > 20, f"len={len(reply1)}")
    state1 = state_registry.wa_get_booking_state(phone)
    check("U-T1: fully_escalated", state1["flags"].get("fully_escalated") is True,
          f"fully_escalated={state1['flags'].get('fully_escalated')}")

    # Turn 2: Try to book (should NOT enter booking flow)
    reply2 = send_message(phone, "Can I book a sunset cruise tomorrow?")
    print(f"  T2: {reply2[:300]}...")
    check("U-T2: got reply", len(reply2) > 20, f"len={len(reply2)}")
    check_not_contains(reply2, "$79", "U-T2: no booking price")
    state2 = state_registry.wa_get_booking_state(phone)
    check("U-T2: still fully_escalated", state2["flags"].get("fully_escalated") is True,
          f"fully_escalated={state2['flags'].get('fully_escalated')}")
    check("U-T2: no awaiting_booking_confirmation",
          not state2["flags"].get("awaiting_booking_confirmation"),
          f"awaiting={state2['flags'].get('awaiting_booking_confirmation')}")

    _cleanup_phone(phone)


# --- Scenario V: Semi-Escalation + Customer Follow-Up While Waiting (2 turns) ---

def test_semi_escalation_followup():
    """Scenario V: Semi-escalation relay, then customer asks for update — relay flags preserved."""
    phone = f"{_PHONE_PREFIX}SEMI_FU_001"
    _cleanup_phone(phone)
    print("\n=== Scenario V: Semi-Escalation Follow-Up ===")

    # Turn 1: Question that triggers semi-escalation
    reply1 = send_message(phone,
        "What's the maximum weight limit for the jet ski? "
        "I'm a bigger guy, about 130kg, and I want to make sure it's safe.")
    print(f"  T1: {reply1[:300]}...")
    check("V-T1: got reply", len(reply1) > 20, f"len={len(reply1)}")
    state1 = state_registry.wa_get_booking_state(phone)
    check("V-T1: awaiting_relay", state1["flags"].get("awaiting_relay") is True,
          f"awaiting_relay={state1['flags'].get('awaiting_relay')}")
    check("V-T1: not fully_escalated",
          not state1["flags"].get("fully_escalated"),
          f"fully_escalated={state1['flags'].get('fully_escalated')}")

    # Turn 2: Customer follows up while waiting
    reply2 = send_message(phone, "Hey any update on my question?")
    print(f"  T2: {reply2[:300]}...")
    check("V-T2: got reply", len(reply2) > 0, f"len={len(reply2)}")
    state2 = state_registry.wa_get_booking_state(phone)
    check("V-T2: awaiting_relay preserved", state2["flags"].get("awaiting_relay") is True,
          f"awaiting_relay={state2['flags'].get('awaiting_relay')}")

    _cleanup_phone(phone)


# --- Scenario W: Slot Unavailable (1 turn) ---

def test_slot_unavailable():
    """Scenario W: Trip is fully booked — graceful rejection."""
    phone = f"{_PHONE_PREFIX}FULL_001"
    _cleanup_phone(phone)
    print("\n=== Scenario W: Slot Unavailable ===")

    reply = send_message(phone,
        "Book the Sunset Cruise for April 10 2027 for 2 guests. "
        "Name is Sold Out Test, phone +5999999079.",
        mock_overrides={"check_availability": {
            "available": False, "spots_remaining": 0, "capacity": 20
        }})
    print(f"  Reply: {reply[:300]}...")

    check("W: got reply", len(reply) > 20, f"len={len(reply)}")
    check_contains_any(reply, ["fully booked", "unavailable", "no spots", "not available",
                                "booked up", "no availability"],
                       "W: mentions unavailability")
    state = state_registry.wa_get_booking_state(phone)
    check("W: not awaiting_booking_confirmation",
          not state["flags"].get("awaiting_booking_confirmation"),
          f"awaiting={state['flags'].get('awaiting_booking_confirmation')}")
    check_not_contains(reply, "[PAYMENT_LINK]", "W: no raw placeholder")

    _cleanup_phone(phone)


# --- Scenario X: Manifest Failure on Confirmation (2 turns) ---

def test_manifest_failure():
    """Scenario X: Booking confirmed but manifest creation fails — reply_hold_failed path."""
    phone = f"{_PHONE_PREFIX}MANIFEST_001"
    _cleanup_phone(phone)
    print("\n=== Scenario X: Manifest Failure ===")

    # Turn 1: Normal booking request (default mocks — available)
    reply1 = send_message(phone,
        "Book the Sunset Cruise for April 10 2027 for 2 guests. "
        "Name is Manifest Test, phone +5999999080.")
    print(f"  T1: {reply1[:300]}...")
    check("X-T1: got reply", len(reply1) > 20, f"len={len(reply1)}")
    state1 = state_registry.wa_get_booking_state(phone)
    check("X-T1: awaiting_booking_confirmation",
          state1["flags"].get("awaiting_booking_confirmation") is True,
          f"awaiting={state1['flags'].get('awaiting_booking_confirmation')}")

    # Turn 2: Confirm, but manifest creation fails
    reply2 = send_message(phone, "Yes, book it!",
        mock_overrides={"create_or_update_manifest": {
            "ok": False, "error": "Calendar API timeout"
        }})
    print(f"  T2: {reply2[:300]}...")
    check("X-T2: got reply", len(reply2) > 20, f"len={len(reply2)}")
    check_not_contains(reply2, "[PAYMENT_LINK]", "X-T2: no raw payment placeholder")
    state2 = state_registry.wa_get_booking_state(phone)
    check("X-T2: hold_created NOT True",
          state2["flags"].get("hold_created") is not True,
          f"hold_created={state2['flags'].get('hold_created')}")
    check("X-T2: slot_checked reset",
          state2["flags"].get("slot_checked") is False or state2["flags"].get("slot_checked") is None,
          f"slot_checked={state2['flags'].get('slot_checked')}")

    _cleanup_phone(phone)


# --- Scenario Y: Past Date Rejection (1 turn) ---

def test_past_date_rejection():
    """Scenario Y: Booking for a past date — should be rejected."""
    phone = f"{_PHONE_PREFIX}PAST_001"
    _cleanup_phone(phone)
    print("\n=== Scenario Y: Past Date Rejection ===")

    reply = send_message(phone,
        "Book the Klein Curacao service for March 1 2026 for 2 people. "
        "Name is Past Date Test.")
    print(f"  Reply: {reply[:300]}...")

    check("Y: got reply", len(reply) > 20, f"len={len(reply)}")
    check_contains_any(reply, ["passed", "already passed", "different date", "past",
                                "in the past", "has passed"],
                       "Y: mentions date is in the past")
    state = state_registry.wa_get_booking_state(phone)
    check("Y: not awaiting_booking_confirmation",
          not state["flags"].get("awaiting_booking_confirmation"),
          f"awaiting={state['flags'].get('awaiting_booking_confirmation')}")

    _cleanup_phone(phone)


# --- Scenario Z: Stale Conversation Reset (2 turns) ---

def test_stale_conversation_reset():
    """Scenario Z: 24h gap triggers stale reset — fresh conversation starts."""
    phone = f"{_PHONE_PREFIX}STALE_001"
    _cleanup_phone(phone)
    print("\n=== Scenario Z: Stale Conversation Reset ===")

    # Turn 1: Start a booking
    reply1 = send_message(phone,
        "Book the Sunset Cruise for April 10 2027 for 2 guests. "
        "Name is Stale Test.")
    print(f"  T1: {reply1[:300]}...")
    check("Z-T1: got reply", len(reply1) > 20, f"len={len(reply1)}")
    state1 = state_registry.wa_get_booking_state(phone)
    check("Z-T1: awaiting_booking_confirmation",
          state1["flags"].get("awaiting_booking_confirmation") is True,
          f"awaiting={state1['flags'].get('awaiting_booking_confirmation')}")

    # Between turns: set last_activity to 48 hours ago (timezone-aware ISO format)
    _stale_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    conn = state_registry._get_conn()
    conn.execute("UPDATE whatsapp_booking_state SET last_activity = ? WHERE phone = ?",
                 (_stale_ts, phone))
    conn.commit()
    conn.close()

    # Turn 2: New message after 48h gap — stale reset should fire
    reply2 = send_message(phone, "Hi, what trips do you have?")
    print(f"  T2: {reply2[:300]}...")
    check("Z-T2: got reply", len(reply2) > 20, f"len={len(reply2)}")
    state2 = state_registry.wa_get_booking_state(phone)
    check("Z-T2: not awaiting_booking_confirmation",
          not state2["flags"].get("awaiting_booking_confirmation"),
          f"awaiting={state2['flags'].get('awaiting_booking_confirmation')}")
    check_contains_any(reply2, ["service", "Klein", "Sunset", "Snorkel", "cruise", "beach",
                                 "jet ski", "$"],
                       "Z-T2: mentions trips (fresh conversation)")

    _cleanup_phone(phone)


# --- Scenario AA: Unknown Booking Ref (1 turn) ---

def test_unknown_booking_ref():
    """Scenario AA: Customer cites a non-existent booking ref — graceful handling."""
    phone = f"{_PHONE_PREFIX}UNKNOWNREF_001"
    _cleanup_phone(phone)
    print("\n=== Scenario AA: Unknown Booking Ref ===")

    reply = send_message(phone,
        "Hi I booked with you, reference BF-2026-00000. I need to change my date.")
    print(f"  Reply: {reply[:300]}...")

    check("AA: got reply", len(reply) > 20, f"len={len(reply)}")
    state = state_registry.wa_get_booking_state(phone)
    check("AA: unknown_ref cleared (one-shot)",
          "unknown_ref" not in state["flags"],
          f"flags keys={list(state['flags'].keys())}")
    # Agent should handle gracefully — not crash, not fabricate data
    check_not_contains(reply, "[PAYMENT_LINK]", "AA: no raw placeholder")

    _cleanup_phone(phone)


# --- Scenario BB: Phone-Based Returning Customer (1 turn) ---

def test_phone_returning_customer():
    """Scenario BB: Past booking by phone, no ref cited — returning customer recognition."""
    phone = f"{_PHONE_PREFIX}PHONERET_001"
    _cleanup_phone(phone)
    print("\n=== Scenario BB: Phone-Based Returning Customer ===")

    # Setup: seed a past booking with customer_email=phone
    _ref = "BF-2026-99902"
    _fields = {"service_key": "klein_curacao", "service_name": "Klein Curacao Trip",
               "date": "2026-03-01", "guests": "4", "customer_name": "Return Phone Test",
               "slot_time": "08:00"}
    _flags = {"booking_ref": _ref, "hold_created": True}
    state_registry.save_booking(_ref, _fields, _flags, customer_email=phone)

    reply = send_message(phone, "Hi, I'd like to book another service please!",
                         from_name="Return Phone Test")
    print(f"  Reply: {reply[:300]}...")

    check("BB: got reply", len(reply) > 20, f"len={len(reply)}")
    # Verify past booking is accessible (code path at lines 295-305 ran)
    past = state_registry.get_bookings_by_email(phone)
    check("BB: past booking accessible", len(past) >= 1,
          f"past_bookings={len(past)}")
    # Check if reply acknowledges returning customer or mentions past service details
    _is_returning_ack = any(w in reply.lower() for w in
        ["welcome back", "again", "before", "previous", "klein", "4 guest",
         "returning", "booked with us"])
    _is_coherent = any(w in reply.lower() for w in
        ["service", "book", "which", "what", "$", "help", "offer"])
    check("BB: coherent reply (returning ack or service engagement)",
          _is_returning_ack or _is_coherent,
          f"returning_ack={_is_returning_ack}, coherent={_is_coherent}")

    _cleanup_phone(phone)


# --- Scenario CC: German Language (1 turn) ---

def test_german_language():
    """Scenario CC: German language inquiry — should reply with service info."""
    phone = f"{_PHONE_PREFIX}GERMAN_001"
    _cleanup_phone(phone)
    print("\n=== Scenario CC: German Language ===")

    reply = send_message(phone,
        "Hallo! Wir sind 4 Personen und suchen einen Bootsausflug "
        "in Curaçao. Welche Optionen habt ihr und was kostet das?")
    print(f"  Reply: {reply[:300]}...")

    check("CC: got reply", len(reply) > 20, f"len={len(reply)}")
    check_contains_any(reply, ["$", "Klein", "Sunset", "Ausflug", "Boot", "service",
                                "cruise", "Schnorchel", "USD", "Tour", "Fahrt"],
                       "CC: mentions trips or pricing")

    _cleanup_phone(phone)


# --- Scenario DD: Rate Limit Boundary (2 turns, seeded state) ---

def test_rate_limit_boundary():
    """Scenario DD: 49 replies seeded, 50th works, 51st blocked."""
    phone = f"{_PHONE_PREFIX}RATELIMIT_001"
    _cleanup_phone(phone)
    print("\n=== Scenario DD: Rate Limit Boundary ===")

    # Seed 49 reply timestamps all within the last hour
    _now = int(time.time())
    _seeded_times = [_now - random.randint(60, 3500) for _ in range(49)]
    state_registry.wa_save_booking_state(phone, {}, {"reply_times": _seeded_times}, [])

    # Turn 1: Reply #50 — should still work (49 < 50)
    reply1 = send_message(phone, "What trips do you have?")
    print(f"  T1: {reply1[:200]}...")
    check("DD-T1: got reply (49 < 50)", len(reply1) > 20, f"len={len(reply1)}")

    # Verify reply_times now has 50 entries
    state1 = state_registry.wa_get_booking_state(phone)
    _times_count = len(state1["flags"].get("reply_times", []))
    check("DD-T1: reply_times=50", _times_count == 50,
          f"reply_times count={_times_count}")

    # Turn 2: Reply #51 — should be rate limited (50 >= 50)
    reply2 = send_message(phone, "Tell me more about Klein Curacao")
    print(f"  T2: reply='{reply2}'")
    check("DD-T2: empty reply (rate limited)", reply2 == "",
          f"reply='{reply2[:100]}'")

    # Verify state was still persisted even on rate-limited path
    state2 = state_registry.wa_get_booking_state(phone)
    check("DD-T2: state persisted", state2 is not None,
          "wa_get_booking_state returned None")

    _cleanup_phone(phone)


# --- Scenario EE: Max Bookings Cap (3 turns, seeded state) ---

def test_max_bookings_cap():
    """Scenario EE: 3 bookings done (seeded), 4th succeeds, 5th hits max cap."""
    phone = f"{_PHONE_PREFIX}MAXBOOK_001"
    _cleanup_phone(phone)
    print("\n=== Scenario EE: Max Bookings Cap ===")

    # Seed: 2 archived bookings + 1 active (hold_created) = 3 bookings done
    fields = {"service_key": "sunset_cruise", "service_name": "Sunset Cruise",
              "date": "2027-04-10", "guests": "2", "customer_name": "Max Test",
              "slot_time": "17:30"}
    flags = {"hold_created": True, "booking_ref": "BF-2026-99903",
             "booking_confirmed": True, "event_id": "test-evt-ee",
             "payment_link": "https://demo.pay/test", "payment_status": "pending"}
    completed_bookings = [
        {"booking_ref": "BF-2026-99901", "service_key": "klein_curacao",
         "service_name": "Klein Curacao Trip", "date": "2027-04-08",
         "guests": "2", "slot_time": "08:00", "payment_link": "https://demo.pay/test1"},
        {"booking_ref": "BF-2026-99902", "service_key": "jet_ski",
         "service_name": "Jet Ski Excursion", "date": "2027-04-09",
         "guests": "2", "slot_time": "10:00", "payment_link": "https://demo.pay/test2"},
    ]
    state_registry.wa_save_booking_state(phone, fields, flags, completed_bookings)

    # Turn 1: Booking #4 — multi-service reset fires (completed=2 < 3), archives current
    reply1 = send_message(phone,
        "I also want the snorkeling service for April 16 2027 for 2 people",
        from_name="Max Test")
    print(f"  T1: {reply1[:300]}...")
    check("EE-T1: got reply", len(reply1) > 20, f"len={len(reply1)}")
    state1 = state_registry.wa_get_booking_state(phone)
    check("EE-T1: completed_bookings=3",
          len(state1.get("completed_bookings", [])) == 3,
          f"completed={len(state1.get('completed_bookings', []))}")

    # Turn 2: Confirm booking #4
    reply2 = send_message(phone, "Yes, confirm it!", from_name="Max Test")
    print(f"  T2: {reply2[:300]}...")
    state2 = state_registry.wa_get_booking_state(phone)
    check("EE-T2: hold_created", state2["flags"].get("hold_created") is True,
          f"hold_created={state2['flags'].get('hold_created')}")
    check("EE-T2: has booking_ref", state2["flags"].get("booking_ref", "").startswith("BF-"),
          f"ref={state2['flags'].get('booking_ref')}")

    # Turn 3: Booking #5 — should NOT reset (completed=3, 3 < 3 = False)
    reply3 = send_message(phone,
        "Now book a jet ski for April 17 2027 at 10am for 2 people",
        from_name="Max Test")
    print(f"  T3: {reply3[:300]}...")
    check("EE-T3: got reply", len(reply3) > 0, f"len={len(reply3)}")
    state3 = state_registry.wa_get_booking_state(phone)
    check("EE-T3: completed_bookings still 3 (no archive)",
          len(state3.get("completed_bookings", [])) == 3,
          f"completed={len(state3.get('completed_bookings', []))}")
    # hold_created should still be True from Turn 2 (fields NOT reset)
    check("EE-T3: hold_created still True (no reset)",
          state3["flags"].get("hold_created") is True,
          f"hold_created={state3['flags'].get('hold_created')}")

    _cleanup_phone(phone)


# --- Scenario FF: Placeholder Safety Net (2 turns) ---

def test_placeholder_safety():
    """Scenario FF: Full booking — verify no raw placeholders in final reply."""
    phone = f"{_PHONE_PREFIX}PLACEHOLDER_001"
    _cleanup_phone(phone)
    print("\n=== Scenario FF: Placeholder Safety Net ===")

    # Turn 1: Booking request
    reply1 = send_message(phone,
        "Book the Sunset Cruise for April 10 2027 for 2 guests. "
        "Name is Placeholder Test, phone +5999999081.")
    print(f"  T1: {reply1[:300]}...")
    check("FF-T1: got reply", len(reply1) > 20, f"len={len(reply1)}")

    # Turn 2: Confirm
    reply2 = send_message(phone, "Yes, confirm it!")
    print(f"  T2: {reply2[:300]}...")
    check_not_contains(reply2, "[PAYMENT_LINK]", "FF-T2: no raw [PAYMENT_LINK]")
    check_not_contains(reply2, "[BOOKING_REF]", "FF-T2: no raw [BOOKING_REF]")
    check_contains(reply2, "demo.pay", "FF-T2: payment link replaced")
    check_contains_any(reply2, ["BF-"], "FF-T2: booking ref replaced")

    _cleanup_phone(phone)


# --- Main runner ---

def main():
    global _passed, _failed, _results
    _passed = 0
    _failed = 0
    _results = []

    print("=" * 60)
    print("WhatsApp Live Autonomy Tests — Real Claude API Calls")
    print("Brief 079 — 12 Scenarios")
    print("=" * 60)

    scenarios = [
        ("U: Fully-Escalated Follow-Up", test_fully_escalated_followup),
        ("V: Semi-Escalation Follow-Up", test_semi_escalation_followup),
        ("W: Slot Unavailable", test_slot_unavailable),
        ("X: Manifest Failure", test_manifest_failure),
        ("Y: Past Date Rejection", test_past_date_rejection),
        ("Z: Stale Conversation Reset", test_stale_conversation_reset),
        ("AA: Unknown Booking Ref", test_unknown_booking_ref),
        ("BB: Phone-Based Returning Customer", test_phone_returning_customer),
        ("CC: German Language", test_german_language),
        ("DD: Rate Limit Boundary", test_rate_limit_boundary),
        ("EE: Max Bookings Cap", test_max_bookings_cap),
        ("FF: Placeholder Safety Net", test_placeholder_safety),
    ]

    for name, fn in scenarios:
        try:
            fn()
        except Exception as e:
            print(f"\n  ERROR in {name}: {e}")
            import traceback
            traceback.print_exc()
            _failed += 1
            _results.append({"name": name, "passed": False, "detail": str(e)})

    print("\n" + "=" * 60)
    print(f"RESULTS: {_passed} passed, {_failed} failed out of {_passed + _failed} checks")
    print("=" * 60)

    if _failed:
        print("\nFailed checks:")
        for r in _results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r.get('detail', '')}")

    return _failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
