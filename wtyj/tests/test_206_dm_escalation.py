"""Brief 206: dm_agent escalation handler + booking_redirect suppression."""

import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from unittest.mock import MagicMock, patch


# ── Part 1: BOOKING REDIRECT block conditional ─────────────────────────────

@patch("agents.social.dm_agent.config_loader")
def test_booking_redirect_omitted_when_booking_flow_false(mock_config):
    """When tenant has booking_flow:false, the BOOKING REDIRECT block is NOT
    included in the rendered system prompt — non-booking tenants don't need
    a recursive 'message us at wa.me/' redirect."""
    from agents.social.dm_agent import _build_dm_system_prompt

    mock_config.get_business.return_value = {
        "agent_name": "Calvin", "name": "Unboks", "whatsapp": "+59912345",
        "languages": ["English"]
    }
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {
        "terminology": {},
        "agent_persona": {"freeform_notes": "Master prompt for unboks."},
        "features": {"booking_flow": False},
    }

    prompt = _build_dm_system_prompt("whatsapp")

    # Master prompt content present
    assert "Master prompt for unboks." in prompt
    # Booking redirect block ABSENT
    assert "BOOKING REDIRECT" not in prompt
    assert "wa.me/59912345" not in prompt


@patch("agents.social.dm_agent.config_loader")
def test_booking_redirect_present_when_booking_flow_true(mock_config):
    """When tenant has booking_flow:true (BlueMarlin path), the BOOKING
    REDIRECT block IS included — regression for tenants that need it."""
    from agents.social.dm_agent import _build_dm_system_prompt

    mock_config.get_business.return_value = {
        "agent_name": "Marina", "name": "BlueMarlin", "whatsapp": "+59999999",
        "languages": ["English"], "booking_email": "hello@bluemarlin.com",
    }
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {
        "terminology": {"service_label": "trip"},
        "features": {"booking_flow": True},
    }

    prompt = _build_dm_system_prompt("whatsapp")

    # Booking redirect block PRESENT (fallback path with no master prompt)
    assert "BOOKING REDIRECT" in prompt
    assert "wa.me/59999999" in prompt


# ── Part 4: escalation sentinel detection + pending_notification creation ──

@patch("agents.social.dm_agent.state_registry")
@patch("agents.social.dm_agent.config_loader")
@patch("agents.social.dm_agent.anthropic.Anthropic")
def test_escalate_sentinel_creates_pending_notification(
    mock_anthropic, mock_config, mock_state
):
    """When Claude's reply contains [ESCALATE], the sentinel is stripped from
    the visible reply AND a pending_notifications row is created via
    state_registry.create_pending_notification."""
    from agents.social import dm_agent

    mock_config.get_business.return_value = {
        "agent_name": "Calvin", "name": "Unboks", "whatsapp": "",
        "languages": ["English"]
    }
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {
        "terminology": {},
        "agent_persona": {"freeform_notes": "Master prompt"},
        "features": {"booking_flow": False},
    }
    mock_state.dm_get_history.return_value = []

    # Claude responds with an escalation reply
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(
        text="Got it, this needs a person. Email hello@unboks.org.\n[ESCALATE]"
    )]
    mock_msg.usage = None
    mock_anthropic.return_value.messages.create.return_value = mock_msg

    reply = dm_agent.handle_incoming_dm({
        "conversation_id": "test-206-conv-id",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "sender_name": "AngryCustomer",
        "text": "I want a refund right now",
        "account_id": "acct-1",
    })

    # Sentinel stripped from visible reply
    assert "[ESCALATE]" not in reply
    # Visible message preserved
    assert "Email hello@unboks.org" in reply
    # Escalation row created with the right payload
    mock_state.create_pending_notification.assert_called_once()
    call = mock_state.create_pending_notification.call_args
    assert call.kwargs["notification_type"] == "escalation"
    assert call.kwargs["channel"] == "whatsapp"
    assert call.kwargs["customer_id"] == "test-206-conv-id"
    assert call.kwargs["customer_name"] == "AngryCustomer"
    # Body should contain the customer's message + Calvin's reply for operator context
    assert "I want a refund right now" in call.kwargs["body"]


@patch("agents.social.dm_agent.state_registry")
@patch("agents.social.dm_agent.config_loader")
@patch("agents.social.dm_agent.anthropic.Anthropic")
def test_no_sentinel_no_escalation_created(
    mock_anthropic, mock_config, mock_state
):
    """Regression: when Claude's reply does NOT contain [ESCALATE], no
    pending_notifications row is created. False-positive guard."""
    from agents.social import dm_agent

    mock_config.get_business.return_value = {
        "agent_name": "Calvin", "name": "Unboks", "whatsapp": "",
        "languages": ["English"]
    }
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {
        "terminology": {},
        "agent_persona": {"freeform_notes": "Master prompt"},
        "features": {"booking_flow": False},
    }
    mock_state.dm_get_history.return_value = []

    # Normal Q&A reply, no sentinel
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(
        text="Unboks puts all your messages in one inbox."
    )]
    mock_msg.usage = None
    mock_anthropic.return_value.messages.create.return_value = mock_msg

    reply = dm_agent.handle_incoming_dm({
        "conversation_id": "test-206-noesc",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "sender_name": "Prospect",
        "text": "What does Unboks do?",
        "account_id": "acct-1",
    })

    assert "Unboks puts all your messages" in reply
    mock_state.create_pending_notification.assert_not_called()


@patch("agents.social.dm_agent.state_registry")
@patch("agents.social.dm_agent.config_loader")
@patch("agents.social.dm_agent.anthropic.Anthropic")
def test_escalation_db_failure_does_not_break_reply(
    mock_anthropic, mock_config, mock_state
):
    """If create_pending_notification raises (e.g., DB transient), the
    customer-facing reply still ships (with sentinel stripped). Escalation
    failures are logged but never blocking."""
    from agents.social import dm_agent

    mock_config.get_business.return_value = {
        "agent_name": "Calvin", "name": "Unboks", "whatsapp": "",
        "languages": ["English"]
    }
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {
        "terminology": {},
        "agent_persona": {"freeform_notes": "Master prompt"},
        "features": {"booking_flow": False},
    }
    mock_state.dm_get_history.return_value = []
    mock_state.create_pending_notification.side_effect = RuntimeError("db down")

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(
        text="Got it, getting to the team.\n[ESCALATE]"
    )]
    mock_msg.usage = None
    mock_anthropic.return_value.messages.create.return_value = mock_msg

    reply = dm_agent.handle_incoming_dm({
        "conversation_id": "test-206-dbfail",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "sender_name": "Customer",
        "text": "complaint",
        "account_id": "acct-1",
    })

    # Reply still shipped (with sentinel stripped)
    assert "[ESCALATE]" not in reply
    assert "Got it, getting to the team" in reply
    # Escalation attempt was made (even though it failed)
    mock_state.create_pending_notification.assert_called_once()
