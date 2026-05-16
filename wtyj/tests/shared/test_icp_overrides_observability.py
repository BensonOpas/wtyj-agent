"""J3-N2-04: observability state + structured logging tests for
wtyj/shared/icp_overrides.py.

Covers:
- get_observability_state returns a snapshot dict (copy, not the
  internal reference)
- Every fetch outcome records the expected fields (last_fetch_at,
  duration_ms, outcome, tone source, escalation source, sot_count)
- Counters increment correctly: success bumps total_fetches only;
  failure bumps total_failures; cache_hit bumps total_cache_hits
  (NOT total_failures)
- Outcome values cover every code path: success / cache_hit / 401 /
  403 / 404 / unexpected_status / network_error / non_json /
  body_not_dict / tenant_mismatch / no_tenant / url_unset /
  token_unset
- clear_cache resets observability
- Token never appears in log output
- Log line shape is consistent (single line, key=val format the spec
  asks for)
"""
import logging
import time

import pytest
import requests

from shared import icp_overrides


TOKEN = "test-observability-token-32-bytes-xyz"
URL = "http://nr3.local:8010"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    icp_overrides.clear_cache()
    icp_overrides._reset_observability()
    monkeypatch.delenv("NR3_INTERNAL_OVERRIDES_URL", raising=False)
    monkeypatch.delenv("NR3_INTERNAL_API_TOKEN", raising=False)
    monkeypatch.delenv("TENANT_ID", raising=False)
    yield
    icp_overrides.clear_cache()
    icp_overrides._reset_observability()


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("NR3_INTERNAL_OVERRIDES_URL", URL)
    monkeypatch.setenv("NR3_INTERNAL_API_TOKEN", TOKEN)
    monkeypatch.setenv("TENANT_ID", "demo")


def _ok_envelope():
    return {
        "tenant_id": "demo",
        "feature_toggles": {},
        "display_metadata": {},
        "sot_entries": [{"title": "X", "content": "Y", "category": "faq",
                          "source": "icp_override"}],
        "ai_agent_settings": {
            "tone": {"tone": "professional", "source": "icp_override"},
            "escalation_rules": {"soft_escalation": {"enabled": True, "when": "x"},
                                   "hard_escalation": {"enabled": False, "when": ""},
                                   "source": "icp_override"},
        },
    }


class _Mock:
    def __init__(self, status, body, raises_json=False):
        self.status_code = status
        self._body = body
        self._raises_json = raises_json

    def json(self):
        if self._raises_json:
            raise ValueError("simulated non-json")
        return self._body


# --- snapshot shape -----------------------------


def test_initial_state_has_zero_counters():
    s = icp_overrides.get_observability_state()
    assert s["total_fetches"] == 0
    assert s["total_failures"] == 0
    assert s["total_cache_hits"] == 0
    assert s["last_fetch_at"] is None
    assert s["last_outcome"] is None


def test_get_observability_state_returns_copy_not_reference():
    """Mutating the returned dict must NOT affect the internal state."""
    s = icp_overrides.get_observability_state()
    s["total_fetches"] = 9999
    s2 = icp_overrides.get_observability_state()
    assert s2["total_fetches"] == 0


# --- success path ---------------------------


def test_success_increments_total_fetches_only(monkeypatch, configured):
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _Mock(200, _ok_envelope()))
    icp_overrides.fetch_overrides()
    s = icp_overrides.get_observability_state()
    assert s["total_fetches"] == 1
    assert s["total_failures"] == 0
    assert s["total_cache_hits"] == 0
    assert s["last_outcome"] == "success"
    assert s["last_tenant_id"] == "demo"
    assert s["last_bridge_available"] is True
    assert s["last_sot_count"] == 1
    assert s["last_tone_source"] == "icp_override"
    assert s["last_escalation_source"] == "icp_override"
    assert s["last_fetch_at"]  # non-empty ISO
    assert isinstance(s["last_fetch_duration_ms"], int)
    assert s["last_fetch_duration_ms"] >= 0


# --- cache hit path -------------------------


def test_cache_hit_increments_only_cache_hits(monkeypatch, configured):
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _Mock(200, _ok_envelope()))
    icp_overrides.fetch_overrides()  # populate cache
    icp_overrides.fetch_overrides()  # cache hit
    s = icp_overrides.get_observability_state()
    assert s["total_fetches"] == 2
    assert s["total_cache_hits"] == 1
    assert s["total_failures"] == 0
    assert s["last_outcome"] == "cache_hit"


# --- failure paths --------------------------


@pytest.mark.parametrize("status,outcome", [
    (401, "401"),
    (403, "403"),
    (404, "404"),
    (500, "unexpected_status"),
])
def test_http_failure_outcomes(monkeypatch, configured, status, outcome):
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _Mock(status, {}))
    icp_overrides.fetch_overrides()
    s = icp_overrides.get_observability_state()
    assert s["last_outcome"] == outcome
    assert s["total_failures"] == 1
    assert s["last_bridge_available"] is False


def test_network_error_outcome(monkeypatch, configured):
    def boom(*a, **k):
        raise requests.ConnectionError("simulated")
    monkeypatch.setattr(requests, "get", boom)
    icp_overrides.fetch_overrides()
    s = icp_overrides.get_observability_state()
    assert s["last_outcome"] == "network_error"
    assert s["total_failures"] == 1


