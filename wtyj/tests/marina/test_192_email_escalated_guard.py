# test_192_email_escalated_guard.py — Brief 192: Email poller escalated guard fix
# Tests the notification creation logic directly via state_registry,
# not through main()'s IMAP loop.
from shared import state_registry


def _cleanup(customer_id):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (customer_id,))
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?", (customer_id,))
    conn.commit()
    conn.close()


def test_relay_notification_created_for_email_channel():
    """Verify create_pending_notification with type='relay' and channel='email'
    creates a visible notification — the same call Brief 192 adds to the
    escalated guard. This tests the DB layer, not the IMAP loop."""
    cid = "test192_relay@example.com"
    _cleanup(cid)
    try:
        notif_id = state_registry.create_pending_notification(
            'relay', 'email', cid, 'Test Customer',
            '[RELAY-abc123] NO-REF - Test Customer',
            'Customer: Test Customer <test192_relay@example.com>\n'
            'Their question: wheelchair access\n',
            relay_token='abc123')

        assert notif_id > 0

        # Verify it's retrievable
        all_esc = state_registry.get_all_escalations()
        match = [e for e in all_esc if e["customer_id"] == cid]
        assert len(match) == 1
        assert match[0]["notification_type"] == "relay"
        assert match[0]["channel"] == "email"
        assert match[0]["relay_token"] == "abc123"
        assert "wheelchair" in match[0]["body"]
        # Brief 188: conversation status should be "open"
        assert state_registry.get_conversation_status(cid) == "open"
    finally:
        _cleanup(cid)


def test_escalation_notification_created_for_email_channel():
    """Verify create_pending_notification with type='escalation' and
    channel='email' works — the re-escalation path from Brief 192."""
    cid = "test192_esc@example.com"
    _cleanup(cid)
    try:
        notif_id = state_registry.create_pending_notification(
            'escalation', 'email', cid, 'Escalated Customer',
            '[ESCALATION] REF123 - Escalated Customer (test192_esc@example.com)',
            '=== RE-ESCALATION (fully_escalated email) ===\n'
            'Customer: Escalated Customer\nNew issue: special arrangements\n')

        assert notif_id > 0

        all_esc = state_registry.get_all_escalations()
        match = [e for e in all_esc if e["customer_id"] == cid]
        assert len(match) == 1
        assert match[0]["notification_type"] == "escalation"
        assert match[0]["channel"] == "email"
        assert "RE-ESCALATION" in match[0]["body"]
        assert state_registry.get_conversation_status(cid) == "open"
    finally:
        _cleanup(cid)
