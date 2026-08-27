from datetime import date
from unittest.mock import patch

from agents.marina import marina_agent
from agents.social import social_agent
from agents.social.webhook_server import (
    _process_zernio_sent_event,
    _use_whatsapp_orchestrator,
)
from agents.social.zernio_dm_client import parse_zernio_sent_webhook
from dashboard import api as dashboard_api
from shared import state_registry, tenant_hard_rules


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

    expected_question = (
        tenant_hard_rules.CONSULTA_DESPERTARES_AUGUST_APPOINTMENT_PREFERENCE_QUESTION
        if tenant_hard_rules._consulta_august_2026_scheduling_active()
        else tenant_hard_rules.CONSULTA_DESPERTARES_APPOINTMENT_PREFERENCE_QUESTION
    )
    assert tenant_hard_rules.CONSULTA_DESPERTARES_CALLBACK_CLOSING not in enforced
    assert enforced.endswith(expected_question)


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
    assert "session_type; then preferred_clinic only for" in rule
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
    assert "preferred_clinic" in properties
    assert "full history" in fields["description"]
    assert "Never use the preferred appointment" in (
        properties["callback_preference"]["description"]
    )
    assert "Never use callback availability" in (
        properties["appointment_preference"]["description"]
    )
    assert "Choosing a physical clinic" in properties["session_type"]["description"]
    assert "Never infer it from their home area" in (
        properties["preferred_clinic"]["description"]
    )
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
    assert "collect preferred_clinic next" in prompt
    assert "For Online,\nskip preferred_clinic" in prompt
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


def test_august_2026_scheduling_rule_expires_after_closure():
    assert tenant_hard_rules._consulta_august_2026_scheduling_active(
        date(2026, 8, 1)
    )
    assert tenant_hard_rules._consulta_august_2026_scheduling_active(
        date(2026, 8, 23)
    )
    assert not tenant_hard_rules._consulta_august_2026_scheduling_active(
        date(2026, 8, 24)
    )


def test_structured_date_inside_august_closure_is_never_accepted():
    history = [
        {"role": "user", "text": "Quiero pedir una cita."},
        {"role": "assistant", "text": "¿Qué día te vendría bien?"},
    ]

    enforced = _enforce(
        "Perfecto, queda confirmada para el 15 de agosto.",
        "El día 15 me viene bien.",
        history=history,
        fields={"date": "2026-08-15"},
        intents=["booking"],
    )

    assert enforced == tenant_hard_rules.CONSULTA_DESPERTARES_AUGUST_CLOSURE_ANSWER
    assert "confirmada para el 15" not in enforced
    assert "24 de agosto" in enforced


def test_natural_spanish_dates_from_10_through_23_august_are_blocked():
    history = [
        {"role": "user", "text": "Necesito una cita."},
        {"role": "assistant", "text": "¿Qué día te vendría bien?"},
    ]
    for day in (10, 15, 23):
        enforced = _enforce(
            f"Perfecto, la cita será el {day} de agosto.",
            f"Me viene bien el {day} de agosto.",
            history=history,
            fields={},
            intents=["booking"],
        )
        assert (
            enforced
            == tenant_hard_rules.CONSULTA_DESPERTARES_AUGUST_CLOSURE_ANSWER
        )


def test_natural_english_closed_date_uses_english_answer():
    history = [
        {"role": "user", "text": "I need an appointment."},
        {"role": "assistant", "text": "What day would suit you?"},
    ]

    enforced = _enforce(
        "Your appointment is confirmed for August 20.",
        "Can I have an appointment on August 20?",
        history=history,
        fields={},
        intents=["booking"],
    )

    assert (
        enforced
        == tenant_hard_rules.CONSULTA_DESPERTARES_ENGLISH_AUGUST_CLOSURE_ANSWER
    )
    assert "August 24 onward" in enforced
    assert "confirmed for August 20" not in enforced


