import json
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.api import router as dashboard_router
from shared import config_loader


def _auth():
    from dashboard import api as api_mod
    return {"Authorization": f"Bearer {api_mod._SESSION_TOKEN}"}


def test_runtime_prompt_manifest_indexes_known_prompt_paths(monkeypatch, tmp_path):
    config_path = tmp_path / "client.json"
    config_path.write_text(
        json.dumps({
            "slug": "test",
            "password": "plain-secret-password",
            "access_key": "plain-secret-access-key",
            "business": {
                "name": "Test Co",
                "email": "hello@test.example",
                "agent_name": "Sofia",
                "languages": ["English", "Spanish"],
            },
            "agent_persona": {
                "tone": "Warm and professional",
                "freeform_notes": "Never tell jokes. Always reply in Spanish.",
            },
            "services": {
                "consult": {"display_name": "Consultation", "price_pp": "50"}
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(config_loader, "_cache", {})
    monkeypatch.delenv("NR3_INTERNAL_OVERRIDES_URL", raising=False)
    monkeypatch.delenv("NR3_INTERNAL_API_TOKEN", raising=False)

    app = FastAPI()
    app.include_router(dashboard_router)
    client = TestClient(app)

    response = client.get("/dashboard/api/runtime-prompt-manifest", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["partial"] is False
    source_ids = {source["id"] for source in body["sources"]}
    assert "runtime.marina.whatsapp.system" in source_ids
    assert "runtime.marina.email.system" in source_ids
    assert "runtime.dashboard.suggest_reply.system" in source_ids
    assert "runtime.escalation_summary.system" in source_ids
    assert "runtime.dm_agent.instagram_dm.system" in source_ids
    assert "runtime.dm_agent.facebook_dm.system" in source_ids
    assert "runtime.fallback.whatsapp" in source_ids

    combined = json.dumps(body)
    assert "plain-secret-password" not in combined
    assert "plain-secret-access-key" not in combined
    assert "Sofia" in combined
    assert "Always reply in Spanish" in combined


def test_runtime_prompt_manifest_indexes_clinica_roberto_phone_privacy_rule(monkeypatch, tmp_path):
    config_path = tmp_path / "client.json"
    config_path.write_text(
        json.dumps({
            "slug": "clinica-roberto",
            "business": {
                "slug": "clinica-roberto",
                "name": "Clinica Roberto",
                "agent_name": "Marina",
                "languages": ["Spanish"],
            },
            "agent_persona": {
                "tone": "Profesional y empático",
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(config_loader, "_cache", {})
    monkeypatch.delenv("NR3_INTERNAL_OVERRIDES_URL", raising=False)
    monkeypatch.delenv("NR3_INTERNAL_API_TOKEN", raising=False)

    app = FastAPI()
    app.include_router(dashboard_router)
    client = TestClient(app)

    response = client.get("/dashboard/api/runtime-prompt-manifest", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    source_ids = {source["id"] for source in body["sources"]}
    assert "runtime.tenant_hard_rules.clinica_roberto.phone_privacy" in source_ids
    combined = json.dumps(body, ensure_ascii=False)
    assert "TENANT HARD PRIVACY RULE - CLINICA ROBERTO" in combined
    assert "no puedo tomar ni guardar automáticamente tu número desde WhatsApp" in combined
    assert "Dashboard suggest-reply system prompt" in combined
