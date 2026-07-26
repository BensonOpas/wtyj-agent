from unittest.mock import patch

from agents.social.webhook_server import _use_whatsapp_orchestrator
from shared import tenant_hard_rules


def _enforce(reply, inbound, history=None, fields=None, intents=None):
    with patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="consulta-despertares",
    ):
        return tenant_hard_rules.enforce_consulta_despertares_boundaries(
            reply=reply,
            inbound_text=inbound,
            history=history or [],
            fields=fields or {},
            intents=intents or [],
        )


def test_website_lead_always_starts_with_exact_mandatory_greeting():
    reply = (
        "¡Hola! Claro, con gusto te ayudo.\n\n"
        "¿Cuándo te podemos llamar para confirmar la primera cita?"
    )
    inbound = (
        "Hola *Consulta Psicológica Despertares*. "
        "Necesito más información sobre Consulta Psicológica Despertares "
        "https://www.consultadespertares.es/"
    )

    enforced = _enforce(reply, inbound)

    assert enforced.startswith(
        tenant_hard_rules.CONSULTA_DESPERTARES_WEBSITE_GREETING
    )
    assert enforced.count(
        tenant_hard_rules.CONSULTA_DESPERTARES_WEBSITE_GREETING
    ) == 1
    assert tenant_hard_rules.CONSULTA_DESPERTARES_CALLBACK_CLOSING not in enforced


def test_other_first_message_uses_exact_alia_greeting():
    enforced = _enforce(
        "Hola, ¿en qué puedo ayudarte?",
        "Buenas tardes, quería consultar precios.",
    )

    assert enforced.startswith(
        tenant_hard_rules.CONSULTA_DESPERTARES_OTHER_GREETING
    )


def test_later_booking_reply_ends_with_exact_callback_question():
    history = [
        {"role": "user", "text": "Quiero pedir una cita."},
        {"role": "assistant", "text": "¿Cuál es tu nombre completo?"},
        {"role": "user", "text": "Me llamo Ana García López."},
    ]
    fields = {
        "first_name": "Ana",
        "surnames": "García López",
        "phone": "612 345 678",
    }

    enforced = _enforce(
        "Gracias, Ana. Ya tengo tus datos.",
        "Mi teléfono es 612 345 678.",
        history=history,
        fields=fields,
        intents=["booking"],
    )

    assert enforced.endswith(
        tenant_hard_rules.CONSULTA_DESPERTARES_CALLBACK_CLOSING
    )
    assert enforced.count(
        tenant_hard_rules.CONSULTA_DESPERTARES_CALLBACK_CLOSING
    ) == 1


def test_callback_question_is_not_used_when_time_was_already_provided():
    history = [
        {"role": "user", "text": "Quiero pedir una cita."},
        {"role": "assistant", "text": "¿Cuál es tu nombre completo?"},
    ]
    fields = {
        "first_name": "Ana",
        "surnames": "García López",
        "phone": "612345678",
        "callback_preference": "El miércoles a las 18:00",
    }
    model_reply = (
        "Perfecto, anotamos el miércoles a las 18:00.\n\n"
        "¿Cuándo te podemos llamar para confirmar la primera cita?"
    )

    enforced = _enforce(
        model_reply,
        "Podéis llamarme el miércoles a las 18:00.",
        history=history,
        fields=fields,
        intents=["booking"],
    )

    assert enforced == "Perfecto, anotamos el miércoles a las 18:00."


def test_other_tenants_are_unchanged():
    reply = "¡Hola! Claro, te ayudo."
    with patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="another-tenant",
    ):
        enforced = tenant_hard_rules.enforce_consulta_despertares_boundaries(
            reply, "Hola", [], {}, []
        )
    assert enforced == reply


def test_callback_workflow_uses_structured_whatsapp_agent_when_booking_is_off():
    config = {
        "features": {"booking_flow": False},
        "workflow": {"type": "callback_follow_up"},
    }
    with patch("agents.social.webhook_server.config_loader.get_raw", return_value=config):
        assert _use_whatsapp_orchestrator("whatsapp") is True
        assert _use_whatsapp_orchestrator("instagram_dm") is False


def test_plain_qa_tenant_still_uses_dm_agent_when_booking_is_off():
    config = {
        "features": {"booking_flow": False},
        "workflow": {"type": "qa"},
    }
    with patch("agents.social.webhook_server.config_loader.get_raw", return_value=config):
        assert _use_whatsapp_orchestrator("whatsapp") is False
