# test_141_booking_ux.py — Booking UX + Email Config
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test")

from shared import config_loader


# --- Test 1: Booking summary says "check availability" not "book" ---
def test_booking_summary_says_check_availability():
    from agents.social.social_agent import _build_booking_summary
    service = config_loader.get_service("sunset_cruise")
    fields = {
        "service_key": "sunset_cruise",
        "date": "2026-04-10",
        "guests": "2",
        "slot_time": "17:30",
    }
    summary = _build_booking_summary(fields, service)
    assert "check availability" in summary.lower() or "hold a spot" in summary.lower(), \
        f"Summary should mention checking availability, got: {summary}"
    assert "go ahead and book" not in summary.lower(), \
        f"Summary should NOT say 'go ahead and book', got: {summary}"


# --- Test 2: Action context mentions availability check ---
def test_action_context_mentions_availability():
    from agents.social.social_agent import _build_action_context
    ctx = _build_action_context({"awaiting_booking_confirmation": True})
    assert "check availability" in ctx.lower(), \
        f"Action context should mention availability check, got: {ctx[:200]}"
    # Should NOT say the old wording
    assert "A booking summary was sent. The customer is replying. Determine" not in ctx, \
        f"Action context still has old wording"


# --- Test 3: DM agent uses booking_email from config ---
def test_dm_agent_uses_booking_email():
    raw = config_loader._cache
    original = raw.get("business", {}).get("booking_email")
    raw.setdefault("business", {})["booking_email"] = "test-booking@demo.com"
    try:
        from agents.social.dm_agent import _build_dm_system_prompt
        prompt = _build_dm_system_prompt("instagram_dm")
        assert "test-booking@demo.com" in prompt, \
            f"DM prompt should use booking_email, got email section: {[l for l in prompt.split(chr(10)) if 'email' in l.lower() or 'book' in l.lower()]}"
    finally:
        if original is not None:
            raw["business"]["booking_email"] = original
        else:
            raw["business"].pop("booking_email", None)


# --- Test 4: DM agent falls back to business.email ---
def test_dm_agent_falls_back_to_email():
    raw = config_loader._cache
    original_booking = raw.get("business", {}).pop("booking_email", None)
    original_email = raw.get("business", {}).get("email")
    try:
        from agents.social.dm_agent import _build_dm_system_prompt
        prompt = _build_dm_system_prompt("instagram_dm")
        if original_email:
            assert original_email in prompt, \
                f"DM prompt should fall back to business.email ({original_email})"
    finally:
        if original_booking is not None:
            raw.setdefault("business", {})["booking_email"] = original_booking
