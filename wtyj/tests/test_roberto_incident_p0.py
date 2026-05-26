import json

from agents.marina import marina_agent
from agents.social import dm_agent
from shared import tenant_context


def _patch_config(monkeypatch, raw):
    from shared import config_loader
    monkeypatch.setattr(config_loader, "get_raw", lambda: raw)
    monkeypatch.setattr(config_loader, "get_business", lambda: tenant_context.canonical_business(raw))
    monkeypatch.setattr(config_loader, "get_common_sense_knowledge", lambda: {})
    monkeypatch.setattr(config_loader, "get_services", lambda: {})
    monkeypatch.setattr(config_loader, "get_faq", lambda: {})
    monkeypatch.setattr(config_loader, "get_agent_signature", lambda: "Marina")


def test_roberto_fallback_is_spanish_and_clinically_safe(monkeypatch):
    raw = {
        "slug": "clinica-roberto",
        "name": "Clínica Roberto",
        "primary_language": "Spanish",
        "languages": ["Spanish"],
        "clinical_guardrails": ["No diagnosis", "No clinical advice"],
    }
    _patch_config(monkeypatch, raw)
    reply = marina_agent._build_contextual_fallback_reply(
        {},
        "whatsapp",
        "Marina",
        "service",
        "people",
        message_text="Hola, necesito una cita",
    )
    assert "Gracias por escribir" in reply
    assert "clínica" in reply
    assert "emergencias" in reply
    assert "hiccup" not in reply.lower()
    assert "sorry" not in reply.lower()


def test_roberto_clinical_guardrails_enter_live_and_dm_prompts(monkeypatch):
    raw = {
        "business": {
            "slug": "clinica-roberto",
            "name": "Clínica Roberto",
            "agent_name": "Marina",
            "primary_language": "Spanish",
            "languages": ["Spanish"],
        },
        "clinical_guardrails": ["No diagnosis", "No therapy advice"],
    }
    _patch_config(monkeypatch, raw)
    live_prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    dm_prompt = dm_agent._build_dm_system_prompt("instagram_dm")
    assert "No diagnosis" in live_prompt
    assert "No therapy advice" in live_prompt
    assert "Primary language: Spanish" in live_prompt
    assert "No diagnosis" in dm_prompt
    assert "Primary language: Spanish" in dm_prompt


def test_flat_onboarding_config_normalizes_to_business():
    raw = {
        "slug": "clinica-roberto",
        "name": "Clínica Roberto",
        "agent_name": "Marina",
        "agent_tone": "professional and calm",
        "languages": ["Spanish"],
        "primary_language": "Spanish",
        "whatsapp": "+5999000000",
        "website": "https://clinica.example",
        "country": "Curaçao",
        "locale": "es-CW",
        "business_brief": "Dental clinic.",
    }
    business = tenant_context.canonical_business(raw)
    assert business["slug"] == "clinica-roberto"
    assert business["primary_language"] == "Spanish"
    assert business["languages"] == ["Spanish"]
    assert business["agent_name"] == "Marina"
    assert business["agent_tone"] == "professional and calm"
    assert business["notes"] == "Dental clinic."
    assert business["whatsapp"] == "+5999000000"


def test_usage_summary_records_provider_failure(monkeypatch, tmp_path):
    from shared import state_registry
    from shared import llm_telemetry
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state_registry.db"))
    llm_telemetry.log_llm_event(
        provider="anthropic",
        model="claude-sonnet-4-6",
        feature_path="WhatsApp Marina",
        channel="whatsapp",
        started_at=__import__("time").monotonic(),
        success=False,
        error="insufficient credits",
        fallback_used=True,
        tenant_id="clinica-roberto",
    )
    summary = state_registry.api_usage_summary(30)
    assert summary["calls"] == 1
    assert summary["errors"] == 1
    assert summary["fallbacks"] == 1
    assert summary["status"] == "critical"