def test_23_august_is_closed_but_24_august_is_accepted():
    history = [
        {"role": "user", "text": "Quiero pedir una cita."},
        {"role": "assistant", "text": "¿Qué día te vendría bien?"},
    ]

    closed = _enforce(
        "Anotado para el 23 de agosto.",
        "El 23 de agosto.",
        history=history,
        fields={"date": "2026-08-23"},
        intents=["booking"],
    )
    available = _enforce(
        "Anotado como preferencia el 24 de agosto.",
        "El 24 de agosto.",
        history=history,
        fields={
            "date": "2026-08-24",
            "appointment_preference": "24 de agosto",
        },
        intents=["booking"],
    )

    assert closed == tenant_hard_rules.CONSULTA_DESPERTARES_AUGUST_CLOSURE_ANSWER
    assert available == "Anotado como preferencia el 24 de agosto."


def test_explicit_after_23_august_request_remains_valid():
    history = [
        {"role": "user", "text": "Quiero pedir una cita."},
        {"role": "assistant", "text": "¿Qué día te vendría bien?"},
    ]
    draft = "Perfecto, buscaremos una cita para la vuelta de vacaciones."

    enforced = _enforce(
        draft,
        "Me viene bien después del 23 de agosto.",
        history=history,
        fields={
            "date": "2026-08-23",
            "appointment_preference": "después del 23 de agosto",
        },
        intents=["booking"],
    )

    assert enforced == draft


def test_august_2027_date_is_not_affected_by_temporary_2026_rule():
    history = [
        {"role": "user", "text": "Quiero pedir una cita."},
        {"role": "assistant", "text": "¿Qué día te vendría bien?"},
    ]
    draft = "Anotado como preferencia."

    enforced = _enforce(
        draft,
        "Me viene bien el 15 de agosto de 2027.",
        history=history,
        fields={
            "date": "2027-08-15",
            "appointment_preference": "15 de agosto de 2027",
        },
        intents=["booking"],
    )

    assert enforced == draft


def test_active_august_rule_steers_new_preference_to_24_august_onward():
    history = [
        {"role": "user", "text": "Quiero una cita."},
        {"role": "assistant", "text": "Gracias por facilitar tus datos."},
    ]
    fields = {
        "first_name": "Ana",
        "surnames": "García",
        "phone": "600111222",
        "callback_preference": "por la tarde",
    }

    with patch(
        "shared.tenant_hard_rules._consulta_august_2026_scheduling_active",
        return_value=True,
    ):
        enforced = _enforce(
            "Perfecto, trasladaré tus datos al equipo.",
            "Podéis llamarme por la tarde.",
            history=history,
            fields=fields,
            intents=["booking"],
        )

    assert enforced.endswith(
        tenant_hard_rules.CONSULTA_DESPERTARES_AUGUST_APPOINTMENT_PREFERENCE_QUESTION
    )


def test_august_company_rule_is_only_in_prompt_while_active():
    with (
        patch(
            "shared.tenant_hard_rules.current_tenant_slug",
            return_value="consulta-despertares",
        ),
        patch(
            "shared.tenant_hard_rules._consulta_august_2026_scheduling_active",
            return_value=True,
        ),
    ):
        active_rule = (
            tenant_hard_rules.consulta_despertares_relationship_rule_block()
        )

    with (
        patch(
            "shared.tenant_hard_rules.current_tenant_slug",
            return_value="consulta-despertares",
        ),
        patch(
            "shared.tenant_hard_rules._consulta_august_2026_scheduling_active",
            return_value=False,
        ),
    ):
        expired_rule = (
            tenant_hard_rules.consulta_despertares_relationship_rule_block()
        )

    assert "closed from 10 August through 23 August 2026" in active_rule
    assert "from 24 August 2026 onward" in active_rule
    assert "closed from 10 August through 23 August 2026" not in expired_rule


def test_august_closure_override_is_tenant_scoped():
    reply = "La cita queda confirmada para el 15 de agosto."
    with patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="another-tenant",
    ):
        enforced = tenant_hard_rules.enforce_consulta_despertares_boundaries(
            reply,
            "Quiero una cita el 15 de agosto.",
            [],
            {"date": "2026-08-15"},
            ["booking"],
        )

    assert enforced == reply

