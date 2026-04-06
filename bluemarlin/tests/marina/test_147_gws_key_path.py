"""
Brief 147 — gws hardcoded calendar key path regression tests.

Guards against:
1. Future renames of the key file breaking gws_calendar / format_sheets /
   sheets_writer (use env var with new-name default, not hardcoded path).
2. The specific bug shape from the Brief 145 rename: `_run_gws` / `_append`
   overwriting the env var with the module-level constant, defeating
   docker-compose's environment block.

Module reload teardown: every test that reloads a module under test also
reloads it again in a finalizer to restore the natural (unmonkeypatched)
state, so test order doesn't leak sentinel paths into other test files.
"""
import importlib
import os

import pytest

ENV_VAR = "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"


def _reload(module_name):
    """Reload a module by name, returning the reloaded module object."""
    import sys
    mod = sys.modules.get(module_name)
    if mod is None:
        mod = importlib.import_module(module_name)
    return importlib.reload(mod)


@pytest.fixture
def reload_gws_calendar(request, monkeypatch):
    """Reload gws_calendar after each test to restore natural state."""
    def finalize():
        # After monkeypatch undoes the env var, reload once more so the
        # module's constants are re-derived from the real environment.
        _reload("agents.marina.gws_calendar")
    request.addfinalizer(finalize)
    return monkeypatch


@pytest.fixture
def reload_format_sheets(request, monkeypatch):
    def finalize():
        _reload("agents.marina.format_sheets")
    request.addfinalizer(finalize)
    return monkeypatch


@pytest.fixture
def reload_sheets_writer(request, monkeypatch):
    def finalize():
        _reload("agents.marina.sheets_writer")
    request.addfinalizer(finalize)
    return monkeypatch


# ---------------------------------------------------------------------------
# Module constant tests — env var respected + new-name default
# ---------------------------------------------------------------------------

def test_gws_calendar_uses_env_var_when_set(reload_gws_calendar):
    reload_gws_calendar.setenv(ENV_VAR, "/tmp/sentinel-gws.json")
    mod = _reload("agents.marina.gws_calendar")
    assert mod._KEY_PATH == "/tmp/sentinel-gws.json"


def test_gws_calendar_uses_new_filename_default_when_env_var_unset(reload_gws_calendar):
    reload_gws_calendar.delenv(ENV_VAR, raising=False)
    mod = _reload("agents.marina.gws_calendar")
    assert mod._KEY_PATH.endswith("calendar-key.json")
    assert "bluemarlin-calendar-key.json" not in mod._KEY_PATH


def test_format_sheets_uses_env_var_when_set(reload_format_sheets):
    reload_format_sheets.setenv(ENV_VAR, "/tmp/sentinel-fmt.json")
    mod = _reload("agents.marina.format_sheets")
    assert mod.KEY_PATH == "/tmp/sentinel-fmt.json"


def test_format_sheets_uses_new_filename_default(reload_format_sheets):
    reload_format_sheets.delenv(ENV_VAR, raising=False)
    mod = _reload("agents.marina.format_sheets")
    assert mod.KEY_PATH.endswith("calendar-key.json")
    assert "bluemarlin-calendar-key.json" not in mod.KEY_PATH


def test_sheets_writer_uses_env_var_when_set(reload_sheets_writer):
    reload_sheets_writer.setenv(ENV_VAR, "/tmp/sentinel-sheets.json")
    mod = _reload("agents.marina.sheets_writer")
    assert mod.KEY_PATH == "/tmp/sentinel-sheets.json"


def test_sheets_writer_uses_new_filename_default(reload_sheets_writer):
    reload_sheets_writer.delenv(ENV_VAR, raising=False)
    mod = _reload("agents.marina.sheets_writer")
    assert mod.KEY_PATH.endswith("calendar-key.json")
    assert "bluemarlin-calendar-key.json" not in mod.KEY_PATH


# ---------------------------------------------------------------------------
# Regression tests — _run_gws / _append must NOT clobber env var
# ---------------------------------------------------------------------------

class _SubprocessResult:
    returncode = 0
    stdout = "{}"
    stderr = ""


def test_run_gws_does_not_clobber_env_var(reload_gws_calendar):
    """The bug that was live for 24h: _run_gws overwrote the env var with
    the module-level _KEY_PATH (which held the stale old filename). Now
    _KEY_PATH IS the env var value, so overwriting it with itself is a no-op
    in the normal case. If someone ever reverts the fix, this test catches it."""
    reload_gws_calendar.setenv(ENV_VAR, "/tmp/sentinel-from-compose.json")
    mod = _reload("agents.marina.gws_calendar")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env", {})
        return _SubprocessResult()

    reload_gws_calendar.setattr(mod.subprocess, "run", fake_run)
    result = mod._run_gws(["stub-command"])

    assert "error" not in result
    assert ENV_VAR in captured["env"]
    assert captured["env"][ENV_VAR] == "/tmp/sentinel-from-compose.json", \
        f"env var was clobbered to {captured['env'][ENV_VAR]!r} instead of the compose value"


def test_sheets_writer_append_does_not_clobber_env_var(reload_sheets_writer):
    reload_sheets_writer.setenv(ENV_VAR, "/tmp/sentinel-from-compose.json")
    mod = _reload("agents.marina.sheets_writer")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env", {})
        return _SubprocessResult()

    reload_sheets_writer.setattr(mod.subprocess, "run", fake_run)
    mod._append("Test", ["row"])

    assert ENV_VAR in captured["env"]
    assert captured["env"][ENV_VAR] == "/tmp/sentinel-from-compose.json", \
        f"env var was clobbered to {captured['env'][ENV_VAR]!r} instead of the compose value"


# ---------------------------------------------------------------------------
# Source text scan — old filename must not reappear in any of the 3 files
# ---------------------------------------------------------------------------

def test_old_filename_not_referenced_in_source():
    """Regression guard: no source file should ever hardcode the pre-Brief-145
    filename `bluemarlin-calendar-key.json` again. The new path comes from the
    env var with a `calendar-key.json` fallback."""
    import agents.marina.gws_calendar as gws
    import agents.marina.format_sheets as fmt
    import agents.marina.sheets_writer as sw

    for mod in (gws, fmt, sw):
        path = mod.__file__
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "bluemarlin-calendar-key.json" not in content, \
            f"{path} still references the old filename"
