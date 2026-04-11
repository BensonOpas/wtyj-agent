"""Tests for Brief 184 — semi-escalation from fully-escalated conversations."""
import os
from unittest.mock import patch, MagicMock

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

import shared.state_registry as state_registry


def test_semi_escalation_in_fully_escalated_creates_notification():
    """Brief 184: Marina flags relay_question on a fully-escalated conversation → notification created."""
    mock_result = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": "Let me check with the team about wheelchair accessibility.",
        "clarifications_needed": [],
        "requires_human": False,
        "flags": {},
        "internal_note": "",
        "semi_escalation": True,
        "relay_question": "Can the boat and boarding accommodate a wheelchair user?",
    }
    with patch("agents.marina.marina_agent.process_message", return_value=mock_result), \
         patch("shared.state_registry.create_pending_notification") as mock_notif, \
         patch("shared.state_registry.wa_get_booking_state", return_value={
             "fields": {"customer_name": "Calvin", "guests": 8},
             "flags": {"fully_escalated": True, "reply_times": []},
             "completed_bookings": [],
         }), \
         patch("shared.state_registry.wa_get_history", return_value=[]), \
         patch("shared.state_registry.wa_save_booking_state"), \
         patch("shared.state_registry.wa_store_message"), \
         patch("shared.state_registry.customer_lookup_or_create", return_value={"id": 99, "display_name": "Calvin"}), \
         patch("shared.state_registry.customer_get_full", return_value={}), \
         patch("shared.state_registry.customer_record_interaction"), \
         patch("agents.social.whatsapp_client._is_zernio_conversation_id", return_value=True):
        from agents.social.social_agent import handle_incoming_whatsapp_message
        result = handle_incoming_whatsapp_message({
            "text": "We have someone in a wheelchair, is that ok?",
            "from": "test184_conv_001",
            "from_name": "Calvin",
            "message_id": "test184_1",
            "_zernio_conv": "test184_conv_001",
            "_zernio_account_id": "acc_test",
            "_zernio_channel": "whatsapp",
            "_zernio_sender_name": "Calvin",
        })
        # Verify a relay notification was created
        mock_notif.assert_called_once()
        call_args = mock_notif.call_args
        assert call_args[0][0] == "relay"  # notification_type
        assert "wheelchair" in call_args[0][5].lower()  # body contains the question


def test_normal_reply_in_fully_escalated_no_notification():
    """Brief 184: normal reply on fully-escalated → NO new notification."""
    mock_result = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": "The trip is 8 hours long with BBQ lunch included.",
        "clarifications_needed": [],
        "requires_human": False,
        "flags": {},
        "internal_note": "",
    }
    with patch("agents.marina.marina_agent.process_message", return_value=mock_result), \
         patch("shared.state_registry.create_pending_notification") as mock_notif, \
         patch("shared.state_registry.wa_get_booking_state", return_value={
             "fields": {"customer_name": "Calvin"},
             "flags": {"fully_escalated": True, "reply_times": []},
             "completed_bookings": [],
         }), \
         patch("shared.state_registry.wa_get_history", return_value=[]), \
         patch("shared.state_registry.wa_save_booking_state"), \
         patch("shared.state_registry.wa_store_message"), \
         patch("shared.state_registry.customer_lookup_or_create", return_value={"id": 99, "display_name": "Calvin"}), \
         patch("shared.state_registry.customer_get_full", return_value={}), \
         patch("shared.state_registry.customer_record_interaction"), \
         patch("agents.social.whatsapp_client._is_zernio_conversation_id", return_value=True):
        from agents.social.social_agent import handle_incoming_whatsapp_message
        handle_incoming_whatsapp_message({
            "text": "How long is the trip?",
            "from": "test184_conv_002",
            "from_name": "Calvin",
            "message_id": "test184_2",
            "_zernio_conv": "test184_conv_002",
            "_zernio_account_id": "acc_test",
            "_zernio_channel": "whatsapp",
            "_zernio_sender_name": "Calvin",
        })
        mock_notif.assert_not_called()


def test_requires_human_in_fully_escalated_creates_escalation():
    """Brief 184: requires_human=True (top-level) on fully-escalated → full escalation notification."""
    mock_result = {
        "intents": ["complaint"],
        "fields": {},
        "confidence": "high",
        "reply": "I'm sorry to hear that. I'm escalating this to the team.",
        "clarifications_needed": [],
        "requires_human": True,
        "flags": {},
        "internal_note": "Customer threatening lawsuit over wheelchair denial",
    }
    with patch("agents.marina.marina_agent.process_message", return_value=mock_result), \
         patch("shared.state_registry.create_pending_notification") as mock_notif, \
         patch("shared.state_registry.wa_get_booking_state", return_value={
             "fields": {"customer_name": "Calvin"},
             "flags": {"fully_escalated": True, "reply_times": []},
             "completed_bookings": [],
         }), \
         patch("shared.state_registry.wa_get_history", return_value=[]), \
         patch("shared.state_registry.wa_save_booking_state"), \
         patch("shared.state_registry.wa_store_message"), \
         patch("shared.state_registry.customer_lookup_or_create", return_value={"id": 99, "display_name": "Calvin"}), \
         patch("shared.state_registry.customer_get_full", return_value={}), \
         patch("shared.state_registry.customer_record_interaction"), \
         patch("agents.social.whatsapp_client._is_zernio_conversation_id", return_value=True):
        from agents.social.social_agent import handle_incoming_whatsapp_message
        handle_incoming_whatsapp_message({
            "text": "I will sue you if my friend can't board",
            "from": "test184_conv_003",
            "from_name": "Calvin",
            "message_id": "test184_3",
            "_zernio_conv": "test184_conv_003",
            "_zernio_account_id": "acc_test",
            "_zernio_channel": "whatsapp",
            "_zernio_sender_name": "Calvin",
        })
        mock_notif.assert_called_once()
        call_args = mock_notif.call_args
        assert call_args[0][0] == "escalation"  # notification_type (not relay)
