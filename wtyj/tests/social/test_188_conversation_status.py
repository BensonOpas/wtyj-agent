# test_188_conversation_status.py — Brief 188: Conversation state machine
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test")

from unittest.mock import patch, MagicMock
from shared import state_registry


def _cleanup(conversation_id):
    """Clean up all test data for a conversation."""
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?",
                 (conversation_id,))
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (conversation_id,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (conversation_id,))
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?",
                 (conversation_id,))
    conn.commit()
    conn.close()


# --- Test 1: set_conversation_status creates and updates correctly ---
def test_set_and_get_conversation_status():
    conv = "conv_188_set_get"
    _cleanup(conv)
    try:
        # First call creates the row
        state_registry.set_conversation_status(conv, "pending", "whatsapp")
        assert state_registry.get_conversation_status(conv) == "pending"

        # Second call updates it (UPSERT)
        state_registry.set_conversation_status(conv, "open", "whatsapp")
        assert state_registry.get_conversation_status(conv) == "open"

        # Third — resolved
        state_registry.set_conversation_status(conv, "resolved", "whatsapp")
        assert state_registry.get_conversation_status(conv) == "resolved"
    finally:
        _cleanup(conv)


# --- Test 2: get_conversation_status returns "pending" for unknown conversations ---
def test_get_status_unknown_returns_pending():
    assert state_registry.get_conversation_status("conv_188_nonexistent_xyz") == "pending"


# --- Test 3: create_pending_notification sets conversation status to "open" ---
def test_create_notification_sets_status_open():
    conv = "conv_188_notif"
    _cleanup(conv)
    try:
        # Status before: no record → "pending"
        assert state_registry.get_conversation_status(conv) == "pending"

        # Create an escalation notification
        state_registry.create_pending_notification(
            'escalation', 'whatsapp', conv, 'Test User',
            '[TEST] Escalation subject', 'Escalation body')

        # Status after: should be "open"
        assert state_registry.get_conversation_status(conv) == "open", \
            f"Expected 'open', got '{state_registry.get_conversation_status(conv)}'"
    finally:
        _cleanup(conv)


# --- Test 4: resolve_conversation_from_escalation sets "resolved" + clears fully_escalated ---
def test_resolve_clears_fully_escalated():
    conv = "conv_188_resolve"
    _cleanup(conv)
    try:
        # Set up: booking state with fully_escalated=True
        state_registry.wa_save_booking_state(
            conv, {"service_key": "test"}, {"fully_escalated": True}, [])

        # Verify fully_escalated is True
        state = state_registry.wa_get_booking_state(conv)
        assert state["flags"].get("fully_escalated") is True

        # Create a notification (which also sets status to "open")
        notif_id = state_registry.create_pending_notification(
            'escalation', 'whatsapp', conv, 'Test User',
            '[TEST] Subject', 'Body')
        assert state_registry.get_conversation_status(conv) == "open"

        # Resolve it
        state_registry.resolve_conversation_from_escalation(notif_id)

        # Status should be "resolved"
        assert state_registry.get_conversation_status(conv) == "resolved", \
            f"Expected 'resolved', got '{state_registry.get_conversation_status(conv)}'"

        # fully_escalated should be cleared (False, not True)
        state = state_registry.wa_get_booking_state(conv)
        assert state["flags"].get("fully_escalated") is False, \
            f"Expected fully_escalated to be False, got: {state['flags']}"
    finally:
        _cleanup(conv)


