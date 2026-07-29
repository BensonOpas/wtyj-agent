from unittest.mock import patch

from agents.marina import marina_agent
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


def test_other_first_message_preserves_single_language_introduction():
    english_reply = (
        "Hi, I'm Alia, the virtual assistant for Consulta Despertares. "
        "How can I help?"
    )
    enforced = _enforce(
        english_reply,
        "Hi, I would like some information.",
    )

    assert enforced == english_reply
    assert tenant_hard_rules.CONSULTA_DESPERTARES_OTHER_GREETING not in enforced


def test_other_spanish_first_message_is_not_duplicated():
    spanish_reply = (
        "Hola, soy Alia, la asistente virtual de Consulta Despertares. "
        "¿En qué puedo ayudarte?"
    )
    enforced = _enforce(
        spanish_reply,
        "Buenas tardes, quería consultar precios.",
    )

    assert enforced == spanish_reply
    assert enforced.lower().count("hola") == 1


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


def test_callback_question_is_not_combined_with_another_question():
    history = [
        {"role": "user", "text": "Quiero pedir una cita."},
        {"role": "assistant", "text": "¿Cuál es tu nombre completo?"},
    ]
    fields = {
        "first_name": "Ana",
        "surnames": "García López",
        "phone": "612345678",
    }
    model_reply = (
        "Tienes razón, vamos paso a paso.\n\n"
        "¿Prefieres la cita por la mañana o por la tarde?\n\n"
        "¿Cuándo te podemos llamar para confirmar la primera cita?"
    )

    enforced = _enforce(
        model_reply,
        "Quiero la cita por la tarde.",
        history=history,
        fields=fields,
        intents=["booking"],
    )

    assert enforced == (
        "Tienes razón, vamos paso a paso.\n\n"
        "¿Prefieres la cita por la mañana o por la tarde?"
    )
    assert tenant_hard_rules.CONSULTA_DESPERTARES_CALLBACK_CLOSING not in enforced


def test_appointment_time_does_not_count_as_callback_preference():
    history = [
        {"role": "user", "text": "Quiero pedir una cita mañana."},
        {"role": "assistant", "text": "Claro, cuéntame."},
    ]
    fields = {
        "first_name": "Ana",
        "surnames": "García López",
        "phone": "612345678",
        "date": "2026-07-28",
        "slot_time": "18:00",
    }

    enforced = _enforce(
        "Perfecto, pediremos una cita para mañana a las 18:00.",
        "La cita me viene bien mañana a las 18:00.",
        history=history,
        fields=fields,
        intents=["booking"],
    )

    assert enforced.endswith(
        tenant_hard_rules.CONSULTA_DESPERTARES_CALLBACK_CLOSING
    )


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


def test_relationship_first_rule_is_tenant_scoped_and_covers_intake_pacing():
    with patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="consulta-despertares",
    ):
        rule = tenant_hard_rules.consulta_despertares_relationship_rule_block()

    assert "Listen and help first" in rule
    assert "ENTIRE conversation" in rule
    assert "again for information" in rule
    assert "at most ONE question total per reply" in rule
    assert "introduce yourself exactly" in rule
    assert "same language as the customer's most recent message" in rule
    assert "Choosing a physical clinic" in rule
    assert "visit reason is always optional" in rule
    assert "still engaged" in rule
    assert "Do not ask which timezone applies" in rule
    assert "Do not display a checklist" in rule

    with patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="another-tenant",
    ):
        assert tenant_hard_rules.consulta_despertares_relationship_rule_block() == ""


def test_marina_schema_supports_a_complete_non_invasive_prospect_card():
    fields = marina_agent.MARINA_TOOL["input_schema"]["properties"]["fields"]
    properties = fields["properties"]

    assert "session_type" in properties
    assert "full history" in fields["description"]
    assert "Never use the preferred appointment" in (
        properties["callback_preference"]["description"]
    )
    assert "Never use callback availability" in (
        properties["appointment_preference"]["description"]
    )
    assert "Choosing a physical clinic" in properties["session_type"]["description"]
    assert "neutral paraphrase" in properties["visit_reason"]["description"]


def test_despertares_rule_keeps_optional_enrichment_natural():
    with patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="consulta-despertares",
    ):
        rule = tenant_hard_rules.consulta_despertares_relationship_rule_block()

    assert "gently collect missing enrichment" in rule
    assert "fields one at a time" in rule
    assert "Never delay" in rule
    assert "If the customer declines" in rule
    assert "¿Preferirías que la primera sesión fuera presencial u online?" in rule


def test_relationship_first_rule_is_the_final_tenant_prompt_block():
    marker = "CONSULTA RELATIONSHIP FIRST FINAL MARKER"
    with patch(
        "agents.marina.marina_agent.tenant_hard_rules."
        "consulta_despertares_relationship_rule_block",
        return_value=marker,
    ):
        prompt = marina_agent._build_system_prompt({}, channel="whatsapp")

    assert prompt.rstrip().endswith(marker)


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