def test_follow_up_alert_dispatch_is_transition_based(monkeypatch):
    calls = []
    monkeypatch.setattr(
        state_registry,
        "_follow_up_alert_dispatcher",
        lambda follow_up, previous_status=None: calls.append(
            (follow_up["status"], previous_status)
        ),
    )

    state_registry.dispatch_follow_up_alert({"status": "collecting"})
    state_registry.dispatch_follow_up_alert(
        {"status": "collecting"}, previous_status="collecting"
    )
    state_registry.dispatch_follow_up_alert(
        {"status": "ready_to_call"}, previous_status="collecting"
    )
    state_registry.dispatch_follow_up_alert(
        {"status": "closed"}, previous_status="ready_to_call"
    )

    assert calls == [
        ("collecting", None),
        ("ready_to_call", "collecting"),
    ]


def test_despertares_follow_up_alert_is_whatsapp_ready():
    alert = dashboard_api._build_follow_up_alert_body({
        "status": "needs_human_answer",
        "first_name": "Ana",
        "surnames": "García",
        "phone_raw": "600 111 222",
        "callback_preference": "Por la tarde",
        "preferred_clinic": "Leganés",
        "visit_reason": "Ansiedad",
    })

    assert "*Necesita respuesta*" in alert
    assert "Prospecto: Ana García" in alert
    assert "Teléfono: 600 111 222" in alert
    assert "Cuándo llamar: Por la tarde" in alert
    assert "Motivo de consulta: Ansiedad" in alert
    assert "Centro preferido: Leganés" in alert
    assert "responde al prospecto" in alert

def _whatsapp_app_sent_payload(source="whatsappbusinessapp"):
    return {
        "id": "webhook-event-1",
        "event": "message.sent",
        "message": {
            "id": "zernio-message-1",
            "conversationId": "conversation-1",
            "accountId": "account-1",
            "platform": "whatsapp",
            "direction": "outgoing",
            "source": source,
            "text": "Te llamaremos mañana por la tarde.",
            "createdAt": "2026-08-01T15:00:00+00:00",
            "sender": {"name": "Consulta Despertares"},
        },
        "conversation": {
            "id": "conversation-1",
            "platform": "whatsapp",
        },
        "account": {"id": "account-1"},
        "timestamp": "2026-08-01T15:00:01+00:00",
    }


def test_parses_whatsapp_business_app_sent_event():
    parsed = parse_zernio_sent_webhook(_whatsapp_app_sent_payload())

    assert parsed["event"] == "message.sent"
    assert parsed["conversation_id"] == "conversation-1"
    assert parsed["message_id"] == "zernio-message-1"
    assert parsed["account_id"] == "account-1"
    assert parsed["platform"] == "whatsapp"
    assert parsed["direction"] == "outgoing"
    assert parsed["source"] == "whatsappbusinessapp"
    assert parsed["text"] == "Te llamaremos mañana por la tarde."


def test_phone_app_reply_is_stored_as_operator_without_ai_processing():
    with (
        patch("shared.tenant_guard.is_account_allowed", return_value=True),
        patch.object(
            state_registry,
            "wa_store_external_operator_message",
            return_value=True,
        ) as store_message,
        patch.object(state_registry, "wa_set_archived") as unarchive,
    ):
        _process_zernio_sent_event(_whatsapp_app_sent_payload())

    store_message.assert_called_once_with(
        message_id="zernio-message-1",
        conversation_id="conversation-1",
        channel="whatsapp",
        text="Te llamaremos mañana por la tarde.",
        sender_name="Secretaría",
        created_at="2026-08-01T15:00:00+00:00",
    )
    unarchive.assert_called_once_with("conversation-1", False)


def test_cloud_api_sent_echo_is_not_stored_again():
    with patch.object(
        state_registry,
        "wa_store_external_operator_message",
    ) as store_message:
        _process_zernio_sent_event(
            _whatsapp_app_sent_payload(source="cloud_api")
        )

    store_message.assert_not_called()