# --- Test 5: After resolve, new message goes through normal AI path (no re-escalation) ---
@patch("agents.social.social_agent.config_loader")
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.marina_agent")
@patch("agents.social.social_agent.state_registry")
def test_after_resolve_normal_ai_path(mock_sr, mock_marina, mock_sheets, mock_config):
    from agents.social.social_agent import handle_incoming_whatsapp_message

    conv = "conv_188_reopen"

    # Configure config_loader mock
    mock_config.get_raw.return_value = {"features": {"booking_flow": True}}

    # Configure state_registry mock: clean state, no fully_escalated
    mock_sr.wa_get_booking_state.return_value = {
        "fields": {}, "flags": {}, "completed_bookings": []
    }
    mock_sr.wa_get_history.return_value = []
    mock_sr.dm_get_history.return_value = []
    mock_sr.customer_lookup_or_create.return_value = {"id": 1, "display_name": "Test"}
    mock_sr.customer_get_full.return_value = {}

    # Configure marina to return a simple inquiry response (no booking fields)
    mock_marina.process_message.return_value = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": "Hello! How can I help you today?",
        "clarifications_needed": [],
        "requires_human": False,
        "flags": {},
        "internal_note": "",
    }

    result = handle_incoming_whatsapp_message(
        {"from": conv, "text": "Hello again!", "from_name": "Test User"})

    # Normal AI path should have been taken
    mock_marina.process_message.assert_called_once()
    # Verify channel kwarg was passed
    call_kwargs = mock_marina.process_message.call_args
    assert call_kwargs[1].get("channel") == "whatsapp", \
        f"Expected channel='whatsapp' kwarg, got kwargs: {call_kwargs[1]}"

    # No re-escalation created (the key behavioral assertion)
    mock_sr.create_pending_notification.assert_not_called()

    # Status should have been set to "pending"
    mock_sr.set_conversation_status.assert_any_call(conv, "pending", "whatsapp")

    # Function returned the reply
    assert result == "Hello! How can I help you today?"


# ── Brief 254: email-side flag cleanup + delete cleanup ─

def test_resolve_clears_email_fully_escalated_flag(monkeypatch, tmp_path):
    """Brief 254: resolve_conversation_from_escalation now ALSO clears
    email_thread_state.json.flags.fully_escalated for email-channel
    escalations. Pre-Brief-254 this was only cleared for WhatsApp;
    email escalations left orphan flags driving Inbox status='escalated'
    forever (issue #23)."""
    import json
    from shared import state_registry

    customer_email = "brief254_email@example.com"
    thread_key = f"subj:{customer_email}:test subject"
    fake_state = {
        "threads": {
            thread_key: {
                "messages": [{"role": "customer", "ts": "2026-05-11T00:00:00+00:00",
                              "body": "test"}],
                "fields": {"customer_name": "Brief 254 Test"},
                "flags": {"fully_escalated": True, "awaiting_relay": True},
            }
        }
    }
    state_path = tmp_path / "email_thread_state.json"
    state_path.write_text(json.dumps(fake_state))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                         lambda: str(state_path))

    eid = state_registry.create_pending_notification(
        notification_type="escalation", channel="email",
        customer_id=customer_email, customer_name="Brief 254 Test",
        subject="[ESCALATION] test", body="body", mode="hard")
    try:
        with open(state_path) as f:
            pre = json.load(f)
        assert pre["threads"][thread_key]["flags"].get("fully_escalated") is True
        assert pre["threads"][thread_key]["flags"].get("awaiting_relay") is True

        state_registry.resolve_conversation_from_escalation(eid)

        with open(state_path) as f:
            post = json.load(f)
        flags = post["threads"][thread_key]["flags"]
        assert flags.get("fully_escalated") is False, (
            f"flags.fully_escalated must be False after resolve; got {flags}")
        assert "awaiting_relay" not in flags or flags.get("awaiting_relay") is None, (
            f"flags.awaiting_relay must be cleared after resolve; got {flags}")
    finally:
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM pending_notifications WHERE id = ?", (eid,))
        conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?",
                     (customer_email,))
        conn.commit()
        conn.close()


