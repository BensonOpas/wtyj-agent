"""Tests for Brief 161 — per-phone lock, ref regex, multi-language booking flow."""
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("LATE_API_KEY", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test")

from agents.marina import marina_agent


# --- Booking ref regex (Fix 2) ---

_BRIEF161_REF_REGEX = re.compile(r'\b(?=[A-Z0-9]*\d)[A-Z0-9]{6}\b')


def test_ref_regex_matches_real_booking_ref():
    """Real ref BF9999 still matches."""
    assert _BRIEF161_REF_REGEX.search("My booking ref is BF9999, please help") is not None


def test_ref_regex_matches_all_digits():
    """6-digit ref still matches."""
    assert _BRIEF161_REF_REGEX.search("ref 123456 please") is not None


def test_ref_regex_rejects_all_letters_sunset():
    """All-letter SUNSET must not be matched as a ref (the c13 bug)."""
    assert _BRIEF161_REF_REGEX.search("I WANT SUNSET CRUISE FOR 4 FRIDAY") is None


def test_ref_regex_rejects_all_letters_common_words():
    """Common shout words that used to false-positive."""
    for word in ("FRIDAY", "CRUISE", "SUNSET", "CASTLE", "ACTION"):
        assert _BRIEF161_REF_REGEX.search(f"I want {word}") is None, f"false positive on {word}"


def test_ref_regex_matches_mixed_letters_and_digit():
    """Real-world ref shapes with digit + letters."""
    for ref in ("BF9999", "AB1234", "XY9Z8W", "A1B2C3"):
        assert _BRIEF161_REF_REGEX.search(f"ref {ref}") is not None, f"missed {ref}"


# --- Per-phone lock (Fix 1) ---

def test_get_phone_lock_returns_same_lock_for_same_key():
    """Calling _get_phone_lock twice for the same key returns the same lock object."""
    from agents.social.webhook_server import _get_phone_lock
    lock_a1 = _get_phone_lock("TEST_BRIEF161_KEY_A")
    lock_a2 = _get_phone_lock("TEST_BRIEF161_KEY_A")
    lock_b = _get_phone_lock("TEST_BRIEF161_KEY_B")
    assert lock_a1 is lock_a2
    assert lock_a1 is not lock_b


def test_per_phone_lock_serializes_concurrent_handlers():
    """Two concurrent handler-style calls for the same phone run one at a time.
    This is the regression test for the a1 race condition from the 2026-04-08 E2E run."""
    from agents.social.webhook_server import _get_phone_lock

    key = "BRIEF161_RACE_TEST_KEY"
    lock = _get_phone_lock(key)

    order = []
    start_barrier = threading.Barrier(3)  # 2 workers + main thread

    def worker(worker_id):
        start_barrier.wait()
        with lock:
            order.append(f"start_{worker_id}")
            time.sleep(0.05)
            order.append(f"end_{worker_id}")

    t1 = threading.Thread(target=worker, args=("A",))
    t2 = threading.Thread(target=worker, args=("B",))
    t1.start()
    t2.start()
    start_barrier.wait()
    t1.join(timeout=2)
    t2.join(timeout=2)

    # Serialized: each start is immediately followed by its own end — no interleaving
    assert len(order) == 4
    assert order[1] == order[0].replace("start_", "end_")
    assert order[3] == order[2].replace("start_", "end_")


# --- Prompt BOOKING VALIDATION section (Fix 3) ---

def test_prompt_has_booking_validation_section():
    """Brief 161: BOOKING VALIDATION block present in Marina's system prompt."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "BOOKING VALIDATION" in prompt


def test_prompt_mentions_past_date_check():
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "PAST DATE" in prompt or "past date" in prompt.lower()


def test_prompt_mentions_wrong_day_check():
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "WRONG DAY" in prompt or "days_available" in prompt


def test_prompt_mentions_multi_departure_check():
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "MULTI-DEPARTURE" in prompt or "multi-departure" in prompt.lower()


def test_prompt_tells_marina_to_generate_summary():
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "confirmation summary" in prompt.lower()


def test_prompt_demands_exact_prices_no_hallucination():
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "CRITICAL PRICE ACCURACY" in prompt or "EXACT" in prompt


def test_prompt_demands_customer_language():
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "CRITICAL LANGUAGE" in prompt or "customer's detected language" in prompt


def test_prompt_no_longer_claims_python_handles_summary():
    """The old 'Python handles all booking validation, state management, and summary generation' is gone."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "Python handles all booking validation, state management, and summary generation" not in prompt


def test_prompt_validation_section_uses_interpolated_terminology():
    """Brief 161: service_label and party_size_label from client terminology are interpolated.
    For BlueMarlin (service_label='trip', party_size_label='guests')."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    # BlueMarlin terminology
    assert "guests" in prompt
    assert "trip" in prompt


def test_prompt_price_zero_guard_present():
    """Brief 161: prompt instructs Marina to omit the price line when price is zero."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "price is 0" in prompt or "price is greater than zero" in prompt
    assert "OMIT the price line" in prompt or "omit the price" in prompt.lower()


def test_prompt_for_adamus_uses_restaurant_terminology():
    """Brief 161: Adamus terminology (service_label='reservation', party_size_label='diners')
    must flow through the prompt builder.

    IMPORTANT: config_loader captures _CONFIG_PATH at module import time.
    Simply reassigning os.environ['CLIENT_CONFIG_PATH'] after import has NO effect —
    we must directly rewrite config_loader._CONFIG_PATH and clear its cache.
    """
    from shared import config_loader

    adamus_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..",
        "clients", "adamus", "config", "client.json"
    ))
    assert os.path.exists(adamus_path), f"Adamus config not found at {adamus_path}"

    old_path = config_loader._CONFIG_PATH
    old_cache = dict(config_loader._cache)
    config_loader._CONFIG_PATH = adamus_path
    config_loader._cache = {}
    try:
        prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
        # Adamus terminology
        assert "diners" in prompt, f"Expected 'diners' in Adamus prompt"
        assert "reservation" in prompt, f"Expected 'reservation' in Adamus prompt"
        # Adamus has 4 languages (English, Dutch, Spanish, Papiamentu) — not 6.
        # Check language BULLETS specifically, not the whole prompt body.
        lr_start = prompt.find("LANGUAGE RULE:")
        lr_end = prompt.find("BOOKING BEHAVIOUR:")
        lr_block = prompt[lr_start:lr_end]
        # German bullet uses "ich möchte" as its recognition hint
        assert "ich möchte" not in lr_block, "Adamus should not have German language bullet"
        # Portuguese bullet uses "Olá" as its recognition hint
        assert "Olá" not in lr_block, "Adamus should not have Portuguese language bullet"
    finally:
        config_loader._CONFIG_PATH = old_path
        config_loader._cache = old_cache
