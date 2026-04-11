"""Tests for Brief 183 — escalation contact enrichment with real email/phone."""
import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

import shared.state_registry as state_registry


def _cleanup(ids):
    conn = state_registry._get_conn()
    for cid in ids:
        conn.execute("DELETE FROM customer_interactions WHERE customer_id = ?", (cid,))
        conn.execute("DELETE FROM customer_identifiers WHERE customer_id = ?", (cid,))
        conn.execute("DELETE FROM customers WHERE id = ?", (cid,))
        conn.execute("DELETE FROM customer_merges WHERE surviving_id = ? OR absorbed_id = ?", (cid, cid))
    conn.commit()
    conn.close()


def test_lookup_finds_email_for_whatsapp_escalation():
    """Brief 183: WhatsApp escalation (hex conv ID) → finds the customer's email."""
    WA_ID = "183affffffff183affffffff"
    EMAIL = "test183a@example.test"
    row_wa = state_registry.customer_lookup_or_create("wa_conversation_id", WA_ID, display_name="Test183a")
    state_registry.customer_add_identifier(row_wa["id"], "email", EMAIL)
    try:
        contact = state_registry._lookup_customer_contact(WA_ID, "whatsapp")
        assert contact["email"] == EMAIL
    finally:
        _cleanup([row_wa["id"]])


def test_lookup_returns_email_directly_for_email_escalation():
    """Brief 183: email escalation → returns the email even without a customer file."""
    EMAIL = "nocustomer183@example.test"
    contact = state_registry._lookup_customer_contact(EMAIL, "email")
    assert contact["email"] == EMAIL
    assert contact["phone"] is None


def test_lookup_returns_both_when_available():
    """Brief 183: customer with email + phone → both fields populated."""
    WA_ID = "183cffffffff183cffffffff"
    EMAIL = "test183c@example.test"
    PHONE = "+5999999183"
    row = state_registry.customer_lookup_or_create("wa_conversation_id", WA_ID, display_name="Test183c")
    state_registry.customer_add_identifier(row["id"], "email", EMAIL)
    state_registry.customer_add_identifier(row["id"], "phone", PHONE)
    try:
        contact = state_registry._lookup_customer_contact(WA_ID, "whatsapp")
        assert contact["email"] == EMAIL
        assert contact["phone"] == PHONE
    finally:
        _cleanup([row["id"]])


def test_escalation_response_includes_contact_fields():
    """Brief 183: get_all_escalations() returns customer_contact, customer_email, customer_phone."""
    conn = state_registry._get_conn()
    conn.execute(
        "INSERT INTO pending_notifications "
        "(notification_type, channel, customer_id, customer_name, subject, body, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("escalation", "whatsapp", "183dffffffff183dffffffff", "Test183d",
         "[TEST] enrichment test", "body", "pending", "2026-04-10T00:00:00Z")
    )
    test_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    try:
        all_esc = state_registry.get_all_escalations()
        test_esc = next((e for e in all_esc if e["id"] == test_id), None)
        assert test_esc is not None
        assert "customer_contact" in test_esc
        assert "customer_email" in test_esc
        assert "customer_phone" in test_esc
    finally:
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM pending_notifications WHERE id = ?", (test_id,))
        conn.commit()
        conn.close()
