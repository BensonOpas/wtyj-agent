"""Tests for Brief 178 — email normalization + strengthened cross-channel rule."""
import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

import shared.state_registry as state_registry
from agents.marina import marina_agent


def _cleanup(ids):
    """Same pattern as test_166_customer_file.py — targeted row delete so tests
    don't pollute the shared dev DB."""
    conn = state_registry._get_conn()
    for cid in ids:
        conn.execute("DELETE FROM customer_interactions WHERE customer_id = ?", (cid,))
        conn.execute("DELETE FROM customer_identifiers WHERE customer_id = ?", (cid,))
        conn.execute("DELETE FROM customers WHERE id = ?", (cid,))
        conn.execute(
            "DELETE FROM customer_merges WHERE surviving_id = ? OR absorbed_id = ?",
            (cid, cid),
        )
    conn.commit()
    conn.close()


# ---- _normalize_identifier_value ----

def test_normalize_lowercases_email():
    """Brief 178: _normalize_identifier_value lowercases emails."""
    assert state_registry._normalize_identifier_value("email", "Calvin@Gaimin.io") == "calvin@gaimin.io"
    assert state_registry._normalize_identifier_value("email", "  ASH9772@GMAIL.COM  ") == "ash9772@gmail.com"


def test_normalize_idempotent():
    """Brief 178: running normalization twice yields the same result."""
    once = state_registry._normalize_identifier_value("email", "Calvin@Gaimin.io")
    twice = state_registry._normalize_identifier_value("email", once)
    assert once == twice == "calvin@gaimin.io"


def test_normalize_does_not_lowercase_phone():
    """Brief 178: non-email identifiers are stripped but not lowercased."""
    # phones are typically digits/+ but if they had case, it would be preserved
    assert state_registry._normalize_identifier_value("phone", "  +34 653 445 607  ") == "+34 653 445 607"
    # wa_conversation_id is hex and naturally lowercase — should pass through stripped
    assert state_registry._normalize_identifier_value("wa_conversation_id", " 69d41ae77d2c605d08114697 ") == "69d41ae77d2c605d08114697"


# ---- case-insensitive lookup + create + add_identifier ----

def test_case_insensitive_email_lookup():
    """Brief 178: customer_lookup finds the same row regardless of email case."""
    EMAIL = "test178a@example.test"
    created = state_registry.customer_lookup_or_create(
        "email", EMAIL, display_name="Test 178a"
    )
    try:
        assert state_registry.customer_lookup("email", "Test178A@example.test")["id"] == created["id"]
        assert state_registry.customer_lookup("email", "TEST178A@EXAMPLE.TEST")["id"] == created["id"]
        assert state_registry.customer_lookup("email", f"  {EMAIL}  ")["id"] == created["id"]
    finally:
        _cleanup([created["id"]])


def test_case_insensitive_create_no_duplicate_row():
    """Brief 178: customer_lookup_or_create with a case variant returns the same row."""
    EMAIL_LOWER = "test178b@example.test"
    EMAIL_MIXED = "Test178B@Example.Test"
    a = state_registry.customer_lookup_or_create(
        "email", EMAIL_LOWER, display_name="Test 178b"
    )
    try:
        b = state_registry.customer_lookup_or_create(
            "email", EMAIL_MIXED, display_name="Test 178b"
        )
        assert a["id"] == b["id"]
    finally:
        _cleanup([a["id"]])


def test_add_identifier_merges_case_variants():
    """Brief 178: add_identifier with a case-variant email triggers the merge path.

    Reconstructs Calvin's production scenario: Row A from email (lowercase),
    Row B from WhatsApp (conversation id). When Calvin types his email in
    WhatsApp with a different case, customer_add_identifier should merge
    the two rows instead of adding a second duplicate identifier."""
    EMAIL_LOWER = "test178c@example.test"
    EMAIL_MIXED = "Test178C@Example.Test"
    WA_ID = "178cafebabe178cafebabe99"
    row_a = state_registry.customer_lookup_or_create(
        "email", EMAIL_LOWER, display_name="Test 178c (email)"
    )
    row_b = state_registry.customer_lookup_or_create(
        "wa_conversation_id", WA_ID, display_name="Test 178c (wa)"
    )
    try:
        assert row_a["id"] != row_b["id"]  # start as two separate rows

        result = state_registry.customer_add_identifier(
            row_b["id"], "email", EMAIL_MIXED
        )
        assert result["action"] == "merged"
        # The older row (row_a, created first) wins per _customer_choose_merge_survivor
        assert result["customer_id"] == row_a["id"]
    finally:
        _cleanup([row_a["id"], row_b["id"]])


# ---- cross-channel rule is in the system prompt ----

def test_cross_channel_rule_in_prompt_with_customer_file():
    """Brief 178: CROSS-CHANNEL CONTINUITY rule present when customer_file is populated."""
    cf = {
        "id": 1, "display_name": "Calvin",
        "first_seen": "2026-04-09T00:00:00+00:00",
        "last_seen": "2026-04-09T00:00:00+00:00",
        "identifiers": [{"type": "email", "value": "calvin@gaimin.io", "first_seen": ""}],
        "recent_interactions": [],
    }
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp", customer_file=cf)
    assert "CROSS-CHANNEL CONTINUITY" in prompt
    # At least two of the forbidden phrases are listed
    assert "I can't check emails" in prompt
    assert "no access to the inbox" in prompt
    # The scoping note is present
    assert "FORBIDDEN ONLY in the cross-channel reference context" in prompt


def test_cross_channel_rule_in_prompt_without_customer_file():
    """Brief 178: CROSS-CHANNEL CONTINUITY rule present EVEN when customer_file is empty.

    This is the brand-new-customer case: a customer messaging for the first
    time has no file yet, but if their very first message is 'did you get my
    email?' Marina still needs the rule. The Brief 166 placement (nested in
    the customer file block) failed this case silently."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp", customer_file=None)
    assert "CROSS-CHANNEL CONTINUITY" in prompt
    assert "I can't check emails" in prompt
