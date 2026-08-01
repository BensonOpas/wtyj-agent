from unittest.mock import patch

from agents.marina import marina_agent
from agents.social import social_agent
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

    assert tenant_hard_rules.CONSULTA_DESPERTARES_CALLBACK_CLOSING not in enforced
    assert enforced.endswith(
        tenant_hard_rules.CONSULTA_DESPERTARES_APPOINTMENT_PREFERENCE_QUESTION
    )


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
    assert "NOT a signal to" in rule
    assert "session_type, then appointment_preference" in rule
    assert "normal request to speak with a psychologist" in rule
    assert "location, clinic, callback time" in rule
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
    assert "Never put a location" in properties["visit_reason"]["description"]


def test_despertares_rule_keeps_optional_enrichment_natural():
    with patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="consulta-despertares",
    ):
        rule = tenant_hard_rules.consulta_despertares_relationship_rule_block()

    assert "NOT a signal to" in rule
    assert "continue naturally with exactly one missing" in rule
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

def test_despertares_callback_prompt_does_not_stop_at_minimum_fields():
    config = {
        "workflow": {"type": "callback_follow_up"},
        "features": {"booking_flow": False},
    }
    with (
        patch("agents.marina.marina_agent.config_loader.get_raw", return_value=config),
        patch(
            "agents.marina.marina_agent.tenant_hard_rules."
            "is_consulta_despertares",
            return_value=True,
        ),
    ):
        prompt = marina_agent._build_system_prompt({}, channel="whatsapp")

    assert "NOT permission to stop or hand off immediately" in prompt
    assert "continue with session_type" in prompt
    assert "Do NOT set requires_human for those requests" in prompt
    assert "A location, clinic, callback time" in prompt


def test_callback_visit_reason_never_uses_location_or_generic_notes():
    assert social_agent._callback_visit_reason({
        "special_requests": "Located in north Madrid",
        "comments": "Prefers Alcobendas",
    }) == ""
    assert social_agent._callback_visit_reason({
        "visit_reason": "Would like support with anxiety",
        "special_requests": "Located in north Madrid",
    }) == "Would like support with anxiety"


def test_callback_status_recalculates_stale_needs_answer_to_ready():
    follow_up = {
        "status": "needs_human_answer",
        "first_name": "Calvin",
        "surnames": "Adamus",
        "phone_raw": "537473246",
        "callback_preference": "After 18:00",
    }
    result = {
        "requires_human": False,
        "reply": "The team will call after 18:00.",
    }

    assert social_agent._callback_follow_up_target_status(
        follow_up, result
    ) == "ready_to_call"


def test_callback_status_stays_collecting_while_agent_enriches_card():
    follow_up = {
        "status": "needs_human_answer",
        "first_name": "Calvin",
        "surnames": "Adamus",
        "phone_raw": "537473246",
        "callback_preference": "After 18:00",
    }
    result = {
        "requires_human": False,
        "reply": "Would you prefer your first session in person or online?",
    }

    assert social_agent._callback_follow_up_target_status(
        follow_up, result
    ) == "collecting"


def test_callback_status_preserves_real_pending_human_answer():
    follow_up = {
        "status": "collecting",
        "first_name": "Calvin",
        "surnames": "Adamus",
        "phone_raw": "537473246",
        "callback_preference": "After 18:00",
    }
    result = {
        "requires_human": True,
        "reply": "I need the team to confirm that detail.",
    }

    assert social_agent._callback_follow_up_target_status(
        follow_up, result
    ) == "needs_human_answer"


def test_callback_status_never_overwrites_operator_outcome():
    follow_up = {
        "status": "copied",
        "first_name": "Calvin",
        "surnames": "Adamus",
        "phone_raw": "537473246",
        "callback_preference": "After 18:00",
    }

    assert social_agent._callback_follow_up_target_status(
        follow_up, {"requires_human": True, "reply": "Pending."}
    ) == "copied"