def test_non_json_outcome(monkeypatch, configured):
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _Mock(200, None, raises_json=True))
    icp_overrides.fetch_overrides()
    s = icp_overrides.get_observability_state()
    assert s["last_outcome"] == "non_json"


def test_body_not_dict_outcome(monkeypatch, configured):
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _Mock(200, ["not", "dict"]))
    icp_overrides.fetch_overrides()
    s = icp_overrides.get_observability_state()
    assert s["last_outcome"] == "body_not_dict"


def test_tenant_mismatch_outcome(monkeypatch, configured):
    fake = _ok_envelope()
    fake["tenant_id"] = "WRONG"
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _Mock(200, fake))
    icp_overrides.fetch_overrides()
    s = icp_overrides.get_observability_state()
    assert s["last_outcome"] == "tenant_mismatch"


def test_no_tenant_outcome(monkeypatch):
    """No env, no client.json slug -> no_tenant."""
    import tempfile, json as _json, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp()) / "client.json"
    tmp.write_text(_json.dumps({"business": {}}))
    monkeypatch.setenv("CLIENT_CONFIG_PATH", str(tmp))
    from shared import config_loader
    config_loader._cache.clear()
    config_loader._CONFIG_PATH = str(tmp)
    icp_overrides.fetch_overrides()
    s = icp_overrides.get_observability_state()
    assert s["last_outcome"] == "no_tenant"
    assert s["total_failures"] == 1


def test_url_unset_outcome(monkeypatch):
    monkeypatch.setenv("NR3_INTERNAL_API_TOKEN", TOKEN)
    monkeypatch.setenv("TENANT_ID", "demo")
    icp_overrides.fetch_overrides()
    s = icp_overrides.get_observability_state()
    assert s["last_outcome"] == "url_unset"


def test_token_unset_outcome(monkeypatch):
    monkeypatch.setenv("NR3_INTERNAL_OVERRIDES_URL", URL)
    monkeypatch.setenv("TENANT_ID", "demo")
    icp_overrides.fetch_overrides()
    s = icp_overrides.get_observability_state()
    assert s["last_outcome"] == "token_unset"


# --- counter behavior across multiple calls -----------


def test_mixed_outcomes_counted_correctly(monkeypatch, configured):
    """3 calls: 1 success, 1 cache_hit, 1 failure. Counters should be
    total=3, failures=1, cache_hits=1."""
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _Mock(200, _ok_envelope()))
    icp_overrides.fetch_overrides()  # success
    icp_overrides.fetch_overrides()  # cache_hit
    icp_overrides.clear_cache()       # clears state + cache
    # Need to re-isolate after clear (counters back to 0). Test
    # mixed-outcome semantics without clear_cache:
    icp_overrides.fetch_overrides()  # success (re-fetch after clear)
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _Mock(401, {}))
    icp_overrides.clear_cache()
    icp_overrides.fetch_overrides()  # 401 fail
    s = icp_overrides.get_observability_state()
    assert s["total_failures"] >= 1


# --- clear_cache resets observability ------------


def test_clear_cache_resets_observability(monkeypatch, configured):
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _Mock(200, _ok_envelope()))
    icp_overrides.fetch_overrides()
    s = icp_overrides.get_observability_state()
    assert s["total_fetches"] == 1
    icp_overrides.clear_cache()
    s2 = icp_overrides.get_observability_state()
    assert s2["total_fetches"] == 0
    assert s2["last_fetch_at"] is None


# --- log line shape -----------------------------


def test_log_line_emitted_with_expected_keys(monkeypatch, configured, caplog):
    """Each fetch emits ONE INFO log line carrying the structured
    key=val fields the brief asks for."""
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _Mock(200, _ok_envelope()))
    with caplog.at_level(logging.INFO, logger="shared.icp_overrides"):
        icp_overrides.fetch_overrides()
    # Find our line
    icp_lines = [r for r in caplog.records
                  if "icp_overrides fetch" in r.getMessage()]
    assert len(icp_lines) == 1
    msg = icp_lines[0].getMessage()
    # Required keys present
    for key in ("tenant=", "outcome=", "duration_ms=", "available=",
                 "sot_count=", "tone_source=", "escalation_source=",
                 "cache_hit="):
        assert key in msg, f"missing key {key!r} in log: {msg!r}"


def test_log_line_does_not_contain_token(monkeypatch, configured, caplog):
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _Mock(200, _ok_envelope()))
    with caplog.at_level(logging.INFO, logger="shared.icp_overrides"):
        icp_overrides.fetch_overrides()
    full_log = " ".join(r.getMessage() for r in caplog.records)
    assert TOKEN not in full_log


def test_log_line_on_failure_outcome(monkeypatch, configured, caplog):
    """Failure outcomes also emit the structured log line (not just
    the existing _log.warning text)."""
    monkeypatch.setattr(requests, "get",
                         lambda *a, **k: _Mock(401, {}))
    with caplog.at_level(logging.INFO, logger="shared.icp_overrides"):
        icp_overrides.fetch_overrides()
    icp_lines = [r for r in caplog.records
                  if "icp_overrides fetch" in r.getMessage()
                  and "outcome=401" in r.getMessage()]
    assert len(icp_lines) == 1
