# bluemarlin/tests/social/live_test_whatsapp_089.py
# Created: Brief 089
# Purpose: Real-world conversation flow tests — multi-turn, messy, human-like

import os
import sys
import time
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

from agents.social.social_agent import handle_incoming_whatsapp_message
from shared import state_registry


def _cleanup_phone(phone):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM service_bookings WHERE customer_email = ?", (phone,))
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (phone,))
    conn.execute("DELETE FROM bookings WHERE customer_email = ?", (phone,))
    conn.commit()
    conn.close()


def send(phone, text, from_name="Live Test", mock_overrides=None):
    """Send a message through full pipeline — real Claude, mocked side effects."""
    extra_patches = []
    with patch("agents.social.social_agent.gws_calendar.check_availability",
               return_value={"available": True, "spots_remaining": 20, "capacity": 30}) as m1, \
         patch("agents.social.social_agent.gws_calendar.remove_from_manifest") as m2, \
         patch("agents.social.social_agent.sheets_writer.log_hold_created") as m3, \
         patch("agents.social.social_agent.sheets_writer.log_manifest_update") as m4, \
         patch("agents.social.social_agent.gws_calendar.create_or_update_manifest",
               return_value={"ok": True, "eventId": "test", "htmlLink": "http://test"}) as m5, \
         patch("agents.social.social_agent.sheets_writer.log_escalation") as m6, \
         patch("agents.social.social_agent.sheets_writer.log_hold_failed") as m7:

        if mock_overrides:
            if "check_availability" in mock_overrides:
                m1.return_value = mock_overrides["check_availability"]

        try:
            msg = {"from": phone, "text": text, "from_name": from_name}
            # Store user message (mimics webhook_server behavior after Brief 089)
            state_registry.wa_store_message(phone, "user", text)
            reply = handle_incoming_whatsapp_message(msg)
            if reply:
                state_registry.wa_store_message(phone, "assistant", reply)
            return reply
        finally:
            for p in extra_patches:
                p.stop()


# ============================================================
# SCENARIO A — The Fisher (SR real pattern)
# "i wanna fish" → redirect → explore → decide
# ============================================================
def test_A_fisher_flow():
    phone = "FLOW_089_A"
    _cleanup_phone(phone)

    r1 = send(phone, "hi, i wanna book a service")
    print(f"[A1] {r1[:100]}")
    assert r1 != "", "A1: must reply to greeting+intent"

    r2 = send(phone, "i was thinking of fishing")
    print(f"[A2] {r2[:100]}")
    assert r2 != "", "A2: must reply to fishing question"
    assert "fishing" in r2.lower() or "fish" in r2.lower() or "boat" in r2.lower() or "service" in r2.lower()

    r3 = send(phone, "snorkeling sounds fun, where is that?")
    print(f"[A3] {r3[:100]}")
    assert r3 != "", "A3: must reply to snorkeling location"

    r4 = send(phone, "nah doesnt sound fun, any service where we can just chill?")
    print(f"[A4] {r4[:100]}")
    assert r4 != "", "A4: must reply to chill recommendation"
    # Should suggest Klein or Sunset — the relaxed ones
    assert "klein" in r4.lower() or "sunset" in r4.lower() or "beach" in r4.lower()

    _cleanup_phone(phone)


# ============================================================
# SCENARIO B — Mid-Booking FAQ (real pattern: "where is mood/tomatoes?")
# Book → get summary → ask about departure point → continue
# ============================================================
def test_B_mid_booking_faq():
    phone = "FLOW_089_B"
    _cleanup_phone(phone)

    r1 = send(phone, "west coast beach service next sunday for 3 people")
    print(f"[B1] {r1[:100]}")
    assert r1 != "", "B1: must reply"
    assert "Just to confirm" in r1 or "sunday" in r1.lower() or "West Coast" in r1

    r2 = send(phone, "where do you leave from?")
    print(f"[B2] {r2[:100]}")
    assert r2 != "", "B2: must answer departure point question"
    # Should mention Mood/Tomatoes — it's in the service data
    assert "mood" in r2.lower() or "tomato" in r2.lower() or "depart" in r2.lower()

    r3 = send(phone, "ok yes book it")
    print(f"[B3] {r3[:100]}")
    assert r3 != "", "B3: must reply to confirmation"

    _cleanup_phone(phone)


