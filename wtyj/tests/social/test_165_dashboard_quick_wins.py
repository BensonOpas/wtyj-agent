"""Tests for Brief 165 — dashboard quick wins bundle.

Covers:
- wa_delete_conversation helper deletes rows from both tables
- Idempotent on nonexistent phones
- Scoped to target phone only
- Source-level guard that DELETE endpoint exists in dashboard/api.py
"""
import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from shared import state_registry


def test_wa_delete_conversation_removes_messages_and_state():
    """Brief 165: wa_delete_conversation removes rows from whatsapp_threads and whatsapp_booking_state."""
    phone = "TEST_165_DELETE_001"
    state_registry.wa_delete_conversation(phone)  # cleanup prior runs

    state_registry.wa_store_message(phone, "user", "hello")
    state_registry.wa_store_message(phone, "assistant", "hi back")
    state_registry.wa_save_booking_state(phone, {"customer_name": "TestUser"}, {})

    assert len(state_registry.wa_get_full_history(phone)) == 2

    count = state_registry.wa_delete_conversation(phone)
    assert count >= 3, (
        f"Expected >= 3 rows deleted (2 messages + 1 booking state), got {count}"
    )

    assert state_registry.wa_get_full_history(phone) == []


def test_wa_delete_conversation_nonexistent_phone_returns_zero():
    """Brief 165: deleting a nonexistent conversation returns 0, does not raise."""
    phone = "TEST_165_NOTHING_HERE_001"
    count = state_registry.wa_delete_conversation(phone)
    assert count == 0


def test_wa_delete_conversation_only_affects_target_phone():
    """Brief 165: delete is scoped to the target phone only."""
    p1 = "TEST_165_KEEP_001"
    p2 = "TEST_165_DELETE_002"
    state_registry.wa_delete_conversation(p1)
    state_registry.wa_delete_conversation(p2)

    state_registry.wa_store_message(p1, "user", "keep me")
    state_registry.wa_store_message(p2, "user", "delete me")

    state_registry.wa_delete_conversation(p2)

    assert len(state_registry.wa_get_full_history(p1)) == 1
    assert state_registry.wa_get_full_history(p2) == []

    state_registry.wa_delete_conversation(p1)  # cleanup


def test_dashboard_delete_endpoint_exists():
    """Brief 165: source-level guard that the DELETE endpoint is declared in api.py."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard", "api.py")
    src = open(path).read()
    assert '@router.delete("/messages/conversations/{phone}"' in src, (
        "Brief 165: DELETE /messages/conversations/{phone} endpoint missing"
    )
    assert "wa_delete_conversation" in src, (
        "Brief 165: wa_delete_conversation call missing from dashboard/api.py"
    )
