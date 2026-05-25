"""J3-N2-01: tests for the Nr 2 -> Nr 3 ICP override bridge client.

Asserts safety properties from the spec:
- successful bridge read returns the envelope
- 401 handled safely (empty envelope, no crash)
- 403 handled safely (empty envelope, no crash)
- 404 / network failure / timeout handled safely
- missing env vars -> empty envelope, NO outbound call attempted
- response is cached within TTL
- tenant_id is resolved locally; caller cannot influence cross-tenant requests
- token is never returned to caller
"""
import json

import pytest
import requests

from shared import icp_overrides


TOKEN = "test-token-32-bytes-long-xyz"
URL = "http://nr3.local:8010"
TENANT = "demo"


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Every test starts with an empty cache and the canonical env vars
    unset (so each test can configure what it needs)."""
    icp_overrides.clear_cache()
    monkeypatch.delenv("NR3_INTERNAL_OVERRIDES_URL", raising=False)
    monkeypatch.delenv("NR3_INTERNAL_API_TOKEN", raising=False)
    monkeypatch.delenv("TENANT_ID", raising=False)
    yield
    icp_overrides.clear_cache()


@pytest.fixture
def configured(monkeypatch):
    """Set up the standard env triplet (URL + token + tenant)."""
    monkeypatch.setenv("NR3_INTERNAL_OVERRIDES_URL", URL)
    monkeypatch.setenv("NR3_INTERNAL_API_TOKEN", TOKEN)
    monkeypatch.setenv("TENANT_ID", TENANT)


def _bridge_envelope(tenant=TENANT):
    """Canonical happy-path response shape from the bridge."""
    return {
        "tenant_id": tenant,
        "feature_toggles": {
            "ai_auto_reply": {
                "value": True, "source": "icp_override",
                "wired": True,
                "updated_at": "2026-05-13T12:00:00.000",
                "updated_by": "op@example.com",
            },
        },
        "display_metadata": {
            "display_name": {
                "value": "Demo Tenant",
                "source": "backend",
                "updated_at": None, "updated_by": None,
            },
        },
    }


# --- env-var gating ---------------------------------------------------


def test_no_env_returns_empty_envelope_no_network(monkeypatch):
    """All three env vars unset -> empty envelope, NO outbound HTTP."""
    called = []
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: called.append(("GET", a, k)) or None)
    env = icp_overrides.fetch_overrides()
    assert env["available"] is False
    assert env["feature_toggles"] == {}
    assert env["display_metadata"] == {}
    assert called == []


def test_missing_url_returns_empty(monkeypatch, configured):
    monkeypatch.delenv("NR3_INTERNAL_OVERRIDES_URL", raising=False)
    called = []
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: called.append(1) or None)
    env = icp_overrides.fetch_overrides()
    assert env["available"] is False
    assert "URL" in env["reason"]
    assert called == []


def test_missing_token_returns_empty(monkeypatch, configured):
    monkeypatch.delenv("NR3_INTERNAL_API_TOKEN", raising=False)
    called = []
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: called.append(1) or None)
    env = icp_overrides.fetch_overrides()
    assert env["available"] is False
    assert "TOKEN" in env["reason"]
    assert called == []


def test_no_tenant_identity_returns_empty(monkeypatch):
    """No TENANT_ID env AND no business.slug -> empty envelope."""
    # Point config_loader at an empty client.json
    import tempfile, json as _json, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp()) / "client.json"
    tmp.write_text(_json.dumps({"business": {}}))
    monkeypatch.setenv("CLIENT_CONFIG_PATH", str(tmp))
    # Force config_loader to re-read
    from shared import config_loader
    config_loader._cache.clear()
    config_loader._CONFIG_PATH = str(tmp)
    monkeypatch.setenv("NR3_INTERNAL_OVERRIDES_URL", URL)
    monkeypatch.setenv("NR3_INTERNAL_API_TOKEN", TOKEN)
    env = icp_overrides.fetch_overrides()
    assert env["available"] is False
    assert "tenant" in env["reason"]


# --- happy path -------------------------------------------------------


def test_successful_200_returns_envelope(monkeypatch, configured):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _MockResponse(200, _bridge_envelope())
    monkeypatch.setattr(requests, "get", fake_get)
    env = icp_overrides.fetch_overrides()
    assert env["available"] is True
    assert env["tenant_id"] == TENANT
    assert env["feature_toggles"]["ai_auto_reply"]["source"] == "icp_override"
    # Outbound URL composed correctly
    assert captured["url"] == f"{URL}/internal/tenants/{TENANT}/overrides"
    assert captured["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert captured["headers"]["X-Tenant-Identity"] == TENANT
    assert captured["timeout"] == 3.0


def test_token_never_in_returned_envelope(monkeypatch, configured):
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _MockResponse(200, _bridge_envelope()))
    env = icp_overrides.fetch_overrides()
    # Token must NEVER round-trip back to the caller via the envelope
    blob = json.dumps(env)
    assert TOKEN not in blob


def test_channel_is_enabled_false_only_when_explicitly_disabled():
    env = {
        "feature_toggles": {
            "whatsapp_inbox": {"value": False},
            "email_inbox": {"value": True},
        }
    }
    assert icp_overrides.channel_is_enabled("whatsapp", env) is False
    assert icp_overrides.channel_is_enabled("email", env) is True
    assert icp_overrides.channel_is_enabled("instagram_dm", env) is True
    assert icp_overrides.channel_is_enabled("unknown", env) is True


def test_channel_is_enabled_fails_open_on_bridge_unavailable():
    env = {"available": False, "feature_toggles": {}}
    assert icp_overrides.channel_is_enabled("whatsapp", env) is True


# --- error handling --------------------------------------------------


@pytest.mark.parametrize("status,expected_reason", [
    (401, "401"),
    (403, "403"),
    (404, "404"),
    (500, "unexpected status 500"),
])
def test_non_200_returns_empty_envelope(monkeypatch, configured,
                                          status, expected_reason):
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _MockResponse(status, {}))
    env = icp_overrides.fetch_overrides()
    assert env["available"] is False
    assert expected_reason in env["reason"]
    assert env["feature_toggles"] == {}


def test_network_timeout_returns_empty(monkeypatch, configured):
    def raise_timeout(*a, **k):
        raise requests.Timeout("simulated timeout")
    monkeypatch.setattr(requests, "get", raise_timeout)
    env = icp_overrides.fetch_overrides()
    assert env["available"] is False
    assert "unreachable" in env["reason"]


def test_connection_error_returns_empty(monkeypatch, configured):
    def raise_conn(*a, **k):
        raise requests.ConnectionError("simulated refused")
    monkeypatch.setattr(requests, "get", raise_conn)
    env = icp_overrides.fetch_overrides()
    assert env["available"] is False


def test_non_json_body_returns_empty(monkeypatch, configured):
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _MockResponse(200, "<html>oops</html>",
                                                        json_raises=True))
    env = icp_overrides.fetch_overrides()
    assert env["available"] is False
    assert "non-json" in env["reason"]


def test_body_not_dict_returns_empty(monkeypatch, configured):
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _MockResponse(200, ["not", "a", "dict"]))
    env = icp_overrides.fetch_overrides()
    assert env["available"] is False


# --- cross-tenant prevention ------------------------------------------


def test_tenant_id_resolved_locally_not_from_argument(monkeypatch, configured):
    """fetch_overrides() takes no arguments - caller cannot pass a
    tenant id. This is the load-bearing cross-tenant prevention."""
    import inspect
    sig = inspect.signature(icp_overrides.fetch_overrides)
    assert len(sig.parameters) == 0, (
        "fetch_overrides() must take no args so callers cannot "
        "request other tenants' overrides")


def test_bridge_tenant_mismatch_treated_as_empty(monkeypatch, configured):
    """If the bridge response carries a DIFFERENT tenant_id than we
    requested (network attack / config bug / bridge misbehavior),
    refuse the data."""
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _MockResponse(
                             200, _bridge_envelope(tenant="other-tenant")))
    env = icp_overrides.fetch_overrides()
    assert env["available"] is False
    assert "tenant_id mismatch" in env["reason"]
    assert env["feature_toggles"] == {}


# --- caching ----------------------------------------------------------


def test_repeated_calls_within_ttl_cached(monkeypatch, configured):
    call_count = {"n": 0}

    def counted_get(*a, **k):
        call_count["n"] += 1
        return _MockResponse(200, _bridge_envelope())
    monkeypatch.setattr(requests, "get", counted_get)
    icp_overrides.fetch_overrides()
    icp_overrides.fetch_overrides()
    icp_overrides.fetch_overrides()
    assert call_count["n"] == 1  # only the first call hit the bridge


def test_failure_cached_too(monkeypatch, configured):
    """Cache failures briefly so a 401 storm doesn't pound the bridge."""
    call_count = {"n": 0}

    def counted_get(*a, **k):
        call_count["n"] += 1
        return _MockResponse(401, {})
    monkeypatch.setattr(requests, "get", counted_get)
    icp_overrides.fetch_overrides()
    icp_overrides.fetch_overrides()
    assert call_count["n"] == 1