# ============================================================
# SCENARIO C — Typos and Slang (real patterns from SR)
# "jeet skio?", "helo", "u there?"
# ============================================================
def test_C_typos_and_slang():
    phone = "FLOW_089_C"
    _cleanup_phone(phone)

    r1 = send(phone, "helo")
    print(f"[C1] {r1[:100]}")
    assert r1 != "", "C1: must reply to typo greeting"

    r2 = send(phone, "jeet skio?")
    print(f"[C2] {r2[:100]}")
    assert r2 != "", "C2: must handle jet ski typo"
    # Should understand as jet ski
    assert "jet" in r2.lower() or "ski" in r2.lower() or "service" in r2.lower()

    r3 = send(phone, "ya how much")
    print(f"[C3] {r3[:100]}")
    assert r3 != "", "C3: must reply to price question"
    assert "135" in r3 or "price" in r3.lower() or "$" in r3

    _cleanup_phone(phone)


# ============================================================
# SCENARIO D — Semi-Escalation Then Book (must not be stuck)
# FAQ question → semi-escalation → book anyway
# ============================================================
def test_D_semi_then_book():
    phone = "FLOW_089_D"
    _cleanup_phone(phone)

    r1 = send(phone, "what's the weight limit for jet ski?")
    print(f"[D1] {r1[:100]}")
    assert r1 != "", "D1: must reply"
    # Should be semi-escalation or a direct answer
    state = state_registry.wa_get_booking_state(phone)
    was_semi = state["flags"].get("awaiting_relay", False)
    print(f"[D1] semi_escalation={was_semi}")

    # Customer doesn't wait for relay — books anyway
    r2 = send(phone, "doesnt matter, book jet ski for tomorrow 10am for 2 people, name is John")
    print(f"[D2] {r2[:100]}")
    assert r2 != "", "D2: must process booking (not stuck in relay mode)"
    # Should be a booking summary or asking for confirmation
    assert "jet ski" in r2.lower() or "Just to confirm" in r2 or "10:00" in r2 or "tomorrow" in r2.lower()

    _cleanup_phone(phone)


# ============================================================
# SCENARIO E — Decline Then Come Back (real pattern)
# Book → no → no really → actually yes
# ============================================================
def test_E_decline_then_comeback():
    phone = "FLOW_089_E"
    _cleanup_phone(phone)

    r1 = send(phone, "sunset cruise next saturday for 4, name is Test")
    print(f"[E1] {r1[:100]}")
    assert "Just to confirm" in r1, "E1: should show booking summary"

    r2 = send(phone, "no")
    print(f"[E2] {r2[:100]}")
    assert r2 != "", "E2: must reply to decline"
    assert "Just to confirm" not in r2, "E2: must NOT re-send summary"

    r3 = send(phone, "no i really dont want it")
    print(f"[E3] {r3[:100]}")
    assert r3 != "", "E3: must reply"
    assert "Just to confirm" not in r3, "E3: must NOT re-send summary"

    r4 = send(phone, "actually wait, book it")
    print(f"[E4] {r4[:100]}")
    assert r4 != "", "E4: must reply to comeback"
    # Should either re-show summary or confirm — not stuck

    _cleanup_phone(phone)


# ============================================================
# SCENARIO F — Topic Switch Chaos (Benson pattern)
# Start sunset → switch to klein → switch back → switch to jet ski
# ============================================================
def test_F_topic_switch():
    phone = "FLOW_089_F"
    _cleanup_phone(phone)

    r1 = send(phone, "sunset cruise next thursday for 2")
    print(f"[F1] {r1[:100]}")
    assert r1 != "", "F1: must reply"

    r2 = send(phone, "actually forget that, tell me about klein curacao")
    print(f"[F2] {r2[:100]}")
    assert r2 != "", "F2: must reply"
    assert "Just to confirm" not in r2, "F2: must not re-send sunset summary"
    assert "klein" in r2.lower() or "island" in r2.lower()

    r3 = send(phone, "nah, jet ski instead, tomorrow 10am for 2")
    print(f"[F3] {r3[:100]}")
    assert r3 != "", "F3: must reply"
    # Should be jet ski booking now
    assert "jet ski" in r3.lower() or "Just to confirm" in r3 or "10:00" in r3

    _cleanup_phone(phone)


# ============================================================
# SCENARIO G — Every Message Gets a Reply (the core promise)
# 10 varied messages — ZERO empty replies
# ============================================================
def test_G_no_silence():
    phone = "FLOW_089_G"
    _cleanup_phone(phone)

    messages = [
        "hi",
        "what trips do you have",
        "which one is the cheapest",
        "is there food included",
        "do you guys have wifi on the boat",
        "what about seasickness",
        "can i bring my dog",
        "ok book the sunset for 2 next friday",
        "actually make it 3",
        "whats the cancellation policy",
    ]

    empty_count = 0
    for i, msg in enumerate(messages):
        reply = send(phone, msg)
        label = f"[G{i+1}]"
        print(f"{label} '{msg}' → {reply[:80] if reply else 'EMPTY'}")
        if not reply:
            empty_count += 1

    assert empty_count == 0, f"G: {empty_count} messages got no reply — must be ZERO"
    _cleanup_phone(phone)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