def test_prospect_support_question_is_never_reinserted_after_it_was_asked():
    previous_question = (
        tenant_hard_rules.CONSULTA_DESPERTARES_SPANISH_PROSPECT_QUESTION
    )
    history = [
        {"role": "assistant", "text": previous_question},
        {"role": "user", "text": "Me cuesta dormir desde hace semanas."},
    ]

    enforced = _enforce(
        "Entiendo que debe ser agotador. ¿Hay algo más en lo que pueda ayudarte?",
        "También tengo mucha ansiedad.",
        history=history,
    )

    assert previous_question not in enforced
    assert "¿Hay algo más en lo que pueda ayudarte?" not in enforced
    assert enforced == "Entiendo que debe ser agotador."


def test_model_cannot_repeat_the_exact_prospect_support_question():
    previous_question = (
        tenant_hard_rules.CONSULTA_DESPERTARES_SPANISH_PROSPECT_QUESTION
    )
    history = [{"role": "assistant", "text": previous_question}]

    enforced = _enforce(
        previous_question,
        "Sigo igual.",
        history=history,
    )

    assert previous_question not in enforced
    assert enforced == (
        tenant_hard_rules.CONSULTA_DESPERTARES_SPANISH_SUPPORT_ACKNOWLEDGEMENT
    )



def test_named_visit_reason_does_not_trigger_the_generic_more_question():
    history = [{"role": "assistant", "text": "Gracias por escribirnos."}]

    enforced = _enforce(
        "Gracias por compartirlo.",
        "Sufro de ansiedad y ya estoy en terapia.",
        history=history,
    )

    assert enforced == "Gracias por compartirlo."
    assert (
        tenant_hard_rules.CONSULTA_DESPERTARES_SPANISH_PROSPECT_QUESTION
        not in enforced
    )


def test_model_generated_generic_question_is_removed_after_named_visit_reason():
    history = [{"role": "assistant", "text": "Gracias por escribirnos."}]
    question = tenant_hard_rules.CONSULTA_DESPERTARES_SPANISH_PROSPECT_QUESTION

    enforced = _enforce(
        f"Gracias por compartirlo. {question}",
        "Sufro de ansiedad.",
        history=history,
    )

    assert enforced == "Gracias por compartirlo."
    assert question not in enforced


def test_callback_question_is_never_repeated_after_a_short_unsaved_answer():
    prior_question = (
        "¿Cuándo os podemos llamar para confirmar la primera cita?"
    )
    history = [
        {"role": "assistant", "text": prior_question},
        {"role": "user", "text": "15:30"},
    ]
    fields = {
        "first_name": "Vanessa",
        "surnames": "Arteaga",
        "phone": "600111222",
    }

    enforced = _enforce(
        "¿Cuándo os podemos llamar para confirmar la primera cita?",
        "15:30",
        history=history,
        fields=fields,
        intents=["booking"],
    )

    assert tenant_hard_rules.CONSULTA_DESPERTARES_CALLBACK_CLOSING not in enforced
    assert "¿Cuándo os podemos llamar para confirmar la primera cita?" not in enforced
    assert enforced == (
        tenant_hard_rules.CONSULTA_DESPERTARES_SPANISH_CALLBACK_ACKNOWLEDGEMENT
    )


def test_short_reply_to_callback_question_is_recovered_for_the_prospect_card():
    history = [
        {
            "role": "assistant",
            "text": "¿Cuándo os podemos llamar para confirmar la primera cita?",
        },
    ]
    with patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="consulta-despertares",
    ):
        recovered = (
            tenant_hard_rules.consulta_despertares_callback_preference_from_reply(
                "15:30", history, {}
            )
        )

    assert recovered == "15:30"