def test_clear_cache_forces_refetch(monkeypatch, configured):
    call_count = {"n": 0}

    def counted_get(*a, **k):
        call_count["n"] += 1
        return _MockResponse(200, _bridge_envelope())
    monkeypatch.setattr(requests, "get", counted_get)
    icp_overrides.fetch_overrides()
    icp_overrides.clear_cache()
    icp_overrides.fetch_overrides()
    assert call_count["n"] == 2


# --- url composition -------------------------------------------------


def test_trailing_slash_on_base_url_normalized(monkeypatch, configured):
    monkeypatch.setenv("NR3_INTERNAL_OVERRIDES_URL", URL + "/")
    captured = {}

    def fake_get(url, **k):
        captured["url"] = url
        return _MockResponse(200, _bridge_envelope())
    monkeypatch.setattr(requests, "get", fake_get)
    icp_overrides.fetch_overrides()
    # No double slash
    assert "//internal" not in captured["url"]
    assert captured["url"] == f"{URL}/internal/tenants/{TENANT}/overrides"


# --- mock helper -----------------------------------------------------


class _MockResponse:
    def __init__(self, status_code, body, json_raises=False):
        self.status_code = status_code
        self._body = body
        self._json_raises = json_raises

    def json(self):
        if self._json_raises:
            raise ValueError("simulated non-json")
        return self._body
