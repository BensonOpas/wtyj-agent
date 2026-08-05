"""Regression tests for Consulta Despertares returning prospects."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from agents.social import social_agent


def test_consulta_intake_fields_survive_a_24_hour_inactivity_gap():
    fields = {
        "customer_name": "Leonor Example",
        "first_name": "Leonor",
        "surnames": "Example",
        "phone": "600111222",
        "phone_raw": "600111222",
        "callback_preference": "Por la tarde",
        "appointment_preference": "A partir del 25 de agosto",
        "session_type": "Presencial",
        "visit_reason": "Ansiedad",
    }
    flags = {}
    completed_bookings = []
    last_activity = (
        datetime.now(timezone.utc) - timedelta(hours=25)
    ).isoformat()

    with patch.object(
        social_agent.tenant_hard_rules,
        "is_consulta_despertares",
        return_value=True,
    ):
        reset = social_agent._maybe_reset_stale_conversation(
            last_activity, fields, flags, completed_bookings
        )

    assert reset is True
    assert fields == {
        "customer_name": "Leonor Example",
        "first_name": "Leonor",
        "surnames": "Example",
        "phone": "600111222",
        "phone_raw": "600111222",
        "callback_preference": "Por la tarde",
        "appointment_preference": "A partir del 25 de agosto",
        "session_type": "Presencial",
        "visit_reason": "Ansiedad",
    }


def test_consulta_uses_full_active_history_for_a_returning_prospect():
    expected_history = [
        {"role": "user", "text": "Sufro de ansiedad."},
        {"role": "assistant", "text": "Gracias por compartirlo."},
    ]

    with (
        patch.object(
            social_agent.tenant_hard_rules,
            "is_consulta_despertares",
            return_value=True,
        ),
        patch.object(
            social_agent.state_registry,
            "wa_get_full_history",
            return_value=expected_history,
        ) as get_full_history,
        patch.object(social_agent.state_registry, "wa_get_history") as get_history,
    ):
        history = social_agent._history_for_agent("conversation-1")

    assert history == expected_history
    get_full_history.assert_called_once_with("conversation-1", limit=200)
    get_history.assert_not_called()


def test_other_tenants_keep_the_standard_recent_history_window():
    expected_history = [{"role": "user", "text": "Hello"}]

    with (
        patch.object(
            social_agent.tenant_hard_rules,
            "is_consulta_despertares",
            return_value=False,
        ),
        patch.object(
            social_agent.state_registry,
            "wa_get_history",
            return_value=expected_history,
        ) as get_history,
        patch.object(social_agent.state_registry, "wa_get_full_history") as get_full_history,
    ):
        history = social_agent._history_for_agent("phone-1")

    assert history == expected_history
    get_history.assert_called_once_with("phone-1", limit=10)
    get_full_history.assert_not_called()