def test_clinica_roberto_locks_a_spanish_prospect_to_spanish():
    with patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="clinica-roberto",
    ):
        target = tenant_hard_rules.consulta_despertares_reply_language(
            "Prefiero comentar mis miedos directamente con la psicóloga."
        )
        lock = tenant_hard_rules.consulta_despertares_language_lock(
            "Prefiero comentar mis miedos directamente con la psicóloga."
        )

    assert target == "Spanish"
    assert "ENTIRE visible reply in Spanish" in lock


def test_mixed_english_opening_is_a_language_violation_for_spanish():
    reply = (
        "That makes complete sense, you can absolutely share the details "
        "with her directly. El equipo se pondrá en contacto contigo."
    )

    assert tenant_hard_rules.reply_violates_tenant_language_lock(
        reply, "Spanish"
    )


def test_english_prospect_is_not_forced_to_spanish():
    with patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="clinica-roberto",
    ):
        target = tenant_hard_rules.consulta_despertares_reply_language(
            "I would like to arrange an appointment."
        )

    assert target == "English"


def test_conversation_inbox_hydrates_zernio_participant_name():
    conversation_id = "a" * 24
    items = [{
        "phone": conversation_id,
        "customer_name": conversation_id,
        "last_message": "Mensaje de Secretaría",
    }]

    with patch.object(
        dashboard_api,
        "resolve_zernio_conversation_contacts",
        return_value={
            conversation_id: {
                "name": "María García",
                "phone": "whatsapp:+34600111222",
            }
        },
    ) as resolve_contacts:
        hydrated = dashboard_api._hydrate_conversation_contact_identities(items)

    resolve_contacts.assert_called_once_with([conversation_id])
    assert hydrated[0]["customer_name"] == "María García"


def test_conversation_inbox_falls_back_to_participant_phone_without_name():
    conversation_id = "b" * 24
    items = [{
        "phone": conversation_id,
        "customer_name": "Unknown contact",
        "last_message": "Mensaje de Secretaría",
    }]

    with patch.object(
        dashboard_api,
        "resolve_zernio_conversation_contacts",
        return_value={
            conversation_id: {
                "name": "",
                "phone": "whatsapp:+34600999888",
            }
        },
    ):
        hydrated = dashboard_api._hydrate_conversation_contact_identities(items)

    assert hydrated[0]["customer_name"] == "+34600999888"


def test_conversation_inbox_preserves_existing_prospect_name():
    conversation_id = "c" * 24
    items = [{
        "phone": conversation_id,
        "customer_name": "Ana López",
        "last_message": "Hola",
    }]

    with patch.object(
        dashboard_api,
        "resolve_zernio_conversation_contacts",
    ) as resolve_contacts:
        hydrated = dashboard_api._hydrate_conversation_contact_identities(items)

    resolve_contacts.assert_called_once_with([])
    assert hydrated[0]["customer_name"] == "Ana López"


def test_presencial_lead_is_asked_once_for_preferred_clinic_before_schedule():
    fields = {
        "first_name": "Gimena",
        "surnames": "Salcedo Marquez",
        "phone": "685427447",
        "callback_preference": "Hoy por la tarde, sobre las 19:30",
        "session_type": "Presencial",
    }

    enforced = _enforce(
        "Perfecto, gracias por indicarlo.",
        "Quiero una cita presencial.",
        history=[{"role": "assistant", "text": "Gracias por escribirnos."}],
        fields=fields,
        intents=["booking"],
    )

    assert tenant_hard_rules.CONSULTA_DESPERTARES_PREFERRED_CLINIC_QUESTION in enforced
    assert (
        tenant_hard_rules.CONSULTA_DESPERTARES_APPOINTMENT_PREFERENCE_QUESTION
        not in enforced
    )


def test_online_lead_skips_preferred_clinic_and_continues_with_schedule():
    fields = {
        "first_name": "Ana",
        "surnames": "García",
        "phone": "600111222",
        "callback_preference": "Por la tarde",
        "session_type": "Online",
    }

    enforced = _enforce(
        "Perfecto, gracias por indicarlo.",
        "Quiero una cita online.",
        history=[{"role": "assistant", "text": "Gracias por escribirnos."}],
        fields=fields,
        intents=["booking"],
    )

    assert tenant_hard_rules.CONSULTA_DESPERTARES_PREFERRED_CLINIC_QUESTION not in enforced
    assert (
        tenant_hard_rules.CONSULTA_DESPERTARES_APPOINTMENT_PREFERENCE_QUESTION
        in enforced
    )