def test_caller_number_question_replaces_hallucinated_spanish_number():
    history = [
        {"role": "user", "text": "Quiero pedir una cita."},
        {"role": "assistant", "text": "Perfecto, el equipo te llamará."},
    ]
    hallucinated = "Te llamaremos desde el 910 123 456."

    enforced = _enforce(
        hallucinated,
        "¿Desde qué número me vais a llamar?",
        history=history,
        fields={
            "first_name": "Ana",
            "surnames": "García",
            "phone": "600111222",
            "callback_preference": "por la tarde",
        },
        intents=["booking"],
    )

    assert enforced == tenant_hard_rules.CONSULTA_DESPERTARES_CALLER_NUMBER_ANSWER
    assert "910 123 456" not in enforced
    assert not any(character.isdigit() for character in enforced)


def test_caller_number_question_uses_controlled_english_answer():
    history = [
        {"role": "user", "text": "I would like an appointment."},
        {"role": "assistant", "text": "The team will call you."},
    ]

    enforced = _enforce(
        "We will call you from +34 910 123 456.",
        "From which number are you going to call me?",
        history=history,
        fields={},
        intents=["booking"],
    )

    assert (
        enforced
        == tenant_hard_rules.CONSULTA_DESPERTARES_ENGLISH_CALLER_NUMBER_ANSWER
    )
    assert not any(character.isdigit() for character in enforced)


def test_caller_number_variants_receive_the_same_safe_answer():
    history = [
        {"role": "user", "text": "Necesito una cita."},
        {"role": "assistant", "text": "De acuerdo."},
    ]
    variants = [
        "¿Cuál será el número desde el que me llamaréis?",
        "¿Me llamaréis desde un número fijo?",
        "¿Qué número me va a contactar?",
    ]

    for inbound in variants:
        enforced = _enforce(
            "El número será 910000000.",
            inbound,
            history=history,
            fields={},
            intents=["booking"],
        )
        assert (
            enforced
            == tenant_hard_rules.CONSULTA_DESPERTARES_CALLER_NUMBER_ANSWER
        )


def test_first_message_caller_number_question_keeps_single_introduction():
    enforced = _enforce(
        "Puedes esperar una llamada desde el 910000000.",
        "¿Desde qué número me llamaréis?",
        history=[],
        fields={},
        intents=["inquiry"],
    )

    assert enforced.startswith(
        tenant_hard_rules.CONSULTA_DESPERTARES_OTHER_GREETING + "."
    )
    assert enforced.endswith(
        tenant_hard_rules.CONSULTA_DESPERTARES_CALLER_NUMBER_ANSWER
    )
    assert enforced.count("Alia") == 1
    assert not any(character.isdigit() for character in enforced)


def test_caller_number_safety_answer_is_not_mixed_with_intake_question():
    history = [
        {"role": "user", "text": "Quiero pedir una cita."},
        {"role": "assistant", "text": "Gracias por tus datos."},
    ]

    enforced = _enforce(
        "Te llamará el equipo desde el 910000000.",
        "¿Desde qué número vais a llamar?",
        history=history,
        fields={
            "first_name": "Ana",
            "surnames": "García",
            "phone": "600111222",
            "callback_preference": "por la tarde",
        },
        intents=["booking"],
    )

    assert enforced == tenant_hard_rules.CONSULTA_DESPERTARES_CALLER_NUMBER_ANSWER
    assert (
        tenant_hard_rules.CONSULTA_DESPERTARES_APPOINTMENT_PREFERENCE_QUESTION
        not in enforced
    )


def test_caller_number_question_remains_unchanged_for_other_tenants():
    reply = "Nuestro número es 910000000."
    with patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="another-tenant",
    ):
        enforced = tenant_hard_rules.enforce_consulta_despertares_boundaries(
            reply,
            "¿Desde qué número vais a llamar?",
            [],
            {},
            ["booking"],
        )

    assert enforced == reply


def test_relationship_rule_forbids_inventing_follow_up_caller_number():
    with patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="consulta-despertares",
    ):
        rule = tenant_hard_rules.consulta_despertares_relationship_rule_block()

    assert "Never invent, infer, or provide a caller telephone number" in rule
    assert "depends on the professional and clinic" in rule
