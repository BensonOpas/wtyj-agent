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
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

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
        "channel_connections": {
            "whatsapp": {
                "provider": "zernio",
                "status": "connected",
                "connected": True,
                "display_phone_number": "+599 9 694 5527",
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
    assert env["channel_connections"]["whatsapp"]["connected"] is True
    assert env["channel_connections"]["whatsapp"]["status"] == "connected"
    # Outbound URL composed correctly
    assert captured["url"] == f"{URL}/internal/tenants/{TENANT}/overrides"
    assert captured["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert captured["headers"]["X-Tenant-Identity"] == TENANT
    assert captured["timeout"] == 3.0


def test_runtime_channel_controls_require_explicit_available_bridge_values(
    monkeypatch,
):
    monkeypatch.setenv("TENANT_RUNTIME_CONTROLS_REQUIRED", "true")
    assert icp_overrides.auto_reply_enabled({
        "feature_toggles": {"ai_auto_reply": {"value": False}},
    }) is False
    assert icp_overrides.auto_reply_enabled({
        "feature_toggles": {"ai_auto_reply": {"value": True}},
    }) is False
    assert icp_overrides.auto_reply_enabled({
        "available": False,
        "feature_toggles": {},
    }) is False
    assert icp_overrides.auto_reply_enabled({
        "available": True,
        "feature_toggles": {},
    }) is False
    assert icp_overrides.auto_reply_enabled({
        "available": "true",
        "feature_toggles": {"ai_auto_reply": {"value": True}},
    }) is False
    assert icp_overrides.auto_reply_enabled({
        "available": True,
        "feature_toggles": {"ai_auto_reply": {"value": True}},
    }) is True

    assert icp_overrides.whatsapp_inbox_enabled({
        "available": True,
        "feature_toggles": {"whatsapp_inbox": {"value": True}},
    }) is True
    assert icp_overrides.whatsapp_inbox_enabled({
        "available": True,
        "feature_toggles": {"whatsapp_inbox": {"value": False}},
    }) is False
    assert icp_overrides.whatsapp_inbox_enabled({
        "available": False,
        "feature_toggles": {"whatsapp_inbox": {"value": True}},
    }) is False
    assert icp_overrides.whatsapp_inbox_enabled({
        "feature_toggles": {"whatsapp_inbox": {"value": True}},
    }) is False
    assert icp_overrides.whatsapp_inbox_state({
        "available": False,
        "feature_toggles": {"whatsapp_inbox": {"value": False}},
    }) is None
    assert icp_overrides.whatsapp_inbox_state({
        "available": True,
        "feature_toggles": {"whatsapp_inbox": {"value": False}},
    }) is False
    assert icp_overrides.auto_reply_state({
        "available": True,
        "feature_toggles": {},
    }) is None


def test_legacy_runtime_controls_preserve_historical_defaults(monkeypatch):
    monkeypatch.delenv("TENANT_RUNTIME_CONTROLS_REQUIRED", raising=False)
    unavailable = {"available": False, "feature_toggles": {}}
    missing = {"available": True, "feature_toggles": {}}
    explicit_off = {
        "available": True,
        "feature_toggles": {
            "ai_auto_reply": {"value": False},
            "whatsapp_inbox": {"value": False},
        },
    }
    assert icp_overrides.auto_reply_enabled(unavailable) is True
    assert icp_overrides.whatsapp_inbox_enabled(unavailable) is True
    assert icp_overrides.auto_reply_enabled(missing) is True
    assert icp_overrides.whatsapp_inbox_enabled(missing) is True
    assert icp_overrides.auto_reply_enabled(explicit_off) is False
    assert icp_overrides.whatsapp_inbox_enabled(explicit_off) is False


def test_set_auto_reply_writes_current_tenant_and_verifies(monkeypatch, configured):
    captured = {}

    def fake_put(url, headers=None, json=None, timeout=None):
        captured.update(
            url=url,
            headers=headers,
            json=json,
            timeout=timeout,
        )
        return _MockResponse(200, {"ok": True})

    stopped = _bridge_envelope()
    stopped["feature_toggles"]["ai_auto_reply"]["value"] = False
    monkeypatch.setattr(requests, "put", fake_put)
    monkeypatch.setattr(requests, "get", lambda *a, **k: _MockResponse(200, stopped))

    envelope = icp_overrides.set_auto_reply_enabled(False)

    assert envelope["feature_toggles"]["ai_auto_reply"]["value"] is False
    assert captured["url"] == (
        f"{URL}/internal/tenants/{TENANT}/feature-toggles/ai_auto_reply"
    )
    assert captured["headers"]["X-Tenant-Identity"] == TENANT
    assert captured["json"] == {"value": False}
    assert captured["timeout"] == 3.0


def test_token_never_in_returned_envelope(monkeypatch, configured):
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _MockResponse(200, _bridge_envelope()))
    env = icp_overrides.fetch_overrides()
    # Token must NEVER round-trip back to the caller via the envelope
    blob = json.dumps(env)
    assert TOKEN not in blob


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


def test_pause_invalidation_prevents_inflight_true_from_reaching_caller(
    monkeypatch, configured
):
    monkeypatch.setenv("TENANT_RUNTIME_CONTROLS_REQUIRED", "true")
    started = threading.Event()
    release_stale = threading.Event()
    stale_result = {}

    running = _bridge_envelope()
    paused = _bridge_envelope()
    paused["feature_toggles"]["ai_auto_reply"]["value"] = False

    def controlled_get(*_args, **_kwargs):
        if threading.current_thread().name == "stale-nr3-fetch":
            started.set()
            assert release_stale.wait(timeout=5)
            return _MockResponse(200, running)
        return _MockResponse(200, paused)

    monkeypatch.setattr(requests, "get", controlled_get)
    monkeypatch.setattr(requests, "put", lambda *a, **k: _MockResponse(200, {}))

    worker = threading.Thread(
        target=lambda: stale_result.setdefault(
            "envelope", icp_overrides.fetch_overrides()
        ),
        name="stale-nr3-fetch",
    )
    worker.start()
    assert started.wait(timeout=5)

    verified = icp_overrides.set_auto_reply_enabled(False)
    assert icp_overrides.auto_reply_enabled(verified) is False
    release_stale.set()
    worker.join(timeout=5)
    assert not worker.is_alive()

    assert stale_result["envelope"]["available"] is False
    assert icp_overrides.auto_reply_enabled(stale_result["envelope"]) is False
    assert icp_overrides.auto_reply_enabled(icp_overrides.fetch_overrides()) is False


def test_newer_fresh_pause_supersedes_older_inflight_enabled_fetch(
    monkeypatch, configured
):
    monkeypatch.setenv("TENANT_RUNTIME_CONTROLS_REQUIRED", "true")
    older_started = threading.Event()
    release_older = threading.Event()
    older_result = {}

    running = _bridge_envelope()
    paused = _bridge_envelope()
    paused["feature_toggles"]["ai_auto_reply"]["value"] = False

    def controlled_get(*_args, **_kwargs):
        if threading.current_thread().name == "older-enabled-fetch":
            older_started.set()
            assert release_older.wait(timeout=5)
            return _MockResponse(200, running)
        return _MockResponse(200, paused)

    monkeypatch.setattr(requests, "get", controlled_get)
    worker = threading.Thread(
        target=lambda: older_result.setdefault(
            "envelope", icp_overrides.fetch_overrides_fresh()
        ),
        name="older-enabled-fetch",
    )
    worker.start()
    assert older_started.wait(timeout=5)

    newer = icp_overrides.fetch_overrides_fresh()
    assert icp_overrides.auto_reply_state(newer) is False
    release_older.set()
    worker.join(timeout=5)
    assert not worker.is_alive()

    assert older_result["envelope"]["available"] is False
    assert "superseded" in older_result["envelope"]["reason"]
    assert icp_overrides.auto_reply_state(older_result["envelope"]) is None
    assert icp_overrides.auto_reply_state(icp_overrides.fetch_overrides()) is False


@pytest.mark.parametrize("pause_finishes_first", [False, True])
def test_fresh_pause_fences_expired_ordinary_read_in_both_orders(
    monkeypatch, configured, pause_finishes_first,
):
    monkeypatch.setenv("TENANT_RUNTIME_CONTROLS_REQUIRED", "true")
    clock = [100.0]
    monkeypatch.setattr(icp_overrides, "time", SimpleNamespace(time=lambda: clock[0]))
    running = _bridge_envelope()
    paused = _bridge_envelope()
    paused["feature_toggles"]["ai_auto_reply"]["value"] = False
    monkeypatch.setattr(requests, "get", lambda *a, **k: _MockResponse(200, running))
    assert icp_overrides.auto_reply_state(icp_overrides.fetch_overrides()) is True
    clock[0] += icp_overrides.ICP_OVERRIDES_TTL_SECONDS + 1

    older_started = threading.Event()
    pause_started = threading.Event()
    release_older = threading.Event()
    release_pause = threading.Event()
    calls = []

    def controlled_get(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            older_started.set()
            assert release_older.wait(timeout=5)
            return _MockResponse(200, running)
        pause_started.set()
        assert release_pause.wait(timeout=5)
        return _MockResponse(200, paused)

    monkeypatch.setattr(requests, "get", controlled_get)
    with ThreadPoolExecutor(max_workers=2) as pool:
        older = pool.submit(icp_overrides.fetch_overrides)
        newer = None
        try:
            assert older_started.wait(timeout=5)
            newer = pool.submit(icp_overrides.fetch_overrides_fresh)
            # Fresh pause checks must bypass the ordinary-read lock.
            assert pause_started.wait(timeout=5)
            if pause_finishes_first:
                release_pause.set()
                assert icp_overrides.auto_reply_state(newer.result(timeout=5)) is False
            release_older.set()
            superseded = older.result(timeout=5)
            assert superseded["available"] is False
            assert icp_overrides.auto_reply_state(superseded) is None
            if not pause_finishes_first:
                assert not newer.done()
                release_pause.set()
                assert icp_overrides.auto_reply_state(newer.result(timeout=5)) is False
        finally:
            release_older.set()
            release_pause.set()
    assert icp_overrides.auto_reply_state(icp_overrides.fetch_overrides()) is False


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
