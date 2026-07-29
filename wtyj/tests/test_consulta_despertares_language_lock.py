from unittest.mock import patch

from agents.marina import marina_agent
from shared import tenant_hard_rules


def _as_despertares():
    return patch(
        "shared.tenant_hard_rules.current_tenant_slug",
        return_value="consulta-despertares",
    )


def test_english_typo_heavy_message_is_detected_from_latest_inbound():
    message = (
        "after winning the worldcup winning i feel that i am industructable "
        "and wanna fight a gorrilla .. is sthat healthy"
    )

    assert tenant_hard_rules.detect_english_or_spanish(message) == "English"


def test_latest_english_message_overrides_spanish_assistant_history():
    history = [
        {"role": "user", "text": "hi"},
        {
            "role": "assistant",
            "text": "Hola, soy Alia, la asistente virtual de Consulta Despertares.",
        },
    ]
    inbound = "yes, why do you write in spanish? i write in english"

    with _as_despertares():
        assert (
            tenant_hard_rules.consulta_despertares_reply_language(
                inbound, history
            )
            == "English"
        )
        lock = tenant_hard_rules.consulta_despertares_language_lock(
            inbound, history
        )

    assert "HIGHEST PRIORITY" in lock
    assert "ENTIRE visible reply in English" in lock
    assert "earlier assistant messages" in lock


def test_neutral_hi_is_treated_as_english_not_spanish():
    with _as_despertares():
        language = tenant_hard_rules.consulta_despertares_reply_language(
            "hi", []
        )

    assert language == "English"


def test_first_english_reply_gets_one_english_greeting():
    spanish_draft = (
        "Hola, soy Alia, la asistente virtual de Consulta Despertares. "
        "¿Cómo te puedo ayudar?"
    )

    with _as_despertares():
        reply = tenant_hard_rules.enforce_consulta_despertares_boundaries(
            reply=spanish_draft,
            inbound_text="hi",
            history=[],
            fields={},
            intents=[],
        )

    assert reply.startswith(
        tenant_hard_rules.CONSULTA_DESPERTARES_ENGLISH_GREETING
    )
    assert reply.count(
        tenant_hard_rules.CONSULTA_DESPERTARES_ENGLISH_GREETING
    ) == 1
    assert "Hola, soy Alia" not in reply


def test_english_callback_question_is_not_forced_to_spanish():
    history = [
        {"role": "user", "text": "I would like an appointment."},
        {"role": "assistant", "text": "What is your full name?"},
    ]
    fields = {
        "first_name": "Calvin",
        "surnames": "Adamus",
        "phone": "537473246",
    }

    with _as_despertares():
        reply = tenant_hard_rules.enforce_consulta_despertares_boundaries(
            reply="Thank you, I have your contact details.",
            inbound_text="My phone number is 537473246.",
            history=history,
            fields=fields,
            intents=["booking"],
        )

    assert reply.endswith(
        tenant_hard_rules.CONSULTA_DESPERTARES_ENGLISH_CALLBACK_CLOSING
    )
    assert (
        tenant_hard_rules.CONSULTA_DESPERTARES_CALLBACK_CLOSING
        not in reply
    )


class _ToolUse:
    type = "tool_use"
    input = {
        "reply": (
            "That post-victory high can be a normal emotional response. "
            "Would you like to tell me how long it has lasted?"
        )
    }


class _Response:
    content = [_ToolUse()]


class _Messages:
    def create(self, **kwargs):
        return _Response()


class _Client:
    messages = _Messages()


def test_language_correction_guard_rewrites_mismatched_reply():
    corrected = marina_agent._correct_reply_language(
        client=_Client(),
        reply="Ese subidón de euforia puede ser una respuesta normal.",
        target_language="English",
        channel="whatsapp",
        from_email="test-thread",
    )

    assert tenant_hard_rules.detect_english_or_spanish(corrected) == "English"
    assert "post-victory high" in corrected


def test_first_hi_does_not_duplicate_an_english_model_introduction():
    model_reply = (
        "I'm Alía, the virtual assistant for Consulta Psicológica Despertares. "
        "How can I help you today?"
    )

    with _as_despertares():
        reply = tenant_hard_rules.enforce_consulta_despertares_boundaries(
            reply=model_reply,
            inbound_text="hi",
            history=[],
            fields={},
            intents=[],
        )

    assert reply.startswith(
        tenant_hard_rules.CONSULTA_DESPERTARES_ENGLISH_GREETING
    )
    assert reply.lower().count("virtual assistant") == 1
    assert "How can I help you today?" in reply


def test_later_english_generic_help_closing_becomes_prospect_centered():
    history = [
        {"role": "user", "text": "hi"},
        {"role": "assistant", "text": "How can I help you today?"},
    ]
    draft = (
        "Feeling invincible for a moment after a big win can happen. "
        "If it continues or leads to risky decisions, it may be worth talking "
        "with a professional.\n\n"
        "Is there anything else I can help you with?"
    )

    with _as_despertares():
        reply = tenant_hard_rules.enforce_consulta_despertares_boundaries(
            reply=draft,
            inbound_text=(
                "After winning I feel indestructible and want to fight a "
                "gorilla. Is that healthy?"
            ),
            history=history,
            fields={},
            intents=["inquiry"],
        )

    assert "anything else I can help you with" not in reply
    assert reply.endswith(
        tenant_hard_rules.CONSULTA_DESPERTARES_ENGLISH_PROSPECT_QUESTION
    )


def test_later_spanish_generic_help_closing_becomes_prospect_centered():
    history = [
        {"role": "user", "text": "Hola"},
        {"role": "assistant", "text": "¿Cómo te puedo ayudar?"},
    ]
    draft = (
        "Si esa sensación se prolonga, puede ser útil hablarlo con un "
        "profesional.\n\n"
        "¿Hay algo más en lo que pueda ayudarte?"
    )

    with _as_despertares():
        reply = tenant_hard_rules.enforce_consulta_despertares_boundaries(
            reply=draft,
            inbound_text="Me siento invencible desde hace varios días.",
            history=history,
            fields={},
            intents=["inquiry"],
        )

    assert "Hay algo más" not in reply
    assert reply.endswith(
        tenant_hard_rules.CONSULTA_DESPERTARES_SPANISH_PROSPECT_QUESTION
    )


def test_first_hi_may_still_use_a_simple_opening_question():
    model_reply = (
        "I'm Alía, the virtual assistant for Consulta Psicológica Despertares. "
        "How can I help you today?"
    )

    with _as_despertares():
        reply = tenant_hard_rules.enforce_consulta_despertares_boundaries(
            reply=model_reply,
            inbound_text="hi",
            history=[],
            fields={},
            intents=[],
        )

    assert reply.endswith("How can I help you today?")
    assert (
        tenant_hard_rules.CONSULTA_DESPERTARES_ENGLISH_PROSPECT_QUESTION
        not in reply
    )


def test_relationship_prompt_forbids_generic_service_desk_closings():
    with _as_despertares():
        rule = tenant_hard_rules.consulta_despertares_relationship_rule_block()

    assert "generic service-desk closing" in rule
    assert "guide them toward the right support" in rule
    assert "do not ask for intimate details or diagnose" in rule