def test_preferred_clinic_question_is_not_repeated_when_already_asked():
    history = [{
        "role": "assistant",
        "text": tenant_hard_rules.CONSULTA_DESPERTARES_PREFERRED_CLINIC_QUESTION,
    }]
    fields = {
        "first_name": "Ana",
        "surnames": "García",
        "phone": "600111222",
        "callback_preference": "Por la tarde",
        "session_type": "Presencial",
    }

    enforced = _enforce(
        "Perfecto, seguimos con tus preferencias.",
        "Todavía no lo sé.",
        history=history,
        fields=fields,
        intents=["booking"],
    )

    assert tenant_hard_rules.CONSULTA_DESPERTARES_PREFERRED_CLINIC_QUESTION not in enforced


def test_known_preferred_clinic_is_never_requested_again():
    fields = {
        "first_name": "Ana",
        "surnames": "García",
        "phone": "600111222",
        "callback_preference": "Por la tarde",
        "session_type": "Presencial",
        "preferred_clinic": "Leganés",
    }

    enforced = _enforce(
        "Perfecto, gracias.",
        "Prefiero el centro de Leganés.",
        fields=fields,
        intents=["booking"],
    )

    assert tenant_hard_rules.CONSULTA_DESPERTARES_PREFERRED_CLINIC_QUESTION not in enforced


def test_explicit_no_clinic_preference_is_recovered_from_short_reply():
    history = [{
        "role": "assistant",
        "text": tenant_hard_rules.CONSULTA_DESPERTARES_PREFERRED_CLINIC_QUESTION,
    }]

    with patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="consulta-despertares",
    ):
        recovered = (
            tenant_hard_rules.consulta_despertares_preferred_clinic_from_reply(
                "Me da igual, cualquier centro.", history, {}
            )
        )

    assert recovered == "Sin preferencia"


def test_no_clinic_preference_continues_to_appointment_schedule():
    history = [{
        "role": "assistant",
        "text": "¿Qué centro preferirías para la sesión?",
    }]
    fields = {
        "first_name": "Ana",
        "surnames": "García",
        "phone": "600111222",
        "callback_preference": "Por la tarde",
        "session_type": "Presencial",
        "preferred_clinic": "Sin preferencia",
    }

    enforced = _enforce(
        "Perfecto, no hay problema.",
        "Me da igual, cualquier centro.",
        history=history,
        fields=fields,
        intents=["booking"],
    )

    assert tenant_hard_rules.CONSULTA_DESPERTARES_PREFERRED_CLINIC_QUESTION not in enforced
    assert (
        tenant_hard_rules.CONSULTA_DESPERTARES_APPOINTMENT_PREFERENCE_QUESTION
        in enforced
    )


JOSE_LUIS_COMMERCIAL_MESSAGE = (
    "Buenos días. Soy José Luis Romero, le escribo en representación de "
    "Asociación INSERTUM especialistas en adicciones en Cádiz. ¿Cuándo le "
    "vendría bien agendar una llamada? Sería para un tema de colaboración "
    "para derivación de posibles pacientes con adicciones, por los cuales "
    "damos una bonificación al derivador."
)


def test_despertares_detects_roberto_commercial_contact_example():
    with patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="consulta-despertares",
    ):
        assert tenant_hard_rules.consulta_despertares_non_patient_service_contact(
            JOSE_LUIS_COMMERCIAL_MESSAGE
        )
        reply = tenant_hard_rules.consulta_despertares_service_contact_reply(
            JOSE_LUIS_COMMERCIAL_MESSAGE
        )

    assert "info@consultadespertares.com" in reply
    assert "?" not in reply
    assert "motivo" not in reply.lower()
    assert "centro" not in reply.lower()


