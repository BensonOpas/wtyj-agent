"""J3-N2-03: tests for the read-only ICP override debug endpoint.

Covers:
- 404 when NR3_DEBUG_VERIFICATION_ENABLED unset / false / wrong-case
- 200 when flag is 'true' (case-insensitive) + valid auth
- 401 when authed-but-flag-on but no Authorization header
- shape contains AI tone + escalation rules + SoT views
- would_apply flags reflect prompt-builder semantics
- token NEVER appears in response body
- bridge-unavailable response carries available=False + reason
- existing /icp-overrides endpoint still works
"""
import json
import os

import pytest
from fastapi.testclient import TestClient

from dashboard.api import router as dashboard_router
from fastapi import FastAPI
from shared import icp_overrides


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(dashboard_router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def dashboard_token(app):
    """The dashboard API uses a session token initialized at import.
    Reach into the module to fetch it for authed requests."""
    from dashboard import api as api_mod
    return api_mod._SESSION_TOKEN


@pytest.fixture(autouse=True)
def _clear_icp_cache_and_envs(monkeypatch):
    icp_overrides.clear_cache()
    # Each test sets its own env state explicitly
    monkeypatch.delenv("NR3_DEBUG_VERIFICATION_ENABLED", raising=False)
    monkeypatch.delenv("NR3_INTERNAL_OVERRIDES_URL", raising=False)
    monkeypatch.delenv("NR3_INTERNAL_API_TOKEN", raising=False)
    monkeypatch.delenv("TENANT_ID", raising=False)
    yield
    icp_overrides.clear_cache()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# --- gating: flag off -> 404 -----------------------------


def test_debug_endpoint_404_when_flag_unset(client, dashboard_token):
    r = client.get("/dashboard/api/icp-overrides-debug",
                    headers=_auth(dashboard_token))
    assert r.status_code == 404


@pytest.mark.parametrize("flag_value", ["false", "FALSE", "0", "no", "",
                                          "  ", "yes", "1"])
def test_debug_endpoint_404_when_flag_not_true(monkeypatch, client,
                                                  dashboard_token, flag_value):
    monkeypatch.setenv("NR3_DEBUG_VERIFICATION_ENABLED", flag_value)
    r = client.get("/dashboard/api/icp-overrides-debug",
                    headers=_auth(dashboard_token))
    assert r.status_code == 404


@pytest.mark.parametrize("flag_value", ["true", "TRUE", "True", "  true  "])
def test_debug_endpoint_200_when_flag_true(monkeypatch, client,
                                             dashboard_token, flag_value):
    monkeypatch.setenv("NR3_DEBUG_VERIFICATION_ENABLED", flag_value)
    r = client.get("/dashboard/api/icp-overrides-debug",
                    headers=_auth(dashboard_token))
    assert r.status_code == 200


# --- auth still required -----------------------------


def test_debug_endpoint_401_without_auth(monkeypatch, client):
    monkeypatch.setenv("NR3_DEBUG_VERIFICATION_ENABLED", "true")
    r = client.get("/dashboard/api/icp-overrides-debug")
    assert r.status_code == 401


def test_debug_endpoint_401_with_bad_token(monkeypatch, client):
    monkeypatch.setenv("NR3_DEBUG_VERIFICATION_ENABLED", "true")
    r = client.get("/dashboard/api/icp-overrides-debug",
                    headers=_auth("wrong-token"))
    assert r.status_code == 401


# --- response shape -------------------------------


def test_response_carries_expected_top_level_keys(monkeypatch, client,
                                                    dashboard_token):
    monkeypatch.setenv("NR3_DEBUG_VERIFICATION_ENABLED", "true")
    r = client.get("/dashboard/api/icp-overrides-debug",
                    headers=_auth(dashboard_token))
    body = r.json()
    for key in ("tenant_id", "bridge_available", "ai_tone",
                 "ai_escalation_rules", "sot_entries"):
        assert key in body, f"missing top-level key: {key}"


def test_bridge_offline_response_explains_why(monkeypatch, client,
                                                dashboard_token):
    """With no env config the helper returns available=False; the
    debug endpoint must surface that + the reason without raising."""
    monkeypatch.setenv("NR3_DEBUG_VERIFICATION_ENABLED", "true")
    r = client.get("/dashboard/api/icp-overrides-debug",
                    headers=_auth(dashboard_token))
    body = r.json()
    assert body["bridge_available"] is False
    assert body["bridge_reason"]  # non-empty explanation
    # All would_apply flags must be False when bridge is offline
    assert body["ai_tone"]["would_apply"] is False
    assert body["ai_escalation_rules"]["would_apply"] is False
    assert body["sot_entries"]["would_apply"] is False
    assert body["sot_entries"]["count"] == 0


def test_response_with_overrides_reports_would_apply(monkeypatch, client,
                                                      dashboard_token):
    """Stub fetch_overrides with a realistic envelope and verify the
    debug endpoint reports would_apply=True for tone + SoT."""
    monkeypatch.setenv("NR3_DEBUG_VERIFICATION_ENABLED", "true")
    fake = {
        "available": True,
        "tenant_id": "demo",
        "feature_toggles": {},
        "display_metadata": {},
        "sot_entries": [
            {"title": "Holiday hours", "content": "Closed Dec 25",
             "category": "hours", "source": "icp_override",
             "updated_by": "op@x"},
        ],
        "ai_agent_settings": {
            "tone": {"tone": "professional", "notes": "Calm.",
                      "source": "icp_override", "updated_by": "op@x",
                      "updated_at": "2026-05-15T00:00:00"},
            "escalation_rules": None,
        },
    }
    monkeypatch.setattr(icp_overrides, "fetch_overrides",
                         lambda: fake)
    r = client.get("/dashboard/api/icp-overrides-debug",
                    headers=_auth(dashboard_token))
    body = r.json()
    assert body["bridge_available"] is True
    assert body["ai_tone"]["would_apply"] is True
    assert body["ai_tone"]["value"] == "professional"
    assert body["ai_tone"]["source"] == "icp_override"
    assert body["ai_escalation_rules"]["would_apply"] is False
    assert body["sot_entries"]["count"] == 1
    assert body["sot_entries"]["would_apply"] is True
    assert body["sot_entries"]["entries"][0]["title"] == "Holiday hours"
    assert body["sot_entries"]["entries"][0]["category"] == "hours"


def test_response_with_escalation_rules_reports_would_apply(monkeypatch,
                                                              client, dashboard_token):
    monkeypatch.setenv("NR3_DEBUG_VERIFICATION_ENABLED", "true")
    fake = {
        "available": True,
        "tenant_id": "demo",
        "feature_toggles": {},
        "display_metadata": {},
        "sot_entries": [],
        "ai_agent_settings": {
            "tone": None,
            "escalation_rules": {
                "soft_escalation": {"enabled": True,
                                       "when": "Agent uncertain."},
                "hard_escalation": {"enabled": False, "when": ""},
                "source": "icp_override",
            },
        },
    }
    monkeypatch.setattr(icp_overrides, "fetch_overrides",
                         lambda: fake)
    r = client.get("/dashboard/api/icp-overrides-debug",
                    headers=_auth(dashboard_token))
    body = r.json()
    rules = body["ai_escalation_rules"]
    assert rules["would_apply"] is True
    assert rules["soft_escalation"]["enabled"] is True
    assert rules["soft_escalation"]["when"] == "Agent uncertain."
    assert rules["hard_escalation"]["enabled"] is False


# --- malformed envelope tolerance ----------------------


def test_response_tolerates_malformed_envelope(monkeypatch, client,
                                                  dashboard_token):
    """If the bridge response shape is unexpected (older Nr 3, partial
    data), the endpoint must still return 200 with safe defaults."""
    monkeypatch.setenv("NR3_DEBUG_VERIFICATION_ENABLED", "true")
    monkeypatch.setattr(icp_overrides, "fetch_overrides",
                         lambda: {"available": True})  # no other keys
    r = client.get("/dashboard/api/icp-overrides-debug",
                    headers=_auth(dashboard_token))
    assert r.status_code == 200
    body = r.json()
    assert body["bridge_available"] is True
    assert body["sot_entries"]["count"] == 0
    assert body["ai_tone"]["would_apply"] is False


def test_sot_entries_filter_skips_malformed(monkeypatch, client,
                                              dashboard_token):
    """SoT entries with missing title or content are filtered out -
    the count + listing reflects only valid entries the prompt
    builder would consume."""
    monkeypatch.setenv("NR3_DEBUG_VERIFICATION_ENABLED", "true")
    monkeypatch.setattr(icp_overrides, "fetch_overrides", lambda: {
        "available": True, "sot_entries": [
            {"title": "Real", "content": "Body", "category": "faq"},
            {"title": "", "content": "Body only", "category": "x"},
            {"title": "Title only", "content": "", "category": "x"},
            "not a dict",
        ],
        "ai_agent_settings": {"tone": None, "escalation_rules": None},
    })
    r = client.get("/dashboard/api/icp-overrides-debug",
                    headers=_auth(dashboard_token))
    body = r.json()
    assert body["sot_entries"]["count"] == 1
    assert body["sot_entries"]["entries"][0]["title"] == "Real"


# --- token leak guard ------------------------------


def test_token_never_in_debug_response(monkeypatch, client,
                                         dashboard_token):
    """The NR3_INTERNAL_API_TOKEN value must NEVER appear in the
    debug response body even though the helper uses it to call Nr 3."""
    monkeypatch.setenv("NR3_DEBUG_VERIFICATION_ENABLED", "true")
    secret = "supersecret-token-32-bytes-long-xyz"
    monkeypatch.setenv("NR3_INTERNAL_API_TOKEN", secret)
    r = client.get("/dashboard/api/icp-overrides-debug",
                    headers=_auth(dashboard_token))
    assert secret not in r.text


# --- read-only: no method other than GET ----------------


def test_debug_endpoint_post_not_allowed(monkeypatch, client,
                                            dashboard_token):
    monkeypatch.setenv("NR3_DEBUG_VERIFICATION_ENABLED", "true")
    r = client.post("/dashboard/api/icp-overrides-debug",
                     headers=_auth(dashboard_token))
    assert r.status_code == 405  # method not allowed


# --- legacy /icp-overrides endpoint untouched -----------


def test_legacy_icp_overrides_endpoint_still_works(client, dashboard_token):
    """J3-N2-01 endpoint must remain reachable; J3-N2-03 only ADDS
    a second endpoint."""
    r = client.get("/dashboard/api/icp-overrides",
                   headers=_auth(dashboard_token))
    assert r.status_code == 200


def test_onboarding_status_hides_whatsapp_connect_when_connected(monkeypatch, client, dashboard_token):
    from shared import config_loader

    monkeypatch.setattr(
        config_loader,
        "get_raw",
        lambda: {
            "slug": "clinica-roberto",
            "name": "Clínica Roberto",
            "whatsapp_connect_token": "connect-token",
        },
    )
    monkeypatch.setattr(
        config_loader,
        "get_business",
        lambda: {"slug": "clinica-roberto", "name": "Clínica Roberto"},
    )
    monkeypatch.setattr(
        icp_overrides,
        "fetch_overrides",
        lambda: {
            "available": True,
            "tenant_id": "clinica-roberto",
            "channel_connections": {
                "whatsapp": {
                    "status": "connected",
                    "connected": True,
                },
            },
        },
    )

    r = client.get("/dashboard/api/onboarding/status", headers=_auth(dashboard_token))
    assert r.status_code == 200
    body = r.json()
    assert body["whatsappConnected"] is True
    assert body["whatsappConnectionStatus"] == "connected"
    assert body["whatsappConnectUrl"] == ""
