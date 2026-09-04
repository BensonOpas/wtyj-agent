"""Regression coverage for a partial dashboard SOT hiding clinic tariffs."""
import pytest

from agents.marina import marina_agent
from shared import state_registry


@pytest.fixture
def clinic(monkeypatch, tmp_path):
    raw = {
        "slug": "consulta-despertares",
        "business": {"slug": "consulta-despertares", "name": "Consulta Despertares"},
        "features": {"info_updates_in_prompt": True, "booking_flow": False},
        "workflow": {"type": "callback_follow_up"},
    }
    envelope = {
        "available": True,
        "sot_entries": [
            {"title": "Tariffs", "category": "pricing", "content": (
                "Individual therapy: 50€. Couples therapy: 70€. Family therapy: 80€. "
                "First session: free, except online sessions."
            )},
            {"title": "Services", "category": "services", "content": "Individual and online therapy."},
            {"title": "Old bookings", "category": "general", "content": "LEGACY_BOOKING_RULE"},
            {"title": "Old greeting", "category": "other", "content": "LEGACY_GREETING_RULE"},
        ],
        "ai_agent_settings": {},
    }
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "clinic.db"))
    monkeypatch.setattr(marina_agent.config_loader, "get_raw", lambda: raw)
    monkeypatch.setattr(marina_agent.config_loader, "get_business", lambda: raw["business"])
    monkeypatch.setattr(marina_agent.config_loader, "get_common_sense_knowledge", lambda: {})
    monkeypatch.setattr(marina_agent.config_loader, "get_agent_signature", lambda: "Alia")
    monkeypatch.setattr(marina_agent, "_icp_envelope_for_prompt", lambda: envelope)
    monkeypatch.setattr(marina_agent, "_build_live_product_catalog_block", lambda: "")
    state_registry.source_of_truth_set([{
        "id": "personality", "title": "Personality", "content": "Be warm and calm.",
        "items": ["Tariff page reference only; not imported."],
    }])
    return raw, envelope


def _prompt():
    return marina_agent._build_system_prompt({}, channel="whatsapp")


def test_partial_dashboard_restores_pricing_and_services_not_legacy_behaviour(clinic):
    prompt = _prompt()
    assert "Individual therapy: 50€" in prompt
    assert "Couples therapy: 70€" in prompt
    assert "Family therapy: 80€" in prompt
    assert "Individual and online therapy." in prompt
    assert "Be warm and calm." in prompt
    assert "LEGACY_BOOKING_RULE" not in prompt
    assert "LEGACY_GREETING_RULE" not in prompt
    assert "ICP SOURCE OF TRUTH" not in prompt
    assert prompt.count("Individual therapy: 50€") == 1


def test_generic_price_instruction_does_not_hide_amounts(clinic, monkeypatch):
    monkeypatch.setattr(state_registry, "get_active_info_updates", lambda **kw: [{
        "type": "pricing", "text": "Da los precios, no un enlace a la web.",
    }])
    prompt = _prompt()
    assert "Individual therapy: 50€" in prompt
    assert "Da los precios, no un enlace a la web." in prompt
    assert "general instruction hide an existing price list" in prompt


def test_new_prices_and_online_terms_have_final_priority(clinic, monkeypatch):
    monkeypatch.setattr(state_registry, "get_active_info_updates", lambda **kw: [
        {"type": "pricing", "text": "Nueva tarifa individual: 55€. Sustituye la anterior."},
        {"type": "product", "text": "La primera sesión online también es gratuita."},
    ])
    prompt = _prompt()
    assert "Nueva tarifa individual: 55€" in prompt
    assert "La primera sesión online también es gratuita." in prompt
    assert "ACTIVE BUSINESS UPDATES override conflicting amounts, conditions" in prompt
    assert prompt.index("ACTIVE BUSINESS UPDATES (operator-curated") < prompt.index("PRICE GROUNDING")
    assert prompt.index("BASE REFERENCE FACTS") < prompt.index("PRICE GROUNDING")
    assert prompt.index("TENANT SOURCE OF TRUTH") < prompt.index("PRICE GROUNDING")
    assert "[PRIORITY 1: lower number = newer edit] [pricing] Nueva tarifa" in prompt
    assert "cannot overrule a newer price correction" in prompt
    assert prompt.count("Nueva tarifa individual: 55€") == 1


