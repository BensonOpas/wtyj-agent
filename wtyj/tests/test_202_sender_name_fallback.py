"""Brief 202: sender_name fallback for dm_agent-path conversation list."""

import os

# Match established test pattern; module-level setdefault before any imports.
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")


def test_dm_only_conversation_uses_sender_name_for_customer_name():
    """When booking_state has no customer_name (dm_agent path / booking_flow:false),
    wa_list_conversations falls back to the most recent user-role sender_name."""
    from shared import state_registry

    # Use a unique phone so other tests don't pollute
    phone = "test-202-dm-only-conv-" + os.urandom(4).hex()

    # Simulate dm_agent inbound: store messages with sender_name, but never
    # touch whatsapp_booking_state.
    state_registry.dm_store_message(phone, "whatsapp", "user", "Hi there",
                                     sender_name="Calvin Adamus")
    state_registry.dm_store_message(phone, "whatsapp", "assistant", "Hi! How can I help?",
                                     sender_name="")

    # Verify booking_state is genuinely empty for this phone
    import sqlite3
    conn = sqlite3.connect(state_registry.DB_PATH)
    booking_row = conn.execute(
        "SELECT * FROM whatsapp_booking_state WHERE phone = ?", (phone,)
    ).fetchone()
    conn.close()
    assert booking_row is None, "Test setup precondition: booking_state must be empty"

    # Call the function under test
    conversations = state_registry.wa_list_conversations()
    matching = [c for c in conversations if c["phone"] == phone]
    assert len(matching) == 1, f"Expected one conversation for phone {phone}"
    assert matching[0]["customer_name"] == "Calvin Adamus", \
        f"Expected sender_name fallback, got {matching[0]['customer_name']!r}"


def test_marina_path_with_booking_state_still_uses_booking_state_name():
    """When booking_state DOES have customer_name (Marina's path / booking_flow:true),
    it takes priority over any sender_name in whatsapp_threads. Regression guard."""
    from shared import state_registry

    phone = "test-202-marina-path-" + os.urandom(4).hex()

    # Simulate Marina's path: store messages AND populate booking_state with
    # an explicitly-extracted customer name.
    state_registry.dm_store_message(phone, "whatsapp", "user", "Hi, I want to book",
                                     sender_name="WhatsApp Display Name")
    state_registry.wa_save_booking_state(phone, {"customer_name": "Marina Extracted Name"}, {})

    conversations = state_registry.wa_list_conversations()
    matching = [c for c in conversations if c["phone"] == phone]
    assert len(matching) == 1, f"Expected one conversation for phone {phone}"
    # Marina's extracted name wins over the WhatsApp display name
    assert matching[0]["customer_name"] == "Marina Extracted Name", \
        f"Expected booking_state.customer_name priority, got {matching[0]['customer_name']!r}"
