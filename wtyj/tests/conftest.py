"""Shared test configuration — adds bluemarlin/ root to sys.path
and points config_loader at the BlueMarlin client config for dev tests.
"""
import sys
import os

import pytest

# Add bluemarlin/ (parent of tests/) to sys.path so package imports work
_BM_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BM_ROOT)

# Brief 150 — BlueMarlin's client.json moved from bluemarlin/config/ to
# clients/bluemarlin/config/. Tests that use config_loader need to find it.
# Set CLIENT_CONFIG_PATH BEFORE any test module imports config_loader.
_REPO_ROOT = os.path.dirname(_BM_ROOT)
_BM_CLIENT_CONFIG = os.path.join(_REPO_ROOT, "clients", "bluemarlin", "config", "client.json")
if os.path.exists(_BM_CLIENT_CONFIG) and "CLIENT_CONFIG_PATH" not in os.environ:
    os.environ["CLIENT_CONFIG_PATH"] = _BM_CLIENT_CONFIG


@pytest.fixture(autouse=True)
def _bypass_tenant_guard_in_tests():
    """Brief 238 — strip channel_account_allowlist from the cached test
    config for the duration of each test, so existing tests bypass the
    inbound/outbound tenant guard via its block-absent path.

    Note: get_raw() returns dict(_load()) — a shallow copy — so we have
    to pop from config_loader._cache directly. The Brief 238 tests inject
    their own allowlist by patching shared.config_loader.get_raw, which
    overrides this strip at the function-call level (the patched function
    returns their fake_cfg directly without going through _cache).

    Many older tests mutate config_loader._cache directly. Reset the path
    and cache before/after every test so one test's temporary tenant config
    cannot leak into unrelated BlueMarlin prompt/config assertions.
    """
    from shared import config_loader
    if os.path.exists(_BM_CLIENT_CONFIG):
        config_loader._CONFIG_PATH = _BM_CLIENT_CONFIG
        os.environ["CLIENT_CONFIG_PATH"] = _BM_CLIENT_CONFIG
    config_loader._cache = {}
    config_loader._load()  # ensure cache populated
    if "channel_account_allowlist" in config_loader._cache:
        config_loader._cache.pop("channel_account_allowlist")
        try:
            yield
        finally:
            config_loader._CONFIG_PATH = _BM_CLIENT_CONFIG
            os.environ["CLIENT_CONFIG_PATH"] = _BM_CLIENT_CONFIG
            config_loader._cache = {}
    else:
        try:
            yield
        finally:
            config_loader._CONFIG_PATH = _BM_CLIENT_CONFIG
            os.environ["CLIENT_CONFIG_PATH"] = _BM_CLIENT_CONFIG
            config_loader._cache = {}


@pytest.fixture(autouse=True)
def _enable_runtime_controls_for_existing_unit_scenarios(monkeypatch, request):
    """Keep legacy unit scenarios explicit about their normal running state.

    Production now fails closed when Nr 3 cannot supply channel controls. The
    pre-existing tests exercise unrelated booking and conversation behavior
    without an Nr 3 server, so they run with both controls enabled. Dedicated
    bridge/hardening tests are excluded and assert the production defaults.
    """
    if request.node.path.name in {
        "test_icp_overrides.py",
        "test_mermaid_runtime_hardening.py",
    }:
        yield
        return
    from shared import icp_overrides
    production_auto_reply_enabled = icp_overrides.auto_reply_enabled
    production_whatsapp_inbox_enabled = icp_overrides.whatsapp_inbox_enabled
    monkeypatch.setattr(
        icp_overrides,
        "auto_reply_enabled",
        lambda envelope=None: (
            production_auto_reply_enabled(envelope)
            if isinstance(envelope, dict)
            else True
        ),
    )
    monkeypatch.setattr(
        icp_overrides,
        "whatsapp_inbox_enabled",
        lambda envelope=None: (
            production_whatsapp_inbox_enabled(envelope)
            if isinstance(envelope, dict)
            else True
        ),
    )
    yield
