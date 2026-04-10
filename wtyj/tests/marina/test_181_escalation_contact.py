"""Tests for Brief 181 — escalation contact_type + customer display_name update."""
import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

import shared.state_registry as state_registry


def _cleanup(ids):
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


def test_infer_contact_type_email():
    """Brief 181: email address → contact_type 'email'."""
    assert state_registry._infer_contact_type("calvin@gaimin.io") == "email"
    assert state_registry._infer_contact_type("Ash9772@gmail.com") == "email"


def test_infer_contact_type_whatsapp():
    """Brief 181: 24-char hex Zernio conversation ID → contact_type 'whatsapp'."""
    assert state_registry._infer_contact_type("69d42a044b32d4847a2f19d8") == "whatsapp"
    assert state_registry._infer_contact_type("69d7a0b4b76e2a1792e6d173") == "whatsapp"


def test_infer_contact_type_phone():
    """Brief 181: E.164 phone number → contact_type 'phone'."""
    assert state_registry._infer_contact_type("+5999686564") == "phone"
    assert state_registry._infer_contact_type("15155005577") == "phone"


def test_customer_update_display_name():
    """Brief 181: customer_update_display_name persists the new name."""
    row = state_registry.customer_lookup_or_create(
        "email", "test181@example.test", display_name="Old Name"
    )
    try:
        assert row["display_name"] == "Old Name"
        state_registry.customer_update_display_name(row["id"], "New Name")
        # Verify via a fresh lookup
        updated = state_registry.customer_lookup("email", "test181@example.test")
        assert updated["display_name"] == "New Name"
    finally:
        _cleanup([row["id"]])


def test_escalation_response_includes_contact_type():
    """Brief 181: get_all_escalations() includes contact_type field."""
    # Create a test notification
    conn = state_registry._get_conn()
    conn.execute(
        "INSERT INTO pending_notifications "
        "(notification_type, channel, customer_id, customer_name, subject, body, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("escalation", "whatsapp", "69d42a044b32d4847a2f19d8", "Test181",
         "[TEST] test escalation", "test body", "pending", "2026-04-10T00:00:00Z")
    )
    test_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    try:
        all_esc = state_registry.get_all_escalations()
        test_esc = next((e for e in all_esc if e["id"] == test_id), None)
        assert test_esc is not None
        assert "contact_type" in test_esc
        assert test_esc["contact_type"] == "whatsapp"
    finally:
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM pending_notifications WHERE id = ?", (test_id,))
        conn.commit()
        conn.close()
