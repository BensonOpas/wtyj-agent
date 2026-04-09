"""Tests for Brief 167 — customer-by-identifier endpoint + resolution.

Covers the new GET /customers/by-identifier/{type}/{value} endpoint and the
state_registry.customer_lookup path it uses.
"""
import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from shared import state_registry


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


def test_customer_lookup_returns_full_when_phone_linked():
    """Brief 167: after a wa_conversation_id customer is linked to a real phone,
    customer_lookup by the conversation_id returns a file containing the phone."""
    wa = state_registry.customer_lookup_or_create(
        "wa_conversation_id", "abcdef1234567890abcdef12_b167", display_name="Calvin"
    )
    state_registry.customer_add_identifier(wa["id"], "phone", "+1-555-0199")
    full = state_registry.customer_get_full(wa["id"])
    types = {i["type"] for i in full["identifiers"]}
    assert "wa_conversation_id" in types
    assert "phone" in types
    phone_values = [i["value"] for i in full["identifiers"] if i["type"] == "phone"]
    assert "+1-555-0199" in phone_values
    _cleanup([wa["id"]])


def test_customer_lookup_returns_none_for_unknown_identifier():
    assert state_registry.customer_lookup("phone", "nonexistent_b167") is None


def test_dashboard_endpoint_source_declaration():
    """Brief 167: source-level guard that the endpoint exists in api.py."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard", "api.py")
    src = open(path).read()
    assert '@router.get("/customers/by-identifier/{type_}/{value}"' in src
    assert "customer_lookup" in src
    assert "customer_get_full" in src