def test_price_contract_requires_service_pair_and_rejects_ai_history(clinic):
    prompt = _prompt()
    assert "exact service AND amount" in prompt
    assert "Earlier AI replies" in prompt
    assert "NOT pricing sources" in prompt
    assert "do NOT set requires_human or" in prompt
    assert "do not guess" in prompt


def test_unavailable_bridge_does_not_invent_reference_prices(clinic, monkeypatch):
    _, envelope = clinic
    envelope.update(available=False, sot_entries=[])
    monkeypatch.setattr(state_registry, "get_active_info_updates", lambda **kw: [])
    prompt = _prompt()
    assert "BASE REFERENCE FACTS" not in prompt
    assert "Individual therapy: 50€" not in prompt
    assert "do not guess" in prompt


def test_current_dashboard_tariffs_work_when_bridge_is_unavailable(clinic, monkeypatch):
    _, envelope = clinic
    envelope.update(available=False, sot_entries=[])
    monkeypatch.setattr(state_registry, "get_active_info_updates", lambda **kw: [
        {"type": "pricing", "text": "Sesión individual: 50 €. Pareja: 70 €. Familiar: 80 €."},
    ])
    assert "Sesión individual: 50 €. Pareja: 70 €. Familiar: 80 €." in _prompt()


@pytest.mark.parametrize("entries", [None, "bad", [None, {}, {"category": "pricing"}]])
def test_malformed_bridge_entries_are_ignored(clinic, entries):
    assert marina_agent._build_consulta_reference_facts({"sot_entries": entries}) == ""


def test_no_duplicate_reference_when_dashboard_sot_empty(clinic):
    state_registry.source_of_truth_set([])
    prompt = _prompt()
    assert "ICP SOURCE OF TRUTH" in prompt
    assert "BASE REFERENCE FACTS" not in prompt


def test_other_tenant_single_source_behaviour_unchanged(clinic):
    raw, _ = clinic
    raw["slug"] = "another-tenant"
    raw["business"]["slug"] = "another-tenant"
    prompt = _prompt()
    assert "Be warm and calm." in prompt
    assert "Individual therapy: 50€" not in prompt
    assert "BASE REFERENCE FACTS" not in prompt
    assert "PRICE GROUNDING" not in prompt


def test_reference_renderer_does_not_mutate_operator_data(clinic):
    import copy
    _, envelope = clinic
    before = copy.deepcopy(envelope)
    marina_agent._build_consulta_reference_facts(envelope)
    assert envelope == before


def test_edit_time_priority_is_opt_in_and_ignores_expired_notes(clinic):
    conn = state_registry._get_conn()
    for text, created, updated, end in [
        ("Individual: 55 €", "2026-01-01", "2026-09-04", None),
        ("Individual: 50 €", "2026-09-01", "2026-09-01", None),
        ("Expired: 1 €", "2026-09-02", "2026-09-05", "2026-01-01"),
    ]:
        conn.execute("INSERT INTO info_updates (type,text,active,created_at,updated_at,end_date) VALUES ('pricing',?,1,?,?,?)", (text, created, updated, end))
    conn.commit()
    conn.close()
    assert [r["text"] for r in state_registry.get_active_info_updates()] == ["Individual: 50 €", "Individual: 55 €"]
    assert [r["text"] for r in state_registry.get_active_info_updates(newest_edit_first=True)] == ["Individual: 55 €", "Individual: 50 €"]
    assert "[PRIORITY 1: lower number = newer edit] [pricing] Individual: 55 €" in _prompt()
