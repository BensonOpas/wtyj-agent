import json
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from fastapi.testclient import TestClient

from agents.social.webhook_server import app


client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _client_config(tmp_path, monkeypatch, data):
    from shared import config_loader

    path = tmp_path / "client.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(path))
    config_loader._cache = {}
    return path


def test_agent_identity_defaults_to_marina(tmp_path, monkeypatch):
    _client_config(tmp_path, monkeypatch, {"slug": "demo", "business": {"name": "Demo"}})
    token = _login()

    r = client.get("/dashboard/api/settings/agent-identity", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["effectiveName"] == "Marina"
    assert r.json()["source"] == "default"


def test_agent_identity_tenant_can_save_name(tmp_path, monkeypatch):
    path = _client_config(tmp_path, monkeypatch, {"slug": "demo", "business": {"name": "Demo"}})
    token = _login()

    r = client.put(
        "/dashboard/api/settings/agent-identity",
        json={"agentName": "Sofia"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert r.json()["tenantName"] == "Sofia"
    assert r.json()["effectiveName"] == "Sofia"
    assert r.json()["source"] == "tenant"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["business"]["agent_name"] == "Sofia"


def test_agent_identity_admin_override_wins(tmp_path, monkeypatch):
    _client_config(
        tmp_path,
        monkeypatch,
        {"slug": "demo", "business": {"name": "Demo", "agent_name": "Sofia"}},
    )
    from shared import icp_overrides

    monkeypatch.setattr(
        icp_overrides,
        "fetch_overrides",
        lambda: {
            "available": True,
            "tenant_id": "demo",
            "feature_toggles": {},
            "display_metadata": {},
            "sot_entries": [],
            "ai_agent_settings": {
                "tone": None,
                "escalation_rules": None,
                "agent_identity": {"name": "Lucia", "source": "icp_override"},
            },
        },
    )
    token = _login()

    r = client.get("/dashboard/api/settings/agent-identity", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["tenantName"] == "Sofia"
    assert r.json()["adminOverrideName"] == "Lucia"
    assert r.json()["effectiveName"] == "Lucia"
    assert r.json()["source"] == "admin_override"


def test_agent_identity_rejects_unsafe_name(tmp_path, monkeypatch):
    _client_config(tmp_path, monkeypatch, {"slug": "demo", "business": {"name": "Demo"}})
    token = _login()

    r = client.put(
        "/dashboard/api/settings/agent-identity",
        json={"agentName": "Doctor Roberto"},
        headers=_auth(token),
    )
    assert r.status_code == 400
    assert "mislead" in r.json()["detail"]