def test_despertares_service_contact_bypasses_model_and_prospect_card():
    saved_state = {}
    with (
        patch(
            "shared.tenant_hard_rules.current_tenant_slug",
            return_value="consulta-despertares",
        ),
        patch.object(state_registry, "match_ignored_contact", return_value=None),
        patch.object(
            social_agent.auto_block,
            "evaluate_inbound",
            return_value={"action": "none"},
        ),
        patch.object(
            state_registry,
            "wa_get_booking_state",
            return_value={
                "fields": {},
                "flags": {},
                "completed_bookings": [],
                "last_activity": None,
            },
        ),
        patch.object(
            state_registry,
            "wa_save_booking_state",
            side_effect=lambda phone, fields, flags, completed: saved_state.update(
                {"phone": phone, "fields": fields, "flags": dict(flags)}
            ),
        ) as save_state,
        patch.object(state_registry, "create_pending_notification") as escalate,
        patch.object(state_registry, "upsert_follow_up_request") as upsert_follow_up,
        patch.object(social_agent.marina_agent, "process_message") as run_model,
    ):
        reply = social_agent.handle_incoming_whatsapp_message({
            "from": "commercial-jose-luis",
            "from_name": "José Luis Romero",
            "text": JOSE_LUIS_COMMERCIAL_MESSAGE,
        })

    assert reply == tenant_hard_rules.CONSULTA_DESPERTARES_SERVICE_CONTACT_REPLY
    assert "info@consultadespertares.com" in reply
    assert "?" not in reply
    assert saved_state["flags"]["consulta_non_patient_service_contact"] is True
    save_state.assert_called_once()
    run_model.assert_not_called()
    upsert_follow_up.assert_not_called()
    escalate.assert_not_called()


def test_despertares_persistent_service_contact_escalates_without_intake():
    with (
        patch(
            "shared.tenant_hard_rules.current_tenant_slug",
            return_value="consulta-despertares",
        ),
        patch.object(state_registry, "match_ignored_contact", return_value=None),
        patch.object(
            social_agent.auto_block,
            "evaluate_inbound",
            return_value={"action": "none"},
        ),
        patch.object(
            state_registry,
            "wa_get_booking_state",
            return_value={
                "fields": {},
                "flags": {"consulta_non_patient_service_contact": True},
                "completed_bookings": [],
                "last_activity": None,
            },
        ),
        patch.object(state_registry, "wa_save_booking_state") as save_state,
        patch.object(state_registry, "wa_store_message") as store_system,
        patch.object(
            state_registry,
            "create_pending_notification",
            return_value=501,
        ) as escalate,
        patch.object(state_registry, "upsert_follow_up_request") as upsert_follow_up,
        patch.object(social_agent.marina_agent, "process_message") as run_model,
    ):
        reply = social_agent.handle_incoming_whatsapp_message({
            "from": "commercial-jose-luis",
            "from_name": "José Luis Romero",
            "text": "Prefiero que alguien del equipo me responda por aquí.",
        })

    assert reply == (
        tenant_hard_rules.CONSULTA_DESPERTARES_SERVICE_CONTACT_ESCALATED_REPLY
    )
    assert "?" not in reply
    escalate.assert_called_once()
    store_system.assert_called_once()
    save_state.assert_called_once()
    run_model.assert_not_called()
    upsert_follow_up.assert_not_called()


def test_despertares_service_route_allows_explicit_patient_reentry():
    with patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="consulta-despertares",
    ):
        assert not tenant_hard_rules.consulta_despertares_non_patient_service_contact(
            "Ahora quiero pedir una cita para mí porque sufro ansiedad.",
            already_routed=True,
        )


def test_service_contact_guard_is_tenant_scoped():
    with patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="another-tenant",
    ):
        assert not tenant_hard_rules.consulta_despertares_non_patient_service_contact(
            JOSE_LUIS_COMMERCIAL_MESSAGE
        )