def test_delete_escalation_clears_email_flags_before_deleting(monkeypatch, tmp_path):
    """Brief 254: delete_escalation now calls
    resolve_conversation_from_escalation BEFORE the DELETE, so all
    orphan flags get cleared. Pre-Brief-254 delete only did the
    DELETE — leaving conversation_status.status='open' and
    email_thread_state.flags.fully_escalated=true orphaned (issue #23
    root cause per Sonia's audit at issue #24)."""
    import json
    from shared import state_registry

    customer_email = "brief254_delete_email@example.com"
    thread_key = f"subj:{customer_email}:delete test"
    fake_state = {
        "threads": {
            thread_key: {
                "messages": [{"role": "customer", "ts": "2026-05-11T00:00:00+00:00",
                              "body": "test"}],
                "fields": {"customer_name": "Brief 254 Delete Test"},
                "flags": {"fully_escalated": True},
            }
        }
    }
    state_path = tmp_path / "email_thread_state.json"
    state_path.write_text(json.dumps(fake_state))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                         lambda: str(state_path))

    eid = state_registry.create_pending_notification(
        notification_type="escalation", channel="email",
        customer_id=customer_email, customer_name="Brief 254 Delete Test",
        subject="[ESCALATION] delete test", body="body", mode="hard")

    try:
        result = state_registry.delete_escalation(eid)
        assert result is True

        conn = state_registry._get_conn()
        row = conn.execute(
            "SELECT 1 FROM pending_notifications WHERE id = ?", (eid,)).fetchone()
        conn.close()
        assert row is None, "delete_escalation should have removed the row"

        conn = state_registry._get_conn()
        cs = conn.execute(
            "SELECT status FROM conversation_status WHERE conversation_id = ?",
            (customer_email,)).fetchone()
        conn.close()
        assert cs is not None and cs[0] == "resolved", (
            f"conversation_status.status must be 'resolved' after delete; "
            f"got {cs[0] if cs else None!r}")

        with open(state_path) as f:
            post = json.load(f)
        assert post["threads"][thread_key]["flags"].get("fully_escalated") is False, (
            f"flags.fully_escalated must be False after delete; "
            f"got {post['threads'][thread_key]['flags']}")
    finally:
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM pending_notifications WHERE id = ?", (eid,))
        conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?",
                     (customer_email,))
        conn.commit()
        conn.close()


def test_delete_escalation_clears_whatsapp_flags_before_deleting():
    """Brief 254: delete_escalation also clears WhatsApp
    whatsapp_booking_state.flags_json.fully_escalated via the
    resolve_conversation_from_escalation call. Pre-Brief-254 this was
    not done on the delete path."""
    from shared import state_registry
    phone = "254_delete_wa_phone"

    state_registry.wa_save_booking_state(
        phone, {"service_key": "test"}, {"fully_escalated": True}, [])
    pre_state = state_registry.wa_get_booking_state(phone)
    assert pre_state["flags"].get("fully_escalated") is True

    eid = state_registry.create_pending_notification(
        notification_type="escalation", channel="whatsapp",
        customer_id=phone, customer_name="Brief 254 WA Delete",
        subject="WA test", body="body", mode="hard")
    try:
        ok = state_registry.delete_escalation(eid)
        assert ok is True

        post_state = state_registry.wa_get_booking_state(phone)
        assert post_state["flags"].get("fully_escalated") is False, (
            f"WhatsApp fully_escalated must be False after delete; "
            f"got {post_state['flags']}")

        conn = state_registry._get_conn()
        cs = conn.execute(
            "SELECT status FROM conversation_status WHERE conversation_id = ?",
            (phone,)).fetchone()
        conn.close()
        assert cs is not None and cs[0] == "resolved"
    finally:
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM pending_notifications WHERE id = ?", (eid,))
        conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?",
                     (phone,))
        conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?",
                     (phone,))
        conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
        conn.commit()
        conn.close()


def test_delete_escalation_returns_false_for_missing_row():
    """Brief 254 regression: delete_escalation still returns False when
    no row matches the escalation_id. Pre-Brief-254 behavior preserved —
    only the cleanup-before-delete logic is new."""
    from shared import state_registry
    result = state_registry.delete_escalation(99999999)
    assert result is False, (
        "delete_escalation should return False for non-existent id; "
        "Pre-Brief-254 behavior must be preserved")
